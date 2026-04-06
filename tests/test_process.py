import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_process_trigger(client: AsyncClient):
    response = await client.post("/api/process")
    assert response.status_code == 200
    assert response.json() == {"status": "complete", "files_processed": 0, "cache_entries": 0}
