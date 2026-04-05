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
