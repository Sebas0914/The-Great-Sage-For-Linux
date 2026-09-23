"""
Local speech-to-text via faster-whisper - CPU-only, fully offline, no
cloud API. Used by both push-to-talk and the wake-word listener.
"""

import logging

import numpy as np

log = logging.getLogger(__name__)

_model = None


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        # Multilingual Whisper model so Spanish input is transcribed correctly.
        _model = WhisperModel("base", device="cpu", compute_type="int8")
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
        "Raphael. Great Sage. Ciel.",
    )
    segments, _ = model.transcribe(
        audio,
        language=language,
        vad_filter=True,
        initial_prompt=initial_prompt,
        condition_on_previous_text=False,
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
