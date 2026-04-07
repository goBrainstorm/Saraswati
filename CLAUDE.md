# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Current implementation snapshot:** see [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) for what is built vs still open (keeps context small versus reading [ROADMAP.md](ROADMAP.md) in full).

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run development server (hot-reload)
uvicorn main:app --reload

# Run server via entry point
python main.py

# Run tests
pytest

# Run a single test file
pytest tests/test_upload.py -v
```

The virtual environment is at `.venv/`. Activate with `source .venv/bin/activate.fish` (fish) or `source .venv/bin/activate` (bash/zsh).

## Architecture

This is a **FastAPI personal knowledge base**. Phases 1–2 and most of the ingestion/processing stack are implemented; **Phase 3 RAG chat is not** (embeddings upsert to Qdrant on pipeline success, but there is no `/api/chat` or retrieval layer yet). See [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md).

**Entry point**: `main.py` — creates the FastAPI app, wires up lifespan (startup/shutdown), includes routers, seeds `ModelConfig` rows, starts the scheduler, and serves the HTMX frontend.

**`app/config.py`**: Single `Settings` singleton (pydantic-settings) loaded from `.env`. All runtime configuration lives here — see `.env.example` for all keys. Import as `from app.config import settings`.

**`app/models.py`**: SQLModel tables — `FileRecord` (`files`), `Entry` (`entries`), `ModelConfig` (`model_configs`). Same classes serve as ORM models and response schemas where exposed.

**`app/database.py`**: SQLite engine + session context manager. Use `get_session()` as a context manager for all DB access.

**`app/scheduler.py`**: APScheduler instance with two jobs:
- `pipeline_job` — fires per `SCHEDULE_CRON` (default `0 3 * * *`). Runs `process_pending_files()` and refreshes the short-term cache (`app/services/cache.py`).
- `cleanup_job` — fires daily at 04:00. Delegates to `app/services/cleanup.py`.

**`app/routes/`** — includes:
- `upload.py` — `POST /api/upload`: multipart audio, SHA-256 dedup, saves under `input/`, creates `FileRecord(status="pending")`.
- `status.py` — `GET /api/status`, `GET /api/status/table` (HTMX).
- `process.py` — `POST /api/process`: manual full pipeline run + cache refresh.
- `entries.py` — entries API, HTMX table, `/entries` page.
- `prompts.py`, `models_config.py`, `settings.py` — prompts, per-step LLM config, settings UI.

**`app/services/`** (non-exhaustive):
- `pipeline.py` — Whisper → LLM translate/summarize/extract → Qdrant upsert (non-fatal) → Nextcloud (non-fatal); granular `files.status` for resume.
- `whisper_service.py`, `llm.py`, `embedder.py`, `cache.py` — transcription, LLM calls, embeddings/Qdrant, rolling JSON cache.
- `cleanup.py` — deletes local files where `status=done AND nextcloud_path IS NOT NULL AND delete_after <= now`. DB row kept.
- `nextcloud.py` — WebDAV PUT. Returns `""` if `NEXTCLOUD_URL` is empty (no HTTP).

**`app/templates/`** — HTMX frontend: `index.html` at `/`, partials under `partials/`.

## Testing conventions

- Use `pytest` + `httpx.AsyncClient` with the real FastAPI app.
- Use a real SQLite database in a `tmp` directory — **no mocks** (see `tests/conftest.py`).
- Tests live in `tests/` named by area (`test_upload.py`, `test_pipeline.py`, etc.).

## Key design decisions

- **File deduplication** is SHA-256 content-based. Identical bytes → HTTP 409 with the existing record in the response body.
- **Filename sanitisation**: client-supplied filenames are stripped to `Path(name).name` (basename only) before writing to disk.
- **Nextcloud is optional**: leaving `NEXTCLOUD_URL` empty in `.env` causes all Nextcloud calls to be silent no-ops. The cleanup job will never delete a file whose `nextcloud_path` is `NULL`, so files accumulate safely without Nextcloud.
- **Phase 4 is blocked**: Native Gemma-4-E4B audio input via llama.cpp is blocked on llama.cpp issue #21325. Do not start Phase 4 work until that issue resolves.
