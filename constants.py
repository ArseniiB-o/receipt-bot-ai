"""Centralised constants — all magic numbers and strings in one place.

Import from here rather than hard-coding values across the codebase.
"""
from __future__ import annotations

# ─── Batch / queue timing ─────────────────────────────────────────────────────
BATCH_DELAY_SECONDS: float = 4.0        # accumulation window after last incoming photo
MEDIA_GROUP_DELAY: float = 2.5          # wait for all album photos from Telegram
AI_INTER_CALL_DELAY: float = 0.5        # stagger between parallel AI calls (seconds)
BATCH_TTL_SECONDS: int = 1800           # 30 min — expire un-confirmed batches
CANCEL_WINDOW_SECONDS: int = 300        # 5 min — /cancel window (overridden by config)

# ─── Batch / receipt limits ────────────────────────────────────────────────────
MAX_BATCH_SIZE: int = 20                # max receipts per batch before splitting
MAX_FILE_SIZE_MB: int = 20              # maximum upload size
MAX_ALBUM_PHOTOS: int = 10              # max photos accepted from one album

# ─── AI / processing ──────────────────────────────────────────────────────────
AI_CACHE_TTL_SECONDS: int = 1800        # 30 min — TTL for per-file AI result cache
AI_CACHE_MAX_SIZE: int = 200            # LRU cache size for AI results
AI_CONFIDENCE_WARNING: float = 0.6      # below this → show verification warning
AI_PROMPT_MAX_CHARS: int = 2000         # user-input max before AI prompt injection trim
PDF_MAX_PAGES: int = 10                 # limit pages read by pdfplumber
PDF_MAX_TEXT_CHARS: int = 15_000        # total char cap for extracted PDF text
PDF_PAGE_MAX_CHARS: int = 5_000         # per-page cap
PDF_EXTRACTION_TIMEOUT: float = 10.0   # seconds before PDF extraction is killed
PDF_UNCOMPRESSED_LIMIT: int = 10 * 1024 * 1024  # 10 MB zip-bomb guard

# ─── Image processing ─────────────────────────────────────────────────────────
IMAGE_MAX_DIM: int = 1024               # resize images to at most this dimension

# ─── File validation ──────────────────────────────────────────────────────────
JPEG_MAGIC = b"\xff\xd8\xff"
PNG_MAGIC = b"\x89\x50\x4e\x47\x0d\x0a\x1a\x0a"
WEBP_RIFF = b"RIFF"
WEBP_MARKER = b"WEBP"
PDF_MAGIC = b"%PDF-"
MAGIC_READ_BYTES: int = 16
MAX_FILENAME_LEN: int = 64

# ─── Rate limiting ─────────────────────────────────────────────────────────────
RATE_MESSAGES_PER_MINUTE: int = 10
RATE_FILES_PER_HOUR: int = 20
RATE_AI_PER_DAY: int = 50
RATE_COMMANDS_PER_MINUTE: int = 30
GLOBAL_AI_CONCURRENCY: int = 100       # max simultaneous AI requests across all users
GLOBAL_DOWNLOAD_CONCURRENCY: int = 5   # max simultaneous file downloads

# ─── API timeouts (seconds) ────────────────────────────────────────────────────
TG_DOWNLOAD_CONNECT_TIMEOUT: float = 30.0
TG_DOWNLOAD_READ_TIMEOUT: float = 120.0
OPENROUTER_CONNECT_TIMEOUT: float = 30.0
OPENROUTER_READ_TIMEOUT: float = 90.0
SHEETS_CONNECT_TIMEOUT: float = 30.0
SHEETS_READ_TIMEOUT: float = 60.0
SHEETS_WRITE_TIMEOUT: float = 30.0

# ─── Circuit breaker ──────────────────────────────────────────────────────────
CB_OPENROUTER_THRESHOLD: int = 5        # failures before opening
CB_OPENROUTER_RECOVERY: float = 60.0   # seconds until half-open
CB_SHEETS_THRESHOLD: int = 3
CB_SHEETS_RECOVERY: float = 300.0

# ─── Database ─────────────────────────────────────────────────────────────────
DB_POOL_SIZE: int = 3                   # aiosqlite connection pool readers
HISTORY_PAGE_SIZE: int = 10

# ─── Date validation ──────────────────────────────────────────────────────────
DATE_MIN_YEAR: int = 2000
DATE_MAX_YEAR: int = 2100

# ─── Logging ──────────────────────────────────────────────────────────────────
LOG_MAX_BYTES: int = 10 * 1024 * 1024  # 10 MB per log file
LOG_BACKUP_COUNT: int = 5

# ─── Data lifecycle ───────────────────────────────────────────────────────────
DEFAULT_DATA_RETENTION_DAYS: int = 730  # 2 years

# ─── Regex patterns for log scrubbing ─────────────────────────────────────────
RE_BOT_TOKEN = r"\d{9,10}:[A-Za-z0-9_-]{35}"
RE_API_KEY = r"sk-[A-Za-z0-9\-_]{20,}"
# Word-boundary anchors prevent matching timestamps (e.g. 20260323174502) or
# IDs embedded in longer digit sequences.
RE_PHONE = r"(?<!\d)\+?[0-9]{10,15}(?!\d)"
RE_EMAIL = r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"

# ─── Watchdog ─────────────────────────────────────────────────────────────────
WATCHDOG_INTERVAL: int = 60             # seconds between health checks
WATCHDOG_FREE_DISK_MB: int = 500        # alert if less than this free

# ─── Metrics ──────────────────────────────────────────────────────────────────
METRICS_LOG_INTERVAL: int = 900         # 15 minutes

# ─── Google Sheets ────────────────────────────────────────────────────────────
SHEETS_RETRY_DELAYS: tuple[float, ...] = (2.0, 4.0, 8.0)

# ─── Admin security ───────────────────────────────────────────────────────────
BACKUP_CONFIRM_WINDOW: int = 60         # seconds to type CONFIRM_BACKUP
BACKUP_PASSWORD_LEN: int = 16
UNAUTHORIZED_ALERT_THRESHOLD: int = 5  # alerts after this many rejected attempts

# ─── GDPR ─────────────────────────────────────────────────────────────────────
PRIVACY_NOTICE_VERSION: str = "1.0"
