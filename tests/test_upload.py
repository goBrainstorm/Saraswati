import pytest
from httpx import AsyncClient
from app.models import FileRecord
from sqlmodel import select

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
