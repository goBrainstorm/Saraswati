import hashlib
import uuid

import pytest
from sqlmodel import Session, select

from app.models import FileRecord
from app.services.pipeline import process_pending_files, run_pipeline


def _make_record(local_path: str = "/nonexistent/path/fake.m4a") -> FileRecord:
    """Return an unsaved FileRecord with a unique sha256."""
    return FileRecord(
        filename="fake.m4a",
        sha256=hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
        status="pending",
        local_path=local_path,
    )


async def test_process_pending_returns_zero_when_empty(db_engine):
    count = await process_pending_files()
    assert count == 0


async def test_process_pending_counts_attempted(db_engine, db_session: Session):
    record = _make_record()
    db_session.add(record)
    db_session.commit()

    count = await process_pending_files()
    assert count == 1

    with Session(db_engine) as session:
        updated = session.get(FileRecord, record.id)

    assert updated.status != "pending"


async def test_pipeline_fails_cleanly_for_missing_file(db_engine, db_session: Session):
    record = _make_record()
    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)

    await run_pipeline(record)

    with Session(db_engine) as session:
        updated = session.get(FileRecord, record.id)

    assert updated.status == "failed"
    assert updated.processed_at is not None
    assert updated.status != "processing"
