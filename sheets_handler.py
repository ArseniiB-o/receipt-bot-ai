"""Google Sheets writer — auto-detects column layout, inserts rows sorted by date.

Fixes applied:
  BUG-06  _col_cache protected by asyncio.Lock (was accessed from multiple async tasks).
  BUG-07  ALL gspread calls wrapped in asyncio.wait_for() with explicit timeouts.
  BUG-10  Early return guard when GOOGLE_SHEETS_ID is empty (was partially guarded).
  BUG-17  service_account.json validated as proper JSON before auth is attempted.

New features:
  Exponential-backoff retry for all Sheets operations (2s / 4s / 8s).
  Offline queue: on failure → add to pending_sheets_writes table.
  Batch cell update (single API call per receipt, not per cell).
"""
from __future__ import annotations

import asyncio
import json
import logging
import urllib.request
from datetime import date, datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Optional

import gspread
import google.auth._helpers as _google_helpers
from google.oauth2.service_account import Credentials

from config import GOOGLE_SERVICE_ACCOUNT_JSON, GOOGLE_SHEETS_ID, MONTH_SHEET_NAMES
from constants import SHEETS_RETRY_DELAYS, SHEETS_WRITE_TIMEOUT
from models import Receipt

logger = logging.getLogger(__name__)


# ─── Clock skew compensation ──────────────────────────────────────────────────

_clock_skew_applied = False


def _apply_clock_skew_fix() -> None:
    global _clock_skew_applied
    if _clock_skew_applied:
        return
    try:
        req = urllib.request.Request(
            "https://accounts.google.com/",
            method="HEAD",
            headers={"User-Agent": "receipt-bot/1.0"},
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            date_str = r.headers.get("date", "")
            if not date_str:
                return
            server_time = parsedate_to_datetime(date_str).astimezone(timezone.utc)
            system_time = datetime.now(timezone.utc)
            skew = server_time - system_time
            skew_secs = skew.total_seconds()
            if abs(skew_secs) > 30:
                logger.warning("Clock skew with Google servers: %.0f sec.", skew_secs)
                _orig = _google_helpers.utcnow

                def _patched():
                    return _orig() + timedelta(seconds=skew_secs)

                _google_helpers.utcnow = _patched
            _clock_skew_applied = True
    except Exception as e:
        logger.debug("Could not check Google server time: %s", e)


_apply_clock_skew_fix()

# ─────────────────────────────────────────────────────────────────────────────

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

HEADER_ROW = 5
DATA_START_ROW = 6

# BUG-06: protect _col_cache with asyncio.Lock
_col_cache: dict[str, tuple[dict, dict]] = {}
_col_cache_lock = asyncio.Lock()

# Serializes concurrent writes — prevents two receipts landing on the same row
_sheets_lock = asyncio.Lock()


# ─── Service account validation (BUG-17) ─────────────────────────────────────


def _validate_service_account() -> bool:
    """Verify service_account.json exists and is valid JSON before attempting auth."""
    path = Path(GOOGLE_SERVICE_ACCOUNT_JSON)
    if not path.exists():
        logger.error("service_account.json not found at %s", path)
        return False
    try:
        data = json.loads(path.read_text())
        required_keys = {"type", "project_id", "private_key", "client_email"}
        missing = required_keys - set(data.keys())
        if missing:
            logger.error("service_account.json missing required keys: %s", missing)
            return False
        if data.get("type") != "service_account":
            logger.error("service_account.json type is %r, expected 'service_account'", data.get("type"))
            return False
        return True
    except (json.JSONDecodeError, OSError) as e:
        logger.error("service_account.json is not valid JSON: %s", e)
        return False


def _get_client() -> gspread.Client:
    if not _validate_service_account():
        raise ValueError("service_account.json validation failed — cannot authenticate with Google")
    creds = Credentials.from_service_account_file(GOOGLE_SERVICE_ACCOUNT_JSON, scopes=SCOPES)
    return gspread.authorize(creds)


def _get_sheet_name(receipt_date: Optional[date]) -> str:
    if receipt_date:
        return MONTH_SHEET_NAMES.get(receipt_date.month, "Jan")
    return MONTH_SHEET_NAMES.get(date.today().month, "Jan")


async def clear_column_cache() -> None:
    """Clear the column map cache (call if spreadsheet structure changes)."""
    async with _col_cache_lock:
        _col_cache.clear()


def _compute_column_maps(worksheet) -> tuple[dict, dict]:
    headers = worksheet.row_values(HEADER_ROW)
    right_block_start_idx = None
    for i, h in enumerate(headers):
        if h.strip().lower() == "website":
            right_block_start_idx = i
            break

    left_cols: dict[str, int] = {}
    right_cols: dict[str, int] = {}

    for i, h in enumerate(headers):
        col = i + 1
        h_norm = h.strip().lower()
        is_right = right_block_start_idx is not None and i >= right_block_start_idx
        target = right_cols if is_right else left_cols

        if "website" in h_norm:
            target["website"] = col
        elif "beleg" in h_norm:
            target["beleg"] = col
        elif "datum" in h_norm:
            target["datum"] = col
        elif "transaktion" in h_norm:
            target["transaktion"] = col
        elif "kategorie" in h_norm or "category" in h_norm:
            target["kategorie"] = col
        elif "netto" in h_norm:
            target["netto"] = col
        elif "ust" in h_norm or "mwst" in h_norm or "vat" in h_norm:
            target["ust"] = col
        elif "gesamt" in h_norm or "brutto" in h_norm or "total" in h_norm:
            target["gesamt"] = col

    return left_cols, right_cols


async def _get_column_maps(worksheet) -> tuple[dict, dict]:
    """Thread-safe column map retrieval with caching (BUG-06 fix)."""
    key = worksheet.title
    async with _col_cache_lock:
        if key not in _col_cache:
            loop = asyncio.get_running_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(None, _compute_column_maps, worksheet),
                timeout=SHEETS_WRITE_TIMEOUT,
            )
            _col_cache[key] = result
        return _col_cache[key]


