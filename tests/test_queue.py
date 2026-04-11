import asyncio
import hashlib
import uuid
from datetime import datetime, timezone

import pytest
from sqlmodel import Session, select

# Shared loop: module-level asyncio.Queue must not hop event loops between tests.
pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest.fixture(autouse=True)
def zero_queue_coalesce_debounce(monkeypatch):
    """Keep drain tests fast; debounce is for real sequential uploads only."""
    monkeypatch.setattr(
        "app.config.settings.queue_coalesce_debounce_seconds",
        0.0,
    )


from app.models import Entry, FileRecord
from app.queue import _queue, drain_queue, enqueue, get_queue_snapshot, reset_processing_queue


def _make_record(tmp_path) -> FileRecord:
    """Return a FileRecord with a nonexistent audio path (causes transcription to fail cleanly)."""
    return FileRecord(
        filename="fake.m4a",
        sha256=hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
        status="pending",
        local_path=str(tmp_path / "nonexistent.m4a"),
    )


async def test_enqueue_puts_item_on_queue(db_engine):
    """enqueue() is non-blocking and puts the file_id on the module-level queue."""
    reset_processing_queue()

    file_id = uuid.uuid4()
    assert _queue.empty()
    enqueue(file_id)
    assert _queue.qsize() == 1
    snap = get_queue_snapshot()
    assert snap["waiting_file_ids"] == [file_id]
    assert snap["current_file_id"] is None
    item = _queue.get_nowait()
    _queue.task_done()
    assert item == file_id
    reset_processing_queue()


async def test_drain_queue_processes_one_file(db_engine, db_session: Session, tmp_path):
    """drain_queue() picks up a file_id and runs the pipeline (which fails for missing file)."""
    reset_processing_queue()

    record = _make_record(tmp_path)
    db_session.add(record)
    db_session.commit()

    enqueue(record.id)

    # Run drain_queue until the queue is empty
    drain_task = asyncio.create_task(drain_queue())
    await _queue.join()  # blocks until task_done() is called for every item
    drain_task.cancel()
    try:
        await drain_task
    except asyncio.CancelledError:
        pass

    with Session(db_engine) as session:
        updated = session.get(FileRecord, record.id)
    assert updated.status == "failed"


async def test_drain_queue_continues_after_failure(db_engine, db_session: Session, tmp_path):
    """drain_queue() processes subsequent files even when one fails."""
    reset_processing_queue()

    record_a = _make_record(tmp_path)
    record_b = _make_record(tmp_path)
    db_session.add(record_a)
    db_session.add(record_b)
    db_session.commit()

    enqueue(record_a.id)
    enqueue(record_b.id)

    drain_task = asyncio.create_task(drain_queue())
    await _queue.join()
    drain_task.cancel()
    try:
        await drain_task
    except asyncio.CancelledError:
        pass

    with Session(db_engine) as session:
        a = session.get(FileRecord, record_a.id)
        b = session.get(FileRecord, record_b.id)
    assert a.status == "failed"
    assert b.status == "failed"


async def test_drain_queue_runs_horizontal_batches(
    db_engine, db_session: Session, tmp_path, monkeypatch
):
    """Coalesced drain runs all transcriptions before any LLM stage (same as /api/process)."""
    reset_processing_queue()

    async def llm_always_ready(_step: str) -> None:
        return None

    monkeypatch.setattr(
        "app.services.llm.check_llm_server_ready",
        llm_always_ready,
    )

    order: list[tuple[str, uuid.UUID]] = []

    async def stub_transcribe(fid: uuid.UUID) -> str | None:
        order.append(("transcribe", fid))
        with Session(db_engine) as session:
            r = session.get(FileRecord, fid)
            r.status = "transcribed"
            session.add(r)
            session.add(
                Entry(file_id=fid, language="en", transcription="hello")
            )
            session.commit()
        return None

    async def stub_translate(fid: uuid.UUID) -> str | None:
        order.append(("translate", fid))
        with Session(db_engine) as session:
            r = session.get(FileRecord, fid)
            e = session.exec(select(Entry).where(Entry.file_id == fid)).first()
            e.translation = "hola"
            r.status = "translated"
            session.add(e)
            session.add(r)
            session.commit()
        return None

    async def stub_summarize(fid: uuid.UUID) -> str | None:
        order.append(("summarize", fid))
        with Session(db_engine) as session:
            r = session.get(FileRecord, fid)
            e = session.exec(select(Entry).where(Entry.file_id == fid)).first()
            e.summary = "brief"
            r.status = "summarized"
            session.add(e)
            session.add(r)
            session.commit()
        return None

    async def stub_extract(fid: uuid.UUID) -> str | None:
        order.append(("extract", fid))
        with Session(db_engine) as session:
            r = session.get(FileRecord, fid)
            e = session.exec(select(Entry).where(Entry.file_id == fid)).first()
            e.extracted_json = "{}"
            r.status = "done"
            r.processed_at = datetime.now(timezone.utc)
            session.add(e)
            session.add(r)
            session.commit()
        return None

    monkeypatch.setattr("app.services.pipeline.run_transcription", stub_transcribe)
    monkeypatch.setattr("app.services.pipeline.run_translation", stub_translate)
    monkeypatch.setattr("app.services.pipeline.run_summarization", stub_summarize)
    monkeypatch.setattr(
        "app.services.pipeline.run_extraction_and_finalize", stub_extract
    )

    record_a = _make_record(tmp_path)
    record_b = _make_record(tmp_path)
    db_session.add(record_a)
    db_session.add(record_b)
    db_session.commit()

    enqueue(record_a.id)
    enqueue(record_b.id)

    drain_task = asyncio.create_task(drain_queue())
    await _queue.join()
    drain_task.cancel()
    try:
        await drain_task
    except asyncio.CancelledError:
        pass

    transcribe_idxs = [i for i, (s, _) in enumerate(order) if s == "transcribe"]
    translate_idxs = [i for i, (s, _) in enumerate(order) if s == "translate"]
    assert transcribe_idxs
    assert translate_idxs
    assert max(transcribe_idxs) < min(translate_idxs)

    summarize_idxs = [i for i, (s, _) in enumerate(order) if s == "summarize"]
    extract_idxs = [i for i, (s, _) in enumerate(order) if s == "extract"]
    assert max(translate_idxs) < min(summarize_idxs)
    assert max(summarize_idxs) < min(extract_idxs)

    with Session(db_engine) as session:
        assert session.get(FileRecord, record_a.id).status == "done"
        assert session.get(FileRecord, record_b.id).status == "done"
