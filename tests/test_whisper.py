"""Pure-logic tests for app/services/whisper_service.py.

These tests exercise _preprocess_audio and transcribe without loading
the Whisper model or requiring a GPU.  Test 3 skips gracefully when
ffmpeg is not installed.
"""

import shutil
import subprocess

import pytest

from app.services.whisper_service import _preprocess_audio, transcribe


# ---------------------------------------------------------------------------
# 1. transcribe raises FileNotFoundError for a missing file
# ---------------------------------------------------------------------------

async def test_transcribe_raises_for_missing_file():
    with pytest.raises(FileNotFoundError, match="Audio file not found"):
        await transcribe("/nonexistent/path.mp3")


# ---------------------------------------------------------------------------
# 2. _preprocess_audio skips large files (returns original path, is_temp=False)
# ---------------------------------------------------------------------------

def test_preprocess_skips_large_files(tmp_path, monkeypatch):
    # Create a small dummy file (any bytes will do)
    audio_file = tmp_path / "sample.mp3"
    audio_file.write_bytes(b"FAKE_AUDIO_DATA")

    # Setting denoise_max_mb=0.0 ensures any file exceeds the threshold
    monkeypatch.setattr("app.services.whisper_service.settings.denoise_max_mb", 0.0)

    path_used, is_temp = _preprocess_audio(str(audio_file))

    assert path_used == str(audio_file), "Expected the original path to be returned"
    assert is_temp is False, "Expected is_temp=False when preprocessing is skipped"


# ---------------------------------------------------------------------------
# 3. _preprocess_audio raises CalledProcessError when ffmpeg fails on bad input
# ---------------------------------------------------------------------------

def test_preprocess_raises_for_ffmpeg_failure(tmp_path, monkeypatch):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not available")

    # Create a tiny file with non-audio bytes so ffmpeg will fail
    bad_file = tmp_path / "bad.mp3"
    bad_file.write_bytes(b"\x00\x01\x02\x03NOT_AUDIO")

    # Setting denoise_max_mb=999.0 ensures ffmpeg IS attempted for this tiny file
    monkeypatch.setattr("app.services.whisper_service.settings.denoise_max_mb", 999.0)

    with pytest.raises(subprocess.CalledProcessError):
        _preprocess_audio(str(bad_file))
