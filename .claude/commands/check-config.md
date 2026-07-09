Read the following files:
- `.env.example` — canonical list of all supported configuration keys with their defaults
- `.env` — the active configuration (may have missing or empty values)
- `app/config.py` — the Settings class (types, defaults, aliases)
- `app/scheduler.py` — scheduler wiring
- `CLAUDE.md` — feature descriptions tied to each config group

Then produce a configuration health report:

---

## Configuration Report

### 1. Missing keys
List any keys present in `.env.example` that are completely absent from `.env` (not just empty — truly missing). If none: "All keys present."

### 2. Service status table

| Service | Key(s) | Status | Effect |
|---------|--------|--------|--------|
| LLM processing (Phase 2) | `LLAMA_SERVER_URL`, `LLAMA_MODEL` | Configured / Default | Phase 2 feature — note if still pointing at default `http://localhost:8080` |
| Whisper transcription (Phase 2) | `WHISPER_MODEL` | Configured / Default | Phase 2 feature |
| Qdrant vector DB (Phase 3) | `QDRANT_URL`, `QDRANT_COLLECTION` | Configured / Default | Phase 3 feature |
| Tailscale remote access | `TAILSCALE_HOST` | Configured / Default | Warn if still `127.0.0.1` — server will not be reachable remotely over Tailscale |
| APScheduler | (none currently registered) | — | No scheduled jobs; processing is queue-driven |

Fill in the Status and Effect columns based on the actual `.env` values.

### 3. Operational summary
One paragraph describing what the system will actually do when started with the current config: whether Phase 2/3 features are wired (they aren't until those phases are implemented), that processing is queue-driven after uploads, and what happens to uploaded files over time.

### 5. Recommended next steps
Prioritised bullet list of configuration changes to make, if any.

---

Do not modify any files. This is a read-only diagnostic.
