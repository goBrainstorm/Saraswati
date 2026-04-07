# Pipeline Separation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the pipeline to process files in horizontal batches (transcribe all, then translate all, etc.) and add a manual endpoint for immediate single-file processing.

**Architecture:** Split the monolithic `run_pipeline` into individual stage functions that reload the model instances to avoid detached ORM objects. Maintain the current behavior of using `processing` transient status before transcription. Ensure Nextcloud side-effect happens at the end of the pipeline. Define `attempted` mathematically as files hit in at least one stage. Manual `/api/process/{file_id}` explicitly does not trigger a cache update.

**Tech Stack:** FastAPI, SQLModel, pytest

---

### Task 1: Split pipeline into stage functions (Database Safe)

**Files:**
- Modify: `app/services/pipeline.py`

- [ ] **Step 1: Extract `run_transcription`**
Create a new async function `run_transcription(file_id: uuid.UUID) -> Optional[str]` in `app/services/pipeline.py` containing the Stage 1 logic (transcribe). 
- Load `FileRecord` via `session.get(FileRecord, file_id)`.
- Replicate marking `status` = `"processing"` and commiting before `whisper_service.transcribe` runs.
- If successful, set to `"transcribed"` and create `Entry`. If exception, set to `"failed"`. Catch exception and return `str(exc)` or `None`.

- [ ] **Step 2: Extract `run_translation`**
Create `run_translation(file_id: uuid.UUID) -> Optional[str]` containing Stage 2 logic. 
- Load `FileRecord` and `Entry` inside session.
- Add a comment `# TODO: Check token count > 4096 here before translation` before calling `llm.translate`. 
- Set status to `"translated"`. Catch exceptions and return string or None.

- [ ] **Step 3: Extract `run_summarization`**
Create `run_summarization(file_id: uuid.UUID) -> Optional[str]` containing Stage 3 logic. 
- Load `FileRecord` and `Entry` inside session.
- Add a comment `# TODO: Check token count > 4096 here before summarization` before calling `llm.summarize`. 
- Set status to `"summarized"`.

- [ ] **Step 4: Extract `run_extraction_and_finalize`**
Create `run_extraction_and_finalize(file_id: uuid.UUID) -> Optional[str]` containing Stages 4, 5, and 6 (extract, embed, mark `done` with `processed_at`, Nextcloud upload). 
- Load `FileRecord` and `Entry` inside session. 
- Keep the side-effect order: extract -> embed (qdrant) -> mark `"done"` in sqlite -> upload to nextcloud.

### Task 2: Refactor `process_pending_files`

**Files:**
- Modify: `app/services/pipeline.py`

- [ ] **Step 1: Update `process_pending_files` logic**
Rewrite `process_pending_files` to run in horizontal batches using sets for counting to avoid double-counting files touched multiple times.

```python
    succeeded = 0
    failed = 0
    errors = []
    attempted_ids = set()

    with get_session() as session:
        pending = session.exec(select(FileRecord).where(FileRecord.status == "pending")).all()
        pending_ids = [r.id for r in pending]
    for fid in pending_ids:
        attempted_ids.add(fid)
        error = await run_transcription(fid)
        if error:
            errors.append({"filename": str(fid), "error": error})
            failed += 1
        else:
            succeeded += 1

    with get_session() as session:
        transcribed = session.exec(select(FileRecord).where(FileRecord.status == "transcribed")).all()
        transcribed_ids = [r.id for r in transcribed]
    for fid in transcribed_ids:
        attempted_ids.add(fid)
        error = await run_translation(fid)
        if error:
            errors.append({"filename": str(fid), "error": error})
            failed += 1
        else:
            succeeded += 1
        
    with get_session() as session:
        translated = session.exec(select(FileRecord).where(FileRecord.status == "translated")).all()
        translated_ids = [r.id for r in translated]
    for fid in translated_ids:
        attempted_ids.add(fid)
        error = await run_summarization(fid)
        if error:
            errors.append({"filename": str(fid), "error": error})
            failed += 1
        else:
            succeeded += 1
        
    with get_session() as session:
        summarized = session.exec(select(FileRecord).where(FileRecord.status == "summarized")).all()
        summarized_ids = [r.id for r in summarized]
    for fid in summarized_ids:
        attempted_ids.add(fid)
        error = await run_extraction_and_finalize(fid)
        if error:
            errors.append({"filename": str(fid), "error": error})
            failed += 1
        else:
            succeeded += 1

    return {"attempted": len(attempted_ids), "succeeded": succeeded, "failed": failed, "errors": errors}
```
*(Remove the old `run_pipeline` function completely).*

