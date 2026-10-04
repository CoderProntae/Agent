"""Bottom panel: embedded terminal console.

Shows live output of both agent-triggered executions and commands typed by
the user. Commands run through the same :class:`TerminalRunner` used by the
agent, so the danger filter, timeouts and quota accounting apply uniformly.
Command history is navigable with ↑/↓.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor, QTextCursor
from PySide6.QtWidgets import (
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from agentdesk.core.usage_tracker import QuotaExceededError, UsageTracker
from agentdesk.tools.terminal import TerminalRunner, check_dangerous
from agentdesk.ui import theme


class TerminalPanel(QWidget):
    """Console output view + command input line."""

    command_finished = Signal(object)  # ExecutionResult

    def __init__(self, runner: TerminalRunner, usage: UsageTracker, parent=None) -> None:
        super().__init__(parent)
        self.runner = runner
        self.usage = usage
        self._history: list[str] = []
        self._history_pos = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setFont(theme.mono_font(11))
        self.output.setStyleSheet(
            f"QPlainTextEdit {{ background: {theme.CODE_BG}; border: 1px solid {theme.BORDER}; }}"
        )
        self.output.setMaximumBlockCount(5000)

        self.input = QLineEdit()
        self.input.setPlaceholderText("Komut girin ve Enter'a basın (↑/↓ geçmiş, örn: pytest -q)…")
        self.input.setFont(theme.mono_font(11))
        self.input.returnPressed.connect(self._submit)
        self.input.installEventFilter(self)

        layout.addWidget(self.output, 1)
        layout.addWidget(self.input)

    # ------------------------------------------------------------------
    def append_line(self, text: str, color: str | None = None) -> None:
        """Append one coloured line to the console buffer."""
        cursor = self.output.textCursor()
        cursor.movePosition(QTextCursor.End)
        if color:
            cursor.insertText(text + "\n", self._char_format(color))
        else:
            cursor.insertText(text + "\n")
        self.output.setTextCursor(cursor)
        self.output.ensureCursorVisible()

    @staticmethod
    def _char_format(color: str):
        from PySide6.QtGui import QTextCharFormat

        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        return fmt

    def append_agent_command(self, command: str) -> None:
        self.append_line(f"[AJAN TERMİNALİ] $ {command}", theme.ACCENT)

    def append_agent_output(self, text: str) -> None:
        for line in text.splitlines():
            self.append_line(line)

    # ------------------------------------------------------------------
    def run_agent_command(self, command: str, timeout: int | None = None) -> None:
        """Mirror an agent-initiated execution into the console."""
        self.append_agent_command(command)
        result = self.runner.run(command, timeout=timeout,
                                 on_line=lambda l: self.append_line(l))
        if result.blocked:
            self.append_line(f"[ENGELLENDİ] {result.block_reason}", theme.RED)
        elif result.timed_out:
            self.append_line("[ZAMAN AŞIMI]", theme.YELLOW)
        self.command_finished.emit(result)

    def _submit(self) -> None:
        command = self.input.text().strip()
        if not command:
            return
        self.input.clear()
        self._history.append(command)
        self._history_pos = len(self._history)

        reason = check_dangerous(command)
        if reason:
            answer = QMessageBox.question(
                self, "Tehlikeli komut",
                f"Bu komut potansiyel olarak tehlikeli:\n\n{command}\n\n({reason})\n\nYine de çalıştırılsın mı?",
            )
            if answer != QMessageBox.Yes:
                self.append_line("[İPTAL] Kullanıcı vazgeçti.", theme.YELLOW)
                return

        try:
            self.usage.check_execution()
        except QuotaExceededError as exc:
            self.append_line(f"[KOTA] {exc}", theme.RED)
            return

        self.append_line(f"$ {command}", theme.GREEN)
        result = self.runner.run(command, on_line=lambda l: self.append_line(l))
        if not result.blocked:
            self.usage.record_execution()
        self.append_line(f"[çıkış kodu: {result.exit_code} — {result.duration:.2f}s]", theme.TEXT_MUTED)
        self.command_finished.emit(result)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        """Route ↑/↓ inside the input line into command history."""
        from PySide6.QtCore import Qt

        if obj is self.input and event.type() == event.Type.KeyPress:
            if event.key() == Qt.Key_Up:
                self._history_move(-1)
                return True
            if event.key() == Qt.Key_Down:
                self._history_move(1)
                return True
        return super().eventFilter(obj, event)

    # -- history navigation ----------------------------------------------
    def _history_move(self, delta: int) -> None:
        if not self._history:
            return
        self._history_pos = max(0, min(len(self._history), self._history_pos + delta))
        if self._history_pos < len(self._history):
            self.input.setText(self._history[self._history_pos])
        else:
            self.input.clear()
