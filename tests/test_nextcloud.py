import pytest
from app.services.nextcloud import upload_file

@pytest.mark.asyncio
async def test_nextcloud_empty_url_noop(monkeypatch):
    monkeypatch.setattr("app.services.nextcloud.settings.nextcloud_url", "")
    
    result = await upload_file("/tmp/dummy.mp3", "dummy.mp3")
    assert result == ""

@pytest.mark.skip(reason="Integration test requires real Nextcloud")
@pytest.mark.asyncio
async def test_nextcloud_integration():
    pass
