import logging
import os
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlmodel import select

from app.database import get_session
from app.models import Entry, FileRecord
from app.templates_env import templates

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/status", response_model=List[FileRecord])
async def get_status(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> List[FileRecord]:
    """Return a paginated list of all FileRecords, newest first."""
    with get_session() as session:
        statement = (
            select(FileRecord)
            .order_by(FileRecord.uploaded_at.desc())  # type: ignore[union-attr]
            .offset(offset)
            .limit(limit)
        )
        records = session.exec(statement).all()
        return list(records)


@router.get("/api/status/table", response_class=HTMLResponse)
async def status_table(request: Request) -> HTMLResponse:
    """Return an HTML table fragment for HTMX polling."""
    with get_session() as session:
        statement = (
            select(FileRecord)
            .order_by(FileRecord.uploaded_at.desc())  # type: ignore[union-attr]
            .limit(100)
        )
        records = session.exec(statement).all()

    return templates.TemplateResponse(
        request,
        "partials/status_table.html",
        {"records": records},
    )


@router.get("/api/status/{file_id}")
async def get_file_detail(file_id: UUID) -> Dict[str, Any]:
    """Return a FileRecord and its associated Entry (if any)."""
    with get_session() as session:
        record = session.get(FileRecord, file_id)
        if not record:
            raise HTTPException(status_code=404, detail="File not found")
        entry_stmt = select(Entry).where(Entry.file_id == file_id)
        entry = session.exec(entry_stmt).first()
        return {
            "file": record.model_dump(),
            "entry": entry.model_dump() if entry else None,
        }


@router.delete("/api/status/{file_id}")
async def delete_file(file_id: UUID) -> Response:
    """Delete a file record, its associated Entry, and the physical audio file."""
    with get_session() as session:
        record = session.get(FileRecord, file_id)
        if not record:
            raise HTTPException(status_code=404, detail="File not found")

        # Delete physical file if it exists
        if record.local_path and os.path.exists(record.local_path):
            try:
                os.remove(record.local_path)
            except OSError as e:
                logger.error(f"Failed to delete physical file {record.local_path}: {e}")

        # Delete associated Entry if present
        entry_stmt = select(Entry).where(Entry.file_id == file_id)
        entry = session.exec(entry_stmt).first()
        if entry:
            session.delete(entry)

        # Delete the file record
        session.delete(record)
        session.commit()

    # Empty response allows HTMX to just remove the element
    return Response(status_code=200)


class BatchIdsBody(BaseModel):
    ids: List[UUID]


@router.post("/api/status/batch-delete")
async def batch_delete(body: BatchIdsBody) -> JSONResponse:
    """Delete multiple FileRecords (and their Entries) by ID."""
    count = 0
    with get_session() as session:
        for file_id in body.ids:
            record = session.get(FileRecord, file_id)
            if not record:
                continue

            # Delete physical file if it exists
            if record.local_path and os.path.exists(record.local_path):
                try:
                    os.remove(record.local_path)
                except OSError as e:
                    logger.error(f"Failed to delete physical file {record.local_path}: {e}")

            # Delete associated Entry if present
            entry_stmt = select(Entry).where(Entry.file_id == file_id)
            entry = session.exec(entry_stmt).first()
            if entry:
                session.delete(entry)

            session.delete(record)
            count += 1

        session.commit()

    return JSONResponse({"count": count})


@router.post("/api/status/batch-reset")
async def batch_reset(body: BatchIdsBody) -> JSONResponse:
    """Reset multiple FileRecords to pending status and remove their Entries."""
    count = 0
    with get_session() as session:
        for file_id in body.ids:
            record = session.get(FileRecord, file_id)
            if not record:
                continue

            record.status = "pending"
            record.processed_at = None

            # Delete associated Entry if present
            entry_stmt = select(Entry).where(Entry.file_id == file_id)
            entry = session.exec(entry_stmt).first()
            if entry:
                session.delete(entry)

            session.add(record)
            count += 1

        session.commit()

    return JSONResponse({"count": count})
