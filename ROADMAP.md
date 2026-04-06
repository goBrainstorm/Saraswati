# ROADMAP — Personal Knowledge Base & Conversational AI Agent

## Project Vision

A self-hosted, automated personal knowledge base. Voice messages and audio files are the primary data source, texting with the chatbot will later on also store information. The system ingests audio, converts it to structured knowledge, stores that knowledge permanently in a queryable database, and exposes a conversational AI interface that can reason over the user's entire personal history.

The system runs on a dedicated home server, is accessible remotely over Tailscale, and is designed to become the backbone of a chatbot that knows everything about the user — their thoughts, tasks, habits, and history, derived from their voice and chats.

---

## Core Technical Stack

| Component | Technology |
|---|---|
| Backend API | Python — FastAPI |
| LLM Inference | llama.cpp (`llama-server`, OpenAI-compatible API) |
| LLM Model | Gemma-4-E4B (GGUF, via llama.cpp) |
| Audio Transcription (Phase 1–3) | faster-whisper |
| Audio Transcription (Phase 4) | Gemma-4-E4B native audio (via llama.cpp, when supported) |
| Vector Database | Qdrant (self-hosted via Docker) |
| Relational Database | SQLite (metadata, job state, file registry) |
| Short-term Cache | JSON or XML flat file (rolling 7-day window) |
| Task Scheduling | APScheduler (embedded in FastAPI app) |
| File Archiving | Nextcloud (WebDAV upload) |
| Frontend | Web app — React or minimal HTML/JS/HTMX |
| Remote Access | Tailscale (no port exposure) |
| Chat Interface | Open WebUI (connected to llama-server + backend RAG endpoint) |

---

## Architecture Overview

```
[ Audio Files ]
      │
      ▼
[ Web App Upload  OR  Local `input/` Directory ]
      │
      ▼
[ Processing Pipeline — triggered by schedule or manual button ]
      │
      ├─ 1. Transcription     (faster-whisper → text)
      ├─ 2. Translation       (Gemma-4-E4B via llama.cpp → English)
      ├─ 3. Summarization     (Gemma-4-E4B via llama.cpp → summary)
      ├─ 4. Extraction        (Gemma-4-E4B via llama.cpp → structured JSON: entities, facts, tasks)
      ├─ 5. Embedding         (text vectorized → Qdrant)
      ├─ 6. Cache Update      (short-term JSON/XML for last 7 days)
      └─ 7. Nextcloud Upload  (raw audio archived → local file deleted after N days)

[ Qdrant Vector DB ] ◄── RAG retrieval at chat time
[ SQLite DB ]        ◄── metadata, file registry, job state

[ FastAPI Backend ]
      │
      ├─ /api/upload          — receive audio files from web app
      ├─ /api/process         — trigger manual pipeline run
      ├─ /api/status          — job status and file registry
      ├─ /api/chat            — RAG-augmented chat endpoint (OpenAI-compatible)
      └─ /api/entries         — browse processed entries

[ Open WebUI ] ──► llama-server (llama.cpp)
                         │
                         └── /api/chat (RAG context injected by backend)
```

---

## Data Model

### SQLite — `files` table
- `id` — UUID
- `filename` — original filename
- `sha256` — content hash (deduplication)
- `status` — `pending | processing | done | failed`
- `uploaded_at` — timestamp
- `processed_at` — timestamp
- `local_path` — path on server
- `nextcloud_path` — archive path
- `delete_after` — date to delete local file

### SQLite — `entries` table
- `id` — UUID
- `file_id` — FK to files
- `created_at` — timestamp derived from filename or processing time
- `language` — detected language
- `transcription` — full transcript text
- `translation` — English translation (if applicable)
- `summary` — distilled summary
- `extracted_json` — structured extraction (entities, facts, tasks, tags)
- `qdrant_id` — reference to vector DB point

### Qdrant — collection `knowledge`
- Each point represents one processed entry
- Payload: `entry_id`, `created_at`, `summary`, `tags`, `filename`
- Vector: embedding of `transcription + summary + extracted facts`

### Short-term Cache (JSON/XML)
- Contains full entry data for files processed in the last 7 days
- Regenerated on every pipeline run
- Intended for direct LLM context injection without vector search overhead

---

## Implementation Phases

