"""Ollama client tested against a local mock HTTP server.

The mock speaks the real Ollama wire protocol (NDJSON chat frames) so
streaming, token accounting, retries and error mapping are all exercised
end-to-end without a real model.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agentdesk.core.ollama_client import (
    OllamaAPIError,
    OllamaClient,
    OllamaConnectionError,
    OllamaTimeoutError,
)


class _OllamaHandler(BaseHTTPRequestHandler):
    fail_next = 0  # class-level: fail N chat attempts with HTTP 500

    def log_message(self, *args):  # silence test noise
        pass

    def do_GET(self):  # noqa: N802
        if self.path == "/api/version":
            self._json(200, {"version": "0.9.9-mock"})
        elif self.path == "/api/tags":
            self._json(200, {"models": [{"name": "qwen3.5-9b-abliterated"}, {"name": "llama3.1"}]})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        if self.path != "/api/chat":
            self._json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")

        if type(self).fail_next > 0:
            type(self).fail_next -= 1
            self._json(500, {"error": "simulated failure"})
            return

        assert body.get("stream") is True
        assert body.get("model")
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        for token in ("Merhaba ", "dünya", "!"):
            frame = {"model": body["model"], "message": {"role": "assistant", "content": token}, "done": False}
            self.wfile.write((json.dumps(frame) + "\n").encode())
        final = {
            "model": body["model"],
            "message": {"role": "assistant", "content": ""},
            "done": True,
            "prompt_eval_count": 111,
            "eval_count": 22,
            "total_duration": 1_500_000_000,
        }
        self.wfile.write((json.dumps(final) + "\n").encode())

    def _json(self, code: int, payload: dict):
        data = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture()
def mock_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _OllamaHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_version_and_health(mock_server):
    client = OllamaClient(base_url=mock_server, max_retries=0)
    assert client.version() == "0.9.9-mock"
    assert client.health() is True


def test_list_models(mock_server):
    client = OllamaClient(base_url=mock_server, max_retries=0)
    models = client.list_models()
    assert "qwen3.5-9b-abliterated" in models


def test_streaming_chunks_and_token_counts(mock_server):
    client = OllamaClient(base_url=mock_server, max_retries=0, model="qwen3.5-9b-abliterated")
    chunks = list(client.chat_stream([{"role": "user", "content": "hi"}]))
    text = "".join(c.text for c in chunks)
    assert text == "Merhaba dünya!"
    final = chunks[-1]
    assert final.done
    assert final.prompt_tokens == 111
    assert final.completion_tokens == 22
    assert final.total_duration_s == pytest.approx(1.5)


def test_http_5xx_raises_typed_error_no_blind_retry(mock_server, monkeypatch):
    # Server errors surface immediately as OllamaAPIError — the client does
    # NOT blindly re-POST chat generation on HTTP 5xx (that could duplicate
    # work); retries are reserved for connect/timeout failures.
    _OllamaHandler.fail_next = 1
    client = OllamaClient(base_url=mock_server, max_retries=3)
    with pytest.raises(OllamaAPIError) as exc:
        client.chat([{"role": "user", "content": "hi"}])
    assert exc.value.status_code == 500


def test_unreachable_server_raises_typed_error(monkeypatch):
    """An unreachable endpoint must raise a typed Ollama error.

    Depending on the OS network stack, an unused loopback port yields either
    an immediate "connection refused" (typical on Linux) or a connect timeout
    (typical on Windows runners); both are valid typed connectivity failures,
    so the test accepts both.
    """
    import socket as _socket

    # Bind-then-close an ephemeral port so the target is guaranteed unused.
    probe = _socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()

    monkeypatch.setattr("agentdesk.core.ollama_client.time.sleep", lambda _s: None)
    client = OllamaClient(base_url=f"http://127.0.0.1:{port}", max_retries=2, connect_timeout=2)
    with pytest.raises((OllamaConnectionError, OllamaTimeoutError)):
        client.chat([{"role": "user", "content": "hi"}])


def test_health_false_when_unreachable(monkeypatch):
    import socket as _socket

    probe = _socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()

    monkeypatch.setattr("agentdesk.core.ollama_client.time.sleep", lambda _s: None)
    client = OllamaClient(base_url=f"http://127.0.0.1:{port}", max_retries=0, connect_timeout=2)
    assert client.health() is False
