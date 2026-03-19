"""OpenRouter AI client — receipt parsing from images and text, with fallback models."""
import asyncio
import base64
import json
import logging
import re
from datetime import date, time
from pathlib import Path
from typing import Optional

from openai import AsyncOpenAI

from config import OPENROUTER_API_KEY, OPENROUTER_MODEL, REPO_URL
from models import Receipt, ReceiptItem

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Prompt for classifying chat messages vs. receipt data
CHAT_PROMPT = """Ты — дружелюбный ассистент Telegram-бота для учёта чеков.
Пользователь написал что-то в чат. Определи: это финансовые данные (чек/расход/приход) или просто разговор?

Если это просто разговор (приветствие, вопрос, благодарность) — ответь по-русски, кратко и дружелюбно.
Если это финансовые данные — ответь ТОЛЬКО словом: RECEIPT

Никаких лишних объяснений."""

# Main prompt for structured receipt extraction
AI_PROMPT = """Ты — финансовый ассистент, который анализирует чеки и финансовые данные.
Твоя задача — извлечь структурированную информацию из предоставленных данных.

ОБЯЗАТЕЛЬНО верни ответ ТОЛЬКО в формате JSON, без лишнего текста, без markdown-блоков:

{
  "type": "expense" | "income" | "unknown",
  "store": "название магазина или источника дохода (строка, null если неизвестно)",
  "website": "домен или название платформы (Amazon, Rewe, Lidl, Zalando, PayPal и т.д.) — для расходов, null если неизвестно",
  "total_amount": число — итоговая сумма включая НДС (Gesamt), null если неизвестно,
  "netto": число — сумма без НДС. Если на чеке нет разбивки — ставить равным total_amount,
  "ust_amount": число — сумма НДС в деньгах. Если на чеке нет отдельной строки налога — ВСЕГДА ставить 0, не вычислять,
  "ust_rate": 0 | 7 | 19 | null — ставка НДС только если явно написана на чеке, иначе 0,
  "currency": "EUR" | "USD" | "RUB" | "UAH" | "другое",
  "date": "YYYY-MM-DD",
  "time": "HH:MM" | null,
  "category": "Lebensmittel" | "Restaurant/Café" | "Transport" | "Kleidung" | "Medizin" | "Technik" | "Wohnen" | "Gehalt" | "Überweisung" | "Sonstiges",
  "items": [{"name": "...", "quantity": число, "price": число}],
  "confidence": число от 0 до 1,
  "notes": "замечания или null"
}

Контекст: физические чеки (фото) — скорее всего из немецких магазинов (Rewe, Lidl, Aldi, Netto, Edeka, Kaufland, DM, Rossmann, Penny, Amazon.de и др.), валюта EUR. PDF и текст — могут быть из любой страны.

Если данных недостаточно — заполни что можешь, остальное null. Никогда не придумывай данные.
КРИТИЧНО: Возвращай ТОЛЬКО валидный JSON без каких-либо пояснений."""

# Supported image MIME types
MIME_MAP = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}

# Fallback models used when primary model hits rate limit or is unavailable
FALLBACK_MODELS = [
    "google/gemma-3-27b-it:free",
    "google/gemma-3-12b-it:free",
    "mistralai/mistral-small-3.1-24b-instruct:free",
]

# Model pool for parallel batch processing (used by message_handler)
MODEL_POOL = [
    "nvidia/nemotron-nano-12b-v2-vl:free",
    "google/gemma-3-27b-it:free",
    "google/gemma-3-12b-it:free",
    "mistralai/mistral-small-3.1-24b-instruct:free",
]

# Models available for user selection via /model command
# Each entry: (model_id, short display name)
AVAILABLE_MODELS: list[tuple[str, str]] = [
    ("nvidia/nemotron-nano-12b-v2-vl:free", "Nemotron Nano 12B VL 👁"),
    ("google/gemma-3-27b-it:free",          "Gemma 3 27B 👁"),
    ("google/gemma-3-12b-it:free",          "Gemma 3 12B 👁"),
    ("mistralai/mistral-small-3.1-24b-instruct:free", "Mistral Small 3.1 24B 👁"),
]

# Module-level singleton client — initialized once and reused
_client: Optional[AsyncOpenAI] = None

# Limit concurrent OpenRouter calls to prevent retry storms under rate limiting
_ai_semaphore = asyncio.Semaphore(2)


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            base_url=OPENROUTER_BASE_URL,
            api_key=OPENROUTER_API_KEY,
            default_headers={
                "HTTP-Referer": REPO_URL,
                "X-Title": "Receipt Bot",
            }
        )
    return _client


