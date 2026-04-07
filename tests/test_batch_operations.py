"""Tests for POST /api/status/batch-delete and POST /api/status/batch-reset."""
import uuid
from pathlib import Path

import pytest
from sqlmodel import Session, select

from app.models import Entry, FileRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_file(session: Session, sha: str, tmp_path, status: str = "done") -> FileRecord:
    f = tmp_path / f"{sha}.mp3"
    f.write_bytes(b"audio")
    rec = FileRecord(filename=f"{sha}.mp3", sha256=sha, status=status, local_path=str(f))
    session.add(rec)
    session.commit()
    session.refresh(rec)
    return rec


def _make_entry(session: Session, file_id) -> Entry:
    entry = Entry(
        file_id=file_id,
        transcription="some text",
    )
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


# ---------------------------------------------------------------------------
# batch-delete tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_batch_delete_removes_record_file_and_entry(app_client, db_engine, db_session, tmp_path):
    rec = _make_file(db_session, "sha_batch_del_1", tmp_path)
    local_path = Path(rec.local_path)
    entry = _make_entry(db_session, rec.id)
    assert local_path.exists()

    resp = await app_client.post("/api/status/batch-delete", json={"ids": [str(rec.id)]})
    assert resp.status_code == 200
    assert resp.json() == {"count": 1}

    # FileRecord gone
    with Session(db_engine) as s:
        assert s.get(FileRecord, rec.id) is None
        assert s.get(Entry, entry.id) is None

    # Physical file deleted
    assert not local_path.exists()


@pytest.mark.anyio
async def test_batch_delete_unknown_ids_silently_skipped(app_client, db_engine):
    fake_id = str(uuid.uuid4())
    resp = await app_client.post("/api/status/batch-delete", json={"ids": [fake_id]})
    assert resp.status_code == 200
    assert resp.json() == {"count": 0}


@pytest.mark.anyio
async def test_batch_delete_mixed_ids(app_client, db_engine, db_session, tmp_path):
    rec1 = _make_file(db_session, "sha_batch_mix_1", tmp_path)
    rec2 = _make_file(db_session, "sha_batch_mix_2", tmp_path)
    fake_id = str(uuid.uuid4())

    resp = await app_client.post(
        "/api/status/batch-delete",
        json={"ids": [str(rec1.id), str(rec2.id), fake_id]},
    )
    assert resp.status_code == 200
    assert resp.json() == {"count": 2}

    with Session(db_engine) as s:
        assert s.get(FileRecord, rec1.id) is None
        assert s.get(FileRecord, rec2.id) is None


# ---------------------------------------------------------------------------
# batch-reset tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_batch_reset_sets_status_and_deletes_entry(app_client, db_engine, db_session, tmp_path):
    import datetime
    rec = _make_file(db_session, "sha_batch_reset_1", tmp_path, status="done")
    # Give it a processed_at timestamp
    rec.processed_at = datetime.datetime.now(datetime.timezone.utc)
    db_session.add(rec)
    db_session.commit()
    db_session.refresh(rec)

    entry = _make_entry(db_session, rec.id)

    resp = await app_client.post("/api/status/batch-reset", json={"ids": [str(rec.id)]})
    assert resp.status_code == 200
    assert resp.json() == {"count": 1}

    with Session(db_engine) as s:
        updated = s.get(FileRecord, rec.id)
        assert updated is not None
        assert updated.status == "pending"
        assert updated.processed_at is None
        assert s.get(Entry, entry.id) is None


@pytest.mark.anyio
async def test_batch_reset_unknown_ids_silently_skipped(app_client, db_engine):
    fake_id = str(uuid.uuid4())
    resp = await app_client.post("/api/status/batch-reset", json={"ids": [fake_id]})
    assert resp.status_code == 200
    assert resp.json() == {"count": 0}
