"""Google Sheets writer — auto-detects column layout, inserts rows sorted by date."""
import asyncio
import logging
import urllib.request
from datetime import date, datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from typing import Optional

import gspread
import google.auth._helpers as _google_helpers
from google.oauth2.service_account import Credentials

from config import GOOGLE_SERVICE_ACCOUNT_JSON, GOOGLE_SHEETS_ID, MONTH_SHEET_NAMES
from models import Receipt

logger = logging.getLogger(__name__)


# ─── Clock skew compensation ──────────────────────────────────────────────────

_clock_skew_applied = False


def _apply_clock_skew_fix():
    """Compensate for system clock drift vs. Google servers.
    Google OAuth rejects JWTs when iat differs by more than 5 minutes.
    """
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
                logger.warning(
                    "Clock skew with Google servers: %.0f sec. Applying compensation.", skew_secs
                )
                _orig_utcnow = _google_helpers.utcnow

                def _patched_utcnow():
                    return _orig_utcnow() + timedelta(seconds=skew_secs)

                _google_helpers.utcnow = _patched_utcnow
            _clock_skew_applied = True
    except Exception as e:
        logger.debug("Could not check Google server time: %s", e)


_apply_clock_skew_fix()

# ─────────────────────────────────────────────────────────────────────────────

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",  # narrowed from full drive access
]

HEADER_ROW = 5       # строка с заголовками колонок
DATA_START_ROW = 6   # первая строка данных


def _get_client() -> gspread.Client:
    creds = Credentials.from_service_account_file(GOOGLE_SERVICE_ACCOUNT_JSON, scopes=SCOPES)
    return gspread.authorize(creds)


def _get_sheet_name(receipt_date: Optional[date]) -> str:
    if receipt_date:
        return MONTH_SHEET_NAMES.get(receipt_date.month, "Jan")
    from datetime import date as date_cls
    return MONTH_SHEET_NAMES.get(date_cls.today().month, "Jan")


# Cache of column maps per worksheet tab name — avoids redundant API calls
_col_cache: dict[str, tuple[dict, dict]] = {}

# Serializes concurrent writes — prevents two receipts landing on the same row
_sheets_lock = asyncio.Lock()


def clear_column_cache():
    """Clear the column map cache (call if spreadsheet structure changes)."""
    _col_cache.clear()


def _build_column_maps(worksheet) -> tuple[dict, dict]:
    """Read header row and build column index maps for both blocks.
    Results are cached by sheet tab name to avoid redundant API calls.

    Returns (left_cols, right_cols) where keys are:
      beleg, datum, transaktion, kategorie, netto, ust, gesamt, website
    Values are 1-based column numbers.
    """
    key = worksheet.title
    if key not in _col_cache:
        _col_cache[key] = _compute_column_maps(worksheet)
    return _col_cache[key]


def _compute_column_maps(worksheet) -> tuple[dict, dict]:
    """Actually fetch the header row and compute column positions."""
    headers = worksheet.row_values(HEADER_ROW)

    # Find where the right block starts — by the "Website" column
    right_block_start_idx = None
    for i, h in enumerate(headers):
        if h.strip().lower() == "website":
            right_block_start_idx = i
            break

    left_cols: dict[str, int] = {}
    right_cols: dict[str, int] = {}

    for i, h in enumerate(headers):
        col = i + 1  # 1-based
        h_norm = h.strip().lower()

        # Determine which block this column belongs to
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

    logger.debug("Left block columns: %s", left_cols)
    logger.debug("Right block columns: %s", right_cols)
    return left_cols, right_cols


def _find_gesamt_row(worksheet, check_col: int) -> int:
    """Find the totals row (Gesamt/Summe). Searches from the bottom up."""
    all_values = worksheet.col_values(check_col)
    for i in range(len(all_values) - 1, DATA_START_ROW - 2, -1):
        val = str(all_values[i]).strip().lower()
        if "gesamt" in val or "summ" in val or "total" in val:
            return i + 1  # 1-based
    return 9999


