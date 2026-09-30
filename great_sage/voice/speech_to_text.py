"""
Local speech-to-text via faster-whisper - CPU-only, fully offline, no
cloud API. Used by both push-to-talk and the wake-word listener.
"""

import logging
import os

import numpy as np

log = logging.getLogger(__name__)

_model = None


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        # Model size configurable via env var or settings.
        # "base" = fastest, least accurate. "small" = better. "medium" = best but slower.
        model_size = os.environ.get("GREAT_SAGE_STT_MODEL", "small")
        # Use int8 for CPU efficiency. For GPU, could use "float16".
        device = os.environ.get("GREAT_SAGE_STT_DEVICE", "cpu")
        compute_type = "int8" if device == "cpu" else "float16"
        log.info("Loading Whisper model: %s on %s (%s)", model_size, device, compute_type)
        _model = WhisperModel(model_size, device=device, compute_type=compute_type)
    return _model


def transcribe(audio: np.ndarray) -> str:
    """Transcribe mono float32 audio sampled at 16 kHz."""
    if audio.size == 0:
        log.warning("Transcription skipped: empty recording")
        return ""

    model = _get_model()
    from great_sage.config import settings

    language = getattr(settings, "INPUT_LANGUAGE", "es")
    # Bias the multilingual decoder toward the project's proper names.
    # Without this, short Spanish speech containing "Raphael" is easy for the
    # base model to render as a phonetically unrelated phrase such as "a caer".
    initial_prompt = getattr(
        settings,
        "STT_INITIAL_PROMPT",
        "Raphael. Great Sage. Ciel. WhatsApp. Firefox. Spotify. Roblox. Steam. Discord."
    )
    # VAD parameters tuned for fewer false positives and better segmentation
    vad_params = {
        "threshold": 0.5,              # Higher = less sensitive to background noise
        "min_speech_duration_ms": 250, # Minimum speech chunk
        "min_silence_duration_ms": 800,# Longer silence before ending utterance
        "speech_pad_ms": 400,          # Padding around detected speech
    }
    segments, _ = model.transcribe(
        audio,
        language=language,
        vad_filter=True,
        vad_parameters=vad_params,
        initial_prompt=initial_prompt,
        condition_on_previous_text=False,
        # Suppress tokens that commonly cause hallucinations
        suppress_tokens=[-1],
        # Beam size for better accuracy (1=fast, 5=better)
        beam_size=5,
    )
    text = "".join(seg.text for seg in segments).strip()

    seconds = audio.size / 16000.0
    if text:
        log.info("Transcribed %.1fs of audio: %r", seconds, text)
    else:
        log.warning(
            "Transcribed %.1fs of audio but got no text. "
            "Either nothing was said or the VAD filter rejected it.",
            seconds,
        )
    return text
