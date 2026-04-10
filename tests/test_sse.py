import asyncio
import json
from uuid import uuid4

import pytest

from app.sse import _subscribers, emit


def _clear_subscribers():
    """Remove any leftover subscribers from prior tests."""
    _subscribers.clear()


async def test_emit_puts_payload_into_subscriber_queues():
    """emit() puts a JSON payload into every active subscriber queue."""
    _clear_subscribers()
    q = asyncio.Queue()
    _subscribers.append(q)

    file_id = uuid4()
    emit(file_id, {"stage": "transcribe", "status": "start"})

    assert q.qsize() == 1
    payload = json.loads(q.get_nowait())
    assert payload["file_id"] == str(file_id)
    assert payload["stage"] == "transcribe"
    assert payload["status"] == "start"

    _subscribers.remove(q)


async def test_emit_broadcasts_to_multiple_subscribers():
    """emit() puts the payload into all subscriber queues, not just one."""
    _clear_subscribers()
    q1, q2 = asyncio.Queue(), asyncio.Queue()
    _subscribers.extend([q1, q2])

    file_id = uuid4()
    emit(file_id, {"stage": "extract", "status": "done"})

    assert q1.qsize() == 1
    assert q2.qsize() == 1

    _subscribers.clear()


async def test_emit_does_nothing_when_no_subscribers():
    """emit() is a no-op when no clients are connected."""
    _clear_subscribers()
    file_id = uuid4()
    # Must not raise
    emit(file_id, {"stage": "translate", "status": "done"})


@pytest.mark.asyncio
async def test_status_stream_handler_returns_event_stream():
    """Route handler exposes text/event-stream (httpx stream() can deadlock on ASGI + async gen)."""
    from app.routes.status import status_stream

    resp = await status_stream()
    assert "text/event-stream" in (resp.media_type or "")
    assert resp.headers.get("cache-control") == "no-cache"


@pytest.mark.asyncio
async def test_sse_body_iterator_receives_emitted_event():
    """StreamingResponse body carries SSE lines after emit() once the subscriber is registered."""
    _clear_subscribers()
    file_id = uuid4()
    chunks: list[bytes] = []

    from app.routes.status import status_stream

    resp = await status_stream()

    async def collect():
        async for chunk in resp.body_iterator:
            chunks.append(
                chunk.encode("utf-8") if isinstance(chunk, str) else chunk
            )
            joined = b"".join(chunks).decode()
            if "summarize" in joined and '"file_id"' in joined:
                break

    task = asyncio.create_task(collect())
    await asyncio.sleep(0.05)
    emit(file_id, {"stage": "summarize", "status": "done"})
    await asyncio.wait_for(task, timeout=3.0)

    joined = b"".join(chunks).decode()
    assert ": connected" in joined or joined.lstrip().startswith(":")
    data_lines = [ln for ln in joined.splitlines() if ln.startswith("data: ")]
    assert data_lines
    payload = json.loads(data_lines[-1][6:])
    assert payload["file_id"] == str(file_id)
    assert payload["stage"] == "summarize"
    _clear_subscribers()
