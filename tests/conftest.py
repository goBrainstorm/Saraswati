import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlmodel import SQLModel, Session, create_engine
from main import app as fastapi_app
from app.database import get_session
import app.database as app_db
import tempfile
from pathlib import Path

@pytest_asyncio.fixture
async def client(session):
    async def override_get_session():
        yield session

    fastapi_app.dependency_overrides[get_session] = override_get_session
    transport = ASGITransport(app=fastapi_app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        fastapi_app.dependency_overrides.pop(get_session, None)

@pytest.fixture(autouse=True)
def disable_queue_drain_at_startup(monkeypatch):
    """Avoid a second drain_queue() competing with queue tests and event-loop issues."""
    monkeypatch.setattr("app.config.settings.queue_drain_enabled", False)


@pytest.fixture(autouse=True)
def setup_test_env(monkeypatch):
    with tempfile.TemporaryDirectory() as temp_dir:
        input_dir = Path(temp_dir) / "input"
        input_dir.mkdir()
        monkeypatch.setattr("app.routes.upload.settings.input_dir", str(input_dir))
        # Might also need to patch app.config.settings just in case
        monkeypatch.setattr("app.config.settings.input_dir", str(input_dir))
        yield temp_dir

@pytest.fixture
def session(monkeypatch, setup_test_env):
    temp_dir = setup_test_env
    db_path = Path(temp_dir) / "test.db"
    sqlite_url = f"sqlite:///{db_path}"
    engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    monkeypatch.setattr(app_db, "engine", engine)

    with Session(engine) as session:
        yield session


@pytest.fixture
def db_engine(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(app_db, "engine", engine)
    yield engine


@pytest.fixture
def db_session(db_engine):
    with Session(db_engine) as session:
        yield session


@pytest_asyncio.fixture
async def app_client(db_engine):
    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
