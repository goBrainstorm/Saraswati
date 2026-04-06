# tests/test_prompts.py
import json
import pytest
from pathlib import Path

from app.services import prompts as prompts_svc


def _patch_path(monkeypatch, tmp_path):
    """Redirect prompts path to tmp_path/data/prompts.json"""
    monkeypatch.setattr(
        "app.services.prompts._prompts_path",
        lambda: tmp_path / "data" / "prompts.json"
    )


def test_load_prompts_returns_defaults_when_no_file(tmp_path, monkeypatch):
    _patch_path(monkeypatch, tmp_path)
    result = prompts_svc.load_prompts()
    assert "translate_system" in result
    assert "summarize_system" in result
    assert "extract_system" in result
    assert len(result) == 6


def test_get_prompt_returns_default(tmp_path, monkeypatch):
    _patch_path(monkeypatch, tmp_path)
    val = prompts_svc.get_prompt("translate_system")
    assert len(val) > 10


def test_update_and_reload_prompt(tmp_path, monkeypatch):
    _patch_path(monkeypatch, tmp_path)
    prompts_svc.update_prompt("translate_system", "Custom system prompt.")
    assert prompts_svc.get_prompt("translate_system") == "Custom system prompt."


def test_update_unknown_prompt_raises(tmp_path, monkeypatch):
    _patch_path(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="Unknown prompt"):
        prompts_svc.update_prompt("nonexistent_key", "value")


def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    _patch_path(monkeypatch, tmp_path)
    prompts_svc.update_prompt("summarize_system", "My custom summarizer.")
    loaded = prompts_svc.load_prompts()
    assert loaded["summarize_system"] == "My custom summarizer."


def test_load_merges_saved_with_defaults(tmp_path, monkeypatch):
    _patch_path(monkeypatch, tmp_path)
    # Save only one key
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "prompts.json").write_text(
        json.dumps({"translate_system": "Custom."})
    )
    loaded = prompts_svc.load_prompts()
    assert loaded["translate_system"] == "Custom."
    # Other keys still have defaults
    assert loaded["summarize_system"] == prompts_svc.DEFAULTS["summarize_system"]


# ---------------------------------------------------------------------------
# HTTP-level tests
# ---------------------------------------------------------------------------
from httpx import AsyncClient


@pytest.mark.anyio
async def test_get_prompts_returns_all_keys(app_client: AsyncClient, tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.prompts._prompts_path", lambda: tmp_path / "data" / "prompts.json")
    resp = await app_client.get("/api/prompts")
    assert resp.status_code == 200
    data = resp.json()
    assert set(data.keys()) == {"translate_system", "translate_user", "summarize_system",
                                 "summarize_user", "extract_system", "extract_user"}


@pytest.mark.anyio
async def test_put_prompt_updates_value(app_client: AsyncClient, tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.prompts._prompts_path", lambda: tmp_path / "data" / "prompts.json")
    resp = await app_client.put(
        "/api/prompts/translate_system",
        json={"text": "New system prompt."},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["translate_system"] == "New system prompt."


@pytest.mark.anyio
async def test_put_unknown_prompt_returns_422(app_client: AsyncClient):
    resp = await app_client.put(
        "/api/prompts/nonexistent_key",
        json={"text": "something"},
    )
    assert resp.status_code == 422
