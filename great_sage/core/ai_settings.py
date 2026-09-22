"""API keys and provider choice for Chat Mode's AI settings.

Keys are stored outside the application bundle and are never returned in full
to the UI. This module is platform-neutral; Windows ACL hardening is used only
when available.
"""

import json
import logging
import os
import subprocess
import tempfile
from typing import Any, Dict

from great_sage.models.base import ModelProvider, ModelProviderError
from great_sage.config import settings as _global_settings

log = logging.getLogger(__name__)

PROVIDERS = ("local", "nvidia", "nvidia_local", "anthropic", "openai")
TTS_PROVIDERS = ("f5", "elevenlabs", "openai")

DEFAULTS: Dict[str, Any] = {
    "chat_provider": "nvidia",
    "chat_model": "",
    "tts_provider": "f5",
    "keys": {},
    "allow_web": False,
    "allow_desktop": True,
    "mode": "companion",
    "auto_gaming": True,
    "web_tools_enabled": False,
    "local_only": False,
    "nvidia_fast_model": "",
    "nvidia_complex_model": "",
}


def _tighten(path: str) -> None:
    """Restrict the file to the current user where Windows ACLs exist."""
    if os.name != "nt":
        return
    try:
        user = os.environ.get("USERNAME")
        if not user:
            return
        subprocess.run(
            ["icacls", path, "/inheritance:r", "/grant:r", f"{user}:F"],
            capture_output=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        log.debug("Could not tighten permissions on the key file", exc_info=True)


def load(path: str) -> Dict[str, Any]:
    data = dict(DEFAULTS)
    data["keys"] = {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            stored = json.load(fh)
        if isinstance(stored, dict):
            for key, value in stored.items():
                if key in DEFAULTS:
                    data[key] = value
            if not isinstance(data.get("keys"), dict):
                data["keys"] = {}
    except FileNotFoundError:
        pass
    except Exception:
        log.exception("AI settings unreadable; using defaults")
    return data


def save(path: str, data: Dict[str, Any]) -> None:
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1)
        os.replace(tmp, path)
        _tighten(path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def mask(value: str) -> str:
    v = (value or "").strip()
    if not v:
        return ""
    return ("*" * max(4, len(v) - 4)) + v[-4:] if len(v) > 4 else "****"


def public_view(data: Dict[str, Any]) -> Dict[str, Any]:
    out = {key: value for key, value in data.items() if key != "keys"}
    out["keys"] = {
        name: mask(value) for name, value in (data.get("keys") or {}).items()
    }
    out["providers"] = list(PROVIDERS)
    try:
        from great_sage.core import modes as _modes
        out["modes"] = _modes.public_list()
    except Exception:
        out["modes"] = []
    out["tts_providers"] = list(TTS_PROVIDERS)
    return out


def apply_update(data: Dict[str, Any], update: Dict[str, Any]) -> Dict[str, Any]:
    for field in (
        "chat_provider", "chat_model", "tts_provider", "mode",
        "nvidia_fast_model", "nvidia_complex_model",
    ):
        if field in update and isinstance(update[field], str):
            data[field] = update[field]

    for field in (
        "allow_web", "allow_desktop", "auto_gaming",
        "web_tools_enabled", "local_only",
    ):
        if field in update:
            data[field] = bool(update[field])

    incoming = update.get("keys")
    if isinstance(incoming, dict):
        keys = dict(data.get("keys") or {})
        for name, value in incoming.items():
            value = (value or "").strip()
            if not value or set(value) <= {"*"} or value.startswith("*"):
                continue
            keys[name] = value
        data["keys"] = keys

    for name in update.get("clear_keys") or []:
        data.get("keys", {}).pop(name, None)
    return data


def web_allowed(data: Dict[str, Any]) -> bool:
    """Require both explicit permission and a mode that permits web access."""
    if not (data or {}).get("allow_web"):
        return False
    try:
        from great_sage.core import modes as _modes
        return _modes.get((data or {}).get("mode")).allow_web
    except Exception:
        return False


class FallbackProvider(ModelProvider):
    """Try one provider first, then a second provider only on failure."""

    def __init__(self, primary, secondary):
        self.primary = primary
        self.secondary = secondary
        self.last_provider = "primary"

    def send_message(self, messages):
        try:
            result = self.primary.send_message(messages)
            self.last_provider = "primary"
            return result
        except ModelProviderError:
            self.last_provider = "secondary"
            return self.secondary.send_message(messages)

    def stream_response(self, messages):
        emitted = False
        try:
            for piece in self.primary.stream_response(messages):
                emitted = True
                yield piece
            self.last_provider = "primary"
            return
        except ModelProviderError:
            if emitted:
                raise
        self.last_provider = "secondary"
        yield from self.secondary.stream_response(messages)

    def chat_raw(self, messages, tools=None, response_format=None):
        try:
            result = self.primary.chat_raw(
                messages, tools=tools, response_format=response_format)
            self.last_provider = "primary"
            return result
        except ModelProviderError:
            self.last_provider = "secondary"
            return self.secondary.chat_raw(
                messages, tools=tools, response_format=response_format)

    def get_available_models(self):
        return list(dict.fromkeys(
            self.primary.get_available_models() + self.secondary.get_available_models()
        ))


def build_provider(data, fallback):
    """Build the selected provider, enforcing local-only mode."""
    data = data or {}
    want = data.get("chat_provider") or "local"

    # Privacy and routing policy are enforced here, at provider construction,
    # rather than relying on the UI to keep the mode and provider in sync.
    try:
        from great_sage.core import modes as _modes
        mode = _modes.get(data.get("mode"))
    except Exception:
        mode = None
    routing = str(os.environ.get("GREAT_SAGE_AI_MODE", "nvidia_first")).lower()
    if bool(data.get("local_only")) or bool(getattr(_global_settings, "LOCAL_ONLY", False)) or (mode is not None and not mode.allow_online):
        return fallback, "Ollama / Local (local-only)"
    if routing == "local_only" or want == "local":
        return fallback, "Ollama / Local"

    try:
        from great_sage.config import settings
        keys = data.get("keys") or {}

        if want == "nvidia":
            key = str(keys.get("nvidia", "")).strip()
            if not key:
                return fallback, "Ollama / Local (NVIDIA key missing)"
            from great_sage.models.nvidia_provider import NvidiaProvider, NvidiaRoutingProvider
            fast_model = (
                data.get("nvidia_fast_model")
                or settings.NVIDIA_API_MODEL_FAST
            )
            complex_model = (
                data.get("nvidia_complex_model")
                or settings.NVIDIA_API_MODEL_COMPLEX
            )
            fast = NvidiaProvider(
                api_key=key,
                model=fast_model,
                base_url=settings.NVIDIA_API_BASE_URL,
                timeout=settings.NVIDIA_API_TIMEOUT,
                reasoning_budget=getattr(settings, "NVIDIA_FAST_REASONING_BUDGET", 0),
                enable_thinking=False,
            )
            complex_provider = NvidiaProvider(
                api_key=key,
                model=complex_model,
                base_url=settings.NVIDIA_API_BASE_URL,
                timeout=settings.NVIDIA_API_TIMEOUT,
                reasoning_budget=getattr(settings, "NVIDIA_COMPLEX_REASONING_BUDGET", 8192),
                enable_thinking=True,
            )
            remote = NvidiaRoutingProvider(
                fast, complex_provider, fallback=None
            )
            if routing == "local_first":
                return FallbackProvider(fallback, remote), "Local first / NVIDIA fallback"
            return NvidiaRoutingProvider(
                fast, complex_provider, fallback=fallback
            ), "NVIDIA API (fast/complex, local fallback)"

        if want == "nvidia_local":
            from great_sage.models.nvidia_provider import NvidiaProvider
            model = (
                data.get("nvidia_fast_model")
                or settings.NVIDIA_API_MODEL_FAST
            )
            base = os.environ.get(
                "GREAT_SAGE_NIM_BASE_URL", "http://localhost:8000/v1"
            )
            return NvidiaProvider(
                api_key="", model=model, base_url=base,
                timeout=settings.NVIDIA_API_TIMEOUT,
            ), "NVIDIA NIM / Local"

        key = str(keys.get(want, "")).strip()
        if not key:
            return fallback, "Ollama / Local (provider key missing)"

        model = data.get("chat_model") or ""
        if want == "anthropic":
            from great_sage.models.anthropic_provider import AnthropicProvider
            return AnthropicProvider(api_key=key, model=model), "Anthropic / Online"
        if want == "openai":
            from great_sage.models.openai_provider import OpenAIProvider
            return OpenAIProvider(api_key=key, model=model), "OpenAI / Online"
    except Exception:
        log.exception("Could not start provider %r; staying local", want)
        return fallback, "Ollama / Local"

    return fallback, "Ollama / Local"
