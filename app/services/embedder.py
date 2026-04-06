"""Embedding service using sentence-transformers (all-MiniLM-L6-v2).

Provides a lazy singleton model and async helpers used by:
  - the processing pipeline (embed new entries into Qdrant)
  - the RAG retrieval layer (embed chat queries)

Model is loaded once on first call and reused for the lifetime of the process.
All CPU-bound work runs in the default ThreadPoolExecutor so it never blocks
the asyncio event loop.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

_model: Optional[object] = None  # SentenceTransformer, typed as object to avoid top-level import


def _get_model():
    """Lazy singleton: load SentenceTransformer on first call, reuse thereafter."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        model_name = "all-MiniLM-L6-v2"
        logger.info("Loading embedding model '%s'.", model_name)
        _model = SentenceTransformer(model_name)
        logger.info("Embedding model loaded (dim=%d).", _model.get_sentence_embedding_dimension())
    return _model


def _embed_sync(text: str) -> list[float]:
    model = _get_model()
    vector = model.encode(text, normalize_embeddings=True)
    return vector.tolist()


async def embed(text: str) -> list[float]:
    """Embed a single string. Returns a normalised float list (384-dim)."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _embed_sync, text)


def _build_entry_text(transcription: str | None, summary: str | None, extracted_json: str | None) -> str:
    """Combine entry fields into a single string for embedding."""
    parts: list[str] = []
    if transcription:
        parts.append(transcription)
    if summary:
        parts.append(summary)
    if extracted_json:
        try:
            data = json.loads(extracted_json)
            facts = data.get("personal_facts", [])
            topics = data.get("topics", [])
            tags = data.get("tags", [])
            if facts:
                parts.append("Facts: " + "; ".join(facts))
            if topics:
                parts.append("Topics: " + "; ".join(topics))
            if tags:
                parts.append("Tags: " + ", ".join(tags))
        except (json.JSONDecodeError, AttributeError):
            pass
    return "\n\n".join(parts)


async def embed_entry_fields(
    transcription: str | None,
    summary: str | None,
    extracted_json: str | None,
) -> list[float]:
    """Build the combined text for an entry and embed it."""
    text = _build_entry_text(transcription, summary, extracted_json)
    if not text.strip():
        raise ValueError("Entry has no embeddable text (transcription, summary, and extracted_json are all empty).")
    return await embed(text)


async def upsert_entry(entry: object, filename: str) -> str:
    """Embed an entry and upsert it into Qdrant.

    Args:
        entry:    An Entry model instance (transcription, summary, extracted_json, id, created_at).
        filename: Original filename, stored in the Qdrant payload for citation.

    Returns:
        The Qdrant point ID (str UUID of the entry).
    """
    from qdrant_client.models import PointStruct

    vector = await embed_entry_fields(entry.transcription, entry.summary, entry.extracted_json)

    # Extract tags from extracted_json for the payload
    tags: list[str] = []
    if entry.extracted_json:
        try:
            data = json.loads(entry.extracted_json)
            tags = data.get("tags", [])
        except (json.JSONDecodeError, AttributeError):
            pass

    point_id = str(entry.id)
    payload = {
        "entry_id": point_id,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
        "summary": entry.summary,
        "tags": tags,
        "filename": filename,
    }

    client = get_qdrant_client()
    ensure_collection(client, dimension=len(vector))

    client.upsert(
        collection_name=settings.qdrant_collection,
        points=[PointStruct(id=point_id, vector=vector, payload=payload)],
    )
    logger.info("Upserted entry %s into Qdrant collection '%s'.", point_id, settings.qdrant_collection)
    return point_id


def get_qdrant_client():
    """Return a QdrantClient pointed at settings.qdrant_url."""
    from qdrant_client import QdrantClient

    return QdrantClient(url=settings.qdrant_url)


def ensure_collection(client, dimension: int = 384) -> None:
    """Create the Qdrant collection if it does not already exist."""
    from qdrant_client.models import Distance, VectorParams

    existing = {c.name for c in client.get_collections().collections}
    if settings.qdrant_collection not in existing:
        client.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config=VectorParams(size=dimension, distance=Distance.COSINE),
        )
        logger.info("Created Qdrant collection '%s' (dim=%d).", settings.qdrant_collection, dimension)
    else:
        logger.debug("Qdrant collection '%s' already exists.", settings.qdrant_collection)
