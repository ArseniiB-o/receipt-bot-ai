"""SQLite persistence layer — schema init, atomic receipt save, queries, user settings."""
import sqlite3
import json
import logging
from datetime import datetime, date, time
from typing import Optional
from contextlib import contextmanager

from config import DB_PATH
from models import Receipt, ReceiptItem

logger = logging.getLogger(__name__)

CREATE_USER_SETTINGS_SQL = """
CREATE TABLE IF NOT EXISTS user_settings (
    user_id INTEGER PRIMARY KEY,
    language TEXT DEFAULT 'ru',
    model TEXT DEFAULT NULL
);
"""

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS receipts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_number TEXT UNIQUE NOT NULL,
    type TEXT NOT NULL,
    store TEXT,
    website TEXT,
    total_amount REAL,
    netto REAL,
    ust_amount REAL,
    ust_rate REAL,
    currency TEXT DEFAULT 'EUR',
    receipt_date DATE,
    receipt_time TIME,
    category TEXT,
    items_json TEXT,
    confidence REAL,
    file_paths TEXT,
    telegram_message_id INTEGER,
    telegram_user_id INTEGER NOT NULL,
    telegram_username TEXT,
    added_by TEXT,
    raw_ai_response TEXT,
    notes TEXT,
    status TEXT DEFAULT 'confirmed',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_receipt_date ON receipts(receipt_date);
CREATE INDEX IF NOT EXISTS idx_receipt_type ON receipts(type);
CREATE INDEX IF NOT EXISTS idx_receipt_number ON receipts(receipt_number);
CREATE INDEX IF NOT EXISTS idx_receipt_user ON receipts(telegram_user_id);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(CREATE_TABLE_SQL)
        conn.executescript(CREATE_USER_SETTINGS_SQL)
        # Safe migration — add model column if it doesn't exist yet
        try:
            conn.execute("ALTER TABLE user_settings ADD COLUMN model TEXT DEFAULT NULL")
        except Exception:
            pass  # Column already exists
    logger.info("Database initialized: %s", DB_PATH)


