from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import UUID

from sqlmodel import select

from app.database import get_session
from app.models import Entry, FileRecord

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def run_transcription(file_id: UUID) -> Optional[str]:
    """Stage 1: Whisper transcription. Returns error message or None on success."""
    from app.services import whisper_service

    with get_session() as session:
        db_record = session.get(FileRecord, file_id)
        if not db_record:
            return "File not found"
        if db_record.status not in ("pending", "processing"):
            return None

    with get_session() as session:
        db_record = session.get(FileRecord, file_id)
        db_record.status = "processing"
        session.add(db_record)
        session.commit()

    try:
        with get_session() as session:
            db_record = session.get(FileRecord, file_id)
            local_path = db_record.local_path
            filename = db_record.filename

        if not Path(local_path).exists():
            raise FileNotFoundError(f"Local file missing: {local_path}")

        transcription, language = await whisper_service.transcribe(local_path)
        with get_session() as session:
            entry = Entry(
                file_id=file_id,
                language=language,
                transcription=transcription,
            )
            session.add(entry)
            session.commit()
        with get_session() as session:
            db_record = session.get(FileRecord, file_id)
            db_record.status = "transcribed"
            session.add(db_record)
            session.commit()
        logger.info(
            "Transcribed %s: lang=%s, %d chars.",
            filename, language, len(transcription),
        )
        return None

    except Exception as exc:
        logger.error(
            "Pipeline failed for file_id=%s: %s",
            file_id, exc, exc_info=True,
        )
        with get_session() as session:
            db_record = session.get(FileRecord, file_id)
            if db_record:
                db_record.status = "failed"
                db_record.processed_at = _utcnow()
                session.add(db_record)
                session.commit()
        return str(exc)


async def run_translation(file_id: UUID) -> Optional[str]:
    """Stage 2: LLM translation. Returns error message or None on success."""
    from app.services import llm

    with get_session() as session:
        db_record = session.get(FileRecord, file_id)
        if not db_record:
            return "File not found"
        if db_record.status != "transcribed":
            return None
        filename = db_record.filename
        existing = session.exec(
            select(Entry).where(Entry.file_id == file_id)
        ).first()
        if not existing:
            return "Entry not found"
        entry_id = existing.id
        transcription = existing.transcription
        language = existing.language
        translation = existing.translation

    if translation:
        return None

    try:
        # TODO: Check token count > 4096 here before translation
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
        return None
    except Exception as exc:
        logger.warning(
            "Translation failed for %s (%s): %s. Will retry next run.",
            filename, file_id, exc,
        )
        return str(exc)


async def run_summarization(file_id: UUID) -> Optional[str]:
    """Stage 3: LLM summarization. Returns error message or None on success."""
    from app.services import llm

    with get_session() as session:
        db_record = session.get(FileRecord, file_id)
        if not db_record:
            return "File not found"
        if db_record.status != "translated":
            return None
        filename = db_record.filename
        existing = session.exec(
            select(Entry).where(Entry.file_id == file_id)
        ).first()
        if not existing:
            return "Entry not found"
        entry_id = existing.id
        transcription = existing.transcription
        translation = existing.translation
        summary = existing.summary

    if summary:
        return None

    try:
        # TODO: Check token count > 4096 here before summarization
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
        return None
    except Exception as exc:
        logger.warning(
            "Summarize failed for %s (%s): %s. Will retry next run.",
            filename, file_id, exc,
        )
        return str(exc)


async def run_extraction_and_finalize(file_id: UUID) -> Optional[str]:
    """Stages 4–6: extract, embed, mark done. Returns error or None."""
    from app.services import llm

    with get_session() as session:
        db_record = session.get(FileRecord, file_id)
        if not db_record:
            return "File not found"
        if db_record.status != "summarized":
            return None
        filename = db_record.filename
        existing = session.exec(
            select(Entry).where(Entry.file_id == file_id)
        ).first()
        if not existing:
            return "Entry not found"
        entry_id = existing.id
        transcription = existing.transcription
        translation = existing.translation
        extracted_json_str = existing.extracted_json

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
                filename, file_id, exc,
            )
            return str(exc)

    try:
        from app.services.embedder import upsert_entry
        with get_session() as session:
            entry_obj = session.get(Entry, entry_id)
            record_obj = session.get(FileRecord, file_id)
        qdrant_id = await upsert_entry(entry_obj, record_obj.filename)
        with get_session() as session:
            e = session.get(Entry, entry_id)
            e.qdrant_id = qdrant_id
            session.add(e)
            session.commit()
    except Exception as exc:
        logger.warning(
            "Qdrant upsert failed for %s: %s. Entry stored in SQLite without embedding.",
            filename, exc,
        )

    with get_session() as session:
        db_record = session.get(FileRecord, file_id)
        db_record.status = "done"
        db_record.processed_at = _utcnow()
        session.add(db_record)
        session.commit()

    logger.info("Pipeline complete for %s (%s).", filename, file_id)
    return None


