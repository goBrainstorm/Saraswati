import hashlib
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Optional

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from sqlmodel import select

from app import queue as _queue_module
from app.config import settings
from app.database import get_session
from app.models import FileRecord
from app.services.audio_metadata import read_embedded_recording_datetime_from_bytes

logger = logging.getLogger(__name__)

router = APIRouter()


def _first_non_empty(*vals: Optional[str]) -> Optional[str]:
    for v in vals:
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return None


def _parse_source_last_modified_ms(raw: Optional[str]) -> Optional[datetime]:
    """Parse JavaScript File.lastModified (milliseconds since Unix epoch, UTC)."""
    if raw is None:
        return None
    s = raw.strip()
    if not s or s.lower() in ("undefined", "null", "nan"):
        return None
    try:
        ms = int(s)
    except ValueError:
        return None
    if ms < 0:
        return None
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)


@router.post("/api/upload", response_model=FileRecord)
async def upload_file(
    file: Annotated[UploadFile, File()],
    source_last_modified_ms: Annotated[Optional[str], Form()] = None,
    x_source_last_modified_ms: Annotated[
        Optional[str], Header(alias="X-Source-Last-Modified-Ms")
    ] = None,
) -> FileRecord:
    """Accept a multipart audio file upload.

    - Computes SHA-256 of the raw bytes for deduplication.
    - Returns HTTP 409 if the same content was already uploaded.
    - Saves file to INPUT_DIR and creates a FileRecord with status='pending'.
    """
    raw = await file.read()

    # Compute SHA-256
    sha256 = hashlib.sha256(raw).hexdigest()

    # Deduplication check
    with get_session() as session:
        existing = session.exec(
            select(FileRecord).where(FileRecord.sha256 == sha256)
        ).first()

        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "File with identical content already exists.",
                    "existing": {
                        "id": str(existing.id),
                        "filename": existing.filename,
                        "status": existing.status,
                        "uploaded_at": existing.uploaded_at.isoformat(),
                        "source_modified_at": existing.source_modified_at.isoformat()
                        if existing.source_modified_at
                        else None,
                    },
                },
            )

        # Build destination path: INPUT_DIR/{uuid}_{original_filename}
        input_dir = Path(settings.input_dir)
        original_name = file.filename or "upload"
        # Sanitise: strip path separators from client-supplied name
        safe_name = Path(original_name).name

        # Temporary UUID for the filename — will match the DB record id
        import uuid as _uuid
        record_id = _uuid.uuid4()
        dest_filename = f"{record_id}_{safe_name}"
        dest_path = input_dir / dest_filename

        ms_raw = _first_non_empty(x_source_last_modified_ms, source_last_modified_ms)
        source_modified_at = _parse_source_last_modified_ms(ms_raw)
        if source_modified_at is None:
            source_modified_at = read_embedded_recording_datetime_from_bytes(raw, safe_name)

        dest_path.write_bytes(raw)
        logger.info("Saved upload '%s' to '%s'.", original_name, dest_path)

        now = datetime.now(timezone.utc)
        delete_after = now + timedelta(days=settings.local_retention_days)

        record = FileRecord(
            id=record_id,
            filename=safe_name,
            sha256=sha256,
            status="pending",
            uploaded_at=now,
            source_modified_at=source_modified_at,
            local_path=str(dest_path),
            delete_after=delete_after,
        )
        session.add(record)
        session.commit()
        session.refresh(record)

        logger.info("Created FileRecord id=%s for '%s'.", record.id, original_name)
        _queue_module.enqueue(record.id)
        return record
