"""Inline keyboard callback handler — batch save/cancel/edit, language, history, stats."""
import asyncio
import json
import logging
from datetime import datetime, date

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

import database
import file_manager
import sheets_handler
from ai_processor import AVAILABLE_MODELS
from handlers.i18n import month_name, t
from models import Receipt
from utils import category_emoji, format_currency
from handlers.message_handler import get_batch_key, refresh_batch_message

logger = logging.getLogger(__name__)

# Maps field name → i18n key for the label shown in the edit menu
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
            callback_data=f"batch_edit_field:{batch_key}:{index}:{field}"
        )])
    buttons.append([InlineKeyboardButton(
        t(user_id, "back_to_list"),
        callback_data=f"batch_back:{batch_key}"
    )])
    return InlineKeyboardMarkup(buttons)


async def _do_save_one(
    context: ContextTypes.DEFAULT_TYPE,
    receipt: Receipt,
    temp_paths: list,
) -> tuple:
    """Save one receipt. Returns (ok: bool, receipt_number: str, sheets_ok: bool)."""
    now = receipt.receipt_date or date.today()

    # Atomically assign receipt number and save to DB (prevents race condition)
    receipt.file_paths = []
    try:
        receipt_number, _ = database.save_receipt_atomic(receipt, now.year, now.month)
    except Exception as e:
        logger.error("SQLite error: %s", e)
        for tp in temp_paths:
            file_manager.delete_temp_file(tp)
        return False, receipt.receipt_number or "?", False

    # Move files to permanent storage after number is assigned
    saved_paths = []
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

    # Update file paths in DB if any were saved
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


async def _batch_save_all(update, context, query, batch_key: str):
    user_id = update.effective_user.id
    batch = context.bot_data.get(batch_key)
    if not batch:
        await query.edit_message_text(t(user_id, "session_expired"))
        return

    receipts = batch["receipts"]
    cancelled = batch["cancelled"]
    all_temp_paths = batch["all_temp_paths"]

    await query.edit_message_text(t(user_id, "saving_all"))

    results = []
    for i, receipt in enumerate(receipts):
        if i in cancelled or receipt is None:
            continue
        temp_paths = all_temp_paths[i] if i < len(all_temp_paths) else []
        ok, num, sheets_ok = await _do_save_one(context, receipt, temp_paths)
        results.append((ok, num, sheets_ok, i + 1))

    context.bot_data.pop(batch_key, None)

    lines = [t(user_id, "saved_header")]
    for ok, num, sheets_ok, idx in results:
        if ok:
            lines.append(f"✅ {num}" + ("" if sheets_ok else " ⚠️"))
        else:
            lines.append(t(user_id, "save_error", n=idx))

    if any(ok and not sheets_ok for ok, _, sheets_ok, _ in results):
        lines.append(t(user_id, "sheets_warning"))

    await query.edit_message_text("\n".join(lines), parse_mode="HTML")


async def _batch_cancel_one(update, context, query, batch_key: str, index: int):
    batch = context.bot_data.get(batch_key)
    if not batch:
        return
    batch["cancelled"].add(index)

    # Clean up temp files for cancelled item
    paths = batch["all_temp_paths"][index] if index < len(batch["all_temp_paths"]) else []
    for p in paths:
        file_manager.delete_temp_file(p)

    batch["_key"] = batch_key
    from handlers.message_handler import _build_batch_text_and_keyboard
    text, keyboard = _build_batch_text_and_keyboard(batch)
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)


async def _batch_cancel_all(update, context, query, batch_key: str):
    user_id = update.effective_user.id
    batch = context.bot_data.pop(batch_key, {})
    for paths in batch.get("all_temp_paths", []):
        for p in paths:
            file_manager.delete_temp_file(p)
    await query.edit_message_text(t(user_id, "all_cancelled"))


async def _batch_show_edit_menu(update, context, query, batch_key: str, index: int):
    user_id = update.effective_user.id
    batch = context.bot_data.get(batch_key)
    if not batch:
        await query.edit_message_text(t(user_id, "session_expired_short"))
        return
    receipt = batch["receipts"][index]
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


