from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

_model: Optional[object] = None  # WhisperModel, typed as object to avoid import at module level


def _get_model():
    """Lazy singleton: load WhisperModel on first call, reuse thereafter.

    Runs in a thread-pool executor — do not call from async context directly.
    """
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            device = "cpu"

        logger.info(
            "Loading Whisper model '%s' on device='%s' compute_type='int8'.",
            settings.whisper_model,
            device,
        )

        try:
            from huggingface_hub.constants import HF_HUB_CACHE
            # faster-whisper default models are mapped to Systran/faster-whisper-{size}
            model_name = settings.whisper_model
            is_default_model = model_name in [
                "tiny", "tiny.en", "base", "base.en", "small", "small.en",
                "medium", "medium.en", "large-v1", "large-v2", "large-v3", "large"
            ]
            if is_default_model:
                repo_id = f"Systran/faster-whisper-{model_name}"
                expected_cache_dir = os.path.join(HF_HUB_CACHE, "models--" + repo_id.replace("/", "--"))
                if not os.path.exists(expected_cache_dir):
                    logger.info(
                        "Whisper model '%s' not found locally. Downloading from Hugging Face... "
                        "(this may take several minutes and appear frozen)",
                        model_name
                    )
            else:
                # If custom repo, checking cache is harder, just log generically
                if not os.path.exists(model_name):
                    logger.info(
                        "Checking/downloading model '%s' from Hugging Face... "
                        "(this may take several minutes and appear frozen)",
                        model_name
                    )
        except Exception:
            # Fallback if huggingface_hub check fails
            logger.info(
                "Note: If the model is not cached locally, it will be downloaded from Hugging Face. "
                "This may take several minutes and appear frozen."
            )

        _model = WhisperModel(settings.whisper_model, device=device, compute_type="int8")
        logger.info("Whisper model loaded.")
    return _model


def _preprocess_audio(local_path: str) -> tuple[str, bool]:
    """Run ffmpeg loudnorm normalization if the file is below DENOISE_MAX_MB.

    Returns (path_to_use, is_temp). If is_temp is True, caller must delete the file.
    Runs synchronously — intended to be called inside run_in_executor.
    """
    size_bytes = os.path.getsize(local_path)
    max_bytes = settings.denoise_max_mb * 1024 * 1024

    if size_bytes > max_bytes:
        logger.info(
            "File %.1f MB exceeds DENOISE_MAX_MB=%.1f, skipping ffmpeg preprocessing.",
            size_bytes / (1024 * 1024),
            settings.denoise_max_mb,
        )
        return local_path, False

    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".wav")
    os.close(tmp_fd)

    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", local_path,
                "-af", "loudnorm",
                "-ar", "16000", "-ac", "1",
                "-f", "wav", tmp_path,
            ],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        os.unlink(tmp_path)
        logger.error(
            "ffmpeg preprocessing failed for %s: %s",
            local_path,
            exc.stderr.decode(errors="replace"),
        )
        raise

    logger.debug("ffmpeg preprocessing complete: %s → %s", local_path, tmp_path)
    return tmp_path, True


def _transcribe_sync(local_path: str) -> tuple[str, str]:
    """Synchronous transcription: preprocess → Whisper → (text, lang).

    Called inside asyncio.get_event_loop().run_in_executor().
    Cleans up any temp file before returning.
    """
    preprocessed_path, is_temp = _preprocess_audio(local_path)
    try:
        model = _get_model()
        segments, info = model.transcribe(
            preprocessed_path,
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        lang = info.language
        logger.info(
            "Transcribed %s: lang=%s, %d chars.",
            Path(local_path).name,
            lang,
            len(text),
        )
        return text, lang
    finally:
        if is_temp:
            try:
                os.unlink(preprocessed_path)
            except OSError:
                pass


async def transcribe(local_path: str) -> tuple[str, str]:
    """Async entry point: transcribe an audio file using faster-whisper.

    Offloads all CPU-bound work to the default ThreadPoolExecutor.

    Args:
        local_path: Path to the audio file.

    Returns:
        (transcription_text, detected_language_code)
    """
    if not Path(local_path).exists():
        raise FileNotFoundError(f"Audio file not found: {local_path}")

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _transcribe_sync, local_path)
