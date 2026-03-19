"""Message handlers — photos, documents, voice, text, forwarded messages, batch queue."""
import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

import ai_processor
import database
import file_manager
from config import MAX_FILE_SIZE_MB, TEMP_FOLDER
from handlers.i18n import receipt_word, t
from models import Receipt
from utils import check_rate_limit, safe_file_path

logger = logging.getLogger(__name__)

# Album grouping
MEDIA_GROUP_KEY = "media_groups"
MEDIA_GROUP_TIMER_KEY = "media_group_timers"
MEDIA_GROUP_DELAY = 2.5  # seconds — wait for Telegram to send all album photos

# Batch queue (all incoming items per user)
BATCH_QUEUE_KEY = "batch_queue"
BATCH_TIMER_KEY = "batch_timers"
BATCH_DELAY = 4.0  # seconds after last incoming message
AI_INTER_CALL_DELAY = 8.0  # seconds between AI calls to avoid rate limit


def _extract_pdf_text(pdf_path: str) -> str:
    """Extract text from a PDF using pdfplumber. Capped per-page and total."""
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            pages_text = []
            for page in pdf.pages[:10]:  # max 10 pages
                text = page.extract_text() or ""
                pages_text.append(text[:5000])  # cap per page before joining
                if sum(len(t) for t in pages_text) > 15000:
                    break
            return "\n".join(pages_text)
    except ImportError:
        logger.warning("pdfplumber not installed — PDF processed without text extraction")
        return ""
    except Exception as e:
        logger.warning("Failed to extract text from PDF: %s", e)
        return ""


def _get_added_by(user) -> str:
    if user.first_name:
        return user.first_name
    if user.username:
        return f"@{user.username}"
    return str(user.id)


def get_batch_key(user_id: int, chat_id: int) -> str:
    return f"batch_{user_id}_{chat_id}"


async def _download_file(bot, file_id: str, filename: str) -> Optional[str]:
    file_manager.ensure_dirs()
    try:
        temp_path = safe_file_path(TEMP_FOLDER, filename)
        tg_file = await bot.get_file(file_id)
        await tg_file.download_to_drive(temp_path)
        return temp_path
    except ValueError as e:
        logger.error("Path traversal blocked: %s", e)
        return None
    except Exception as e:
        logger.error("File download error: %s", e)
        return None


async def _enqueue_item(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    temp_paths: list,
    caption: str = "",
    message_id: Optional[int] = None,
):
    """Add one item to the user's processing queue and reset the batch timer."""
    user = update.effective_user
    user_id = user.id
    chat_id = update.effective_chat.id

    queue = context.bot_data.setdefault(BATCH_QUEUE_KEY, {})
    queue.setdefault(user_id, []).append({
        "temp_paths": temp_paths,
        "caption": caption,
        "message_id": message_id,
        "update": update,
        "user": user,
        "chat_id": chat_id,
    })

    timers = context.bot_data.setdefault(BATCH_TIMER_KEY, {})
    if user_id in timers:
        timers[user_id].cancel()

    loop = asyncio.get_running_loop()
    timers[user_id] = loop.create_task(
        _process_batch_after_delay(user_id, chat_id, update, context)
    )


