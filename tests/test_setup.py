import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_test_client_and_db(client: AsyncClient, session):
    response = await client.get("/api/status")
    assert response.status_code == 200
