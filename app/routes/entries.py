from typing import List

from fastapi import APIRouter, Query, Request
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
                "file_id": e.file_id,
                "filename": filenames.get(e.file_id),
                "language": e.language,
                "summary": e.summary,
                "created_at": e.created_at,
            }
            for e in raw_entries
        ]

    return templates.TemplateResponse(
        request,
        "partials/entries_table.html",
        {"entries": entries},
    )
