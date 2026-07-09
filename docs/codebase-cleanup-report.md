# Codebase cleanup report — `cleanup/codebase-cleanup`

Date: 2026-07-09
Branch: `cleanup/codebase-cleanup`
Tests: `pytest -q` → `106 passed in 0.77s`

> **Second-agent review (2026-07-09):** A second agent independently re-checked every
> item below against the current source. Each finding is annotated with a
> `Verified` / `Verified (with nuance)` / `Corrected` note. New issues found during the
> re-check are listed under "Additional findings from second-agent review".

## Fixes applied (2026-07-09, follow-up pass)

All 106 pre-existing tests still pass and 6 new tests were added (112 total).

**Rework needed — done:**
- 1. Template CSS extracted to `app/static/css/app.css` and served via `StaticFiles` (`/static`); the three templates now `<link>` it. The shared file is the union of all three blocks (queue-window + settings rules are class-scoped, so unused rules on a page are harmless).
- 2. `process.py` `/api/process` docstring rewritten to describe the real behavior.
- 3. Dead `import os` removed from `tests/conftest.py`.
- 4. Queue now reports the file being processed: `queue.set_current_file()` is called per file in `process_pending_files()`.
- 5. Pipeline counts are now per-file (`succeeded + failed == attempted`) instead of per-stage.
- 6. LLM char limit is configurable via `LLM_MAX_INPUT_CHARS`; the pipeline token-count TODOs were resolved (documented as the char guard).
- 7. SSE/error payloads now include the filename instead of the raw UUID.
- 8. Scheduler runs an optional periodic cache refresh, gated by `CACHE_REFRESH_INTERVAL_MINUTES` (0 = disabled, unchanged default).

**Potential app-breaking bugs — done:**
- 1. `processing` rows are reset to `pending` on startup (`reset_stuck_processing()` in the lifespan); the manual `/api/process/{id}` endpoint also handles `processing`.
- 2. `run_transcription()` reuses an existing `Entry` for a file instead of inserting a duplicate.
- 3. `_chat()` validates the OpenAI-shaped response and raises a clear, retryable `RuntimeError`.
- 4. Whisper model load and GPU-fallback reset are guarded by a `threading.RLock`.
- 6. Upload commits the `FileRecord` before writing the file and rolls the record back if the write fails.

**Deferred (need schema migration or larger design work — not done this pass):**
- Bug 5: streaming upload (avoid reading the whole file into memory). Correctness is fine today; deferred because `audio_metadata` needs the bytes, so this is an optimization requiring more care.
- Additional findings 7 & 8: automatic retry of `failed` files with a bounded attempt counter/backoff. Needs a new `FileRecord`/`Entry` column, and the project has no migration framework (SQLModel `create_all` will not add columns to an existing DB).
- Additional finding 10: consolidating the two overlapping conftest fixture families. Test-only churn; deferred to avoid destabilizing the suite in the same pass as the behavioral fixes.

## What was done

- Created and switched to branch `cleanup/codebase-cleanup`.
- The branch already contained a commit that removed the unused Nextcloud archiving and retention-cleanup code:
  - `app/services/nextcloud.py`
  - `app/services/cleanup.py`
  - `tests/test_nextcloud.py`
  - `tests/test_cleanup.py`
  - Related config keys, model fields, scheduler jobs, and docs references.
- Removed tracked generated artifacts and added ignore rules for them:
  - `pytest-of-brain/`
  - `.superpowers/`
  - `.pytest_cache/` (also added to `.gitignore`).
- Updated `.gitignore` so the directories above will not be accidentally tracked again.

## Files that looked suspicious but were kept

| File | Reason kept |
|------|-------------|
| `app/services/audio_metadata.py` | Still imported and used by `app/routes/upload.py` for embedded recording timestamps. |
| `tests/test_batch_operations.py` | Tests real endpoints `/api/status/batch-delete` and `/api/status/batch-reset`. |
| `tests/test_entries_actions.py` | Tests real entry action endpoints under `/api/entries/{id}/...`. |
| `install_ffmpeg.sh` | Useful setup helper, not dead code. |
| `app/scheduler.py` | Currently has no jobs, but is still wired into the lifespan in `main.py`. |

## Rework needed

