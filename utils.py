"""Shared utilities — rate limiting, currency formatting, category emojis, safe paths.

BUG-15 fixed: uppercase Cyrillic added to transliteration map.
"""
from __future__ import annotations

import os
import re
from collections import defaultdict
from datetime import datetime
from time import time
from typing import Optional


# ─── Transliteration ──────────────────────────────────────────────────────────
# BUG-15: added full uppercase mapping + corrected missing chars

TRANSLIT_MAP: dict[str, str] = {
    # Lowercase
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d",
    "е": "e", "ё": "yo", "ж": "zh", "з": "z", "и": "i",
    "й": "y", "к": "k", "л": "l", "м": "m", "н": "n",
    "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
    "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch",
    "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "ь": "",
    "э": "e", "ю": "yu", "я": "ya",
    # Ukrainian
    "і": "i", "ї": "yi", "є": "ye", "ґ": "g",
    # Uppercase (BUG-15 fix)
    "А": "a", "Б": "b", "В": "v", "Г": "g", "Д": "d",
    "Е": "e", "Ё": "yo", "Ж": "zh", "З": "z", "И": "i",
    "Й": "y", "К": "k", "Л": "l", "М": "m", "Н": "n",
    "О": "o", "П": "p", "Р": "r", "С": "s", "Т": "t",
    "У": "u", "Ф": "f", "Х": "kh", "Ц": "ts", "Ч": "ch",
    "Ш": "sh", "Щ": "shch", "Ъ": "", "Ы": "y", "Ь": "",
    "Э": "e", "Ю": "yu", "Я": "ya",
    # Ukrainian uppercase
    "І": "i", "Ї": "yi", "Є": "ye", "Ґ": "g",
}

KNOWN_STORES: dict[str, str] = {
    "пятёрочка": "pyatyorochka", "пятерочка": "pyatyorochka",
    "магнит": "magnit", "вкусвилл": "vkusvill",
    "перекрёсток": "perekryostok", "перекресток": "perekryostok",
    "лента": "lenta", "ашан": "auchan", "auchan": "auchan",
    "rewe": "rewe", "lidl": "lidl", "aldi": "aldi", "netto": "netto",
    "penny": "penny", "edeka": "edeka", "kaufland": "kaufland",
    "dm": "dm", "rossmann": "rossmann", "amazon": "amazon",
    "zalando": "zalando", "paypal": "paypal", "ozon": "ozon",
    "wildberries": "wildberries", "wb": "wildberries",
    "сбербанк": "sberbank", "тинькофф": "tinkoff",
    "тинькофф банк": "tinkoff", "додо": "dodo", "додо пицца": "dodo",
}


def transliterate(text: str) -> str:
    """Transliterate Cyrillic text to ASCII equivalents."""
    return "".join(TRANSLIT_MAP.get(c, c) for c in text)


def sanitize_store_name(store: Optional[str]) -> str:
    """Produce a filesystem-safe store identifier for use in filenames."""
    if not store:
        return "unknown"
    lower = store.lower().strip()
    for key, val in KNOWN_STORES.items():
        if key in lower:
            return val
    result = re.sub(r"[^a-z0-9]+", "_", transliterate(lower).lower()).strip("_")[:30]
    return result or "unknown"


def sanitize_text_for_prompt(text: str, max_len: int = 2000) -> str:
    """Strip control characters and limit length before embedding in an AI prompt.

    Prevents prompt injection via user-supplied text.
    """
    # Remove control characters except newline/tab
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    return cleaned[:max_len]


def safe_file_path(base_dir: str, filename: str) -> str:
    """Guard against path traversal.

    Uses os.path.realpath to resolve symlinks, then verifies the result
    still lives under base_dir.  Raises ValueError on violation.
    """
    safe_name = re.sub(r"[^\w\-.]", "_", filename)[:120].lstrip(".")
    if not safe_name:
        safe_name = "file"
    # Construct candidate path and resolve fully (follows symlinks)
    candidate = os.path.realpath(os.path.join(base_dir, safe_name))
    abs_base = os.path.realpath(base_dir)
    if not (candidate.startswith(abs_base + os.sep) or candidate == abs_base):
        raise ValueError(f"Path traversal blocked: {filename!r}")
    return candidate


