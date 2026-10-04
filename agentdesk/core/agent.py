"""Autonomous agent loop.

The loop mirrors Codex/Cursor-style behaviour:

1. user message + conversation history are sent to the local Ollama model;
2. streamed deltas are surfaced to the UI in real time;
3. the model may emit one or more ``tool`` JSON calls which are executed
   inside the sandboxed workspace; observations are fed back and the loop
   repeats (up to ``max_tool_iterations``);
4. API failures and tool errors are logged with tracebacks, reported to the
   model and retried — the agent self-corrects instead of dying;
5. every LLM request and execution passes the live corporate quota checks.

The worker is a :class:`PySide6.QtCore.QObject` driven on a ``QThread`` so
the GUI never blocks; all communication happens through Qt signals.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import threading
import traceback
from typing import Any

from PySide6.QtCore import QObject, Signal

from agentdesk.core.config import AppConfig
from agentdesk.core.ollama_client import (
    OllamaAPIError,
    OllamaClient,
    OllamaConnectionError,
    OllamaError,
    OllamaTimeoutError,
)
from agentdesk.core.tokenizer import estimate_conversation_tokens, estimate_tokens
from agentdesk.core.tool_parser import extract_tool_calls
from agentdesk.core.usage_tracker import QuotaExceededError, UsageTracker
from agentdesk.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_TEMPLATE = """You are AgentDesk, an autonomous senior software engineer running locally inside the user's workspace directory. You operate like Codex/Cursor agents: you inspect files, write production-quality code, run commands, verify results and use git.

ENVIRONMENT
- Workspace root: {workspace}
- Platform: {platform}
- Date: {date}
- Primary model: {model}

TOOL PROTOCOL
To use tools, output one fenced block per tool call, exactly this shape:
```tool
{{"tool": "<name>", "args": {{...}}}}
```
You may emit several tool blocks in one reply; they run in order and their results come back as OBSERVATION messages. When you are finished, reply with the final answer and NO tool blocks.

AVAILABLE TOOLS
{tools}