1. **Template CSS duplication.** `index.html`, `entries.html`, and `settings.html` each contain a large, nearly identical `<style>` block. Extract the shared stylesheet into a single static file and serve it via `StaticFiles`. _Corrected: the blocks are 393 / 319 / 332 lines respectively (not "~400 each"), but the duplication and the recommendation stand._

2. **Outdated docstring in `app/routes/process.py`.** It still describes the endpoint as a "Phase 1 stub" waiting for Phase 2 wiring, but Phase 2 is already fully implemented. _Verified: `POST /api/process` docstring at `app/routes/process.py:63-67`._

3. **Dead import in `tests/conftest.py`.** `import os` is unused. _Verified: `os` is imported at line 9 and never referenced._

4. **Queue "current file" is never reported.** `app/queue.py` defines `_current_file_id`, but `drain_queue()` only ever assigns it `None` (lines 83 and 92). The queue panel therefore cannot show the file that is actually being processed. _Verified._

5. **Pipeline result counts are misleading.** `process_pending_files()` counts `succeeded`/`failed` per stage, while `attempted` is the number of unique file IDs. A file that succeeds at stage 1 and fails at stage 2 is reported as `1 succeeded, 1 failed, 1 attempted`, which is confusing in the UI. _Verified: `succeeded`/`failed` are incremented once per stage per file, `attempted` uses `attempted_ids` (a set)._

6. **Hard-coded LLM text limit.** `app/services/llm.py` truncates input at 32,000 characters (`_MAX_CHARS`). The pipeline has TODO comments (`app/services/pipeline.py:108,154`) asking for real token-count checks (`> 4096`) before translation and summarization. _Verified._

7. **SSE error messages show UUIDs instead of filenames.** `process_pending_files()` uses `str(fid)` rather than the filename in error payloads (e.g. line 309). _Verified._

8. **Empty scheduler.** `app/scheduler.py` is currently a no-op. It should either be given a real scheduled job (for example, a periodic cache refresh) or removed entirely to reduce startup complexity. _Verified: `start_scheduler()` logs "no scheduled jobs" and registers none._

## Potential app-breaking bugs

### 1. Files stuck in `processing` status are never recovered

`run_transcription()` sets the status to `processing`:

```python
db_record.status = "processing"
session.add(db_record)
```

but `process_pending_files()` only queries `pending`, `transcribed`, `translated`, and `summarized`. It never queries `processing`. If the server crashes or is restarted while a file is in `processing`, that file stays stuck forever. The manual `/api/process/{file_id}` endpoint also does not handle `processing` (it only calls `run_transcription` when `status == "pending"`), so it cannot force a retry.

_Verified (with nuance):_ `run_transcription()` itself **already accepts** `processing` as a valid input status (`app/services/pipeline.py:30` guards on `("pending", "processing")`), so the recovery is only half-wired — the function can resume a stuck file, but nothing ever re-queries `processing` rows or calls it for them. Recovery today is only possible via `POST /api/status/batch-reset`, which forces the row back to `pending`.

**Fix direction:** include `processing` in the pending query, or reset `processing` rows to `pending` on startup, or remove the `processing` status and use `pending` + row-level locking.

### 2. `run_transcription()` can create duplicate `Entry` rows

`run_transcription()` always inserts a new `Entry` without checking whether one already exists:

```python
entry = Entry(
    file_id=file_id,
    language=language,
    transcription=transcription,
)
session.add(entry)
```

`Entry.file_id` is declared `index=True` but **not** `unique` (`app/models.py:30`), so repeated runs or a race between the queue and manual processing can create multiple entries for the same file. Later stages use `select(Entry).where(Entry.file_id == file_id).first()`, which may then operate on the wrong row.

_Verified (with nuance):_ the status guard at `run_transcription():30` returns early for any status other than `pending`/`processing`, so a normal sequential re-run does **not** duplicate — the realistic trigger is a concurrent queue-vs-manual race, or a `batch-reset` that runs while a stage is in flight. Note also that `batch-reset` deletes only the first entry (`select(...).first()` at `app/routes/status.py:217`), so any duplicates would leave orphaned `Entry` rows behind.

**Fix direction:** make `Entry.file_id` unique, or check for an existing `Entry` before inserting, or update in place.

