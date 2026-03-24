"""File manager — safe download, magic-byte validation, permanent storage, cleanup.

Security fixes applied:
  BUG-01  Pure-Python magic-byte validation (no libmagic dependency).
  BUG-11  Cascade delete: deleting a receipt also removes its files from disk.
          Path traversal double-check with realpath-based guard.
  ZIP-bomb guard for PDF extraction (checked by message_handler).
  Temp-file tracking set per session (managed by callers).
  All directories created with restricted permissions (0o700 on POSIX).
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import stat
import sys
from pathlib import Path
from typing import Optional

import aiofiles

from config import RECEIPTS_FOLDER, TEMP_FOLDER, MAX_FILE_SIZE_MB
from constants import (
    JPEG_MAGIC,
    PNG_MAGIC,
    WEBP_RIFF,
    WEBP_MARKER,
    PDF_MAGIC,
    MAGIC_READ_BYTES,
    MAX_FILENAME_LEN,
)
from exceptions import FileValidationError
from utils import sanitize_store_name, safe_file_path

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS: frozenset[str] = frozenset({".jpg", ".jpeg", ".png", ".pdf", ".webp"})

# ─── Directory setup ──────────────────────────────────────────────────────────


def _secure_mkdir(path: Path) -> None:
    """Create directory with restricted permissions (0o700 on POSIX)."""
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform != "win32":
        try:
            os.chmod(str(path), stat.S_IRWXU)
        except OSError:
            pass


def ensure_dirs() -> None:
    _secure_mkdir(Path(RECEIPTS_FOLDER))
    _secure_mkdir(Path(TEMP_FOLDER))


# ─── Magic-byte validation (BUG-01) ──────────────────────────────────────────


def validate_magic_bytes(path: str) -> str:
    """Read the first 16 bytes and validate against known file signatures.

    Returns the detected type string: 'jpeg', 'png', 'webp', 'pdf'.
    Raises FileValidationError if the signature is not recognised.
    """
    try:
        with open(path, "rb") as f:
            header = f.read(MAGIC_READ_BYTES)
    except OSError as exc:
        raise FileValidationError(f"Cannot read file for validation: {exc}") from exc

    if header[:3] == JPEG_MAGIC:
        return "jpeg"
    if header[:8] == PNG_MAGIC:
        return "png"
    if header[:4] == WEBP_RIFF and header[8:12] == WEBP_MARKER:
        return "webp"
    if header[:5] == PDF_MAGIC:
        return "pdf"

    raise FileValidationError(
        f"File {Path(path).name!r} has unrecognised magic bytes: {header[:8].hex()!r}"
    )


def _validate_final_path(final_path: str, expected_base: str) -> None:
    """Second-layer path traversal guard using realpath (BUG-01 double-check)."""
    real = os.path.realpath(final_path)
    real_base = os.path.realpath(expected_base)
    if not (real.startswith(real_base + os.sep) or real == real_base):
        raise FileValidationError(
            f"Security: resolved path {real!r} escapes expected base {real_base!r}"
        )


# ─── Directory helpers ────────────────────────────────────────────────────────


def _receipt_dir(year: int, month: int, receipt_type: str) -> Path:
    folder_type = "expense" if receipt_type == "expense" else "income"
    path = Path(RECEIPTS_FOLDER) / str(year) / f"{month:02d}" / folder_type
    _secure_mkdir(path)
    return path


def _build_filename(receipt_number: str, store: Optional[str], ext: str, index: int = 0) -> str:
    if not re.match(r"^[\w\-]+$", receipt_number):
        raise FileValidationError(f"Invalid receipt_number: {receipt_number!r}")
    store_safe = sanitize_store_name(store)
    base = f"{receipt_number}_{store_safe}" + (f"_{index}" if index > 0 else "")
    # Enforce MAX_FILENAME_LEN: trim base to leave room for ext
    max_base = MAX_FILENAME_LEN - len(ext)
    return base[:max_base] + ext


# ─── File persistence ─────────────────────────────────────────────────────────


async def save_receipt_file(
    temp_path: str,
    receipt_number: str,
    receipt_type: str,
    store: Optional[str],
    year: int,
    month: int,
    index: int = 0,
) -> str:
    """Move a validated temp file to permanent storage.

    Returns the final path string (forward slashes for cross-platform consistency).
    Raises FileValidationError on path violations.
    """
    src = Path(temp_path)
    ext = src.suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        ext = ".jpg"

    dest_dir = _receipt_dir(year, month, receipt_type)
    filename = _build_filename(receipt_number, store, ext, index)
    dest = dest_dir / filename

    # Deduplicate if file already exists
    counter = 1
    while dest.exists():
        stem = _build_filename(receipt_number, store, "", index)
        dest = dest_dir / f"{stem[:MAX_FILENAME_LEN - len(ext) - 5]}_{counter}{ext}"
        counter += 1

    # Double-check the destination is inside RECEIPTS_FOLDER
    _validate_final_path(str(dest), RECEIPTS_FOLDER)

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, shutil.move, str(src), str(dest))

    # Restrict file permissions to owner-only on POSIX (BUG-01)
    if sys.platform != "win32":
        try:
            os.chmod(str(dest), stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass

    result = str(dest).replace("\\", "/")
    logger.info("File saved: %s", result)
    return result


async def save_temp_file(data: bytes, filename: str) -> str:
    """Save bytes to a validated temporary file. Returns the path."""
    ensure_dirs()
    safe = safe_file_path(TEMP_FOLDER, filename)
    _validate_final_path(safe, TEMP_FOLDER)
    path = Path(safe)
    async with aiofiles.open(path, "wb") as f:
        await f.write(data)
    return str(path)


# ─── Deletion helpers ─────────────────────────────────────────────────────────


def delete_temp_file(path: str) -> None:
    """Silently remove a temporary file. Never raises."""
    try:
        Path(path).unlink(missing_ok=True)
    except Exception as e:
        logger.warning("Failed to delete temp file %s: %s", path, e)


def delete_receipt_files(file_paths: list[str]) -> None:
    """Delete all files associated with a receipt (BUG-11: cascade delete).

    Validates each path is within RECEIPTS_FOLDER before deletion.
    """
    for fp in file_paths:
        try:
            # Verify the file is actually inside the receipts folder
            _validate_final_path(fp, RECEIPTS_FOLDER)
            Path(fp).unlink(missing_ok=True)
            logger.info("Deleted receipt file: %s", fp)
        except FileValidationError as exc:
            logger.warning("Refusing to delete file outside receipts folder: %s — %s", fp, exc)
        except Exception as e:
            logger.warning("Failed to delete receipt file %s: %s", fp, e)


def cleanup_temp_paths(paths: list[str]) -> None:
    """Batch-cleanup a list of temp file paths. Used on error / cancel paths."""
    for p in paths:
        delete_temp_file(p)


# ─── Size check ───────────────────────────────────────────────────────────────


def check_file_size(size_bytes: int) -> bool:
    """Return True if the file is within the configured size limit."""
    return size_bytes <= MAX_FILE_SIZE_MB * 1024 * 1024