### Phase 1 — Foundation & Infrastructure ✅

**Goal**: A running server that accepts file uploads, stores them, and has working Nextcloud archiving and cleanup.

- [x] FastAPI application scaffold with SQLite database (SQLModel)
- [x] File upload endpoint (`/api/upload`) with SHA-256 deduplication
- [x] File registry management: track upload time, local path, deletion deadline
- [x] Scheduled job runner (APScheduler) wired into FastAPI — configurable cron schedule (default: daily at 03:00)
- [x] Nextcloud integration: WebDAV upload stub (skips gracefully if unconfigured)
- [x] Local file deletion job: removes files older than N days (configurable)
- [ ] Tailscale access: server binds to Tailscale interface address (configure on remote deploy)
- [x] Minimal web frontend: file upload form, processing status list, manual trigger button (HTMX)

**Deliverables**: Files can be uploaded, stored, tracked and archived to Nextcloud.

#### Phase 1 — Tests (pytest + httpx AsyncClient, real SQLite in tmp dir, no mocks)

- [x] `test_upload.py`
  - [x] Valid upload → 200, `FileRecord` with `status=pending`
  - [x] Same bytes uploaded again → 409 with existing record in detail
  - [x] Filename with path separators (`../../evil.mp3`) → sanitised to basename only
  - [x] Upload with no filename → falls back to `"upload"`, no crash
- [x] `test_status.py`
  - [x] Empty DB → `GET /api/status` returns `[]`
  - [x] After upload, record appears in response
  - [x] `limit` / `offset` pagination works correctly
  - [x] `GET /api/status/table` returns HTML fragment containing the filename
- [x] `test_process.py`
  - [x] `POST /api/process` → 200, `{"status": "complete"}`
- [x] `test_cleanup.py`
  - [x] Ignores records with `status=pending`
  - [x] Ignores `done` records where `nextcloud_path` is `None`
  - [x] Ignores `done + backed_up` records where `delete_after` is in the future
  - [x] Deletes local file when all three conditions met; DB record preserved
  - [x] Logs warning (no crash) when local file is already absent
- [x] `test_nextcloud.py`
  - [x] `upload_file()` returns `""` immediately when `NEXTCLOUD_URL` is empty (no HTTP call made)
  - [ ] (Integration, skip in CI): actual WebDAV PUT succeeds against a real Nextcloud

---

### Phase 2 — Transcription & LLM Processing Pipeline

**Goal**: Audio files are transcribed by Whisper and then processed by Gemma-4-E4B for translation, summarization, and extraction.

- [ ] faster-whisper integration: audio → text, language detection, per-file model selection
- [ ] Audio preprocessing: ffmpeg-based audio normalization before transcription
- [ ] Denoising: skip for files above configurable size threshold
- [ ] llama.cpp server integration: FastAPI backend calls `llama-server` OpenAI-compatible `/chat/completions`
- [ ] Prompt chains for (prompt editing on Web app):
  - [ ] **Translation**: transcript → English (skip if already English)
  - [ ] **Summarization**: translated text → concise summary with key points
  - [ ] **Extraction**: structured JSON extraction of entities (people, places), personal facts, action items, topics, tags
- [ ] SQLite `entries` table populated with all outputs
- [ ] Short-term cache writer: after each pipeline run, serialize last 7 days of entries to `cache/recent.json`
- [ ] Processing state machine: `pending → processing → done | failed`; failed entries logged and retryable
- [ ] `/api/status` endpoint exposes pipeline state and per-file results

**Deliverables**: Audio in → structured knowledge out, stored in SQLite and cache file.

---

### Phase 3 — Vector Database & RAG Pipeline

**Goal**: All processed knowledge is semantically searchable; the chat endpoint can retrieve relevant context.

- [ ] Qdrant deployment: Docker container on same server
- [ ] Embedding model: sentence-transformers (e.g., `all-MiniLM-L6-v2`) or Gemma-4-E4B embeddings if exposed by llama.cpp
- [ ] Embedding pipeline: on entry completion, vectorize `transcription + summary + extracted_facts`, upsert into Qdrant
- [ ] Backfill job: embed all existing entries on first run
- [ ] `/api/chat` RAG endpoint:
  - [ ] Embed the user query
  - [ ] Query Qdrant for top-K relevant entries
  - [ ] Build system prompt with retrieved context
  - [ ] Forward augmented prompt to `llama-server`
  - [ ] Return response with source citations (entry IDs and dates)
