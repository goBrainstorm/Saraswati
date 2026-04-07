import logging
from pathlib import Path
from typing import List, Optional

import httpx
from fastapi import APIRouter, HTTPException, Query
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


class AvailableModelsResponse(BaseModel):
    models: List[str]
    cached: List[str]


@router.get("/config")
async def get_all_configs() -> List[ModelConfig]:
    """Return ModelConfig for all 4 pipeline steps."""
    configs = []
    for step in VALID_STEPS:
        try:
            configs.append(get_model_config(step))
        except ValueError:
            logger.warning("ModelConfig for step %r not found in DB; skipping.", step)
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
async def get_available_models(
    step: str,
    server_url: Optional[str] = Query(default=None),
) -> AvailableModelsResponse:
    """Return available and cached models for a pipeline step.

    For LLM steps, ``server_url`` may be supplied as a query parameter to
    query a URL without persisting it to the database first.  When omitted the
    stored config value is used.
    """
    if step not in VALID_STEPS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid step {step!r}. Valid steps: {list(VALID_STEPS)}",
        )

    if step == "transcribe":
        return AvailableModelsResponse(models=_WHISPER_MODELS, cached=_cached_whisper_models())

    # LLM step — prefer query param, fall back to DB
    if server_url is None:
        try:
            config = get_model_config(step)
        except ValueError:
            return AvailableModelsResponse(models=[], cached=[])
        server_url = config.server_url

    if not server_url:
        return AvailableModelsResponse(models=[], cached=[])

    url = server_url.rstrip("/") + "/v1/models"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("Could not reach LLM server at %s: %s", url, exc)
        raise HTTPException(
            status_code=502,
            detail=f"Could not reach model server at {server_url}: {exc}",
        )

    # OpenAI-style /v1/models uses {"data": [...]}; some servers send "data": null.
    # dict.get("key", default) returns None if the key exists with value null.
    if not isinstance(data, dict):
        logger.warning("Unexpected JSON from model server at %s: not an object", url)
        raw = []
    else:
        raw = data.get("data") or []
    if not isinstance(raw, list):
        logger.warning("Unexpected JSON from model server at %s: data is not a list", url)
        raw = []
    models = [item["id"] for item in raw if isinstance(item, dict) and "id" in item]
    return AvailableModelsResponse(models=models, cached=[])
