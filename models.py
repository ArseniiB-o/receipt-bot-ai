"""Domain models — Receipt and ReceiptItem dataclasses with validation."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time, datetime
from typing import Optional

from constants import DATE_MIN_YEAR, DATE_MAX_YEAR


@dataclass
class ReceiptItem:
    name: str
    quantity: float = 1.0
    price: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.name, str):
            self.name = str(self.name)
        self.name = self.name[:200]
        # Guard against non-numeric values from AI
        try:
            self.quantity = float(self.quantity)
            if self.quantity <= 0:
                self.quantity = 1.0
        except (TypeError, ValueError):
            self.quantity = 1.0
        try:
            self.price = float(self.price)
            if self.price < 0:
                self.price = 0.0
        except (TypeError, ValueError):
            self.price = 0.0


@dataclass
class Receipt:
    # Identity
    receipt_number: str = ""
    type: str = "expense"           # 'expense' | 'income' | 'unknown'

    # Store / source
    store: Optional[str] = None
    website: Optional[str] = None

    # Amounts
    total_amount: Optional[float] = None
    netto: Optional[float] = None
    ust_amount: Optional[float] = None
    ust_rate: Optional[float] = None
    currency: str = "EUR"

    # Date and time
    receipt_date: Optional[date] = None
    receipt_time: Optional[time] = None

    # Category and items
    category: Optional[str] = None
    items: list[ReceiptItem] = field(default_factory=list)

    # AI metadata
    confidence: float = 0.5
    notes: Optional[str] = None
    raw_ai_response: Optional[str] = None

    # Files
    file_paths: list[str] = field(default_factory=list)

    # Telegram
    telegram_message_id: Optional[int] = None
    telegram_user_id: int = 0
    telegram_username: Optional[str] = None
    added_by: Optional[str] = None

    # Status
    status: str = "confirmed"       # 'confirmed' | 'needs_review'
    created_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        # Clamp confidence
        try:
            self.confidence = min(1.0, max(0.0, float(self.confidence)))
        except (TypeError, ValueError):
            self.confidence = 0.5

        # Validate type
        if self.type not in ("expense", "income", "unknown"):
            self.type = "unknown"

        # Validate currency
        if not self.currency or not isinstance(self.currency, str):
            self.currency = "EUR"
        self.currency = self.currency[:10]

        # Validate date range
        if self.receipt_date is not None:
            if not (DATE_MIN_YEAR <= self.receipt_date.year <= DATE_MAX_YEAR):
                self.receipt_date = date.today()

        # Clamp amounts to non-negative
        if self.total_amount is not None and self.total_amount < 0:
            self.total_amount = abs(self.total_amount)
        if self.netto is not None and self.netto < 0:
            self.netto = abs(self.netto)
        if self.ust_amount is not None and self.ust_amount < 0:
            self.ust_amount = 0.0

    def display_type(self) -> str:
        if self.type == "expense":
            return "Расход 💸"
        elif self.type == "income":
            return "Приход 💰"
        return "Неизвестно ❓"

    def format_amount(self, amount: Optional[float]) -> str:
        if amount is None:
            return "—"
        symbol = {"EUR": "€", "USD": "$", "RUB": "₽", "UAH": "₴"}.get(self.currency, self.currency)
        return f"{amount:,.2f} {symbol}".replace(",", " ")

    def to_card_text(self) -> str:
        lines = ["✅ Чек распознан!\n"]
        lines.append(f"📋 Тип: {self.display_type()}")
        if self.store:
            lines.append(f"🏪 Магазин: {self.store}")
        if self.website:
            lines.append(f"🌐 Платформа: {self.website}")

        date_str = self.receipt_date.strftime("%d.%m.%Y") if self.receipt_date else "—"
        time_str = self.receipt_time.strftime("%H:%M") if self.receipt_time else ""
        lines.append(f"📅 Дата: {date_str}" + (f", {time_str}" if time_str else ""))

        lines.append(f"💵 Netto: {self.format_amount(self.netto)}")

        ust_rate_str = f" ({int(self.ust_rate)}%)" if self.ust_rate not in (None, 0) else ""
        lines.append(f"🧾 USt.{ust_rate_str}: {self.format_amount(self.ust_amount or 0)}")
        lines.append(f"💶 Gesamt: {self.format_amount(self.total_amount)}")

        if self.category:
            lines.append(f"🏷️ Kategorie: {self.category}")
        if self.added_by:
            lines.append(f"👤 Добавил: {self.added_by}")
        if self.receipt_number:
            lines.append(f"\n🔢 Номер чека: {self.receipt_number}")
        if self.confidence < 0.6:
            lines.append("\n⚠️ Низкая уверенность — рекомендуется проверка")

        return "\n".join(lines)
