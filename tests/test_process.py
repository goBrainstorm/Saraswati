import uuid

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_process_single_file_not_found(client: AsyncClient):
    fake_id = uuid.uuid4()
    response = await client.post(f"/api/process/{fake_id}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_process_trigger(client: AsyncClient):
    response = await client.post("/api/process")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "complete"
    assert data["files_processed"] == 0
    assert data["cache_entries"] == 0