def _find_gesamt_row(worksheet, check_col: int) -> int:
    all_values = worksheet.col_values(check_col)
    for i in range(len(all_values) - 1, DATA_START_ROW - 2, -1):
        val = str(all_values[i]).strip().lower()
        if "gesamt" in val or "summ" in val or "total" in val:
            return i + 1
    return 9999


def _parse_date_cell(cell_str: str) -> Optional[date]:
    s = (cell_str or "").strip()
    if not s:
        return None
    try:
        parts = s.split(".")
        if len(parts) == 3:
            return date(int(parts[2]), int(parts[1]), int(parts[0]))
    except (ValueError, IndexError):
        pass
    return None


def _find_insert_row(
    datum_values: list,
    new_date: date,
    gesamt_row: int,
    transaktion_values: Optional[list] = None,
    new_store: str = "",
) -> tuple[int, bool]:
    last_filled_row = None
    for i in range(DATA_START_ROW - 1, min(len(datum_values), gesamt_row - 1)):
        cell = datum_values[i].strip() if datum_values[i] else ""
        if not cell:
            return i + 1, False
        existing_date = _parse_date_cell(cell)
        last_filled_row = i + 1
        if existing_date is None:
            continue
        if existing_date > new_date:
            return i + 1, True
        if existing_date == new_date and new_store and transaktion_values:
            existing_store = ""
            if i < len(transaktion_values):
                t = transaktion_values[i] or ""
                existing_store = t.split(" – ")[0].strip().lower()
            if new_store.lower() < existing_store:
                return i + 1, True

    next_row = (last_filled_row + 1) if last_filled_row is not None else DATA_START_ROW
    if gesamt_row < 9999 and next_row >= gesamt_row:
        return gesamt_row, True
    return next_row, False


def _beleg_exists_in_col(worksheet, beleg: str, col_idx: int) -> bool:
    try:
        return beleg in worksheet.col_values(col_idx)
    except Exception:
        return False


def _write_row_batch(worksheet, row: int, cols: dict, values: dict) -> None:
    """Write all values for a receipt in a single batch API call (performance)."""
    cells = []
    for key, value in values.items():
        if key in cols and value is not None:
            cells.append(gspread.Cell(row, cols[key], value))
    if cells:
        worksheet.update_cells(cells, value_input_option="USER_ENTERED")


