from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_MAX_CHARS = 32_000

# ---------------------------------------------------------------------------
# Prompt templates (Phase 2 hardcoded; Phase 3 will move to DB-editable table)
# ---------------------------------------------------------------------------

TRANSLATE_SYSTEM = (
    "You are a professional translator. "
    "Translate the following text into English. "
    "Output only the translated text, with no commentary, "
    "no explanations, and no preamble."
)

TRANSLATE_USER = "Text to translate:\n\n{text}"

SUMMARIZE_SYSTEM = (
    "You are an expert at distilling spoken audio transcripts into concise summaries. "
    "Write a clear, dense summary of the following transcript. "
    "Capture the main topic, key points, and any decisions or conclusions. "
    "Write in third person. Output only the summary, no preamble."
)

SUMMARIZE_USER = "Transcript:\n\n{text}"

EXTRACT_SYSTEM = (
    "You are a structured information extraction system. "
    "Extract entities and facts from the following transcript. "
    "You MUST respond with a single valid JSON object matching this exact schema "
    "and nothing else — no markdown fences, no commentary:\n"
    "{\n"
    '  "people": ["list of person names mentioned"],\n'
    '  "places": ["list of locations mentioned"],\n'
    '  "personal_facts": ["statements of fact about the speaker or their life"],\n'
    '  "action_items": ["tasks or commitments mentioned"],\n'
    '  "topics": ["main subjects discussed"],\n'
    '  "tags": ["short keyword tags for retrieval, max 10"]\n'
    "}\n"
    "Use empty arrays for categories with no relevant content. "
    "Do not invent information not present in the text."
)

EXTRACT_USER = "Transcript:\n\n{text}"


def _guard_text(text: str) -> str:
    """Truncate text to _MAX_CHARS if necessary."""
    if len(text) > _MAX_CHARS:
        logger.warning(
            "Text length %d exceeds limit %d; truncating.", len(text), _MAX_CHARS
        )
        return text[:_MAX_CHARS] + " [truncated]"
    return text


async def _chat(messages: list[dict], temperature: float = 0.3) -> str:
    """Send a chat completion request to llama-server and return the reply text.

    Raises:
        RuntimeError: if LLAMA_SERVER_URL is not configured.
        httpx.ConnectError / httpx.TimeoutException: propagated to caller.
        httpx.HTTPStatusError: on non-2xx response.
    """
    if not settings.llama_server_url:
        raise RuntimeError(
            "LLAMA_SERVER_URL is not configured. Cannot call LLM."
        )

    url = settings.llama_server_url.rstrip("/") + "/v1/chat/completions"
    payload = {
        "model": settings.llama_model,
        "messages": messages,
        "temperature": temperature,
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()

    data = response.json()
    return data["choices"][0]["message"]["content"].strip()


async def translate(text: str, source_lang: str) -> str:
    """Translate text to English using the configured LLM.

    Returns text unchanged if source_lang starts with 'en' (no API call).
    """
    if source_lang.startswith("en"):
        logger.debug("Language is '%s', skipping translation.", source_lang)
        return text

    logger.info("Translating from '%s' to English.", source_lang)
    messages = [
        {"role": "system", "content": TRANSLATE_SYSTEM},
        {"role": "user", "content": TRANSLATE_USER.format(text=_guard_text(text))},
    ]
    return await _chat(messages, temperature=0.3)


async def summarize(text: str) -> str:
    """Generate a dense summary of the given transcript text."""
    logger.info("Summarizing transcript (%d chars).", len(text))
    messages = [
        {"role": "system", "content": SUMMARIZE_SYSTEM},
        {"role": "user", "content": SUMMARIZE_USER.format(text=_guard_text(text))},
    ]
    return await _chat(messages, temperature=0.3)


async def extract(text: str) -> Dict[str, Any]:
    """Extract structured entities and facts from the given transcript.

    Returns a dict with keys: people, places, personal_facts, action_items,
    topics, tags.

    Raises:
        json.JSONDecodeError: if the LLM response cannot be parsed as JSON.
    """
    logger.info("Extracting entities from transcript (%d chars).", len(text))
    messages = [
        {"role": "system", "content": EXTRACT_SYSTEM},
        {"role": "user", "content": EXTRACT_USER.format(text=_guard_text(text))},
    ]
    raw = await _chat(messages, temperature=0.0)

    # Strip markdown fences if the model added them despite instructions
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        logger.error("Failed to parse extraction JSON. Raw response:\n%s", raw)
        raise
