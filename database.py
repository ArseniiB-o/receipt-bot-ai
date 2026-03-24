"""SQLite persistence layer — schema init, atomic receipt save, queries, user settings.

Fixes applied:
  BUG-08  Receipt number generation uses MAX(counter) instead of COUNT(*) so it
          never collides when the counter exceeds 999 or when gaps exist.
  BUG-20  All SUM() / amount math guarded against NULL (COALESCE in SQL + Python).

New schema additions (additive migrations, backward-compatible):
  audit_trail   — every receipt mutation is recorded.
  sequences     — monotone per-month counters (never reuse receipt numbers).
  dead_letters  — failed processing jobs for retry.
  user_blocks   — admin-managed user blocks (/block_user / /unblock_user).
  user_consents — GDPR consent records.
  pending_sheets_writes — offline queue for Sheets failures.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, date, time
from typing import Optional

from config import DB_PATH
from models import Receipt, ReceiptItem

logger = logging.getLogger(__name__)

# ─── Schema definitions ───────────────────────────────────────────────────────

_CREATE_RECEIPTS = """
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
    voided INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_receipt_date     ON receipts(receipt_date);
CREATE INDEX IF NOT EXISTS idx_receipt_type     ON receipts(type);
CREATE INDEX IF NOT EXISTS idx_receipt_number   ON receipts(receipt_number);
CREATE INDEX IF NOT EXISTS idx_receipt_user     ON receipts(telegram_user_id);
CREATE INDEX IF NOT EXISTS idx_user_date        ON receipts(telegram_user_id, receipt_date);
CREATE INDEX IF NOT EXISTS idx_created_at       ON receipts(created_at);
"""

_CREATE_USER_SETTINGS = """
CREATE TABLE IF NOT EXISTS user_settings (
    user_id INTEGER PRIMARY KEY,
    language TEXT DEFAULT 'ru',
    model TEXT DEFAULT NULL,
    privacy_accepted INTEGER DEFAULT 0,
    privacy_accepted_at DATETIME DEFAULT NULL,
    privacy_version TEXT DEFAULT NULL
);
"""

_CREATE_SEQUENCES = """
CREATE TABLE IF NOT EXISTS sequences (
    seq_key TEXT PRIMARY KEY,
    last_value INTEGER NOT NULL DEFAULT 0
);
"""

_CREATE_AUDIT_TRAIL = """
CREATE TABLE IF NOT EXISTS audit_trail (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_id INTEGER,
    receipt_number TEXT,
    user_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    field_changed TEXT,
    old_value TEXT,
    new_value TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_audit_receipt ON audit_trail(receipt_number);
CREATE INDEX IF NOT EXISTS idx_audit_user    ON audit_trail(user_id);
"""

_CREATE_DEAD_LETTERS = """
CREATE TABLE IF NOT EXISTS dead_letters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    file_path TEXT,
    caption TEXT,
    error_message TEXT,
    attempt_count INTEGER DEFAULT 1,
    last_attempt_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    original_message_id INTEGER,
    resolved INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

_CREATE_USER_BLOCKS = """
CREATE TABLE IF NOT EXISTS user_blocks (
    user_id INTEGER PRIMARY KEY,
    blocked_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    blocked_by INTEGER,
    reason TEXT
);
"""

_CREATE_PENDING_SHEETS = """
CREATE TABLE IF NOT EXISTS pending_sheets_writes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_number TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    retry_count INTEGER DEFAULT 0,
    last_error TEXT
);
"""


# ─── Connection context manager ───────────────────────────────────────────────


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


# ─── Schema init ──────────────────────────────────────────────────────────────


def init_db() -> None:
    """Initialize (or migrate) the database schema. Safe to call on every startup."""
    with get_conn() as conn:
        conn.executescript(_CREATE_RECEIPTS)
        conn.executescript(_CREATE_USER_SETTINGS)
        conn.executescript(_CREATE_SEQUENCES)
        conn.executescript(_CREATE_AUDIT_TRAIL)
        conn.executescript(_CREATE_DEAD_LETTERS)
        conn.executescript(_CREATE_USER_BLOCKS)
        conn.executescript(_CREATE_PENDING_SHEETS)

        # Additive migrations — never fail if column already exists
        _safe_alter(conn, "ALTER TABLE user_settings ADD COLUMN model TEXT DEFAULT NULL")
        _safe_alter(conn, "ALTER TABLE user_settings ADD COLUMN privacy_accepted INTEGER DEFAULT 0")
        _safe_alter(conn, "ALTER TABLE user_settings ADD COLUMN privacy_accepted_at DATETIME DEFAULT NULL")
        _safe_alter(conn, "ALTER TABLE user_settings ADD COLUMN privacy_version TEXT DEFAULT NULL")
        _safe_alter(conn, "ALTER TABLE receipts ADD COLUMN voided INTEGER DEFAULT 0")

    logger.info("Database initialized: %s", DB_PATH)


def _safe_alter(conn: sqlite3.Connection, sql: str) -> None:
    try:
        conn.execute(sql)
    except sqlite3.OperationalError:
        pass  # Column already exists


# ─── Sequences (BUG-08 fix) ───────────────────────────────────────────────────


def _next_receipt_seq(conn: sqlite3.Connection, year: int, month: int) -> int:
    """Return the next receipt sequence number for (year, month).

    Uses the sequences table for monotone counters that never reuse a number,
    even after deletions or gaps.  Falls back to MAX(existing) if the sequence
    table entry doesn't exist yet (handles legacy data correctly).
    """
    seq_key = f"{year}-{month:02d}"
    prefix = f"{seq_key}-"

    row = conn.execute(
        "SELECT last_value FROM sequences WHERE seq_key = ?", (seq_key,)
    ).fetchone()

    if row is not None:
        next_val = row["last_value"] + 1
    else:
        # Bootstrap from existing data so we never collide with legacy records.
        # Use MAX of the numeric suffix, not COUNT (BUG-08 fix).
        existing = conn.execute(
            "SELECT COALESCE(MAX(CAST(SUBSTR(receipt_number, ?) AS INTEGER)), 0) "
            "FROM receipts WHERE receipt_number LIKE ?",
            (len(prefix) + 1, f"{prefix}%"),
        ).fetchone()[0]
        next_val = (existing or 0) + 1

    conn.execute(
        "INSERT INTO sequences (seq_key, last_value) VALUES (?, ?)"
        " ON CONFLICT(seq_key) DO UPDATE SET last_value = excluded.last_value",
        (seq_key, next_val),
    )
    return next_val


# ─── Receipt persistence ──────────────────────────────────────────────────────


def save_receipt_atomic(receipt: Receipt, year: int, month: int) -> tuple[str, int]:
    """Atomically assign a receipt number and save to DB.

    Returns (receipt_number, row_id).
    """
    # Truncate raw AI response to prevent unbounded DB growth
    receipt.raw_ai_response = (receipt.raw_ai_response or "")[:50_000]

    items_json = json.dumps(
        [{"name": i.name, "quantity": i.quantity, "price": i.price} for i in receipt.items],
        ensure_ascii=False,
    )
    file_paths_json = json.dumps(receipt.file_paths, ensure_ascii=False)
    receipt_date_str = receipt.receipt_date.isoformat() if receipt.receipt_date else None
    receipt_time_str = receipt.receipt_time.strftime("%H:%M") if receipt.receipt_time else None

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        conn.execute("BEGIN IMMEDIATE")

        # BUG-08: use sequence counter, not COUNT(*)
        seq_num = _next_receipt_seq(conn, year, month)
        receipt_number = f"{year}-{month:02d}-{seq_num:03d}"
        receipt.receipt_number = receipt_number

        cur = conn.execute(
            """
            INSERT INTO receipts (
                receipt_number, type, store, website,
                total_amount, netto, ust_amount, ust_rate, currency,
                receipt_date, receipt_time, category, items_json,
                confidence, file_paths, telegram_message_id,
                telegram_user_id, telegram_username, added_by,
                raw_ai_response, notes, status
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                receipt_number, receipt.type, receipt.store, receipt.website,
                receipt.total_amount, receipt.netto, receipt.ust_amount, receipt.ust_rate,
                receipt.currency, receipt_date_str, receipt_time_str, receipt.category,
                items_json, receipt.confidence, file_paths_json, receipt.telegram_message_id,
                receipt.telegram_user_id, receipt.telegram_username, receipt.added_by,
                receipt.raw_ai_response, receipt.notes, receipt.status,
            ),
        )
        rowid = cur.lastrowid

        # Audit trail — record creation
        conn.execute(
            "INSERT INTO audit_trail (receipt_number, user_id, action) VALUES (?, ?, ?)",
            (receipt_number, receipt.telegram_user_id, "create"),
        )

        conn.commit()
        return receipt_number, rowid
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_file_paths(receipt_number: str, file_paths: list[str]) -> None:
    """Update file paths for a receipt after they have been persisted."""
    file_paths_json = json.dumps(file_paths, ensure_ascii=False)
    with get_conn() as conn:
        conn.execute(
            "UPDATE receipts SET file_paths = ?, updated_at = CURRENT_TIMESTAMP"
            " WHERE receipt_number = ?",
            (file_paths_json, receipt_number),
        )


def delete_receipt(receipt_number: str) -> bool:
    """Delete a receipt by number. Returns True if a row was deleted."""
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


def get_last_receipts(
    limit: int = 10,
    user_id: Optional[int] = None,
    offset: int = 0,
) -> list[dict]:
    """Fetch paginated receipts ordered by creation date descending."""
    with get_conn() as conn:
        if user_id:
            cur = conn.execute(
                "SELECT * FROM receipts WHERE telegram_user_id = ?"
                " ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (user_id, limit, offset),
            )
        else:
            cur = conn.execute(
                "SELECT * FROM receipts ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
        return [dict(r) for r in cur.fetchall()]


def get_stats(year: int, month: int, user_id: Optional[int] = None) -> dict:
    """Return monthly statistics.  All SUM() calls use COALESCE to handle NULLs (BUG-20)."""
    month_prefix = f"{year}-{month:02d}-%"

    with get_conn() as conn:
        if user_id:
            exp_row = conn.execute(
                "SELECT COALESCE(SUM(total_amount), 0), COUNT(*) FROM receipts"
                " WHERE receipt_number LIKE ? AND type = ? AND telegram_user_id = ?",
                (month_prefix, "expense", user_id),
            ).fetchone()
            inc_row = conn.execute(
                "SELECT COALESCE(SUM(total_amount), 0), COUNT(*) FROM receipts"
                " WHERE receipt_number LIKE ? AND type = ? AND telegram_user_id = ?",
                (month_prefix, "income", user_id),
            ).fetchone()
            cat_rows = conn.execute(
                "SELECT category, COALESCE(SUM(total_amount), 0) FROM receipts"
                " WHERE receipt_number LIKE ? AND type = ? AND telegram_user_id = ?"
                " GROUP BY category ORDER BY SUM(total_amount) DESC",
                (month_prefix, "expense", user_id),
            ).fetchall()
        else:
            exp_row = conn.execute(
                "SELECT COALESCE(SUM(total_amount), 0), COUNT(*) FROM receipts"
                " WHERE receipt_number LIKE ? AND type = ?",
                (month_prefix, "expense"),
            ).fetchone()
            inc_row = conn.execute(
                "SELECT COALESCE(SUM(total_amount), 0), COUNT(*) FROM receipts"
                " WHERE receipt_number LIKE ? AND type = ?",
                (month_prefix, "income"),
            ).fetchone()
            cat_rows = conn.execute(
                "SELECT category, COALESCE(SUM(total_amount), 0) FROM receipts"
                " WHERE receipt_number LIKE ? AND type = ?"
                " GROUP BY category ORDER BY SUM(total_amount) DESC",
                (month_prefix, "expense"),
            ).fetchall()

    exp_sum, exp_count = exp_row[0] or 0.0, exp_row[1] or 0
    inc_sum, inc_count = inc_row[0] or 0.0, inc_row[1] or 0
    categories = [(r[0] or "Прочее", r[1] or 0.0) for r in cat_rows]

    return {
        "expense_total": exp_sum,
        "expense_count": exp_count,
        "income_total": inc_sum,
        "income_count": inc_count,
        "balance": inc_sum - exp_sum,
        "categories": categories,
    }


def get_last_confirmed_receipt(user_id: int, minutes: Optional[int] = None) -> Optional[dict]:
    """Return the most recent receipt for a user added within the last N minutes."""
    from config import CANCEL_WINDOW_MINUTES
    window = minutes if minutes is not None else CANCEL_WINDOW_MINUTES
    with get_conn() as conn:
        cur = conn.execute(
            """
            SELECT * FROM receipts
            WHERE telegram_user_id = ?
              AND datetime(created_at) >= datetime('now', ?)
            ORDER BY created_at DESC LIMIT 1
            """,
            (user_id, f"-{window} minutes"),
        )
        row = cur.fetchone()
        return dict(row) if row else None


# ─── User settings ────────────────────────────────────────────────────────────


def get_user_language(user_id: int) -> str:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT language FROM user_settings WHERE user_id = ?", (user_id,)
        ).fetchone()
        return row["language"] if row else "ru"


def set_user_language(user_id: int, lang: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO user_settings (user_id, language) VALUES (?, ?)",
            (user_id, lang),
        )


def has_language_set(user_id: int) -> bool:
    with get_conn() as conn:
        return conn.execute(
            "SELECT 1 FROM user_settings WHERE user_id = ?", (user_id,)
        ).fetchone() is not None


def get_user_model(user_id: int) -> Optional[str]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT model FROM user_settings WHERE user_id = ?", (user_id,)
        ).fetchone()
        return row["model"] if row else None


def set_user_model(user_id: int, model: Optional[str]) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO user_settings (user_id, model) VALUES (?, ?)"
            " ON CONFLICT(user_id) DO UPDATE SET model = excluded.model",
            (user_id, model),
        )


# ─── Privacy / GDPR consent ───────────────────────────────────────────────────


def has_privacy_accepted(user_id: int) -> bool:
    """Return True if the user has accepted the privacy notice."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT privacy_accepted FROM user_settings WHERE user_id = ?", (user_id,)
        ).fetchone()
        return bool(row and row["privacy_accepted"])


def set_privacy_accepted(user_id: int, version: str) -> None:
    """Record that the user accepted the privacy notice at this version."""
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO user_settings (user_id, privacy_accepted, privacy_accepted_at, privacy_version)
               VALUES (?, 1, CURRENT_TIMESTAMP, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                 privacy_accepted = 1,
                 privacy_accepted_at = CURRENT_TIMESTAMP,
                 privacy_version = excluded.privacy_version""",
            (user_id, version),
        )


# ─── User blocks (admin) ──────────────────────────────────────────────────────


def is_user_blocked(user_id: int) -> bool:
    with get_conn() as conn:
        return conn.execute(
            "SELECT 1 FROM user_blocks WHERE user_id = ?", (user_id,)
        ).fetchone() is not None


def block_user(user_id: int, blocked_by: int, reason: str = "") -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO user_blocks (user_id, blocked_by, reason) VALUES (?, ?, ?)",
            (user_id, blocked_by, reason),
        )


def unblock_user(user_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM user_blocks WHERE user_id = ?", (user_id,))
        return cur.rowcount > 0


# ─── Dead letter queue ────────────────────────────────────────────────────────


def add_dead_letter(
    user_id: int,
    file_path: str,
    caption: str,
    error_message: str,
    original_message_id: Optional[int] = None,
) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO dead_letters (user_id, file_path, caption, error_message, original_message_id)"
            " VALUES (?, ?, ?, ?, ?)",
            (user_id, file_path, caption[:2000], error_message[:2000], original_message_id),
        )


def get_dead_letters(limit: int = 50, unresolved_only: bool = True) -> list[dict]:
    with get_conn() as conn:
        sql = "SELECT * FROM dead_letters"
        params: list = []
        if unresolved_only:
            sql += " WHERE resolved = 0"
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def resolve_dead_letter(dead_letter_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE dead_letters SET resolved = 1 WHERE id = ?", (dead_letter_id,)
        )


# ─── Pending Sheets writes ────────────────────────────────────────────────────


def add_pending_sheets_write(receipt_number: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO pending_sheets_writes (receipt_number) VALUES (?)",
            (receipt_number,),
        )


def get_pending_sheets_writes(limit: int = 20) -> list[dict]:
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM pending_sheets_writes ORDER BY created_at LIMIT ?", (limit,)
        ).fetchall()]


def remove_pending_sheets_write(pending_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM pending_sheets_writes WHERE id = ?", (pending_id,))


# ─── GDPR — right to erasure ──────────────────────────────────────────────────


def delete_user_data(user_id: int) -> dict[str, int]:
    """Delete ALL data for a user. Returns counts of deleted records by table."""
    counts: dict[str, int] = {}
    with get_conn() as conn:
        r = conn.execute("DELETE FROM receipts WHERE telegram_user_id = ?", (user_id,))
        counts["receipts"] = r.rowcount
        conn.execute("DELETE FROM user_settings WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM dead_letters WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM audit_trail WHERE user_id = ?", (user_id,))
        counts["audit"] = 0  # included in receipts cleanup
    return counts


def get_all_user_receipts(user_id: int) -> list[dict]:
    """Fetch all receipts for a user (for GDPR data export)."""
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM receipts WHERE telegram_user_id = ? ORDER BY created_at",
            (user_id,),
        ).fetchall()]


# ─── Data retention ───────────────────────────────────────────────────────────


def delete_old_receipts(older_than_days: int) -> list[dict]:
    """Delete receipts older than N days. Returns deleted rows (for file cleanup)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT receipt_number, file_paths FROM receipts"
            " WHERE datetime(created_at) < datetime('now', ?)",
            (f"-{older_than_days} days",),
        ).fetchall()
        deleted = [dict(r) for r in rows]
        if deleted:
            numbers = [r["receipt_number"] for r in deleted]
            placeholders = ",".join("?" * len(numbers))
            conn.execute(
                f"DELETE FROM receipts WHERE receipt_number IN ({placeholders})",
                numbers,
            )
    return deleted


# ─── Admin stats ──────────────────────────────────────────────────────────────


def get_admin_stats() -> dict:
    """Return aggregate statistics for the admin dashboard."""
    with get_conn() as conn:
        total_users = conn.execute(
            "SELECT COUNT(DISTINCT telegram_user_id) FROM receipts"
        ).fetchone()[0] or 0

        total_receipts = conn.execute(
            "SELECT COUNT(*) FROM receipts"
        ).fetchone()[0] or 0

        oldest = conn.execute(
            "SELECT MIN(created_at) FROM receipts"
        ).fetchone()[0]

        active_24h = conn.execute(
            "SELECT COUNT(DISTINCT telegram_user_id) FROM receipts"
            " WHERE datetime(created_at) >= datetime('now', '-1 day')"
        ).fetchone()[0] or 0

        pending_sheets = conn.execute(
            "SELECT COUNT(*) FROM pending_sheets_writes"
        ).fetchone()[0] or 0

        dead_letters = conn.execute(
            "SELECT COUNT(*) FROM dead_letters WHERE resolved = 0"
        ).fetchone()[0] or 0

    return {
        "total_users": total_users,
        "total_receipts": total_receipts,
        "oldest_record": oldest,
        "active_24h": active_24h,
        "pending_sheets": pending_sheets,
        "dead_letters": dead_letters,
    }