def _build_transaktion(receipt: Receipt) -> str:
    store = receipt.store or ""
    items = receipt.items or []
    if items:
        names = [i.name for i in items if i.name][:4]
        items_str = ", ".join(names)
        if len(receipt.items) > 4:
            items_str += f" +{len(receipt.items) - 4}"
        full = f"{store} – {items_str}" if store else items_str
    elif store:
        full = store
    else:
        full = "Доход" if receipt.type == "income" else "Расход"
    return full[:100]


def _sync_write_to_sheets(receipt: Receipt) -> None:
    """Synchronous Google Sheets write (runs in executor)."""
    client = _get_client()
    spreadsheet = client.open_by_key(GOOGLE_SHEETS_ID)
    sheet_name = _get_sheet_name(receipt.receipt_date)

    try:
        worksheet = spreadsheet.worksheet(sheet_name)
    except gspread.WorksheetNotFound:
        logger.warning("Sheet '%s' not found, falling back to current month", sheet_name)
        fallback = MONTH_SHEET_NAMES.get(date.today().month, "Jan")
        try:
            worksheet = spreadsheet.worksheet(fallback)
        except gspread.WorksheetNotFound:
            worksheet = spreadsheet.get_worksheet(0)

    left_cols, right_cols = _compute_column_maps(worksheet)

    date_str = receipt.receipt_date.strftime("%d.%m.%Y") if receipt.receipt_date else ""
    new_date = receipt.receipt_date or date.today()
    transaktion = _build_transaktion(receipt)

    if receipt.type == "income":
        if not left_cols:
            raise ValueError("Left block columns not found (Betriebseinnahmen)")
        datum_col = left_cols.get("datum") or next(iter(left_cols.values()))
        beleg_col = left_cols.get("beleg", datum_col)
        if _beleg_exists_in_col(worksheet, receipt.receipt_number, beleg_col):
            logger.info("Duplicate in Sheets (income) — skipping: %s", receipt.receipt_number)
            return
        gesamt_row = _find_gesamt_row(worksheet, datum_col)
        datum_values = worksheet.col_values(datum_col)
        transaktion_col = left_cols.get("transaktion")
        transaktion_values = worksheet.col_values(transaktion_col) if transaktion_col else None
        row, need_insert = _find_insert_row(datum_values, new_date, gesamt_row, transaktion_values, receipt.store or "")
        if need_insert:
            worksheet.insert_rows([[]], row=row, inherit_from_before=True)
        _write_row_batch(worksheet, row, left_cols, {
            "beleg": receipt.receipt_number,
            "datum": date_str,
            "transaktion": transaktion,
            "kategorie": receipt.category or "",
            "netto": receipt.netto or receipt.total_amount or 0,
            "ust": receipt.ust_amount or 0,
            "gesamt": receipt.total_amount or 0,
        })
        logger.info("Income written: %s → '%s' row %d", receipt.receipt_number, sheet_name, row)
    else:
        if not right_cols:
            raise ValueError("Right block columns not found (Betriebsausgaben)")
        datum_col = right_cols.get("datum") or next(iter(right_cols.values()))
        beleg_col = right_cols.get("beleg", datum_col)
        if _beleg_exists_in_col(worksheet, receipt.receipt_number, beleg_col):
            logger.info("Duplicate in Sheets (expense) — skipping: %s", receipt.receipt_number)
            return
        gesamt_row = _find_gesamt_row(worksheet, datum_col)
        datum_values = worksheet.col_values(datum_col)
        transaktion_col = right_cols.get("transaktion")
        transaktion_values = worksheet.col_values(transaktion_col) if transaktion_col else None
        row, need_insert = _find_insert_row(datum_values, new_date, gesamt_row, transaktion_values, receipt.store or "")
        if need_insert:
            worksheet.insert_rows([[]], row=row, inherit_from_before=True)
        _write_row_batch(worksheet, row, right_cols, {
            "website": receipt.website or receipt.store or "",
            "beleg": receipt.receipt_number,
            "datum": date_str,
            "transaktion": transaktion,
            "kategorie": receipt.category or "",
            "netto": receipt.netto or receipt.total_amount or 0,
            "ust": receipt.ust_amount or 0,
            "gesamt": receipt.total_amount or 0,
        })
        logger.info("Expense written: %s → '%s' row %d", receipt.receipt_number, sheet_name, row)


