import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlmodel import SQLModel, Session, create_engine
from main import app as fastapi_app
from app.database import get_session
import app.database as app_db
import tempfile
import os
from pathlib import Path

@pytest_asyncio.fixture
async def client(session):
    async def override_get_session():
        yield session

    fastapi_app.dependency_overrides[get_session] = override_get_session
    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    fastapi_app.dependency_overrides.clear()

@pytest.fixture
def session(monkeypatch):
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "test.db"
        sqlite_url = f"sqlite:///{db_path}"
        engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(engine)
        
        monkeypatch.setattr(app_db, "engine", engine)
        
        with Session(engine) as session:
            yield session

@pytest.mark.asyncio
async def test_test_client_and_db(client: AsyncClient, session):
    response = await client.get("/api/status")
    assert response.status_code == 200
