"""Tests for database.py — schema init, receipt CRUD, atomic numbering, stats, GDPR."""
import pytest
from datetime import date

from models import Receipt, ReceiptItem
import database


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_receipt(**kwargs):
    defaults = dict(
        type="expense",
        store="TestStore",
        total_amount=19.99,
        netto=16.80,
        ust_amount=3.19,
        ust_rate=19,
        currency="EUR",
        receipt_date=date(2024, 3, 15),
        category="Lebensmittel",
        confidence=0.9,
        telegram_user_id=12345,
        telegram_username="testuser",
        added_by="testuser",
        status="confirmed",
    )
    defaults.update(kwargs)
    return Receipt(**defaults)


# ─── Schema initialization ────────────────────────────────────────────────────

class TestInitDb:
    def test_creates_tables(self, tmp_db):
        with database.get_conn() as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        expected = {
            "receipts", "user_settings", "sequences",
            "audit_trail", "dead_letters", "user_blocks",
            "pending_sheets_writes",
        }
        assert expected.issubset(tables)

    def test_idempotent(self, tmp_db):
        database.init_db()  # second call must not raise


# ─── Receipt CRUD ─────────────────────────────────────────────────────────────

class TestSaveAndFetch:
    def test_save_returns_receipt_number(self, tmp_db):
        r = _make_receipt()
        number, rowid = database.save_receipt_atomic(r, 2024, 3)
        assert number.startswith("2024-03-")
        assert rowid > 0

    def test_receipt_number_format(self, tmp_db):
        r = _make_receipt()
        number, _ = database.save_receipt_atomic(r, 2024, 3)
        parts = number.split("-")
        assert len(parts) == 3
        assert parts[0] == "2024"
        assert parts[1] == "03"
        assert int(parts[2]) >= 1

    def test_fetch_by_number(self, tmp_db):
        r = _make_receipt(store="REWE")
        number, _ = database.save_receipt_atomic(r, 2024, 3)
        row = database.get_receipt_by_number(number)
        assert row is not None
        assert row["store"] == "REWE"
        assert row["receipt_number"] == number

    def test_fetch_nonexistent_returns_none(self, tmp_db):
        assert database.get_receipt_by_number("9999-99-999") is None

    def test_delete_returns_true(self, tmp_db):
        r = _make_receipt()
        number, _ = database.save_receipt_atomic(r, 2024, 3)
        assert database.delete_receipt(number) is True
        assert database.get_receipt_by_number(number) is None

    def test_delete_nonexistent_returns_false(self, tmp_db):
        assert database.delete_receipt("9999-99-001") is False

    def test_update_file_paths(self, tmp_db):
        r = _make_receipt()
        number, _ = database.save_receipt_atomic(r, 2024, 3)
        database.update_file_paths(number, ["/data/receipts/file.jpg"])
        row = database.get_receipt_by_number(number)
        assert "/data/receipts/file.jpg" in row["file_paths"]

    def test_get_last_receipts(self, tmp_db):
        for i in range(3):
            database.save_receipt_atomic(_make_receipt(store=f"Store{i}"), 2024, 3)
        rows = database.get_last_receipts(limit=10)
        assert len(rows) == 3

    def test_get_last_receipts_filtered_by_user(self, tmp_db):
        database.save_receipt_atomic(_make_receipt(telegram_user_id=100), 2024, 3)
        database.save_receipt_atomic(_make_receipt(telegram_user_id=200), 2024, 3)
        rows = database.get_last_receipts(user_id=100)
        assert all(r["telegram_user_id"] == 100 for r in rows)
        assert len(rows) == 1

    def test_get_last_receipts_pagination(self, tmp_db):
        for i in range(5):
            database.save_receipt_atomic(_make_receipt(), 2024, 3)
        page1 = database.get_last_receipts(limit=3, offset=0)
        page2 = database.get_last_receipts(limit=3, offset=3)
        assert len(page1) == 3
        assert len(page2) == 2
        # No overlap
        nums1 = {r["receipt_number"] for r in page1}
        nums2 = {r["receipt_number"] for r in page2}
        assert nums1.isdisjoint(nums2)


# ─── Atomic receipt numbering (BUG-08) ───────────────────────────────────────

class TestAtomicNumbering:
    def test_sequential_numbering(self, tmp_db):
        numbers = []
        for _ in range(5):
            r = _make_receipt()
            num, _ = database.save_receipt_atomic(r, 2024, 3)
            numbers.append(num)
        suffixes = [int(n.split("-")[2]) for n in numbers]
        assert suffixes == list(range(1, 6))

    def test_different_months_independent(self, tmp_db):
        r1 = _make_receipt()
        r2 = _make_receipt()
        n1, _ = database.save_receipt_atomic(r1, 2024, 3)
        n2, _ = database.save_receipt_atomic(r2, 2024, 4)
        assert n1.startswith("2024-03-")
        assert n2.startswith("2024-04-")
        # Both should start at 001
        assert n1.endswith("-001")
        assert n2.endswith("-001")

    def test_sequence_survives_deletion(self, tmp_db):
        r1 = _make_receipt()
        n1, _ = database.save_receipt_atomic(r1, 2024, 5)
        database.delete_receipt(n1)
        r2 = _make_receipt()
        n2, _ = database.save_receipt_atomic(r2, 2024, 5)
        # Counter must not reuse 001 after deletion
        assert int(n2.split("-")[2]) > int(n1.split("-")[2])

    def test_numbering_beyond_999(self, tmp_db):
        # Manually set sequence counter to 999
        with database.get_conn() as conn:
            conn.execute(
                "INSERT INTO sequences (seq_key, last_value) VALUES ('2024-06', 999)"
            )
        r = _make_receipt()
        n, _ = database.save_receipt_atomic(r, 2024, 6)
        assert int(n.split("-")[2]) == 1000


