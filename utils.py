"""Shared utilities — rate limiting, currency formatting, category emojis, safe paths."""
import os
import re
from collections import defaultdict
from datetime import datetime
from time import time
from typing import Optional


TRANSLIT_MAP = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "і": "i", "ї": "yi", "є": "ye", "ґ": "g",
}

KNOWN_STORES = {
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
    return "".join(TRANSLIT_MAP.get(c, c) for c in text.lower())


def sanitize_store_name(store: Optional[str]) -> str:
    if not store:
        return "unknown"
    lower = store.lower().strip()
    for key, val in KNOWN_STORES.items():
        if key in lower:
            return val
    result = re.sub(r"[^a-z0-9]+", "_", transliterate(lower)).strip("_")[:30]
    return result or "unknown"


def safe_file_path(base_dir: str, filename: str) -> str:
    """Защита от path traversal."""
    safe_name = re.sub(r"[^\w\-.]", "_", filename)[:120].lstrip(".")
    if not safe_name:
        safe_name = "file"
    full_path = os.path.abspath(os.path.join(base_dir, safe_name))
    abs_base = os.path.abspath(base_dir)
    if not full_path.startswith(abs_base + os.sep) and full_path != abs_base:
        raise ValueError(f"Path traversal blocked: {filename}")
    return full_path


# ─── Rate limiting ────────────────────────────────────────────────────────────

_rate_limit: dict = defaultdict(list)


def check_rate_limit(user_id: int, max_per_minute: int = 20) -> bool:
    now = time()
    ts = [t for t in _rate_limit[user_id] if now - t < 60]
    _rate_limit[user_id] = ts
    if len(ts) >= max_per_minute:
        return False
    _rate_limit[user_id].append(now)
    return True


# ─── Форматирование ───────────────────────────────────────────────────────────

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


CATEGORY_EMOJI = {
    "Lebensmittel": "🛒", "Restaurant/Café": "🍽️", "Transport": "🚗",
    "Kleidung": "👕", "Medizin": "💊", "Technik": "💻", "Wohnen": "🏠",
    "Gehalt": "💼", "Überweisung": "🔄", "Sonstiges": "📦",
}


def category_emoji(category: Optional[str]) -> str:
    return CATEGORY_EMOJI.get(category or "", "📦")


def escape_md(text: str) -> str:
    for c in r"_*[]()~`>#+-=|{}.!":
        text = text.replace(c, "\\" + c)
    return text
