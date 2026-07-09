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
| Task Scheduling | APScheduler (embedded in FastAPI app; currently unused) |
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
      └─ 6. Cache Update      (short-term JSON/XML for last 7 days)

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

**Goal**: A running server that accepts file uploads, stores them, and triggers processing via a background queue.

- [x] FastAPI application scaffold with SQLite database (SQLModel)
- [x] File upload endpoint (`/api/upload`) with SHA-256 deduplication
- [x] File registry management: track upload time and local path
- [x] APScheduler wired into FastAPI lifespan (currently no scheduled jobs; processing is queue-driven)
- [x] Tailscale access: server binds to Tailscale interface address (configure on remote deploy)
- [x] Minimal web frontend: file upload form, processing status list, manual trigger button (HTMX)

**Deliverables**: Files can be uploaded, stored, tracked, and queued for processing.

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

---

### Phase 2 — Transcription & LLM Processing Pipeline ✅

**Goal**: Audio files are transcribed by Whisper and then processed by Gemma-4-E4B for translation, summarization, and extraction.

- [x] faster-whisper integration: audio → text, language detection, per-file model selection
- [x] Audio preprocessing: ffmpeg-based audio normalization before transcription
- [x] Denoising: skip for files above configurable size threshold
- [x] llama.cpp server integration: FastAPI backend calls `llama-server` OpenAI-compatible `/chat/completions`
- [x] Prompt chains for (prompt editing on Web app):
  - [x] **Translation**: transcript → English (skip if already English)
  - [x] **Summarization**: translated text → concise summary with key points
  - [x] **Extraction**: structured JSON extraction of entities (people, places), personal facts, action items, topics, tags
- [x] SQLite `entries` table populated with all outputs
- [x] Short-term cache writer: after each pipeline run, serialize last 7 days of entries to `cache/recent.json`
- [x] Processing state machine: `pending → processing → done | failed`; failed entries logged and retryable
- [x] `/api/status` endpoint exposes pipeline state and per-file results

**Deliverables**: Audio in → structured knowledge out, stored in SQLite and cache file.

---

### Phase 3 — Vector Database & RAG Pipeline

**Goal**: All processed knowledge is semantically searchable; the chat endpoint can retrieve relevant context.

- [x] Qdrant deployment: Docker container on same server
- [x] Embedding model: sentence-transformers (e.g., `all-MiniLM-L6-v2`) or Gemma-4-E4B embeddings if exposed by llama.cpp
- [x] Embedding pipeline: on entry completion, vectorize `transcription + summary + extracted_facts`, upsert into Qdrant
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

- Raw audio: kept locally indefinitely (no automatic deletion)
- SQLite entries: kept permanently
- Qdrant vectors: kept permanently
- Short-term cache (`recent.json`): rolling 7-day window, regenerated on each pipeline run

---

## Configuration

All runtime configuration lives in a single `config.json` or `.env` file:

```
LLAMA_SERVER_URL        — base URL of llama-server instance
LLAMA_MODEL             — model name for generation
WHISPER_MODEL           — faster-whisper model name (e.g. large-v3)
QDRANT_URL              — Qdrant server URL
QDRANT_COLLECTION       — collection name
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

---

## Backlog — Pending Feature Specs

### Fix page reload bug

**Reported 2026-04-07.**

Page reload is buggy — the whole page resets itself and everything that is marked (e.g., checkboxes, selections) gets undone. Need to investigate and fix state persistence on page reload.

---

### Dynamic context size

**Reported 2026-04-07.**

Implement dynamic context size management — context window should scale larger if needed to accommodate the full content without truncation.

---

### Batch-first pipeline ordering + per-file step visibility

**Requested 2026-04-06. Do not implement until explicitly tasked.**

#### Pipeline ordering change

Currently `process_pending_files()` in `app/services/pipeline.py` runs the full pipeline for each file sequentially (transcribe → translate → summarize → extract per file). Change this to a **batch-first, step-first** execution order:

1. **Transcribe all pending files first** — run `whisper_service.transcribe()` on every pending file before any LLM step begins.
2. **Translate all files** — once all transcriptions are complete, run `llm.translate()` on every file that needs it.
3. **Summarize all files** — then `llm.summarize()` on every file.
4. **Extract all files** — then `llm.extract()` on every file.
5. Write all `Entry` records and mark files `done` at the end.

This allows Whisper (CPU-bound) to complete its full batch before the LLM server (separate process) takes over, avoiding resource contention and making progress more visible.

State machine change: the `files.status` column will need intermediate states beyond `pending → processing → done | failed`. Proposed additional states: `transcribed`, `translated` (optional — evaluate whether DB granularity is worth the added complexity vs. storing step progress in a separate `pipeline_steps` table).

#### Per-file step visibility in the UI

Add a **pipeline step log** visible in the Entries section of the frontend:

- In the "Processed Entries" table, each row should have an expandable detail panel (or a link to a modal/separate view).
- The detail panel shows a **step timeline** for that file: each pipeline stage (Transcribe, Translate, Summarize, Extract) with its status (pending / running / done / failed) and timestamp.
- This requires a new `pipeline_steps` table in SQLite (or a JSON column on `entries`) to record per-step status and timestamps.
- New API endpoint: `GET /api/entries/{entry_id}/steps` returns the step log for a single entry.
- The frontend should poll or use HTMX to refresh step status while a file is in-flight.

**Suggested `pipeline_steps` schema:**
```sql
CREATE TABLE pipeline_steps (
    id       TEXT PRIMARY KEY,   -- UUID
    file_id  TEXT NOT NULL,      -- FK → files.id
    step     TEXT NOT NULL,      -- 'transcribe' | 'translate' | 'summarize' | 'extract'
    status   TEXT NOT NULL,      -- 'pending' | 'running' | 'done' | 'failed'
    started_at  TEXT,
    finished_at TEXT,
    error    TEXT                -- error message if failed
);
```

---

### Checkpoint-based pipeline recovery (LLM unavailability)

**Requested 2026-04-06. Do not implement until explicitly tasked.**

#### Problem

The current pipeline wraps all steps — Whisper transcription through all LLM steps — in a single `try/except`. Any failure (including the LLM server being unreachable) marks the file `failed` and discards all partial progress. Re-triggering the pipeline re-transcribes from scratch and fails again at the same LLM step.

When the LLM server is temporarily down (e.g. `ollama serve` not running), every file stays `failed` until manually reset, and Whisper work is wasted on each retry.

#### Desired behaviour

- Transcription result is **persisted to the database immediately** after Whisper completes, before any LLM call is attempted.
- If an LLM call fails (connectivity, timeout, model error), the file is set to a `transcribed` status rather than `failed`.
- On the next pipeline trigger, files with `status=transcribed` **skip Whisper** and resume from the LLM step (translate → summarize → extract).
- LLM failures are logged with a clear message indicating that the file will be retried automatically on next run.

#### Implementation notes

**State machine additions** (`files.status`):

```
pending → processing → transcribed → done | failed
                             ↑
                  re-entered on next pipeline run
                  (skips Whisper, resumes at LLM)
```

**`run_pipeline()` changes** (`app/services/pipeline.py`):

1. Split the single `try/except` into two stages:
   - **Stage A — Whisper**: `pending → processing → transcribed`. On exception, mark `failed`.
   - **Stage B — LLM**: `transcribed → processing → done`. On LLM connectivity error specifically, revert to `transcribed` (not `failed`) so it is retried next run. Other fatal errors (bad JSON, etc.) still mark `failed`.
2. Persist transcription + language to a new `Entry` row (with null LLM fields) at end of Stage A.
3. Stage B updates the existing `Entry` row with translation, summary, extracted_json.

**`process_pending_files()` changes** (`app/services/pipeline.py`):

- Query `status IN ('pending', 'transcribed')` instead of only `pending`.
- Pass a flag or check `entry` existence to know which stage to run.

**LLM error classification** (`app/services/llm.py`):

- Catch `httpx.ConnectError` and `httpx.TimeoutException` separately and re-raise as a typed `LLMUnavailableError`.
- Pipeline Stage B catches `LLMUnavailableError` → revert to `transcribed`. All other exceptions → `failed`.

**DB migration**: `files.status` is already a plain `TEXT` column with no enum constraint, so adding `transcribed` requires no schema migration — only code changes.