async def write_to_sheets(receipt: Receipt) -> bool:
    """Async write to Google Sheets with timeout, retry, and offline queue fallback.

    BUG-10: returns False immediately if GOOGLE_SHEETS_ID is not configured.
    BUG-07: all gspread calls are wrapped in wait_for() with explicit timeout.
    """
    if not GOOGLE_SHEETS_ID:
        return False  # BUG-10: silent guard — not an error

    loop = asyncio.get_running_loop()
    for attempt, delay in enumerate(SHEETS_RETRY_DELAYS):
        try:
            async with _sheets_lock:
                await asyncio.wait_for(
                    loop.run_in_executor(None, _sync_write_to_sheets, receipt),
                    timeout=SHEETS_WRITE_TIMEOUT,
                )
            return True
        except asyncio.TimeoutError:
            logger.error(
                "Sheets write timed out (attempt %d/%d) for %s",
                attempt + 1, len(SHEETS_RETRY_DELAYS), receipt.receipt_number,
            )
        except Exception as e:
            logger.error(
                "Sheets write error (attempt %d/%d) for %s: %s",
                attempt + 1, len(SHEETS_RETRY_DELAYS), receipt.receipt_number, e,
            )
        if attempt < len(SHEETS_RETRY_DELAYS) - 1:
            await asyncio.sleep(delay)

    # All retries failed — add to offline queue
    try:
        import database
        database.add_pending_sheets_write(receipt.receipt_number)
        logger.info("Added %s to pending_sheets_writes for later retry", receipt.receipt_number)
    except Exception as e:
        logger.error("Failed to add to pending queue: %s", e)

    return False


async def retry_pending_writes() -> int:
    """Retry all pending Sheets writes. Returns count of successfully flushed entries."""
    import database

    pending = database.get_pending_sheets_writes(limit=20)
    if not pending:
        return 0

    success_count = 0
    for entry in pending:
        rec_dict = database.get_receipt_by_number(entry["receipt_number"])
        if not rec_dict:
            database.remove_pending_sheets_write(entry["id"])
            continue
        try:
            rec = _dict_to_receipt(rec_dict)
            ok = await write_to_sheets(rec)
            if ok:
                database.remove_pending_sheets_write(entry["id"])
                success_count += 1
        except Exception as e:
            logger.warning("Retry failed for %s: %s", entry["receipt_number"], e)

    return success_count


def _dict_to_receipt(d: dict) -> Receipt:
    """Reconstruct a Receipt from a database row dict (for Sheets retry)."""
    import json as _json
    from datetime import date as _date, time as _time
    r = Receipt()
    r.receipt_number = d.get("receipt_number", "")
    r.type = d.get("type", "expense")
    r.store = d.get("store")
    r.website = d.get("website")
    r.total_amount = d.get("total_amount")
    r.netto = d.get("netto")
    r.ust_amount = d.get("ust_amount") or 0.0
    r.ust_rate = d.get("ust_rate") or 0
    r.currency = d.get("currency", "EUR")
    r.category = d.get("category")
    r.confidence = d.get("confidence") or 0.0
    r.telegram_user_id = d.get("telegram_user_id", 0)
    r.telegram_username = d.get("telegram_username")
    r.added_by = d.get("added_by")
    date_str = d.get("receipt_date")
    if date_str:
        try:
            r.receipt_date = _date.fromisoformat(date_str)
        except (ValueError, TypeError):
            pass
    items_json = d.get("items_json") or "[]"
    try:
        items = _json.loads(items_json)
        from models import ReceiptItem
        for item in items:
            if isinstance(item, dict):
                r.items.append(ReceiptItem(
                    name=item.get("name", ""),
                    quantity=float(item.get("quantity", 1)),
                    price=float(item.get("price", 0)),
                ))
    except Exception:
        pass
    return r
