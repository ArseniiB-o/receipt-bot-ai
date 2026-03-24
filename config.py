"""Loads and validates all configuration from environment variables / .env file.

Supports reading secrets from files (Docker secrets pattern):
  If FOO_FILE is set, FOO is read from that file path.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from constants import (
    DEFAULT_DATA_RETENTION_DAYS,
    MAX_FILE_SIZE_MB as _DEFAULT_MAX_FILE_MB,
    CANCEL_WINDOW_SECONDS as _DEFAULT_CANCEL_WINDOW,
    BACKUP_CONFIRM_WINDOW as _DEFAULT_BACKUP_WINDOW,
)

load_dotenv()


def _read_secret(key: str) -> str:
    """Read from file if KEY_FILE is set, otherwise read key directly."""
    file_key = f"{key}_FILE"
    file_path = os.getenv(file_key, "").strip()
    if file_path:
        try:
            return Path(file_path).read_text().strip()
        except OSError as exc:
            print(f"FATAL: Cannot read secret file {file_path} for {key}: {exc}", file=sys.stderr)
            sys.exit(1)
    return os.getenv(key, "").strip()


def _require(key: str) -> str:
    val = _read_secret(key)
    if not val:
        print(f"FATAL: {key} not set in .env", file=sys.stderr)
        sys.exit(1)
    return val


def _bool(key: str, default: bool) -> bool:
    return os.getenv(key, "true" if default else "false").lower() in ("1", "true", "yes")


def _int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


# ─── Required ─────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN: str = _require("TELEGRAM_BOT_TOKEN")
OPENROUTER_API_KEY: str = _require("OPENROUTER_API_KEY")

# ─── Optional with defaults ────────────────────────────────────────────────────
OPENROUTER_MODEL: str = os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-nano-12b-v2-vl:free")
GOOGLE_SHEETS_ID: str = os.getenv("GOOGLE_SHEETS_ID", "")
GOOGLE_SERVICE_ACCOUNT_JSON: str = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "./service_account.json")
RECEIPTS_FOLDER: str = os.getenv("RECEIPTS_FOLDER", "./receipts")
DB_PATH: str = os.getenv("DB_PATH", "./receipts.db")
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
CONFIRMATION_REQUIRED: bool = _bool("CONFIRMATION_REQUIRED", True)
REPO_URL: str = os.getenv("REPO_URL", "https://github.com/your-username/receipt-bot")
TEMP_FOLDER: str = "./temp"

# ─── File limits ──────────────────────────────────────────────────────────────
MAX_FILE_SIZE_MB: int = _int("MAX_FILE_SIZE_MB", _DEFAULT_MAX_FILE_MB)

# ─── Cancel window (BUG-19) ───────────────────────────────────────────────────
CANCEL_WINDOW_MINUTES: int = _int("CANCEL_WINDOW_MINUTES", _DEFAULT_CANCEL_WINDOW // 60)

# ─── Backup ───────────────────────────────────────────────────────────────────
BACKUP_CONFIRM_TIMEOUT: int = _int("BACKUP_CONFIRM_TIMEOUT", _DEFAULT_BACKUP_WINDOW)

# ─── Data privacy / GDPR ──────────────────────────────────────────────────────
DATA_RETENTION_DAYS: int = _int("DATA_RETENTION_DAYS", DEFAULT_DATA_RETENTION_DAYS)
STORE_TELEGRAM_USERNAME: bool = _bool("STORE_TELEGRAM_USERNAME", False)
DELETE_IMAGES_AFTER_PROCESSING: bool = _bool("DELETE_IMAGES_AFTER_PROCESSING", False)

# ─── Financial compliance ─────────────────────────────────────────────────────
IMMUTABLE_RECEIPTS: bool = _bool("IMMUTABLE_RECEIPTS", False)

# ─── Performance / profiling ──────────────────────────────────────────────────
ENABLE_MEMORY_PROFILING: bool = _bool("ENABLE_MEMORY_PROFILING", False)

# ─── Allowed users ────────────────────────────────────────────────────────────
_raw_ids: str = os.getenv("ALLOWED_USER_IDS", "")
ALLOWED_USER_IDS: set[int] = set()
if _raw_ids.strip():
    for _id in _raw_ids.split(","):
        _id = _id.strip()
        if _id.isdigit():
            ALLOWED_USER_IDS.add(int(_id))

# Admin user ID — set explicitly in .env
ADMIN_USER_ID: int | None = int(os.getenv("ADMIN_USER_ID", "0")) or None

# ─── Blocked users (runtime, stored in DB — but also loadable from env) ───────
# This set is authoritative at startup; /block_user and /unblock_user mutate it.
BLOCKED_USER_IDS: set[int] = set()

# ─── Sheets month tab names ───────────────────────────────────────────────────
MONTH_SHEET_NAMES: dict[int, str] = {
    1: "Jan", 2: "Feb", 3: "March", 4: "Apr",
    5: "May", 6: "Jun", 7: "Jul", 8: "Aug",
    9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
}
