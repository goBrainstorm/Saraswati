import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_process_trigger(client: AsyncClient):
    response = await client.post("/api/process")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "complete"
    assert data["files_processed"] == 0
    assert data["cache_entries"] == 0