- [ ] Short-term cache injection: entries from the last 7 days always prepended to context (bypassing vector search for recent memory)
- [ ] Web app chat interface: basic conversation view wired to `/api/chat`
- [ ] Open WebUI connection: configure `llama-server` as the OpenAI-compatible backend; RAG context injected via system prompt or custom pipeline

**Deliverables**: Chat interface that can answer questions using the full personal knowledge history.

---

### Phase 4 — Native Audio Migration & Full Integration

**Goal**: Replace faster-whisper with Gemma-4-E4B native audio processing once llama.cpp audio evaluation support for Gemma 4 is stable.

**Prerequisite**: llama.cpp GitHub issue #21325 (missing Gemma 4 audio evaluation) must be resolved. **BLOCKED — do not start.**

- [ ] Refactor transcription step: replace faster-whisper call with direct audio submission to `llama-server` multimodal endpoint
- [ ] Validate output quality against faster-whisper baseline on a test set of historical files
- [ ] Remove faster-whisper and audio-denoiser dependencies once native path is validated
- [ ] Combined prompt: a single Gemma-4-E4B call handles transcription + translation + summarization + extraction in one pass
- [ ] Update extraction schema to take advantage of any improvements in Gemma 4's structured output capabilities
- [ ] Open WebUI: expose backend as fully OpenAI-compatible; test direct integration without custom `/api/chat` wrapper if RAG is handled inside Open WebUI

**Deliverables**: Single-model pipeline end-to-end; Whisper dependency eliminated.

---

## File & Data Retention Policy

- Raw audio: kept locally for **N days** (configurable, default 7), then deleted after Nextcloud upload is confirmed
- SQLite entries: kept permanently
- Qdrant vectors: kept permanently
- Short-term cache (`recent.json`): rolling 7-day window, regenerated on each pipeline run
- Nextcloud: permanent archive of all raw audio

---

## Configuration

All runtime configuration lives in a single `config.json` or `.env` file:

```
LLAMA_SERVER_URL        — base URL of llama-server instance
LLAMA_MODEL             — model name for generation
WHISPER_MODEL           — faster-whisper model name (e.g. large-v3)
QDRANT_URL              — Qdrant server URL
QDRANT_COLLECTION       — collection name
NEXTCLOUD_URL           — WebDAV base URL
NEXTCLOUD_USER          — credentials
NEXTCLOUD_PASS          — credentials
NEXTCLOUD_REMOTE_DIR    — remote path for audio archive
LOCAL_RETENTION_DAYS    — days before local audio deletion (default: 7)
SCHEDULE_CRON           — APScheduler cron expression (default: "0 3 * * *")
TAILSCALE_HOST          — bind address (Tailscale IP)
CACHE_DIR               — path for short-term cache files
DB_PATH                 — SQLite file path
```

---

## Known Constraints & Open Questions

1. **Gemma-4-E4B audio support in llama.cpp**: As of April 2026, native audio evaluation for Gemma 4 in llama.cpp is not functional (issue #21325). Phase 4 is blocked until this is resolved. faster-whisper is the transcription method for all earlier phases.

2. **Embedding model selection**: The embedding model for Qdrant must be decided. Options: a separate sentence-transformers model (lightweight, fast), or Gemma-4-E4B itself if llama.cpp exposes an embeddings endpoint. Using the same model for generation and embedding simplifies the stack but adds latency.

3. **Hardware requirements**: Running llama.cpp with Gemma-4-E4B GGUF, Qdrant, FastAPI, and faster-whisper on the same machine requires sufficient RAM and ideally a GPU. Minimum viable: 16 GB RAM, CPU-only inference (slower). Recommended: NVIDIA GPU with 8+ GB VRAM for llama.cpp acceleration.

4. **Open WebUI RAG vs custom RAG**: Open WebUI has built-in RAG. The decision of whether to use Open WebUI's internal RAG (pointing it directly at Qdrant) or route all chat through the custom `/api/chat` endpoint affects architecture complexity. Both options are viable.

5. **Nextcloud auth**: WebDAV with username/password is the baseline. App passwords should be used rather than the main account credentials.