# ─── Statistics (BUG-20) ─────────────────────────────────────────────────────

class TestGetStats:
    def test_stats_empty_returns_zeros(self, tmp_db):
        stats = database.get_stats(2024, 1)
        assert stats["expense_total"] == 0.0
        assert stats["expense_count"] == 0
        assert stats["income_total"] == 0.0

    def test_stats_with_data(self, tmp_db):
        database.save_receipt_atomic(_make_receipt(type="expense", total_amount=50.0), 2024, 3)
        database.save_receipt_atomic(_make_receipt(type="expense", total_amount=30.0), 2024, 3)
        database.save_receipt_atomic(_make_receipt(type="income", total_amount=200.0), 2024, 3)
        stats = database.get_stats(2024, 3)
        assert stats["expense_total"] == pytest.approx(80.0)
        assert stats["expense_count"] == 2
        assert stats["income_total"] == pytest.approx(200.0)
        assert stats["balance"] == pytest.approx(120.0)

    def test_stats_with_null_amounts(self, tmp_db):
        # BUG-20: SUM of NULL should return 0, not NULL
        database.save_receipt_atomic(_make_receipt(type="expense", total_amount=None), 2024, 7)
        stats = database.get_stats(2024, 7)
        assert stats["expense_total"] == 0.0

    def test_stats_by_user(self, tmp_db):
        database.save_receipt_atomic(
            _make_receipt(type="expense", total_amount=100.0, telegram_user_id=111), 2024, 3
        )
        database.save_receipt_atomic(
            _make_receipt(type="expense", total_amount=200.0, telegram_user_id=222), 2024, 3
        )
        stats = database.get_stats(2024, 3, user_id=111)
        assert stats["expense_total"] == pytest.approx(100.0)

    def test_stats_categories(self, tmp_db):
        database.save_receipt_atomic(
            _make_receipt(type="expense", total_amount=30.0, category="Transport"), 2024, 3
        )
        database.save_receipt_atomic(
            _make_receipt(type="expense", total_amount=20.0, category="Lebensmittel"), 2024, 3
        )
        stats = database.get_stats(2024, 3)
        cats = dict(stats["categories"])
        assert "Transport" in cats
        assert "Lebensmittel" in cats


# ─── User settings ────────────────────────────────────────────────────────────

class TestUserSettings:
    def test_default_language_ru(self, tmp_db):
        assert database.get_user_language(9999) == "ru"

    def test_set_and_get_language(self, tmp_db):
        database.set_user_language(9001, "de")
        assert database.get_user_language(9001) == "de"

    def test_has_language_set(self, tmp_db):
        assert database.has_language_set(8001) is False
        database.set_user_language(8001, "en")
        assert database.has_language_set(8001) is True

    def test_set_and_get_model(self, tmp_db):
        database.set_user_model(9002, "google/gemma-3-27b-it:free")
        assert database.get_user_model(9002) == "google/gemma-3-27b-it:free"

    def test_get_model_default_none(self, tmp_db):
        assert database.get_user_model(9999) is None


# ─── GDPR / Privacy ───────────────────────────────────────────────────────────

class TestPrivacy:
    def test_not_accepted_by_default(self, tmp_db):
        assert database.has_privacy_accepted(7001) is False

    def test_accept_and_check(self, tmp_db):
        database.set_privacy_accepted(7001, "1.0")
        assert database.has_privacy_accepted(7001) is True

    def test_accept_idempotent(self, tmp_db):
        database.set_privacy_accepted(7002, "1.0")
        database.set_privacy_accepted(7002, "1.1")
        assert database.has_privacy_accepted(7002) is True


# ─── User blocks ─────────────────────────────────────────────────────────────

class TestUserBlocks:
    def test_not_blocked_by_default(self, tmp_db):
        assert database.is_user_blocked(6001) is False

    def test_block_user(self, tmp_db):
        database.block_user(6001, blocked_by=1, reason="spam")
        assert database.is_user_blocked(6001) is True

    def test_unblock_user(self, tmp_db):
        database.block_user(6002, blocked_by=1)
        assert database.unblock_user(6002) is True
        assert database.is_user_blocked(6002) is False

    def test_unblock_nonexistent_returns_false(self, tmp_db):
        assert database.unblock_user(6999) is False


# ─── Dead letter queue ────────────────────────────────────────────────────────

class TestDeadLetters:
    def test_add_and_fetch(self, tmp_db):
        database.add_dead_letter(
            user_id=5001,
            file_path="/tmp/file.jpg",
            caption="test",
            error_message="AI failed",
            original_message_id=42,
        )
        letters = database.get_dead_letters(unresolved_only=True)
        assert len(letters) >= 1
        assert any(dl["user_id"] == 5001 for dl in letters)

    def test_resolve_dead_letter(self, tmp_db):
        database.add_dead_letter(5002, "/tmp/f.jpg", "", "error")
        letters = database.get_dead_letters(unresolved_only=True)
        dl_id = letters[-1]["id"]
        database.resolve_dead_letter(dl_id)
        # After resolving, it should not appear in unresolved list
        unresolved = database.get_dead_letters(unresolved_only=True)
        assert not any(dl["id"] == dl_id for dl in unresolved)
        # But should appear when fetching all
        all_letters = database.get_dead_letters(unresolved_only=False)
        assert any(dl["id"] == dl_id for dl in all_letters)
