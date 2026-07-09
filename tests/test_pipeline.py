import hashlib
import uuid

import pytest
from sqlmodel import Session, select

from app.models import Entry, FileRecord
from app.services.pipeline import (
    process_pending_files,
    reset_stuck_processing,
    run_transcription,
)


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


def test_reset_stuck_processing(db_engine, db_session: Session):
    stuck = _make_record()
    stuck.status = "processing"
    other = _make_record()
    other.status = "done"
    db_session.add(stuck)
    db_session.add(other)
    db_session.commit()
    db_session.refresh(stuck)
    db_session.refresh(other)

    count = reset_stuck_processing()

    assert count == 1
    with Session(db_engine) as session:
        assert session.get(FileRecord, stuck.id).status == "pending"
        assert session.get(FileRecord, other.id).status == "done"


async def test_run_transcription_does_not_duplicate_entry(
    db_engine, db_session: Session, tmp_path, monkeypatch
):
    from app.services import whisper_service

    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"not-real-audio")
    record = _make_record(local_path=str(audio))
    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)

    async def fake_transcribe(_path: str):
        return ("hello world", "en")

    monkeypatch.setattr(whisper_service, "transcribe", fake_transcribe)

    await run_transcription(record.id)

    # Force a re-run (e.g. after a reset) and ensure no second Entry is created.
    with Session(db_engine) as session:
        r = session.get(FileRecord, record.id)
        r.status = "pending"
        session.add(r)
        session.commit()

    await run_transcription(record.id)

    with Session(db_engine) as session:
        entries = session.exec(
            select(Entry).where(Entry.file_id == record.id)
        ).all()
    assert len(entries) == 1