def save_receipt_atomic(receipt: Receipt, year: int, month: int) -> tuple[str, int]:
    """Atomically assign a receipt number and save to DB. Prevents race conditions.
    Returns (receipt_number, row_id).
    """
    prefix = f"{year}-{month:02d}-"
    # Truncate AI response to prevent unbounded DB growth
    receipt.raw_ai_response = (receipt.raw_ai_response or "")[:50_000]
    items_json = json.dumps(
        [{"name": i.name, "quantity": i.quantity, "price": i.price} for i in receipt.items],
        ensure_ascii=False
    )
    file_paths_json = json.dumps(receipt.file_paths, ensure_ascii=False)
    receipt_date_str = receipt.receipt_date.isoformat() if receipt.receipt_date else None
    receipt_time_str = receipt.receipt_time.strftime("%H:%M") if receipt.receipt_time else None

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        conn.execute("BEGIN IMMEDIATE")
        # Only count standard-format receipt numbers (YYYY-MM-NNN) to avoid legacy pollution
        cur = conn.execute(
            "SELECT COUNT(*) FROM receipts "
            "WHERE receipt_number GLOB '????-??-???' AND receipt_number LIKE ?",
            (f"{prefix}%",)
        )
        count = cur.fetchone()[0]
        receipt_number = f"{prefix}{count + 1:03d}"
        receipt.receipt_number = receipt_number

        cur = conn.execute("""
            INSERT INTO receipts (
                receipt_number, type, store, website,
                total_amount, netto, ust_amount, ust_rate, currency,
                receipt_date, receipt_time, category, items_json,
                confidence, file_paths, telegram_message_id,
                telegram_user_id, telegram_username, added_by,
                raw_ai_response, notes, status
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            receipt_number, receipt.type, receipt.store, receipt.website,
            receipt.total_amount, receipt.netto, receipt.ust_amount, receipt.ust_rate, receipt.currency,
            receipt_date_str, receipt_time_str, receipt.category, items_json,
            receipt.confidence, file_paths_json, receipt.telegram_message_id,
            receipt.telegram_user_id, receipt.telegram_username, receipt.added_by,
            receipt.raw_ai_response, receipt.notes, receipt.status
        ))
        rowid = cur.lastrowid
        conn.commit()
        return receipt_number, rowid
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_file_paths(receipt_number: str, file_paths: list[str]):
    """Update file paths for a receipt after they have been persisted."""
    file_paths_json = json.dumps(file_paths, ensure_ascii=False)
    with get_conn() as conn:
        conn.execute(
            "UPDATE receipts SET file_paths = ? WHERE receipt_number = ?",
            (file_paths_json, receipt_number)
        )


def delete_receipt(receipt_number: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM receipts WHERE receipt_number = ?", (receipt_number,)
        )
        return cur.rowcount > 0


def get_receipt_by_number(receipt_number: str) -> Optional[dict]:
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT * FROM receipts WHERE receipt_number = ?", (receipt_number,)
        )
        row = cur.fetchone()
        return dict(row) if row else None


def get_last_receipts(limit: int = 10, user_id: Optional[int] = None) -> list[dict]:
    with get_conn() as conn:
        if user_id:
            cur = conn.execute(
                "SELECT * FROM receipts WHERE telegram_user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit)
            )
        else:
            cur = conn.execute(
                "SELECT * FROM receipts ORDER BY created_at DESC LIMIT ?", (limit,)
            )
        return [dict(r) for r in cur.fetchall()]


def get_stats(year: int, month: int, user_id: Optional[int] = None) -> dict:
    month_prefix = f"{year}-{month:02d}-%"

    with get_conn() as conn:
        if user_id:
            cur = conn.execute(
                "SELECT SUM(total_amount), COUNT(*) FROM receipts"
                " WHERE receipt_number LIKE ? AND type = ? AND telegram_user_id = ?",
                (month_prefix, "expense", user_id),
            )
        else:
            cur = conn.execute(
                "SELECT SUM(total_amount), COUNT(*) FROM receipts"
                " WHERE receipt_number LIKE ? AND type = ?",
                (month_prefix, "expense"),
            )
        exp_sum, exp_count = cur.fetchone()

        if user_id:
            cur = conn.execute(
                "SELECT SUM(total_amount), COUNT(*) FROM receipts"
                " WHERE receipt_number LIKE ? AND type = ? AND telegram_user_id = ?",
                (month_prefix, "income", user_id),
            )
        else:
            cur = conn.execute(
                "SELECT SUM(total_amount), COUNT(*) FROM receipts"
                " WHERE receipt_number LIKE ? AND type = ?",
                (month_prefix, "income"),
            )
        inc_sum, inc_count = cur.fetchone()

        if user_id:
            cur = conn.execute(
                "SELECT category, SUM(total_amount) FROM receipts"
                " WHERE receipt_number LIKE ? AND type = ? AND telegram_user_id = ?"
                " GROUP BY category ORDER BY SUM(total_amount) DESC",
                (month_prefix, "expense", user_id),
            )
        else:
            cur = conn.execute(
                "SELECT category, SUM(total_amount) FROM receipts"
                " WHERE receipt_number LIKE ? AND type = ?"
                " GROUP BY category ORDER BY SUM(total_amount) DESC",
                (month_prefix, "expense"),
            )
        categories = [(r[0] or "Прочее", r[1] or 0) for r in cur.fetchall()]

    return {
        "expense_total": exp_sum or 0,
        "expense_count": exp_count or 0,
        "income_total": inc_sum or 0,
        "income_count": inc_count or 0,
        "balance": (inc_sum or 0) - (exp_sum or 0),
        "categories": categories,
    }


def get_user_language(user_id: int) -> str:
    """Return the user's preferred language (ru/de/en). Defaults to 'ru'."""
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT language FROM user_settings WHERE user_id = ?", (user_id,)
        )
        row = cur.fetchone()
        return row["language"] if row else "ru"


def set_user_language(user_id: int, lang: str) -> None:
    """Persist the user's language preference."""
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO user_settings (user_id, language) VALUES (?, ?)",
            (user_id, lang),
        )


def has_language_set(user_id: int) -> bool:
    """Return True if the user has explicitly chosen a language."""
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT 1 FROM user_settings WHERE user_id = ?", (user_id,)
        )
        return cur.fetchone() is not None


def get_user_model(user_id: int) -> Optional[str]:
    """Return the user's preferred AI model, or None if using auto (pool round-robin)."""
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT model FROM user_settings WHERE user_id = ?", (user_id,)
        )
        row = cur.fetchone()
        if row is None:
            return None
        return row["model"]  # may be None


def set_user_model(user_id: int, model: Optional[str]) -> None:
    """Persist the user's preferred AI model. Pass None to reset to auto."""
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO user_settings (user_id, model) VALUES (?, ?)"
            " ON CONFLICT(user_id) DO UPDATE SET model = excluded.model",
            (user_id, model),
        )


def get_last_confirmed_receipt(user_id: int, minutes: int = 5) -> Optional[dict]:
    """Return the most recent receipt for a user added within the last N minutes."""
    with get_conn() as conn:
        cur = conn.execute("""
            SELECT * FROM receipts
            WHERE telegram_user_id = ?
              AND datetime(created_at) >= datetime('now', ?)
            ORDER BY created_at DESC LIMIT 1
        """, (user_id, f"-{minutes} minutes"))
        row = cur.fetchone()
        return dict(row) if row else None
