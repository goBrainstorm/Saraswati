# Personal Knowledge Base

A self-hosted AI system that ingests voice messages, converts them to structured knowledge, and exposes a conversational interface that can reason over personal history.

Audio files are transcribed, translated, summarized, and semantically indexed. Everything is stored permanently in a vector database and queryable via a chat interface accessible over Tailscale. Raw files are archived to Nextcloud and deleted locally after a configurable number of days.

See **[ROADMAP.md](ROADMAP.md)** for the full architecture and implementation plan.

---

## Setup & Usage

### 0. Install ffmpeg

ffmpeg is required for audio processing. A helper script handles the most common package managers (apt, pacman, brew, dnf):

```bash
bash install_ffmpeg.sh
```

### 1. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate   # bash/zsh
# or: source .venv/bin/activate.fish
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
```

Edit `.env` as needed. The only required change for local use is confirming `HOST` and `PORT`. Nextcloud credentials are optional — leave them blank and audio files will accumulate locally without being archived.

Key settings:

| Variable | Default | Description |
|---|---|---|
| `HOST` | `127.0.0.1` | Bind address |
| `PORT` | `8000` | Bind port |
| `LOCAL_RETENTION_DAYS` | `7` | Days before local files are eligible for cleanup |
| `SCHEDULE_CRON` | `0 3 * * *` | When the pipeline job runs (daily at 03:00) |
| `NEXTCLOUD_URL` | _(empty)_ | Leave blank to disable Nextcloud archiving |

### 3. Start the server

```bash
# Development (auto-reload on code changes)
uvicorn main:app --reload

# Production
python main.py
```

The web UI is available at `http://localhost:8000`.

### 4. Upload audio

Open the web UI and use the upload form, or send a file directly via the API:

```bash
curl -X POST http://localhost:8000/api/upload \
  -F "file=@recording.m4a"
```

Duplicate files (same SHA-256 content) return HTTP 409 with the existing record.

### 5. Check file status

Open `http://localhost:8000` to see the file list, or query the API:

```bash
curl http://localhost:8000/api/status
```

### 6. Trigger the pipeline manually

The processing pipeline runs automatically on the cron schedule. To trigger it immediately:

```bash
curl -X POST http://localhost:8000/api/process
```

> **Note**: The pipeline is a stub in Phase 1. Transcription and LLM processing are wired in Phase 2.

---

## What It Does

- Accepts audio file uploads via a web app or local directory
- Runs a processing pipeline (on a schedule or on demand) that:
  - Transcribes audio with faster-whisper
  - Translates, summarizes, and extracts structured information with Gemma-4-E4B via llama.cpp
  - Stores results in SQLite and a Qdrant vector database
  - Maintains a 7-day rolling JSON cache for recent entries
  - Archives raw audio to Nextcloud and deletes local copies after N days
- Exposes a RAG-augmented chat endpoint that retrieves relevant personal history when answering questions
- Integrates with Open WebUI as a full chat interface

---

## Stack

- **Backend**: Python / FastAPI
- **LLM**: Gemma-4-E4B running in llama.cpp (`llama-server`)
- **Transcription**: faster-whisper (Phase 1–3); Gemma-4-E4B native audio (Phase 4, pending llama.cpp support)
- **Vector DB**: Qdrant (Docker)
- **Metadata DB**: SQLite
- **Scheduling**: APScheduler
- **Archive**: Nextcloud (WebDAV)
- **Remote Access**: Tailscale
- **Chat UI**: Open WebUI

---

## Project Status

This project is in active development. See [ROADMAP.md](ROADMAP.md) for phased implementation details.

**Phase 1**: Foundation & Infrastructure — file ingestion, Nextcloud archiving, scheduling  
**Phase 2**: Processing Pipeline — transcription + LLM post-processing  
**Phase 3**: Vector DB & RAG — semantic search and chat interface  
**Phase 4**: Native audio via Gemma-4-E4B (blocked on llama.cpp issue #21325)
