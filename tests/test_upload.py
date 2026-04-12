import pytest
from httpx import AsyncClient
from sqlmodel import select

from app.models import FileRecord

@pytest.mark.asyncio
async def test_valid_upload(client: AsyncClient, session):
    file_content = b"test audio content"
    files = {"file": ("test.mp3", file_content, "audio/mpeg")}
    response = await client.post("/api/upload", files=files)
    
    assert response.status_code == 200
    db_file = session.exec(select(FileRecord)).first()
    assert db_file is not None
    assert db_file.status == "pending"
    assert db_file.filename == "test.mp3"

@pytest.mark.asyncio
async def test_duplicate_upload(client: AsyncClient, session):
    file_content = b"duplicate audio content"
    files1 = {"file": ("test1.mp3", file_content, "audio/mpeg")}
    response1 = await client.post("/api/upload", files=files1)
    assert response1.status_code == 200
    
    files2 = {"file": ("test2.mp3", file_content, "audio/mpeg")}
    response2 = await client.post("/api/upload", files=files2)
    assert response2.status_code == 409
    assert "detail" in response2.json()
    assert "existing" in response2.json()["detail"]
    assert "id" in response2.json()["detail"]["existing"]

@pytest.mark.asyncio
async def test_filename_sanitisation(client: AsyncClient, session):
    file_content = b"sanitisation content"
    files = {"file": ("../../evil.mp3", file_content, "audio/mpeg")}
    response = await client.post("/api/upload", files=files)
    assert response.status_code == 200
    db_file = session.exec(select(FileRecord)).first()
    assert db_file.filename == "evil.mp3"

@pytest.mark.asyncio
async def test_upload_no_filename(client: AsyncClient, session):
    file_content = b"no filename content"
    files = {"file": b"no filename content"}
    response = await client.post("/api/upload", files=files)
    assert response.status_code == 200
    db_file = session.exec(select(FileRecord)).first()
    assert db_file.filename == "upload"


@pytest.mark.asyncio
async def test_upload_source_last_modified_ms(client: AsyncClient, session):
    file_content = b"test audio content"
    files = {"file": ("test.mp3", file_content, "audio/mpeg")}
    # 2024-01-01 00:00:00 UTC
    data = {"source_last_modified_ms": "1704067200000"}
    response = await client.post("/api/upload", files=files, data=data)
    assert response.status_code == 200
    db_file = session.exec(select(FileRecord)).first()
    assert db_file.source_modified_at is not None
    assert db_file.source_modified_at.strftime("%Y-%m-%d %H:%M") == "2024-01-01 00:00"


@pytest.mark.asyncio
async def test_upload_source_last_modified_header(client: AsyncClient, session):
    """Header is accepted when multipart form field is missing (proxy-safe path)."""
    file_content = b"header-only upload content unique"
    files = {"file": ("test.mp3", file_content, "audio/mpeg")}
    response = await client.post(
        "/api/upload",
        files=files,
        headers={"X-Source-Last-Modified-Ms": "1704067200000"},
    )
    assert response.status_code == 200
    db_file = session.exec(select(FileRecord)).first()
    assert db_file.source_modified_at is not None
    assert db_file.source_modified_at.strftime("%Y-%m-%d %H:%M") == "2024-01-01 00:00"
