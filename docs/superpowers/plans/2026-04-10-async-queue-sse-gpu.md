# Async Queue + SSE + GPU Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the cron-fired `pipeline_job` with an in-process `asyncio.Queue` that processes files immediately on upload, add an SSE endpoint so the browser gets live stage-progress events, and enable GPU (CUDA) for faster-whisper via Docker passthrough.

**Architecture:** A module-level `asyncio.Queue` in `app/queue.py` is enqueued from the upload route and drained by a background coroutine started at lifespan. A companion `app/sse.py` module maintains a list of per-connection `asyncio.Queue` instances; `emit()` broadcasts JSON events to all of them. A plain `EventSource` JS call in `index.html` receives events and triggers an HTMX reload of the status table fragment.

**Tech Stack:** FastAPI, asyncio, faster-whisper (CUDA/CPU auto), HTMX polling + EventSource, Docker Compose NVIDIA GPU passthrough.

---

## Pre-flight note

`app/config.py` already has `whisper_device: Literal["auto", "cuda", "cpu"] = Field(default="auto", ...)` and `app/services/whisper_service.py` already reads `settings.whisper_device` with CUDA→CPU fallback. **No changes needed to those two files.**

---

## File Map

| File | Action |
|---|---|
| `app/queue.py` | **Create** — asyncio queue, `enqueue()`, `process_single_file()`, `drain_queue()` |
| `app/sse.py` | **Create** — subscriber list, `emit()`, `_sse_generator()`, `stream_response()` |
| `app/routes/status.py` | **Modify** — add `GET /api/status/stream` route (3 lines) |
| `app/routes/upload.py` | **Modify** — add `queue.enqueue(file_id)` after commit (2 lines) |
| `main.py` | **Modify** — add `asyncio.create_task(drain_queue())` in lifespan startup |
| `app/scheduler.py` | **Modify** — remove `pipeline_job` function and its `add_job` call |
| `app/templates/index.html` | **Modify** — add `EventSource` JS that triggers status-panel reload on SSE events |
| `docker-compose.yml` | **Modify** — add FastAPI app service with GPU passthrough |
| `tests/test_queue.py` | **Create** — queue integration tests |
| `tests/test_sse.py` | **Create** — SSE endpoint tests |

---

## Task 1: Create `app/queue.py`

**Files:**
- Create: `app/queue.py`

- [ ] **Step 1: Write the file**

```python
# app/queue.py
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
        run_transcription,
        run_translation,
        run_summarization,
        run_extraction_and_finalize,
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
```

- [ ] **Step 2: Verify syntax**

```bash
python -c "import app.queue; print('ok')"
```
Expected output: `ok`

---

## Task 2: Create `app/sse.py`

**Files:**
- Create: `app/sse.py`

- [ ] **Step 1: Write the file**

```python
# app/sse.py
from __future__ import annotations

import asyncio
import json
import logging
from uuid import UUID

from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

# One asyncio.Queue per active SSE connection. All subscribers get all events.
_subscribers: list[asyncio.Queue[str]] = []


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
```

- [ ] **Step 2: Verify syntax**

```bash
python -c "import app.sse; print('ok')"
```
Expected output: `ok`

---

## Task 3: Add `GET /api/status/stream` to `app/routes/status.py`

**Files:**
- Modify: `app/routes/status.py`

The existing imports at the top of `status.py` already have `from fastapi.responses import HTMLResponse` and `Response`. Add the SSE route at the end of the file.

- [ ] **Step 1: Add import and route**

In `app/routes/status.py`, add this import at the top alongside the other `from fastapi.responses` imports:

```python
from app.sse import stream_response
```

Then append this route at the bottom of the file:

```python
@router.get("/api/status/stream")
async def status_stream() -> StreamingResponse:
    """SSE stream — yields stage-progress events for all active pipeline runs."""
    return stream_response()
```

Note: `StreamingResponse` is already imported at line 6 via `from fastapi.responses import ...` — confirm it's in the existing import line or add it.