def _parse_date_cell(cell_str: str) -> Optional[date]:
    """Parse a date cell in DD.MM.YYYY format."""
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
    """Find the row to insert into: sorted by date, then alphabetically by store within same date.

    Returns (row_1based, need_insert).
    """
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
            # Existing date is later — insert before it
            return i + 1, True

        if existing_date == new_date and new_store and transaktion_values:
            # Same date — sort alphabetically by store
            existing_store = ""
            if i < len(transaktion_values):
                t = transaktion_values[i] or ""
                existing_store = t.split(" – ")[0].strip().lower()
            if new_store.lower() < existing_store:
                return i + 1, True

    if last_filled_row is not None:
        next_row = last_filled_row + 1
    else:
        next_row = DATA_START_ROW

    if gesamt_row < 9999 and next_row >= gesamt_row:
        return gesamt_row, True

    return next_row, False


def _beleg_exists_in_col(worksheet, beleg: str, col_idx: int) -> bool:
    try:
        return beleg in worksheet.col_values(col_idx)
    except Exception:
        return False


def _write_row(worksheet, row: int, cols: dict, values: dict):
    """Write values to a row. values: {key -> value}."""
    cells_to_update = []
    for key, value in values.items():
        if key in cols and value is not None:
            cells_to_update.append(gspread.Cell(row, cols[key], value))
    if cells_to_update:
        worksheet.update_cells(cells_to_update, value_input_option="USER_ENTERED")


def _build_transaktion(receipt: Receipt) -> str:
    """Build the Transaktion column value: store + item list (max 100 chars)."""
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


def _sync_write_to_sheets(receipt: Receipt):
    """Synchronous write to Google Sheets (called from executor)."""
    client = _get_client()
    spreadsheet = client.open_by_key(GOOGLE_SHEETS_ID)

    sheet_name = _get_sheet_name(receipt.receipt_date)

    # Find the worksheet for the receipt's month
    try:
        worksheet = spreadsheet.worksheet(sheet_name)
    except gspread.WorksheetNotFound:
        logger.warning("Sheet '%s' not found, falling back to current month", sheet_name)
        from datetime import date as date_cls
        fallback = MONTH_SHEET_NAMES.get(date_cls.today().month, "Jan")
        try:
            worksheet = spreadsheet.worksheet(fallback)
        except gspread.WorksheetNotFound:
            worksheet = spreadsheet.get_worksheet(0)

    # Auto-detect column positions from header row (cached)
    left_cols, right_cols = _build_column_maps(worksheet)

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

        values = {
            "beleg": receipt.receipt_number,
            "datum": date_str,
            "transaktion": transaktion,
            "kategorie": receipt.category or "",
            "netto": receipt.netto or receipt.total_amount or 0,
            "ust": receipt.ust_amount or 0,
            "gesamt": receipt.total_amount or 0,
        }
        _write_row(worksheet, row, left_cols, values)
        logger.info("Income written: %s → sheet '%s' row %d", receipt.receipt_number, sheet_name, row)

    else:  # expense или unknown
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

        values = {
            "website": receipt.website or receipt.store or "",
            "beleg": receipt.receipt_number,
            "datum": date_str,
            "transaktion": transaktion,
            "kategorie": receipt.category or "",
            "netto": receipt.netto or receipt.total_amount or 0,
            "ust": receipt.ust_amount or 0,
            "gesamt": receipt.total_amount or 0,
        }
        _write_row(worksheet, row, right_cols, values)
        logger.info("Expense written: %s → sheet '%s' row %d", receipt.receipt_number, sheet_name, row)


async def write_to_sheets(receipt: Receipt, retries: int = 3) -> bool:
    """Async write to Google Sheets with retry."""
    if not GOOGLE_SHEETS_ID:
        logger.warning("GOOGLE_SHEETS_ID not set — skipping Sheets write")
        return False

    loop = asyncio.get_event_loop()
    for attempt in range(retries):
        try:
            async with _sheets_lock:
                await loop.run_in_executor(None, _sync_write_to_sheets, receipt)
            return True
        except Exception as e:
            logger.error("Sheets write error (attempt %d/%d): %s", attempt + 1, retries, e)
            if attempt < retries - 1:
                await asyncio.sleep(2)
    return False
