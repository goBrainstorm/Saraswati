You are implementing the next incomplete item in the Saraswati personal knowledge base project.

## Step 1 — Read project state

Read these files in full before doing anything else:
- `ROADMAP.md` — source of truth for all phases and completion state
- `CLAUDE.md` — architecture, conventions, and key design decisions

## Step 2 — Identify the next item

Scan `ROADMAP.md` top-to-bottom through the phases. Find the **first `[ ]` (unchecked) item** that is not blocked.

Rules:
- **Phase 4 is permanently BLOCKED** pending llama.cpp issue #21325. Skip all Phase 4 items regardless of checkbox state. If Phase 3 is complete, say so and stop.
- If the current phase has no remaining unchecked items, move to the next phase and take its first unchecked item.
- If `$ARGUMENTS` is provided, treat it as a hint to narrow the phase or item (e.g. `phase 2 whisper` → look for the Whisper item in Phase 2). A hint cannot override the Phase 4 BLOCKED constraint.

## Step 3 — Announce before coding

Output this block before writing any code:

```
NEXT ITEM
  Phase:   <N — title>
  Item:    <exact checkbox text from ROADMAP>
  Rationale: <one sentence explaining why this item is next>
  Files to create/modify: <list>
```

Then proceed immediately — no confirmation needed.

## Step 4 — Read before you write

Before editing or creating any file, read:
- Every file you plan to modify
- Any closely related files (e.g. if adding a route, read existing routes for patterns)
- The relevant section of `CLAUDE.md` for the component type

## Step 5 — Implement

Follow all conventions from `CLAUDE.md`:
- Settings: add new keys to `app/config.py` with sensible defaults
- DB access: use `get_session()` context manager from `app/database.py`
- New routes: go in `app/routes/`; register in `main.py`
- New services: go in `app/services/`
- Tests: `pytest` + `httpx.AsyncClient`, real SQLite in `tmp_path`, no mocks

If the item is a test item, write only tests — do not refactor production code unless a bug is found.

If a new dependency is required (e.g. `faster-whisper`, `sentence-transformers`), add it to `requirements.txt` and note the install command.

If the item involves an open design question (e.g. embedding model selection, chunking strategy), **surface the question and the options** rather than silently picking one. Wait for a response before proceeding.

## Step 6 — Update ROADMAP

After implementing, change the relevant `[ ]` to `[x]` in `ROADMAP.md`.

## Constraints

- Implement **one ROADMAP item per invocation** unless two items are trivially coupled (e.g. a config key and the single function that reads it).
- Do not start Phase 4 under any circumstances.
- Do not add features, refactors, or "improvements" beyond what the checklist item describes.