- [ ] **Step 2: Confirm `StreamingResponse` is imported**

Open `app/routes/status.py` and check line 6. The existing import is:
```python
from fastapi.responses import JSONResponse
from fastapi.responses import HTMLResponse
```

`StreamingResponse` is not there. Add it to the second import line:
```python
from fastapi.responses import HTMLResponse, StreamingResponse
```

- [ ] **Step 3: Verify the app still loads**

```bash
python -c "from app.routes import status; print('ok')"
```
Expected output: `ok`

- [ ] **Step 4: Commit**

```bash
git add app/queue.py app/sse.py app/routes/status.py
git commit -m "feat: add asyncio queue, SSE broadcaster, and /api/status/stream route"
```

---

## Task 4: Wire queue into the upload route

**Files:**
- Modify: `app/routes/upload.py`

- [ ] **Step 1: Add the enqueue call**

In `app/routes/upload.py`, find the block after `session.refresh(record)` and before `return record`. Add the import at the top of the file alongside existing imports, and the enqueue call inside the route:

Add to top-level imports (after `from app.models import FileRecord`):
```python
from app import queue as _queue_module
```

Replace the final lines of `upload_file()`:
```python
        session.refresh(record)

        logger.info("Created FileRecord id=%s for '%s'.", record.id, original_name)
        _queue_module.enqueue(record.id)
        return record
```

The only new line is `_queue_module.enqueue(record.id)` — it goes between `logger.info(...)` and `return record`.

- [ ] **Step 2: Verify syntax**

```bash
python -c "from app.routes import upload; print('ok')"
```
Expected output: `ok`

- [ ] **Step 3: Commit**

```bash
git add app/routes/upload.py
git commit -m "feat: enqueue file_id immediately after upload"
```

---

## Task 5: Start `drain_queue` in `main.py` lifespan

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add import and task creation**

In `main.py`, add the import at the top alongside the existing `from app.scheduler` line:
```python
from app.queue import drain_queue
```

In the `lifespan()` function, add the task creation **after** `start_scheduler()` and **before** `yield`:
```python
    # Start background scheduler
    start_scheduler()

    # Start queue drain coroutine
    asyncio.create_task(drain_queue())

    yield
```

Also add `import asyncio` at the top of `main.py` if not already present. Check line 1–6: it isn't imported. Add it:
```python
import asyncio
import logging
import sys
```

- [ ] **Step 2: Verify the app loads**

```bash
python -c "import main; print('ok')"
```
Expected output: `ok`

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: start drain_queue background coroutine at lifespan startup"
```

---

## Task 6: Remove `pipeline_job` from `app/scheduler.py`

**Files:**
- Modify: `app/scheduler.py`

- [ ] **Step 1: Remove `pipeline_job` function and its registration**

Delete the entire `pipeline_job` async function (lines 18–30 in the current file):
```python
async def pipeline_job() -> None:
    """Scheduled pipeline: process all pending files then refresh cache."""
    from app.services.pipeline import process_pending_files
    from app.services.cache import write_recent_cache

    logger.info("pipeline_job starting.")
    result = await process_pending_files()
    logger.info(
        "pipeline_job: %d attempted, %d succeeded, %d failed.",
        result["attempted"], result["succeeded"], result["failed"],
    )
    cache_count = await write_recent_cache()
    logger.info("Cache refreshed: %d entries in recent.json.", cache_count)
```

In `start_scheduler()`, delete the `pipeline_job` registration block:
```python
    # Pipeline job — follows SCHEDULE_CRON
    scheduler.add_job(
        pipeline_job,
        trigger=_parse_cron(settings.schedule_cron),
        id="pipeline_job",
        name="Scheduled processing pipeline",
        replace_existing=True,
    )
```

Also update the `logger.info` in `start_scheduler()` — remove the pipeline_job reference:

Replace:
```python
    logger.info(
        "Scheduler started. pipeline_job cron='%s', cleanup_job cron='0 4 * * *'.",
        settings.schedule_cron,
    )
