import hashlib
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from sqlmodel import select

from app.config import settings
from app.database import get_session
from app.models import FileRecord

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/api/upload", response_model=FileRecord)
async def upload_file(file: UploadFile) -> FileRecord:
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
            local_path=str(dest_path),
            delete_after=delete_after,
        )
        session.add(record)
        session.commit()
        session.refresh(record)

        logger.info("Created FileRecord id=%s for '%s'.", record.id, original_name)
        return record