RULES
1. Every file path is relative to the workspace root. Never escape it.
2. Prefer edit_file for small changes; write_file for new files or full rewrites.
3. After changing code, verify: read the file back and/or run tests or a quick command.
4. If a command fails, read the error output, fix the root cause, and retry — do not give up after one attempt.
5. Use git_init/git_add/git_commit to checkpoint meaningful progress with clear conventional messages.
6. Produce complete, working, production-ready code. NEVER emit placeholders, TODO stubs or pseudo-code.
7. Keep explanations concise; show key diffs/commands instead of restating whole files.
8. Respond in the same language the user writes in."""


class AgentSignals(QObject):
    """Signal bridge emitted by the agent worker thread."""

    text_delta = Signal(str)                      # streamed assistant text
    assistant_done = Signal(str)                  # full final text of one model turn
    tool_started = Signal(dict)                   # {"tool", "args", "iteration"}
    tool_finished = Signal(dict)                  # tool result payload
    warning = Signal(str)                         # quota / retry warnings
    error = Signal(str)                           # fatal error message
    finished = Signal(dict)                       # summary: tokens, requests, status
    retrying = Signal(int, str)                   # attempt number, reason


class AgentWorker(QObject):
    """Runs one user turn of the agent loop on a background thread."""

    def __init__(
        self,
        config: AppConfig,
        client: OllamaClient,
        registry: ToolRegistry,
        usage: UsageTracker,
        history: list[dict[str, Any]],
        user_message: str,
        session_id: str,
    ) -> None:
        super().__init__()
        self.signals = AgentSignals()
        self.config = config
        self.client = client
        self.registry = registry
        self.usage = usage
        self.history = history
        self.user_message = user_message
        self.session_id = session_id
        self._stop = threading.Event()
        self.total_tokens_in = 0
        self.total_tokens_out = 0
        self.requests_made = 0

    # ------------------------------------------------------------------
    def stop(self) -> None:
        """Request graceful cancellation (checked between iterations)."""
        self._stop.set()

    def _system_prompt(self) -> str:
        import platform

        return SYSTEM_PROMPT_TEMPLATE.format(
            workspace=self.registry.workspace.root,
            platform=platform.platform(),
            date=_dt.date.today().isoformat(),
            model=self.config.model,
            tools=self.registry.describe(),
        )

    # ------------------------------------------------------------------
    def run(self) -> None:  # noqa: C901 — single orchestration routine
        """Entry point invoked on the worker thread."""
        status = "completed"
        try:
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": self._system_prompt()},
                *self.history,
                {"role": "user", "content": self.user_message},
            ]

            for iteration in range(1, self.config.max_tool_iterations + 1):
                if self._stop.is_set():
                    status = "cancelled"
                    self.signals.warning.emit("Ajan durduruldu.")
                    break

                # Pre-flight quota check with prompt-size estimate.
                try:
                    estimate = estimate_conversation_tokens(messages)
                    self.usage.check_request(estimated_tokens=estimate, session_id=self.session_id)
                except QuotaExceededError as exc:
                    status = "quota_exceeded"
                    self.signals.warning.emit(f"⚠️ {exc}")
                    break

                # ---- model turn ------------------------------------
                try:
                    text, usage = self._stream_one_turn(messages)
                except QuotaExceededError as exc:
                    status = "quota_exceeded"
                    self.signals.warning.emit(f"⚠️ {exc}")
                    break
                except OllamaError as exc:
                    status = "api_error"
                    logger.error("Ollama failure: %s\n%s", exc, traceback.format_exc())
                    self.signals.error.emit(f"Ollama bağlantı hatası: {exc}")
                    break

                self.requests_made += 1
                tokens_in, tokens_out = usage
                self.usage.record_request(tokens_in, tokens_out, session_id=self.session_id)
                self.total_tokens_in += tokens_in
                self.total_tokens_out += tokens_out

                messages.append({"role": "assistant", "content": text})
                self.signals.assistant_done.emit(text)

                # ---- tool calls -------------------------------------
                calls = extract_tool_calls(text)
                if not calls:
                    break  # final answer reached

                if iteration >= self.config.max_tool_iterations:
                    self.signals.warning.emit("Azami araç yineleme sayısına ulaşıldı; döngü durduruldu.")
                    status = "iteration_limit"
                    break

                for call in calls:
                    if self._stop.is_set():
                        break
                    tool_name, args = call["tool"], call.get("args", {})
                    self.signals.tool_started.emit(
                        {"tool": tool_name, "args": args, "iteration": iteration}
                    )
                    result = self.registry.execute(tool_name, args)
                    self.signals.tool_finished.emit(result)
                    observation = json.dumps(result, ensure_ascii=False, default=str)
                    messages.append(
                        {
                            "role": "user",
                            "content": f"OBSERVATION [{tool_name}] =>\n{observation[:60000]}",
                        }
                    )

                if self._stop.is_set():
                    status = "cancelled"
                    break

            # Persist the user message + final assistant text into history.
            self.history.append({"role": "user", "content": self.user_message})
            if messages and messages[-1].get("role") == "assistant":
                self.history.append(messages[-1])

        except Exception as exc:  # noqa: BLE001 — last-resort guard
            status = "crashed"
            logger.error("Agent loop crashed: %s\n%s", exc, traceback.format_exc())
            self.signals.error.emit(f"Ajan döngüsü çöktü: {exc}")
        finally:
            self.signals.finished.emit(
                {
                    "status": status,
                    "requests": self.requests_made,
                    "tokens_in": self.total_tokens_in,
                    "tokens_out": self.total_tokens_out,
                }
            )

    # ------------------------------------------------------------------
    def _stream_one_turn(self, messages: list[dict[str, Any]]) -> tuple[str, tuple[int, int]]:
        """Stream one completion; returns (full_text, (tokens_in, tokens_out))."""
        buffer: list[str] = []
        tokens: tuple[int, int] = (0, 0)

        def on_retry(attempt: int, err: OllamaError) -> None:
            self.signals.retrying.emit(attempt, str(err))
            self.signals.warning.emit(f"🔁 API hatası, yeniden deneniyor ({attempt}. deneme): {err}")

        for chunk in self.client.chat_stream(
            messages,
            model=self.config.model,
            temperature=self.config.temperature,
            max_tokens=self.config.max_output_tokens,
            on_retry=on_retry,
        ):
            if self._stop.is_set():
                break
            if chunk.text:
                buffer.append(chunk.text)
                self.signals.text_delta.emit(chunk.text)
            if chunk.done:
                tokens = (chunk.prompt_tokens, chunk.completion_tokens)

        text = "".join(buffer)
        # Server omitted usage → fall back to deterministic estimates.
        if tokens == (0, 0):
            tokens = (estimate_conversation_tokens(messages), estimate_tokens(text))
        return text, tokens
