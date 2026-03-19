"""Command handlers — /start /help /history /stats /cancel /backup /language."""
import io
import logging
import zipfile
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

import database
from ai_processor import AVAILABLE_MODELS
from config import ADMIN_USER_ID, DB_PATH
from handlers.i18n import month_name, t
from utils import category_emoji, format_currency

logger = logging.getLogger(__name__)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not database.has_language_set(user_id):
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🇷🇺 Русский", callback_data="lang:ru"),
            InlineKeyboardButton("🇩🇪 Deutsch", callback_data="lang:de"),
            InlineKeyboardButton("🇬🇧 English", callback_data="lang:en"),
        ]])
        await update.message.reply_text(
            t(user_id, "language_select"),
            reply_markup=keyboard,
        )
    else:
        await update.message.reply_text(t(user_id, "start_text"))


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_html(t(user_id, "help_text"))


async def cmd_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🇷🇺 Русский", callback_data="lang:ru"),
        InlineKeyboardButton("🇩🇪 Deutsch", callback_data="lang:de"),
        InlineKeyboardButton("🇬🇧 English", callback_data="lang:en"),
    ]])
    await update.message.reply_text(
        t(user_id, "language_select"),
        reply_markup=keyboard,
    )


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    limit = 10
    if args:
        try:
            limit = max(1, min(int(args[0]), 50))
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
        store = r["store"] or "—"
        added = r["added_by"] or r["telegram_username"] or "—"
        lines.append(
            f"{i}. #{r['receipt_number']} | {date_str} | {type_icon} {store} | {amount} | 👤 {added}"
        )

    keyboard = [[
        InlineKeyboardButton(t(user_id, "filter_all"), callback_data="history:all:10"),
        InlineKeyboardButton(t(user_id, "filter_mine"), callback_data="history:mine:10"),
    ]]

    await update.message.reply_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    now = datetime.now()
    year, month = now.year, now.month

    args = context.args
    if len(args) >= 2:
        try:
            month = int(args[0])
            year = int(args[1])
        except ValueError:
            pass
    elif len(args) == 1:
        try:
            month = int(args[0])
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

    await update.message.reply_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    last = database.get_last_confirmed_receipt(user_id, minutes=5)

    if not last:
        await update.message.reply_text(t(user_id, "no_cancel_target"))
        return

    receipt_number = last["receipt_number"]
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(t(user_id, "yes_cancel"), callback_data=f"do_cancel:{receipt_number}"),
        InlineKeyboardButton(t(user_id, "no"), callback_data="cancel_dialog"),
    ]])
    await update.message.reply_text(
        t(user_id, "confirm_cancel",
          number=receipt_number,
          store=last["store"] or "—",
          amount=format_currency(last["total_amount"], last.get("currency", "EUR"))),
        reply_markup=keyboard,
    )


async def cmd_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    current = database.get_user_model(user_id)

    buttons = []
    # "Auto" option — uses MODEL_POOL round-robin
    auto_label = ("✅ " if current is None else "") + t(user_id, "model_auto")
    buttons.append([InlineKeyboardButton(auto_label, callback_data="model:auto")])
    # Each available model
    for model_id, display_name in AVAILABLE_MODELS:
        label = ("✅ " if model_id == current else "") + display_name
        buttons.append([InlineKeyboardButton(label, callback_data=f"model:{model_id}")])

    await update.message.reply_text(
        t(user_id, "model_select"),
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def cmd_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if ADMIN_USER_ID and user_id != ADMIN_USER_ID:
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
        logger.error("Backup error: %s", e)
        await update.message.reply_text(t(user_id, "error", error=e))
