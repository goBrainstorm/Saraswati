# Phase 2 — Transcription & LLM Pipeline Completion

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete Phase 2 by adding tests for all implemented pipeline services, exposing processed entries through new API endpoints, making prompts editable at runtime via a JSON store and web UI, and updating the frontend to reflect Phase 2 capabilities.

**Architecture:** The core AI pipeline (faster-whisper → translate → summarize → extract → cache) is already fully implemented in `app/services/`. What remains is tests that cover the service logic, two new read endpoints (`/api/entries` and `/api/status/{file_id}`), a prompt configuration service backed by `data/prompts.json`, and frontend updates to expose these capabilities.

**Tech Stack:** pytest + pytest-asyncio, SQLModel, FastAPI, HTMX, httpx (already in requirements.txt — no new dependencies needed)

---

## File Map

**Create:**
- `tests/test_cache.py` — cache service tests
- `tests/test_llm.py` — LLM service pure-logic tests
- `tests/test_whisper.py` — whisper service pure-logic tests
- `tests/test_pipeline.py` — pipeline state machine tests
- `app/services/prompts.py` — load/save prompts from `data/prompts.json`
- `app/routes/entries.py` — `GET /api/entries` endpoint
- `app/routes/prompts.py` — `GET /api/prompts`, `PUT /api/prompts/{name}`
- `app/templates/partials/entries_table.html` — HTMX partial for entries list

**Modify:**
- `app/services/llm.py` — replace hardcoded prompt constants with `get_prompt()` calls
- `app/routes/status.py` — add `GET /api/status/{file_id}` detail endpoint
- `main.py` — include `entries` and `prompts` routers
- `app/templates/index.html` — add Entries section, Prompts section, update copy
- `app/templates/partials/status_table.html` — add Language column sourced from Entry

---

## Task 1: Cache Service Tests

**Files:**
- Create: `tests/test_cache.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cache.py
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlmodel import Session

from app.models import Entry, FileRecord
from app.services.cache import write_recent_cache


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _make_file(session: Session, sha: str, tmp_path: Path) -> FileRecord:
    f = tmp_path / f"{sha}.mp3"
    f.write_bytes(b"x")
    rec = FileRecord(filename=f"{sha}.mp3", sha256=sha, status="done", local_path=str(f))
    session.add(rec)
    session.commit()
    session.refresh(rec)
    return rec


def _make_entry(session: Session, file_id, created_at: datetime, lang: str = "en") -> Entry:
    entry = Entry(
        file_id=file_id,
        created_at=created_at,
        language=lang,
        transcription="hello world",
        translation="hello world",
        summary="a greeting",
        extracted_json='{"people":[],"places":[],"personal_facts":[],"action_items":[],"topics":["greetings"],"tags":["hello"]}',
    )
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


async def test_cache_empty_db(db_engine, db_session: Session, tmp_path: Path, monkeypatch):
    monkeypatch.setattr("app.config.settings.cache_dir", str(tmp_path / "cache"))

    count = await write_recent_cache()

    assert count == 0
    cache_file = tmp_path / "cache" / "recent.json"
    assert cache_file.exists()
    assert json.loads(cache_file.read_text()) == []


async def test_cache_includes_recent_entries(db_engine, db_session: Session, tmp_path: Path, monkeypatch):
    monkeypatch.setattr("app.config.settings.cache_dir", str(tmp_path / "cache"))

    rec = _make_file(db_session, "sha_cache1", tmp_path)
    _make_entry(db_session, rec.id, _utcnow() - timedelta(days=1))

    count = await write_recent_cache()

    assert count == 1
    rows = json.loads((tmp_path / "cache" / "recent.json").read_text())
    assert len(rows) == 1
    assert rows[0]["transcription"] == "hello world"
    assert rows[0]["filename"] == "sha_cache1.mp3"


async def test_cache_excludes_old_entries(db_engine, db_session: Session, tmp_path: Path, monkeypatch):
    monkeypatch.setattr("app.config.settings.cache_dir", str(tmp_path / "cache"))

    rec = _make_file(db_session, "sha_cache2", tmp_path)
    # Entry created 8 days ago — outside the 7-day window
    _make_entry(db_session, rec.id, _utcnow() - timedelta(days=8))

    count = await write_recent_cache()

    assert count == 0
    rows = json.loads((tmp_path / "cache" / "recent.json").read_text())
    assert rows == []


async def test_cache_atomic_write_leaves_no_tmp(db_engine, db_session: Session, tmp_path: Path, monkeypatch):
    monkeypatch.setattr("app.config.settings.cache_dir", str(tmp_path / "cache"))

    await write_recent_cache()

    cache_dir = tmp_path / "cache"
    assert (cache_dir / "recent.json").exists()
    assert not (cache_dir / "recent.json.tmp").exists()


async def test_cache_extracted_json_parsed(db_engine, db_session: Session, tmp_path: Path, monkeypatch):
    monkeypatch.setattr("app.config.settings.cache_dir", str(tmp_path / "cache"))

    rec = _make_file(db_session, "sha_cache3", tmp_path)
    _make_entry(db_session, rec.id, _utcnow())

    await write_recent_cache()

    rows = json.loads((tmp_path / "cache" / "recent.json").read_text())
    assert isinstance(rows[0]["extracted"], dict)
    assert "tags" in rows[0]["extracted"]
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_cache.py -v
```

