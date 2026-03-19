"""Loads and validates all configuration from environment variables / .env file."""
import os
import sys
from dotenv import load_dotenv

load_dotenv()

def _require(key: str) -> str:
    val = os.getenv(key, "").strip()
    if not val:
        print(f"FATAL: {key} not set in .env", file=sys.stderr)
        sys.exit(1)
    return val

TELEGRAM_BOT_TOKEN = _require("TELEGRAM_BOT_TOKEN")
OPENROUTER_API_KEY = _require("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-nano-12b-v2-vl:free")
GOOGLE_SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID", "")
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "./service_account.json")
RECEIPTS_FOLDER = os.getenv("RECEIPTS_FOLDER", "./receipts")
DB_PATH = os.getenv("DB_PATH", "./receipts.db")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
CONFIRMATION_REQUIRED = os.getenv("CONFIRMATION_REQUIRED", "true").lower() == "true"
REPO_URL = os.getenv("REPO_URL", "https://github.com/your-username/receipt-bot")

_raw_ids = os.getenv("ALLOWED_USER_IDS", "")
ALLOWED_USER_IDS: set[int] = set()
if _raw_ids.strip():
    for _id in _raw_ids.split(","):
        _id = _id.strip()
        if _id.isdigit():
            ALLOWED_USER_IDS.add(int(_id))

# Admin user ID — set explicitly in .env, do not derive from ALLOWED_USER_IDS
ADMIN_USER_ID: int | None = int(os.getenv("ADMIN_USER_ID", "0")) or None

MONTH_SHEET_NAMES = {
    1: "Jan", 2: "Feb", 3: "March", 4: "Apr",
    5: "May", 6: "Jun", 7: "Jul", 8: "Aug",
    9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
}

MAX_FILE_SIZE_MB = 20
TEMP_FOLDER = "./temp"
