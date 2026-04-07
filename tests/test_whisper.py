"""Pure-logic tests for app/services/whisper_service.py.

These tests exercise _preprocess_audio and transcribe without loading
the Whisper model or requiring a GPU.  Test 3 skips gracefully when
ffmpeg is not installed.
"""

import shutil
import subprocess
from types import SimpleNamespace

import pytest

import app.services.whisper_service as whisper_service
from app.services.whisper_service import _preprocess_audio, _transcribe_sync, transcribe


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


# ---------------------------------------------------------------------------
# 4. _transcribe_sync passes VAD and beam options to faster-whisper
# ---------------------------------------------------------------------------

def test_transcribe_sync_transcribe_kwargs(tmp_path, monkeypatch):
    audio_file = tmp_path / "sample.mp3"
    audio_file.write_bytes(b"FAKE_AUDIO_DATA")

    captured_kwargs = {}

    class _FakeModel:
        def transcribe(self, path, **kwargs):
            captured_kwargs.update(kwargs)
            assert path == str(audio_file)
            return [SimpleNamespace(text="hello"), SimpleNamespace(text="world")], SimpleNamespace(language="en")

    monkeypatch.setattr("app.services.whisper_service._preprocess_audio", lambda p: (p, False))
    monkeypatch.setattr("app.services.whisper_service._get_model", lambda: _FakeModel())

    text, lang = _transcribe_sync(str(audio_file))

    assert text == "hello world"
    assert lang == "en"
    assert captured_kwargs["beam_size"] == 5
    assert captured_kwargs["vad_filter"] is True
    assert captured_kwargs["vad_parameters"] == {"min_silence_duration_ms": 500}


# ---------------------------------------------------------------------------
# 5. auto + missing CUDA libs: one GPU failure then CPU retry succeeds
# ---------------------------------------------------------------------------


def test_transcribe_sync_falls_back_to_cpu_on_cublas_error(tmp_path, monkeypatch):
    audio_file = tmp_path / "sample.mp3"
    audio_file.write_bytes(b"FAKE_AUDIO_DATA")

    monkeypatch.setattr(whisper_service.settings, "whisper_device", "auto")
    monkeypatch.setattr(whisper_service, "_whisper_gpu_broken", False)
    monkeypatch.setattr(whisper_service, "_model", None)
    monkeypatch.setattr(whisper_service, "_current_model_name", None)
    monkeypatch.setattr(whisper_service, "_resolve_whisper_device", lambda: "cuda")

    n = {"get_model": 0}

    class _BadGpu:
        def transcribe(self, path, **kwargs):
            raise RuntimeError(
                "Library libcublas.so.12 is not found or cannot be loaded"
            )

    class _OkCpu:
        def transcribe(self, path, **kwargs):
            return [SimpleNamespace(text="ok")], SimpleNamespace(language="pl")

    def fake_get_model():
        n["get_model"] += 1
        return _BadGpu() if n["get_model"] == 1 else _OkCpu()

    monkeypatch.setattr(whisper_service, "_preprocess_audio", lambda p: (p, False))
    monkeypatch.setattr(whisper_service, "_get_model", fake_get_model)

    text, lang = whisper_service._transcribe_sync(str(audio_file))

    assert text == "ok"
    assert lang == "pl"
    assert n["get_model"] == 2
    assert whisper_service._whisper_gpu_broken is True


def test_transcribe_sync_no_cpu_fallback_when_whisper_device_cuda(tmp_path, monkeypatch):
    audio_file = tmp_path / "sample.mp3"
    audio_file.write_bytes(b"FAKE_AUDIO_DATA")

    monkeypatch.setattr(whisper_service.settings, "whisper_device", "cuda")

    class _BadGpu:
        def transcribe(self, path, **kwargs):
            raise RuntimeError(
                "Library libcublas.so.12 is not found or cannot be loaded"
            )

    monkeypatch.setattr(whisper_service, "_preprocess_audio", lambda p: (p, False))
    monkeypatch.setattr(whisper_service, "_get_model", lambda: _BadGpu())

    with pytest.raises(RuntimeError, match="libcublas"):
        whisper_service._transcribe_sync(str(audio_file))