async def _process_batch_after_delay(
    user_id: int,
    chat_id: int,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await asyncio.sleep(BATCH_DELAY)

    queue = context.bot_data.get(BATCH_QUEUE_KEY, {})
    items = queue.pop(user_id, [])
    timers = context.bot_data.get(BATCH_TIMER_KEY, {})
    timers.pop(user_id, None)

    if not items:
        return

    user = items[0]["user"]
    n = len(items)
    lang = database.get_user_language(user_id)
    word = receipt_word(lang, n)
    processing_msg = await update.effective_message.reply_text(
        t(user_id, "processing", n=n, word=word)
    )

    all_temp_paths = []

    # Parallel processing: assign each receipt its own model from the pool
    from ai_processor import MODEL_POOL, analyze_image, analyze_text

    async def _process_one(idx: int, item: dict) -> Receipt | None:
        paths = item["temp_paths"]
        cap = item["caption"]
        # Use user's preferred model if set, otherwise round-robin from pool
        preferred = database.get_user_model(user_id)
        model = preferred if preferred else MODEL_POOL[idx % len(MODEL_POOL)]
        # Stagger starts to avoid hitting all models simultaneously
        await asyncio.sleep(idx * 2.0)
        try:
            if paths:
                receipt = await analyze_image(paths[0], cap, model=model)
            else:
                receipt = await analyze_text(cap)
            receipt.telegram_user_id = user.id
            receipt.telegram_username = user.username or user.first_name
            receipt.added_by = _get_added_by(user)
            receipt.telegram_message_id = item["message_id"]
            ts = datetime.now().strftime("%H%M%S%f")
            receipt.receipt_number = f"DRAFT-{ts}-{idx}"
            return receipt
        except Exception as e:
            logger.error("AI error for receipt %d: %s", idx, e, exc_info=True)
            # Guarantee temp file cleanup on exception
            for p in paths:
                file_manager.delete_temp_file(p)
            return None

    for item in items:
        all_temp_paths.append(item["temp_paths"])

    tasks = [_process_one(idx, item) for idx, item in enumerate(items)]
    receipts = list(await asyncio.gather(*tasks))

    try:
        await processing_msg.delete()
    except Exception:
        pass

    batch_key = get_batch_key(user_id, chat_id)
    context.bot_data[batch_key] = {
        "receipts": receipts,
        "all_temp_paths": all_temp_paths,
        "cancelled": set(),
        "chat_id": chat_id,
        "user_id": user_id,
    }

    await show_batch_confirmation(update, context, batch_key)

    # Expire stale batch after 30 min — cleans up temp files if user never responds
    async def _expire_batch(ctx):
        key = ctx.job.data
        batch = ctx.bot_data.pop(key, {})
        for paths in batch.get("all_temp_paths", []):
            for p in (paths if isinstance(paths, list) else [paths]):
                file_manager.delete_temp_file(p)

    if context.job_queue:
        context.job_queue.run_once(_expire_batch, 1800, data=batch_key)


def _build_batch_text_and_keyboard(batch: dict) -> tuple:
    user_id = batch.get("user_id", 0)
    receipts = batch.get("receipts", [])
    cancelled = batch.get("cancelled", set())

    lines = []
    n_active = 0
    for i, r in enumerate(receipts):
        num = i + 1
        if i in cancelled:
            lines.append(f"{num}. {t(user_id, 'cancelled')}")
            continue
        if r is None:
            lines.append(f"{num}. {t(user_id, 'error_processing')}")
            continue
        n_active += 1
        icon = "💸" if r.type == "expense" else ("💰" if r.type == "income" else "❓")
        date_str = r.receipt_date.strftime("%d.%m.%Y") if r.receipt_date else "—"
        amount_str = f"{r.total_amount:.2f} {r.currency}" if r.total_amount else "—"
        store = r.store or "—"
        lines.append(f"{num}. {icon} <b>{store}</b>  {date_str}  {amount_str}")

    n_total = len(receipts)
    header = t(user_id, "batch_header", n_total=n_total)
    if n_total != n_active:
        header += t(user_id, "batch_active", n_active=n_active)
    text = header + "\n\n" + "\n".join(lines)

    keyboard = []
    for i, r in enumerate(receipts):
        if i in cancelled or r is None:
            continue
        keyboard.append([
            InlineKeyboardButton(
                t(user_id, "edit_button", n=i + 1),
                callback_data=f"batch_edit:{batch.get('_key', '')}:{i}",
            ),
            InlineKeyboardButton(
                t(user_id, "cancel_button", n=i + 1),
                callback_data=f"batch_cancel:{batch.get('_key', '')}:{i}",
            ),
        ])

    if n_active > 0:
        keyboard.append([
            InlineKeyboardButton(
                t(user_id, "save_all", n_active=n_active),
                callback_data=f"batch_save:{batch.get('_key', '')}",
            )
        ])

    if n_total > 1:
        keyboard.append([
            InlineKeyboardButton(
                t(user_id, "cancel_all"),
                callback_data=f"batch_cancel_all:{batch.get('_key', '')}",
            ),
        ])

    return text, InlineKeyboardMarkup(keyboard)


async def show_batch_confirmation(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    batch_key: str,
):
    batch = context.bot_data.get(batch_key, {})
    batch["_key"] = batch_key  # inject key for keyboard builder

    text, keyboard = _build_batch_text_and_keyboard(batch)

    msg = await update.effective_message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    batch["msg_id"] = msg.message_id
    batch["chat_id"] = update.effective_chat.id


async def refresh_batch_message(context: ContextTypes.DEFAULT_TYPE, batch_key: str):
    """Edit the existing batch confirmation message in place."""
    batch = context.bot_data.get(batch_key)
    if not batch:
        return
    batch["_key"] = batch_key
    text, keyboard = _build_batch_text_and_keyboard(batch)
    msg_id = batch.get("msg_id")
    chat_id = batch.get("chat_id")
    if not msg_id or not chat_id:
        return
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg_id,
            text=text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    except Exception as e:
        logger.debug("Failed to update batch message: %s", e)


# ─── Handlers ────────────────────────────────────────────────────────────────

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    if not text.strip():
        return

    user_id = update.effective_user.id
    if not check_rate_limit(user_id, max_per_minute=10):
        await update.message.reply_text(t(user_id, "rate_limit"))
        return

    # Truncate overly long messages
    if len(text) > 4096:
        text = text[:4096]

    edit_state = context.user_data.get("edit_state")
    if edit_state:
        from handlers.callback_handler import handle_edit_input
        await handle_edit_input(update, context)
        return

    # Classify: casual chat or receipt data
    result = await ai_processor.classify_or_chat(text)
    if result != "RECEIPT":
        await update.message.reply_text(result)
        return

    await update.message.reply_text(t(user_id, "accepted"))
    await _enqueue_item(
        update, context,
        temp_paths=[],
        caption=text,
        message_id=update.message.message_id,
    )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    user_id = update.effective_user.id
    if not check_rate_limit(user_id, max_per_minute=10):
        await message.reply_text(t(user_id, "rate_limit"))
        return
    photo = message.photo[-1]

    if photo.file_size and not file_manager.check_file_size(photo.file_size):
        await message.reply_text(t(user_id, "file_too_large", max_mb=MAX_FILE_SIZE_MB))
        return

    filename = f"photo_{message.message_id}_{photo.file_id[-8:]}.jpg"
    temp_path = await _download_file(context.bot, photo.file_id, filename)
    if not temp_path:
        return

    media_group_id = message.media_group_id
    if media_group_id:
        # Album: collect all photos, then enqueue as separate receipts
        groups = context.bot_data.setdefault(MEDIA_GROUP_KEY, {})
        if media_group_id not in groups:
            groups[media_group_id] = {
                "photos": [],
                "update": update,
                "caption": message.caption or "",
                "message_id": message.message_id,
            }
        if len(groups[media_group_id]["photos"]) >= 10:
            file_manager.delete_temp_file(temp_path)
            return
        groups[media_group_id]["photos"].append(temp_path)

        timers = context.bot_data.setdefault(MEDIA_GROUP_TIMER_KEY, {})
        if media_group_id in timers:
            timers[media_group_id].cancel()
        loop = asyncio.get_running_loop()
        timers[media_group_id] = loop.create_task(
            _finish_media_group(update, context, media_group_id)
        )
    else:
        await _enqueue_item(
            update, context,
            temp_paths=[temp_path],
            caption=message.caption or "",
            message_id=message.message_id,
        )


async def _finish_media_group(update, context, media_group_id):
    """After album is fully received, enqueue each photo as a separate receipt."""
    await asyncio.sleep(MEDIA_GROUP_DELAY)

    groups = context.bot_data.get(MEDIA_GROUP_KEY, {})
    group_data = groups.pop(media_group_id, None)
    timers = context.bot_data.get(MEDIA_GROUP_TIMER_KEY, {})
    timers.pop(media_group_id, None)

    if not group_data or not group_data["photos"]:
        return

    # Each photo becomes a separate receipt
    for photo_path in group_data["photos"]:
        await _enqueue_item(
            group_data["update"], context,
            temp_paths=[photo_path],
            caption=group_data["caption"],
            message_id=group_data["message_id"],
        )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    doc = message.document
    user_id = update.effective_user.id

    if not check_rate_limit(user_id, max_per_minute=10):
        await message.reply_text(t(user_id, "rate_limit"))
        return

    mime = doc.mime_type or ""

    if not (mime.startswith("image/") or mime == "application/pdf"):
        await message.reply_text(t(user_id, "unsupported_type"))
        return

    if doc.file_size and not file_manager.check_file_size(doc.file_size):
        await message.reply_text(t(user_id, "file_too_large", max_mb=MAX_FILE_SIZE_MB))
        return

    ext = Path(doc.file_name or "").suffix.lower() or (".pdf" if mime == "application/pdf" else ".jpg")
    filename = f"doc_{message.message_id}_{doc.file_id[-8:]}{ext}"
    temp_path = await _download_file(context.bot, doc.file_id, filename)
    if not temp_path:
        await message.reply_text(t(user_id, "download_failed"))
        return

    # Magic-byte validation for images — rejects files with mismatched content
    if mime != "application/pdf":
        import imghdr
        detected = imghdr.what(temp_path)
        if detected not in ("jpeg", "png", "webp"):
            file_manager.delete_temp_file(temp_path)
            await message.reply_text(t(user_id, "invalid_file_type"))
            return

    if mime == "application/pdf":
        loop = asyncio.get_running_loop()
        try:
            pdf_text = await asyncio.wait_for(
                loop.run_in_executor(None, _extract_pdf_text, temp_path),
                timeout=30.0,
            )
        except asyncio.TimeoutError:
            logger.warning("PDF extraction timed out: %s", temp_path)
            pdf_text = ""
        finally:
            file_manager.delete_temp_file(temp_path)
        caption_parts = [f"[PDF: {doc.file_name}]"]
        if pdf_text:
            caption_parts.append(pdf_text[:3000])
        if message.caption:
            caption_parts.append(message.caption)
        await _enqueue_item(
            update, context,
            temp_paths=[],
            caption="\n".join(caption_parts),
            message_id=message.message_id,
        )
    else:
        await _enqueue_item(
            update, context,
            temp_paths=[temp_path],
            caption=message.caption or "",
            message_id=message.message_id,
        )


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not check_rate_limit(user_id, max_per_minute=10):
        await update.message.reply_text(t(user_id, "rate_limit"))
        return
    await update.message.reply_text(t(user_id, "voice_unsupported"))


async def handle_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not check_rate_limit(user_id, max_per_minute=10):
        await update.message.reply_text(t(user_id, "rate_limit"))
        return
    text = update.message.text or update.message.caption or ""
    if text.strip():
        await _enqueue_item(
            update, context,
            temp_paths=[],
            caption=text,
            message_id=update.message.message_id,
        )
    else:
        await update.message.reply_text(t(user_id, "forward_no_data"))
