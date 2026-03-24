"""Internationalization helpers.

Supported languages: ru (Russian), de (German), en (English).
"""
from __future__ import annotations

TEXTS: dict[str, dict[str, str]] = {
    "ru": {
        # ── Rate limiting ──────────────────────────────────────────────────────
        "rate_limit": "⏳ Слишком много запросов. Подожди минуту.",
        "file_rate_limit": "⏳ Слишком много файлов. Подожди час.",
        "ai_rate_limit": "⏳ Дневной лимит AI-запросов исчерпан ({limit}/день). Попробуйте завтра.",
        # ── File errors ────────────────────────────────────────────────────────
        "file_too_large": "❌ Файл слишком большой. Максимум {max_mb} МБ.",
        "unsupported_type": "❌ Поддерживаются только изображения и PDF.",
        "download_failed": "❌ Не удалось скачать файл.",
        "invalid_file_type": "❌ Тип файла не соответствует содержимому.",
        # ── Voice / forward ────────────────────────────────────────────────────
        "voice_unsupported": (
            "🎤 Голосовые сообщения не поддерживаются.\n"
            "Напишите текстом или отправьте фото чека."
        ),
        "forward_no_data": "⚠️ Не удалось извлечь данные из пересланного сообщения.",
        # ── Processing ─────────────────────────────────────────────────────────
        "accepted": "📥 Принято, обрабатываю...",
        "processing": "⏳ Обрабатываю {n} {word}...",
        "processing_one": "обрабатывается",
        "processing_status": "⏳ Статус: ",
        "merging_queue": "➕ Добавляю {n} чек(и) в очередь. Всего: {total}. Обрабатываю вместе...",
        "batch_size_limit": "⚠️ Максимальный размер партии — {max} чеков.",
        "still_processing": "ещё обрабатывается: {n}",
        # ── Receipt words ──────────────────────────────────────────────────────
        "receipt_word_1": "чек",
        "receipt_word_2": "чека",
        "receipt_word_5": "чеков",
        # ── Batch UI ───────────────────────────────────────────────────────────
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
        # ── History / stats ────────────────────────────────────────────────────
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
        # ── Receipt ops ────────────────────────────────────────────────────────
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
            "(можно отменить только в течение {minutes} минут после сохранения)."
        ),
        "confirm_cancel": "⚠️ Отменить последний чек?\n\n#{number} | {store} | {amount}",
        "yes_cancel": "✅ Да, отменить",
        "no": "❌ Нет",
        # ── Admin / backup ─────────────────────────────────────────────────────
        "admin_only": "⛔ Только администратор может выполнить эту команду.",
        "backup_ready": "📦 Резервная копия базы данных готова.",
        "internal_error": "❌ Внутренняя ошибка. Код: {ref}",
        "error": "❌ Ошибка: {error}",
        # ── Language / model ───────────────────────────────────────────────────
        "language_select": "🌐 Выберите язык / Sprache wählen / Choose language:",
        "language_set": "✅ Язык установлен: Русский 🇷🇺",
        "field_type": "📋 Тип (expense/income)",
        "field_store": "🏪 Магазин",
        "field_amount": "💶 Сумма",
        "field_date": "📅 Дата (ДД.ММ.ГГГГ)",
        "field_category": "🏷️ Категория",
        "field_currency": "💱 Валюта (EUR/RUB/USD)",
        "model_select": "🤖 Выберите модель ИИ для распознавания чеков:",
        "model_auto": "🔄 Авто (пул моделей)",
        "model_set": "✅ Модель выбрана: {model}",
        "invalid_model": "❌ Неизвестная модель.",
        # ── Privacy / GDPR ─────────────────────────────────────────────────────
        "privacy_notice": (
            "🔒 <b>Уведомление о конфиденциальности</b>\n\n"
            "Перед использованием бота ознакомьтесь с политикой:\n\n"
            "📸 Что собирается: фото чеков, финансовые данные (суммы, магазины, даты)\n"
            "💾 Где хранится: локальная база данных{sheets_note}\n"
            "🗓 Срок хранения: {retention_days} дней\n"
            "🗑 Удаление: /delete_my_data\n"
            "📤 Экспорт: /export_my_data\n\n"
            "Нажмите «Принять» для продолжения."
        ),
        "privacy_sheets_note": ", Google Sheets",
        "privacy_accept": "✅ Принять",
        "privacy_accepted": "✅ Вы приняли условия обработки данных.",
        "privacy_accepted_resend": (
            "✅ Отлично! Теперь отправьте фото чека, PDF или текст ещё раз — я обработаю его сейчас."
        ),
        "batch_expired_notify": (
            "⏰ Сессия подтверждения истекла. Ваш чек не был сохранён.\n"
            "Пожалуйста, отправьте фото или файл ещё раз."
        ),
        # ── GDPR commands ──────────────────────────────────────────────────────
        "confirm_delete_data": (
            "⚠️ <b>Удаление всех данных</b>\n\n"
            "Это действие удалит ВСЕ ваши чеки, файлы и настройки безвозвратно.\n\n"
            "Для подтверждения отправьте сообщение: <code>DELETE_ALL_MY_DATA</code>"
        ),
        "data_deleted": "✅ Удалено {count} чеков и все связанные файлы.",
        "delete_cancelled": "👌 Удаление отменено.",
        "export_preparing": "⏳ Подготавливаю экспорт данных...",
        "export_ready": "📦 Экспорт готов. {count} чеков.",
        # ── Help / start ───────────────────────────────────────────────────────
        "help_text": (
            "📖 <b>Как пользоваться ботом</b>\n\n"
            "Просто отправь в чат:\n"
            "• 📷 <b>Фото чека</b> — одно или несколько\n"
            "• 📄 <b>PDF-документ</b>\n"
            '• ✍️ <b>Текст</b> — например: "потратил 500 рублей в Пятёрочке"\n'
            "• ↩️ <b>Пересланное сообщение</b> — бот извлечёт данные\n\n"
            "<b>Команды:</b>\n"
            "/start — приветствие\n"
            "/history [N] — последние N записей\n"
            "/stats [месяц] [год] — статистика\n"
            "/cancel — отменить последнее сохранение\n"
            "/delete_my_data — удалить все мои данные (GDPR)\n"
            "/export_my_data — экспорт всех моих данных (GDPR)\n"
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
            "Я распознаю, сохраню в таблицу и присвою номер.\n\n"
            "/history — последние записи\n"
            "/stats — статистика\n"
            "/language — сменить язык\n"
            "/help — помощь"
        ),
    },

    # ─── German ───────────────────────────────────────────────────────────────
    "de": {
        "rate_limit": "⏳ Zu viele Anfragen. Bitte warte eine Minute.",
        "file_rate_limit": "⏳ Zu viele Dateien. Bitte eine Stunde warten.",
        "ai_rate_limit": "⏳ Tägliches KI-Limit erreicht ({limit}/Tag). Bitte morgen wieder versuchen.",
        "file_too_large": "❌ Datei zu groß. Maximum {max_mb} MB.",
        "unsupported_type": "❌ Nur Bilder und PDF werden unterstützt.",
        "download_failed": "❌ Datei konnte nicht heruntergeladen werden.",
        "invalid_file_type": "❌ Dateityp stimmt nicht mit dem Inhalt überein.",
        "voice_unsupported": (
            "🎤 Sprachnachrichten werden nicht unterstützt.\n"
            "Schreibe einen Text oder sende ein Foto des Belegs."
        ),
        "forward_no_data": "⚠️ Aus der weitergeleiteten Nachricht konnten keine Daten extrahiert werden.",
        "accepted": "📥 Erhalten, verarbeite...",
        "processing": "⏳ Verarbeite {n} {word}...",
        "processing_one": "wird verarbeitet",
        "processing_status": "⏳ Status: ",
        "merging_queue": "➕ {n} Beleg(e) zur Warteschlange hinzugefügt. Gesamt: {total}. Verarbeite zusammen...",
        "batch_size_limit": "⚠️ Maximale Batch-Größe: {max} Belege.",
        "still_processing": "noch in Bearbeitung: {n}",
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
            "(nur innerhalb von {minutes} Minuten nach dem Speichern möglich)."
        ),
        "confirm_cancel": "⚠️ Letzten Beleg stornieren?\n\n#{number} | {store} | {amount}",
        "yes_cancel": "✅ Ja, stornieren",
        "no": "❌ Nein",
        "admin_only": "⛔ Nur der Administrator kann diesen Befehl ausführen.",
        "backup_ready": "📦 Datenbank-Backup bereit.",
        "internal_error": "❌ Interner Fehler. Code: {ref}",
        "error": "❌ Fehler: {error}",
        "language_select": "🌐 Выберите язык / Sprache wählen / Choose language:",
        "language_set": "✅ Sprache eingestellt: Deutsch 🇩🇪",
        "field_type": "📋 Typ (expense/income)",
        "field_store": "🏪 Geschäft",
        "field_amount": "💶 Betrag",
        "field_date": "📅 Datum (TT.MM.JJJJ)",
        "field_category": "🏷️ Kategorie",
        "field_currency": "💱 Währung (EUR/RUB/USD)",
        "model_select": "🤖 KI-Modell für die Belegerkennung wählen:",
        "model_auto": "🔄 Auto (Modell-Pool)",
        "model_set": "✅ Modell gewählt: {model}",
        "invalid_model": "❌ Unbekanntes Modell.",
        "privacy_notice": (
            "🔒 <b>Datenschutzhinweis</b>\n\n"
            "Bevor du den Bot nutzt:\n\n"
            "📸 Gesammelte Daten: Belegfotos, Finanzdaten (Beträge, Geschäfte, Daten)\n"
            "💾 Speicherort: Lokale Datenbank{sheets_note}\n"
            "🗓 Aufbewahrungsfrist: {retention_days} Tage\n"
            "🗑 Löschen: /delete_my_data\n"
            "📤 Export: /export_my_data\n\n"
            "Klicke auf «Akzeptieren» um fortzufahren."
        ),
        "privacy_sheets_note": ", Google Sheets",
        "privacy_accept": "✅ Akzeptieren",
        "privacy_accepted": "✅ Du hast der Datenverarbeitung zugestimmt.",
        "privacy_accepted_resend": (
            "✅ Super! Bitte sende jetzt nochmal dein Belegfoto, PDF oder Text — ich verarbeite es sofort."
        ),
        "batch_expired_notify": (
            "⏰ Bestätigungssitzung abgelaufen. Dein Beleg wurde nicht gespeichert.\n"
            "Bitte sende das Foto oder die Datei erneut."
        ),
        "confirm_delete_data": (
            "⚠️ <b>Alle Daten löschen</b>\n\n"
            "Diese Aktion löscht ALLE deine Belege, Dateien und Einstellungen unwiderruflich.\n\n"
            "Zur Bestätigung sende: <code>DELETE_ALL_MY_DATA</code>"
        ),
        "data_deleted": "✅ {count} Belege und alle zugehörigen Dateien wurden gelöscht.",
        "delete_cancelled": "👌 Löschen abgebrochen.",
        "export_preparing": "⏳ Exportiere Daten...",
        "export_ready": "📦 Export bereit. {count} Belege.",
        "help_text": (
            "📖 <b>So verwendest du den Bot</b>\n\n"
            "Sende einfach:\n"
            "• 📷 <b>Belegfoto</b>\n"
            "• 📄 <b>PDF-Dokument</b>\n"
            '• ✍️ <b>Text</b>\n\n'
            "<b>Befehle:</b>\n"
            "/history — letzte Einträge\n"
            "/stats — Statistik\n"
            "/cancel — letzten Eintrag stornieren\n"
            "/delete_my_data — alle Daten löschen (DSGVO)\n"
            "/export_my_data — Daten exportieren (DSGVO)\n"
            "/language — Sprache ändern\n"
            "/model — KI-Modell wählen\n"
            "/help — Hilfe"
        ),
        "start_text": (
            "👋 Hallo! Ich bin ein Bot zur Belegerfassung.\n\n"
            "Sende mir:\n"
            "📷 Belegfoto\n"
            "📄 PDF\n"
            "✍️ Text\n\n"
            "/history — letzte Einträge\n"
            "/stats — Statistik\n"
            "/help — Hilfe"
        ),
    },

    # ─── English ──────────────────────────────────────────────────────────────
    "en": {
        "rate_limit": "⏳ Too many requests. Please wait a minute.",
        "file_rate_limit": "⏳ Too many files. Please wait an hour.",
        "ai_rate_limit": "⏳ Daily AI request limit reached ({limit}/day). Please try again tomorrow.",
        "file_too_large": "❌ File too large. Maximum {max_mb} MB.",
        "unsupported_type": "❌ Only images and PDF are supported.",
        "download_failed": "❌ Could not download the file.",
        "invalid_file_type": "❌ File type does not match its content.",
        "voice_unsupported": (
            "🎤 Voice messages are not supported.\n"
            "Please write text or send a receipt photo."
        ),
        "forward_no_data": "⚠️ Could not extract data from the forwarded message.",
        "accepted": "📥 Received, processing...",
        "processing": "⏳ Processing {n} {word}...",
        "processing_one": "processing",
        "processing_status": "⏳ Status: ",
        "merging_queue": "➕ Adding {n} receipt(s) to queue. Total: {total}. Processing together...",
        "batch_size_limit": "⚠️ Maximum batch size is {max} receipts.",
        "still_processing": "still processing: {n}",
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
            "(only possible within {minutes} minutes after saving)."
        ),
        "confirm_cancel": "⚠️ Cancel the last receipt?\n\n#{number} | {store} | {amount}",
        "yes_cancel": "✅ Yes, cancel",
        "no": "❌ No",
        "admin_only": "⛔ Only the administrator can run this command.",
        "backup_ready": "📦 Database backup ready.",
        "internal_error": "❌ Internal error. Reference: {ref}",
        "error": "❌ Error: {error}",
        "language_select": "🌐 Выберите язык / Sprache wählen / Choose language:",
        "language_set": "✅ Language set: English 🇬🇧",
        "field_type": "📋 Type (expense/income)",
        "field_store": "🏪 Store",
        "field_amount": "💶 Amount",
        "field_date": "📅 Date (DD.MM.YYYY)",
        "field_category": "🏷️ Category",
        "field_currency": "💱 Currency (EUR/RUB/USD)",
        "model_select": "🤖 Choose AI model for receipt recognition:",
        "model_auto": "🔄 Auto (model pool)",
        "model_set": "✅ Model selected: {model}",
        "invalid_model": "❌ Unknown model.",
        "privacy_notice": (
            "🔒 <b>Privacy Notice</b>\n\n"
            "Before using this bot:\n\n"
            "📸 Data collected: receipt photos, financial data (amounts, stores, dates)\n"
            "💾 Storage: local database{sheets_note}\n"
            "🗓 Retention period: {retention_days} days\n"
            "🗑 Delete your data: /delete_my_data\n"
            "📤 Export your data: /export_my_data\n\n"
            "Click «Accept» to continue."
        ),
        "privacy_sheets_note": ", Google Sheets",
        "privacy_accept": "✅ Accept",
        "privacy_accepted": "✅ You have accepted the data processing terms.",
        "privacy_accepted_resend": (
            "✅ Great! Now please resend your receipt photo, PDF, or text — I'll process it right away."
        ),
        "batch_expired_notify": (
            "⏰ Confirmation session expired. Your receipt was not saved.\n"
            "Please send the photo or file again."
        ),
        "confirm_delete_data": (
            "⚠️ <b>Delete all data</b>\n\n"
            "This will permanently delete ALL your receipts, files, and settings.\n\n"
            "To confirm, send: <code>DELETE_ALL_MY_DATA</code>"
        ),
        "data_deleted": "✅ {count} receipts and all associated files deleted.",
        "delete_cancelled": "👌 Deletion cancelled.",
        "export_preparing": "⏳ Preparing your data export...",
        "export_ready": "📦 Export ready. {count} receipts.",
        "help_text": (
            "📖 <b>How to use the bot</b>\n\n"
            "Just send:\n"
            "• 📷 <b>Receipt photo</b>\n"
            "• 📄 <b>PDF document</b>\n"
            '• ✍️ <b>Text</b>\n\n'
            "<b>Commands:</b>\n"
            "/history — recent records\n"
            "/stats — statistics\n"
            "/cancel — undo last save\n"
            "/delete_my_data — delete all my data (GDPR)\n"
            "/export_my_data — export all my data (GDPR)\n"
            "/language — change language\n"
            "/model — choose AI model\n"
            "/help — this help"
        ),
        "start_text": (
            "👋 Hello! I'm a receipt tracking bot.\n\n"
            "Send me:\n"
            "📷 Receipt photo\n"
            "📄 PDF\n"
            "✍️ Text\n\n"
            "/history — recent records\n"
            "/stats — statistics\n"
            "/help — help"
        ),
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
    names = _MONTH_NAMES.get(lang, _MONTH_NAMES["ru"])
    if 1 <= month <= 12:
        return names[month - 1]
    return str(month)


def receipt_word(lang: str, n: int) -> str:
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
    import database as _db
    lang = _db.get_user_language(user_id)
    texts = TEXTS.get(lang, TEXTS["ru"])
    template = texts.get(key) or TEXTS["ru"].get(key, key)
    if kwargs:
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError):
            return template
    return template
