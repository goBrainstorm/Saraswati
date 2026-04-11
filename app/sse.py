from __future__ import annotations

import asyncio
import json
import logging
from uuid import UUID

from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

# One asyncio.Queue per active SSE connection. All subscribers get all events.
_subscribers: list[asyncio.Queue[str]] = []


def subscriber_count() -> int:
    """Number of active SSE connections (each has its own asyncio.Queue)."""
    return len(_subscribers)


def emit(file_id: UUID, event: dict) -> None:
    """Broadcast a JSON event to every active SSE subscriber."""
    payload = json.dumps({"file_id": str(file_id), **event})
    for q in _subscribers:
        q.put_nowait(payload)


async def _sse_generator():
    """Async generator that yields SSE lines to one connected client."""
    q: asyncio.Queue[str] = asyncio.Queue()
    _subscribers.append(q)
    logger.debug("SSE subscriber added (total=%d).", len(_subscribers))
    try:
        # Flush headers / unblock clients that wait for the first chunk
        yield ": connected\n\n"
        while True:
            payload = await q.get()
            yield f"data: {payload}\n\n"
    except asyncio.CancelledError:
        pass
    finally:
        if q in _subscribers:
            _subscribers.remove(q)
        logger.debug("SSE subscriber removed (total=%d).", len(_subscribers))


def stream_response() -> StreamingResponse:
    """Return a text/event-stream StreamingResponse for one client connection."""
    return StreamingResponse(
        _sse_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
