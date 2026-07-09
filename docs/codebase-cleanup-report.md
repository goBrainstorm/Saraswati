# Codebase cleanup report — `cleanup/codebase-cleanup`

Date: 2026-07-09
Branch: `cleanup/codebase-cleanup`
Tests: `pytest -q` → `106 passed in 0.77s`

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

1. **Template CSS duplication.** `index.html`, `entries.html`, and `settings.html` each contain roughly 400 lines of nearly identical CSS. Extract the shared stylesheet into a single static file and serve it via `StaticFiles`.

2. **Outdated docstring in `app/routes/process.py`.** It still describes the endpoint as a "Phase 1 stub" waiting for Phase 2 wiring, but Phase 2 is already fully implemented.

3. **Dead import in `tests/conftest.py`.** `import os` is unused.

4. **Queue "current file" is never reported.** `app/queue.py` defines `_current_file_id`, but `drain_queue()` only ever assigns it `None`. The queue panel therefore cannot show the file that is actually being processed.

5. **Pipeline result counts are misleading.** `process_pending_files()` counts `succeeded`/`failed` per stage, while `attempted` is the number of unique file IDs. A file that succeeds at stage 1 and fails at stage 2 is reported as `1 succeeded, 1 failed, 1 attempted`, which is confusing in the UI.

6. **Hard-coded LLM text limit.** `app/services/llm.py` truncates input at 32,000 characters. There are TODO comments asking for real token-count checks before translation and summarization.

7. **SSE error messages show UUIDs instead of filenames.** `process_pending_files()` uses `str(fid)` rather than the filename in error payloads.

8. **Empty scheduler.** `app/scheduler.py` is currently a no-op. It should either be given a real scheduled job (for example, a periodic cache refresh) or removed entirely to reduce startup complexity.

## Potential app-breaking bugs

### 1. Files stuck in `processing` status are never recovered

`run_transcription()` sets the status to `processing`:

```python
db_record.status = "processing"
session.add(db_record)
```

but `process_pending_files()` only queries `pending`, `transcribed`, `translated`, and `summarized`. It never queries `processing`. If the server crashes or is restarted while a file is in `processing`, that file stays stuck forever. The manual `/api/process/{file_id}` endpoint also does not handle `processing`, so it cannot force a retry.

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

`Entry.file_id` is not unique, so repeated runs or a race between the queue and manual processing can create multiple entries for the same file. Later stages use `select(Entry).where(Entry.file_id == file_id).first()`, which may then operate on the wrong row.

**Fix direction:** make `Entry.file_id` unique, or check for an existing `Entry` before inserting, or update in place.

### 3. `_chat()` assumes a valid OpenAI-shaped response

```python
return data["choices"][0]["message"]["content"].strip()
```

If the LLM server returns an error JSON, an empty `choices` list, or a non-standard response, this raises `KeyError` or `IndexError` and crashes the stage instead of logging a retryable failure.

**Fix direction:** validate the response shape and return a clear error string that the pipeline can catch and retry.

### 4. Whisper model loader is not thread-safe

`app/services/whisper_service.py` stores the loaded model in module globals:

```python
_model: Optional[object] = None
_current_model_name: Optional[str] = None
```

`_get_model()` mutates these globals from inside `run_in_executor`. If two uploads trigger transcription concurrently, both threads can race to load the model, possibly loading it twice or leaving `_current_model_name` inconsistent.

**Fix direction:** protect model loading with a `threading.Lock`.

### 5. Upload endpoint reads the entire file into memory

```python
raw = await file.read()
```

For large audio files this can exhaust memory. Streaming SHA-256 calculation and file writing would be safer.

**Fix direction:** stream the upload to a temporary file and compute the hash incrementally.

### 6. File is written before the database record is committed

In `upload_file()`, the bytes are written to disk before the `FileRecord` is committed. If the DB commit fails, the file remains orphaned in `input/`.

**Fix direction:** write the DB record first, then write the file, or roll back the file write on commit failure.

## Long-term view

- Phase 2 (audio ingestion and processing pipeline) is structurally complete but needs the bugs above fixed before it is reliable in production.
- Phase 3 RAG chat is still missing. Embeddings are upserted to Qdrant, but there is no `/api/chat`, no retrieval layer, and no chat UI.
- Phase 4 native audio input via Gemma-4-E4B is blocked on llama.cpp issue #21325, as documented in `CLAUDE.md`.
- Consider adding a linter (for example `ruff`) to catch unused imports and basic style issues automatically.
