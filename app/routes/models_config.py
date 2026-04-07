import logging
from pathlib import Path
from typing import List

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.models import ModelConfig
from app.services.model_config import VALID_STEPS, get_model_config, upsert_model_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/models")

_WHISPER_MODELS = [
    "tiny", "tiny.en",
    "base", "base.en",
    "small", "small.en",
    "medium", "medium.en",
    "large-v1", "large-v2", "large-v3", "large",
]

try:
    from huggingface_hub.constants import HF_HUB_CACHE as _HF_HUB_CACHE
except Exception:
    _HF_HUB_CACHE = None


def _cached_whisper_models() -> List[str]:
    """Return which whisper model names are locally cached in HuggingFace cache."""
    if _HF_HUB_CACHE is None:
        return []
    cached = []
    for name in _WHISPER_MODELS:
        cache_dir = Path(_HF_HUB_CACHE) / f"models--Systran--faster-whisper-{name}"
        if cache_dir.exists():
            cached.append(name)
    return cached


class ModelConfigUpdate(BaseModel):
    server_url: str
    model_name: str


@router.get("/config")
async def get_all_configs() -> List[ModelConfig]:
    """Return ModelConfig for all 4 pipeline steps."""
    configs = []
    for step in VALID_STEPS:
        try:
            configs.append(get_model_config(step))
        except ValueError:
            pass
    return configs


@router.put("/config/{step}")
async def put_config(step: str, body: ModelConfigUpdate) -> ModelConfig:
    """Update server_url and model_name for a pipeline step."""
    if step not in VALID_STEPS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid step {step!r}. Valid steps: {list(VALID_STEPS)}",
        )
    return upsert_model_config(step, body.server_url, body.model_name)


@router.get("/available/{step}")
async def get_available_models(step: str):
    """Return available and cached models for a pipeline step."""
    if step not in VALID_STEPS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid step {step!r}. Valid steps: {list(VALID_STEPS)}",
        )

    if step == "transcribe":
        return {"models": _WHISPER_MODELS, "cached": _cached_whisper_models()}

    # LLM step
    try:
        config = get_model_config(step)
    except ValueError:
        return {"models": [], "cached": []}

    if not config.server_url:
        return {"models": [], "cached": []}

    url = config.server_url.rstrip("/") + "/v1/models"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("Could not reach LLM server at %s: %s", url, exc)
        raise HTTPException(
            status_code=502,
            detail=f"Could not reach model server at {config.server_url}: {exc}",
        )

    models = [item["id"] for item in data.get("data", [])]
    return {"models": models, "cached": []}