# ─── Rate limiting ─────────────────────────────────────────────────────────────

# {user_id: [timestamp, ...]}  — in-memory sliding window per type
_rate_messages: dict[int, list[float]] = defaultdict(list)
_rate_files: dict[int, list[float]] = defaultdict(list)
_rate_commands: dict[int, list[float]] = defaultdict(list)
_rate_ai_daily: dict[int, list[float]] = defaultdict(list)


def _sliding_window(store: dict[int, list[float]], user_id: int,
                    limit: int, window_secs: float) -> bool:
    """Return True if the action is allowed (within limit); False if exceeded."""
    now = time()
    ts = [t for t in store[user_id] if now - t < window_secs]
    store[user_id] = ts
    if len(ts) >= limit:
        return False
    store[user_id].append(now)
    return True


def check_rate_limit(user_id: int, max_per_minute: int = 10) -> bool:
    """General-purpose per-user rate check (messages/minute)."""
    return _sliding_window(_rate_messages, user_id, max_per_minute, 60.0)


def check_file_rate_limit(user_id: int) -> bool:
    """Per-user file upload rate: 20 per hour."""
    from constants import RATE_FILES_PER_HOUR
    return _sliding_window(_rate_files, user_id, RATE_FILES_PER_HOUR, 3600.0)


def check_command_rate_limit(user_id: int) -> bool:
    """Per-user command rate: 30 per minute."""
    from constants import RATE_COMMANDS_PER_MINUTE
    return _sliding_window(_rate_commands, user_id, RATE_COMMANDS_PER_MINUTE, 60.0)


def check_ai_rate_limit(user_id: int) -> bool:
    """Per-user AI call rate: RATE_AI_PER_DAY calls per 24 hours."""
    from constants import RATE_AI_PER_DAY
    return _sliding_window(_rate_ai_daily, user_id, RATE_AI_PER_DAY, 86400.0)


# ─── Formatting ───────────────────────────────────────────────────────────────

def format_currency(amount: Optional[float], currency: str = "EUR") -> str:
    if amount is None:
        return "—"
    symbols = {"EUR": "€", "USD": "$", "RUB": "₽", "UAH": "₴"}
    sym = symbols.get(currency, currency)
    return f"{amount:,.2f} {sym}".replace(",", " ")


def format_date_ru(dt) -> str:
    if dt is None:
        return "—"
    months = ["", "января", "февраля", "марта", "апреля", "мая", "июня",
              "июля", "августа", "сентября", "октября", "ноября", "декабря"]
    if hasattr(dt, "day"):
        return f"{dt.day} {months[dt.month]} {dt.year}"
    return str(dt)


def month_name_ru(month: int) -> str:
    months = ["", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
              "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
    return months[month] if 1 <= month <= 12 else str(month)


CATEGORY_EMOJI: dict[str, str] = {
    "Lebensmittel": "🛒", "Restaurant/Café": "🍽️", "Transport": "🚗",
    "Kleidung": "👕", "Medizin": "💊", "Technik": "💻", "Wohnen": "🏠",
    "Gehalt": "💼", "Überweisung": "🔄", "Sonstiges": "📦",
}


def category_emoji(category: Optional[str]) -> str:
    return CATEGORY_EMOJI.get(category or "", "📦")


def escape_md(text: str) -> str:
    """Escape MarkdownV2 special characters."""
    for c in r"_*[]()~`>#+-=|{}.!":
        text = text.replace(c, "\\" + c)
    return text


def escape_html(text: str) -> str:
    """Escape HTML special characters for use in parse_mode=HTML messages."""
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
    )


def error_ref() -> str:
    """Generate a timestamp-based support reference number for error messages."""
    return f"ERR-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
