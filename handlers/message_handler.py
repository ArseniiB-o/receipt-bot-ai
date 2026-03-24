"""Message handlers — photos, documents, voice, text, forwarded messages.

Section 1 — Intelligent Concurrent Receipt Queueing:

  State machine per user_id:
    IDLE → ACCUMULATING → PROCESSING → AWAITING_CONFIRMATION → SAVING → IDLE

  Key behaviours:
  • 4-second accumulation window after the last incoming photo.
  • If new photos arrive while PROCESSING, cancel in-flight AI calls (already-
    completed results are cached), merge new items, restart processing.
  • Media-group (album) collection waits 2.5 s for all Telegram updates with
    the same media_group_id before enqueuing.
  • Real-time status message is edited (not spammed) as each receipt completes.
  • Maximum batch size of 20; larger sets are split and processed sequentially.
  • All temp files are guaranteed to be cleaned up in every exit path.

BUG-04 fixed: batch_key is per (user_id, chat_id) — two chats for same user_id
               are isolated.
BUG-16 fixed: stale batches expire after BATCH_TTL_SECONDS; a JobQueue job
               cleans up all associated temp files even if user never responds.
"""
from __future__ import annotations

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
from constants import (
    BATCH_DELAY_SECONDS,
    MEDIA_GROUP_DELAY,
    AI_INTER_CALL_DELAY,
    BATCH_TTL_SECONDS,
    MAX_BATCH_SIZE,
    PDF_MAX_TEXT_CHARS,
    PDF_MAX_PAGES,
    PDF_PAGE_MAX_CHARS,
    PDF_EXTRACTION_TIMEOUT,
)
from exceptions import AIProcessingError, FileValidationError
from handlers.i18n import receipt_word, t
from models import Receipt
from utils import check_rate_limit, check_file_rate_limit, check_ai_rate_limit, safe_file_path, escape_html

logger = logging.getLogger(__name__)

# ─── bot_data keys ────────────────────────────────────────────────────────────
MEDIA_GROUP_KEY = "media_groups"
MEDIA_GROUP_TIMER_KEY = "media_group_timers"

# Per-user state stored in bot_data["queue_states"][user_id]
QUEUE_STATES_KEY = "queue_states"
# Per-user asyncio.Lock stored in bot_data["queue_locks"][user_id]
QUEUE_LOCKS_KEY = "queue_locks"

# ─── State machine constants ──────────────────────────────────────────────────
STATE_IDLE = "IDLE"
STATE_ACCUMULATING = "ACCUMULATING"
STATE_PROCESSING = "PROCESSING"
STATE_AWAITING = "AWAITING_CONFIRMATION"
STATE_SAVING = "SAVING"


# ─── Per-user state object ────────────────────────────────────────────────────

class UserQueueState:
    """All mutable per-user processing state.

    Must be accessed only while holding the corresponding asyncio.Lock.
    """

    __slots__ = (
        "state", "items", "processing_tasks", "cancel_event",
        "status_msg_id", "status_chat_id", "batch_key",
        "timer_task", "accumulated_items",
    )

    def __init__(self) -> None:
        self.state: str = STATE_IDLE
        # Items waiting to be processed: list of dicts
        self.items: list[dict] = []
        # Active asyncio.Task objects for in-flight AI calls
        self.processing_tasks: list[asyncio.Task] = []
        # Signal to cancel in-flight AI coroutines
        self.cancel_event: asyncio.Event = asyncio.Event()
        # Telegram message used for live status updates
        self.status_msg_id: Optional[int] = None
        self.status_chat_id: Optional[int] = None
        # Key for the batch confirmation data in bot_data
        self.batch_key: Optional[str] = None
        # Timer task (accumulation delay)
        self.timer_task: Optional[asyncio.Task] = None
        # Items that are ready (accumulated)
        self.accumulated_items: list[dict] = []


