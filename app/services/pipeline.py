from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlmodel import select

from app.database import get_session
from app.models import Entry, FileRecord

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def run_pipeline(record: FileRecord) -> Optional[str]:
    """Process a single FileRecord through the AI pipeline.

    Each stage is independent: failures in later stages do not discard progress
    from earlier stages. The status field tracks how far processing has reached:

        pending     → Whisper not yet run
        processing  → currently running (transient)
        transcribed → Whisper done; Entry created
        translated  → LLM translation done
        summarized  → LLM summarize done
        done        → entity extraction done; pipeline complete
        failed      → Whisper failed (no Entry)

    On each run the pipeline resumes from the current status, so interrupted
    runs are retried incrementally on the next call.
    """
    from app.services import whisper_service, llm
    from app.services.nextcloud import upload_file

    file_id = record.id

    # Mark processing
    with get_session() as session:
        db_record = session.get(FileRecord, file_id)
        db_record.status = "processing"
        session.add(db_record)
        session.commit()

    try:
        local_path = record.local_path
        if not Path(local_path).exists():
            raise FileNotFoundError(f"Local file missing: {local_path}")

        # Load existing Entry (present when resuming a transcribed/translated/summarized file)
        with get_session() as session:
            existing = session.exec(
                select(Entry).where(Entry.file_id == file_id)
            ).first()
            entry_id: Optional[object] = existing.id if existing else None
            transcription: Optional[str] = existing.transcription if existing else None
            language: Optional[str] = existing.language if existing else None
            translation: Optional[str] = existing.translation if existing else None
            summary: Optional[str] = existing.summary if existing else None
            extracted_json_str: Optional[str] = existing.extracted_json if existing else None

        # ── Stage 1: Transcribe ───────────────────────────────────────────────
        if not transcription:
            transcription, language = await whisper_service.transcribe(local_path)
            with get_session() as session:
                entry = Entry(
                    file_id=file_id,
                    language=language,
                    transcription=transcription,
                )
                session.add(entry)
                session.commit()
                session.refresh(entry)
                entry_id = entry.id
            with get_session() as session:
                db_record = session.get(FileRecord, file_id)
                db_record.status = "transcribed"
                session.add(db_record)
                session.commit()
            logger.info(
                "Transcribed %s: lang=%s, %d chars.",
                record.filename, language, len(transcription),
            )

        # ── Stage 2: Translate ────────────────────────────────────────────────
        if not translation:
            try:
                translation = await llm.translate(transcription, language)
                with get_session() as session:
                    e = session.get(Entry, entry_id)
                    e.translation = translation
                    session.add(e)
                    session.commit()
                with get_session() as session:
                    db_record = session.get(FileRecord, file_id)
                    db_record.status = "translated"
                    session.add(db_record)
                    session.commit()
            except Exception as exc:
                logger.warning(
                    "Translation failed for %s (%s): %s. Will retry next run.",
                    record.filename, file_id, exc,
                )
                return None  # transcription saved; retry next run

        # ── Stage 3: Summarize ────────────────────────────────────────────────
        if not summary:
            try:
                text = translation or transcription
                summary = await llm.summarize(text)
                with get_session() as session:
                    e = session.get(Entry, entry_id)
                    e.summary = summary
                    session.add(e)
                    session.commit()
                with get_session() as session:
                    db_record = session.get(FileRecord, file_id)
                    db_record.status = "summarized"
                    session.add(db_record)
                    session.commit()
            except Exception as exc:
                logger.warning(
                    "Summarize failed for %s (%s): %s. Will retry next run.",
                    record.filename, file_id, exc,
                )
                return None  # translation saved; retry next run

        # ── Stage 4: Extract entities ─────────────────────────────────────────
        if not extracted_json_str:
            try:
                text = translation or transcription
                extracted = await llm.extract(text)
                extracted_json_str = json.dumps(extracted, ensure_ascii=False)
                with get_session() as session:
                    e = session.get(Entry, entry_id)
                    e.extracted_json = extracted_json_str
                    session.add(e)
                    session.commit()
            except Exception as exc:
                logger.warning(
                    "Extraction failed for %s (%s): %s. Will retry next run.",
                    record.filename, file_id, exc,
                )
                return None  # summary saved; retry next run

        # ── Stage 5: Embed and upsert to Qdrant (non-fatal) ──────────────────
        try:
            from app.services.embedder import upsert_entry
            with get_session() as session:
                entry_obj = session.get(Entry, entry_id)
            qdrant_id = await upsert_entry(entry_obj, record.filename)
            with get_session() as session:
                e = session.get(Entry, entry_id)
                e.qdrant_id = qdrant_id
                session.add(e)
                session.commit()
        except Exception as exc:
            logger.warning(
                "Qdrant upsert failed for %s: %s. Entry stored in SQLite without embedding.",
                record.filename, exc,
            )

        # ── Mark done ─────────────────────────────────────────────────────────
        with get_session() as session:
            db_record = session.get(FileRecord, file_id)
            db_record.status = "done"
            db_record.processed_at = _utcnow()
            session.add(db_record)
            session.commit()

        logger.info("Pipeline complete for %s (%s).", record.filename, file_id)

        # ── Stage 6: Nextcloud upload (non-fatal) ─────────────────────────────
        try:
            remote_path = await upload_file(local_path, record.filename)
            if remote_path:
                with get_session() as session:
                    db_record = session.get(FileRecord, file_id)
                    db_record.nextcloud_path = remote_path
                    session.add(db_record)
                    session.commit()
        except Exception as exc:
            logger.warning(
                "Nextcloud upload failed for %s: %s. File stays local.",
                record.filename, exc,
            )

        return None  # success

    except Exception as exc:
        logger.error(
            "Pipeline failed for %s (%s): %s",
            record.filename, file_id, exc, exc_info=True,
        )
        with get_session() as session:
            db_record = session.get(FileRecord, file_id)
            db_record.status = "failed"
            db_record.processed_at = _utcnow()
            session.add(db_record)
            session.commit()
        return str(exc)


async def process_pending_files() -> dict:
    """Query all resumable FileRecords and run the pipeline on each sequentially.

    Picks up files at any intermediate status so interrupted pipelines are
    retried automatically.

    Returns:
        Dict with keys: attempted, succeeded, failed, errors (list of {filename, error}).
    """
    with get_session() as session:
        statement = select(FileRecord).where(
            FileRecord.status.in_(  # type: ignore[attr-defined]
                ["pending", "transcribed", "translated", "summarized"]
            )
        )
        pending = session.exec(statement).all()

    count = len(pending)
    if count == 0:
        logger.info("No pending files to process.")
        return {"attempted": 0, "succeeded": 0, "failed": 0, "errors": []}

    logger.info("Processing %d file(s).", count)
    succeeded = 0
    failed = 0
    errors: list = []
    for record in pending:
        error = await run_pipeline(record)
        if error is None:
            succeeded += 1
        else:
            failed += 1
            errors.append({"filename": record.filename, "error": error})

    return {"attempted": count, "succeeded": succeeded, "failed": failed, "errors": errors}
