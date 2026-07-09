from __future__ import annotations

import asyncio
import logging
from collections import deque
from uuid import UUID

from app.config import settings

logger = logging.getLogger(__name__)

_queue: asyncio.Queue[UUID] = asyncio.Queue()
# FIFO mirror of IDs still inside asyncio.Queue (Queue has no public peek API).
_waiting_ids: deque[UUID] = deque()
_current_file_id: UUID | None = None


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


def set_current_file(file_id: UUID | None) -> None:
    """Record the file the pipeline is actively processing, for the queue panel.

    Called by :func:`app.services.pipeline.process_pending_files` as it iterates
    files so the panel can show real progress instead of always ``None``.
    """
    global _current_file_id
    _current_file_id = file_id


def reset_processing_queue() -> None:
    """Drop all items from the asyncio queue and clear mirror state. For tests."""
    global _current_file_id
    while not _queue.empty():
        _queue.get_nowait()
        _queue.task_done()
    _waiting_ids.clear()
    _current_file_id = None


def _remove_from_waiting(fid: UUID) -> None:
    if _waiting_ids and _waiting_ids[0] == fid:
        _waiting_ids.popleft()
    elif fid in _waiting_ids:
        _waiting_ids.remove(fid)


async def drain_queue() -> None:
    """Background coroutine — coalesces enqueue notifications and runs horizontal batches.

    After the first dequeue, waits :attr:`app.config.Settings.queue_coalesce_debounce_seconds`
    so sequential client uploads (each POST finishing before the next) can enqueue more
    IDs before we run :func:`app.services.pipeline.process_pending_files`, matching
    manual ``POST /api/process`` batching.

    Each logical enqueue still consumes one ``task_done``.
    """
    global _current_file_id
    from app.services.pipeline import process_pending_files

    logger.info("Queue drain coroutine started.")
    while True:
        first_id = await _queue.get()
        batch_ids = [first_id]
        # Sequential uploads enqueue one-by-one; without a short pause, the first
        # process_pending_files run would see only one pending row. Debouncing lets
        # later uploads land in the queue before we snapshot coalesced IDs.
        debounce = float(settings.queue_coalesce_debounce_seconds)
        if debounce > 0:
            await asyncio.sleep(debounce)
        while True:
            try:
                batch_ids.append(_queue.get_nowait())
            except asyncio.QueueEmpty:
                break

        for fid in batch_ids:
            _remove_from_waiting(fid)

        try:
            _current_file_id = None
            await process_pending_files(emit_sse=True)
        except Exception as exc:
            logger.error(
                "Unexpected error in process_pending_files: %s",
                exc,
                exc_info=True,
            )
        finally:
            _current_file_id = None
            for _ in batch_ids:
                _queue.task_done()
