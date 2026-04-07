"""Tests for DELETE entry action endpoints in /api/entries/{id}/..."""
import uuid
from pathlib import Path

import pytest
from sqlmodel import Session

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


def _make_entry(
    session: Session,
    file_id,
    transcription: str = "hello",
    translation: str = "hello",
    summary: str = "a summary",
    extracted_json: str | None = None,
) -> Entry:
    entry = Entry(
        file_id=file_id,
        transcription=transcription,
        translation=translation,
        summary=summary,
        extracted_json=extracted_json,
    )
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


# ---------------------------------------------------------------------------
# DELETE /api/entries/{id}
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_delete_entry_removes_row_and_resets_file(app_client, db_engine, db_session, tmp_path):
    rec = _make_file(db_session, "sha_del_entry_1", tmp_path, status="done")
    entry = _make_entry(db_session, rec.id)

    resp = await app_client.delete(f"/api/entries/{entry.id}")
    assert resp.status_code == 200

    with Session(db_engine) as s:
        assert s.get(Entry, entry.id) is None
        updated = s.get(FileRecord, rec.id)
        assert updated is not None
        assert updated.status == "pending"


@pytest.mark.anyio
async def test_delete_entry_404_for_unknown(app_client, db_engine):
    resp = await app_client.delete(f"/api/entries/{uuid.uuid4()}")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/entries/{id}/transcription
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_delete_transcription_removes_entry_and_resets_file(app_client, db_engine, db_session, tmp_path):
    rec = _make_file(db_session, "sha_del_transcription_1", tmp_path, status="done")
    entry = _make_entry(db_session, rec.id)

    resp = await app_client.delete(f"/api/entries/{entry.id}/transcription")
    assert resp.status_code == 200

    with Session(db_engine) as s:
        assert s.get(Entry, entry.id) is None
        updated = s.get(FileRecord, rec.id)
        assert updated is not None
        assert updated.status == "pending"


# ---------------------------------------------------------------------------
# DELETE /api/entries/{id}/translation
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_clear_translation_nulls_field_reverts_status(app_client, db_engine, db_session, tmp_path):
    rec = _make_file(db_session, "sha_del_translation_1", tmp_path, status="done")
    entry = _make_entry(db_session, rec.id, translation="bonjour")

    resp = await app_client.delete(f"/api/entries/{entry.id}/translation")
    assert resp.status_code == 200

    with Session(db_engine) as s:
        updated_entry = s.get(Entry, entry.id)
        assert updated_entry is not None
        assert updated_entry.translation is None
        updated_file = s.get(FileRecord, rec.id)
        assert updated_file is not None
        assert updated_file.status == "transcribed"


# ---------------------------------------------------------------------------
# DELETE /api/entries/{id}/summary
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_clear_summary_nulls_field_reverts_status(app_client, db_engine, db_session, tmp_path):
    rec = _make_file(db_session, "sha_del_summary_1", tmp_path, status="done")
    entry = _make_entry(db_session, rec.id, summary="some summary")

    resp = await app_client.delete(f"/api/entries/{entry.id}/summary")
    assert resp.status_code == 200

    with Session(db_engine) as s:
        updated_entry = s.get(Entry, entry.id)
        assert updated_entry is not None
        assert updated_entry.summary is None
        updated_file = s.get(FileRecord, rec.id)
        assert updated_file is not None
        assert updated_file.status == "translated"


# ---------------------------------------------------------------------------
# DELETE /api/entries/{id}/extracted_json
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_clear_extracted_json_nulls_field_reverts_status(app_client, db_engine, db_session, tmp_path):
    rec = _make_file(db_session, "sha_del_json_1", tmp_path, status="done")
    entry = _make_entry(db_session, rec.id, extracted_json='{"key": "value"}')

    resp = await app_client.delete(f"/api/entries/{entry.id}/extracted_json")
    assert resp.status_code == 200

    with Session(db_engine) as s:
        updated_entry = s.get(Entry, entry.id)
        assert updated_entry is not None
        assert updated_entry.extracted_json is None
        updated_file = s.get(FileRecord, rec.id)
        assert updated_file is not None
        assert updated_file.status == "summarized"


# ---------------------------------------------------------------------------
# 404 for unknown entry on field clear
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_clear_field_404_for_unknown(app_client, db_engine):
    resp = await app_client.delete(f"/api/entries/{uuid.uuid4()}/translation")
    assert resp.status_code == 404
