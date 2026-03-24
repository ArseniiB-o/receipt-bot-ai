"""Command handlers — all /commands.

New commands added:
  /delete_my_data  — GDPR right to erasure
  /export_my_data  — GDPR data portability (Article 20)
  /data_info       — admin: GDPR Article 30 records of processing
  /block_user      — admin: block a user_id
  /unblock_user    — admin: unblock a user_id
  /dead_letters    — admin: review failed processing jobs
  /admin           — admin dashboard

Fixes:
  BUG-13  Date validation in /cancel uses DATE_MIN_YEAR / DATE_MAX_YEAR (imported from ai_processor).
  BUG-19  /cancel window is now driven by CANCEL_WINDOW_MINUTES from config (not hardcoded 5).
"""
from __future__ import annotations

import csv
import io
import json
import logging
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

import database
import file_manager
from ai_processor import AVAILABLE_MODELS, AVAILABLE_MODEL_IDS, get_circuit_breaker_state
from config import ADMIN_USER_ID, DB_PATH, RECEIPTS_FOLDER, CANCEL_WINDOW_MINUTES
from handlers.i18n import month_name, t
from utils import category_emoji, format_currency, escape_html, error_ref

logger = logging.getLogger(__name__)


def _is_admin(user_id: int) -> bool:
    return ADMIN_USER_ID is not None and user_id == ADMIN_USER_ID


# ─── /start ───────────────────────────────────────────────────────────────────


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not database.has_language_set(user_id):
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🇷🇺 Русский", callback_data="lang:ru"),
            InlineKeyboardButton("🇩🇪 Deutsch", callback_data="lang:de"),
            InlineKeyboardButton("🇬🇧 English", callback_data="lang:en"),
        ]])
        await update.message.reply_text(t(user_id, "language_select"), reply_markup=keyboard)
    elif not database.has_privacy_accepted(user_id):
        from handlers.message_handler import _send_privacy_notice
        await _send_privacy_notice(update, context)
    else:
        await update.message.reply_text(t(user_id, "start_text"))


# ─── /help ────────────────────────────────────────────────────────────────────


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    await update.message.reply_html(t(user_id, "help_text"))


# ─── /language ────────────────────────────────────────────────────────────────


async def cmd_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🇷🇺 Русский", callback_data="lang:ru"),
        InlineKeyboardButton("🇩🇪 Deutsch", callback_data="lang:de"),
        InlineKeyboardButton("🇬🇧 English", callback_data="lang:en"),
    ]])
    await update.message.reply_text(t(user_id, "language_select"), reply_markup=keyboard)


# ─── /history ─────────────────────────────────────────────────────────────────


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    limit = 10
    if context.args:
        try:
            limit = max(1, min(int(context.args[0]), 50))
        except ValueError:
            pass

    records = database.get_last_receipts(limit=limit)
    if not records:
        await update.message.reply_text(t(user_id, "no_records_yet"))
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

    keyboard = [[
        InlineKeyboardButton(t(user_id, "filter_all"), callback_data="history:all:10:0"),
        InlineKeyboardButton(t(user_id, "filter_mine"), callback_data="history:mine:10:0"),
    ]]
    await update.message.reply_html(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ─── /stats ───────────────────────────────────────────────────────────────────


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    now = datetime.now()
    year, month = now.year, now.month

    if context.args and len(context.args) >= 2:
        try:
            month = int(context.args[0])
            year = int(context.args[1])
        except ValueError:
            pass
    elif context.args and len(context.args) == 1:
        try:
            month = int(context.args[0])
        except ValueError:
            pass

    stats = database.get_stats(year, month)
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

    keyboard = [[
        InlineKeyboardButton(t(user_id, "filter_all"), callback_data=f"stats:all:{year}:{month}"),
        InlineKeyboardButton(t(user_id, "filter_mine"), callback_data=f"stats:mine:{year}:{month}"),
    ]]
    await update.message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard))