```
With:
```python
    logger.info("Scheduler started. cleanup_job cron='0 4 * * *'.")
```

The `settings.schedule_cron` import is still used by `_parse_cron` — check if anything else in the file uses `settings`. Only `_parse_cron` uses it now. But `_parse_cron` itself is now unused (only called by the deleted `add_job` block). Delete `_parse_cron` too and its call to `settings.schedule_cron`:

Delete the `_parse_cron` function (lines 46–60):
```python
def _parse_cron(cron_expr: str) -> CronTrigger:
    """Parse a five-field cron expression into an APScheduler CronTrigger."""
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        raise ValueError(
            f"SCHEDULE_CRON must be a five-field cron expression, got: '{cron_expr}'"
        )
    minute, hour, day, month, day_of_week = parts
    return CronTrigger(
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=day_of_week,
    )
```

Also remove the unused imports: `import asyncio` at line 1 and `from app.config import settings` at line 7 — both become unused after the deletion. Remove them.

The final `app/scheduler.py` should look like:

```python
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


# ---------------------------------------------------------------------------
# Job callables
# ---------------------------------------------------------------------------

async def cleanup_job() -> None:
    """Daily cleanup: remove local files past their retention window."""
    from app.services.cleanup import delete_expired_files

    logger.info("Cleanup job starting.")
    await delete_expired_files()
    logger.info("Cleanup job finished.")


# ---------------------------------------------------------------------------
# Scheduler lifecycle
# ---------------------------------------------------------------------------

