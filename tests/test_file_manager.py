"""Tests for file_manager.py — magic-byte validation, path guards, size checks."""
import os
import struct
import tempfile
from pathlib import Path

import pytest

from constants import (
    JPEG_MAGIC, PNG_MAGIC, WEBP_RIFF, WEBP_MARKER, PDF_MAGIC,
    MAX_FILE_SIZE_MB,
)
from exceptions import FileValidationError
from file_manager import (
    validate_magic_bytes,
    check_file_size,
    _validate_final_path,
    _build_filename,
    delete_temp_file,
    delete_receipt_files,
    cleanup_temp_paths,
)


# ─── Magic-byte validation ─────────────────────────────────────────────────────

def _write_temp(data: bytes, suffix: str = ".bin") -> str:
    f = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    f.write(data)
    f.close()
    return f.name


class TestValidateMagicBytes:
    def test_valid_jpeg(self):
        path = _write_temp(JPEG_MAGIC + b"\xe0\x00\x10" + b"\x00" * 10, ".jpg")
        try:
            assert validate_magic_bytes(path) == "jpeg"
        finally:
            os.unlink(path)

    def test_valid_png(self):
        path = _write_temp(PNG_MAGIC + b"\x00" * 8, ".png")
        try:
            assert validate_magic_bytes(path) == "png"
        finally:
            os.unlink(path)

    def test_valid_webp(self):
        # RIFF????WEBP — bytes 4-7 are file size (can be anything)
        data = WEBP_RIFF + b"\x00\x00\x00\x00" + WEBP_MARKER + b"\x00" * 4
        path = _write_temp(data, ".webp")
        try:
            assert validate_magic_bytes(path) == "webp"
        finally:
            os.unlink(path)

    def test_valid_pdf(self):
        path = _write_temp(PDF_MAGIC + b"-1.4\n", ".pdf")
        try:
            assert validate_magic_bytes(path) == "pdf"
        finally:
            os.unlink(path)

    def test_invalid_magic_raises(self):
        path = _write_temp(b"\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f")
        try:
            with pytest.raises(FileValidationError, match="magic bytes"):
                validate_magic_bytes(path)
        finally:
            os.unlink(path)

    def test_text_file_raises(self):
        path = _write_temp(b"Hello world, this is not an image.")
        try:
            with pytest.raises(FileValidationError):
                validate_magic_bytes(path)
        finally:
            os.unlink(path)

    def test_missing_file_raises(self):
        with pytest.raises(FileValidationError, match="Cannot read"):
            validate_magic_bytes("/nonexistent/path/file.jpg")

    def test_empty_file_raises(self):
        path = _write_temp(b"")
        try:
            with pytest.raises(FileValidationError):
                validate_magic_bytes(path)
        finally:
            os.unlink(path)

    def test_webp_wrong_marker_raises(self):
        # RIFF header but WEBX instead of WEBP
        data = WEBP_RIFF + b"\x00\x00\x00\x00" + b"WEBX" + b"\x00" * 4
        path = _write_temp(data)
        try:
            with pytest.raises(FileValidationError):
                validate_magic_bytes(path)
        finally:
            os.unlink(path)


# ─── Path traversal guard ─────────────────────────────────────────────────────

class TestValidateFinalPath:
    def test_valid_path_passes(self, tmp_path):
        valid = str(tmp_path / "sub" / "file.jpg")
        _validate_final_path(valid, str(tmp_path))  # should not raise

    def test_escape_raises(self, tmp_path):
        bad = str(tmp_path.parent / "other" / "file.jpg")
        with pytest.raises(FileValidationError, match="escapes"):
            _validate_final_path(bad, str(tmp_path))

    def test_exact_base_passes(self, tmp_path):
        _validate_final_path(str(tmp_path), str(tmp_path))


# ─── Filename builder ─────────────────────────────────────────────────────────

class TestBuildFilename:
    def test_basic_filename(self):
        name = _build_filename("2024-01-001", "rewe", ".jpg", 0)
        assert name.startswith("2024-01-001_rewe")
        assert name.endswith(".jpg")

    def test_index_appended_when_nonzero(self):
        name = _build_filename("2024-01-001", "rewe", ".jpg", 2)
        assert "_2" in name

    def test_filename_length_respects_max(self):
        from constants import MAX_FILENAME_LEN
        name = _build_filename("2024-01-001", "a" * 50, ".jpg", 0)
        assert len(name) <= MAX_FILENAME_LEN

    def test_invalid_receipt_number_raises(self):
        with pytest.raises(FileValidationError, match="Invalid receipt_number"):
            _build_filename("../bad", "store", ".jpg")


# ─── Size check ───────────────────────────────────────────────────────────────

class TestCheckFileSize:
    def test_within_limit(self):
        assert check_file_size(1 * 1024 * 1024) is True

    def test_exactly_at_limit(self):
        assert check_file_size(MAX_FILE_SIZE_MB * 1024 * 1024) is True

    def test_over_limit(self):
        assert check_file_size((MAX_FILE_SIZE_MB + 1) * 1024 * 1024) is False

    def test_zero_bytes(self):
        assert check_file_size(0) is True


# ─── Delete helpers ───────────────────────────────────────────────────────────

class TestDeleteHelpers:
    def test_delete_temp_file(self, tmp_path):
        f = tmp_path / "temp.jpg"
        f.write_bytes(b"data")
        delete_temp_file(str(f))
        assert not f.exists()

    def test_delete_temp_file_nonexistent_no_raise(self):
        delete_temp_file("/nonexistent/path.jpg")  # must not raise

    def test_delete_receipt_files_valid(self, tmp_path, monkeypatch):
        import file_manager
        monkeypatch.setattr(file_manager, "RECEIPTS_FOLDER", str(tmp_path))
        f = tmp_path / "receipt.jpg"
        f.write_bytes(b"data")
        delete_receipt_files([str(f)])
        assert not f.exists()

    def test_delete_receipt_files_outside_folder_skipped(self, tmp_path, monkeypatch):
        import file_manager
        monkeypatch.setattr(file_manager, "RECEIPTS_FOLDER", str(tmp_path / "receipts"))
        # File exists but is outside RECEIPTS_FOLDER
        outside = tmp_path / "other" / "secret.jpg"
        outside.parent.mkdir(parents=True)
        outside.write_bytes(b"data")
        delete_receipt_files([str(outside)])
        assert outside.exists()  # should NOT be deleted

    def test_cleanup_temp_paths(self, tmp_path):
        files = []
        for i in range(3):
            f = tmp_path / f"temp_{i}.jpg"
            f.write_bytes(b"data")
            files.append(str(f))
        cleanup_temp_paths(files)
        for f in files:
            assert not Path(f).exists()