Expected: FAIL — ImportError or no `test_cache.py` yet (since we just wrote it). The tests should fail with import errors or assertion errors before the implementation step, but actually the service is already implemented. They should PASS. Run them to confirm they pass.

Expected: ALL PASS (cache.py is already implemented; this step verifies the test suite itself is correct)

- [ ] **Step 3: Commit**

```bash
git add tests/test_cache.py
git commit -m "test: add cache service tests"
```

---

## Task 2: LLM Service Pure-Logic Tests

These tests cover behavior that requires no running LLM server: the English-skip guard in `translate()` and the empty-URL RuntimeError in `_chat()`.

**Files:**
- Create: `tests/test_llm.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_llm.py
import pytest

from app.services import llm


async def test_translate_skips_english(monkeypatch):
    """translate() must return the original text unchanged when lang starts with 'en'."""
    # Guarantee no HTTP call is made — LLAMA_SERVER_URL doesn't matter
    original = "This is already English."
    result = await llm.translate(original, "en")
    assert result == original


async def test_translate_skips_english_variant(monkeypatch):
    """en-US and en-GB should also be skipped."""
    text = "Hello."
    assert await llm.translate(text, "en-US") == text
    assert await llm.translate(text, "en-GB") == text


async def test_translate_calls_llm_for_non_english(monkeypatch):
    """translate() must raise RuntimeError (not silently no-op) when the server is unconfigured."""
    monkeypatch.setattr("app.config.settings.llama_server_url", "")
    with pytest.raises(RuntimeError, match="LLAMA_SERVER_URL"):
        await llm.translate("Hallo Welt.", "de")


async def test_summarize_raises_when_url_empty(monkeypatch):
    monkeypatch.setattr("app.config.settings.llama_server_url", "")
    with pytest.raises(RuntimeError, match="LLAMA_SERVER_URL"):
        await llm.summarize("Some transcript text.")


async def test_extract_raises_when_url_empty(monkeypatch):
    monkeypatch.setattr("app.config.settings.llama_server_url", "")
    with pytest.raises(RuntimeError, match="LLAMA_SERVER_URL"):
        await llm.extract("Some transcript text.")


async def test_guard_text_truncates():
    """_guard_text must truncate strings longer than _MAX_CHARS."""
    long_text = "x" * (llm._MAX_CHARS + 1)
    result = llm._guard_text(long_text)
    assert len(result) == llm._MAX_CHARS + len(" [truncated]")
    assert result.endswith("[truncated]")


async def test_guard_text_passthrough():
    """_guard_text must not modify short strings."""
    short = "hello world"
    assert llm._guard_text(short) == short
```

- [ ] **Step 2: Run tests to verify they pass**

```
pytest tests/test_llm.py -v
```

Expected: ALL PASS (pure logic, no network needed)

- [ ] **Step 3: Commit**

```bash
git add tests/test_llm.py
git commit -m "test: add LLM service pure-logic tests"
```

---

## Task 3: Whisper Service Pure-Logic Tests

**Files:**
- Create: `tests/test_whisper.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_whisper.py
import os
import pytest
from pathlib import Path

from app.services import whisper_service
from app.config import settings


async def test_transcribe_raises_for_missing_file(tmp_path: Path):
    """transcribe() must raise FileNotFoundError for a nonexistent path."""
    missing = str(tmp_path / "nonexistent.mp3")
    with pytest.raises(FileNotFoundError, match="Audio file not found"):
        await whisper_service.transcribe(missing)


def test_preprocess_skips_large_files(tmp_path: Path, monkeypatch):
    """_preprocess_audio must return (original_path, False) without calling ffmpeg
    when the file exceeds DENOISE_MAX_MB."""
    # Create a fake file whose size on disk is 1 byte but patch the threshold to 0
    audio = tmp_path / "large.mp3"
    audio.write_bytes(b"x")

    monkeypatch.setattr("app.config.settings.denoise_max_mb", 0.0)

    path, is_temp = whisper_service._preprocess_audio(str(audio))

    assert path == str(audio)   # original path returned unchanged
    assert is_temp is False     # no temp file created


def test_preprocess_raises_for_ffmpeg_failure(tmp_path: Path, monkeypatch):
    """_preprocess_audio must raise CalledProcessError when ffmpeg fails."""
    import subprocess

    audio = tmp_path / "bad.mp3"
    audio.write_bytes(b"not valid audio")

    # Threshold high enough to attempt preprocessing
    monkeypatch.setattr("app.config.settings.denoise_max_mb", 999.0)

    # Only run this test if ffmpeg is installed
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        pytest.skip("ffmpeg not available")

    with pytest.raises(subprocess.CalledProcessError):
        whisper_service._preprocess_audio(str(audio))
```

- [ ] **Step 2: Run tests to verify they pass**

```
pytest tests/test_whisper.py -v
```

Expected: `test_transcribe_raises_for_missing_file` — PASS; `test_preprocess_skips_large_files` — PASS; `test_preprocess_raises_for_ffmpeg_failure` — PASS or SKIP (ffmpeg not available)

- [ ] **Step 3: Commit**

```bash
git add tests/test_whisper.py
git commit -m "test: add whisper service pure-logic tests"
```

---

## Task 4: Pipeline State Machine Tests

These tests verify the state machine logic without requiring a running Whisper model or LLM server.

