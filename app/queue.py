from __future__ import annotations

import asyncio
import logging
from collections import deque
from uuid import UUID

logger = logging.getLogger(__name__)

_queue: asyncio.Queue[UUID] = asyncio.Queue()
# FIFO mirror of IDs still inside asyncio.Queue (Queue has no public peek API).
_waiting_ids: deque[UUID] = deque()
_current_file_id: UUID | None = None

# DB statuses that each stage requires before it will do any work.
# If the file is not in one of these statuses the stage function returns None
# without changing anything — we skip it rather than misreporting it as done.
_STAGE_PRECONDITIONS: dict[str, frozenset[str]] = {
    "transcribe": frozenset({"pending", "processing"}),
    "translate": frozenset({"transcribed"}),
    "summarize": frozenset({"translated"}),
    "extract": frozenset({"summarized"}),
}


def enqueue(file_id: UUID) -> None:
    """Put file_id onto the processing queue (non-blocking)."""
    _queue.put_nowait(file_id)
    _waiting_ids.append(file_id)
    logger.info("Enqueued file_id=%s.", file_id)


def get_queue_snapshot() -> dict:
    """Return waiting file IDs (FIFO) and the file currently being processed, if any."""
    return {
        "waiting_file_ids": list(_waiting_ids),
        "current_file_id": _current_file_id,
    }


def reset_processing_queue() -> None:
    """Drop all items from the asyncio queue and clear mirror state. For tests."""
    global _current_file_id
    while not _queue.empty():
        _queue.get_nowait()
        _queue.task_done()
    _waiting_ids.clear()
    _current_file_id = None


async def process_single_file(file_id: UUID) -> None:
    """Run all four pipeline stages for one file, emitting SSE events between stages.

    Each stage is only invoked when the file's current DB status satisfies that
    stage's precondition.  Stages whose precondition is not met are skipped
    silently (no SSE events emitted) so that callers never see a false "done".
    """
    from app.database import get_session
    from app.models import FileRecord
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
        # Only call (and announce) a stage when the file is in the right state.
        with get_session() as session:
            record = session.get(FileRecord, file_id)
            if not record:
                logger.error("process_single_file: file_id=%s not found.", file_id)
                return
            current_status = record.status

        if current_status not in _STAGE_PRECONDITIONS[stage_name]:
            continue  # stage not applicable — skip without emitting any event

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
    global _current_file_id
    logger.info("Queue drain coroutine started.")
    while True:
        file_id = await _queue.get()
        if _waiting_ids and _waiting_ids[0] == file_id:
            _waiting_ids.popleft()
        elif file_id in _waiting_ids:
            _waiting_ids.remove(file_id)
        try:
            _current_file_id = file_id
            await process_single_file(file_id)
        except Exception as exc:
            logger.error(
                "Unexpected error processing file_id=%s: %s",
                file_id,
                exc,
                exc_info=True,
            )
        finally:
            _current_file_id = None
            _queue.task_done()
