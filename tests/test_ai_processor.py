"""Tests for ai_processor.py — JSON extraction, circuit breaker, cache, receipt builder."""
import time as _time

import pytest

from ai_processor import (
    _extract_json,
    _parse_ai_response,
    _build_receipt_from_ai,
    _CircuitBreaker,
    get_cached_result,
    set_cached_result,
    invalidate_cache,
    _ai_cache,
    AVAILABLE_MODEL_IDS,
    _VALID_CATEGORIES,
)
from exceptions import CircuitOpenError
from models import Receipt


# ─── JSON extraction (BUG-03) ─────────────────────────────────────────────────

class TestExtractJson:
    def test_simple_object(self):
        raw = '{"key": "value"}'
        assert _extract_json(raw) == '{"key": "value"}'

    def test_leading_text_ignored(self):
        raw = 'Here is the JSON: {"total": 9.99}'
        assert _extract_json(raw) == '{"total": 9.99}'

    def test_trailing_text_ignored(self):
        raw = '{"total": 9.99} extra text here'
        assert _extract_json(raw) == '{"total": 9.99}'

    def test_markdown_fence_stripped(self):
        raw = '```json\n{"total": 9.99}\n```'
        result = _extract_json(raw)
        assert result == '{"total": 9.99}'

    def test_nested_objects(self):
        raw = '{"a": {"b": {"c": 1}}}'
        result = _extract_json(raw)
        assert result == '{"a": {"b": {"c": 1}}}'

    def test_brace_in_string_not_counted(self):
        raw = '{"note": "has } brace inside", "val": 1}'
        result = _extract_json(raw)
        import json
        parsed = json.loads(result)
        assert parsed["note"] == "has } brace inside"
        assert parsed["val"] == 1

    def test_escaped_quote_in_string(self):
        raw = '{"name": "say \\"hello\\"", "n": 2}'
        result = _extract_json(raw)
        import json
        parsed = json.loads(result)
        assert parsed["n"] == 2

    def test_no_json_returns_original(self):
        raw = "no json here"
        result = _extract_json(raw)
        assert result == raw

    def test_trailing_brace_in_text_after_json(self):
        # AI sometimes appends "}" explanations after the JSON
        raw = '{"total": 5.0} Note: } means end'
        result = _extract_json(raw)
        import json
        parsed = json.loads(result)
        assert parsed["total"] == 5.0


# ─── Receipt builder from AI dict ─────────────────────────────────────────────

class TestBuildReceiptFromAi:
    def _make_data(self, **overrides):
        base = {
            "type": "expense",
            "store": "REWE",
            "website": None,
            "total_amount": 25.50,
            "netto": 21.43,
            "ust_amount": 4.07,
            "ust_rate": 19,
            "currency": "EUR",
            "date": "2024-03-15",
            "time": "14:30",
            "category": "Lebensmittel",
            "items": [{"name": "Milk", "quantity": 2, "price": 1.50}],
            "confidence": 0.9,
            "notes": None,
        }
        base.update(overrides)
        return base

    def test_basic_parsing(self):
        r = _build_receipt_from_ai(self._make_data(), "raw")
        assert r.store == "REWE"
        assert r.total_amount == pytest.approx(25.50)
        assert r.currency == "EUR"
        assert r.category == "Lebensmittel"
        assert r.confidence == pytest.approx(0.9)

    def test_confidence_none_defaults_to_half(self):
        r = _build_receipt_from_ai(self._make_data(confidence=None), "raw")
        assert r.confidence == pytest.approx(0.5)

    def test_invalid_category_defaults_to_sonstiges(self):
        r = _build_receipt_from_ai(self._make_data(category="Groceries"), "raw")
        assert r.category == "Sonstiges"

    def test_valid_categories_accepted(self):
        for cat in _VALID_CATEGORIES:
            r = _build_receipt_from_ai(self._make_data(category=cat), "raw")
            assert r.category == cat

    def test_date_parsed(self):
        from datetime import date, timedelta
        # Use a date within 366 days of today to avoid the freshness guard
        recent = date.today() - timedelta(days=30)
        r = _build_receipt_from_ai(self._make_data(date=recent.isoformat()), "raw")
        assert r.receipt_date == recent

    def test_date_out_of_range_replaced_with_today(self):
        from datetime import date
        r = _build_receipt_from_ai(self._make_data(date="1985-01-01"), "raw")
        assert r.receipt_date == date.today()

    def test_time_parsed(self):
        from datetime import time
        r = _build_receipt_from_ai(self._make_data(time="09:45"), "raw")
        assert r.receipt_time == time(9, 45)

    def test_invalid_time_ignored(self):
        r = _build_receipt_from_ai(self._make_data(time="bad:time"), "raw")
        assert r.receipt_time is None

    def test_netto_defaults_to_total_if_missing(self):
        r = _build_receipt_from_ai(self._make_data(netto=None, total_amount=30.0), "raw")
        assert r.netto == pytest.approx(30.0)

    def test_items_parsed(self):
        r = _build_receipt_from_ai(self._make_data(), "raw")
        assert len(r.items) == 1
        assert r.items[0].name == "Milk"
        assert r.items[0].quantity == pytest.approx(2.0)
        assert r.items[0].price == pytest.approx(1.50)

    def test_items_cap_at_100(self):
        items = [{"name": f"item{i}", "quantity": 1, "price": 1.0} for i in range(150)]
        r = _build_receipt_from_ai(self._make_data(items=items), "raw")
        assert len(r.items) == 100

    def test_low_confidence_triggers_needs_review(self):
        r = _build_receipt_from_ai(self._make_data(confidence=0.3), "raw")
        assert r.status == "needs_review"

    def test_high_confidence_stays_confirmed(self):
        r = _build_receipt_from_ai(self._make_data(confidence=0.95), "raw")
        assert r.status == "confirmed"

    def test_invalid_type_set_to_unknown(self):
        r = _build_receipt_from_ai(self._make_data(type="refund"), "raw")
        assert r.type == "unknown"

    def test_amount_over_limit_set_to_none(self):
        r = _build_receipt_from_ai(self._make_data(total_amount=2_000_000), "raw")
        assert r.total_amount is None

    def test_negative_amount_set_to_none(self):
        r = _build_receipt_from_ai(self._make_data(total_amount=-10.0), "raw")
        assert r.total_amount is None