def _encode_image(image_path: str) -> dict:
    """Encode an image file to base64 and return an OpenAI content block."""
    path = Path(image_path)
    mime = MIME_MAP.get(path.suffix.lower(), "image/jpeg")
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


def _build_content(
    text: str = "",
    image_paths: Optional[list[str]] = None,
    extra_text: str = "",
) -> list:
    """Build the content list for an OpenAI API call."""
    content: list = [{"type": "text", "text": AI_PROMPT}]
    if extra_text:
        content.append({"type": "text", "text": f"Дополнительный контекст: {extra_text}"})
    if text:
        content.append({"type": "text", "text": f"Данные для анализа:\n{text}"})
    for path in (image_paths or []):
        content.append(_encode_image(path))
    return content


def _extract_json(text: str) -> str:
    """Strip markdown code fences and extract the first JSON object."""
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```", "", text)
    text = text.strip()
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        return text[start:end]
    return text


def _parse_ai_response(raw: str) -> dict:
    cleaned = _extract_json(raw)
    return json.loads(cleaned)


def _build_receipt_from_ai(data: dict, raw: str) -> Receipt:
    receipt = Receipt()
    receipt.raw_ai_response = raw

    receipt.type = data.get("type", "unknown")
    if receipt.type not in ("expense", "income", "unknown"):
        receipt.type = "unknown"

    def _clamp_str(v, maxlen: int) -> Optional[str]:
        if v is None: return None
        return str(v)[:maxlen]

    def _clamp_amount(v) -> Optional[float]:
        if v is None: return None
        try:
            f = float(v)
            return f if 0 <= f <= 1_000_000 else None
        except (TypeError, ValueError):
            return None

    receipt.store = _clamp_str(data.get("store"), 200)
    receipt.website = _clamp_str(data.get("website"), 200)
    receipt.total_amount = _clamp_amount(data.get("total_amount"))
    receipt.netto = _clamp_amount(data.get("netto"))
    receipt.ust_amount = _clamp_amount(data.get("ust_amount")) or 0
    receipt.ust_rate = data.get("ust_rate") or 0
    receipt.currency = _clamp_str(data.get("currency"), 10) or "EUR"
    _raw_category = _clamp_str(data.get("category"), 50)
    _VALID_CATEGORIES = {
        "Lebensmittel", "Restaurant/Café", "Transport", "Kleidung",
        "Medizin", "Technik", "Wohnen", "Gehalt", "Überweisung", "Sonstiges",
    }
    receipt.category = _raw_category if _raw_category in _VALID_CATEGORIES else "Sonstiges"
    receipt.confidence = min(1.0, max(0.0, float(data.get("confidence") or 0)))
    receipt.notes = _clamp_str(data.get("notes"), 1000)

    # If netto is not provided, default to total_amount
    if receipt.netto is None and receipt.total_amount is not None:
        receipt.netto = receipt.total_amount

    # Parse date
    date_str = data.get("date")
    if date_str:
        try:
            receipt.receipt_date = date.fromisoformat(date_str)
        except (ValueError, TypeError):
            pass

    # Parse time
    time_str = data.get("time")
    if time_str:
        try:
            h, m = time_str.split(":")
            receipt.receipt_time = time(int(h), int(m))
        except (ValueError, TypeError, AttributeError):
            pass

    # Fall back to today if no date found; reject dates more than 1 year out of range
    from datetime import date as date_cls
    today = date_cls.today()
    if receipt.receipt_date is None:
        receipt.receipt_date = today
    else:
        delta_days = abs((receipt.receipt_date - today).days)
        if delta_days > 366:
            logger.warning("AI returned suspicious date %s (delta %d days), using today", receipt.receipt_date, delta_days)
            receipt.receipt_date = today

    # Cap items list to 100 entries; guard against non-numeric quantity/price
    items_raw = (data.get("items") or [])[:100]
    for item in items_raw:
        if not isinstance(item, dict):
            continue
        try:
            receipt.items.append(ReceiptItem(
                name=str(item.get("name") or "")[:200],
                quantity=float(item.get("quantity") or 1),
                price=float(item.get("price") or 0),
            ))
        except (TypeError, ValueError):
            continue

    if receipt.confidence < 0.5:
        receipt.status = "needs_review"

    return receipt


async def _call_ai(
    content: list,
    attempt: int = 0,
    model: Optional[str] = None,
    _tried: frozenset = frozenset(),
) -> str:
    current_model = model or OPENROUTER_MODEL
    _tried = _tried | {current_model}
    delays = [10, 20, 40]
    try:
        client = _get_client()
        async with _ai_semaphore:
            response = await client.chat.completions.create(
                model=current_model,
                messages=[{"role": "user", "content": content}],
            )
        choices = response.choices if response else None
        if not choices:
            raise ValueError(f"Empty choices from {current_model}")
        return choices[0].message.content or ""
    except Exception as e:
        err_str = str(e)
        is_rate_limit = "429" in err_str or "rate" in err_str.lower()
        is_unavailable = (
            "provider" in err_str.lower() or "503" in err_str
            or "404" in err_str or "Empty choices" in err_str
        )

        if is_rate_limit or is_unavailable:
            # Pick next untried model from pool — never switch to the same model
            next_models = [m for m in MODEL_POOL if m not in _tried]
            if next_models:
                fallback = next_models[0]
                logger.warning("Model %s unavailable, switching to %s", current_model, fallback)
                await asyncio.sleep(3)
                return await _call_ai(content, attempt, model=fallback, _tried=_tried)
            # All models exhausted — fall through to exponential backoff
            logger.warning("All models exhausted for attempt %d", attempt)

        if attempt < len(delays):
            wait = delays[attempt]
            logger.warning("OpenRouter error (attempt %d, model %s): %s — retrying in %ds",
                           attempt + 1, current_model, e, wait)
            await asyncio.sleep(wait)
            # Reset tried set on backoff so models get a second chance after cooldown
            return await _call_ai(content, attempt + 1, model=current_model, _tried=frozenset({current_model}))
        raise


async def _call_and_parse(content: list, model: Optional[str] = None) -> Receipt:
    """Call AI, parse JSON response, retry once on JSONDecodeError."""
    raw = await _call_ai(content, model=model)
    logger.debug("AI response: %s", raw[:300])
    try:
        data = _parse_ai_response(raw)
    except json.JSONDecodeError:
        logger.warning("First JSON parse failed, retrying...")
        raw = await _call_ai(content, model=model)
        data = _parse_ai_response(raw)
    return _build_receipt_from_ai(data, raw)


async def classify_or_chat(text: str) -> str:
    """Classify input as receipt data or casual chat. Returns AI reply or 'RECEIPT'."""
    # Fast pattern matching without AI (saves API quota)
    lower = text.lower().strip()
    GREETINGS = {"привет", "хай", "хэй", "здравствуй", "здравствуйте", "добрый день",
                 "добрый вечер", "доброе утро", "салют", "hi", "hello", "hey"}
    THANKS = {"спасибо", "благодарю", "thanks", "thank you", "спс", "сяп"}
    if lower in GREETINGS or any(lower.startswith(g) for g in GREETINGS):
        return "Привет! 👋 Отправь мне фото чека, PDF или напиши что потратил/получил — я запишу в таблицу."
    if lower in THANKS or any(lower.startswith(t) for t in THANKS):
        return "Пожалуйста! 😊 Если нужно записать чек — просто отправь."

    # Financial keywords or digits — treat as receipt immediately
    RECEIPT_WORDS = {"потратил", "купил", "оплатил", "заплатил", "получил", "зарплата",
                     "перевод", "приход", "расход", "руб", "евро", "₽", "€", "$", "rub", "eur"}
    if any(w in lower for w in RECEIPT_WORDS) or any(c.isdigit() for c in text):
        return "RECEIPT"

    # Short messages without digits — ask AI
    if len(text) < 100:
        try:
            client = _get_client()
            resp = await client.chat.completions.create(
                model=OPENROUTER_MODEL,
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": CHAT_PROMPT},
                    {"type": "text", "text": text},
                ]}],
            )
            answer = (resp.choices[0].message.content or "").strip()
            if answer.upper() == "RECEIPT":
                return "RECEIPT"
            return answer or "RECEIPT"
        except Exception:
            pass

    return "RECEIPT"


async def analyze_text(text: str) -> Receipt:
    """Analyze a text message and extract receipt data."""
    logger.info("AI text analysis: %s", text[:100])
    return await _call_and_parse(_build_content(text=text))


async def analyze_image(image_path: str, extra_text: str = "", model: Optional[str] = None) -> Receipt:
    """Analyze a receipt image. Optionally use a specific model (for parallel batch processing)."""
    logger.info("AI image analysis (model=%s): %s", model or OPENROUTER_MODEL, image_path)
    return await _call_and_parse(_build_content(image_paths=[image_path], extra_text=extra_text), model=model)


async def analyze_multiple_images(image_paths: list[str], extra_text: str = "") -> Receipt:
    """Analyze multiple images of a single receipt (media group)."""
    logger.info("AI analysis of %d images", len(image_paths))
    return await _call_and_parse(_build_content(image_paths=image_paths, extra_text=extra_text))