**Files:**
- Create: `tests/test_pipeline.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_pipeline.py
from pathlib import Path

from sqlmodel import Session, select

from app.models import FileRecord
from app.services.pipeline import process_pending_files, run_pipeline


async def test_process_pending_returns_zero_when_empty(db_engine, db_session: Session):
    """process_pending_files() returns 0 when there are no pending records."""
    count = await process_pending_files()
    assert count == 0


async def test_process_pending_counts_attempted(db_engine, db_session: Session, tmp_path: Path):
    """process_pending_files() returns the number of files attempted, even if they fail."""
    # Insert a pending record pointing to a nonexistent file
    rec = FileRecord(
        filename="ghost.mp3",
        sha256="sha_pipe1",
        status="pending",
        local_path=str(tmp_path / "ghost.mp3"),  # file does not exist on disk
    )
    db_session.add(rec)
    db_session.commit()

    count = await process_pending_files()

    assert count == 1


async def test_pipeline_marks_failed_for_missing_file(db_engine, db_session: Session, tmp_path: Path):
    """run_pipeline() transitions status to 'failed' when local file is absent."""
    rec = FileRecord(
        filename="missing.mp3",
        sha256="sha_pipe2",
        status="pending",
        local_path=str(tmp_path / "missing.mp3"),  # not created
    )
    db_session.add(rec)
    db_session.commit()
    rec_id = rec.id

    await run_pipeline(rec)

    db_session.expire_all()
    updated = db_session.get(FileRecord, rec_id)
    assert updated.status == "failed"
    assert updated.processed_at is not None


async def test_pipeline_sets_processing_then_failed(db_engine, db_session: Session, tmp_path: Path):
    """run_pipeline() first sets status to 'processing', then 'failed' on error."""
    # We can only observe the final state since run_pipeline is awaited sequentially.
    # This test confirms the final state is 'failed' (not 'processing') after a failed run.
    rec = FileRecord(
        filename="bad.mp3",
        sha256="sha_pipe3",
        status="pending",
        local_path=str(tmp_path / "bad.mp3"),
    )
    db_session.add(rec)
    db_session.commit()
    rec_id = rec.id

    await run_pipeline(rec)

    db_session.expire_all()
    updated = db_session.get(FileRecord, rec_id)
    assert updated.status == "failed", "status must not be left as 'processing'"
```

- [ ] **Step 2: Run tests to verify they pass**

```
pytest tests/test_pipeline.py -v
```

Expected: ALL PASS (no whisper/llm needed — all tests exercise the missing-file failure path)

- [ ] **Step 3: Commit**

```bash
git add tests/test_pipeline.py
git commit -m "test: add pipeline state machine tests"
```

---

## Task 5: `/api/entries` Endpoint

**Files:**
- Create: `app/routes/entries.py`
- Create: `app/templates/partials/entries_table.html`
- Modify: `main.py` (include router)

- [ ] **Step 1: Write the failing test first**

Add to a new file `tests/test_entries.py`:

```python
# tests/test_entries.py
from datetime import datetime, timezone
from pathlib import Path

from httpx import AsyncClient
from sqlmodel import Session

from app.models import Entry, FileRecord


def _now():
    return datetime.now(timezone.utc)


def _make_file(session: Session, sha: str, tmp_path: Path) -> FileRecord:
    f = tmp_path / f"{sha}.mp3"
    f.write_bytes(b"x")
    rec = FileRecord(filename=f"{sha}.mp3", sha256=sha, status="done", local_path=str(f))
    session.add(rec)
    session.commit()
    session.refresh(rec)
    return rec


def _make_entry(session: Session, file_id, summary: str = "test summary") -> Entry:
    entry = Entry(
        file_id=file_id,
        created_at=_now(),
        language="en",
        transcription="hello world",
        translation="hello world",
        summary=summary,
        extracted_json='{"tags":["test"]}',
    )
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


async def test_entries_empty(app_client: AsyncClient, db_engine):
    resp = await app_client.get("/api/entries")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_entries_returns_entry(app_client: AsyncClient, db_engine, db_session: Session, tmp_path: Path):
    rec = _make_file(db_session, "sha_ent1", tmp_path)
    _make_entry(db_session, rec.id, "a test summary")

    resp = await app_client.get("/api/entries")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["summary"] == "a test summary"
    assert data[0]["language"] == "en"


async def test_entries_pagination(app_client: AsyncClient, db_engine, db_session: Session, tmp_path: Path):
    for i in range(3):
        rec = _make_file(db_session, f"sha_ent_pg{i}", tmp_path)
        _make_entry(db_session, rec.id, f"summary {i}")

    resp = await app_client.get("/api/entries?limit=2&offset=0")
    assert resp.status_code == 200
    assert len(resp.json()) == 2

    resp2 = await app_client.get("/api/entries?limit=2&offset=2")
    assert resp2.status_code == 200
    assert len(resp2.json()) == 1


async def test_status_detail_includes_entry(app_client: AsyncClient, db_engine, db_session: Session, tmp_path: Path):
    rec = _make_file(db_session, "sha_det1", tmp_path)
    entry = _make_entry(db_session, rec.id, "detail summary")

    resp = await app_client.get(f"/api/status/{rec.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["file"]["id"] == str(rec.id)
    assert data["entry"]["summary"] == "detail summary"


async def test_status_detail_no_entry(app_client: AsyncClient, db_engine, db_session: Session, tmp_path: Path):
    rec = _make_file(db_session, "sha_det2", tmp_path)

    resp = await app_client.get(f"/api/status/{rec.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["file"]["id"] == str(rec.id)
    assert data["entry"] is None


async def test_status_detail_404(app_client: AsyncClient, db_engine):
    import uuid
    resp = await app_client.get(f"/api/status/{uuid.uuid4()}")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_entries.py -v
```