def start_scheduler() -> None:
    """Register jobs and start the AsyncIOScheduler."""
    # Cleanup job — daily at 04:00
    scheduler.add_job(
        cleanup_job,
        trigger=CronTrigger(hour=4, minute=0),
        id="cleanup_job",
        name="Daily local-file cleanup",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("Scheduler started. cleanup_job cron='0 4 * * *'.")


def stop_scheduler() -> None:
    """Gracefully shut down the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped.")
```

- [ ] **Step 2: Verify syntax**

```bash
python -c "from app.scheduler import start_scheduler; print('ok')"
```
Expected output: `ok`

- [ ] **Step 3: Run existing tests to confirm nothing broke**

```bash
pytest tests/test_process.py tests/test_pipeline.py tests/test_upload.py -v
```
Expected: all pass (the manual `/api/process` route calls `process_pending_files()` directly — it does not depend on the scheduler).

- [ ] **Step 4: Commit**

```bash
git add app/scheduler.py
git commit -m "feat: remove pipeline_job from scheduler — queue handles immediate processing"
```

---

## Task 7: Add SSE wiring to `app/templates/index.html`

**Files:**
- Modify: `app/templates/index.html`

The status panel currently polls every 10 s:
```html
<div
  id="status-panel"
  hx-get="/api/status/table"
  hx-trigger="load, every 10s"
  hx-swap="innerHTML"
  hx-indicator="#table-spinner"
>
```

We add a plain JavaScript `EventSource` that fires an HTMX reload when any SSE event arrives. This approach requires no additional script tags and works alongside the existing 10 s polling (which remains as a fallback).

- [ ] **Step 1: Add the EventSource snippet**

In `app/templates/index.html`, find the closing `</script>` tag at the very end of the file (after the `batchAction` function). **Before** `</script>`, add:

```javascript
    // SSE — trigger status table reload on each pipeline stage event
    (function () {
      var es = new EventSource('/api/status/stream');
      es.onmessage = function () {
        if (typeof htmx !== 'undefined') {
          htmx.trigger(document.getElementById('status-panel'), 'load');
        }
      };
    })();
```

- [ ] **Step 2: Manual smoke test (dev server)**

Start the dev server:
```bash
uvicorn main:app --reload
```
Open the browser, upload a file. The status table should update in real time as the file moves through pipeline stages (transcribe → translate → summarize → extract → done), without waiting for the 10 s poll.

If llama.cpp is not running, the file will fail at the translation stage — you should still see the badge change from `pending` → `processing` → `transcribed` → `failed` in real time.

- [ ] **Step 3: Commit**

```bash
git add app/templates/index.html
git commit -m "feat: add EventSource SSE wiring to trigger live status table refreshes"
```

---

## Task 8: Add FastAPI app service to `docker-compose.yml`

**Files:**
- Modify: `docker-compose.yml`
- Reference: `.env.example` (for environment variable names)

- [ ] **Step 1: Rewrite docker-compose.yml**

```yaml
services:
  app:
    build: .
    container_name: saraswati-app
    restart: unless-stopped
    ports:
      - "${PORT:-8000}:8000"
    volumes:
      - ./input:/app/input
      - ./cache:/app/cache
      - ./data:/app/data
    env_file:
      - .env
    depends_on:
      - qdrant
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]

  qdrant:
    image: qdrant/qdrant:latest
    container_name: saraswati-qdrant
    restart: unless-stopped
    ports:
      - "6333:6333"
    volumes:
      - qdrant_storage:/qdrant/storage

volumes:
  qdrant_storage:
```

- [ ] **Step 2: Create a minimal `Dockerfile` if one does not exist**

Check:
```bash
ls Dockerfile 2>/dev/null && echo "exists" || echo "missing"
```

If missing, create `Dockerfile`:
```dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["python", "main.py"]
```

- [ ] **Step 3: Add `WHISPER_DEVICE=cuda` to `.env.example`**

In `.env.example`, add the new variable in the Whisper section:
```
# Whisper device: auto (tries CUDA, falls back to CPU), cuda, or cpu
WHISPER_DEVICE=auto
```

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml .env.example
# Add Dockerfile only if it was created in step 2
git commit -m "feat: add FastAPI app service with NVIDIA GPU passthrough to docker-compose"
```

---

## Task 9: Write `tests/test_queue.py`

**Files:**
- Create: `tests/test_queue.py`

These tests use the real pipeline functions (no mocks). A file with a nonexistent path triggers a clean failure, which verifies the queue drain loop catches errors and continues.

- [ ] **Step 1: Write the test file**

```python
# tests/test_queue.py
import asyncio
import hashlib
import uuid

import pytest
from sqlmodel import Session

from app.models import FileRecord
from app.queue import drain_queue, enqueue, _queue


def _make_record(tmp_path) -> FileRecord:
    """Return a FileRecord with a nonexistent audio path (causes transcription to fail cleanly)."""
    return FileRecord(
        filename="fake.m4a",
        sha256=hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
        status="pending",
        local_path=str(tmp_path / "nonexistent.m4a"),
    )


async def test_enqueue_puts_item_on_queue(db_engine):
    """enqueue() is non-blocking and puts the file_id on the module-level queue."""
    # Drain any pre-existing items from prior test runs
    while not _queue.empty():
        _queue.get_nowait()
        _queue.task_done()

    file_id = uuid.uuid4()
    assert _queue.empty()
    enqueue(file_id)
    assert _queue.qsize() == 1
    item = _queue.get_nowait()
    _queue.task_done()
    assert item == file_id


async def test_drain_queue_processes_one_file(db_engine, db_session: Session, tmp_path):
    """drain_queue() picks up a file_id and runs the pipeline (which fails for missing file)."""
    while not _queue.empty():
        _queue.get_nowait()
        _queue.task_done()

    record = _make_record(tmp_path)
    db_session.add(record)
    db_session.commit()

    enqueue(record.id)

    # Run drain_queue until the queue is empty
    drain_task = asyncio.create_task(drain_queue())
    await _queue.join()  # blocks until task_done() is called for every item
    drain_task.cancel()
    try:
        await drain_task
    except asyncio.CancelledError:
        pass

    with Session(db_engine) as session:
        updated = session.get(FileRecord, record.id)
    assert updated.status == "failed"


async def test_drain_queue_continues_after_failure(db_engine, db_session: Session, tmp_path):
    """drain_queue() processes subsequent files even when one fails."""
    while not _queue.empty():
        _queue.get_nowait()
        _queue.task_done()

    record_a = _make_record(tmp_path)
    record_b = _make_record(tmp_path)
    db_session.add(record_a)
    db_session.add(record_b)
    db_session.commit()

    enqueue(record_a.id)
    enqueue(record_b.id)

    drain_task = asyncio.create_task(drain_queue())
    await _queue.join()
    drain_task.cancel()
    try:
        await drain_task
    except asyncio.CancelledError:
        pass

    with Session(db_engine) as session:
        a = session.get(FileRecord, record_a.id)
        b = session.get(FileRecord, record_b.id)
    assert a.status == "failed"
    assert b.status == "failed"
```

- [ ] **Step 2: Run the tests**

```bash
pytest tests/test_queue.py -v
```
Expected: all 3 pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_queue.py
git commit -m "test: add test_queue.py for asyncio queue drain behavior"
```

---

## Task 10: Write `tests/test_sse.py`

**Files:**
- Create: `tests/test_sse.py`

- [ ] **Step 1: Write the test file**

```python
# tests/test_sse.py
import asyncio
import json
from uuid import uuid4

import pytest

from app.sse import emit, _subscribers


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
async def test_sse_stream_endpoint_responds(client):
    """GET /api/status/stream returns 200 with text/event-stream content type."""
    async with client.stream("GET", "/api/status/stream") as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        # Don't read body — just verify the connection opened; close immediately


@pytest.mark.asyncio
async def test_sse_stream_delivers_emitted_event(client):
    """An event emitted after a client connects is received by that client."""
    _clear_subscribers()
    file_id = uuid4()
    received: list[dict] = []

    async def collect():
        async with client.stream("GET", "/api/status/stream") as response:
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    received.append(json.loads(line[6:]))
                    return  # got one event, done

    task = asyncio.create_task(collect())
    # Give the connection time to register its subscriber queue
    await asyncio.sleep(0.05)

    emit(file_id, {"stage": "summarize", "status": "done"})

    await asyncio.wait_for(task, timeout=3.0)

    assert len(received) == 1
    assert received[0]["file_id"] == str(file_id)
    assert received[0]["stage"] == "summarize"
    _clear_subscribers()
```

- [ ] **Step 2: Run the tests**

```bash
pytest tests/test_sse.py -v
```
Expected: all 5 pass.

- [ ] **Step 3: Run the full test suite**

```bash
pytest -v
```
Expected: all existing tests pass, new tests pass, no regressions.

- [ ] **Step 4: Commit**

```bash
git add tests/test_sse.py
git commit -m "test: add test_sse.py for SSE broadcaster and stream endpoint"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|---|---|
| Upload enqueues file_id immediately | Task 4 |
| asyncio.Queue drain coroutine | Task 1 |
| process_single_file runs all four stages with SSE events | Task 1 |
| SSE subscriber registry + emit() | Task 2 |
| GET /api/status/stream StreamingResponse | Task 3 |
| HTMX triggers status table refresh on SSE event | Task 7 |
| drain_queue wraps in try/except, queue never stalls | Task 1 (`drain_queue` catches all exceptions) |
| lifespan starts drain coroutine | Task 5 |
| Remove pipeline_job | Task 6 |
| WHISPER_DEVICE config | **Already done** — no task needed |
| Docker GPU passthrough | Task 8 |
| test_queue.py | Task 9 |
| test_sse.py | Task 10 |
| Existing tests unchanged | Verified in Task 6 step 3 |

**Placeholder scan:** None found. All code blocks are complete.

**Type consistency:** `enqueue(file_id: UUID)` in Task 1, `emit(file_id: UUID, event: dict)` in Task 2, both consumed consistently in `process_single_file`. `stream_response()` returns `StreamingResponse` and is imported identically in Task 3.
