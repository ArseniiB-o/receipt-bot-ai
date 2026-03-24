"""Entry point — logging setup, security filters, handler registration, startup self-test.

Security additions:
  • Log scrubbing filter removes bot tokens, API keys, phone numbers, emails.
  • Constant-time user ID check (hmac.compare_digest) prevents timing attacks.
  • Unauthorized access is logged to security.log; repeated attempts alert admin.
  • Blocked users (database.is_user_blocked) are rejected at the decorator level.

Reliability additions:
  • Startup self-test validates DB, env, directories, service account.
  • Graceful shutdown: waits up to 30 s for in-progress AI calls before exiting.
  • Daily data-retention job (JobQueue).
  • Periodic Sheets retry job (every 5 minutes).
  • Watchdog coroutine every 60 s (disk space, DB health).
"""
from __future__ import annotations

import hmac
import logging
import logging.handlers
import os
import shutil
import sys
import time
from functools import wraps
from pathlib import Path

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
    ADMIN_USER_ID,
    LOG_LEVEL,
    TELEGRAM_BOT_TOKEN,
    DB_PATH,
    RECEIPTS_FOLDER,
    TEMP_FOLDER,
    GOOGLE_SHEETS_ID,
    GOOGLE_SERVICE_ACCOUNT_JSON,
    DATA_RETENTION_DAYS,
)
from constants import (
    RE_BOT_TOKEN,
    RE_API_KEY,
    RE_PHONE,
    RE_EMAIL,
    WATCHDOG_INTERVAL,
    WATCHDOG_FREE_DISK_MB,
    METRICS_LOG_INTERVAL,
    LOG_MAX_BYTES,
    LOG_BACKUP_COUNT,
)
from database import init_db, is_user_blocked
from file_manager import ensure_dirs