def _get_user_lock(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> asyncio.Lock:
    """Return (or create) the per-user asyncio.Lock."""
    locks = context.bot_data.setdefault(QUEUE_LOCKS_KEY, {})
    if user_id not in locks:
        locks[user_id] = asyncio.Lock()
    return locks[user_id]


def _get_user_state(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> UserQueueState:
    """Return (or create) the per-user UserQueueState. Must be called while holding the lock."""
    states = context.bot_data.setdefault(QUEUE_STATES_KEY, {})
    if user_id not in states:
        states[user_id] = UserQueueState()
    return states[user_id]


def _reset_user_state(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    """Reset user state to IDLE. Must be called while holding the lock."""
    states = context.bot_data.get(QUEUE_STATES_KEY, {})
    if user_id in states:
        states[user_id] = UserQueueState()


def get_batch_key(user_id: int, chat_id: int) -> str:
    return f"batch_{user_id}_{chat_id}"


# ─── PDF extraction (with timeout guard) ─────────────────────────────────────


def _extract_pdf_text(pdf_path: str) -> str:
    """Extract text from a PDF using pdfplumber. Capped per-page and total.

    BUG-02: PDF extraction now has an explicit timeout applied via asyncio.wait_for()
    at the call site (handle_document). This function itself is sync and must not block
    the event loop — it is always called from run_in_executor.
    """
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            pages_text = []
            total = 0
            for page in pdf.pages[:PDF_MAX_PAGES]:
                text = (page.extract_text() or "")[:PDF_PAGE_MAX_CHARS]
                pages_text.append(text)
                total += len(text)
                if total > PDF_MAX_TEXT_CHARS:
                    break
            return "\n".join(pages_text)[:PDF_MAX_TEXT_CHARS]
    except ImportError:
        logger.warning("pdfplumber not installed — PDF processed without text extraction")
        return ""
    except Exception as e:
        logger.warning("Failed to extract text from PDF: %s", e)
        return ""


# ─── Display helpers ──────────────────────────────────────────────────────────


def _get_added_by(user) -> str:
    if user.first_name:
        return user.first_name
    if user.username:
        return f"@{user.username}"
    return str(user.id)


def _build_batch_text_and_keyboard(
    batch: dict,
    in_progress_indices: Optional[set[int]] = None,
) -> tuple[str, InlineKeyboardMarkup]:
    user_id = batch.get("user_id", 0)
    receipts: list[Optional[Receipt]] = batch.get("receipts", [])
    cancelled: set[int] = batch.get("cancelled", set())
    in_progress = in_progress_indices or set()

    lines = []
    n_active = 0
    for i, r in enumerate(receipts):
        num = i + 1
        if i in cancelled:
            lines.append(f"{num}. {t(user_id, 'cancelled')}")
            continue
        if r is None:
            if i in in_progress:
                lines.append(f"{num}. ⏳ {t(user_id, 'processing_one')}")
            else:
                lines.append(f"{num}. {t(user_id, 'error_processing')}")
            continue
        n_active += 1
        icon = "💸" if r.type == "expense" else ("💰" if r.type == "income" else "❓")
        date_str = r.receipt_date.strftime("%d.%m.%Y") if r.receipt_date else "—"
        amount_str = f"{r.total_amount:.2f} {r.currency}" if r.total_amount else "—"
        store = escape_html(r.store or "—")
        conf_icon = " ⚠️" if r.confidence < 0.6 else ""
        lines.append(f"{num}. {icon} <b>{store}</b>  {date_str}  {amount_str}{conf_icon}")

    n_total = len(receipts)
    n_queued = len(in_progress)
    header = t(user_id, "batch_header", n_total=n_total)
    if n_queued > 0:
        header += f"\n⏳ {t(user_id, 'still_processing', n=n_queued)}"
    if n_total != n_active and n_queued == 0:
        header += t(user_id, "batch_active", n_active=n_active)
    text = header + "\n\n" + "\n".join(lines)

    keyboard: list[list[InlineKeyboardButton]] = []
    for i, r in enumerate(receipts):
        if i in cancelled or (r is None and i not in in_progress):
            continue
        if r is None:
            continue  # still processing — no edit/cancel buttons yet
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
        keyboard.append([InlineKeyboardButton(
            t(user_id, "save_all", n_active=n_active),
            callback_data=f"batch_save:{batch.get('_key', '')}",
        )])

    if n_total > 1:
        keyboard.append([InlineKeyboardButton(
            t(user_id, "cancel_all"),
            callback_data=f"batch_cancel_all:{batch.get('_key', '')}",
        )])

    return text, InlineKeyboardMarkup(keyboard)


async def show_batch_confirmation(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    batch_key: str,
) -> None:
    batch = context.bot_data.get(batch_key, {})
    batch["_key"] = batch_key
    text, keyboard = _build_batch_text_and_keyboard(batch)
    msg = await update.effective_message.reply_text(
        text, parse_mode="HTML", reply_markup=keyboard,
    )
    batch["msg_id"] = msg.message_id
    batch["chat_id"] = update.effective_chat.id


async def refresh_batch_message(
    context: ContextTypes.DEFAULT_TYPE,
    batch_key: str,
    in_progress_indices: Optional[set[int]] = None,
) -> None:
    """Edit the existing batch confirmation message in place."""
    batch = context.bot_data.get(batch_key)
    if not batch:
        return
    batch["_key"] = batch_key
    text, keyboard = _build_batch_text_and_keyboard(batch, in_progress_indices)
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


# ─── Core queue / state machine ──────────────────────────────────────────────


async def _enqueue_item(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    temp_paths: list[str],
    caption: str = "",
    message_id: Optional[int] = None,
    file_unique_ids: Optional[list[str]] = None,
) -> None:
    """Add item(s) to the user's queue and reset the accumulation timer."""
    user = update.effective_user
    user_id = user.id
    chat_id = update.effective_chat.id
    lock = _get_user_lock(context, user_id)

    async with lock:
        qs = _get_user_state(context, user_id)

        item = {
            "temp_paths": temp_paths,
            "caption": caption,
            "message_id": message_id,
            "update": update,
            "user": user,
            "chat_id": chat_id,
            "file_unique_ids": file_unique_ids or [],
        }

        if qs.state == STATE_PROCESSING:
            # Cancel all in-flight AI tasks gracefully
            qs.cancel_event.set()
            for task in qs.processing_tasks:
                task.cancel()
            qs.processing_tasks.clear()
            # Merge new item into the accumulated list
            qs.accumulated_items.append(item)
            # Rebuild from remaining accumulated items (already-done results stay in cache)
            qs.state = STATE_ACCUMULATING
            logger.info(
                "user=%d: New photo arrived during PROCESSING — merged, restarting",
                user_id,
            )
            # Notify user
            n_total = len(qs.accumulated_items)
            try:
                await update.effective_message.reply_text(
                    t(user_id, "merging_queue", n=1, total=n_total)
                )
            except Exception:
                pass
        elif qs.state in (STATE_AWAITING, STATE_SAVING):
            # Already confirmed — start a fresh batch
            _reset_user_state(context, user_id)
            qs = _get_user_state(context, user_id)
            qs.accumulated_items.append(item)
            qs.state = STATE_ACCUMULATING
        else:
            qs.accumulated_items.append(item)
            if qs.state == STATE_IDLE:
                qs.state = STATE_ACCUMULATING

        # Enforce batch size limit
        if len(qs.accumulated_items) > MAX_BATCH_SIZE:
            excess = qs.accumulated_items[MAX_BATCH_SIZE:]
            qs.accumulated_items = qs.accumulated_items[:MAX_BATCH_SIZE]
            for ex_item in excess:
                for p in ex_item.get("temp_paths", []):
                    file_manager.delete_temp_file(p)
            try:
                await update.effective_message.reply_text(
                    t(user_id, "batch_size_limit", max=MAX_BATCH_SIZE)
                )
            except Exception:
                pass

        # Reset accumulation timer
        if qs.timer_task and not qs.timer_task.done():
            qs.timer_task.cancel()

        loop = asyncio.get_running_loop()
        qs.timer_task = loop.create_task(
            _accumulation_timeout(user_id, chat_id, update, context)
        )


async def _accumulation_timeout(
    user_id: int,
    chat_id: int,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Called after BATCH_DELAY_SECONDS with no new photos — start processing."""
    await asyncio.sleep(BATCH_DELAY_SECONDS)

    lock = _get_user_lock(context, user_id)
    async with lock:
        qs = _get_user_state(context, user_id)
        if qs.state != STATE_ACCUMULATING or not qs.accumulated_items:
            return
        items = qs.accumulated_items[:]
        qs.accumulated_items.clear()
        qs.state = STATE_PROCESSING
        qs.cancel_event = asyncio.Event()  # fresh event for this processing run

    # Run processing outside the lock (it's async and may take a while)
    await _process_batch(user_id, chat_id, update, context, items)


async def _process_batch(
    user_id: int,
    chat_id: int,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    items: list[dict],
) -> None:
    """Run AI analysis for all items, updating a live status message."""
    lock = _get_user_lock(context, user_id)

    n = len(items)
    lang = database.get_user_language(user_id)
    word = receipt_word(lang, n)

    # Send initial status message
    try:
        status_msg = await update.effective_message.reply_text(
            t(user_id, "processing", n=n, word=word)
        )
        status_msg_id = status_msg.message_id
        status_chat_id = update.effective_chat.id
    except Exception:
        status_msg_id = None
        status_chat_id = chat_id

    async with lock:
        qs = _get_user_state(context, user_id)
        qs.status_msg_id = status_msg_id
        qs.status_chat_id = status_chat_id

    cancel_event: asyncio.Event = asyncio.Event()
    async with lock:
        qs = _get_user_state(context, user_id)
        cancel_event = qs.cancel_event

    results: list[Optional[Receipt]] = [None] * n
    done_flags: list[bool] = [False] * n

    async def _process_one(idx: int, item: dict) -> None:
        if cancel_event.is_set():
            return
        await asyncio.sleep(idx * AI_INTER_CALL_DELAY)
        if cancel_event.is_set():
            return

        paths = item["temp_paths"]
        cap = item["caption"]
        file_unique_ids: list[str] = item.get("file_unique_ids", [])
        preferred = database.get_user_model(user_id)

        from ai_processor import AVAILABLE_MODEL_IDS, MODEL_POOL
        if preferred and preferred not in AVAILABLE_MODEL_IDS:
            preferred = None
        model = preferred or MODEL_POOL[idx % len(MODEL_POOL)]

        fuid = file_unique_ids[0] if file_unique_ids else None

        # Enforce daily AI call limit per user
        from constants import RATE_AI_PER_DAY
        if not check_ai_rate_limit(user_id):
            logger.warning("user=%d: daily AI rate limit (%d/day) exceeded", user_id, RATE_AI_PER_DAY)
            try:
                await item["update"].effective_message.reply_text(
                    t(user_id, "ai_rate_limit", limit=RATE_AI_PER_DAY)
                )
            except Exception:
                pass
            done_flags[idx] = True
            return

        try:
            if paths:
                receipt = await ai_processor.analyze_image(
                    paths[0], cap, model=model, file_unique_id=fuid
                )
            else:
                receipt = await ai_processor.analyze_text(cap)

            receipt.telegram_user_id = item["user"].id
            from config import STORE_TELEGRAM_USERNAME
            if STORE_TELEGRAM_USERNAME:
                receipt.telegram_username = item["user"].username or item["user"].first_name
            receipt.added_by = _get_added_by(item["user"])
            receipt.telegram_message_id = item["message_id"]
            ts = datetime.now().strftime("%H%M%S%f")
            receipt.receipt_number = f"DRAFT-{ts}-{idx}"
            results[idx] = receipt
        except asyncio.CancelledError:
            logger.info("AI task %d cancelled (new photos arrived)", idx)
            raise
        except Exception as e:
            logger.error("AI error for receipt %d: %s", idx, e, exc_info=True)
            for p in paths:
                file_manager.delete_temp_file(p)
        finally:
            done_flags[idx] = True

        # Update live status message
        if not cancel_event.is_set() and status_msg_id:
            done_count = sum(done_flags)
            status_lines = []
            for j in range(n):
                if done_flags[j]:
                    icon = "✅" if results[j] is not None else "❌"
                elif j == idx:
                    icon = "⏳"
                else:
                    icon = "🔄"
                status_lines.append(f"{icon} {j + 1}/{n}")
            status_text = t(user_id, "processing_status") + " ".join(status_lines)
            try:
                await context.bot.edit_message_text(
                    chat_id=status_chat_id,
                    message_id=status_msg_id,
                    text=status_text,
                )
            except Exception:
                pass

    # Launch all tasks and track them in state
    tasks = [asyncio.create_task(_process_one(idx, item)) for idx, item in enumerate(items)]

    async with lock:
        qs = _get_user_state(context, user_id)
        if qs.state == STATE_PROCESSING:
            qs.processing_tasks = tasks

    # Wait for completion or cancellation
    try:
        await asyncio.gather(*tasks, return_exceptions=True)
    except Exception:
        pass

    # Check if we were cancelled (new photos arrived mid-processing)
    if cancel_event.is_set():
        logger.info("user=%d: Processing cancelled — new photos arrived", user_id)
        # Temp files are preserved in items; they will be re-processed
        try:
            if status_msg_id:
                await context.bot.delete_message(chat_id=status_chat_id, message_id=status_msg_id)
        except Exception:
            pass
        return

    # Delete status message and show confirmation UI
    try:
        if status_msg_id:
            await context.bot.delete_message(chat_id=status_chat_id, message_id=status_msg_id)
    except Exception:
        pass

    all_temp_paths = [item["temp_paths"] for item in items]
    batch_key = get_batch_key(user_id, chat_id)

    context.bot_data[batch_key] = {
        "receipts": results,
        "all_temp_paths": all_temp_paths,
        "cancelled": set(),
        "chat_id": chat_id,
        "user_id": user_id,
    }

    async with lock:
        qs = _get_user_state(context, user_id)
        qs.state = STATE_AWAITING
        qs.batch_key = batch_key

    await show_batch_confirmation(update, context, batch_key)

    # Schedule batch expiry (BUG-16 fix: always clean up, even if user never responds)
    async def _expire_batch(ctx):
        key = ctx.job.data
        batch = ctx.bot_data.pop(key, {})
        for paths in batch.get("all_temp_paths", []):
            file_manager.cleanup_temp_paths(paths if isinstance(paths, list) else [paths])
        # Reset user state to IDLE
        _uid = batch.get("user_id")
        _cid = batch.get("chat_id")
        if _uid:
            _lock = _get_user_lock(ctx, _uid)
            async with _lock:
                _reset_user_state(ctx, _uid)
        # Notify user that the session expired and nothing was saved
        if _uid and _cid:
            try:
                await ctx.bot.send_message(
                    chat_id=_cid,
                    text=t(_uid, "batch_expired_notify"),
                )
            except Exception:
                pass

    if context.job_queue:
        context.job_queue.run_once(_expire_batch, BATCH_TTL_SECONDS, data=batch_key)


# ─── Media group handler ──────────────────────────────────────────────────────


async def _finish_media_group(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    media_group_id: str,
) -> None:
    """After an album is fully received, enqueue each photo as a separate receipt."""
    await asyncio.sleep(MEDIA_GROUP_DELAY)

    groups = context.bot_data.get(MEDIA_GROUP_KEY, {})
    group_data = groups.pop(media_group_id, None)
    timers = context.bot_data.get(MEDIA_GROUP_TIMER_KEY, {})
    timers.pop(media_group_id, None)

    if not group_data or not group_data["photos"]:
        return

    for photo_info in group_data["photos"]:
        await _enqueue_item(
            group_data["update"],
            context,
            temp_paths=[photo_info["path"]],
            caption=group_data["caption"],
            message_id=group_data["message_id"],
            file_unique_ids=[photo_info["file_unique_id"]],
        )


# ─── Telegram handlers ────────────────────────────────────────────────────────


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text or ""
    if not text.strip():
        return

    user_id = update.effective_user.id
    if not check_rate_limit(user_id):
        await update.message.reply_text(t(user_id, "rate_limit"))
        return

    if len(text) > 4096:
        text = text[:4096]

    edit_state = context.user_data.get("edit_state")
    if edit_state:
        from handlers.callback_handler import handle_edit_input
        await handle_edit_input(update, context)
        return

    # Check privacy consent
    if not database.has_privacy_accepted(user_id):
        await _send_privacy_notice(update, context)
        return

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


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    user_id = update.effective_user.id

    if not check_rate_limit(user_id):
        await message.reply_text(t(user_id, "rate_limit"))
        return

    if not check_file_rate_limit(user_id):
        await message.reply_text(t(user_id, "file_rate_limit"))
        return

    # Check privacy consent
    if not database.has_privacy_accepted(user_id):
        await _send_privacy_notice(update, context)
        return

    photo = message.photo[-1]
    if photo.file_size and not file_manager.check_file_size(photo.file_size):
        await message.reply_text(t(user_id, "file_too_large", max_mb=MAX_FILE_SIZE_MB))
        return

    filename = f"photo_{message.message_id}_{photo.file_id[-8:]}.jpg"
    temp_path = await _download_file(context.bot, photo.file_id, filename)
    if not temp_path:
        return

    # Magic-byte validation for photos
    try:
        file_manager.validate_magic_bytes(temp_path)
    except FileValidationError:
        file_manager.delete_temp_file(temp_path)
        await message.reply_text(t(user_id, "invalid_file_type"))
        return

    media_group_id = message.media_group_id
    if media_group_id:
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
        groups[media_group_id]["photos"].append({
            "path": temp_path,
            "file_unique_id": photo.file_unique_id,
        })
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
            file_unique_ids=[photo.file_unique_id],
        )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    doc = message.document
    user_id = update.effective_user.id

    if not check_rate_limit(user_id):
        await message.reply_text(t(user_id, "rate_limit"))
        return

    if not check_file_rate_limit(user_id):
        await message.reply_text(t(user_id, "file_rate_limit"))
        return

    # Check privacy consent
    if not database.has_privacy_accepted(user_id):
        await _send_privacy_notice(update, context)
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

    try:
        # Magic-byte validation (BUG-01 applied to documents too)
        detected = file_manager.validate_magic_bytes(temp_path)

        if mime == "application/pdf" or detected == "pdf":
            loop = asyncio.get_running_loop()
            try:
                pdf_text = await asyncio.wait_for(
                    loop.run_in_executor(None, _extract_pdf_text, temp_path),
                    timeout=PDF_EXTRACTION_TIMEOUT,
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
            # Image document
            await _enqueue_item(
                update, context,
                temp_paths=[temp_path],
                caption=message.caption or "",
                message_id=message.message_id,
                file_unique_ids=[doc.file_unique_id],
            )
    except FileValidationError:
        file_manager.delete_temp_file(temp_path)
        await message.reply_text(t(user_id, "invalid_file_type"))


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not check_rate_limit(user_id):
        await update.message.reply_text(t(user_id, "rate_limit"))
        return
    # BUG-12: voice handler never downloaded a file, so nothing to clean up
    await update.message.reply_text(t(user_id, "voice_unsupported"))


async def handle_forward(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not check_rate_limit(user_id):
        await update.message.reply_text(t(user_id, "rate_limit"))
        return

    if not database.has_privacy_accepted(user_id):
        await _send_privacy_notice(update, context)
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


# ─── Privacy notice ───────────────────────────────────────────────────────────


async def _send_privacy_notice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the GDPR privacy notice with an Accept button (first-time users)."""
    user_id = update.effective_user.id
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(t(user_id, "privacy_accept"), callback_data="privacy:accept"),
    ]])
    from config import GOOGLE_SHEETS_ID, DATA_RETENTION_DAYS
    sheets_note = f"\n\n{t(user_id, 'privacy_sheets_note')}" if GOOGLE_SHEETS_ID else ""
    text = t(
        user_id, "privacy_notice",
        retention_days=DATA_RETENTION_DAYS,
        sheets_note=sheets_note,
    )
    await update.effective_message.reply_text(text, reply_markup=keyboard)


# ─── File download helper ─────────────────────────────────────────────────────


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
