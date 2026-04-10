from __future__ import annotations

import asyncio
import logging
from uuid import UUID

logger = logging.getLogger(__name__)

_queue: asyncio.Queue[UUID] = asyncio.Queue()


def enqueue(file_id: UUID) -> None:
    """Put file_id onto the processing queue (non-blocking)."""
    _queue.put_nowait(file_id)
    logger.info("Enqueued file_id=%s.", file_id)


async def process_single_file(file_id: UUID) -> None:
    """Run all four pipeline stages for one file, emitting SSE events between stages."""
    from app.services.pipeline import (
        run_extraction_and_finalize,
        run_summarization,
        run_translation,
        run_transcription,
    )
    from app.sse import emit

    stages = [
        ("transcribe", run_transcription),
        ("translate", run_translation),
        ("summarize", run_summarization),
        ("extract", run_extraction_and_finalize),
    ]

    for stage_name, stage_fn in stages:
        emit(file_id, {"stage": stage_name, "status": "start"})
        error = await stage_fn(file_id)
        if error:
            emit(file_id, {"stage": stage_name, "status": "failed", "error": error})
            logger.warning(
                "Stage %s failed for file_id=%s: %s", stage_name, file_id, error
            )
            return
        emit(file_id, {"stage": stage_name, "status": "done"})

    emit(file_id, {"stage": "pipeline", "status": "complete"})


async def drain_queue() -> None:
    """Background coroutine — drains the queue one file at a time. Never exits."""
    logger.info("Queue drain coroutine started.")
    while True:
        file_id = await _queue.get()
        try:
            await process_single_file(file_id)
        except Exception as exc:
            logger.error(
                "Unexpected error processing file_id=%s: %s",
                file_id,
                exc,
                exc_info=True,
            )
        finally:
            _queue.task_done()