async def _batch_select_edit_field(update, context, query, batch_key: str, index: int, field: str):
    user_id = update.effective_user.id
    batch = context.bot_data.get(batch_key)
    if not batch:
        await query.edit_message_text(t(user_id, "session_expired_short"))
        return
    receipt = batch["receipts"][index]
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


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data or ""
    user = update.effective_user
    user_id = user.id
    chat_id = update.effective_chat.id

    # ── Model selection ───────────────────────────────────────────────────────
    if data.startswith("model:"):
        model_value = data[6:]
        valid_ids = {m[0] for m in AVAILABLE_MODELS}
        if model_value == "auto":
            database.set_user_model(user_id, None)
            display = t(user_id, "model_auto")
        elif model_value in valid_ids:
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
        batch_key = parts[0]
        index = int(parts[1])
        await _batch_cancel_one(update, context, query, batch_key, index)

    # ── Batch: cancel all ─────────────────────────────────────────────────────
    elif data.startswith("batch_cancel_all:"):
        batch_key = data[len("batch_cancel_all:"):]
        await _batch_cancel_all(update, context, query, batch_key)

    # ── Batch: edit field menu ────────────────────────────────────────────────
    elif data.startswith("batch_edit_field:"):
        rest = data[len("batch_edit_field:"):]
        parts = rest.rsplit(":", 2)
        batch_key = parts[0]
        index = int(parts[1])
        field = parts[2]
        if field not in EDIT_FIELDS:
            await query.answer(t(user_id, "invalid_field"), show_alert=True)
            return
        await _batch_select_edit_field(update, context, query, batch_key, index, field)

    elif data.startswith("batch_edit:"):
        rest = data[len("batch_edit:"):]
        parts = rest.rsplit(":", 1)
        batch_key = parts[0]
        index = int(parts[1])
        await _batch_show_edit_menu(update, context, query, batch_key, index)

    # ── Batch: back to list ───────────────────────────────────────────────────
    elif data.startswith("batch_back:"):
        batch_key = data[len("batch_back:"):]
        batch = context.bot_data.get(batch_key)
        if not batch:
            await query.edit_message_text(t(user_id, "session_expired_short"))
            return
        batch["_key"] = batch_key
        from handlers.message_handler import _build_batch_text_and_keyboard
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
        uid = user_id if filter_type == "mine" else None
        records = database.get_last_receipts(limit=limit, user_id=uid)

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
            store = r["store"] or "—"
            added = r["added_by"] or r["telegram_username"] or "—"
            lines.append(
                f"{i}. #{r['receipt_number']} | {date_str} | {type_icon} {store} | {amount} | 👤 {added}"
            )

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(t(user_id, "filter_all"), callback_data="history:all:10"),
            InlineKeyboardButton(t(user_id, "filter_mine"), callback_data="history:mine:10"),
        ]])
        await query.edit_message_text("\n".join(lines), reply_markup=keyboard)

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


async def handle_edit_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text input when user is editing a field of a receipt in a batch."""
    edit_state = context.user_data.get("edit_state")
    if not edit_state:
        return

    if edit_state.get("mode") != "batch":
        return

    user_id = update.effective_user.id
    batch_key = edit_state["batch_key"]
    index = edit_state["index"]
    field = edit_state["field"]
    new_value = update.message.text or ""

    if field not in EDIT_FIELDS:
        context.user_data.pop("edit_state", None)
        return

    batch = context.bot_data.get(batch_key)
    if not batch:
        await update.message.reply_text(t(user_id, "session_expired"))
        context.user_data.pop("edit_state", None)
        return

    receipt: Receipt = batch["receipts"][index]
    if not receipt:
        context.user_data.pop("edit_state", None)
        return

    try:
        if field == "total_amount":
            val = float(new_value.replace(",", ".").replace(" ", ""))
            receipt.total_amount = val
            if receipt.netto is None:
                receipt.netto = val
        elif field == "receipt_date":
            parts = new_value.strip().split(".")
            if len(parts) == 3:
                receipt.receipt_date = date(int(parts[2]), int(parts[1]), int(parts[0]))
            else:
                raise ValueError(t(user_id, "date_format_hint"))
        elif field == "type":
            v = new_value.strip().lower()
            if v in ("expense", "income"):
                receipt.type = v
            else:
                raise ValueError(t(user_id, "type_format_hint"))
        else:
            setattr(receipt, field, new_value.strip())

        context.user_data.pop("edit_state", None)
        await update.message.reply_text(t(user_id, "updated"))
        await refresh_batch_message(context, batch_key)

    except (ValueError, TypeError) as e:
        await update.message.reply_text(t(user_id, "invalid_format", error=e))
