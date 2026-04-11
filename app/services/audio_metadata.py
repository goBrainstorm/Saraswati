"""Read recording-related timestamps from audio file containers."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_DATE_PART = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?")

_mutagen_missing_logged = False


def _log_mutagen_missing_once() -> None:
    global _mutagen_missing_logged
    if not _mutagen_missing_logged:
        logger.warning(
            "mutagen is not installed; embedded recording dates are skipped. "
            "Install dependencies with: pip install -r requirements.txt"
        )
        _mutagen_missing_logged = True


def _parse_tag_date(value: object) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, list) and value:
        value = value[0]
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    m = _DATE_PART.match(s)
    if not m:
        return None
    y, mo, d = int(m.group(1)), m.group(2), m.group(3)
    try:
        if mo and d:
            return datetime(int(y), int(mo), int(d), tzinfo=timezone.utc)
        if mo:
            return datetime(int(y), int(mo), 1, tzinfo=timezone.utc)
        return datetime(int(y), 1, 1, tzinfo=timezone.utc)
    except ValueError:
        return None


def _collect_tag_strings(tags: object) -> list[str]:
    out: list[str] = []
    if hasattr(tags, "getall"):
        for key in ("TDRC", "TDOR", "TYER"):
            try:
                for v in tags.getall(key):
                    if hasattr(v, "text") and v.text:
                        out.append(str(v.text[0]))
                    elif v is not None:
                        out.append(str(v))
            except KeyError:
                continue
    if isinstance(tags, dict):
        for k in (
            "\xa9day",
            "©day",
            "date",
            "DATE",
            "creation_time",
            "ORIGINALDATE",
        ):
            if k in tags:
                val = tags[k]
                if isinstance(val, list) and val:
                    out.append(str(val[0]))
                elif val is not None:
                    out.append(str(val))
    if hasattr(tags, "keys"):
        for key in ("date", "DATE", "originaldate"):
            try:
                if key in tags:
                    v = tags[key]
                    if isinstance(v, list) and v:
                        out.append(str(v[0]))
                    elif isinstance(v, str):
                        out.append(v)
            except Exception:
                pass
    return out


def _datetime_from_mutagen_audio(audio: object) -> Optional[datetime]:
    if audio is None or not getattr(audio, "tags", None):
        return None
    for c in _collect_tag_strings(audio.tags):
        dt = _parse_tag_date(c)
        if dt is not None:
            return dt
    return None


def read_embedded_recording_datetime_from_bytes(data: bytes, filename: str) -> Optional[datetime]:
    """Parse embedded date tags from raw bytes (uses filename for format detection)."""
    try:
        from mutagen import File as mutagen_file
    except ImportError:
        _log_mutagen_missing_once()
        return None

    bio = BytesIO(data)
    for easy in (True, False):
        bio.seek(0)
        try:
            audio = mutagen_file(bio, filename=filename, easy=easy)
        except Exception as e:
            logger.debug("mutagen could not parse %r (easy=%s): %s", filename, easy, e)
            continue
        dt = _datetime_from_mutagen_audio(audio)
        if dt is not None:
            return dt

    return None


def read_embedded_recording_datetime(path: Path) -> Optional[datetime]:
    """Best-effort date from embedded tags (ID3, Vorbis, MP4 metadata, etc.)."""
    try:
        return read_embedded_recording_datetime_from_bytes(path.read_bytes(), path.name)
    except OSError as e:
        logger.debug("could not read %s: %s", path, e)
        return None
