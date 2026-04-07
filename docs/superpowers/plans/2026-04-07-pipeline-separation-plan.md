# Pipeline Separation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the pipeline to process files in horizontal batches (transcribe all, then translate all, etc.) and add a manual endpoint for immediate single-file processing.

**Architecture:** Split the monolithic `run_pipeline` into individual stage functions. Update `process_pending_files` to query and process each stage across all applicable files. Add `POST /api/process/{file_id}` for manual override.

**Tech Stack:** FastAPI, SQLModel, pytest

---

### Task 1: Split pipeline into stage functions

**Files:**
- Modify: `app/services/pipeline.py`

- [ ] **Step 1: Extract `run_transcription`**
Create a new async function `run_transcription(record: FileRecord) -> Optional[str]` in `app/services/pipeline.py` containing the Stage 1 logic (transcribe) from the existing `run_pipeline`. Be sure to update `record.status` to `"transcribed"` (or `"failed"`) and create the `Entry`.

- [ ] **Step 2: Extract `run_translation`**
Create `run_translation(record: FileRecord, entry_id: uuid.UUID) -> Optional[str]` containing Stage 2 logic. Add a comment `# TODO: Check token count > 4096 here before translation` before calling `llm.translate`. Set status to `"translated"`.

- [ ] **Step 3: Extract `run_summarization`**
Create `run_summarization(record: FileRecord, entry_id: uuid.UUID) -> Optional[str]` containing Stage 3 logic. Add a comment `# TODO: Check token count > 4096 here before summarization` before calling `llm.summarize`. Set status to `"summarized"`.

- [ ] **Step 4: Extract `run_extraction_and_finalize`**
Create `run_extraction_and_finalize(record: FileRecord, entry_id: uuid.UUID) -> Optional[str]` containing Stages 4, 5, and 6 (extract, embed, Nextcloud). Set status to `"done"`.

### Task 2: Refactor `process_pending_files`

**Files:**
- Modify: `app/services/pipeline.py`

- [ ] **Step 1: Update `process_pending_files` logic**
Rewrite `process_pending_files` to run in horizontal batches.
```python
    succeeded = 0
    failed = 0
    errors = []
    
    with get_session() as session:
        pending = session.exec(select(FileRecord).where(FileRecord.status == "pending")).all()
    for record in pending:
        # call run_transcription
        # update counts

    with get_session() as session:
        transcribed = session.exec(select(FileRecord).where(FileRecord.status == "transcribed")).all()
    for record in transcribed:
        # lookup entry_id
        # call run_translation
        # update counts
        
    with get_session() as session:
        translated = session.exec(select(FileRecord).where(FileRecord.status == "translated")).all()
    for record in translated:
        # lookup entry_id
        # call run_summarization
        # update counts
        
    with get_session() as session:
        summarized = session.exec(select(FileRecord).where(FileRecord.status == "summarized")).all()
    for record in summarized:
        # lookup entry_id
        # call run_extraction_and_finalize
        # update counts

    return {"attempted": sum([...]), "succeeded": succeeded, "failed": failed, "errors": errors}
```
*(Remove the old `run_pipeline` function completely).*

- [ ] **Step 2: Check syntax and basic logic**
Ensure it type-checks and imports are correct. 

### Task 3: Implement single-file manual endpoint

**Files:**
- Modify: `app/routes/process.py`

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
Add the endpoint in `app/routes/process.py`:
```python
from uuid import UUID
from fastapi import HTTPException
from app.database import get_session
from app.models import FileRecord

@router.post("/api/process/{file_id}")
async def trigger_process_single(file_id: UUID) -> Dict[str, Any]:
    from app.services.pipeline import (
        run_transcription, run_translation, run_summarization, run_extraction_and_finalize
    )
    from sqlmodel import select
    from app.models import Entry

    with get_session() as session:
        record = session.get(FileRecord, file_id)
        if not record:
            raise HTTPException(status_code=404, detail="File not found")
            
    # Process sequentially for this specific file
    if record.status == "pending":
        await run_transcription(record)
        with get_session() as session:
            record = session.get(FileRecord, file_id)
            
    if record.status == "transcribed":
        with get_session() as session:
            entry = session.exec(select(Entry).where(Entry.file_id == file_id)).first()
        if entry:
            await run_translation(record, entry.id)
        with get_session() as session:
            record = session.get(FileRecord, file_id)
            
    if record.status == "translated":
        with get_session() as session:
            entry = session.exec(select(Entry).where(Entry.file_id == file_id)).first()
        if entry:
            await run_summarization(record, entry.id)
        with get_session() as session:
            record = session.get(FileRecord, file_id)
            
    if record.status == "summarized":
        with get_session() as session:
            entry = session.exec(select(Entry).where(Entry.file_id == file_id)).first()
        if entry:
            await run_extraction_and_finalize(record, entry.id)

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
Change `await run_pipeline(record)` to `await run_transcription(record)`.
Run: `pytest tests/test_pipeline.py -v`
Expected: PASS

- [ ] **Step 3: Run all tests**
Run: `pytest -v`
Expected: PASS

- [ ] **Step 4: Commit changes**
Commit: `git add . && git commit -m "feat: separate pipeline stages and horizontal batching"`