### 3. `_chat()` assumes a valid OpenAI-shaped response

```python
return data["choices"][0]["message"]["content"].strip()
```

If the LLM server returns an error JSON, an empty `choices` list, or a non-standard response, this raises `KeyError` or `IndexError` and crashes the stage instead of logging a retryable failure. _Verified: `app/services/llm.py:82`._

**Fix direction:** validate the response shape and return a clear error string that the pipeline can catch and retry.

### 4. Whisper model loader is not thread-safe

`app/services/whisper_service.py` stores the loaded model in module globals:

```python
_model: Optional[object] = None
_current_model_name: Optional[str] = None
```

`_get_model()` mutates these globals from inside `run_in_executor`. If two uploads trigger transcription concurrently, both threads can race to load the model, possibly loading it twice or leaving `_current_model_name` inconsistent. The GPU-fallback path in `_transcribe_sync()` also mutates `_model`/`_current_model_name`/`_whisper_gpu_broken` without locking. _Verified: `app/services/whisper_service.py:35-38, 75-130, 183-208`._

**Fix direction:** protect model loading (and the GPU-fallback reset) with a `threading.Lock`.

### 5. Upload endpoint reads the entire file into memory

```python
raw = await file.read()
```

For large audio files this can exhaust memory. Streaming SHA-256 calculation and file writing would be safer. _Verified: `app/routes/upload.py:61`; the same `raw` buffer is also handed to `read_embedded_recording_datetime_from_bytes`._

**Fix direction:** stream the upload to a temporary file and compute the hash incrementally.

### 6. File is written before the database record is committed

In `upload_file()`, the bytes are written to disk before the `FileRecord` is committed. If the DB commit fails, the file remains orphaned in `input/`. _Verified: `dest_path.write_bytes(raw)` at `app/routes/upload.py:106` precedes `session.commit()` at line 121._

**Fix direction:** write the DB record first, then write the file, or roll back the file write on commit failure.

## Additional findings from second-agent review

These were not in the original list and were found while re-verifying the report.

### 7. Failed files are never retried automatically

Only `run_transcription()` sets `status="failed"` (`app/services/pipeline.py:76`). `process_pending_files()` selects only `pending`, `transcribed`, `translated`, and `summarized`, so a file that fails transcription is never re-attempted by the queue or by `POST /api/process` — the only recovery path is a manual `batch-reset`. LLM stages (translate/summarize/extract) behave differently: they return an error string but leave the status unchanged, so they *are* retried on the next batch.

**Fix direction:** decide on a consistent retry policy — either include `failed` in the retry query with a bounded attempt counter, or add explicit backoff/max-retry so permanently-failing LLM stages do not retry forever on every batch.

### 8. No retry cap / backoff on LLM stages

Because translate/summarize/extract leave the row at its previous status on failure, a permanently failing input (for example, `extract()` raising `JSONDecodeError` on malformed LLM output at `app/services/llm.py:118`) will be retried on **every** subsequent batch run indefinitely, with no attempt counter or backoff.

**Fix direction:** add an attempt/next-retry column to `FileRecord` or `Entry`, and stop after N attempts.

### 9. Minor: in-function import in `upload.py`

`import uuid as _uuid` sits inside `upload_file()` (`app/routes/upload.py:96`) instead of at module top. Harmless, but inconsistent with the rest of the file; move it up when touching this module.

### 10. Minor: overlapping test fixtures in `conftest.py`

`tests/conftest.py` defines two parallel DB-fixture families — `setup_test_env`/`session`/`client` and `db_engine`/`db_session`/`app_client`. This duplication is confusing; consolidating on one pattern (in addition to removing the dead `import os`) would simplify the test setup.

## Long-term view

- Phase 2 (audio ingestion and processing pipeline) is structurally complete but needs the bugs above fixed before it is reliable in production.
- Phase 3 RAG chat is still missing. Embeddings are upserted to Qdrant, but there is no `/api/chat`, no retrieval layer, and no chat UI.
- Phase 4 native audio input via Gemma-4-E4B is blocked on llama.cpp issue #21325, as documented in `CLAUDE.md`.
- Consider adding a linter (for example `ruff`) to catch unused imports and basic style issues automatically.
