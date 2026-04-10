# Design: asyncio Queue + SSE + GPU (Option B)

**Date:** 2026-04-10
**Status:** Approved

## Problem Statement

Three concrete problems with the current Saraswati backend:

1. **Files wait for cron** — `pipeline_job` fires on `SCHEDULE_CRON` (default 3 AM). Files uploaded during the day sit in `pending` status until the next scheduled run.
2. **Whisper runs on CPU** — transcription is too slow for batches of 20–30 files on a CPU-only machine.
3. **No real-time visibility** — no feedback about which stage a file is currently in; users must poll the status table manually.

## Chosen Approach: asyncio internal queue + SSE

All three fixes applied within the existing single-process FastAPI app. No external queue broker, no multi-process workers, no PostgreSQL migration required. This is safe for SQLite's single-writer model.

APScheduler is kept — only `cleanup_job` (daily 4 AM file deletion) is retained. `pipeline_job` is removed.

## Architecture

| Problem | Fix |
|---|---|
| Files wait for cron | `asyncio.Queue` — upload enqueues `file_id` immediately; background coroutine drains it |
| Whisper is slow (CPU) | `device="cuda"` in whisper_service + Docker GPU passthrough |
| No progress visibility | SSE endpoint streams per-file stage events; HTMX subscribes and updates the status table |

## Components

### `app/queue.py` (new, ~30 lines)

- Module-level `asyncio.Queue[UUID]`
- `enqueue(file_id)` — puts file_id onto the queue (non-blocking, called from upload route)
- `drain_queue()` — background coroutine: `while True: file_id = await queue.get(); await process_single_file(file_id)`
- `process_single_file(file_id)` — runs all four pipeline stages in sequence for one file, emitting SSE events between stages

Files are processed one at a time. This is intentional — safe for SQLite, matches existing horizontal batching intent.

### `app/sse.py` (new, ~40 lines)

- Module-level `dict[UUID, list[asyncio.Queue]]` — one small queue per active SSE subscriber
- `emit(file_id, event)` — puts event into all matching subscriber queues
- `GET /api/status/stream` — `StreamingResponse` (`text/event-stream`) that yields SSE lines from the subscriber queue; removes subscriber on disconnect

### Upload route (`app/routes/upload.py`)

After creating `FileRecord(status="pending")` and committing: call `queue.enqueue(file_id)`. ~3 lines added.

### `main.py` lifespan

On startup: `asyncio.create_task(drain_queue())`. Remove `pipeline_job` from APScheduler registration; keep `cleanup_job`.

### `app/services/whisper_service.py`

Change `device` argument to read from config (`WHISPER_DEVICE=cuda|cpu|auto`). Default `auto` tries CUDA, falls back to CPU with a warning log.

### `docker-compose.yml`

Add FastAPI app service:
- `deploy.resources.reservations.devices` for GPU passthrough (NVIDIA runtime)
- Volume mounts for `input/`, `cache/`, `db/`
- Pass environment from `.env`
- Keep Qdrant service unchanged

## Data Flow

### Upload path

```
POST /api/upload
  → save file, create FileRecord(status="pending"), commit
  → queue.enqueue(file_id)          ← new, immediate
  → return 201 to client
```

### Queue drain (background)

```
drain_queue() coroutine:
  file_id = await queue.get()
  → emit(file_id, {stage: "transcribe", status: "start"})
  → run_transcription(file_id)      ← existing, unchanged
  → emit(file_id, {stage: "transcribe", status: "done"})
  → run_translation(file_id)
  → emit(file_id, {stage: "translate", status: "done"})
  → run_summarization(file_id)
  → emit(file_id, {stage: "summarize", status: "done"})
  → run_extraction_and_finalize(file_id)
  → emit(file_id, {stage: "extract", status: "done"})
  → queue.task_done()
```

### SSE stream

```
GET /api/status/stream
  → StreamingResponse, text/event-stream
  → subscriber registered in sse.py dict
  → yields: "data: {file_id, stage, status}\n\n"
  → on disconnect: subscriber removed
```

### HTMX wiring

`index.html` adds `hx-ext="sse"` on a container element with `sse-connect="/api/status/stream"`. On each SSE event, HTMX triggers a refresh of the status table partial (`GET /api/status/table`).

### Restart recovery

On startup the queue is empty. Files that survived a restart in `pending/transcribed/translated/summarized` state are picked up by:
- `POST /api/process` (existing manual trigger) — calls `process_pending_files()` directly, bypassing the queue
- Or the next upload, which re-enqueues and the subsequent drain also picks up older resumable files via `process_pending_files()`

The simplest operational path: after a restart, hit "Process" once.

## Error Handling

- **drain_queue()**: wraps `process_single_file()` in `try/except`. A failed file logs the error, emits `{stage, status: "failed"}` via SSE, then the loop continues to the next file. The queue never stalls.
- **Individual stage functions**: already handle their own exceptions and set `db_record.status = "failed"`. No changes needed.
- **CUDA unavailable**: `whisper_service.py` with `WHISPER_DEVICE=auto` catches the CUDA init error and falls back to `"cpu"` with a warning log. Explicit `cuda` or `cpu` values skip the fallback.
- **SSE subscriber disconnect**: `sse.py` catches `asyncio.CancelledError` / generator close and removes the subscriber from the dict cleanly.

## Testing

- **Existing tests**: unchanged. They use `POST /api/process` → `process_pending_files()` directly, bypassing the queue. No test churn.
- **New `test_queue.py`**: enqueue a file_id, assert `drain_queue()` picks it up and calls the pipeline stages in order.
- **New `test_sse.py`**: connect to `/api/status/stream`, trigger a pipeline run, assert SSE events arrive in correct sequence.
- **GPU**: `WHISPER_DEVICE=cpu` in test environment (`.env.test`). All tests run CPU-only.

## Configuration Changes

| Variable | Default | Purpose |
|---|---|---|
| `WHISPER_DEVICE` | `auto` | `cuda`, `cpu`, or `auto` (tries CUDA, falls back to CPU) |

All existing variables unchanged.

## Files Changed

| File | Change |
|---|---|
| `app/queue.py` | New — asyncio queue + drain coroutine |
| `app/sse.py` | New — SSE subscriber registry + StreamingResponse endpoint |
| `app/routes/upload.py` | Add `queue.enqueue(file_id)` after commit |
| `app/routes/status.py` | Add `GET /api/status/stream` route (or wire in `app/sse.py`) |
| `main.py` | Add `create_task(drain_queue())` in lifespan; remove `pipeline_job` |
| `app/scheduler.py` | Remove `pipeline_job` registration |
| `app/services/whisper_service.py` | Read `WHISPER_DEVICE` from config |
| `app/config.py` | Add `whisper_device: str = "auto"` |
| `app/templates/index.html` | Add SSE extension + `hx-ext="sse"` on status container |
| `docker-compose.yml` | Add FastAPI service with GPU passthrough |
| `tests/test_queue.py` | New |
| `tests/test_sse.py` | New |
