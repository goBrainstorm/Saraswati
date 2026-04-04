# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run development server (hot-reload)
uvicorn main:app --reload

# Run server via entry point
python main.py

# Run tests (Phase 1 tests not yet written; target command when they exist)
pytest

# Run a single test file
pytest tests/test_upload.py -v
```

The virtual environment is at `.venv/`. Activate with `source .venv/bin/activate.fish` (fish) or `source .venv/bin/activate` (bash/zsh).

## Architecture

This is a **FastAPI personal knowledge base** — currently Phase 1 of 4. The app ingests audio files, processes them through an AI pipeline, stores results in SQLite + Qdrant, and exposes a RAG chat interface.

**Entry point**: `main.py` — creates the FastAPI app, wires up lifespan (startup/shutdown), includes routers, and serves the HTMX frontend.

**`app/config.py`**: Single `Settings` singleton (pydantic-settings) loaded from `.env`. All runtime configuration lives here — see `.env.example` for all keys. Import as `from app.config import settings`.

**`app/models.py`**: Two SQLModel tables — `FileRecord` (`files`) and `Entry` (`entries`). The same classes serve as both ORM models and Pydantic response schemas.

**`app/database.py`**: SQLite engine + session context manager. Use `get_session()` as a context manager for all DB access.

**`app/scheduler.py`**: APScheduler instance with two jobs:
- `pipeline_job` — fires per `SCHEDULE_CRON` (default `0 3 * * *`). Currently a no-op stub; Phase 2 will wire Whisper + LLM here.
- `cleanup_job` — fires daily at 04:00. Delegates to `app/services/cleanup.py`.

**`app/routes/`** — three routers:
- `upload.py` — `POST /api/upload`: receives multipart audio, SHA-256 deduplicates, saves to `input/{uuid}_{safe_name}`, creates `FileRecord(status="pending")`.
- `status.py` — `GET /api/status`: file registry with pagination; `GET /api/status/table` returns HTMX HTML partial.
- `process.py` — `POST /api/process`: manual pipeline trigger.

**`app/services/`**:
- `cleanup.py` — deletes local files where `status=done AND nextcloud_path IS NOT NULL AND delete_after <= now`. DB record is preserved; only the local copy is removed.
- `nextcloud.py` — WebDAV PUT to Nextcloud. Returns `""` immediately and logs a warning if `NEXTCLOUD_URL` is empty (no HTTP call made).

**`app/templates/`** — HTMX-driven HTML frontend. `index.html` is served at `/`; `partials/status_table.html` is the HTMX swap target for the file list.

## Testing conventions

Per ROADMAP Phase 1 test plan (tests not yet written):
- Use `pytest` + `httpx.AsyncClient` with the real FastAPI app.
- Use a real SQLite database in a `tmp` directory — **no mocks**.
- Test files go in `tests/` named after the route/service they cover (`test_upload.py`, `test_cleanup.py`, etc.).

## Key design decisions

- **File deduplication** is SHA-256 content-based. Identical bytes → HTTP 409 with the existing record in the response body.
- **Filename sanitisation**: client-supplied filenames are stripped to `Path(name).name` (basename only) before writing to disk.
- **Nextcloud is optional**: leaving `NEXTCLOUD_URL` empty in `.env` causes all Nextcloud calls to be silent no-ops. The cleanup job will never delete a file whose `nextcloud_path` is `NULL`, so files accumulate safely without Nextcloud.
- **Phase 4 is blocked**: Native Gemma-4-E4B audio input via llama.cpp is blocked on llama.cpp issue #21325. Do not start Phase 4 work until that issue resolves.
