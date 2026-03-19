"""File manager — safe download, rename to permanent storage, path traversal guard."""
import asyncio
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Optional

import aiofiles

from config import RECEIPTS_FOLDER, TEMP_FOLDER, MAX_FILE_SIZE_MB
from utils import sanitize_store_name

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".pdf", ".webp"}


def ensure_dirs():
    Path(RECEIPTS_FOLDER).mkdir(parents=True, exist_ok=True)
    Path(TEMP_FOLDER).mkdir(parents=True, exist_ok=True)


def _receipt_dir(year: int, month: int, receipt_type: str) -> Path:
    folder_type = "expense" if receipt_type == "expense" else "income"
    path = Path(RECEIPTS_FOLDER) / str(year) / f"{month:02d}" / folder_type
    path.mkdir(parents=True, exist_ok=True)
    return path


def _build_filename(receipt_number: str, store: Optional[str], ext: str, index: int = 0) -> str:
    # Validate receipt_number to prevent path traversal
    if not re.match(r'^[\w\-]+$', receipt_number):
        raise ValueError(f"Invalid receipt_number: {receipt_number!r}")
    store_safe = sanitize_store_name(store)
    if index > 0:
        return f"{receipt_number}_{store_safe}_{index}{ext}"
    return f"{receipt_number}_{store_safe}{ext}"


async def save_receipt_file(
    temp_path: str,
    receipt_number: str,
    receipt_type: str,
    store: Optional[str],
    year: int,
    month: int,
    index: int = 0,
) -> str:
    """Move file from temp to permanent storage. Returns the final path."""
    src = Path(temp_path)
    ext = src.suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        ext = ".jpg"

    dest_dir = _receipt_dir(year, month, receipt_type)
    filename = _build_filename(receipt_number, store, ext, index)
    dest = dest_dir / filename

    # If file already exists, add a suffix
    counter = 1
    while dest.exists():
        stem = _build_filename(receipt_number, store, "", index)
        dest = dest_dir / f"{stem}_{counter}{ext}"
        counter += 1

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, shutil.move, str(src), str(dest))
    # Normalize to forward slashes for cross-platform consistency
    result = str(dest).replace("\\", "/")
    logger.info("File saved: %s", result)
    return result


async def save_temp_file(data: bytes, filename: str) -> str:
    """Save bytes to a temporary file. Returns the path."""
    ensure_dirs()
    from utils import safe_file_path
    safe = safe_file_path(TEMP_FOLDER, filename)
    path = Path(safe)
    async with aiofiles.open(path, "wb") as f:
        await f.write(data)
    return str(path)


def delete_temp_file(path: str):
    try:
        Path(path).unlink(missing_ok=True)
    except Exception as e:
        logger.warning("Failed to delete temp file %s: %s", path, e)


def check_file_size(size_bytes: int) -> bool:
    """Return True if file is within the size limit."""
    return size_bytes <= MAX_FILE_SIZE_MB * 1024 * 1024


def delete_receipt_files(file_paths: list[str]):
    """Delete all files associated with a receipt (on cancellation)."""
    for fp in file_paths:
        try:
            Path(fp).unlink(missing_ok=True)
            logger.info("Deleted receipt file: %s", fp)
        except Exception as e:
            logger.warning("Failed to delete %s: %s", fp, e)