async def process_pending_files(emit_sse: bool = False) -> dict:
    """Run pipeline in horizontal batches; each stage processes all eligible files.

    When ``emit_sse`` is True (e.g. queue drain), broadcast stage events compatible with
    :func:`app.queue.drain_queue` / the status SSE stream.

    Returns:
        Dict with keys: attempted, succeeded, failed, errors (list of {filename, error}).
    """
    if emit_sse:
        from app.sse import emit as sse_emit
    else:

        def sse_emit(_fid: UUID, _payload: dict) -> None:  # type: ignore[misc]
            pass

    with get_session() as session:
        pending = session.exec(
            select(FileRecord).where(FileRecord.status == "pending")
        ).all()
        pending_ids = [r.id for r in pending]
    with get_session() as session:
        transcribed = session.exec(
            select(FileRecord).where(FileRecord.status == "transcribed")
        ).all()
        transcribed_ids = [r.id for r in transcribed]
    with get_session() as session:
        translated = session.exec(
            select(FileRecord).where(FileRecord.status == "translated")
        ).all()
        translated_ids = [r.id for r in translated]
    with get_session() as session:
        summarized = session.exec(
            select(FileRecord).where(FileRecord.status == "summarized")
        ).all()
        summarized_ids = [r.id for r in summarized]

    if not (pending_ids or transcribed_ids or translated_ids or summarized_ids):
        logger.info("No pending files to process.")
        return {"attempted": 0, "succeeded": 0, "failed": 0, "errors": []}

    total = (
        len(pending_ids)
        + len(transcribed_ids)
        + len(translated_ids)
        + len(summarized_ids)
    )
    logger.info(
        "Processing batches: pending=%d transcribed=%d translated=%d summarized=%d (total=%d).",
        len(pending_ids),
        len(transcribed_ids),
        len(translated_ids),
        len(summarized_ids),
        total,
    )

    succeeded = 0
    failed = 0
    errors: list = []
    attempted_ids: set[UUID] = set()

    for fid in pending_ids:
        attempted_ids.add(fid)
        sse_emit(fid, {"stage": "transcribe", "status": "start"})
        error = await run_transcription(fid)
        if error:
            sse_emit(fid, {"stage": "transcribe", "status": "failed", "error": error})
            errors.append({"filename": str(fid), "error": error})
            failed += 1
        else:
            sse_emit(fid, {"stage": "transcribe", "status": "done"})
            succeeded += 1

    with get_session() as session:
        transcribed = session.exec(
            select(FileRecord).where(FileRecord.status == "transcribed")
        ).all()
        transcribed_ids = [r.id for r in transcribed]

    from app.services.llm import check_llm_server_ready

    llm_probe = await check_llm_server_ready("translate")
    if llm_probe:
        logger.warning(
            "Translate server probe: %s — running translation for %d file(s) anyway.",
            llm_probe,
            len(transcribed_ids),
        )
    for fid in transcribed_ids:
        attempted_ids.add(fid)
        sse_emit(fid, {"stage": "translate", "status": "start"})
        error = await run_translation(fid)
        if error:
            sse_emit(fid, {"stage": "translate", "status": "failed", "error": error})
            errors.append({"filename": str(fid), "error": error})
            failed += 1
        else:
            sse_emit(fid, {"stage": "translate", "status": "done"})
            succeeded += 1

    with get_session() as session:
        translated = session.exec(
            select(FileRecord).where(FileRecord.status == "translated")
        ).all()
        translated_ids = [r.id for r in translated]

    llm_probe = await check_llm_server_ready("summarize")
    if llm_probe:
        logger.warning(
            "Summarize server probe: %s — running summarization for %d file(s) anyway.",
            llm_probe,
            len(translated_ids),
        )
    for fid in translated_ids:
        attempted_ids.add(fid)
        sse_emit(fid, {"stage": "summarize", "status": "start"})
        error = await run_summarization(fid)
        if error:
            sse_emit(fid, {"stage": "summarize", "status": "failed", "error": error})
            errors.append({"filename": str(fid), "error": error})
            failed += 1
        else:
            sse_emit(fid, {"stage": "summarize", "status": "done"})
            succeeded += 1

    with get_session() as session:
        summarized = session.exec(
            select(FileRecord).where(FileRecord.status == "summarized")
        ).all()
        summarized_ids = [r.id for r in summarized]

    llm_probe = await check_llm_server_ready("extract")
    if llm_probe:
        logger.warning(
            "Extract server probe: %s — running extraction/finalize for %d file(s) anyway.",
            llm_probe,
            len(summarized_ids),
        )
    for fid in summarized_ids:
        attempted_ids.add(fid)
        sse_emit(fid, {"stage": "extract", "status": "start"})
        error = await run_extraction_and_finalize(fid)
        if error:
            sse_emit(fid, {"stage": "extract", "status": "failed", "error": error})
            errors.append({"filename": str(fid), "error": error})
            failed += 1
        else:
            sse_emit(fid, {"stage": "extract", "status": "done"})
            sse_emit(fid, {"stage": "pipeline", "status": "complete"})
            succeeded += 1

    return {
        "attempted": len(attempted_ids),
        "succeeded": succeeded,
        "failed": failed,
        "errors": errors,
    }