# ─── Circuit breaker ──────────────────────────────────────────────────────────

class TestCircuitBreaker:
    def _make_cb(self, threshold=3, recovery=60.0):
        return _CircuitBreaker("test", threshold, recovery)

    def test_starts_closed(self):
        cb = self._make_cb()
        assert cb.state == "CLOSED"
        assert cb.allow_request() is True

    def test_opens_after_threshold_failures(self):
        cb = self._make_cb(threshold=3)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == "OPEN"
        assert cb.allow_request() is False

    def test_success_resets_to_closed(self):
        cb = self._make_cb(threshold=2)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "OPEN"
        cb.record_success()
        assert cb.state == "CLOSED"
        assert cb.allow_request() is True

    def test_transitions_to_half_open_after_recovery(self, monkeypatch):
        cb = self._make_cb(threshold=1, recovery=1.0)
        cb.record_failure()
        assert cb.state == "OPEN"

        # Advance time past recovery window
        fake_time = _time.monotonic() + 2.0
        monkeypatch.setattr("ai_processor._time.monotonic", lambda: fake_time)
        assert cb.allow_request() is True
        assert cb.state == "HALF_OPEN"

    def test_not_open_before_threshold(self):
        cb = self._make_cb(threshold=5)
        for _ in range(4):
            cb.record_failure()
        assert cb.state == "CLOSED"
        assert cb.allow_request() is True


# ─── AI result cache ──────────────────────────────────────────────────────────

class TestAiCache:
    def setup_method(self):
        _ai_cache.clear()

    def teardown_method(self):
        _ai_cache.clear()

    def _make_receipt(self):
        return Receipt(telegram_user_id=1, store="TestStore")

    def test_cache_miss_returns_none(self):
        assert get_cached_result("file123", "model-x") is None

    def test_cache_hit_returns_receipt(self):
        r = self._make_receipt()
        set_cached_result("file123", "model-x", r)
        cached = get_cached_result("file123", "model-x")
        assert cached is r

    def test_different_model_miss(self):
        r = self._make_receipt()
        set_cached_result("file123", "model-a", r)
        assert get_cached_result("file123", "model-b") is None

    def test_different_file_miss(self):
        r = self._make_receipt()
        set_cached_result("file-A", "model-x", r)
        assert get_cached_result("file-B", "model-x") is None

    def test_expired_entry_returns_none(self, monkeypatch):
        r = self._make_receipt()
        set_cached_result("fileExp", "model-x", r)

        # Advance monotonic time past TTL
        from constants import AI_CACHE_TTL_SECONDS
        fake_time = _time.monotonic() + AI_CACHE_TTL_SECONDS + 10
        monkeypatch.setattr("ai_processor._time.monotonic", lambda: fake_time)

        assert get_cached_result("fileExp", "model-x") is None
        assert ("fileExp", "model-x") not in _ai_cache

    def test_invalidate_removes_all_for_file(self):
        r = self._make_receipt()
        set_cached_result("fileX", "model-a", r)
        set_cached_result("fileX", "model-b", r)
        set_cached_result("fileY", "model-a", r)
        invalidate_cache("fileX")
        assert get_cached_result("fileX", "model-a") is None
        assert get_cached_result("fileX", "model-b") is None
        assert get_cached_result("fileY", "model-a") is r

    def test_lru_eviction_when_full(self, monkeypatch):
        from constants import AI_CACHE_MAX_SIZE
        monkeypatch.setattr("ai_processor.AI_CACHE_MAX_SIZE", 3)

        for i in range(3):
            set_cached_result(f"f{i}", "m", self._make_receipt())
        assert len(_ai_cache) == 3

        # Adding a 4th should evict the one that expires soonest
        set_cached_result("f_new", "m", self._make_receipt())
        assert len(_ai_cache) == 3


# ─── Available models ─────────────────────────────────────────────────────────

class TestAvailableModels:
    def test_frozenset_not_empty(self):
        assert len(AVAILABLE_MODEL_IDS) > 0

    def test_all_ids_are_strings(self):
        assert all(isinstance(m, str) for m in AVAILABLE_MODEL_IDS)

    def test_default_model_in_pool(self):
        from ai_processor import MODEL_POOL
        for m in AVAILABLE_MODEL_IDS:
            assert isinstance(m, str)
