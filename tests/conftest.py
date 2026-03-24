"""Pytest configuration and shared fixtures.

Sets required environment variables BEFORE any app module is imported,
since config.py calls sys.exit() at module level if they are missing.
"""
import os
import sys
import tempfile

# ── Must happen before any app imports ─────────────────────────────────────────
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
os.environ.setdefault("OPENROUTER_API_KEY", "sk-test-0000000000000000000000000000")

# Ensure the project root is on sys.path so `import config` etc. work
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import pytest


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """Patch database.DB_PATH to an isolated temp file and initialise the schema."""
    db_file = str(tmp_path / "test.db")
    import database
    monkeypatch.setattr(database, "DB_PATH", db_file)
    # Also patch the config value read by get_conn() / save_receipt_atomic()
    import config
    monkeypatch.setattr(config, "DB_PATH", db_file)
    database.init_db()
    return db_file


@pytest.fixture()
def tmp_receipts(tmp_path, monkeypatch):
    """Patch RECEIPTS_FOLDER and TEMP_FOLDER to isolated temp directories."""
    receipts_dir = str(tmp_path / "receipts")
    temp_dir = str(tmp_path / "temp")
    os.makedirs(receipts_dir, exist_ok=True)
    os.makedirs(temp_dir, exist_ok=True)

    import config
    import file_manager
    monkeypatch.setattr(config, "RECEIPTS_FOLDER", receipts_dir)
    monkeypatch.setattr(file_manager, "RECEIPTS_FOLDER", receipts_dir)
    monkeypatch.setattr(file_manager, "TEMP_FOLDER", temp_dir)
    return receipts_dir, temp_dir