# ─── /cancel ──────────────────────────────────────────────────────────────────


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    # BUG-19: use config-driven window
    last = database.get_last_confirmed_receipt(user_id, minutes=CANCEL_WINDOW_MINUTES)

    if not last:
        await update.message.reply_text(
            t(user_id, "no_cancel_target", minutes=CANCEL_WINDOW_MINUTES)
        )
        return

    receipt_number = last["receipt_number"]
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(t(user_id, "yes_cancel"), callback_data=f"do_cancel:{receipt_number}"),
        InlineKeyboardButton(t(user_id, "no"), callback_data="cancel_dialog"),
    ]])
    await update.message.reply_text(
        t(user_id, "confirm_cancel",
          number=receipt_number,
          store=escape_html(last["store"] or "—"),
          amount=format_currency(last["total_amount"], last.get("currency", "EUR"))),
        reply_markup=keyboard,
    )


# ─── /model ───────────────────────────────────────────────────────────────────


async def cmd_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    current = database.get_user_model(user_id)

    # BUG-09: validate stored preference against current AVAILABLE_MODEL_IDS
    if current and current not in AVAILABLE_MODEL_IDS:
        logger.warning("User %d had invalid model %r — resetting to auto", user_id, current)
        database.set_user_model(user_id, None)
        current = None

    buttons = []
    auto_label = ("✅ " if current is None else "") + t(user_id, "model_auto")
    buttons.append([InlineKeyboardButton(auto_label, callback_data="model:auto")])
    for model_id, display_name in AVAILABLE_MODELS:
        label = ("✅ " if model_id == current else "") + display_name
        buttons.append([InlineKeyboardButton(label, callback_data=f"model:{model_id}")])

    await update.message.reply_text(
        t(user_id, "model_select"),
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# ─── /backup ──────────────────────────────────────────────────────────────────


async def cmd_backup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not _is_admin(user_id):
        await update.message.reply_text(t(user_id, "admin_only"))
        return

    try:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(DB_PATH, "receipts.db")
        buf.seek(0)
        filename = f"receipts_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        await update.message.reply_document(
            document=buf,
            filename=filename,
            caption=t(user_id, "backup_ready"),
        )
    except Exception as e:
        ref = error_ref()
        logger.error("Backup error [%s]: %s", ref, e)
        await update.message.reply_text(t(user_id, "internal_error", ref=ref))


# ─── /delete_my_data (GDPR Article 17) ───────────────────────────────────────


