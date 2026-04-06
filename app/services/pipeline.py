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
    """Process a single FileRecord through the full AI pipeline.

    State transitions:
        pending → processing  (at start)
        processing → done     (on full success)
        processing → failed   (on any exception in transcription or LLM steps)

    Nextcloud upload errors do not revert status to failed — the file is
    marked done and nextcloud_path stays None, so the cleanup job will not
    delete the local copy.

    Returns:
        None on success, error message string on failure.
    """
    from app.services import whisper_service, llm
    from app.services.nextcloud import upload_file

    file_id = record.id

    # Step 1: mark processing
    with get_session() as session:
        db_record = session.get(FileRecord, file_id)
        db_record.status = "processing"
        session.add(db_record)
        session.commit()

    try:
        # Step 2: verify file exists on disk
        local_path = record.local_path
        if not Path(local_path).exists():
            raise FileNotFoundError(f"Local file missing: {local_path}")

        # Step 3: transcribe
        transcription, language = await whisper_service.transcribe(local_path)

        # Step 4: translate (no-op if already English)
        translation = await llm.translate(transcription, language)

        # Step 5: summarize
        summary = await llm.summarize(translation)

        # Step 6: extract entities
        extracted = await llm.extract(translation)
        extracted_json_str = json.dumps(extracted, ensure_ascii=False)

        # Step 7: write Entry to DB
        with get_session() as session:
            entry = Entry(
                file_id=file_id,
                language=language,
                transcription=transcription,
                translation=translation,
                summary=summary,
                extracted_json=extracted_json_str,
            )
            session.add(entry)
            session.commit()

        # Step 8: mark done
        with get_session() as session:
            db_record = session.get(FileRecord, file_id)
            db_record.status = "done"
            db_record.processed_at = _utcnow()
            session.add(db_record)
            session.commit()

        logger.info("Pipeline complete for file %s (%s).", record.filename, file_id)

        # Step 9: Nextcloud upload (failure does not revert status)
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
                record.filename,
                exc,
            )

        return None  # success

    except Exception as exc:
        logger.error(
            "Pipeline failed for %s (%s): %s",
            record.filename,
            file_id,
            exc,
            exc_info=True,
        )
        with get_session() as session:
            db_record = session.get(FileRecord, file_id)
            db_record.status = "failed"
            db_record.processed_at = _utcnow()
            session.add(db_record)
            session.commit()
        return str(exc)


async def process_pending_files() -> dict:
    """Query all pending FileRecords and run the pipeline on each sequentially.

    Returns:
        Dict with keys: attempted, succeeded, failed, errors (list of {filename, error}).
    """
    with get_session() as session:
        statement = select(FileRecord).where(FileRecord.status == "pending")
        pending = session.exec(statement).all()

    count = len(pending)
    if count == 0:
        logger.info("No pending files to process.")
        return {"attempted": 0, "succeeded": 0, "failed": 0, "errors": []}

    logger.info("Processing %d pending file(s).", count)
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
