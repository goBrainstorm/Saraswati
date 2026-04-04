import logging
from typing import Dict, Any

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/api/process")
async def trigger_process() -> Dict[str, Any]:
    """Manually trigger the processing pipeline.

    Phase 1 stub: logs the trigger and returns a confirmation.
    Phase 2 will wire Whisper transcription and LLM summarisation here.
    """
    from app.services.pipeline import process_pending_files
    from app.services.cache import write_recent_cache

    logger.info("Manual trigger received via POST /api/process.")
    count = await process_pending_files()
    cache_count = await write_recent_cache()
    return {"status": "complete", "files_processed": count, "cache_entries": cache_count}