- [ ] **Step 2: Check syntax and basic logic**
Ensure it type-checks and imports are correct.

### Task 3: Implement single-file manual endpoint (No Cache Refresh)

**Files:**
- Modify: `app/routes/process.py`
- Modify: `tests/test_process.py`

- [ ] **Step 1: Write test for single file manual trigger**
Add a failing test to `tests/test_process.py`:
```python
import uuid
@pytest.mark.asyncio
async def test_process_single_file_not_found(client: AsyncClient):
    fake_id = uuid.uuid4()
    response = await client.post(f"/api/process/{fake_id}")
    assert response.status_code == 404
```

- [ ] **Step 2: Run test**
Run: `pytest tests/test_process.py -v`
Expected: FAIL (404 != 405 Method Not Allowed or 404 because route doesn't exist)

- [ ] **Step 3: Implement `POST /api/process/{file_id}`**
Add the endpoint in `app/routes/process.py`. Do NOT call `write_recent_cache()`:
```python
from uuid import UUID
from fastapi import APIRouter, HTTPException
from typing import Dict, Any

from app.database import get_session
from app.models import FileRecord

@router.post("/api/process/{file_id}")
async def trigger_process_single(file_id: UUID) -> Dict[str, Any]:
    """Manually process a specific file without triggering a cache refresh."""
    from app.services.pipeline import (
        run_transcription, run_translation, run_summarization, run_extraction_and_finalize
    )

    with get_session() as session:
        record = session.get(FileRecord, file_id)
        if not record:
            raise HTTPException(status_code=404, detail="File not found")
            
    # Process sequentially for this specific file, loading status cleanly each time
    with get_session() as session:
        status = session.get(FileRecord, file_id).status
    if status == "pending":
        await run_transcription(file_id)

    with get_session() as session:
        status = session.get(FileRecord, file_id).status        
    if status == "transcribed":
        await run_translation(file_id)
        
    with get_session() as session:
        status = session.get(FileRecord, file_id).status
    if status == "translated":
        await run_summarization(file_id)
        
    with get_session() as session:
        status = session.get(FileRecord, file_id).status
    if status == "summarized":
        await run_extraction_and_finalize(file_id)

    return {"status": "complete", "file_id": str(file_id)}
```

- [ ] **Step 4: Run test to pass**
Run: `pytest tests/test_process.py -v`
Expected: PASS

### Task 4: Fix Pipeline tests

**Files:**
- Modify: `tests/test_pipeline.py`

- [ ] **Step 1: Replace `run_pipeline` imports in tests**
In `tests/test_pipeline.py`, change `from app.services.pipeline import process_pending_files, run_pipeline` to `from app.services.pipeline import process_pending_files, run_transcription`.

- [ ] **Step 2: Fix `test_pipeline_fails_cleanly_for_missing_file`**
Change `await run_pipeline(record)` to `await run_transcription(record.id)`.
Run: `pytest tests/test_pipeline.py -v`
Expected: PASS

- [ ] **Step 3: Run all tests**
Run: `pytest -v`
Expected: PASS

- [ ] **Step 4: Commit changes**
Commit: `git add . && git commit -m "feat: separate pipeline stages and horizontal batching with manual endpoint"`
