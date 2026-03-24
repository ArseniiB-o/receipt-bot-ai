"""Inline keyboard callback handler — batch save/cancel/edit, language, history, stats.

Fixes applied:
  BUG-05  Stale batch guard — every callback that fetches a batch checks for
          expiry and responds gracefully if the session is gone.
  BUG-09  User-selected model validated against AVAILABLE_MODEL_IDS before use.

New features:
  Privacy consent callback (privacy:accept).
  Block/unblock user confirmation callbacks.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, date
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

import database
import file_manager
import sheets_handler
from ai_processor import AVAILABLE_MODELS, AVAILABLE_MODEL_IDS
from constants import PRIVACY_NOTICE_VERSION
from handlers.i18n import month_name, t
from models import Receipt
from utils import category_emoji, format_currency, escape_html
from handlers.message_handler import (
    get_batch_key,
    refresh_batch_message,
    _build_batch_text_and_keyboard,
    STATE_AWAITING,
    STATE_SAVING,
    STATE_IDLE,
    _get_user_lock,
    _get_user_state,
    _reset_user_state,
)

logger = logging.getLogger(__name__)

EDIT_FIELDS = {
    "type": "field_type",
    "store": "field_store",
    "total_amount": "field_amount",
    "receipt_date": "field_date",
    "category": "field_category",
    "currency": "field_currency",
}


def _batch_edit_menu_keyboard(batch_key: str, index: int, user_id: int) -> InlineKeyboardMarkup:
    buttons = []
    for field, label_key in EDIT_FIELDS.items():
        buttons.append([InlineKeyboardButton(
            t(user_id, label_key),
            callback_data=f"batch_edit_field:{batch_key}:{index}:{field}",
        )])
    buttons.append([InlineKeyboardButton(
        t(user_id, "back_to_list"),
        callback_data=f"batch_back:{batch_key}",
    )])
    return InlineKeyboardMarkup(buttons)


# ─── BUG-05: stale batch helper ───────────────────────────────────────────────


async def _require_batch(
    context: ContextTypes.DEFAULT_TYPE,
    batch_key: str,
    query,
    user_id: int,
) -> Optional[dict]:
    """Return the batch dict, or respond to the user and return None if stale."""
    batch = context.bot_data.get(batch_key)
    if not batch:
        try:
            await query.edit_message_text(t(user_id, "session_expired"))
        except Exception:
            pass
        return None
    return batch


# ─── Save one receipt ─────────────────────────────────────────────────────────


async def _do_save_one(
    context: ContextTypes.DEFAULT_TYPE,
    receipt: Receipt,
    temp_paths: list[str],
) -> tuple[bool, str, bool]:
    """Save one receipt. Returns (ok, receipt_number, sheets_ok)."""
    now = receipt.receipt_date or date.today()
    receipt.file_paths = []
    try:
        receipt_number, _ = database.save_receipt_atomic(receipt, now.year, now.month)
    except Exception as e:
        logger.error("SQLite error saving receipt: %s", e)
        file_manager.cleanup_temp_paths(temp_paths)
        return False, receipt.receipt_number or "?", False

    saved_paths: list[str] = []
    for i, tp in enumerate(temp_paths):
        try:
            dest = await file_manager.save_receipt_file(
                temp_path=tp,
                receipt_number=receipt_number,
                receipt_type=receipt.type,
                store=receipt.store,
                year=now.year,
                month=now.month,
                index=i,
            )
            saved_paths.append(dest)
        except Exception as e:
            logger.error("File save error: %s", e)
            file_manager.delete_temp_file(tp)

    if saved_paths:
        receipt.file_paths = saved_paths
        try:
            database.update_file_paths(receipt_number, saved_paths)
        except Exception as e:
            logger.warning("Could not update file paths: %s", e)

    try:
        sheets_ok = await asyncio.wait_for(
            sheets_handler.write_to_sheets(receipt), timeout=60.0
        )
    except asyncio.TimeoutError:
        logger.error("Google Sheets write timed out for %s", receipt.receipt_number)
        sheets_ok = False

    return True, receipt_number, sheets_ok


# ─── Batch operations ─────────────────────────────────────────────────────────


async def _batch_save_all(update, context, query, batch_key: str) -> None:
    user_id = update.effective_user.id
    batch = await _require_batch(context, batch_key, query, user_id)
    if not batch:
        return

    receipts = batch["receipts"]
    cancelled = batch["cancelled"]
    all_temp_paths = batch["all_temp_paths"]

    await query.edit_message_text(t(user_id, "saving_all"))

    # Update state machine
    lock = _get_user_lock(context, user_id)
    async with lock:
        qs = _get_user_state(context, user_id)
        qs.state = STATE_SAVING

    results = []
    for i, receipt in enumerate(receipts):
        if i in cancelled or receipt is None:
            continue
        temp_paths = all_temp_paths[i] if i < len(all_temp_paths) else []
        ok, num, sheets_ok = await _do_save_one(context, receipt, temp_paths)
        results.append((ok, num, sheets_ok, i + 1))

    context.bot_data.pop(batch_key, None)

    # Reset state machine to IDLE
    async with lock:
        _reset_user_state(context, user_id)

    lines = [t(user_id, "saved_header")]
    for ok, num, sheets_ok, idx in results:
        if ok:
            lines.append(f"✅ {num}" + ("" if sheets_ok else " ⚠️"))
        else:
            lines.append(t(user_id, "save_error", n=idx))

    if any(ok and not sheets_ok for ok, _, sheets_ok, _ in results):
        lines.append(t(user_id, "sheets_warning"))

    await query.edit_message_text("\n".join(lines), parse_mode="HTML")


async def _batch_cancel_one(update, context, query, batch_key: str, index: int) -> None:
    batch = context.bot_data.get(batch_key)
    if not batch:
        return
    batch["cancelled"].add(index)
    paths = batch["all_temp_paths"][index] if index < len(batch["all_temp_paths"]) else []
    file_manager.cleanup_temp_paths(paths if isinstance(paths, list) else [paths])

    batch["_key"] = batch_key
    text, keyboard = _build_batch_text_and_keyboard(batch)
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)


async def _batch_cancel_all(update, context, query, batch_key: str) -> None:
    user_id = update.effective_user.id
    batch = context.bot_data.pop(batch_key, {})
    for paths in batch.get("all_temp_paths", []):
        file_manager.cleanup_temp_paths(paths if isinstance(paths, list) else [paths])

    lock = _get_user_lock(context, user_id)
    async with lock:
        _reset_user_state(context, user_id)

    await query.edit_message_text(t(user_id, "all_cancelled"))


async def _batch_show_edit_menu(update, context, query, batch_key: str, index: int) -> None:
    user_id = update.effective_user.id
    batch = await _require_batch(context, batch_key, query, user_id)
    if not batch:
        return
    receipt: Optional[Receipt] = batch["receipts"][index] if index < len(batch["receipts"]) else None
    if receipt is None:
        return
    text = (
        t(user_id, "editing_receipt", n=index + 1)
        + receipt.to_card_text()
        + t(user_id, "choose_field")
    )
    await query.edit_message_text(
        text,
        reply_markup=_batch_edit_menu_keyboard(batch_key, index, user_id),
    )


async def _batch_select_edit_field(
    update, context, query, batch_key: str, index: int, field: str
) -> None:
    user_id = update.effective_user.id
    batch = await _require_batch(context, batch_key, query, user_id)
    if not batch:
        return
    receipt: Optional[Receipt] = batch["receipts"][index] if index < len(batch["receipts"]) else None
    current_val = getattr(receipt, field, "—") if receipt else "—"
    label = t(user_id, EDIT_FIELDS.get(field, field))

    context.user_data["edit_state"] = {
        "mode": "batch",
        "batch_key": batch_key,
        "index": index,
        "field": field,
        "msg_id": query.message.message_id,
        "chat_id": update.effective_chat.id,
    }
    await query.edit_message_text(
        t(user_id, "edit_field_prompt", label=label, current=current_val)
    )


# ─── Main callback dispatcher ─────────────────────────────────────────────────


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    data = query.data or ""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    # ── Privacy consent ───────────────────────────────────────────────────────
    if data == "privacy:accept":
        database.set_privacy_accepted(user_id, PRIVACY_NOTICE_VERSION)
        await query.edit_message_text(t(user_id, "privacy_accepted"))
        await context.bot.send_message(chat_id=chat_id, text=t(user_id, "privacy_accepted_resend"))
        return

    # ── Model selection (BUG-09: validate against AVAILABLE_MODEL_IDS) ────────
    if data.startswith("model:"):
        model_value = data[6:]
        if model_value == "auto":
            database.set_user_model(user_id, None)
            display = t(user_id, "model_auto")
        elif model_value in AVAILABLE_MODEL_IDS:
            database.set_user_model(user_id, model_value)
            display = next(name for mid, name in AVAILABLE_MODELS if mid == model_value)
        else:
            await query.answer(t(user_id, "invalid_model"), show_alert=True)
            return
        await query.edit_message_text(t(user_id, "model_set", model=display))
        return

    # ── Language selection ────────────────────────────────────────────────────
    if data.startswith("lang:"):
        lang = data[5:]
        if lang in ("ru", "de", "en"):
            database.set_user_language(user_id, lang)
            await query.edit_message_text(t(user_id, "language_set"))
            await context.bot.send_message(chat_id=chat_id, text=t(user_id, "start_text"))
        return

    # ── Batch: save all ───────────────────────────────────────────────────────
    if data.startswith("batch_save:"):
        batch_key = data[len("batch_save:"):]
        await _batch_save_all(update, context, query, batch_key)

    # ── Batch: cancel one ─────────────────────────────────────────────────────
    elif data.startswith("batch_cancel:") and not data.startswith("batch_cancel_all:"):
        rest = data[len("batch_cancel:"):]
        parts = rest.rsplit(":", 1)
        if len(parts) == 2:
            batch_key, index_str = parts[0], parts[1]
            try:
                await _batch_cancel_one(update, context, query, batch_key, int(index_str))
            except (ValueError, IndexError):
                pass

    # ── Batch: cancel all ─────────────────────────────────────────────────────
    elif data.startswith("batch_cancel_all:"):
        batch_key = data[len("batch_cancel_all:"):]
        await _batch_cancel_all(update, context, query, batch_key)

    # ── Batch: edit field menu ────────────────────────────────────────────────
    elif data.startswith("batch_edit_field:"):
        rest = data[len("batch_edit_field:"):]
        parts = rest.rsplit(":", 2)
        if len(parts) == 3:
            batch_key, index_str, field = parts[0], parts[1], parts[2]
            if field not in EDIT_FIELDS:
                await query.answer(t(user_id, "invalid_field"), show_alert=True)
                return
            try:
                await _batch_select_edit_field(update, context, query, batch_key, int(index_str), field)
            except ValueError:
                pass

    elif data.startswith("batch_edit:"):
        rest = data[len("batch_edit:"):]
        parts = rest.rsplit(":", 1)
        if len(parts) == 2:
            batch_key, index_str = parts[0], parts[1]
            try:
                await _batch_show_edit_menu(update, context, query, batch_key, int(index_str))
            except ValueError:
                pass

    # ── Batch: back to list ───────────────────────────────────────────────────
    elif data.startswith("batch_back:"):
        batch_key = data[len("batch_back:"):]
        batch = context.bot_data.get(batch_key)
        if not batch:
            await query.edit_message_text(t(user_id, "session_expired_short"))
            return
        batch["_key"] = batch_key
        text, keyboard = _build_batch_text_and_keyboard(batch)
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)

    # ── Confirm cancel last receipt (/cancel) ─────────────────────────────────
    elif data.startswith("do_cancel:"):
        receipt_number = data.split(":", 1)[1]
        rec = database.get_receipt_by_number(receipt_number)
        if rec:
            try:
                paths = json.loads(rec.get("file_paths") or "[]")
                file_manager.delete_receipt_files(paths)
            except Exception:
                pass
            database.delete_receipt(receipt_number)
            await query.edit_message_text(
                t(user_id, "receipt_deleted", number=receipt_number)
            )
        else:
            await query.edit_message_text(t(user_id, "receipt_not_found"))

    elif data == "cancel_dialog":
        await query.edit_message_text(t(user_id, "cancel_undone"))

    # ── History filter ────────────────────────────────────────────────────────
    elif data.startswith("history:"):
        parts = data.split(":")
        filter_type = parts[1] if len(parts) > 1 else "all"
        limit = int(parts[2]) if len(parts) > 2 else 10
        offset = int(parts[3]) if len(parts) > 3 else 0
        uid = user_id if filter_type == "mine" else None
        records = database.get_last_receipts(limit=limit, user_id=uid, offset=offset)

        if not records:
            await query.edit_message_text(t(user_id, "no_records"))
            return

        lines = [t(user_id, "last_records", n=len(records))]
        for i, r in enumerate(records, 1):
            type_icon = "💸" if r["type"] == "expense" else "💰"
            date_str = r["receipt_date"] or "—"
            if date_str and len(date_str) == 10:
                date_str = date_str[8:10] + "." + date_str[5:7]
            amount = format_currency(r["total_amount"], r.get("currency", "EUR"))
            store = escape_html(r["store"] or "—")
            lines.append(f"{i}. #{r['receipt_number']} | {date_str} | {type_icon} {store} | {amount}")

        keyboard_rows = [[
            InlineKeyboardButton(t(user_id, "filter_all"), callback_data=f"history:all:{limit}:{offset}"),
            InlineKeyboardButton(t(user_id, "filter_mine"), callback_data=f"history:mine:{limit}:{offset}"),
        ]]
        if offset > 0:
            keyboard_rows.append([
                InlineKeyboardButton("← Prev", callback_data=f"history:{filter_type}:{limit}:{max(0, offset-limit)}")
            ])
        if len(records) == limit:
            keyboard_rows.append([
                InlineKeyboardButton("Next →", callback_data=f"history:{filter_type}:{limit}:{offset+limit}")
            ])

        await query.edit_message_text(
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(keyboard_rows),
            parse_mode="HTML",
        )

    # ── Stats filter ──────────────────────────────────────────────────────────
    elif data.startswith("stats:"):
        parts = data.split(":")
        filter_type = parts[1] if len(parts) > 1 else "all"
        year = int(parts[2]) if len(parts) > 2 else datetime.now().year
        month = int(parts[3]) if len(parts) > 3 else datetime.now().month
        uid = user_id if filter_type == "mine" else None

        stats = database.get_stats(year, month, user_id=uid)
        currency = "EUR"
        lang = database.get_user_language(user_id)
        month_nm = month_name(lang, month)

        lines = [t(user_id, "stats_header", month=month_nm, year=year)]
        lines.append(t(user_id, "expenses_line",
                       amount=format_currency(stats["expense_total"], currency),
                       count=stats["expense_count"]))
        lines.append(t(user_id, "income_line",
                       amount=format_currency(stats["income_total"], currency),
                       count=stats["income_count"]))
        balance = stats["balance"]
        sign = "+" if balance >= 0 else ""
        lines.append(t(user_id, "balance_line", sign=sign, amount=format_currency(balance, currency)))
        if stats["categories"]:
            lines.append(t(user_id, "by_categories"))
            for cat, total in stats["categories"]:
                lines.append(f"{category_emoji(cat)} {cat}: {format_currency(total, currency)}")

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(t(user_id, "filter_all"), callback_data=f"stats:all:{year}:{month}"),
            InlineKeyboardButton(t(user_id, "filter_mine"), callback_data=f"stats:mine:{year}:{month}"),
        ]])
        await query.edit_message_text("\n".join(lines), reply_markup=keyboard)


# ─── Edit input handler ───────────────────────────────────────────────────────


async def handle_edit_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle text input when user is editing a receipt field."""
    edit_state = context.user_data.get("edit_state")
    if not edit_state or edit_state.get("mode") != "batch":
        return

    user_id = update.effective_user.id
    batch_key = edit_state["batch_key"]
    index = edit_state["index"]
    field = edit_state["field"]
    new_value = (update.message.text or "").strip()

    if field not in EDIT_FIELDS:
        context.user_data.pop("edit_state", None)
        return

    batch = context.bot_data.get(batch_key)
    if not batch:
        await update.message.reply_text(t(user_id, "session_expired"))
        context.user_data.pop("edit_state", None)
        return

    receipt: Optional[Receipt] = batch["receipts"][index] if index < len(batch["receipts"]) else None
    if not receipt:
        context.user_data.pop("edit_state", None)
        return

    try:
        if field == "total_amount":
            val = float(new_value.replace(",", ".").replace(" ", ""))
            if val < 0:
                raise ValueError("Amount cannot be negative")
            receipt.total_amount = val
            if receipt.netto is None:
                receipt.netto = val
        elif field == "receipt_date":
            from constants import DATE_MIN_YEAR, DATE_MAX_YEAR
            parts = new_value.split(".")
            if len(parts) == 3:
                parsed_date = date(int(parts[2]), int(parts[1]), int(parts[0]))
                if not (DATE_MIN_YEAR <= parsed_date.year <= DATE_MAX_YEAR):
                    raise ValueError(f"Year must be between {DATE_MIN_YEAR} and {DATE_MAX_YEAR}")
                receipt.receipt_date = parsed_date
            else:
                raise ValueError(t(user_id, "date_format_hint"))
        elif field == "type":
            v = new_value.lower()
            if v in ("expense", "income"):
                receipt.type = v
            else:
                raise ValueError(t(user_id, "type_format_hint"))
        elif field == "category":
            from ai_processor import _VALID_CATEGORIES
            if new_value in _VALID_CATEGORIES:
                receipt.category = new_value
            else:
                valid = ", ".join(sorted(_VALID_CATEGORIES))
                raise ValueError(f"Valid categories: {valid}")
        else:
            setattr(receipt, field, new_value[:500])

        context.user_data.pop("edit_state", None)
        await update.message.reply_text(t(user_id, "updated"))
        await refresh_batch_message(context, batch_key)

    except (ValueError, TypeError) as e:
        await update.message.reply_text(t(user_id, "invalid_format", error=e))
