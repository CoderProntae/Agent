"""Streaming HTTP client for a local Ollama server.

Design goals (per the product requirements):

* **Default endpoint ``http://localhost:11435``** — one off the stock
  ``11434`` on purpose; the port is fully configurable at runtime.
* **Chunked streaming** of chat completions (newline-delimited JSON frames)
  with incremental ``delta`` delivery to the UI.
* **Resilience**: exponential backoff + jitter retries for connect/timeout
  failures, strict timeout handling, HTTP keep-alive via a pooled
  ``requests.Session`` and typed exceptions the agent loop can react to.
* **Token accounting**: server-reported ``prompt_eval_count`` /
  ``eval_count`` are surfaced on the final chunk; callers fall back to the
  heuristic estimator when the server omits them.
"""

from __future__ import annotations

import json
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Iterator

import requests

from agentdesk.core.config import DEFAULT_MODEL, DEFAULT_OLLAMA_HOST, DEFAULT_OLLAMA_PORT

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
class OllamaError(Exception):
    """Base class for all Ollama client failures."""


class OllamaConnectionError(OllamaError):
    """The server could not be reached (refused / DNS / network down)."""


class OllamaTimeoutError(OllamaError):
    """A connect or read timeout occurred."""


class OllamaAPIError(OllamaError):
    """The server responded with an HTTP error or malformed payload."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Chunk model
# ---------------------------------------------------------------------------
@dataclass
class StreamChunk:
    """One incremental piece of a streamed completion."""

    text: str = ""
    done: bool = False
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_duration_s: float = 0.0
    model: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------
class OllamaClient:
    """Robust REST client for a local Ollama instance."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str = DEFAULT_MODEL,
        connect_timeout: float = 8.0,
        read_timeout: float = 600.0,
        max_retries: int = 3,
        retry_backoff: float = 1.8,
        keep_alive: str = "10m",
    ) -> None:
        host = DEFAULT_OLLAMA_HOST
        port = DEFAULT_OLLAMA_PORT
        self.base_url = (base_url or f"http://{host}:{port}").rstrip("/")
        self.model = model
        self.connect_timeout = float(connect_timeout)
        self.read_timeout = float(read_timeout)
        self.max_retries = max(0, int(max_retries))
        self.retry_backoff = float(retry_backoff)
        self.keep_alive = keep_alive

        # Pooled session → TCP keep-alive / connection reuse across calls.
        self._session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=4, pool_maxsize=8, max_retries=0
        )
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)
        self._session.headers.update(
            {"Content-Type": "application/json", "Connection": "keep-alive"}
        )
        # Some Ollama-compatible servers implement only /api/generate.
        # When /api/chat answers 404 we latch onto the generate endpoint.
        self._force_generate = False

    # -- helpers ------------------------------------------------------------
    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _sleep_backoff(self, attempt: int) -> float:
        delay = self.retry_backoff ** attempt + random.uniform(0, 0.25)
        time.sleep(min(delay, 15.0))
        return delay

    def _post(self, path: str, payload: dict[str, Any], stream: bool = False):
        """POST with retries. Retries happen only *before* the first byte."""
        url = self._url(path)
        last_error: OllamaError | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self._session.post(
                    url,
                    json=payload,
                    stream=stream,
                    timeout=(self.connect_timeout, self.read_timeout),
                )
            except requests.exceptions.ConnectTimeout as exc:
                last_error = OllamaTimeoutError(f"Bağlantı zaman aşımı: {url} ({exc})")
            except requests.exceptions.ReadTimeout as exc:
                # A read timeout mid-stream means generation stalled; retrying
                # would duplicate work, so callers decide via the raised error.
                raise OllamaTimeoutError(f"Okuma zaman aşımı: {url} ({exc})") from exc
            except requests.exceptions.Timeout as exc:
                last_error = OllamaTimeoutError(f"Zaman aşımı: {url} ({exc})")
            except requests.exceptions.ConnectionError as exc:
                last_error = OllamaConnectionError(f"Bağlantı kurulamadı: {url} ({exc})")
            except requests.exceptions.RequestException as exc:
                raise OllamaError(f"Beklenmeyen HTTP hatası: {exc}") from exc
            else:
                if response.status_code >= 400:
                    detail = response.text[:500]
                    raise OllamaAPIError(
                        f"Ollama HTTP {response.status_code}: {detail}",
                        status_code=response.status_code,
                    )
                return response
            if attempt < self.max_retries:
                delay = self._sleep_backoff(attempt)
                logger.warning(
                    "Ollama isteği başarısız (deneme %d/%d, %.1fs sonra tekrar): %s",
                    attempt + 1,
                    self.max_retries + 1,
                    delay,
                    last_error,
                )
        assert last_error is not None
        raise last_error

    def _get(self, path: str, timeout: float | None = None):
        url = self._url(path)
        try:
            response = self._session.get(url, timeout=timeout or self.connect_timeout)
        except requests.exceptions.Timeout as exc:
            raise OllamaTimeoutError(f"Zaman aşımı: {url}") from exc
        except requests.exceptions.ConnectionError as exc:
            raise OllamaConnectionError(f"Bağlantı kurulamadı: {url}") from exc
        except requests.exceptions.RequestException as exc:
            raise OllamaError(f"Beklenmeyen HTTP hatası: {exc}") from exc
        if response.status_code >= 400:
            raise OllamaAPIError(
                f"Ollama HTTP {response.status_code}: {response.text[:500]}",
                status_code=response.status_code,
            )
        return response

    # -- public API -----------------------------------------------------------
    def health(self) -> bool:
        """Cheap connectivity probe (``GET /api/version``)."""
        try:
            self.version()
            return True
        except OllamaError:
            return False

    def version(self) -> str:
        data = self._get("/api/version").json()
        return str(data.get("version", "unknown"))

    def list_models(self) -> list[str]:
        """Names of models installed on the server (``GET /api/tags``)."""
        data = self._get("/api/tags").json()
        models = data.get("models", []) if isinstance(data, dict) else []
        return [m.get("name", "") for m in models if m.get("name")]

    def chat(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        keep_alive: str | None = None,
        on_retry: Callable[[int, OllamaError], None] | None = None,
    ) -> str:
        """Blocking (non-streamed) chat completion. Returns final text."""
        final_text: list[str] = []
        for chunk in self.chat_stream(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            keep_alive=keep_alive,
            on_retry=on_retry,
        ):
            final_text.append(chunk.text)
        return "".join(final_text)

    def chat_stream(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        keep_alive: str | None = None,
        on_retry: Callable[[int, OllamaError], None] | None = None,
    ) -> Iterator[StreamChunk]:
        """Stream a chat completion, yielding :class:`StreamChunk` objects.

        Primary endpoint is ``POST /api/chat``. If the server answers
        **404** (Ollama-compatible backends that only expose the classic
        ``/api/generate`` route), the client transparently retries the turn
        against ``/api/generate`` with the conversation flattened into a
        prompt, and latches onto that endpoint for subsequent calls.

        ``on_retry`` (optional) is invoked whenever a full request attempt
        fails and is about to be retried, so the UI can surface the
        self-healing behaviour ("retrying…") instead of silently waiting.
        """
        chosen_model = model or self.model
        options: dict[str, Any] = {"temperature": temperature}
        if max_tokens:
            options["num_predict"] = int(max_tokens)

        if not self._force_generate:
            chat_payload: dict[str, Any] = {
                "model": chosen_model,
                "messages": messages,
                "stream": True,
                "keep_alive": keep_alive or self.keep_alive,
                "options": options,
            }
            try:
                response = self._post_with_notify(
                    "/api/chat", chat_payload, stream=True, on_retry=on_retry
                )
            except OllamaAPIError as exc:
                if exc.status_code == 404:
                    logger.warning(
                        "Sunucu /api/chat uç noktasını sunmuyor (404); "
                        "/api/generate kullanılıyor."
                    )
                    self._force_generate = True
                else:
                    raise
            else:
                return self._iter_stream(response)

        generate_payload: dict[str, Any] = {
            "model": chosen_model,
            "prompt": self._messages_to_prompt(messages),
            "stream": True,
            "keep_alive": keep_alive or self.keep_alive,
            "options": options,
        }
        response = self._post_with_notify(
            "/api/generate", generate_payload, stream=True, on_retry=on_retry
        )
        return self._iter_stream(response)

    @staticmethod
    def _messages_to_prompt(messages: list[dict[str, Any]]) -> str:
        """Flatten a chat history into a single prompt for /api/generate."""
        parts: list[str] = []
        for message in messages:
            role = message.get("role", "user")
            content = (message.get("content") or "").strip()
            if not content:
                continue
            if role == "system":
                parts.append(f"[SYSTEM]\n{content}")
            elif role == "assistant":
                parts.append(f"[ASSISTANT]\n{content}")
            else:
                parts.append(f"[USER]\n{content}")
        parts.append("[ASSISTANT]")
        return "\n\n".join(parts)

    def _post_with_notify(
        self,
        path: str,
        payload: dict[str, Any],
        stream: bool,
        on_retry: Callable[[int, OllamaError], None] | None,
    ):
        url = self._url(path)
        last_error: OllamaError | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self._session.post(
                    url,
                    json=payload,
                    stream=stream,
                    timeout=(self.connect_timeout, self.read_timeout),
                )
            except requests.exceptions.ReadTimeout as exc:
                raise OllamaTimeoutError(f"Okuma zaman aşımı: {url}") from exc
            except requests.exceptions.Timeout as exc:
                last_error = OllamaTimeoutError(f"Zaman aşımı: {url} ({exc})")
            except requests.exceptions.ConnectionError as exc:
                last_error = OllamaConnectionError(f"Bağlantı kurulamadı: {url} ({exc})")
            except requests.exceptions.RequestException as exc:
                raise OllamaError(f"Beklenmeyen HTTP hatası: {exc}") from exc
            else:
                if response.status_code >= 400:
                    raise OllamaAPIError(
                        f"Ollama HTTP {response.status_code}: {response.text[:500]}",
                        status_code=response.status_code,
                    )
                return response
            if attempt < self.max_retries:
                delay = self._sleep_backoff(attempt)
                logger.warning("Yeniden deneniyor (%d/%d): %s", attempt + 1, self.max_retries, last_error)
                if on_retry:
                    on_retry(attempt + 1, last_error)  # type: ignore[arg-type]
        assert last_error is not None
        raise last_error

    def _iter_stream(self, response: requests.Response) -> Iterator[StreamChunk]:
        """Parse newline-delimited JSON frames from a chunked response.

        Handles both wire formats: ``/api/chat`` frames carry the delta in
        ``message.content`` while classic ``/api/generate`` frames carry it
        in ``response``.
        """
        try:
            for raw_line in response.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                try:
                    frame = json.loads(raw_line)
                except json.JSONDecodeError:
                    logger.warning("Ollama akışında çözümlenemeyen çerçeve: %.200s", raw_line)
                    continue
                message = frame.get("message") or {}
                text = message.get("content") or frame.get("response") or ""
                yield StreamChunk(
                    text=text,
                    done=bool(frame.get("done", False)),
                    prompt_tokens=int(frame.get("prompt_eval_count", 0) or 0),
                    completion_tokens=int(frame.get("eval_count", 0) or 0),
                    total_duration_s=float(frame.get("total_duration", 0) or 0) / 1e9,
                    model=frame.get("model", ""),
                    raw=frame,
                )
        except requests.exceptions.ChunkedEncodingError as exc:
            raise OllamaConnectionError(f"Akış yarıda kesildi: {exc}") from exc
        except requests.exceptions.ReadTimeout as exc:
            raise OllamaTimeoutError("Akış sırasında okuma zaman aşımı") from exc
        finally:
            response.close()
