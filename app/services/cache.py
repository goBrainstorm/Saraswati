from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlmodel import select

from app.config import settings
from app.database import get_session
from app.models import Entry, FileRecord

logger = logging.getLogger(__name__)

_RECENT_DAYS = 7


async def write_recent_cache() -> int:
    """Serialize the last 7 days of entries to CACHE_DIR/recent.json.

    Uses an atomic tmp-then-replace write so the file is never half-written.
    Returns the number of entries written. Errors are logged and not raised.
    """
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=_RECENT_DAYS)

        with get_session() as session:
            statement = select(Entry).where(Entry.created_at >= cutoff)
            entries = session.exec(statement).all()

            # Build a filename lookup in the same session
            file_ids = {e.file_id for e in entries}
            filenames: dict = {}
            for fid in file_ids:
                record = session.get(FileRecord, fid)
                if record:
                    filenames[fid] = record.filename

        rows = []
        for entry in entries:
            extracted = None
            if entry.extracted_json:
                try:
                    extracted = json.loads(entry.extracted_json)
                except json.JSONDecodeError:
                    extracted = None

            rows.append(
                {
                    "id": str(entry.id),
                    "file_id": str(entry.file_id),
                    "filename": filenames.get(entry.file_id),
                    "created_at": entry.created_at.isoformat(),
                    "language": entry.language,
                    "transcription": entry.transcription,
                    "translation": entry.translation,
                    "summary": entry.summary,
                    "extracted": extracted,
                    "qdrant_id": entry.qdrant_id,
                }
            )

        cache_dir = Path(settings.cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = cache_dir / "recent.json.tmp"
        final_path = cache_dir / "recent.json"

        tmp_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp_path, final_path)

        logger.info("Cache written: %d entries to %s.", len(rows), final_path)
        return len(rows)

    except Exception as exc:
        logger.error("Failed to write recent cache: %s", exc, exc_info=True)
        return 0
