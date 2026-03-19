"""Entry point — configures logging, registers Telegram handlers, starts polling."""
import logging
import logging.handlers
import os
import sys
from functools import wraps

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from config import (
    ALLOWED_USER_IDS,
    LOG_LEVEL,
    TELEGRAM_BOT_TOKEN,
)
from database import init_db
from file_manager import ensure_dirs
from handlers.callback_handler import handle_callback
from handlers.command_handler import (
    cmd_backup,
    cmd_cancel,
    cmd_help,
    cmd_history,
    cmd_language,
    cmd_model,
    cmd_start,
    cmd_stats,
)
from handlers.message_handler import (
    handle_document,
    handle_forward,
    handle_photo,
    handle_text,
    handle_voice,
)

# ─── Logging ──────────────────────────────────────────────────────────────────

os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.handlers.RotatingFileHandler(
            "logs/bot.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        ),
    ],
)
# Suppress httpx INFO logs — they contain the bot token in the URL path
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


# ─── Authorization ────────────────────────────────────────────────────────────

def authorized(func):
    """Decorator: only allow authorized users."""
    @wraps(func)
    async def wrapper(update: Update, *args, **kwargs):
        user = update.effective_user
        if not user:
            return
        if ALLOWED_USER_IDS and user.id not in ALLOWED_USER_IDS:
            logger.warning("Access denied: user_id=%d (@%s)", user.id, user.username)
            if update.message:
                await update.message.reply_text("⛔ У вас нет доступа к этому боту.")
            elif update.callback_query:
                await update.callback_query.answer("⛔ Доступ запрещён.", show_alert=True)
            return
        return await func(update, *args, **kwargs)
    return wrapper


# ─── Authorized wrappers ──────────────────────────────────────────────────────

@authorized
async def _cmd_start(update, context): await cmd_start(update, context)

@authorized
async def _cmd_help(update, context): await cmd_help(update, context)

@authorized
async def _cmd_history(update, context): await cmd_history(update, context)

@authorized
async def _cmd_stats(update, context): await cmd_stats(update, context)

@authorized
async def _cmd_cancel(update, context): await cmd_cancel(update, context)

@authorized
async def _cmd_backup(update, context): await cmd_backup(update, context)

@authorized
async def _cmd_language(update, context): await cmd_language(update, context)

@authorized
async def _cmd_model(update, context): await cmd_model(update, context)

@authorized
async def _handle_text(update, context): await handle_text(update, context)

@authorized
async def _handle_photo(update, context): await handle_photo(update, context)

@authorized
async def _handle_document(update, context): await handle_document(update, context)

@authorized
async def _handle_voice(update, context): await handle_voice(update, context)

@authorized
async def _handle_callback(update, context): await handle_callback(update, context)


async def _handle_forward(update, context):
    """Forwarded messages — check auth and dispatch."""
    @authorized
    async def inner(u, c): await handle_forward(u, c)
    await inner(update, context)


# ─── Entry point ──────────────────────────────────────────────────────────────

def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.critical("TELEGRAM_BOT_TOKEN not set in .env")
        sys.exit(1)

    if not ALLOWED_USER_IDS:
        sys.exit("FATAL: ALLOWED_USER_IDS must be set in .env")

    # Initialize DB and directories
    init_db()
    ensure_dirs()

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", _cmd_start))
    app.add_handler(CommandHandler("help", _cmd_help))
    app.add_handler(CommandHandler("history", _cmd_history))
    app.add_handler(CommandHandler("stats", _cmd_stats))
    app.add_handler(CommandHandler("cancel", _cmd_cancel))
    app.add_handler(CommandHandler("backup", _cmd_backup))
    app.add_handler(CommandHandler("language", _cmd_language))
    app.add_handler(CommandHandler("model", _cmd_model))

    # Callback (inline buttons)
    app.add_handler(CallbackQueryHandler(_handle_callback))

    # Media
    app.add_handler(MessageHandler(filters.PHOTO, _handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, _handle_document))
    app.add_handler(MessageHandler(filters.VOICE, _handle_voice))

    # Forwarded messages
    app.add_handler(MessageHandler(filters.FORWARDED, _handle_forward))

    # Text (last — don't intercept commands)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _handle_text))

    # Global error handler — prevents silent update drops on unhandled exceptions
    async def _error_handler(update, context):
        from telegram.error import RetryAfter, TimedOut, NetworkError
        import asyncio as _asyncio
        if isinstance(context.error, RetryAfter):
            await _asyncio.sleep(context.error.retry_after)
            return
        if isinstance(context.error, (TimedOut, NetworkError)):
            return  # transient network issue — no user message needed
        logger.exception("Unhandled exception for update %s", update, exc_info=context.error)
        if update and update.effective_message:
            try:
                await update.effective_message.reply_text("❌ Внутренняя ошибка. Попробуйте ещё раз.")
            except Exception:
                pass

    app.add_error_handler(_error_handler)

    logger.info("Bot started. Authorized users: %s", ALLOWED_USER_IDS)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
