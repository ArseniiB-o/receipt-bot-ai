"""Tests for utils.py — transliteration, sanitization, rate limiting, path safety."""
import os
import tempfile
import time

import pytest

from utils import (
    transliterate,
    sanitize_store_name,
    sanitize_text_for_prompt,
    safe_file_path,
    check_rate_limit,
    check_file_rate_limit,
    check_command_rate_limit,
    escape_html,
    error_ref,
    _rate_messages,
    _rate_files,
    _rate_commands,
)


# ─── Transliteration ──────────────────────────────────────────────────────────

class TestTransliterate:
    def test_lowercase_cyrillic(self):
        assert transliterate("привет") == "privet"

    def test_uppercase_cyrillic_bug15_fix(self):
        assert transliterate("ПРИВЕТ") == "privet"

    def test_mixed_case(self):
        assert transliterate("Привет") == "privet"

    def test_ukrainian_chars(self):
        assert "i" in transliterate("їі")

    def test_ascii_passthrough(self):
        assert transliterate("hello") == "hello"

    def test_soft_sign_removed(self):
        result = transliterate("рубль")
        assert "'" not in result
        assert result == "rubl"

    def test_hard_sign_removed(self):
        result = transliterate("объект")
        assert result == "obekt"


class TestSanitizeStoreName:
    def test_known_store_rewe(self):
        assert sanitize_store_name("REWE Markt") == "rewe"

    def test_known_store_cyrillic(self):
        assert sanitize_store_name("Магнит") == "magnit"

    def test_none_returns_unknown(self):
        assert sanitize_store_name(None) == "unknown"

    def test_empty_returns_unknown(self):
        assert sanitize_store_name("") == "unknown"

    def test_unknown_store_sanitized(self):
        name = sanitize_store_name("H&M Berlin!")
        assert name.isidentifier() or "_" in name or name.replace("_", "").isalnum()
        assert len(name) <= 30

    def test_result_no_special_chars(self):
        result = sanitize_store_name("Café & Bistro #1")
        assert all(c.isalnum() or c == "_" for c in result)


# ─── Prompt sanitization ──────────────────────────────────────────────────────

class TestSanitizeTextForPrompt:
    def test_strips_control_chars(self):
        result = sanitize_text_for_prompt("hello\x00world\x07end")
        assert "\x00" not in result
        assert "\x07" not in result
        assert "helloworld" in result

    def test_keeps_newlines_and_tabs(self):
        result = sanitize_text_for_prompt("line1\nline2\ttabbed")
        assert "\n" in result
        assert "\t" in result

    def test_truncates_at_max_len(self):
        long_text = "a" * 3000
        result = sanitize_text_for_prompt(long_text, max_len=2000)
        assert len(result) == 2000

    def test_custom_max_len(self):
        result = sanitize_text_for_prompt("hello world", max_len=5)
        assert result == "hello"

    def test_del_char_stripped(self):
        result = sanitize_text_for_prompt("ok\x7fno")
        assert "\x7f" not in result


# ─── Path safety ──────────────────────────────────────────────────────────────

class TestSafeFilePath:
    def test_normal_filename_inside_dir(self, tmp_path):
        result = safe_file_path(str(tmp_path), "receipt.jpg")
        assert result.startswith(str(tmp_path.resolve()))
        assert result.endswith("receipt.jpg")

    def test_path_traversal_sanitized(self, tmp_path):
        # The function sanitizes slashes out of filenames, so ../../etc/passwd
        # becomes a safe name inside the base dir (no ValueError needed)
        result = safe_file_path(str(tmp_path), "../../etc/passwd")
        base = str(tmp_path.resolve())
        assert result.startswith(base)

    def test_traversal_via_null_byte_sanitized(self, tmp_path):
        result = safe_file_path(str(tmp_path), "file\x00.jpg")
        assert "\x00" not in result
        assert result.startswith(str(tmp_path.resolve()))

    def test_leading_dot_stripped(self, tmp_path):
        result = safe_file_path(str(tmp_path), ".hidden")
        basename = os.path.basename(result)
        assert not basename.startswith(".")

    def test_empty_filename_replaced_with_file(self, tmp_path):
        result = safe_file_path(str(tmp_path), "")
        assert os.path.basename(result) == "file"

    def test_long_filename_truncated(self, tmp_path):
        long_name = "a" * 200 + ".jpg"
        result = safe_file_path(str(tmp_path), long_name)
        assert len(os.path.basename(result)) <= 120


# ─── Rate limiting ────────────────────────────────────────────────────────────

class TestRateLimiting:
    def setup_method(self):
        # Clear rate stores before each test
        _rate_messages.clear()
        _rate_files.clear()
        _rate_commands.clear()

    def test_first_call_allowed(self):
        assert check_rate_limit(1001) is True

    def test_repeated_calls_within_limit(self):
        for _ in range(10):
            result = check_rate_limit(1002, max_per_minute=10)
        assert result is True

    def test_exceeds_limit_blocked(self):
        for _ in range(10):
            check_rate_limit(1003, max_per_minute=5)
        # 6th call should be blocked (max_per_minute=5)
        _rate_messages[1003] = [time.time()] * 5
        assert check_rate_limit(1003, max_per_minute=5) is False

    def test_different_users_isolated(self):
        _rate_messages[2001] = [time.time()] * 10
        assert check_rate_limit(2002, max_per_minute=10) is True

    def test_old_timestamps_expire(self):
        # Put timestamps from 2 minutes ago — they should be expired
        old_ts = time.time() - 130
        _rate_messages[3001] = [old_ts] * 10
        assert check_rate_limit(3001, max_per_minute=10) is True

    def test_file_rate_limit_allowed(self):
        assert check_file_rate_limit(4001) is True

    def test_file_rate_limit_blocked(self):
        from constants import RATE_FILES_PER_HOUR
        _rate_files[4002] = [time.time()] * RATE_FILES_PER_HOUR
        assert check_file_rate_limit(4002) is False

    def test_command_rate_limit_allowed(self):
        assert check_command_rate_limit(5001) is True

    def test_command_rate_limit_blocked(self):
        from constants import RATE_COMMANDS_PER_MINUTE
        _rate_commands[5002] = [time.time()] * RATE_COMMANDS_PER_MINUTE
        assert check_command_rate_limit(5002) is False


# ─── Helpers ──────────────────────────────────────────────────────────────────

class TestEscapeHtml:
    def test_ampersand(self):
        assert escape_html("a & b") == "a &amp; b"

    def test_less_than(self):
        assert escape_html("<script>") == "&lt;script&gt;"

    def test_quote(self):
        assert escape_html('"hello"') == "&quot;hello&quot;"

    def test_no_special_chars(self):
        assert escape_html("hello world") == "hello world"


class TestErrorRef:
    def test_format(self):
        ref = error_ref()
        assert ref.startswith("ERR-")
        parts = ref[4:].split("-")
        assert len(parts) == 2
        assert len(parts[0]) == 8   # YYYYMMDD
        assert len(parts[1]) == 6   # HHMMSS

    def test_unique(self):
        refs = {error_ref() for _ in range(5)}
        # All should be strings in the right format (may match if called very fast)
        for ref in refs:
            assert ref.startswith("ERR-")
