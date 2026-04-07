import httpx
import pytest
from httpx import AsyncClient
from sqlmodel import select
from unittest.mock import AsyncMock, patch

from app.models import ModelConfig
from app.services.model_config import seed_model_configs, VALID_STEPS


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_seed_is_idempotent(session):
    """Calling seed twice should still leave exactly 4 rows."""
    seed_model_configs()
    seed_model_configs()
    rows = session.exec(select(ModelConfig)).all()
    assert len(rows) == 4
    steps = {r.step for r in rows}
    assert steps == set(VALID_STEPS)


@pytest.mark.asyncio
async def test_get_config_returns_all_steps(client: AsyncClient, session):
    """GET /api/models/config returns a list of all 4 step configs."""
    seed_model_configs()
    response = await client.get("/api/models/config")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 4
    returned_steps = {item["step"] for item in data}
    assert returned_steps == set(VALID_STEPS)


@pytest.mark.asyncio
async def test_put_config_updates_step(client: AsyncClient, session):
    """PUT /api/models/config/translate updates and returns the updated config."""
    seed_model_configs()
    payload = {"server_url": "http://myserver:8080", "model_name": "my-model"}
    response = await client.put("/api/models/config/translate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["step"] == "translate"
    assert data["server_url"] == "http://myserver:8080"
    assert data["model_name"] == "my-model"

    # Verify DB was actually updated
    row = session.exec(select(ModelConfig).where(ModelConfig.step == "translate")).first()
    assert row is not None
    assert row.server_url == "http://myserver:8080"
    assert row.model_name == "my-model"


@pytest.mark.asyncio
async def test_put_config_invalid_step(client: AsyncClient, session):
    """PUT /api/models/config/<invalid> returns 422."""
    payload = {"server_url": "http://x", "model_name": "x"}
    response = await client.put("/api/models/config/invalid_step", json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_available_transcribe_returns_list(client: AsyncClient, session):
    """GET /api/models/available/transcribe returns expected whisper model names."""
    seed_model_configs()
    response = await client.get("/api/models/available/transcribe")
    assert response.status_code == 200
    data = response.json()
    assert "models" in data
    assert "cached" in data
    expected = [
        "tiny", "tiny.en", "base", "base.en", "small", "small.en",
        "medium", "medium.en", "large-v1", "large-v2", "large-v3", "large",
    ]
    assert data["models"] == expected
    assert isinstance(data["cached"], list)


@pytest.mark.asyncio
async def test_available_llm_step_empty_url(client: AsyncClient, session):
    """With server_url empty, available returns {models: [], cached: []}."""
    seed_model_configs()
    # Set server_url to empty string
    await client.put(
        "/api/models/config/translate",
        json={"server_url": "", "model_name": "some-model"},
    )
    response = await client.get("/api/models/available/translate")
    assert response.status_code == 200
    data = response.json()
    assert data == {"models": [], "cached": []}


@pytest.mark.asyncio
async def test_available_llm_step_unreachable(client, session):
    from app.services.model_config import seed_model_configs
    seed_model_configs()
    await client.put(
        "/api/models/config/translate",
        json={"server_url": "http://localhost:9999", "model_name": "x"},
    )
    with patch("app.routes.models_config.httpx.AsyncClient") as mock_cls:
        mock_instance = AsyncMock()
        mock_cls.return_value.__aenter__.return_value = mock_instance
        mock_instance.get.side_effect = httpx.ConnectError("Connection refused")
        response = await client.get("/api/models/available/translate")
    assert response.status_code == 502
