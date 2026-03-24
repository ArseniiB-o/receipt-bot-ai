"""Custom exception hierarchy for the receipt bot.

All application-level errors inherit from ReceiptBotError so callers can
catch the broad base class or a specific subclass as needed.
"""
from __future__ import annotations


class ReceiptBotError(Exception):
    """Base class for all receipt bot errors."""


class FileValidationError(ReceiptBotError):
    """Raised when a file fails validation (bad magic bytes, too large, path traversal)."""


class AIProcessingError(ReceiptBotError):
    """Raised when AI analysis fails after all retries."""


class DatabaseError(ReceiptBotError):
    """Raised on SQLite or schema errors."""


class SheetsError(ReceiptBotError):
    """Raised when Google Sheets operations fail."""


class RateLimitError(ReceiptBotError):
    """Raised when a per-user or global rate limit is exceeded."""


class AuthorizationError(ReceiptBotError):
    """Raised when an unauthorized user attempts to access the bot."""


class CircuitOpenError(ReceiptBotError):
    """Raised when a circuit breaker is in the OPEN state."""

    def __init__(self, service: str, retry_after: float) -> None:
        self.service = service
        self.retry_after = retry_after
        super().__init__(f"Circuit breaker OPEN for {service}, retry after {retry_after:.0f}s")


class ConfigurationError(ReceiptBotError):
    """Raised when a required configuration value is missing or invalid."""


class BatchExpiredError(ReceiptBotError):
    """Raised when a batch session has expired before the user confirmed."""
