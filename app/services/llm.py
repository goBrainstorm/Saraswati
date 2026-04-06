from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict

import httpx

from app.config import settings
from app.services.prompts import get_prompt

logger = logging.getLogger(__name__)

_MAX_CHARS = 32_000


def _guard_text(text: str) -> str:
    if len(text) > _MAX_CHARS:
        logger.warning("Text length %d exceeds limit %d; truncating.", len(text), _MAX_CHARS)
        return text[:_MAX_CHARS] + " [truncated]"
    return text


async def _chat(messages: list[dict], temperature: float = 0.3) -> str:
    if not settings.llama_server_url:
        raise RuntimeError("LLAMA_SERVER_URL is not configured. Cannot call LLM.")
    url = settings.llama_server_url.rstrip("/") + "/v1/chat/completions"
    payload = {"model": settings.llama_model, "messages": messages, "temperature": temperature}
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"].strip()


async def translate(text: str, source_lang: str) -> str:
    if source_lang.startswith("en"):
        logger.debug("Language is '%s', skipping translation.", source_lang)
        return text
    logger.info("Translating from '%s' to English.", source_lang)
    messages = [
        {"role": "system", "content": get_prompt("translate_system")},
        {"role": "user", "content": get_prompt("translate_user").format(text=_guard_text(text))},
    ]
    return await _chat(messages, temperature=0.3)


async def summarize(text: str) -> str:
    logger.info("Summarizing transcript (%d chars).", len(text))
    messages = [
        {"role": "system", "content": get_prompt("summarize_system")},
        {"role": "user", "content": get_prompt("summarize_user").format(text=_guard_text(text))},
    ]
    return await _chat(messages, temperature=0.3)


async def extract(text: str) -> Dict[str, Any]:
    logger.info("Extracting entities from transcript (%d chars).", len(text))
    messages = [
        {"role": "system", "content": get_prompt("extract_system")},
        {"role": "user", "content": get_prompt("extract_user").format(text=_guard_text(text))},
    ]
    raw = await _chat(messages, temperature=0.0)
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        logger.error("Failed to parse extraction JSON. Raw response:\n%s", raw)
        raise
