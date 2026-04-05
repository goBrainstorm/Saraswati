"""Runtime-editable prompt store.

Prompts are stored in data/prompts.json. If absent or unreadable, hardcoded defaults are used.
update_prompt() persists changes immediately.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULTS: dict[str, str] = {
    "translate_system": (
        "You are a professional translator. "
        "Translate the following text into English. "
        "Output only the translated text, with no commentary, "
        "no explanations, and no preamble."
    ),
    "translate_user": "Text to translate:\n\n{text}",
    "summarize_system": (
        "You are an expert at distilling spoken audio transcripts into concise summaries. "
        "Write a clear, dense summary of the following transcript. "
        "Capture the main topic, key points, and any decisions or conclusions. "
        "Write in third person. Output only the summary, no preamble."
    ),
    "summarize_user": "Transcript:\n\n{text}",
    "extract_system": (
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
    ),
    "extract_user": "Transcript:\n\n{text}",
}


def _prompts_path() -> Path:
    return Path("data") / "prompts.json"


def load_prompts() -> dict[str, str]:
    """Return the current prompts dict (defaults merged with any saved overrides)."""
    path = _prompts_path()
    if path.exists():
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            merged = dict(DEFAULTS)
            merged.update({k: v for k, v in saved.items() if k in DEFAULTS})
            return merged
        except Exception as exc:
            logger.warning("Failed to load prompts from %s: %s. Using defaults.", path, exc)
    return dict(DEFAULTS)


def get_prompt(name: str) -> str:
    """Return the current value of a single prompt by name."""
    return load_prompts().get(name, DEFAULTS.get(name, ""))


def update_prompt(name: str, text: str) -> None:
    """Persist an updated prompt value to disk.
    Raises ValueError if name is not a recognised prompt key.
    """
    if name not in DEFAULTS:
        raise ValueError(f"Unknown prompt: '{name}'. Valid keys: {list(DEFAULTS)}")
    current = load_prompts()
    current[name] = text
    path = _prompts_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Prompt '%s' updated and saved to %s.", name, path)
