# Queue and pipeline batching (upload vs manual process)

This document records **why** the async upload queue behaved differently from **POST /api/process**, what we changed, and how to tune behavior. **Maintainers:** skim this before editing `app/queue.py`, `app/services/pipeline.py`, or upload-driven processing.

---

## Summary

| Topic | Issue | Resolution |
|--------|--------|------------|
| Vertical vs horizontal pipeline | Upload path ran `process_single_file` (all stages per file before the next). Manual process ran `process_pending_files` (all transcriptions, then all translations, etc.). | `drain_queue` now calls `process_pending_files(emit_sse=True)` once per coalesced wake-up. |
| SSE during batch runs | Batch runner did not emit per-stage events. | `process_pending_files(emit_sse=True)` wraps each stage with the same SSE payloads as the old per-file helper. |
| LLM stages skipped entirely | `check_llm_server_ready()` could return a non-`None` probe result; the code **skipped whole translate / summarize / extract loops**, leaving files stuck at `transcribed` (or later) with only a log line. The old per-file path still called `run_*` and failed per file. | Probe failures are **warnings only**; the stage loops **always run**; per-file errors behave as before. |
| First file “fast-laned” on multi-upload | Sequential uploads enqueue one ID at a time. The first `process_pending_files()` often saw **only one** `pending` row and finished the full pipeline for that file before the next upload committed. Later files then appeared together and got true horizontal batching. | **Debounce** after the first dequeue: wait `QUEUE_COALESCE_DEBOUNCE_SECONDS` (default `0.2`), then `get_nowait()` the rest so one run usually sees every file from a quick multi-file upload. |

---

## Problem 1: Two different execution strategies

### Symptom

- **Manual “trigger pipeline”** (`POST /api/process`): All pending files were transcribed, then all eligible files translated, then summarized, then extracted (horizontal batches).
- **Per-upload queue** (`enqueue` after `POST /api/upload`): Each dequeued file ran transcribe → translate → summarize → extract **for that file** before the next file (`process_single_file` in `app/queue.py`).

### Root cause

`POST /api/process` called `process_pending_files()` in `app/services/pipeline.py`. The background drain called `process_single_file()`, which sequenced all four stage functions for one `file_id` per queue item.

### Fix

- `drain_queue` in `app/queue.py` invokes **`process_pending_files(emit_sse=True)`** instead of per-file vertical processing.
- **`emit_sse`**: When `True` (queue drain only), `process_pending_files` emits SSE `start` / `done` / `failed` / pipeline `complete` events compatible with the status stream. When `False` (manual `/api/process`), a no-op emitter avoids extra SSE traffic.

### Semantics note

`process_pending_files` operates on **all rows** in the DB that are in pipeline states (`pending`, `transcribed`, `translated`, `summarized`), not only IDs that were enqueued. That matches manual process and is intentional: the queue is a **wake-up / work-available** signal, not a closed work-set.

---

## Problem 2: Translation (and later stages) never ran after transcription

### Symptom

Files reached `transcribed` but did not move to `translated` / `summarized` / `done`, even when the LLM could have been invoked.

### Root cause

Before each LLM batch, `check_llm_server_ready(step)` probes `GET /v1/models` and configuration. If it returned **any** non-`None` string (empty server URL in `ModelConfig`, unreachable server, model name not listed in the response, etc.), the implementation **did not enter** the `for fid in ...` loops at all. No `run_translation` / `run_summarization` / `run_extraction_and_finalize` calls were made for that run.

The previous per-file drain path did **not** use this batch gate; it called the stage functions directly, so behavior diverged after unifying on `process_pending_files`.

### Fix

In `process_pending_files`, the probe result is logged as a **warning** (“running N file(s) anyway”). The translate, summarize, and extract loops **always execute** for the IDs returned from the DB queries; per-file failures are still recorded in the returned `errors` list and in SSE when `emit_sse` is enabled.

---

## Problem 3: Inconsistent batching when uploading several files in a row

### Symptom

Uploading three files: the **first** file often went through the full pipeline alone; the **second and third** were transcribed together, then translated together, etc. **POST /api/process** after all uploads still saw all files `pending` at once and looked “correct.”

### Root cause

The client uploads **sequentially** (one `POST /api/upload` after another). The drain loop wakes on the **first** enqueue. With only `get_nowait()` coalescing (no delay), only the first `file_id` was usually present in the queue before `process_pending_files` ran, so only **one** row was `pending` in the DB for that run. By the time the next files were inserted and enqueued, the first file had often already progressed through multiple stages or finished.

### Fix

After `await _queue.get()`, the drain waits **`queue_coalesce_debounce_seconds`** (settings / `QUEUE_COALESCE_DEBOUNCE_SECONDS`, default **0.2**), then drains the rest with `get_nowait()`. Uploads that complete during that window are included in the same batch notification set, so one `process_pending_files` call tends to see **all** new rows as `pending`, matching manual process.

**Trade-off:** A single upload pays the debounce latency before processing starts. Set `QUEUE_COALESCE_DEBOUNCE_SECONDS=0` to disable coalescing (restores fastest start for a single file, at the cost of uneven batching for sequential multi-uploads).

---

## Configuration

| Setting | Env alias | Default | Role |
|---------|-----------|---------|------|
| `queue_coalesce_debounce_seconds` | `QUEUE_COALESCE_DEBOUNCE_SECONDS` | `0.2` | Pause after first dequeue to collect more enqueue notifications. |
| `queue_drain_enabled` | `QUEUE_DRAIN_ENABLED` | `true` | Disable background drain in tests / special environments. |

See `.env.example` for env names.

---

## Tests

- `tests/test_queue.py`: `test_drain_queue_runs_horizontal_batches` (stubbed stages) asserts all transcribe steps occur before any translate step, etc.; autouse fixture forces **zero** debounce so tests stay fast and deterministic.
- Full `pytest` suite should pass after changes to queue or pipeline batching.

---

## Files most involved

- `app/queue.py` — `drain_queue`, debounce, coalescing, `task_done` per enqueue.
- `app/services/pipeline.py` — `process_pending_files(emit_sse=...)`, LLM loops, SSE hooks.
- `app/config.py` — `queue_coalesce_debounce_seconds`.
- `app/routes/process.py` — unchanged contract: `POST /api/process` calls `process_pending_files()` without SSE.
- `app/routes/upload.py` — still `enqueue(record.id)` after commit.

---

## Revision history (high level)

- **Queue aligned with horizontal `process_pending_files`**; removed per-file vertical helper from the drain path.
- **LLM batch skip removed**; probe-only warnings retained.
- **Upload debounce** added for multi-file sequential uploads.
