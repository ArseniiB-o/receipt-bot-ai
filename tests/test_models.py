"""Tests for models.py — Receipt and ReceiptItem dataclass validation."""
import pytest
from datetime import date, time

from models import Receipt, ReceiptItem


class TestReceiptItem:
    def test_valid_item(self):
        item = ReceiptItem(name="Milk", quantity=2.0, price=1.50)
        assert item.name == "Milk"
        assert item.quantity == 2.0
        assert item.price == 1.50

    def test_non_string_name_coerced(self):
        item = ReceiptItem(name=42)
        assert item.name == "42"

    def test_name_capped_at_200_chars(self):
        long_name = "x" * 300
        item = ReceiptItem(name=long_name)
        assert len(item.name) == 200

    def test_zero_quantity_defaults_to_one(self):
        item = ReceiptItem(name="item", quantity=0)
        assert item.quantity == 1.0

    def test_negative_quantity_defaults_to_one(self):
        item = ReceiptItem(name="item", quantity=-5.0)
        assert item.quantity == 1.0

    def test_invalid_quantity_string_defaults_to_one(self):
        item = ReceiptItem(name="item", quantity="abc")
        assert item.quantity == 1.0

    def test_negative_price_defaults_to_zero(self):
        item = ReceiptItem(name="item", price=-9.99)
        assert item.price == 0.0

    def test_invalid_price_defaults_to_zero(self):
        item = ReceiptItem(name="item", price=None)
        assert item.price == 0.0

    def test_string_price_parsed(self):
        item = ReceiptItem(name="item", price="3.99")
        assert item.price == pytest.approx(3.99)


class TestReceipt:
    def test_default_receipt(self):
        r = Receipt(telegram_user_id=100)
        assert r.type == "expense"
        assert r.currency == "EUR"
        assert r.confidence == 0.5
        assert r.status == "confirmed"

    def test_confidence_clamped_to_zero_one(self):
        r = Receipt(telegram_user_id=1, confidence=2.5)
        assert r.confidence == 1.0
        r2 = Receipt(telegram_user_id=1, confidence=-0.3)
        assert r2.confidence == 0.0

    def test_invalid_confidence_defaults_to_half(self):
        r = Receipt(telegram_user_id=1, confidence="bad")
        assert r.confidence == 0.5

    def test_invalid_type_set_to_unknown(self):
        r = Receipt(telegram_user_id=1, type="refund")
        assert r.type == "unknown"

    def test_valid_types_accepted(self):
        for t in ("expense", "income", "unknown"):
            assert Receipt(telegram_user_id=1, type=t).type == t

    def test_empty_currency_defaults_to_eur(self):
        r = Receipt(telegram_user_id=1, currency="")
        assert r.currency == "EUR"

    def test_none_currency_defaults_to_eur(self):
        r = Receipt(telegram_user_id=1, currency=None)
        assert r.currency == "EUR"

    def test_currency_capped_at_10_chars(self):
        r = Receipt(telegram_user_id=1, currency="TOOLONGCURRENCY")
        assert len(r.currency) == 10

    def test_date_out_of_range_replaced_with_today(self):
        from datetime import date as _date
        r = Receipt(telegram_user_id=1, receipt_date=_date(1990, 1, 1))
        assert r.receipt_date == _date.today()

    def test_date_in_range_kept(self):
        from datetime import date as _date
        d = _date(2023, 6, 15)
        r = Receipt(telegram_user_id=1, receipt_date=d)
        assert r.receipt_date == d

    def test_negative_total_amount_made_positive(self):
        r = Receipt(telegram_user_id=1, total_amount=-50.0)
        assert r.total_amount == 50.0

    def test_negative_netto_made_positive(self):
        r = Receipt(telegram_user_id=1, netto=-42.0)
        assert r.netto == 42.0

    def test_negative_ust_amount_set_to_zero(self):
        r = Receipt(telegram_user_id=1, ust_amount=-5.0)
        assert r.ust_amount == 0.0

    def test_display_type_expense(self):
        r = Receipt(telegram_user_id=1, type="expense")
        assert "Расход" in r.display_type()

    def test_display_type_income(self):
        r = Receipt(telegram_user_id=1, type="income")
        assert "Приход" in r.display_type()

    def test_display_type_unknown(self):
        r = Receipt(telegram_user_id=1, type="unknown")
        assert "Неизвестно" in r.display_type()

    def test_format_amount_eur(self):
        r = Receipt(telegram_user_id=1, currency="EUR")
        result = r.format_amount(12.5)
        assert "12" in result and "€" in result

    def test_format_amount_none(self):
        r = Receipt(telegram_user_id=1)
        assert r.format_amount(None) == "—"

    def test_to_card_text_contains_type(self):
        r = Receipt(telegram_user_id=1, type="expense", total_amount=99.0)
        card = r.to_card_text()
        assert "Тип" in card
        assert "Расход" in card
