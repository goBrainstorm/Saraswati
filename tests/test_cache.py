"""Tests for app/services/cache.py — write_recent_cache()."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlmodel import Session

from app.models import Entry, FileRecord
from app.services.cache import write_recent_cache


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_file_record(session: Session, filename: str = "test.m4a") -> FileRecord:
    record = FileRecord(
        filename=filename,
        sha256=uuid.uuid4().hex,
        status="done",
        local_path=f"/tmp/{filename}",
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def _make_entry(
    session: Session,
    file_id,
    *,
    created_at: datetime | None = None,
    transcription: str = "hello world",
    extracted_json: str | None = None,
) -> Entry:
    entry = Entry(
        file_id=file_id,
        transcription=transcription,
        extracted_json=extracted_json,
    )
    if created_at is not None:
        entry.created_at = created_at
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_cache_empty_db(db_engine, db_session, tmp_path, monkeypatch):
    """Empty DB → write_recent_cache() returns 0 and writes an empty JSON array."""
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr("app.config.settings.cache_dir", str(cache_dir))

    count = await write_recent_cache()

    assert count == 0
    final = cache_dir / "recent.json"
    assert final.exists()
    assert json.loads(final.read_text()) == []


async def test_cache_includes_recent_entries(db_engine, db_session, tmp_path, monkeypatch):
    """Entry created 1 day ago is included; count=1 and JSON has correct fields."""
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr("app.config.settings.cache_dir", str(cache_dir))

    record = _make_file_record(db_session, filename="audio.m4a")
    just_within_cutoff = datetime.now(timezone.utc) - timedelta(days=6, hours=23, minutes=59)
    entry = _make_entry(db_session, record.id, created_at=just_within_cutoff, transcription="recent text")

    count = await write_recent_cache()

    assert count == 1
    rows = json.loads((cache_dir / "recent.json").read_text())
    assert len(rows) == 1
    row = rows[0]
    assert row["transcription"] == "recent text"
    assert row["filename"] == "audio.m4a"
    assert str(entry.id) == row["id"]


async def test_cache_excludes_old_entries(db_engine, db_session, tmp_path, monkeypatch):
    """Entry created 8 days ago is excluded; count=0 and JSON array is empty."""
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr("app.config.settings.cache_dir", str(cache_dir))

    record = _make_file_record(db_session, filename="old.m4a")
    just_over_cutoff = datetime.now(timezone.utc) - timedelta(days=7, seconds=1)
    _make_entry(db_session, record.id, created_at=just_over_cutoff, transcription="old text")

    count = await write_recent_cache()

    assert count == 0
    rows = json.loads((cache_dir / "recent.json").read_text())
    assert rows == []


async def test_cache_atomic_write_leaves_no_tmp(db_engine, db_session, tmp_path, monkeypatch):
    """After a successful write, recent.json exists and recent.json.tmp does not."""
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr("app.config.settings.cache_dir", str(cache_dir))

    record = _make_file_record(db_session)
    one_day_ago = datetime.now(timezone.utc) - timedelta(days=1)
    _make_entry(db_session, record.id, created_at=one_day_ago)

    await write_recent_cache()

    assert (cache_dir / "recent.json").exists()
    assert not (cache_dir / "recent.json.tmp").exists()


async def test_cache_extracted_json_parsed(db_engine, db_session, tmp_path, monkeypatch):
    """Entry with extracted_json string → cache row's `extracted` field is a dict."""
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr("app.config.settings.cache_dir", str(cache_dir))

    record = _make_file_record(db_session)
    one_day_ago = datetime.now(timezone.utc) - timedelta(days=1)
    payload = {"key": "value", "number": 42}
    _make_entry(
        db_session,
        record.id,
        created_at=one_day_ago,
        extracted_json=json.dumps(payload),
    )

    await write_recent_cache()

    rows = json.loads((cache_dir / "recent.json").read_text())
    assert len(rows) == 1
    assert rows[0]["extracted"] == payload
