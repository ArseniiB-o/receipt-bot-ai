"""
Internationalization helpers.

Supported languages: ru (Russian), de (German), en (English).
"""

TEXTS: dict[str, dict[str, str]] = {
    "ru": {
        "rate_limit": "⏳ Слишком много запросов. Подожди минуту.",
        "file_too_large": "❌ Файл слишком большой. Максимум {max_mb} МБ.",
        "unsupported_type": "❌ Поддерживаются только изображения и PDF.",
        "download_failed": "❌ Не удалось скачать файл.",
        "invalid_file_type": "❌ Тип файла не соответствует содержимому.",
        "voice_unsupported": (
            "🎤 Голосовые сообщения не поддерживаются.\n"
            "Напишите текстом или отправьте фото чека."
        ),
        "forward_no_data": "⚠️ Не удалось извлечь данные из пересланного сообщения.",
        "accepted": "📥 Принято, обрабатываю...",
        "processing": "⏳ Обрабатываю {n} {word}...",
        "receipt_word_1": "чек",
        "receipt_word_2": "чека",
        "receipt_word_5": "чеков",
        "batch_header": "📋 Чеков: <b>{n_total}</b>",
        "batch_active": "  (активных: {n_active})",
        "cancelled": "<s>Отменён</s>",
        "error_processing": "⚠️ Ошибка обработки",
        "save_all": "✅ Сохранить все ({n_active})",
        "cancel_all": "🗑 Отменить все",
        "edit_button": "✏️ #{n}",
        "cancel_button": "❌ #{n}",
        "session_expired": "❌ Сессия устарела. Отправьте чеки заново.",
        "session_expired_short": "❌ Сессия устарела.",
        "saving_all": "⏳ Сохраняю все чеки...",
        "saved_header": "✅ <b>Сохранено!</b>\n",
        "save_error": "❌ Ошибка при сохранении #{n}",
        "sheets_warning": "\n⚠️ — не записан в Google Sheets (запишется позже)",
        "all_cancelled": "❌ Все чеки отменены.",
        "editing_receipt": "✏️ Редактирование чека #{n}\n\n",
        "choose_field": "\n\nВыберите поле:",
        "back_to_list": "← Назад к списку",
        "edit_field_prompt": "✏️ {label}\nТекущее: {current}\n\nВведите новое значение:",
        "invalid_field": "❌ Недопустимое поле.",
        "no_records": "📋 Нет записей.",
        "no_records_yet": "📋 Записей пока нет.",
        "last_records": "📜 Последние {n} записей:\n",
        "filter_all": "👥 Все",
        "filter_mine": "👤 Только мои",
        "stats_header": "📊 Статистика за {month} {year}:\n",
        "expenses_line": "💸 Расходы: {amount} ({count} чеков)",
        "income_line": "💰 Приходы: {amount} ({count} чеков)",
        "balance_line": "📈 Баланс: {sign}{amount}",
        "by_categories": "\nПо категориям (расходы):",
        "receipt_deleted": (
            "✅ Чек #{number} удалён из базы.\n"
            "⚠️ Если записан в Sheets — удалите строку вручную."
        ),
        "receipt_not_found": "⚠️ Чек не найден.",
        "cancel_undone": "👌 Отмена отменена. Чек сохранён.",
        "updated": "✅ Обновлено.",
        "invalid_format": "❌ Неверный формат: {error}\nПопробуйте ещё раз.",
        "date_format_hint": "Формат даты: ДД.ММ.ГГГГ",
        "type_format_hint": "Введите 'expense' или 'income'",
        "no_cancel_target": (
            "⚠️ Нет записей для отмены "
            "(можно отменить только в течение 5 минут после сохранения)."
        ),
        "confirm_cancel": "⚠️ Отменить последний чек?\n\n#{number} | {store} | {amount}",
        "yes_cancel": "✅ Да, отменить",
        "no": "❌ Нет",
        "admin_only": "⛔ Только администратор может делать резервные копии.",
        "backup_ready": "📦 Резервная копия базы данных готова.",
        "error": "❌ Ошибка: {error}",
        "language_select": "🌐 Выберите язык / Sprache wählen / Choose language:",
        "language_set": "✅ Язык установлен: Русский 🇷🇺",
        "field_type": "📋 Тип (expense/income)",
        "field_store": "🏪 Магазин",
        "field_amount": "💶 Сумма",
        "field_date": "📅 Дата (ДД.ММ.ГГГГ)",
        "field_category": "🏷️ Категория",
        "field_currency": "💱 Валюта (EUR/RUB/USD)",
        "help_text": (
            "📖 <b>Как пользоваться ботом</b>\n\n"
            "Просто отправь в чат:\n"
            "• 📷 <b>Фото чека</b> — одно или несколько\n"
            "• 📄 <b>PDF-документ</b>\n"
            '• ✍️ <b>Текст</b> — например: "потратил 500 рублей в Пятёрочке"\n'
            "• ↩️ <b>Пересланное сообщение</b> — бот извлечёт данные\n\n"
            "Бот автоматически:\n"
            "1. Распознает тип (расход/приход), сумму, магазин, дату\n"
            "2. Покажет карточку для подтверждения\n"
            "3. Сохранит в базу данных и Google Sheets\n\n"
            "<b>Команды:</b>\n"
            "/start — приветствие\n"
            "/history [N] — последние N записей (по умолчанию 10)\n"
            "/stats [месяц] [год] — статистика за месяц\n"
            "/cancel — отменить последнее сохранение (в течение 5 минут)\n"
            "/backup — резервная копия БД (только для админа)\n"
            "/language — сменить язык\n"
            "/model — выбрать AI-модель\n"
            "/help — эта справка"
        ),
        "start_text": (
            "👋 Привет! Я бот для учёта чеков.\n\n"
            "Просто отправь мне:\n"
            "📷 Фото чека\n"
            "📄 PDF-документ\n"
            '✍️ Текст ("потратил 500 рублей в Пятёрочке")\n\n'
            "Я сам распознаю, сохраню в таблицу и присвою номер.\n\n"
            "Команды:\n"
            "/history — последние 10 записей\n"
            "/stats — статистика за месяц\n"
            "/language — сменить язык\n"
            "/model — выбрать AI-модель\n"
            "/help — помощь"
        ),
        "model_select": "🤖 Выберите модель ИИ для распознавания чеков:",
        "model_auto": "🔄 Авто (пул моделей)",
        "model_set": "✅ Модель выбрана: {model}",
        "invalid_model": "❌ Неизвестная модель.",
    },
    "de": {
        "rate_limit": "⏳ Zu viele Anfragen. Bitte warte eine Minute.",
        "file_too_large": "❌ Datei zu groß. Maximum {max_mb} MB.",
        "unsupported_type": "❌ Nur Bilder und PDF werden unterstützt.",
        "download_failed": "❌ Datei konnte nicht heruntergeladen werden.",
        "invalid_file_type": "❌ Dateityp stimmt nicht mit dem Inhalt überein.",
        "voice_unsupported": (
            "🎤 Sprachnachrichten werden nicht unterstützt.\n"
            "Schreibe einen Text oder sende ein Foto des Belegs."
        ),
        "forward_no_data": (
            "⚠️ Aus der weitergeleiteten Nachricht konnten keine Daten extrahiert werden."
        ),
        "accepted": "📥 Erhalten, verarbeite...",
        "processing": "⏳ Verarbeite {n} {word}...",
        "receipt_word_1": "Beleg",
        "receipt_word_2": "Belege",
        "receipt_word_5": "Belege",
        "batch_header": "📋 Belege: <b>{n_total}</b>",
        "batch_active": "  (aktiv: {n_active})",
        "cancelled": "<s>Abgebrochen</s>",
        "error_processing": "⚠️ Verarbeitungsfehler",
        "save_all": "✅ Alle speichern ({n_active})",
        "cancel_all": "🗑 Alle abbrechen",
        "edit_button": "✏️ #{n}",
        "cancel_button": "❌ #{n}",
        "session_expired": "❌ Sitzung abgelaufen. Bitte Belege erneut senden.",
        "session_expired_short": "❌ Sitzung abgelaufen.",
        "saving_all": "⏳ Speichere alle Belege...",
        "saved_header": "✅ <b>Gespeichert!</b>\n",
        "save_error": "❌ Fehler beim Speichern von #{n}",
        "sheets_warning": "\n⚠️ — nicht in Google Sheets gespeichert (wird später eingetragen)",
        "all_cancelled": "❌ Alle Belege abgebrochen.",
        "editing_receipt": "✏️ Beleg #{n} bearbeiten\n\n",
        "choose_field": "\n\nFeld auswählen:",
        "back_to_list": "← Zurück zur Liste",
        "edit_field_prompt": "✏️ {label}\nAktuell: {current}\n\nNeuen Wert eingeben:",
        "invalid_field": "❌ Ungültiges Feld.",
        "no_records": "📋 Keine Einträge.",
        "no_records_yet": "📋 Noch keine Einträge.",
        "last_records": "📜 Letzte {n} Einträge:\n",
        "filter_all": "👥 Alle",
        "filter_mine": "👤 Nur meine",
        "stats_header": "📊 Statistik für {month} {year}:\n",
        "expenses_line": "💸 Ausgaben: {amount} ({count} Belege)",
        "income_line": "💰 Einnahmen: {amount} ({count} Belege)",
        "balance_line": "📈 Saldo: {sign}{amount}",
        "by_categories": "\nNach Kategorien (Ausgaben):",
        "receipt_deleted": (
            "✅ Beleg #{number} aus der Datenbank gelöscht.\n"
            "⚠️ Falls in Sheets eingetragen — Zeile manuell löschen."
        ),
        "receipt_not_found": "⚠️ Beleg nicht gefunden.",
        "cancel_undone": "👌 Abbruch rückgängig. Beleg gespeichert.",
        "updated": "✅ Aktualisiert.",
        "invalid_format": "❌ Ungültiges Format: {error}\nBitte erneut versuchen.",
        "date_format_hint": "Datumsformat: TT.MM.JJJJ",
        "type_format_hint": "Bitte 'expense' oder 'income' eingeben",
        "no_cancel_target": (
            "⚠️ Keine Einträge zum Stornieren "
            "(nur innerhalb von 5 Minuten nach dem Speichern möglich)."
        ),
        "confirm_cancel": "⚠️ Letzten Beleg stornieren?\n\n#{number} | {store} | {amount}",
        "yes_cancel": "✅ Ja, stornieren",
        "no": "❌ Nein",
        "admin_only": "⛔ Nur der Administrator kann Backups erstellen.",
        "backup_ready": "📦 Datenbank-Backup bereit.",
        "error": "❌ Fehler: {error}",
        "language_select": "🌐 Выберите язык / Sprache wählen / Choose language:",
        "language_set": "✅ Sprache eingestellt: Deutsch 🇩🇪",
        "field_type": "📋 Typ (expense/income)",
        "field_store": "🏪 Geschäft",
        "field_amount": "💶 Betrag",
        "field_date": "📅 Datum (TT.MM.JJJJ)",
        "field_category": "🏷️ Kategorie",
        "field_currency": "💱 Währung (EUR/RUB/USD)",
        "help_text": (
            "📖 <b>So verwendest du den Bot</b>\n\n"
            "Sende einfach in den Chat:\n"
            "• 📷 <b>Foto eines Belegs</b> — eines oder mehrere\n"
            "• 📄 <b>PDF-Dokument</b>\n"
            '• ✍️ <b>Text</b> — z.B.: "50 Euro bei Rewe ausgegeben"\n'
            "• ↩️ <b>Weitergeleitete Nachricht</b> — der Bot extrahiert die Daten\n\n"
            "Der Bot erledigt automatisch:\n"
            "1. Erkennt Typ (Ausgabe/Einnahme), Betrag, Geschäft, Datum\n"
            "2. Zeigt eine Karte zur Bestätigung\n"
            "3. Speichert in Datenbank und Google Sheets\n\n"
            "<b>Befehle:</b>\n"
            "/start — Begrüßung\n"
            "/history [N] — letzte N Einträge (Standard: 10)\n"
            "/stats [Monat] [Jahr] — Monatsstatistik\n"
            "/cancel — letzten Eintrag stornieren (innerhalb von 5 Minuten)\n"
            "/backup — Datenbank-Backup (nur Admin)\n"
            "/language — Sprache ändern\n"
            "/model — KI-Modell wählen\n"
            "/help — diese Hilfe"
        ),
        "start_text": (
            "👋 Hallo! Ich bin ein Bot zur Belegerfassung.\n\n"
            "Sende mir einfach:\n"
            "📷 Foto eines Belegs\n"
            "📄 PDF-Dokument\n"
            '✍️ Text ("50 Euro bei Rewe ausgegeben")\n\n'
            "Ich erkenne alles automatisch, speichere in der Tabelle und vergebe eine Nummer.\n\n"
            "Befehle:\n"
            "/history — letzte 10 Einträge\n"
            "/stats — Monatsstatistik\n"
            "/language — Sprache ändern\n"
            "/model — KI-Modell wählen\n"
            "/help — Hilfe"
        ),
        "model_select": "🤖 KI-Modell für die Belegerkennung wählen:",
        "model_auto": "🔄 Auto (Modell-Pool)",
        "model_set": "✅ Modell gewählt: {model}",
        "invalid_model": "❌ Unbekanntes Modell.",
    },
    "en": {
        "rate_limit": "⏳ Too many requests. Please wait a minute.",
        "file_too_large": "❌ File too large. Maximum {max_mb} MB.",
        "unsupported_type": "❌ Only images and PDF are supported.",
        "download_failed": "❌ Could not download the file.",
        "invalid_file_type": "❌ File type does not match its content.",
        "voice_unsupported": (
            "🎤 Voice messages are not supported.\n"
            "Please write text or send a photo of the receipt."
        ),
        "forward_no_data": "⚠️ Could not extract data from the forwarded message.",
        "accepted": "📥 Received, processing...",
        "processing": "⏳ Processing {n} {word}...",
        "receipt_word_1": "receipt",
        "receipt_word_2": "receipts",
        "receipt_word_5": "receipts",
        "batch_header": "📋 Receipts: <b>{n_total}</b>",
        "batch_active": "  (active: {n_active})",
        "cancelled": "<s>Cancelled</s>",
        "error_processing": "⚠️ Processing error",
        "save_all": "✅ Save all ({n_active})",
        "cancel_all": "🗑 Cancel all",
        "edit_button": "✏️ #{n}",
        "cancel_button": "❌ #{n}",
        "session_expired": "❌ Session expired. Please send receipts again.",
        "session_expired_short": "❌ Session expired.",
        "saving_all": "⏳ Saving all receipts...",
        "saved_header": "✅ <b>Saved!</b>\n",
        "save_error": "❌ Error saving #{n}",
        "sheets_warning": "\n⚠️ — not saved to Google Sheets (will be saved later)",
        "all_cancelled": "❌ All receipts cancelled.",
        "editing_receipt": "✏️ Editing receipt #{n}\n\n",
        "choose_field": "\n\nChoose field:",
        "back_to_list": "← Back to list",
        "edit_field_prompt": "✏️ {label}\nCurrent: {current}\n\nEnter new value:",
        "invalid_field": "❌ Invalid field.",
        "no_records": "📋 No records.",
        "no_records_yet": "📋 No records yet.",
        "last_records": "📜 Last {n} records:\n",
        "filter_all": "👥 All",
        "filter_mine": "👤 Mine only",
        "stats_header": "📊 Statistics for {month} {year}:\n",
        "expenses_line": "💸 Expenses: {amount} ({count} receipts)",
        "income_line": "💰 Income: {amount} ({count} receipts)",
        "balance_line": "📈 Balance: {sign}{amount}",
        "by_categories": "\nBy category (expenses):",
        "receipt_deleted": (
            "✅ Receipt #{number} deleted from the database.\n"
            "⚠️ If saved in Sheets — delete the row manually."
        ),
        "receipt_not_found": "⚠️ Receipt not found.",
        "cancel_undone": "👌 Cancellation undone. Receipt is saved.",
        "updated": "✅ Updated.",
        "invalid_format": "❌ Invalid format: {error}\nPlease try again.",
        "date_format_hint": "Date format: DD.MM.YYYY",
        "type_format_hint": "Please enter 'expense' or 'income'",
        "no_cancel_target": (
            "⚠️ No records to cancel "
            "(only possible within 5 minutes after saving)."
        ),
        "confirm_cancel": "⚠️ Cancel the last receipt?\n\n#{number} | {store} | {amount}",
        "yes_cancel": "✅ Yes, cancel",
        "no": "❌ No",
        "admin_only": "⛔ Only the administrator can create backups.",
        "backup_ready": "📦 Database backup ready.",
        "error": "❌ Error: {error}",
        "language_select": "🌐 Выберите язык / Sprache wählen / Choose language:",
        "language_set": "✅ Language set: English 🇬🇧",
        "field_type": "📋 Type (expense/income)",
        "field_store": "🏪 Store",
        "field_amount": "💶 Amount",
        "field_date": "📅 Date (DD.MM.YYYY)",
        "field_category": "🏷️ Category",
        "field_currency": "💱 Currency (EUR/RUB/USD)",
        "help_text": (
            "📖 <b>How to use the bot</b>\n\n"
            "Just send to the chat:\n"
            "• 📷 <b>Receipt photo</b> — one or several\n"
            "• 📄 <b>PDF document</b>\n"
            '• ✍️ <b>Text</b> — e.g.: "spent €50 at Rewe"\n'
            "• ↩️ <b>Forwarded message</b> — the bot will extract the data\n\n"
            "The bot automatically:\n"
            "1. Recognizes type (expense/income), amount, store, date\n"
            "2. Shows a confirmation card\n"
            "3. Saves to database and Google Sheets\n\n"
            "<b>Commands:</b>\n"
            "/start — welcome message\n"
            "/history [N] — last N records (default 10)\n"
            "/stats [month] [year] — monthly statistics\n"
            "/cancel — undo last save (within 5 minutes)\n"
            "/backup — database backup (admin only)\n"
            "/language — change language\n"
            "/model — choose AI model\n"
            "/help — this help"
        ),
        "start_text": (
            "👋 Hello! I'm a receipt tracking bot.\n\n"
            "Just send me:\n"
            "📷 Receipt photo\n"
            "📄 PDF document\n"
            '✍️ Text ("spent €50 at Rewe")\n\n'
            "I'll recognize everything automatically, save to the spreadsheet and assign a number.\n\n"
            "Commands:\n"
            "/history — last 10 records\n"
            "/stats — monthly statistics\n"
            "/language — change language\n"
            "/model — choose AI model\n"
            "/help — help"
        ),
        "model_select": "🤖 Choose AI model for receipt recognition:",
        "model_auto": "🔄 Auto (model pool)",
        "model_set": "✅ Model selected: {model}",
        "invalid_model": "❌ Unknown model.",
    },
}

