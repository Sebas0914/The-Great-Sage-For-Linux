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
                 max_tokens: int = 2048, reasoning_effort: str = ""):
        self.api_key = (api_key or "").strip()
        self.model = model.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.reasoning_effort = (reasoning_effort or "").strip()

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

    def _payload(self, messages, stream=False, tools=None, response_format=None):
        body = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if tools:
            body["tools"] = tools
        if response_format:
            body["response_format"] = response_format
        if self.reasoning_effort:
            body["reasoning_effort"] = self.reasoning_effort
        return body

    def _post(self, messages, stream=False, tools=None, response_format=None):
        if not self.model:
            raise ModelProviderError("NVIDIA provider has no model configured.")
        if self.is_remote and not self.api_key:
            raise ModelProviderError("NVIDIA API key is not configured.")
        try:
            return requests.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=self._payload(messages, stream, tools, response_format),
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

    def chat_raw(self, messages, tools=None, response_format=None):
        response = self._post(messages, tools=tools, response_format=response_format)
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
    """Route turns between fast/complex NVIDIA models with local fallback."""

    COMPLEX_MARKERS = (
        "debug", "debugging", "error", "exception", "traceback", "stack trace",
        "program", "programming", "code", "codigo", "código", "python", "flutter",
        "javascript", "linux", "git", "github", "repo", "repository", "project",
        "proyecto", "architecture", "arquitectura", "refactor", "implement",
        "implementation", "implementa", "analiza", "analyze", "analysis",
        "explica en detalle", "paso a paso", "multiple files", "varios archivos",
        "document", "documento", "long context", "why does", "por qué",
    )
    CLASSIFIER_MIN_CHARS = 80
    CLASSIFIER_MAX_CHARS = 1399

    def __init__(self, fast: NvidiaProvider, complex_provider: NvidiaProvider,
                 fallback: ModelProvider = None):
        self.fast = fast
        self.complex = complex_provider
        self.fallback = fallback
        self.last_route = "fast"
        self.last_provider = "nvidia"
        self.last_classification = ""

    @staticmethod
    def _user_text(messages):
        for message in reversed(messages):
            if message.get("role") == "user":
                return str(message.get("content") or "").strip()
        return ""

    @classmethod
    def _obvious_complex(cls, text):
        low = text.lower()
        return len(text) >= 1400 or any(marker in low for marker in cls.COMPLEX_MARKERS)

    def _classify(self, text):
        if not (self.CLASSIFIER_MIN_CHARS <= len(text) <= self.CLASSIFIER_MAX_CHARS):
            return None
        prompt = [
            {"role": "system", "content":
                'Classify the request for routing. Return JSON only: {"route":"fast"} '
                'or {"route":"complex"}. Use complex for multi-step reasoning, difficult '
                'debugging, substantial code/project analysis, architecture, planning, '
                'or detailed synthesis. Use fast for ordinary conversation, simple '
                'explanations, short factual answers, and straightforward actions. '
                'Do not solve the request.'},
            {"role": "user", "content": text},
        ]
        try:
            result = self.fast.chat_raw(
                prompt, response_format={"type": "json_object"})
        except ModelProviderError:
            # Some OpenAI-compatible endpoints expose tool calling but not
            # structured response_format. Retry the tiny classifier with the
            # same provider and its JSON-only instruction instead of disabling
            # IA1 classification entirely.
            try:
                result = self.fast.chat_raw(prompt)
            except ModelProviderError:
                self.last_classification = ""
                return None
        try:
            raw = result.get("content") or ""
            route = str(json.loads(raw).get("route", "")).strip().lower()
            if route in {"fast", "complex"}:
                self.last_classification = route
                return route == "complex"
        except (ValueError, TypeError, AttributeError, KeyError):
            pass
        self.last_classification = ""
        return None

    def _looks_complex(self, messages):
        text = self._user_text(messages)
        if self._obvious_complex(text):
            self.last_classification = "complex"
            return True
        classified = self._classify(text)
        if classified is not None:
            return classified
        self.last_classification = "fast"
        return False

    def _select(self, messages):
        provider = self.complex if self._looks_complex(messages) else self.fast
        self.last_route = "complex" if provider is self.complex else "fast"
        self.last_provider = "nvidia"
        return provider

    def _call_with_fallback(self, method, *args, **kwargs):
        provider = self._select(args[0])
        try:
            return getattr(provider, method)(*args, **kwargs)
        except ModelProviderError:
            if self.fallback is None:
                raise
            self.last_provider = "local-fallback"
            return getattr(self.fallback, method)(*args, **kwargs)

    def send_message(self, messages: List[Message]) -> str:
        return self._call_with_fallback("send_message", messages)

    def stream_response(self, messages: List[Message]) -> Iterator[str]:
        provider = self._select(messages)
        emitted = False
        try:
            for piece in provider.stream_response(messages):
                emitted = True
                yield piece
        except ModelProviderError:
            if self.fallback is None or emitted:
                raise
            self.last_provider = "local-fallback"
            yield from self.fallback.stream_response(messages)

    def chat_raw(self, messages, tools=None, response_format=None):
        return self._call_with_fallback(
            "chat_raw", messages, tools=tools, response_format=response_format)

    def get_available_models(self) -> List[str]:
        return list(dict.fromkeys(
            model for model in (self.fast.model, self.complex.model) if model
        ))

