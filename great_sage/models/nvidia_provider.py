"""NVIDIA API / NIM provider.

NVIDIA's hosted API and self-hosted NIM expose an OpenAI-compatible
/v1/chat/completions interface. This provider intentionally uses requests
instead of an SDK so the same implementation can target either:
  https://integrate.api.nvidia.com/v1
or a local NIM base such as:
  http://localhost:8000/v1
"""

import json
from typing import Iterator, List

import requests

from great_sage.models.base import Message, ModelProvider, ModelProviderError


class NvidiaProvider(ModelProvider):
    def __init__(self, api_key: str = "", model: str = "",
                 base_url: str = "https://integrate.api.nvidia.com/v1",
                 timeout: int = 120, temperature: float = 0.2,
                 max_tokens: int = 2048):
        self.api_key = (api_key or "").strip()
        self.model = model.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.temperature = temperature
        self.max_tokens = max_tokens

    @property
    def is_remote(self) -> bool:
        return not self.base_url.startswith(("http://localhost", "http://127.0.0.1",
                                             "http://[::1]", "https://localhost",
                                             "https://127.0.0.1"))

    def _headers(self):
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _payload(self, messages, stream=False, tools=None):
        body = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if tools:
            body["tools"] = tools
        return body

    def _post(self, messages, stream=False, tools=None):
        if not self.model:
            raise ModelProviderError("NVIDIA provider has no model configured.")
        if self.is_remote and not self.api_key:
            raise ModelProviderError("NVIDIA API key is not configured.")
        try:
            return requests.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=self._payload(messages, stream, tools),
                timeout=self.timeout,
                stream=stream,
            )
        except requests.exceptions.ConnectionError as exc:
            raise ModelProviderError(
                f"Could not connect to NVIDIA endpoint {self.base_url}."
            ) from exc
        except requests.exceptions.Timeout as exc:
            raise ModelProviderError(
                f"NVIDIA did not respond within {self.timeout}s."
            ) from exc

    @staticmethod
    def _http_error(response):
        detail = ""
        try:
            detail = str(response.json().get("error", ""))[:400]
        except Exception:
            detail = (response.text or "")[:400]
        return f"NVIDIA returned HTTP {response.status_code}" + (
            f": {detail}" if detail else ".")

    def send_message(self, messages: List[Message]) -> str:
        response = self._post(messages)
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as exc:
            raise ModelProviderError(self._http_error(response)) from exc
        try:
            return response.json()["choices"][0]["message"].get("content") or ""
        except (ValueError, KeyError, IndexError) as exc:
            raise ModelProviderError("NVIDIA returned an unexpected response.") from exc

    def stream_response(self, messages: List[Message]) -> Iterator[str]:
        response = self._post(messages, stream=True)
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as exc:
            raise ModelProviderError(self._http_error(response)) from exc
        try:
            for line in response.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                chunk = json.loads(payload)
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                piece = delta.get("content") or ""
                if piece:
                    yield piece
        except (requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError) as exc:
            raise ModelProviderError("Lost connection to NVIDIA mid-response.") from exc
        except (ValueError, KeyError, IndexError) as exc:
            raise ModelProviderError("NVIDIA returned an invalid streaming response.") from exc

    def chat_raw(self, messages, tools=None):
        response = self._post(messages, tools=tools)
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as exc:
            raise ModelProviderError(self._http_error(response)) from exc
        try:
            return response.json()["choices"][0]["message"]
        except (ValueError, KeyError, IndexError) as exc:
            raise ModelProviderError("NVIDIA returned an unexpected tool response.") from exc

    def get_available_models(self) -> List[str]:
        if self.is_remote and not self.api_key:
            raise ModelProviderError("NVIDIA API key is not configured.")
        try:
            response = requests.get(
                f"{self.base_url}/models",
                headers=self._headers(), timeout=15)
            response.raise_for_status()
            return [m.get("id", "") for m in response.json().get("data", [])
                    if m.get("id")]
        except requests.exceptions.RequestException as exc:
            raise ModelProviderError("Could not query NVIDIA models.") from exc
        except (ValueError, KeyError) as exc:
            raise ModelProviderError("NVIDIA returned an invalid model list.") from exc

class NvidiaRoutingProvider(ModelProvider):
    """Route ordinary turns to a fast NVIDIA model and hard turns to a complex one."""

    COMPLEX_MARKERS = (
        "debug", "debugging", "error", "exception", "traceback", "stack trace",
        "program", "programming", "code", "codigo", "código", "python", "flutter",
        "javascript", "linux", "git", "github", "repo", "repository", "project",
        "proyecto", "architecture", "arquitectura", "refactor", "implement",
        "implementation", "implementa", "analiza", "analyze", "analysis",
        "explica en detalle", "paso a paso", "multiple files", "varios archivos",
        "document", "documento", "long context", "why does", "por qué",
    )

    def __init__(self, fast: NvidiaProvider, complex_provider: NvidiaProvider):
        self.fast = fast
        self.complex = complex_provider
        self.last_route = "fast"

    @classmethod
    def _looks_complex(cls, messages) -> bool:
        for message in reversed(messages):
            if message.get("role") != "user":
                continue
            text = str(message.get("content") or "").lower()
            if len(text) >= 1400:
                return True
            return any(marker in text for marker in cls.COMPLEX_MARKERS)
        return False

    def _select(self, messages):
        provider = self.complex if self._looks_complex(messages) else self.fast
        self.last_route = "complex" if provider is self.complex else "fast"
        return provider

    def send_message(self, messages: List[Message]) -> str:
        return self._select(messages).send_message(messages)

    def stream_response(self, messages: List[Message]) -> Iterator[str]:
        return self._select(messages).stream_response(messages)

    def chat_raw(self, messages, tools=None):
        return self._select(messages).chat_raw(messages, tools=tools)

    def get_available_models(self) -> List[str]:
        models = []
        for provider in (self.fast, self.complex):
            try:
                models.extend(provider.get_available_models())
            except ModelProviderError:
                continue
        return list(dict.fromkeys(models))
