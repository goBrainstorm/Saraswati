from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FileRecord(SQLModel, table=True):
    __tablename__ = "files"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    filename: str
    sha256: str = Field(unique=True, index=True)
    status: str = Field(default="pending")  # pending | processing | done | failed
    uploaded_at: datetime = Field(default_factory=_utcnow)
    # When the source file was last modified: browser File.lastModified and/or embedded tags
    source_modified_at: Optional[datetime] = Field(default=None)
    processed_at: Optional[datetime] = Field(default=None)
    local_path: str


class Entry(SQLModel, table=True):
    __tablename__ = "entries"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    file_id: UUID = Field(foreign_key="files.id", index=True)
    created_at: datetime = Field(default_factory=_utcnow)
    language: Optional[str] = Field(default=None)
    transcription: Optional[str] = Field(default=None)
    translation: Optional[str] = Field(default=None)
    summary: Optional[str] = Field(default=None)
    extracted_json: Optional[str] = Field(default=None)  # JSON string
    qdrant_id: Optional[str] = Field(default=None)


class ModelConfig(SQLModel, table=True):
    __tablename__ = "model_configs"

    id: int = Field(default=None, primary_key=True)
    step: str = Field(unique=True, index=True)  # transcribe|translate|summarize|extract
    server_url: str = Field(default="")          # empty for transcribe; llama.cpp URL for LLM steps
    model_name: str
