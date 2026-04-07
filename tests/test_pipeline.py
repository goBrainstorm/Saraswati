import hashlib
import uuid

import pytest
from sqlmodel import Session

from app.models import FileRecord
from app.services.pipeline import process_pending_files, run_transcription


def _make_record(local_path: str = "/nonexistent/path/fake.m4a") -> FileRecord:
    """Return an unsaved FileRecord with a unique sha256."""
    return FileRecord(
        filename="fake.m4a",
        sha256=hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
        status="pending",
        local_path=local_path,
    )


async def test_process_pending_returns_zero_when_empty(db_engine):
    result = await process_pending_files()
    assert result["attempted"] == 0
    assert result["succeeded"] == 0
    assert result["failed"] == 0
    assert result["errors"] == []


async def test_process_pending_counts_attempted(db_engine, db_session: Session):
    record = _make_record()
    db_session.add(record)
    db_session.commit()

    result = await process_pending_files()
    assert result["attempted"] == 1
    assert result["failed"] == 1
    assert result["succeeded"] == 0
    assert len(result["errors"]) == 1

    with Session(db_engine) as session:
        updated = session.get(FileRecord, record.id)

    assert updated.status == "failed"


async def test_pipeline_fails_cleanly_for_missing_file(db_engine, db_session: Session):
    record = _make_record()
    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)

    await run_transcription(record.id)

    with Session(db_engine) as session:
        updated = session.get(FileRecord, record.id)

    assert updated.status == "failed"
    assert updated.processed_at is not None
    assert updated.status != "processing"
