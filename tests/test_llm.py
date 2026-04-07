import pytest

from app.models import ModelConfig
from app.services.llm import _guard_text, _MAX_CHARS, translate, summarize, extract


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