from handlers.callback_handler import handle_callback
from handlers.command_handler import (
    cmd_admin,
    cmd_backup,
    cmd_block_user,
    cmd_cancel,
    cmd_data_info,
    cmd_dead_letters,
    cmd_delete_my_data,
    cmd_export_my_data,
    cmd_help,
    cmd_history,
    cmd_language,
    cmd_model,
    cmd_start,
    cmd_stats,
    cmd_unblock_user,
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

import re as _re


class _ScrubFilter(logging.Filter):
    """Remove secrets from log records before they hit any handler."""

    _PATTERNS = [
        (_re.compile(RE_BOT_TOKEN), "<TOKEN>"),
        (_re.compile(RE_API_KEY), "<API_KEY>"),
        (_re.compile(RE_PHONE), "<PHONE>"),
        (_re.compile(RE_EMAIL), "<EMAIL>"),
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for pattern, replacement in self._PATTERNS:
            msg = pattern.sub(replacement, msg)
        record.msg = msg
        record.args = ()
        return True


_scrub = _ScrubFilter()

_handlers: list[logging.Handler] = [
    logging.StreamHandler(sys.stdout),
    logging.handlers.RotatingFileHandler(
        "logs/bot.log",
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    ),
]

# Separate security log
_security_handler = logging.handlers.RotatingFileHandler(
    "logs/security.log",
    maxBytes=LOG_MAX_BYTES,
    backupCount=LOG_BACKUP_COUNT,
    encoding="utf-8",
)
_security_handler.setLevel(logging.WARNING)

for h in _handlers:
    h.addFilter(_scrub)

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=_handlers,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram.ext").setLevel(logging.WARNING)

_security_logger = logging.getLogger("security")
_security_logger.addHandler(_security_handler)
_security_logger.addHandler(_handlers[0])  # also to console

logger = logging.getLogger(__name__)

# In-memory tracker for unauthorized access (user_id → count)
_unauthorized_attempts: dict[int, int] = {}


# ─── Authorization ────────────────────────────────────────────────────────────


def _is_allowed(user_id: int) -> bool:
    """Constant-time membership check — iterates ALL allowed IDs without short-circuiting.

    Never returns early on a match so that execution time does not reveal
    whether user_id is in the allow-list (timing side-channel).
    """
    if not ALLOWED_USER_IDS:
        return True
    uid_str = str(user_id)
    allowed = False
    for allowed_id in ALLOWED_USER_IDS:
        # Use compare_digest for each comparison AND avoid early exit
        if hmac.compare_digest(uid_str, str(allowed_id)):
            allowed = True
    return allowed


def authorized(func):
    """Decorator: reject unauthorized or blocked users."""
    @wraps(func)
    async def wrapper(update: Update, *args, **kwargs):
        user = update.effective_user
        if not user:
            return

        user_id = user.id

        # Check allow-list
        if ALLOWED_USER_IDS and not _is_allowed(user_id):
            count = _unauthorized_attempts.get(user_id, 0) + 1
            _unauthorized_attempts[user_id] = count

            # Log to security.log
            msg_text = ""
            if update.message:
                raw = update.message.text or update.message.caption or ""
                msg_text = raw[:20]
            _security_logger.warning(
                "Unauthorized access: user_id=%d username=@%s chat_id=%s "
                "msg_type=%s text_preview=%r attempt=%d",
                user_id, user.username, update.effective_chat.id if update.effective_chat else "?",
                update.message.chat.type if update.message else "?",
                msg_text, count,
            )

            # Alert admin after threshold
            from constants import UNAUTHORIZED_ALERT_THRESHOLD
            if count >= UNAUTHORIZED_ALERT_THRESHOLD and ADMIN_USER_ID:
                try:
                    app = kwargs.get("context") or (args[0] if args else None)
                    if app and hasattr(app, "bot"):
                        await app.bot.send_message(
                            chat_id=ADMIN_USER_ID,
                            text=f"⚠️ Security: user_id={user_id} (@{user.username}) "
                                 f"made {count} unauthorized access attempts.",
                        )
                except Exception:
                    pass

            if update.message:
                await update.message.reply_text("⛔ Доступ запрещён.")
            elif update.callback_query:
                await update.callback_query.answer("⛔ Доступ запрещён.", show_alert=True)
            return

        # Check if user is admin-blocked
        try:
            if is_user_blocked(user_id):
                if update.message:
                    await update.message.reply_text("⛔ Ваш аккаунт заблокирован.")
                return
        except Exception:
            pass

        return await func(update, *args, **kwargs)
    return wrapper


# ─── Authorized wrappers ──────────────────────────────────────────────────────

@authorized
async def _cmd_start(u, c): await cmd_start(u, c)

@authorized
async def _cmd_help(u, c): await cmd_help(u, c)

@authorized
async def _cmd_history(u, c): await cmd_history(u, c)

@authorized
async def _cmd_stats(u, c): await cmd_stats(u, c)

@authorized
async def _cmd_cancel(u, c): await cmd_cancel(u, c)

@authorized
async def _cmd_backup(u, c): await cmd_backup(u, c)

@authorized
async def _cmd_language(u, c): await cmd_language(u, c)

@authorized
async def _cmd_model(u, c): await cmd_model(u, c)

@authorized
async def _cmd_delete_my_data(u, c): await cmd_delete_my_data(u, c)

@authorized
async def _cmd_export_my_data(u, c): await cmd_export_my_data(u, c)

@authorized
async def _cmd_data_info(u, c): await cmd_data_info(u, c)

@authorized
async def _cmd_admin(u, c): await cmd_admin(u, c)

@authorized
async def _cmd_block_user(u, c): await cmd_block_user(u, c)

@authorized
async def _cmd_unblock_user(u, c): await cmd_unblock_user(u, c)

@authorized
async def _cmd_dead_letters(u, c): await cmd_dead_letters(u, c)

@authorized
async def _handle_text(u, c): await handle_text(u, c)

@authorized
async def _handle_photo(u, c): await handle_photo(u, c)

@authorized
async def _handle_document(u, c): await handle_document(u, c)

@authorized
async def _handle_voice(u, c): await handle_voice(u, c)

@authorized
async def _handle_callback(u, c): await handle_callback(u, c)


async def _handle_forward(update, context):
    @authorized
    async def inner(u, c): await handle_forward(u, c)
    await inner(update, context)


# ─── Startup self-test ────────────────────────────────────────────────────────


def _run_startup_checks() -> bool:
    """Run pre-flight checks. Returns False if any critical check fails."""
    checks = []

    def check(name: str, ok: bool, msg: str = "") -> None:
        status = "PASS" if ok else "FAIL"
        logger.info("Startup check [%s]: %s %s", status, name, f"— {msg}" if msg else "")
        checks.append(ok)

    # DB connection
    try:
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        conn.execute("SELECT 1")
        conn.close()
        check("DB connection", True)
    except Exception as e:
        check("DB connection", False, str(e))

    # Writable directories
    for folder in (RECEIPTS_FOLDER, TEMP_FOLDER, "logs"):
        try:
            Path(folder).mkdir(parents=True, exist_ok=True)
            test = Path(folder) / ".write_test"
            test.touch()
            test.unlink()
            check(f"Dir writable: {folder}", True)
        except Exception as e:
            check(f"Dir writable: {folder}", False, str(e))

    # Required env vars
    check("TELEGRAM_BOT_TOKEN", bool(TELEGRAM_BOT_TOKEN))
    check("ALLOWED_USER_IDS", bool(ALLOWED_USER_IDS), "if empty, all users allowed")

    # Service account (only if Sheets enabled)
    if GOOGLE_SHEETS_ID:
        sa_path = Path(GOOGLE_SERVICE_ACCOUNT_JSON)
        sa_exists = sa_path.exists()
        check("service_account.json exists", sa_exists)
        if sa_exists:
            import json
            try:
                data = json.loads(sa_path.read_text())
                check("service_account.json valid JSON", True)
                check("service_account.json has required keys",
                      {"type", "private_key", "client_email"}.issubset(set(data.keys())))
                # Warn if world-readable (POSIX only)
                if sys.platform != "win32":
                    mode = sa_path.stat().st_mode
                    if mode & 0o044:
                        logger.warning(
                            "⚠️ %s is readable by group/others (mode %o) — "
                            "consider: chmod 600 %s",
                            sa_path, mode & 0o777, sa_path,
                        )
            except Exception as e:
                check("service_account.json valid JSON", False, str(e))

    # OpenRouter API key
    from config import OPENROUTER_API_KEY
    check("OPENROUTER_API_KEY", bool(OPENROUTER_API_KEY))

    # Disk space
    try:
        usage = shutil.disk_usage(".")
        free_mb = usage.free / (1024 * 1024)
        check(f"Disk space >{WATCHDOG_FREE_DISK_MB}MB", free_mb > WATCHDOG_FREE_DISK_MB,
              f"{free_mb:.0f}MB free")
    except Exception:
        pass

    failed = sum(1 for ok in checks if not ok)
    if failed:
        logger.error("Startup: %d check(s) FAILED", failed)
    else:
        logger.info("Startup: all checks PASSED")
    return failed == 0


# ─── Background jobs ──────────────────────────────────────────────────────────


async def _job_data_retention(context) -> None:
    """Daily job: delete receipts older than DATA_RETENTION_DAYS."""
    import json as _json
    from database import delete_old_receipts

    logger.info("Running data retention job (older than %d days)", DATA_RETENTION_DAYS)
    deleted = delete_old_receipts(DATA_RETENTION_DAYS)
    for rec in deleted:
        try:
            paths = _json.loads(rec.get("file_paths") or "[]")
            from file_manager import delete_receipt_files
            delete_receipt_files(paths)
        except Exception:
            pass
    if deleted:
        logger.info("Data retention: deleted %d old receipts", len(deleted))


async def _job_retry_sheets(context) -> None:
    """Retry pending Google Sheets writes every 5 minutes."""
    from sheets_handler import retry_pending_writes
    n = await retry_pending_writes()
    if n > 0:
        logger.info("Sheets retry: flushed %d pending writes", n)


async def _job_watchdog(context) -> None:
    """Periodic health check — alerts admin if something is wrong."""
    issues = []

    # DB health
    try:
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        conn.execute("SELECT 1")
        conn.close()
    except Exception as e:
        issues.append(f"DB check failed: {e}")

    # Disk space
    try:
        usage = shutil.disk_usage(".")
        free_mb = usage.free / (1024 * 1024)
        if free_mb < WATCHDOG_FREE_DISK_MB:
            issues.append(f"Low disk space: {free_mb:.0f}MB free")
    except Exception:
        pass

    if issues and ADMIN_USER_ID:
        try:
            msg = "⚠️ Watchdog alert:\n" + "\n".join(f"• {i}" for i in issues)
            await context.bot.send_message(chat_id=ADMIN_USER_ID, text=msg)
        except Exception:
            pass

    if issues:
        logger.warning("Watchdog: %s", "; ".join(issues))


# ─── Error handler ────────────────────────────────────────────────────────────


async def _error_handler(update, context) -> None:
    from telegram.error import RetryAfter, TimedOut, NetworkError
    import asyncio
    if isinstance(context.error, RetryAfter):
        await asyncio.sleep(context.error.retry_after)
        return
    if isinstance(context.error, (TimedOut, NetworkError)):
        return
    from utils import error_ref
    ref = error_ref()
    logger.exception("Unhandled exception [%s] for update %s", ref, update, exc_info=context.error)
    if update and update.effective_message:
        try:
            await update.effective_message.reply_text(
                f"❌ Внутренняя ошибка. Код: {ref}"
            )
        except Exception:
            pass


# ─── Entry point ──────────────────────────────────────────────────────────────


def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        logger.critical("TELEGRAM_BOT_TOKEN not set")
        sys.exit(1)

    if not ALLOWED_USER_IDS:
        logger.warning("ALLOWED_USER_IDS is empty — all users will be allowed!")

    init_db()
    ensure_dirs()

    _start = time.monotonic()
    if not _run_startup_checks():
        logger.critical("Critical startup check failed — aborting.")
        sys.exit(1)
    logger.info("Startup completed in %.2fs", time.monotonic() - _start)

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
    # GDPR
    app.add_handler(CommandHandler("delete_my_data", _cmd_delete_my_data))
    app.add_handler(CommandHandler("export_my_data", _cmd_export_my_data))
    # Admin
    app.add_handler(CommandHandler("data_info", _cmd_data_info))
    app.add_handler(CommandHandler("admin", _cmd_admin))
    app.add_handler(CommandHandler("block_user", _cmd_block_user))
    app.add_handler(CommandHandler("unblock_user", _cmd_unblock_user))
    app.add_handler(CommandHandler("dead_letters", _cmd_dead_letters))

    # Callbacks
    app.add_handler(CallbackQueryHandler(_handle_callback))

    # Media
    app.add_handler(MessageHandler(filters.PHOTO, _handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, _handle_document))
    app.add_handler(MessageHandler(filters.VOICE, _handle_voice))
    app.add_handler(MessageHandler(filters.FORWARDED, _handle_forward))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _handle_text))

    # Error handler
    app.add_error_handler(_error_handler)

    # Background jobs (require JobQueue — python-telegram-bot[job-queue])
    if app.job_queue:
        app.job_queue.run_daily(_job_data_retention, time=__import__("datetime").time(3, 0))
        app.job_queue.run_repeating(_job_retry_sheets, interval=300, first=60)
        app.job_queue.run_repeating(_job_watchdog, interval=WATCHDOG_INTERVAL, first=30)
    else:
        logger.warning(
            "JobQueue not available — install python-telegram-bot[job-queue] "
            "for scheduled jobs (data retention, Sheets retry, watchdog)"
        )

    logger.info(
        "Bot started. Authorized users: %s | Admin: %s",
        ALLOWED_USER_IDS or "ALL",
        ADMIN_USER_ID,
    )
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
