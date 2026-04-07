import logging
from typing import Dict, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.database import get_session
from app.models import FileRecord

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/api/process/{file_id}")
async def trigger_process_single(file_id: UUID) -> Dict[str, Any]:
    """Manually process a specific file without triggering a cache refresh."""
    from app.services.pipeline import (
        run_extraction_and_finalize,
        run_summarization,
        run_transcription,
        run_translation,
    )

    with get_session() as session:
        record = session.get(FileRecord, file_id)
        if not record:
            raise HTTPException(status_code=404, detail="File not found")

    with get_session() as session:
        status = session.get(FileRecord, file_id).status
    if status == "pending":
        err = await run_transcription(file_id)
        if err:
            raise HTTPException(status_code=500, detail=err)

    with get_session() as session:
        status = session.get(FileRecord, file_id).status
    if status == "transcribed":
        err = await run_translation(file_id)
        if err:
            raise HTTPException(status_code=500, detail=err)

    with get_session() as session:
        status = session.get(FileRecord, file_id).status
    if status == "translated":
        err = await run_summarization(file_id)
        if err:
            raise HTTPException(status_code=500, detail=err)

    with get_session() as session:
        status = session.get(FileRecord, file_id).status
    if status == "summarized":
        err = await run_extraction_and_finalize(file_id)
        if err:
            raise HTTPException(status_code=500, detail=err)

    return {"status": "complete", "file_id": str(file_id)}


@router.post("/api/process")
async def trigger_process() -> Dict[str, Any]:
    """Manually trigger the processing pipeline.

    Phase 1 stub: logs the trigger and returns a confirmation.
    Phase 2 will wire Whisper transcription and LLM summarisation here.
    """
    from app.services.pipeline import process_pending_files
    from app.services.cache import write_recent_cache

    logger.info("Manual trigger received via POST /api/process.")
    result = await process_pending_files()
    cache_count = await write_recent_cache()
    return {
        "status": "complete",
        "files_processed": result["attempted"],
        "succeeded": result["succeeded"],
        "failed": result["failed"],
        "errors": result["errors"],
        "cache_entries": cache_count,
    }
