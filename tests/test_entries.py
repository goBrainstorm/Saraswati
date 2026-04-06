"""Tests for /api/entries and /api/status/{file_id} endpoints."""
import uuid

import pytest
from sqlmodel import Session

from app.models import Entry, FileRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_file(session: Session, sha: str, tmp_path) -> FileRecord:
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
        language="en",
        transcription="hello",
        translation="hello",
        summary=summary,
    )
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


# ---------------------------------------------------------------------------
# /api/entries tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_entries_empty(app_client, db_engine):
    resp = await app_client.get("/api/entries")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.anyio
async def test_entries_returns_entry(app_client, db_engine, db_session, tmp_path):
    rec = _make_file(db_session, "sha_entry_one", tmp_path)
    _make_entry(db_session, rec.id, summary="my summary")

    resp = await app_client.get("/api/entries")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["summary"] == "my summary"
    assert data[0]["language"] == "en"


@pytest.mark.anyio
async def test_entries_pagination(app_client, db_engine, db_session, tmp_path):
    for i in range(3):
        rec = _make_file(db_session, f"sha_page_{i}", tmp_path)
        _make_entry(db_session, rec.id, summary=f"summary {i}")

    resp_first = await app_client.get("/api/entries?limit=2&offset=0")
    assert resp_first.status_code == 200
    assert len(resp_first.json()) == 2

    resp_second = await app_client.get("/api/entries?limit=2&offset=2")
    assert resp_second.status_code == 200
    assert len(resp_second.json()) == 1


# ---------------------------------------------------------------------------
# /api/status/{file_id} tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_status_detail_includes_entry(app_client, db_engine, db_session, tmp_path):
    rec = _make_file(db_session, "sha_detail_with_entry", tmp_path)
    _make_entry(db_session, rec.id, summary="detail summary")

    resp = await app_client.get(f"/api/status/{rec.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["file"]["id"] == str(rec.id)
    assert data["entry"]["summary"] == "detail summary"


@pytest.mark.anyio
async def test_status_detail_no_entry(app_client, db_engine, db_session, tmp_path):
    rec = _make_file(db_session, "sha_detail_no_entry", tmp_path)

    resp = await app_client.get(f"/api/status/{rec.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["file"]["id"] == str(rec.id)
    assert data["entry"] is None


@pytest.mark.anyio
async def test_status_detail_404(app_client, db_engine):
    resp = await app_client.get(f"/api/status/{uuid.uuid4()}")
    assert resp.status_code == 404