_VALID_LANGS = {"ru", "de", "en"}

_MONTH_NAMES: dict[str, list[str]] = {
    "ru": [
        "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
        "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
    ],
    "de": [
        "Januar", "Februar", "März", "April", "Mai", "Juni",
        "Juli", "August", "September", "Oktober", "November", "Dezember",
    ],
    "en": [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ],
}


def month_name(lang: str, month: int) -> str:
    """Return the localized month name (1-based)."""
    names = _MONTH_NAMES.get(lang, _MONTH_NAMES["ru"])
    if 1 <= month <= 12:
        return names[month - 1]
    return str(month)


def receipt_word(lang: str, n: int) -> str:
    """Return the correct plural form of 'receipt' for the given language and count."""
    if lang == "ru":
        mod10, mod100 = n % 10, n % 100
        if mod10 == 1 and mod100 != 11:
            return TEXTS["ru"]["receipt_word_1"]
        elif 2 <= mod10 <= 4 and not (12 <= mod100 <= 14):
            return TEXTS["ru"]["receipt_word_2"]
        else:
            return TEXTS["ru"]["receipt_word_5"]
    elif lang == "de":
        return TEXTS["de"]["receipt_word_1"] if n == 1 else TEXTS["de"]["receipt_word_2"]
    else:
        return TEXTS["en"]["receipt_word_1"] if n == 1 else TEXTS["en"]["receipt_word_2"]


def t(user_id: int, key: str, **kwargs) -> str:
    """Look up a translation string for the given user. Falls back to Russian."""
    import database
    lang = database.get_user_language(user_id)
    texts = TEXTS.get(lang, TEXTS["ru"])
    template = texts.get(key) or TEXTS["ru"].get(key, key)
    if kwargs:
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError):
            return template
    return template
