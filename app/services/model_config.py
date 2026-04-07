import logging

from sqlmodel import select

from app.config import settings
from app.database import get_session
from app.models import ModelConfig

logger = logging.getLogger(__name__)

VALID_STEPS = ("transcribe", "translate", "summarize", "extract")

_DEFAULTS = [
    {
        "step": "transcribe",
        "server_url": "",
        "model_name_attr": "whisper_model",
    },
    {
        "step": "translate",
        "server_url_attr": "llama_server_url",
        "model_name_attr": "llama_model",
    },
    {
        "step": "summarize",
        "server_url_attr": "llama_server_url",
        "model_name_attr": "llama_model",
    },
    {
        "step": "extract",
        "server_url_attr": "llama_server_url",
        "model_name_attr": "llama_model",
    },
]


def seed_model_configs() -> None:
    """Idempotent: insert default ModelConfig rows for all 4 steps if missing."""
    with get_session() as session:
        for spec in _DEFAULTS:
            step = spec["step"]
            existing = session.exec(
                select(ModelConfig).where(ModelConfig.step == step)
            ).first()
            if existing is not None:
                continue

            if "server_url" in spec:
                server_url = spec["server_url"]
            else:
                server_url = getattr(settings, spec["server_url_attr"])
            model_name = getattr(settings, spec["model_name_attr"])

            row = ModelConfig(step=step, server_url=server_url, model_name=model_name)
            session.add(row)
            logger.info("Seeding ModelConfig for step=%s", step)

        session.commit()


def get_model_config(step: str) -> ModelConfig:
    """Fetch ModelConfig by step; raises ValueError if not found."""
    with get_session() as session:
        row = session.exec(
            select(ModelConfig).where(ModelConfig.step == step)
        ).first()
        if row is None:
            raise ValueError(f"No ModelConfig found for step={step!r}")
        return row


def upsert_model_config(step: str, server_url: str, model_name: str) -> ModelConfig:
    """Update existing row or insert new one; returns the persisted row."""
    if step not in VALID_STEPS:
        raise ValueError(f"Invalid step {step!r}. Must be one of {VALID_STEPS}")
    with get_session() as session:
        row = session.exec(
            select(ModelConfig).where(ModelConfig.step == step)
        ).first()
        if row is None:
            row = ModelConfig(step=step, server_url=server_url, model_name=model_name)
            session.add(row)
        else:
            row.server_url = server_url
            row.model_name = model_name
            session.add(row)

        session.commit()
        session.refresh(row)
        return row
