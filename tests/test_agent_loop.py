"""End-to-end agent loop integration test against a mock Ollama server.

Scenario: the model first answers with a ``write_file`` tool call, receives
the OBSERVATION, then delivers a final answer. The test asserts the loop
streamed text, executed the tool (file really created), recorded usage and
finished cleanly — the full Codex-style cycle.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


def _tool_call_response(path: str, content: str) -> str:
    call = json.dumps({"tool": "write_file", "args": {"path": path, "content": content}})
    return f"Elbette, dosyayı oluşturuyorum.\n```tool\n{call}\n```"


FINAL_ANSWER = "Dosya başarıyla oluşturuldu ve doğrulandı. ✅"


class _AgentMockHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        messages = body.get("messages", [])
        last = messages[-1] if messages else {}

        if str(last.get("content", "")).startswith("OBSERVATION"):
            text = FINAL_ANSWER
        else:
            text = _tool_call_response("hello.txt", "merhaba ajan\n")

        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        frame = {"model": body.get("model", ""), "message": {"role": "assistant", "content": text}, "done": False}
        self.wfile.write((json.dumps(frame) + "\n").encode())
        final = {
            "model": body.get("model", ""),
            "message": {"role": "assistant", "content": ""},
            "done": True,
            "prompt_eval_count": 50,
            "eval_count": 10,
        }
        self.wfile.write((json.dumps(final) + "\n").encode())


@pytest.fixture()
def agent_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _AgentMockHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_full_agent_turn(qapp, workspace_dir, agent_server):
    from agentdesk.core.agent import AgentWorker
    from agentdesk.core.config import AppConfig
    from agentdesk.core.limits_store import LimitsStore
    from agentdesk.core.ollama_client import OllamaClient
    from agentdesk.core.usage_tracker import UsageTracker
    from agentdesk.tools.git import GitManager
    from agentdesk.tools.registry import ToolRegistry
    from agentdesk.tools.terminal import TerminalRunner
    from agentdesk.tools.workspace import Workspace

    config = AppConfig(max_retries=0, connect_timeout=2, read_timeout=10)
    client = OllamaClient(base_url=agent_server, model="mock-model", max_retries=0)
    db = str(workspace_dir / "usage.db")
    tracker = UsageTracker(db_path=db, limits_store=LimitsStore(db))
    workspace = Workspace(workspace_dir)
    registry = ToolRegistry(workspace, TerminalRunner(str(workspace_dir)), GitManager(str(workspace_dir)), tracker)

    history: list[dict] = []
    worker = AgentWorker(
        config=config,
        client=client,
        registry=registry,
        usage=tracker,
        history=history,
        user_message="hello.txt dosyası oluştur",
        session_id="integration-test",
    )

    events: dict = {"tools_started": [], "tools_finished": [], "warnings": [], "errors": [], "done": []}
    worker.signals.tool_started.connect(lambda p: events["tools_started"].append(p))
    worker.signals.tool_finished.connect(lambda r: events["tools_finished"].append(r))
    worker.signals.warning.connect(lambda m: events["warnings"].append(m))
    worker.signals.error.connect(lambda m: events["errors"].append(m))
    worker.signals.finished.connect(lambda s: events["done"].append(s))
    worker.signals.assistant_done.connect(lambda t: events.setdefault("turns", []).append(t))

    worker.run()  # synchronous in this thread; signals deliver directly

    # Tool executed: file really exists in the sandbox.
    created = workspace_dir / "hello.txt"
    assert created.exists()
    assert created.read_text(encoding="utf-8") == "merhaba ajan\n"

    # Exactly one tool cycle, then the final answer.
    assert [p["tool"] for p in events["tools_started"]] == ["write_file"]
    assert events["tools_finished"][0]["path"] == "hello.txt"
    assert "diff" in events["tools_finished"][0]
    assert FINAL_ANSWER in events["turns"][-1]

    # Persisted history keeps the clean [user, final-assistant] pair; the
    # intermediate tool-call turn deliberately stays out of the session file.
    roles = [m["role"] for m in history]
    assert roles == ["user", "assistant"]
    assert FINAL_ANSWER in history[-1]["content"]

    # Usage accounting happened live.
    snap = tracker.snapshot(session_id="integration-test")
    assert snap.requests == 2
    assert snap.tokens_total == 120  # 2 × (50 prompt + 10 completion)

    # No failures anywhere.
    assert events["errors"] == []
    assert events["warnings"] == []
    assert events["done"][0]["status"] == "completed"


def test_quota_blocks_agent_turn(qapp, workspace_dir, agent_server):
    """Exhausted quota must stop the loop before any model call."""
    from agentdesk.core.agent import AgentWorker
    from agentdesk.core.config import AppConfig
    from agentdesk.core.limits_store import LimitsStore, UsageLimits
    from agentdesk.core.ollama_client import OllamaClient
    from agentdesk.core.usage_tracker import UsageTracker
    from agentdesk.tools.registry import ToolRegistry
    from agentdesk.tools.terminal import TerminalRunner
    from agentdesk.tools.workspace import Workspace

    db = str(workspace_dir / "quota.db")
    store = LimitsStore(db)
    store.save(UsageLimits(max_requests_per_day=1))
    tracker = UsageTracker(db_path=db, limits_store=store)
    tracker.record_request(1, 1, session_id="s")  # exhaust the single request

    config = AppConfig(max_retries=0)
    worker = AgentWorker(
        config=config,
        client=OllamaClient(base_url=agent_server, max_retries=0),
        registry=ToolRegistry(Workspace(workspace_dir), TerminalRunner(str(workspace_dir)), None, tracker),
        usage=tracker,
        history=[],
        user_message="bu istek yapılamamalı",
        session_id="s",
    )
    finished: list[dict] = []
    warnings: list[str] = []
    worker.signals.finished.connect(finished.append)
    worker.signals.warning.connect(warnings.append)
    worker.run()

    assert finished and finished[0]["status"] == "quota_exceeded"
    assert finished[0]["requests"] == 0
    assert warnings and "sınır" in warnings[0].lower()
