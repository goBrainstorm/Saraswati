# Implementation status (agent brief)

**Purpose:** Dense snapshot of what the repo does today and what is still open. For product vision, phased goals, and architecture diagrams, read [ROADMAP.md](ROADMAP.md) instead.

## Stack snapshot

- **Backend:** FastAPI (`main.py`), SQLite + SQLModel
- **Frontend:** HTMX templates under `app/templates/`
- **Ingestion:** Multipart upload, local `input/` storage, SHA-256 dedup
- **Pipeline:** faster-whisper (ffmpeg normalization, optional denoise by size), llama-server OpenAI-compatible `/v1/chat/completions` for translate / summarize / extract
- **Vector store:** Qdrant + sentence-transformers (`all-MiniLM-L6-v2`) upsert on successful pipeline completion
- **Optional:** Nextcloud WebDAV archive; APScheduler for scheduled pipeline + daily cleanup

## Implemented today

### HTTP API and pages

- `POST /api/upload` — audio upload, dedup, `FileRecord(status="pending")`
- `GET /api/status`, `GET /api/status/table` — registry + HTMX fragment
- `POST /api/process` — run pipeline on pending/resumable files, refresh short-term cache
- `GET /api/entries`, `GET /api/entries/table`, `GET /entries` — list/browse entries + HTMX; delete/retry actions (see `app/routes/entries.py`)
- `app/routes/prompts.py` — editable LLM prompts (stored service-side)
- `app/routes/models_config.py` — per-step model name + server URL (transcribe/translate/summarize/extract)
- `app/routes/settings.py` — settings UI
- `/` — main upload + status UI (`app/templates/index.html`)

### Data model (`app/models.py`)

- `**files` (`FileRecord`):** `status` includes `pending`, `processing`, `transcribed`, `translated`, `summarized`, `done`, `failed` (granular states used for resume)
- `**entries` (`Entry`):** transcription, translation, summary, `extracted_json`, optional `qdrant_id`
- `**model_configs` (`ModelConfig`):** per-pipeline-step server URL and model name (seeded at startup)

### Pipeline (`app/services/pipeline.py`)

- Stages: transcribe → translate → summarize → extract → Qdrant upsert (non-fatal) → mark `done` → Nextcloud upload (non-fatal)
- **Resume:** `process_pending_files()` selects `status IN ('pending','transcribed','translated','summarized')`. Partial LLM failures leave prior fields persisted and retry on next run (no typed `LLMUnavailableError`; generic exceptions on translate/summarize/extract).
- **Whisper failure** on a fresh file sets `failed` (see pipeline error handling).

### Other services

- `**app/services/cache.py`** — writes rolling ~7-day `cache/recent.json` after pipeline runs (scheduled + manual)
- `**app/services/embedder.py**` — embed combined entry text, create collection if missing, upsert to Qdrant
- `**app/services/cleanup.py**` — remove local files when `done`, `nextcloud_path` set, and `delete_after` passed
- `**app/services/nextcloud.py**` — WebDAV; no-op when `NEXTCLOUD_URL` empty

### Scheduler (`app/scheduler.py`)

- `pipeline_job` — runs `process_pending_files()` + `write_recent_cache()` on `SCHEDULE_CRON`
- `cleanup_job` — daily 04:00 cleanup

### Tests

- `**tests/**` — pytest + httpx against real app and tmp SQLite (upload, status, process, cleanup, nextcloud, pipeline, whisper, llm, cache, entries, prompts, model_config, batch operations, etc.)

## Not implemented yet (see ROADMAP for detail)

- **RAG chat:** no `/api/chat`, no query embedding, no Qdrant search/top-K, no llama-server forwarding with citations
- **Backfill:** no job to embed historical entries missing vectors
- **Chat UI / Open WebUI** integration as described in ROADMAP Phase 3
- **Short-term cache at chat time:** cache file exists; not wired into a chat context path
- **Phase 4:** native Gemma audio via llama.cpp — **blocked** on llama.cpp issue #21325 (per ROADMAP)

## ROADMAP backlog (not done; specs in ROADMAP)

- Page reload / UI state persistence bug
- Dynamic context size for LLM prompts
- Batch-first (all transcribe, then all translate, …) ordering — **note:** current design is per-file incremental resume instead; changing order is a separate product decision
- Per-file pipeline step visibility (`pipeline_steps` / API) and related UI
- Stricter LLM unavailability typing and explicit `transcribed`-only recovery semantics (partially overlapped by current retry behavior)

## Key paths


| Area                       | Path                                                          |
| -------------------------- | ------------------------------------------------------------- |
| App entry, routers         | `main.py`                                                     |
| Settings / env             | `app/config.py`, `.env.example`                               |
| ORM models                 | `app/models.py`                                               |
| Pipeline orchestration     | `app/services/pipeline.py`                                    |
| Whisper                    | `app/services/whisper_service.py`                             |
| LLM client                 | `app/services/llm.py`                                         |
| Embeddings + Qdrant upsert | `app/services/embedder.py`                                    |
| Prompts                    | `app/services/prompts.py`, `app/routes/prompts.py`            |
| Model config               | `app/services/model_config.py`, `app/routes/models_config.py` |


## Configuration (environment variables)

Loaded from `.env` via `app/config.py` (`Settings`):


| Variable                                                                    | Role                                                       |
| --------------------------------------------------------------------------- | ---------------------------------------------------------- |
| `HOST`, `PORT`                                                              | Bind address                                               |
| `DB_PATH`, `CACHE_DIR`, `INPUT_DIR`                                         | Paths                                                      |
| `LOCAL_RETENTION_DAYS`                                                      | Days until local file eligible for cleanup after Nextcloud |
| `SCHEDULE_CRON`                                                             | Pipeline schedule (five-field cron)                        |
| `NEXTCLOUD_URL`, `NEXTCLOUD_USER`, `NEXTCLOUD_PASS`, `NEXTCLOUD_REMOTE_DIR` | WebDAV archive (optional)                                  |
| `LLAMA_SERVER_URL`, `LLAMA_MODEL`                                           | Default LLM server (per-step overrides in DB)              |
| `WHISPER_MODEL`, `WHISPER_BATCH_SIZE`, `DENOISE_MAX_MB`                     | Transcription                                              |
| `QDRANT_URL`, `QDRANT_COLLECTION`                                           | Vector DB                                                  |
| `TAILSCALE_HOST`                                                            | Documented for remote bind; same pattern as `HOST`         |