Expected: FAIL with 404 for `/api/entries` (route does not exist yet)

- [ ] **Step 3: Implement `app/routes/entries.py`**

```python
# app/routes/entries.py
from typing import List
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import select

from app.database import get_session
from app.models import Entry, FileRecord

router = APIRouter()


@router.get("/api/entries", response_model=List[Entry])
async def get_entries(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> List[Entry]:
    """Return a paginated list of all processed entries, newest first."""
    with get_session() as session:
        statement = (
            select(Entry)
            .order_by(Entry.created_at.desc())  # type: ignore[union-attr]
            .offset(offset)
            .limit(limit)
        )
        return list(session.exec(statement).all())
```

- [ ] **Step 4: Add `/api/status/{file_id}` detail to `app/routes/status.py`**

Open `app/routes/status.py`. Add this import at the top (it already imports `Entry` and `UUID`):

```python
from typing import Any, Dict, Optional
```

Then add this route **before** the `delete_file` route at the bottom of the file:

```python
@router.get("/api/status/{file_id}")
async def get_file_detail(file_id: UUID) -> Dict[str, Any]:
    """Return a FileRecord and its associated Entry (if any)."""
    with get_session() as session:
        record = session.get(FileRecord, file_id)
        if not record:
            raise HTTPException(status_code=404, detail="File not found")

        entry_stmt = select(Entry).where(Entry.file_id == file_id)
        entry = session.exec(entry_stmt).first()

        return {
            "file": record.model_dump(),
            "entry": entry.model_dump() if entry else None,
        }
```

- [ ] **Step 5: Register the entries router in `main.py`**

In `main.py`, change the import line:

```python
from app.routes import process, status, upload
```

to:

```python
from app.routes import entries, process, status, upload
```

And add after the existing `app.include_router(process.router)` line:

```python
app.include_router(entries.router)
```

- [ ] **Step 6: Create `app/templates/partials/entries_table.html`**

```html
<table>
  <thead>
    <tr>
      <th>Filename</th>
      <th>Language</th>
      <th>Summary</th>
      <th>Processed</th>
    </tr>
  </thead>
  <tbody>
    {% for e in entries %}
    <tr>
      <td title="{{ e.file_id }}">{{ e.filename or '—' }}</td>
      <td>{{ e.language or '—' }}</td>
      <td style="max-width:400px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;" title="{{ e.summary or '' }}">
        {{ e.summary or '—' }}
      </td>
      <td>{{ e.created_at.strftime('%Y-%m-%d %H:%M') if e.created_at else '—' }}</td>
    </tr>
    {% else %}
    <tr>
      <td colspan="4" style="text-align:center; color: var(--muted);">No entries processed yet.</td>
    </tr>
    {% endfor %}
  </tbody>
</table>
```

Note: `entries_table.html` uses an `entries` context variable that includes `filename` joined from `FileRecord`. This requires a dedicated HTMX endpoint that joins the data. Add `GET /api/entries/table` to `entries.py`:

```python
@router.get("/api/entries/table", response_class=HTMLResponse)
async def entries_table(request: Request) -> HTMLResponse:
    """Return an HTML table fragment for HTMX rendering."""
    from fastapi.responses import HTMLResponse
    import jinja2
    from pathlib import Path as _Path

    _TEMPLATES_DIR = _Path(__file__).parent.parent / "templates"
    _jinja_env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=jinja2.select_autoescape(["html"]),
        cache_size=0,
    )

    with get_session() as session:
        statement = (
            select(Entry)
            .order_by(Entry.created_at.desc())  # type: ignore[union-attr]
            .limit(100)
        )
        raw_entries = list(session.exec(statement).all())

        file_ids = {e.file_id for e in raw_entries}
        filenames: dict = {}
        for fid in file_ids:
            rec = session.get(FileRecord, fid)
            if rec:
                filenames[fid] = rec.filename

    rows = [
        {
            "file_id": e.file_id,
            "filename": filenames.get(e.file_id),
            "language": e.language,
            "summary": e.summary,
            "created_at": e.created_at,
        }
        for e in raw_entries
    ]

    tmpl = _jinja_env.get_template("partials/entries_table.html")
    html = tmpl.render(entries=rows)
    return HTMLResponse(content=html)
```

Also add `from fastapi import Request` to the import block in `entries.py` (update the full import block):

```python
from typing import List
from uuid import UUID

import jinja2
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pathlib import Path as _Path
from sqlmodel import select

from app.database import get_session
from app.models import Entry, FileRecord

router = APIRouter()
```

- [ ] **Step 7: Run the tests to verify they pass**

```
pytest tests/test_entries.py -v
```

Expected: ALL PASS

- [ ] **Step 8: Run the full test suite to check for regressions**

```
pytest -v
```

Expected: ALL PASS

- [ ] **Step 9: Commit**

```bash
git add app/routes/entries.py app/routes/status.py app/templates/partials/entries_table.html main.py tests/test_entries.py
git commit -m "feat: add /api/entries and /api/status/{file_id} detail endpoints"
```

---

## Task 6: Prompt Configuration Service

**Files:**
- Create: `app/services/prompts.py`
- Modify: `app/services/llm.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_prompts.py`:

```python
# tests/test_prompts.py
import json
import pytest
from pathlib import Path

from app.services import prompts as prompts_svc


def test_load_prompts_returns_defaults_when_no_file(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("app.config.settings.cache_dir", str(tmp_path / "cache"))
    result = prompts_svc.load_prompts()
    assert "translate_system" in result
    assert "summarize_system" in result
    assert "extract_system" in result


def test_get_prompt_returns_default(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("app.config.settings.cache_dir", str(tmp_path / "cache"))
    val = prompts_svc.get_prompt("translate_system")
    assert len(val) > 10  # non-empty default


def test_update_and_reload_prompt(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("app.config.settings.cache_dir", str(tmp_path / "cache"))
    prompts_svc.update_prompt("translate_system", "Custom system prompt.")
    assert prompts_svc.get_prompt("translate_system") == "Custom system prompt."


def test_update_unknown_prompt_raises(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("app.config.settings.cache_dir", str(tmp_path / "cache"))
    with pytest.raises(ValueError, match="Unknown prompt"):
        prompts_svc.update_prompt("nonexistent_key", "value")


def test_save_and_load_roundtrip(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("app.config.settings.cache_dir", str(tmp_path / "cache"))
    prompts_svc.update_prompt("summarize_system", "My custom summarizer.")
    # Reload from disk
    loaded = prompts_svc.load_prompts()
    assert loaded["summarize_system"] == "My custom summarizer."
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_prompts.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.prompts'`

- [ ] **Step 3: Implement `app/services/prompts.py`**

```python
# app/services/prompts.py
"""Runtime-editable prompt store.

Prompts are stored in ``data/prompts.json``. If the file is absent or
unreadable, hardcoded defaults are used. ``update_prompt`` persists a change
back to disk immediately.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

DEFAULTS: dict[str, str] = {
    "translate_system": (
        "You are a professional translator. "
        "Translate the following text into English. "
        "Output only the translated text, with no commentary, "
        "no explanations, and no preamble."
    ),
    "translate_user": "Text to translate:\n\n{text}",
    "summarize_system": (
        "You are an expert at distilling spoken audio transcripts into concise summaries. "
        "Write a clear, dense summary of the following transcript. "
        "Capture the main topic, key points, and any decisions or conclusions. "
        "Write in third person. Output only the summary, no preamble."
    ),
    "summarize_user": "Transcript:\n\n{text}",
    "extract_system": (
        "You are a structured information extraction system. "
        "Extract entities and facts from the following transcript. "
        "You MUST respond with a single valid JSON object matching this exact schema "
        "and nothing else — no markdown fences, no commentary:\n"
        "{\n"
        '  "people": ["list of person names mentioned"],\n'
        '  "places": ["list of locations mentioned"],\n'
        '  "personal_facts": ["statements of fact about the speaker or their life"],\n'
        '  "action_items": ["tasks or commitments mentioned"],\n'
        '  "topics": ["main subjects discussed"],\n'
        '  "tags": ["short keyword tags for retrieval, max 10"]\n'
        "}\n"
        "Use empty arrays for categories with no relevant content. "
        "Do not invent information not present in the text."
    ),
    "extract_user": "Transcript:\n\n{text}",
}


def _prompts_path() -> Path:
    return Path("data") / "prompts.json"


def load_prompts() -> dict[str, str]:
    """Return the current prompts dict (defaults merged with any saved overrides)."""
    path = _prompts_path()
    if path.exists():
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            merged = dict(DEFAULTS)
            merged.update({k: v for k, v in saved.items() if k in DEFAULTS})
            return merged
        except Exception as exc:
            logger.warning("Failed to load prompts from %s: %s. Using defaults.", path, exc)
    return dict(DEFAULTS)


def get_prompt(name: str) -> str:
    """Return the current value of a single prompt by name."""
    return load_prompts().get(name, DEFAULTS.get(name, ""))


def update_prompt(name: str, text: str) -> None:
    """Persist an updated prompt value to disk.

    Raises:
        ValueError: if *name* is not a recognised prompt key.
    """
    if name not in DEFAULTS:
        raise ValueError(f"Unknown prompt: '{name}'. Valid keys: {list(DEFAULTS)}")
    current = load_prompts()
    current[name] = text
    path = _prompts_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Prompt '%s' updated and saved to %s.", name, path)
```

- [ ] **Step 4: Run the prompt tests to verify they pass**

```
pytest tests/test_prompts.py -v
```

Expected: ALL PASS

- [ ] **Step 5: Update `app/services/llm.py` to use `get_prompt()`**

In `app/services/llm.py`, remove the module-level prompt constants and replace the callers. Here is the full updated file:

```python
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict

import httpx

from app.config import settings
from app.services.prompts import get_prompt

logger = logging.getLogger(__name__)

_MAX_CHARS = 32_000


def _guard_text(text: str) -> str:
    """Truncate text to _MAX_CHARS if necessary."""
    if len(text) > _MAX_CHARS:
        logger.warning(
            "Text length %d exceeds limit %d; truncating.", len(text), _MAX_CHARS
        )
        return text[:_MAX_CHARS] + " [truncated]"
    return text


async def _chat(messages: list[dict], temperature: float = 0.3) -> str:
    """Send a chat completion request to llama-server and return the reply text.

    Raises:
        RuntimeError: if LLAMA_SERVER_URL is not configured.
        httpx.ConnectError / httpx.TimeoutException: propagated to caller.
        httpx.HTTPStatusError: on non-2xx response.
    """
    if not settings.llama_server_url:
        raise RuntimeError(
            "LLAMA_SERVER_URL is not configured. Cannot call LLM."
        )

    url = settings.llama_server_url.rstrip("/") + "/v1/chat/completions"
    payload = {
        "model": settings.llama_model,
        "messages": messages,
        "temperature": temperature,
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()

    data = response.json()
    return data["choices"][0]["message"]["content"].strip()


async def translate(text: str, source_lang: str) -> str:
    """Translate text to English using the configured LLM.

    Returns text unchanged if source_lang starts with 'en' (no API call).
    """
    if source_lang.startswith("en"):
        logger.debug("Language is '%s', skipping translation.", source_lang)
        return text

    logger.info("Translating from '%s' to English.", source_lang)
    messages = [
        {"role": "system", "content": get_prompt("translate_system")},
        {"role": "user", "content": get_prompt("translate_user").format(text=_guard_text(text))},
    ]
    return await _chat(messages, temperature=0.3)


async def summarize(text: str) -> str:
    """Generate a dense summary of the given transcript text."""
    logger.info("Summarizing transcript (%d chars).", len(text))
    messages = [
        {"role": "system", "content": get_prompt("summarize_system")},
        {"role": "user", "content": get_prompt("summarize_user").format(text=_guard_text(text))},
    ]
    return await _chat(messages, temperature=0.3)


async def extract(text: str) -> Dict[str, Any]:
    """Extract structured entities and facts from the given transcript.

    Returns a dict with keys: people, places, personal_facts, action_items,
    topics, tags.

    Raises:
        json.JSONDecodeError: if the LLM response cannot be parsed as JSON.
    """
    logger.info("Extracting entities from transcript (%d chars).", len(text))
    messages = [
        {"role": "system", "content": get_prompt("extract_system")},
        {"role": "user", "content": get_prompt("extract_user").format(text=_guard_text(text))},
    ]
    raw = await _chat(messages, temperature=0.0)

    # Strip markdown fences if the model added them despite instructions
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        logger.error("Failed to parse extraction JSON. Raw response:\n%s", raw)
        raise
```

- [ ] **Step 6: Run all tests to verify nothing broke**

```
pytest -v
```

Expected: ALL PASS (llm.py tests still pass since `get_prompt()` returns the same defaults)

- [ ] **Step 7: Commit**

```bash
git add app/services/prompts.py app/services/llm.py tests/test_prompts.py
git commit -m "feat: add runtime-editable prompt store; wire llm.py to use get_prompt()"
```

---

## Task 7: Prompts API Endpoint

**Files:**
- Create: `app/routes/prompts.py`
- Modify: `main.py` (include router)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_prompts.py` (append to the file):

```python
# Append to tests/test_prompts.py

from httpx import AsyncClient


