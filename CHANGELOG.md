# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [1.2.0] — 2026-03-23

### Security

- **`_is_allowed()` timing fix** — removed early `return True` inside the loop so all allowed IDs are always compared; execution time no longer reveals whether a user_id is in the allow-list
- **`RE_PHONE` regex hardened** — added `(?<!\d)` / `(?!\d)` word-boundary anchors to prevent log scrubber from matching timestamps or IDs embedded in longer digit sequences
- **Prompt injection protection** — added explicit instruction to both `AI_PROMPT` and `CHAT_PROMPT` to ignore any override instructions embedded in user-supplied data

### Added

- **Daily AI rate limit** (`RATE_AI_PER_DAY = 50`) — previously defined but not enforced; now applied per user per 24 hours before each AI call in `_process_one`
- **`check_ai_rate_limit()`** helper in `utils.py` with 24-hour sliding window
- **`ai_rate_limit` i18n key** in all three languages (RU / DE / EN)

---

## [1.1.0] — 2026-03-19

### Added

- **`/model` command** — users can select which AI model processes their receipts via an inline keyboard
- **Per-user model preference** — stored in `user_settings.model` (SQLite); overrides the round-robin MODEL_POOL when set
- **Auto mode** — selecting "Auto" reverts to the existing MODEL_POOL round-robin behaviour
- **`AVAILABLE_MODELS` export** in `ai_processor.py` — single source of truth for selectable models, shared by command and callback handlers
- **i18n strings** for model selection added in all three languages (RU / DE / EN)
- **`/model`** listed in `/help` and `/start` texts for all languages
- **Safe DB migration** — `init_db()` adds the `model` column to existing `user_settings` tables without data loss

---

## [1.0.0] — 2026-03-15

### Added

- **AI receipt parsing** — photo, PDF, and text input analyzed by OpenRouter vision models (Nemotron, Gemma 3, Mistral Small)
- **Automatic fallback chain** — switches models on rate limit or unavailability; retries with exponential back-off
- **Batch processing** — multiple receipts queued per user, processed in parallel with model pool round-robin
- **Inline editing** — edit any receipt field (store, amount, date, category, type, currency) before saving
- **SQLite storage** — atomic receipt numbering (`YYYY-MM-NNN`), WAL mode, busy timeout, duplicate guard
- **Google Sheets sync** — monthly EÜR worksheets with auto-detected column layout, date-sorted insert, duplicate skip
- **Multi-language UI** — Russian, German, English; per-user preference stored in `user_settings` table; `/language` command
- **Access control** — `ALLOWED_USER_IDS` whitelist; unauthorized users silently rejected
- **Admin commands** — `/backup` streams a zipped SQLite copy; restricted to `ADMIN_USER_ID`
- **Stats & history** — `/stats` with category breakdown; `/history` with all/mine filter; both accessible via inline buttons
- **Security hardening** — path traversal guard, magic-byte image validation, per-user rate limit (10 req/min), AI concurrency semaphore, PDF timeout, media group DoS cap, TTL batch expiry
- **Clock skew compensation** — patches `google.auth` to handle system clock drift vs Google OAuth servers
- **Logging** — rotating file handler (10 MB × 5 backups); httpx INFO suppressed to prevent token leakage
- **`start.sh` / `start.bat`** — launchers that kill stale instances before starting
- **`Makefile`** — `install`, `run`, `lint`, `test` targets
