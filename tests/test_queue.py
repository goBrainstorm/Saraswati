import asyncio
import hashlib
import uuid

import pytest
from sqlmodel import Session

# Shared loop: module-level asyncio.Queue must not hop event loops between tests.
pytestmark = pytest.mark.asyncio(loop_scope="module")

from app.models import FileRecord
from app.queue import _queue, drain_queue, enqueue


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
    # Drain any pre-existing items from prior test runs
    while not _queue.empty():
        _queue.get_nowait()
        _queue.task_done()

    file_id = uuid.uuid4()
    assert _queue.empty()
    enqueue(file_id)
    assert _queue.qsize() == 1
    item = _queue.get_nowait()
    _queue.task_done()
    assert item == file_id


async def test_drain_queue_processes_one_file(db_engine, db_session: Session, tmp_path):
    """drain_queue() picks up a file_id and runs the pipeline (which fails for missing file)."""
    while not _queue.empty():
        _queue.get_nowait()
        _queue.task_done()

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
    while not _queue.empty():
        _queue.get_nowait()
        _queue.task_done()

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
