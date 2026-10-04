"""Headless terminal execution subsystem.

Runs shell commands on behalf of the agent (or the user's manual console),
capturing combined stdout/stderr, the exit code and wall-clock duration.
Output streams line-by-line through an optional callback so the UI console
is live. Timeouts kill the entire process tree.

A pattern-based danger filter blocks clearly destructive commands
(``rm -rf /``, disk formatting, forced shutdown, …). The agent receives a
descriptive error; the manual console asks the user for confirmation.
"""

from __future__ import annotations

import logging
import os
import re
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

logger = logging.getLogger(__name__)

#: Commands that are never executed, no matter who asks.
DANGEROUS_PATTERNS: list[tuple[str, str]] = [
    (r"rm\s+(-[a-z]*f[a-z]*\s+)?(-[a-z]*r[a-z]*\s+)?(/|/\s|~|\$HOME)(\s|$)", "Kök dizini silme girişimi"),
    (r"rm\s+-[a-z]*\s+/\*", "Kök dizini silme girişimi"),
    (r"mkfs(\.[a-z0-9]+)?\s", "Dosya sistemi biçimlendirme"),
    (r"\bdd\s+.*of=/dev/", "Ham disk yazma"),
    (r":\(\)\s*{\s*:\|:&\s*}\s*;\s*:", "Fork bomb"),
    (r"(format|del|rmdir)\s+(/s|/q|/f)*\s*[a-zA-Z]:\\?\s*$", "Sürücü silme/biçimlendirme"),
    (r"shutdown\s|reboot\s*$|init\s+0|halt\s*$", "Sistemi kapatma/yeniden başlatma"),
    (r">\s*/dev/sd[a-z]", "Ham cihaza yazma"),
    (r"chmod\s+-R\s+777\s+/", "Kök dizin izinlerini bozma"),
]

DEFAULT_TIMEOUT = 300
MAX_OUTPUT_CHARS = 200_000


@dataclass
class ExecutionResult:
    """Outcome of one shell command."""

    command: str
    exit_code: int = -1
    output: str = ""
    duration: float = 0.0
    timed_out: bool = False
    blocked: bool = False
    block_reason: str = ""
    tail: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.blocked and not self.timed_out


def check_dangerous(command: str) -> str | None:
    """Return a human-readable block reason, or ``None`` if acceptable."""
    compact = " ".join(command.lower().split())
    for pattern, reason in DANGEROUS_PATTERNS:
        if re.search(pattern, compact):
            return reason
    return None


class TerminalRunner:
    """Executes shell commands with streaming capture and hard timeouts."""

    def __init__(self, default_cwd: str | None = None, default_timeout: int = DEFAULT_TIMEOUT):
        self.default_cwd = default_cwd
        self.default_timeout = default_timeout

    def run(
        self,
        command: str,
        cwd: str | None = None,
        timeout: int | None = None,
        on_line: Callable[[str], None] | None = None,
        allow_dangerous: bool = False,
        env: dict[str, str] | None = None,
    ) -> ExecutionResult:
        """Run ``command`` blocking until completion; stream lines via callback."""
        command = command.strip()
        if not command:
            return ExecutionResult(command=command, exit_code=-1, output="Boş komut.")

        reason = check_dangerous(command)
        if reason and not allow_dangerous:
            logger.warning("Blocked dangerous command: %r (%s)", command, reason)
            return ExecutionResult(command=command, blocked=True, block_reason=reason,
                                   output=f"[ENGELLENDİ] {reason}: {command}")

        workdir = cwd or self.default_cwd or os.getcwd()
        timeout = int(timeout or self.default_timeout)
        started = time.monotonic()
        collected: list[str] = []
        total_chars = 0

        creationflags = 0
        # POSIX: the child gets its OWN process group/session so a timeout
        # kill (killpg) can never signal the host application's group.
        start_new_session = sys.platform != "win32"
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

        merged_env = dict(os.environ)
        merged_env.setdefault("PYTHONUNBUFFERED", "1")
        if env:
            merged_env.update(env)

        try:
            proc = subprocess.Popen(
                command,
                shell=True,
                cwd=workdir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=merged_env,
                creationflags=creationflags,
                start_new_session=start_new_session,
            )
        except OSError as exc:
            return ExecutionResult(command=command, exit_code=-1, output=f"Başlatılamadı: {exc}")

        timed_out_event = threading.Event()

        def _watchdog() -> None:
            """Kill the process tree once the deadline passes."""
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out_event.set()
                self._kill_tree(proc)

        watchdog = threading.Thread(target=_watchdog, daemon=True)
        watchdog.start()

        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                if len(collected) < 5000 and total_chars < MAX_OUTPUT_CHARS:
                    collected.append(line.rstrip("\n"))
                    total_chars += len(line)
                    if on_line:
                        try:
                            on_line(line.rstrip("\n"))
                        except Exception:  # noqa: BLE001 — UI callback must not kill runner
                            logger.exception("on_line callback failed")
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            timed_out_event.set()
            self._kill_tree(proc)
        finally:
            if proc.poll() is None:
                timed_out_event.set()
                self._kill_tree(proc)

        timed_out = timed_out_event.is_set()
        duration = time.monotonic() - started
        exit_code = proc.returncode if proc.returncode is not None else -9
        output = "\n".join(collected)
        if timed_out:
            output += f"\n[ZAMAN AŞIMI] Komut {timeout} saniyede tamamlanmadı ve sonlandırıldı."
        logger.info(
            "Executed %r -> exit=%s timeout=%s (%.2fs)", command, exit_code, timed_out, duration
        )
        return ExecutionResult(
            command=command,
            exit_code=exit_code,
            output=output,
            duration=duration,
            timed_out=timed_out,
            tail=collected[-80:],
        )

    @staticmethod
    def _kill_tree(proc: subprocess.Popen) -> None:
        """Best-effort kill of the whole process tree."""
        try:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True, timeout=10, check=False,
                )
            else:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    proc.kill()
        except Exception:  # noqa: BLE001
            logger.exception("Failed to kill process tree for pid %s", proc.pid)
