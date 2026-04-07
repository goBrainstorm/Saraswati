from typing import List
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse
from sqlmodel import select

from app.database import get_session
from app.models import Entry, FileRecord
from app.templates_env import templates

router = APIRouter()


@router.get("/api/entries", response_model=List[Entry])
async def get_entries(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> List[Entry]:
    """Return a paginated list of all Entry records, newest first."""
    with get_session() as session:
        statement = (
            select(Entry)
            .order_by(Entry.created_at.desc())  # type: ignore[union-attr]
            .offset(offset)
            .limit(limit)
        )
        entries = session.exec(statement).all()
        return list(entries)


@router.get("/api/entries/table", response_class=HTMLResponse)
async def entries_table(request: Request) -> HTMLResponse:
    """Return an HTML table fragment for HTMX polling."""
    with get_session() as session:
        statement = (
            select(Entry)
            .order_by(Entry.created_at.desc())  # type: ignore[union-attr]
            .limit(100)
        )
        raw_entries = session.exec(statement).all()

        # Collect file IDs and fetch filenames in one query
        file_ids = list({e.file_id for e in raw_entries})
        filenames: dict = {}
        if file_ids:
            file_stmt = select(FileRecord).where(FileRecord.id.in_(file_ids))  # type: ignore[attr-defined]
            for fr in session.exec(file_stmt).all():
                filenames[fr.id] = fr.filename

        entries = [
            {
                "id": str(e.id),
                "file_id": e.file_id,
                "filename": filenames.get(e.file_id),
                "language": e.language,
                "summary": e.summary,
                "created_at": e.created_at,
                "transcription": e.transcription,
                "translation": e.translation,
                "extracted_json": e.extracted_json,
            }
            for e in raw_entries
        ]

    return templates.TemplateResponse(
        request,
        "partials/entries_table.html",
        {"entries": entries},
    )


@router.get("/entries", response_class=HTMLResponse, include_in_schema=False)
async def entries_page(request: Request) -> HTMLResponse:
    """Serve the entries management page."""
    return templates.TemplateResponse(request, "entries.html", {"active_page": "entries"})


def _delete_entry_and_revert(entry_id: UUID) -> Response:
    """Shared logic: delete Entry row and revert FileRecord status to 'pending'."""
    with get_session() as session:
        entry = session.get(Entry, entry_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Entry not found")
        record = session.get(FileRecord, entry.file_id)
        session.delete(entry)
        if record:
            record.status = "pending"
            record.processed_at = None
            session.add(record)
        session.commit()
    return Response(status_code=200)


@router.delete("/api/entries/{entry_id}")
async def delete_entry(entry_id: UUID) -> Response:
    """Delete an entire Entry row and revert FileRecord status to 'pending'."""
    return _delete_entry_and_revert(entry_id)


@router.delete("/api/entries/{entry_id}/transcription")
async def delete_entry_transcription(entry_id: UUID) -> Response:
    """Delete an entire Entry row (transcription is the base field) and revert FileRecord status to 'pending'."""
    return _delete_entry_and_revert(entry_id)


@router.delete("/api/entries/{entry_id}/translation")
async def delete_entry_translation(entry_id: UUID) -> Response:
    """Null translation and all downstream fields; revert FileRecord status to 'transcribed'."""
    with get_session() as session:
        entry = session.get(Entry, entry_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Entry not found")
        entry.translation = None
        entry.summary = None
        entry.extracted_json = None
        session.add(entry)
        record = session.get(FileRecord, entry.file_id)
        if record:
            record.status = "transcribed"
            session.add(record)
        session.commit()
    return Response(status_code=200)


@router.delete("/api/entries/{entry_id}/summary")
async def delete_entry_summary(entry_id: UUID) -> Response:
    """Null summary and all downstream fields; revert FileRecord status to 'translated'."""
    with get_session() as session:
        entry = session.get(Entry, entry_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Entry not found")
        entry.summary = None
        entry.extracted_json = None
        session.add(entry)
        record = session.get(FileRecord, entry.file_id)
        if record:
            record.status = "translated"
            session.add(record)
        session.commit()
    return Response(status_code=200)


@router.delete("/api/entries/{entry_id}/extracted_json")
async def delete_entry_extracted_json(entry_id: UUID) -> Response:
    """Null the extracted_json field and revert FileRecord status to 'summarized'."""
    with get_session() as session:
        entry = session.get(Entry, entry_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Entry not found")
        entry.extracted_json = None
        session.add(entry)
        record = session.get(FileRecord, entry.file_id)
        if record:
            record.status = "summarized"
            session.add(record)
        session.commit()
    return Response(status_code=200)