async def test_get_prompts_returns_all_keys(app_client: AsyncClient, db_engine, tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.cache_dir", str(tmp_path / "cache"))
    resp = await app_client.get("/api/prompts")
    assert resp.status_code == 200
    data = resp.json()
    assert "translate_system" in data
    assert "extract_system" in data
    assert len(data) == 6  # all six prompts


async def test_put_prompt_updates_value(app_client: AsyncClient, db_engine, tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.cache_dir", str(tmp_path / "cache"))
    resp = await app_client.put(
        "/api/prompts/translate_system",
        json={"text": "New system prompt."},
    )
    assert resp.status_code == 200
    assert resp.json()["translate_system"] == "New system prompt."


async def test_put_unknown_prompt_returns_422(app_client: AsyncClient, db_engine):
    resp = await app_client.put(
        "/api/prompts/nonexistent_key",
        json={"text": "something"},
    )
    assert resp.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_prompts.py::test_get_prompts_returns_all_keys tests/test_prompts.py::test_put_prompt_updates_value tests/test_prompts.py::test_put_unknown_prompt_returns_422 -v
```

Expected: FAIL — 404 (routes don't exist yet)

- [ ] **Step 3: Implement `app/routes/prompts.py`**

```python
# app/routes/prompts.py
from typing import Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.prompts import DEFAULTS, get_prompt, load_prompts, update_prompt

router = APIRouter()


class PromptUpdate(BaseModel):
    text: str


@router.get("/api/prompts")
async def get_prompts() -> Dict[str, str]:
    """Return all current prompt values."""
    return load_prompts()


@router.put("/api/prompts/{name}")
async def put_prompt(name: str, body: PromptUpdate) -> Dict[str, str]:
    """Update a single prompt by name. Returns the full updated prompts dict."""
    if name not in DEFAULTS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown prompt '{name}'. Valid keys: {list(DEFAULTS)}",
        )
    update_prompt(name, body.text)
    return load_prompts()
```

- [ ] **Step 4: Register the prompts router in `main.py`**

Change:
```python
from app.routes import entries, process, status, upload
```
to:
```python
from app.routes import entries, process, prompts, status, upload
```

And add after `app.include_router(entries.router)`:
```python
app.include_router(prompts.router)
```

- [ ] **Step 5: Run the tests to verify they pass**

```
pytest tests/test_prompts.py -v
```

Expected: ALL PASS

- [ ] **Step 6: Run the full test suite**

```
pytest -v
```

Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add app/routes/prompts.py main.py tests/test_prompts.py
git commit -m "feat: add /api/prompts GET and PUT endpoints"
```

---

## Task 8: Frontend Update — Phase 2 UI

Update the web UI to reflect that the pipeline is functional, add an Entries section, and add a Prompts editor section.

**Files:**
- Modify: `app/templates/index.html`
- Modify: `app/templates/partials/status_table.html`

- [ ] **Step 1: Update the status table partial to show the language column**

In `app/templates/partials/status_table.html`, add a "Language" column by modifying the header row. The current table doesn't have language; adding it requires a join. Since the partial currently only receives `records` (list of FileRecord), we need to either pass entry data via a dict or change the route to pass combined data.

The simplest approach: keep the status table showing FileRecord data only (language lookup would require a join that changes the route), and rely on the new Entries section for per-entry detail. Just update the status table header to remove "Nextcloud" and "Delete After" from the main view to reduce clutter — leave those for the detail endpoint.

Actually: leave the status table as-is. Don't change it. The Entries section is the right place for transcription data.

- [ ] **Step 2: Update `index.html`**

Make the following changes to `app/templates/index.html`:

**Change 1:** Update the subtitle in the `<header>`:
- Old: `<p>Self-hosted audio ingestion pipeline — Phase 1</p>`
- New: `<p>Self-hosted audio ingestion and knowledge pipeline — Phase 2</p>`

**Change 2:** Update the `<app>` description in `main.py`:
- Old: `description="Self-hosted audio ingestion and knowledge pipeline — Phase 1"`
- New: `description="Self-hosted audio ingestion and knowledge pipeline — Phase 2"`

**Change 3:** Update the pipeline control section description:
- Old: `<p>Manually trigger the processing pipeline. In Phase 1 this is a stub — no actual transcription occurs.</p>`
- New: `<p>Manually trigger the processing pipeline. Processes all pending audio files through Whisper transcription and LLM analysis.</p>`

**Change 4:** Add an Entries section after the File Status section, before Pipeline Control:

```html
<!-- ---------------------------------------------------------------- -->
<!-- Entries section                                                    -->
<!-- ---------------------------------------------------------------- -->
<section>
  <h2>
    Processed Entries
    <span class="htmx-indicator" id="entries-spinner" style="font-size:0.75rem; color:var(--muted); font-weight:400; letter-spacing:0; text-transform:none; margin-left:0.5rem;">
      refreshing<span class="spinner"></span>
    </span>
  </h2>

  <div
    id="entries-panel"
    hx-get="/api/entries/table"
    hx-trigger="load, every 15s"
    hx-swap="innerHTML"
    hx-indicator="#entries-spinner"
  >
    <p style="color:var(--muted); font-size:0.875rem;">Loading...</p>
  </div>
</section>
```

**Change 5:** Add a Prompts section after the Pipeline Control section, before the footer:

```html
<!-- ---------------------------------------------------------------- -->
<!-- Prompt configuration section                                       -->
<!-- ---------------------------------------------------------------- -->
<section>
  <h2>Prompt Configuration</h2>
  <p style="color:var(--muted); font-size:0.875rem; margin-bottom:1.5rem;">
    Edit the prompts used by the LLM pipeline. Changes take effect on the next pipeline run.
  </p>

  <div id="prompts-container" hx-get="/api/prompts-ui" hx-trigger="load" hx-swap="innerHTML">
    <p style="color:var(--muted); font-size:0.875rem;">Loading prompts...</p>
  </div>
</section>
```

Wait — a prompts UI requires a dedicated HTMX partial endpoint that renders textareas. This is getting complex. Let me simplify: render the prompt editing UI directly in JavaScript on page load, fetching from `/api/prompts`.

**Change 5 (revised):** Add a simpler Prompts section that renders via JavaScript:

```html
<!-- ---------------------------------------------------------------- -->
<!-- Prompt configuration section                                       -->
<!-- ---------------------------------------------------------------- -->
<section id="prompts-section">
  <h2>Prompt Configuration</h2>
  <p style="color:var(--muted); font-size:0.875rem; margin-bottom:1.5rem;">
    Edit the prompts used by the LLM pipeline. Changes take effect on the next pipeline run.
  </p>
  <div id="prompts-container">
    <p style="color:var(--muted); font-size:0.875rem;">Loading...</p>
  </div>
</section>
```

Add to the `<script>` block in `index.html`:

```javascript
(async function loadPrompts() {
  const container = document.getElementById('prompts-container');
  try {
    const resp = await fetch('/api/prompts');
    const prompts = await resp.json();
    const labels = {
      translate_system: 'Translate — System',
      translate_user:   'Translate — User template',
      summarize_system: 'Summarize — System',
      summarize_user:   'Summarize — User template',
      extract_system:   'Extract — System',
      extract_user:     'Extract — User template',
    };
    container.innerHTML = Object.entries(prompts).map(([key, val]) => `
      <div style="margin-bottom:1.5rem;">
        <label style="display:block; font-size:0.8rem; color:var(--muted); margin-bottom:0.4rem; text-transform:uppercase; letter-spacing:0.05em;">
          ${labels[key] || key}
        </label>
        <textarea id="prompt-${key}" rows="4" style="width:100%; background:var(--bg); color:var(--text); border:1px solid var(--border); border-radius:var(--radius); padding:0.6rem; font-family:monospace; font-size:0.8rem; resize:vertical;">${val.replace(/</g,'&lt;')}</textarea>
        <button onclick="savePrompt('${key}')" class="secondary" style="margin-top:0.4rem; font-size:0.8rem; padding:0.3rem 0.8rem;">Save</button>
        <span id="prompt-msg-${key}" style="font-size:0.8rem; margin-left:0.75rem; color:var(--muted);"></span>
      </div>
    `).join('');
  } catch (e) {
    container.innerHTML = '<p style="color:var(--danger)">Failed to load prompts.</p>';
  }
})();

async function savePrompt(key) {
  const textarea = document.getElementById('prompt-' + key);
  const msgEl = document.getElementById('prompt-msg-' + key);
  if (!textarea) return;
  msgEl.textContent = 'Saving…';
  msgEl.style.color = 'var(--muted)';
  try {
    const resp = await fetch('/api/prompts/' + key, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: textarea.value }),
    });
    if (resp.ok) {
      msgEl.textContent = 'Saved.';
      msgEl.style.color = 'var(--success)';
    } else {
      msgEl.textContent = 'Error: ' + resp.status;
      msgEl.style.color = 'var(--danger)';
    }
  } catch {
    msgEl.textContent = 'Network error.';
    msgEl.style.color = 'var(--danger)';
  }
}
```

**Change 6:** Update the `<footer>`:
- Old: `Knowledge Base &mdash; Phase 1 scaffold &mdash; self-hosted`
- New: `Knowledge Base &mdash; Phase 2 &mdash; self-hosted`

- [ ] **Step 3: Apply all changes to `index.html`**

Apply each of the 6 changes listed in Step 2 using targeted edits to `app/templates/index.html`.

For the subtitle:
```
Old: <p>Self-hosted audio ingestion pipeline — Phase 1</p>
New: <p>Self-hosted audio ingestion and knowledge pipeline — Phase 2</p>
```

For the pipeline description:
```
Old: <p>Manually trigger the processing pipeline. In Phase 1 this is a stub — no actual transcription occurs.</p>
New: <p>Manually trigger the processing pipeline. Processes all pending audio files through Whisper transcription and LLM analysis.</p>
```

For the footer:
```
Old: Knowledge Base &mdash; Phase 1 scaffold &mdash; self-hosted
New: Knowledge Base &mdash; Phase 2 &mdash; self-hosted
```

Insert the Entries section HTML after the closing `</section>` of the File Status section (before the `<!-- Manual trigger section -->` comment).

Insert the Prompts section HTML after the closing `</section>` of the Pipeline Control section (before the `<footer>` tag).

Insert the `loadPrompts` and `savePrompt` functions into the `<script>` block before the closing `</script>` tag.

- [ ] **Step 4: Update `main.py` description**

In `main.py`, change:
```python
    description="Self-hosted audio ingestion and knowledge pipeline — Phase 1",
```
to:
```python
    description="Self-hosted audio ingestion and knowledge pipeline — Phase 2",
```

- [ ] **Step 5: Run the full test suite to confirm nothing broke**

```
pytest -v
```

Expected: ALL PASS

- [ ] **Step 6: Verify the UI manually**

```
source .venv/bin/activate.fish && uvicorn main:app --reload
```

Open `http://localhost:8000` in a browser. Verify:
- Header shows "Phase 2"
- Entries section appears and shows "No entries processed yet."
- Prompts section loads all 6 prompt textareas with their default text
- Save button on a prompt shows "Saved." on click

- [ ] **Step 7: Commit**

```bash
git add app/templates/index.html app/templates/partials/entries_table.html main.py
git commit -m "feat: update frontend for Phase 2 — entries section and prompt editor"
```

---

## Self-Review

### Spec Coverage Check

ROADMAP Phase 2 items vs. plan tasks:

| ROADMAP Item | Covered By |
|---|---|
| faster-whisper integration | Already implemented; Task 3 adds tests |
| Audio preprocessing (ffmpeg loudnorm) | Already implemented; Task 3 adds tests |
| Denoising skip for large files | Already implemented; Task 3 tests size threshold |
| llama.cpp server integration | Already implemented; Task 2 tests guard logic |
| Translation prompt chain | Already implemented; Task 6 makes it editable |
| Summarization prompt chain | Already implemented; Task 6 makes it editable |
| Extraction prompt chain | Already implemented; Task 6 makes it editable |
| SQLite `entries` table populated | Already implemented in pipeline.py |
| Short-term cache writer | Already implemented; Task 1 adds tests |
| Processing state machine (pending→processing→done/failed) | Already implemented; Task 4 adds tests |
| `/api/status` exposing per-file results | Task 5 adds `/api/status/{file_id}` detail |
| Prompt editing on Web app | Task 7 (API) + Task 8 (UI) |
| `/api/entries` — browse processed entries | Task 5 |

All ROADMAP Phase 2 items are covered. ✓

### Placeholder Scan

- No "TBD" or "TODO" present in code steps
- Every code block is complete and directly usable
- All file paths are exact
- All test function names are referenced consistently

### Type Consistency

- `Entry.model_dump()` — `Entry` is a SQLModel; `model_dump()` is the Pydantic v2 method (SQLModel 0.0.14+ uses Pydantic v2). If the installed SQLModel version uses `.dict()` instead, replace with `.dict()`. Verify by running `python -c "from app.models import Entry; print(Entry().model_dump)"` in the virtualenv.
- `FileRecord.model_dump()` — same caveat applies
- `entries_table.html` receives a list of plain dicts (not SQLModel objects) so attribute access uses dict key syntax (`e.filename`, etc.) — the template uses dot notation which works for both dicts and objects in Jinja2 since Jinja2 tries both

---

Plan complete and saved to `docs/superpowers/plans/2026-04-05-phase2-pipeline-completion.md`.

**Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
