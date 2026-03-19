"""Domain models — Receipt and ReceiptItem dataclasses with formatting helpers."""
from dataclasses import dataclass, field
from typing import Optional
from datetime import date, time, datetime


@dataclass
class ReceiptItem:
    name: str
    quantity: float = 1.0
    price: float = 0.0


@dataclass
class Receipt:
    # Идентификация
    receipt_number: str = ""
    type: str = "expense"           # 'expense' | 'income' | 'unknown'

    # Магазин / источник
    store: Optional[str] = None
    website: Optional[str] = None

    # Суммы
    total_amount: Optional[float] = None
    netto: Optional[float] = None
    ust_amount: Optional[float] = None
    ust_rate: Optional[float] = None
    currency: str = "EUR"

    # Дата и время
    receipt_date: Optional[date] = None
    receipt_time: Optional[time] = None

    # Категория и позиции
    category: Optional[str] = None
    items: list[ReceiptItem] = field(default_factory=list)

    # Метаданные AI
    confidence: float = 0.0
    notes: Optional[str] = None
    raw_ai_response: Optional[str] = None

    # Файлы
    file_paths: list[str] = field(default_factory=list)

    # Telegram
    telegram_message_id: Optional[int] = None
    telegram_user_id: int = 0
    telegram_username: Optional[str] = None
    added_by: Optional[str] = None

    # Статус
    status: str = "confirmed"       # 'confirmed' | 'needs_review'
    created_at: Optional[datetime] = None

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
        if self.confidence < 0.5:
            lines.append("\n⚠️ Низкая уверенность — требует проверки")

        return "\n".join(lines)