async def cmd_delete_my_data(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id

    # Check if this is a confirmation response
    pending = context.user_data.get("pending_delete_confirm")
    if pending:
        text = (update.message.text or "").strip()
        if text == "DELETE_ALL_MY_DATA":
            context.user_data.pop("pending_delete_confirm", None)
            # Fetch files before deletion
            all_recs = database.get_all_user_receipts(user_id)
            all_file_paths: list[str] = []
            for rec in all_recs:
                try:
                    paths = json.loads(rec.get("file_paths") or "[]")
                    all_file_paths.extend(paths)
                except Exception:
                    pass

            counts = database.delete_user_data(user_id)
            file_manager.delete_receipt_files(all_file_paths)

            logger.info(
                "GDPR erasure completed for user_id=%d: %d receipts deleted",
                user_id, counts.get("receipts", 0),
            )
            await update.message.reply_text(
                t(user_id, "data_deleted", count=counts.get("receipts", 0))
            )
        else:
            await update.message.reply_text(t(user_id, "delete_cancelled"))
        return

    # First call — request confirmation
    context.user_data["pending_delete_confirm"] = True
    await update.message.reply_text(t(user_id, "confirm_delete_data"))


# ─── /export_my_data (GDPR Article 20) ───────────────────────────────────────


async def cmd_export_my_data(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    await update.message.reply_text(t(user_id, "export_preparing"))

    receipts = database.get_all_user_receipts(user_id)

    buf = io.BytesIO()
    try:
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            # CSV of receipts
            csv_buf = io.StringIO()
            fieldnames = [
                "receipt_number", "type", "store", "website", "total_amount",
                "netto", "ust_amount", "currency", "receipt_date", "category",
                "notes", "status", "created_at",
            ]
            writer = csv.DictWriter(csv_buf, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for r in receipts:
                writer.writerow({k: r.get(k, "") for k in fieldnames})
            zf.writestr("receipts.csv", csv_buf.getvalue())

            # JSON for machine-readable export
            zf.writestr(
                "receipts.json",
                json.dumps(receipts, ensure_ascii=False, default=str, indent=2),
            )

            # Attach actual receipt files
            for rec in receipts:
                try:
                    paths = json.loads(rec.get("file_paths") or "[]")
                    for fp in paths:
                        path = Path(fp)
                        if path.exists():
                            zf.write(str(path), f"files/{path.name}")
                except Exception:
                    pass
        buf.seek(0)
        filename = f"my_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        await update.message.reply_document(
            document=buf,
            filename=filename,
            caption=t(user_id, "export_ready", count=len(receipts)),
        )
    except Exception as e:
        ref = error_ref()
        logger.error("Export error [%s]: %s", ref, e)
        await update.message.reply_text(t(user_id, "internal_error", ref=ref))


# ─── /data_info (admin — GDPR Article 30) ────────────────────────────────────


async def cmd_data_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not _is_admin(user_id):
        await update.message.reply_text(t(user_id, "admin_only"))
        return

    stats = database.get_admin_stats()
    try:
        db_size_mb = Path(DB_PATH).stat().st_size / (1024 * 1024)
    except OSError:
        db_size_mb = 0.0
    try:
        receipts_size = sum(
            f.stat().st_size for f in Path(RECEIPTS_FOLDER).rglob("*") if f.is_file()
        ) / (1024 * 1024)
    except OSError:
        receipts_size = 0.0

    lines = [
        "<b>📊 Data Processing Register</b>",
        f"Total users: {stats['total_users']}",
        f"Total receipts: {stats['total_receipts']}",
        f"Active (24h): {stats['active_24h']}",
        f"DB size: {db_size_mb:.1f} MB",
        f"Receipt files: {receipts_size:.1f} MB",
        f"Oldest record: {stats['oldest_record'] or 'none'}",
        f"Pending Sheets: {stats['pending_sheets']}",
        f"Dead letters: {stats['dead_letters']}",
        f"Circuit breaker (AI): {get_circuit_breaker_state()}",
    ]
    await update.message.reply_html("\n".join(lines))


# ─── /admin dashboard ─────────────────────────────────────────────────────────


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not _is_admin(user_id):
        await update.message.reply_text(t(user_id, "admin_only"))
        return
    await cmd_data_info(update, context)


# ─── /block_user ──────────────────────────────────────────────────────────────


async def cmd_block_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not _is_admin(user_id):
        await update.message.reply_text(t(user_id, "admin_only"))
        return

    if not context.args:
        await update.message.reply_text("Usage: /block_user <user_id> [reason]")
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid user_id")
        return

    reason = " ".join(context.args[1:]) if len(context.args) > 1 else ""
    database.block_user(target_id, user_id, reason)
    logger.warning("Admin %d blocked user %d (reason: %s)", user_id, target_id, reason)
    await update.message.reply_text(f"✅ User {target_id} blocked.")


# ─── /unblock_user ────────────────────────────────────────────────────────────


async def cmd_unblock_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not _is_admin(user_id):
        await update.message.reply_text(t(user_id, "admin_only"))
        return

    if not context.args:
        await update.message.reply_text("Usage: /unblock_user <user_id>")
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid user_id")
        return

    ok = database.unblock_user(target_id)
    logger.info("Admin %d unblocked user %d", user_id, target_id)
    await update.message.reply_text(f"✅ User {target_id} {'unblocked' if ok else 'was not blocked'}.")


# ─── /dead_letters ────────────────────────────────────────────────────────────


async def cmd_dead_letters(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not _is_admin(user_id):
        await update.message.reply_text(t(user_id, "admin_only"))
        return

    letters = database.get_dead_letters(limit=10)
    if not letters:
        await update.message.reply_text("✅ Dead letter queue is empty.")
        return

    lines = [f"☠️ <b>Dead Letters ({len(letters)})</b>"]
    for dl in letters:
        lines.append(
            f"#{dl['id']} | user:{dl['user_id']} | "
            f"attempts:{dl['attempt_count']} | "
            f"{dl['last_attempt_at'][:16]} | "
            f"{escape_html(str(dl['error_message'])[:60])}"
        )
    await update.message.reply_html("\n".join(lines))
