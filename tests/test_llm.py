from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.models import ModelConfig
from app.services.llm import (
    _chat,
    _guard_text,
    _MAX_CHARS,
    check_llm_server_ready,
    extract,
    summarize,
    translate,
)


def _mock_chat_response(json_value):
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value=json_value)
    mock_instance = AsyncMock()
    mock_instance.post = AsyncMock(return_value=mock_resp)
    return mock_instance


@pytest.mark.asyncio
async def test_chat_returns_content_on_valid_shape():
    mock_instance = _mock_chat_response(
        {"choices": [{"message": {"content": "  hi there  "}}]}
    )
    with patch("app.services.llm.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_instance
        result = await _chat([{"role": "user", "content": "x"}])
    assert result == "hi there"


@pytest.mark.asyncio
async def test_chat_raises_on_error_json():
    mock_instance = _mock_chat_response({"error": {"message": "boom"}})
    with patch("app.services.llm.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_instance
        with pytest.raises(RuntimeError, match="Unexpected LLM response shape"):
            await _chat([{"role": "user", "content": "x"}])


@pytest.mark.asyncio
async def test_chat_raises_on_empty_choices():
    mock_instance = _mock_chat_response({"choices": []})
    with patch("app.services.llm.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_instance
        with pytest.raises(RuntimeError, match="Unexpected LLM response shape"):
            await _chat([{"role": "user", "content": "x"}])


@pytest.mark.asyncio
async def test_chat_raises_when_content_not_string():
    mock_instance = _mock_chat_response({"choices": [{"message": {"content": None}}]})
    with patch("app.services.llm.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_instance
        with pytest.raises(RuntimeError, match="content"):
            await _chat([{"role": "user", "content": "x"}])


async def test_translate_skips_english():
    result = await translate("hello", "en")
    assert result == "hello"


async def test_translate_skips_english_variants():
    assert await translate("hello", "en-US") == "hello"
    assert await translate("hello", "en-GB") == "hello"


async def test_translate_raises_when_url_empty(db_engine, db_session):
    db_session.add(ModelConfig(step="translate", server_url="", model_name="test"))
    db_session.commit()
    with pytest.raises(RuntimeError, match="LLAMA_SERVER_URL"):
        await translate("Hallo", "de")


async def test_summarize_raises_when_url_empty(db_engine, db_session):
    db_session.add(ModelConfig(step="summarize", server_url="", model_name="test"))
    db_session.commit()
    with pytest.raises(RuntimeError, match="LLAMA_SERVER_URL"):
        await summarize("text")


async def test_extract_raises_when_url_empty(db_engine, db_session):
    db_session.add(ModelConfig(step="extract", server_url="", model_name="test"))
    db_session.commit()
    with pytest.raises(RuntimeError, match="LLAMA_SERVER_URL"):
        await extract("text")


async def test_guard_text_truncates():
    long_text = "x" * (_MAX_CHARS + 1)
    result = _guard_text(long_text)
    assert result.endswith("[truncated]")
    assert len(result) == _MAX_CHARS + len(" [truncated]")


async def test_guard_text_passthrough():
    assert _guard_text("hello") == "hello"


@pytest.mark.asyncio
async def test_check_llm_server_ready_ok(db_engine, db_session):
    db_session.add(
        ModelConfig(
            step="translate",
            server_url="http://127.0.0.1:1",
            model_name="my-model",
        )
    )
    db_session.commit()
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value={"data": [{"id": "my-model"}]})
    mock_instance = AsyncMock()
    mock_instance.get = AsyncMock(return_value=mock_resp)
    with patch("app.services.llm.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_instance
        assert await check_llm_server_ready("translate") is None


@pytest.mark.asyncio
async def test_check_llm_server_ready_model_not_loaded(db_engine, db_session):
    db_session.add(
        ModelConfig(
            step="translate",
            server_url="http://127.0.0.1:1",
            model_name="wanted",
        )
    )
    db_session.commit()
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value={"data": [{"id": "other"}]})
    mock_instance = AsyncMock()
    mock_instance.get = AsyncMock(return_value=mock_resp)
    with patch("app.services.llm.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_instance
        err = await check_llm_server_ready("translate")
    assert err is not None
    assert "not loaded" in err
    assert "wanted" in err


@pytest.mark.asyncio
async def test_check_llm_server_ready_unreachable(db_engine, db_session):
    db_session.add(
        ModelConfig(
            step="translate",
            server_url="http://127.0.0.1:1",
            model_name="m",
        )
    )
    db_session.commit()
    mock_instance = AsyncMock()
    mock_instance.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
    with patch("app.services.llm.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_instance
        err = await check_llm_server_ready("translate")
    assert err is not None
    assert "unreachable" in err


@pytest.mark.asyncio
async def test_check_llm_server_ready_empty_models_list_ok(db_engine, db_session):
    """If /v1/models returns no ids, do not block (some servers use odd shapes)."""
    db_session.add(
        ModelConfig(
            step="translate",
            server_url="http://127.0.0.1:1",
            model_name="m",
        )
    )
    db_session.commit()
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value={"data": []})
    mock_instance = AsyncMock()
    mock_instance.get = AsyncMock(return_value=mock_resp)
    with patch("app.services.llm.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_instance
        assert await check_llm_server_ready("translate") is None


@pytest.mark.asyncio
async def test_check_llm_server_ready_no_server_url(db_engine, db_session):
    db_session.add(ModelConfig(step="translate", server_url="", model_name="x"))
    db_session.commit()
    err = await check_llm_server_ready("translate")
    assert err is not None
    assert "not configured" in err
