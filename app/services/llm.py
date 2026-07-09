from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict

import httpx

from app.config import settings
from app.services.prompts import get_prompt

logger = logging.getLogger(__name__)

# Coarse char-based cap used as a stand-in for a real token limit; configurable
# via LLM_MAX_INPUT_CHARS. ~4 chars/token, so 32k chars ~ 8k tokens.
_MAX_CHARS = settings.llm_max_input_chars


async def check_llm_server_ready(step: str) -> str | None:
    """Return None if the OpenAI-compatible server (e.g. llama.cpp) looks usable.

    Probes ``GET /v1/models`` and, when the server returns a non-empty model list,
    ensures ``ModelConfig.model_name`` is listed so we skip whole batches instead
    of failing every file with connection errors.
    """
    from app.services.model_config import get_model_config

    try:
        cfg = get_model_config(step)
    except ValueError as exc:
        return str(exc)
    server_url = (cfg.server_url or "").strip()
    if not server_url:
        return "LLM server URL is not configured"
    model_name = (cfg.model_name or "").strip()
    models_url = server_url.rstrip("/") + "/v1/models"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(models_url)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        return f"LLM server unreachable ({server_url}): {exc}"

    raw = data.get("data") or [] if isinstance(data, dict) else []
    if not isinstance(raw, list):
        raw = []
    ids = [item["id"] for item in raw if isinstance(item, dict) and "id" in item]
    if ids and model_name and model_name not in ids:
        preview = ids[:8]
        suffix = "..." if len(ids) > 8 else ""
        return (
            f"Model {model_name!r} not loaded on server "
            f"(available ids: {preview}{suffix})"
        )
    return None


def _guard_text(text: str) -> str:
    if len(text) > _MAX_CHARS:
        logger.warning("Text length %d exceeds limit %d; truncating.", len(text), _MAX_CHARS)
        return text[:_MAX_CHARS] + " [truncated]"
    return text


async def _chat(messages: list[dict], temperature: float = 0.3, step: str | None = None) -> str:
    if step is not None:
        from app.services.model_config import get_model_config  # local import to avoid circular imports
        cfg = get_model_config(step)
        server_url = cfg.server_url
        model_name = cfg.model_name
    else:
        server_url = settings.llama_server_url
        model_name = settings.llama_model
    if not server_url:
        raise RuntimeError("LLAMA_SERVER_URL is not configured. Cannot call LLM.")
    url = server_url.rstrip("/") + "/v1/chat/completions"
    payload = {"model": model_name, "messages": messages, "temperature": temperature}
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
    data = response.json()
    # Validate the OpenAI-shaped response instead of blindly indexing, so a
    # server-side error JSON or empty choices list becomes a clear, retryable
    # error rather than a raw KeyError/IndexError.
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        preview = repr(data)[:300]
        raise RuntimeError(f"Unexpected LLM response shape: {preview}")
    if not isinstance(content, str):
        raise RuntimeError("LLM response 'content' was missing or not a string.")
    return content.strip()


async def translate(text: str, source_lang: str) -> str:
    if source_lang.startswith("en"):
        logger.debug("Language is '%s', skipping translation.", source_lang)
        return text
    logger.info("Translating from '%s' to English.", source_lang)
    messages = [
        {"role": "system", "content": get_prompt("translate_system")},
        {"role": "user", "content": get_prompt("translate_user").format(text=_guard_text(text))},
    ]
    return await _chat(messages, temperature=0.3, step="translate")


async def summarize(text: str) -> str:
    logger.info("Summarizing transcript (%d chars).", len(text))
    messages = [
        {"role": "system", "content": get_prompt("summarize_system")},
        {"role": "user", "content": get_prompt("summarize_user").format(text=_guard_text(text))},
    ]
    return await _chat(messages, temperature=0.3, step="summarize")


async def extract(text: str) -> Dict[str, Any]:
    logger.info("Extracting entities from transcript (%d chars).", len(text))
    messages = [
        {"role": "system", "content": get_prompt("extract_system")},
        {"role": "user", "content": get_prompt("extract_user").format(text=_guard_text(text))},
    ]
    raw = await _chat(messages, temperature=0.0, step="extract")
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        logger.error("Failed to parse extraction JSON. Raw response:\n%s", raw)
        raise
