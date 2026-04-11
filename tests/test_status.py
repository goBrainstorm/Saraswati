import pytest
import datetime
from httpx import AsyncClient
from app.models import FileRecord
from sqlmodel import Session

@pytest.mark.asyncio
async def test_empty_status(client: AsyncClient):
    response = await client.get("/api/status")
    assert response.status_code == 200
    assert response.json() == []

@pytest.mark.asyncio
async def test_populated_status(client: AsyncClient, session: Session):
    record = FileRecord(
        filename="test.mp3",
        sha256="dummyhash",
        status="pending",
        uploaded_at=datetime.datetime.now(datetime.timezone.utc),
        local_path="/tmp/test.mp3"
    )
    session.add(record)
    session.commit()
    
    response = await client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["filename"] == "test.mp3"

@pytest.mark.asyncio
async def test_status_pagination(client: AsyncClient, session: Session):
    for i in range(5):
        record = FileRecord(
            filename=f"test{i}.mp3",
            sha256=f"hash{i}",
            status="pending",
            uploaded_at=datetime.datetime.now(datetime.timezone.utc),
            local_path=f"/tmp/test{i}.mp3"
        )
        session.add(record)
    session.commit()
    
    # Depending on offset and limit
    response = await client.get("/api/status?limit=2&offset=1")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2

@pytest.mark.asyncio
async def test_status_table_html(client: AsyncClient, session: Session):
    record = FileRecord(
        filename="html_test.mp3",
        sha256="htmlhash",
        status="pending",
        uploaded_at=datetime.datetime.now(datetime.timezone.utc),
        local_path="/tmp/html_test.mp3"
    )
    session.add(record)
    session.commit()
    
    response = await client.get("/api/status/table")
    assert response.status_code == 200
    assert "html_test.mp3" in response.text
    assert "<" in response.text # rough check for HTML


@pytest.mark.asyncio
async def test_queues_json_empty(client: AsyncClient):
    from app.queue import reset_processing_queue

    reset_processing_queue()
    response = await client.get("/api/status/queues")
    assert response.status_code == 200
    data = response.json()
    assert data["processing"]["waiting"] == []
    assert data["processing"]["current"] is None
    assert isinstance(data["sse"]["subscribers"], int)


@pytest.mark.asyncio
async def test_queues_json_waiting_filename(client: AsyncClient, session: Session):
    from app.queue import enqueue, reset_processing_queue

    reset_processing_queue()
    record = FileRecord(
        filename="queued.m4a",
        sha256="queuesnapsha",
        status="pending",
        uploaded_at=datetime.datetime.now(datetime.timezone.utc),
        local_path="/tmp/queued.m4a",
    )
    session.add(record)
    session.commit()
    enqueue(record.id)

    response = await client.get("/api/status/queues")
    assert response.status_code == 200
    data = response.json()
    assert len(data["processing"]["waiting"]) == 1
    assert data["processing"]["waiting"][0]["filename"] == "queued.m4a"
    assert data["processing"]["waiting"][0]["id"] == str(record.id)
    reset_processing_queue()


@pytest.mark.asyncio
async def test_queues_panel_html(client: AsyncClient):
    response = await client.get("/api/status/queues/panel")
    assert response.status_code == 200
    assert "Pipeline queue" in response.text
    assert "SSE subscribers" in response.text
