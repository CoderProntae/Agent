"""Center panel: interactive agent chat with live action cards.

Messages render as Markdown-capable bubbles; tool invocations appear as
collapsible "action cards" showing what the agent is doing right now
(``[AJAN] src/utils.py oluşturuluyor…``, ``[AJAN TERMİNALİ] pytest…``)
with status icons, arguments and truncated results.
"""

from __future__ import annotations

import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from agentdesk.core.markdown import md_to_html
from agentdesk.ui import theme


class MessageBubble(QFrame):
    """One chat message (user or assistant) with Markdown rendering."""

    def __init__(self, role: str, text: str = "", parent=None) -> None:
        super().__init__(parent)
        self.role = role
        accent = "#1f6feb" if role == "user" else theme.BG_RAISED
        self.setStyleSheet(
            f"MessageBubble {{ background: {accent if role == 'user' else theme.BG_RAISED}; "
            f"border: 1px solid {theme.BORDER}; border-radius: 10px; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 10)
        layout.setSpacing(2)

        header = QLabel("🧑 Kullanıcı" if role == "user" else "🤖 AgentDesk")
        header.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 11px; font-weight: 600;")
        layout.addWidget(header)

        self.body = QTextBrowser()
        self.body.setOpenExternalLinks(True)
        self.body.setStyleSheet(
            "QTextBrowser { border: none; background: transparent; }"
        )
        self.body.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.body.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.body.document().setDocumentMargin(2)
        self.body.document().contentsChanged.connect(self._fit_height)
        layout.addWidget(self.body)
        self.set_text(text)

    def _fit_height(self) -> None:
        doc_height = int(self.body.document().size().height()) + 6
        self.body.setFixedHeight(max(24, doc_height))

    def set_text(self, text: str) -> None:
        if self.role == "user":
            import html

            rendered = f"<p>{html.escape(text).replace(chr(10), '<br/>')}</p>"
        else:
            rendered = md_to_html(text)
        self.body.setHtml(theme.CHAT_CSS + rendered)
        self._fit_height()

    def append_delta(self, delta: str) -> None:
        self._raw = getattr(self, "_raw", "") + delta
        self.set_text(self._raw)


class ActionCard(QFrame):
    """Live execution card for one agent tool call."""

    TOOL_LABELS = {
        "write_file": "📝 Dosya yazılıyor",
        "edit_file": "✂️ Dosya düzenleniyor",
        "read_file": "📖 Dosya okunuyor",
        "list_files": "📂 Dizin listeleniyor",
        "rename_file": "🔁 Yeniden adlandırılıyor",
        "delete_file": "🗑 Siliniyor",
        "search_text": "🔍 Aranıyor",
        "run_command": "⌨️ [AJAN TERMİNALİ]",
        "git_init": "🌿 git init",
        "git_status": "🌿 git status",
        "git_diff": "🌿 git diff",
        "git_add": "🌿 git add",
        "git_commit": "🌿 git commit",
        "git_branch": "🌿 git branch",
        "git_log": "🌿 git log",
    }

    def __init__(self, tool: str, args: dict, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            f"ActionCard {{ background: {theme.BG_PANEL}; border: 1px solid {theme.BORDER}; "
            f"border-left: 3px solid {theme.ACCENT}; border-radius: 8px; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 8)
        layout.setSpacing(3)

        header_row = QHBoxLayout()
        self.status_icon = QLabel("⏳")
        title_text = self.TOOL_LABELS.get(tool, f"🔧 {tool}")
        detail = args.get("path") or args.get("command") or args.get("pattern") or ""
        if detail:
            title_text += f": `{detail}`"
        self.title = QLabel(title_text)
        self.title.setObjectName("toolCardTitle")
        header_row.addWidget(self.status_icon)
        header_row.addWidget(self.title, 1)
        layout.addLayout(header_row)

        if args:
            args_label = QLabel(json.dumps(args, ensure_ascii=False)[:300])
            args_label.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 11px;")
            args_label.setWordWrap(True)
            layout.addWidget(args_label)

        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setFont(theme.mono_font(10))
        self.detail.setFixedHeight(0)
        self.detail.setStyleSheet(
            f"QPlainTextEdit {{ background: {theme.CODE_BG}; border: 1px solid {theme.BORDER}; border-radius: 6px; }}"
        )
        layout.addWidget(self.detail)

    def set_running(self) -> None:
        self.status_icon.setText("⏳")

    def set_result(self, result: dict) -> None:
        error = result.get("error")
        if error:
            self.status_icon.setText("❌")
            self.setStyleSheet(
                f"ActionCard {{ background: {theme.BG_PANEL}; border: 1px solid {theme.BORDER}; "
                f"border-left: 3px solid {theme.RED}; border-radius: 8px; }}"
            )
        else:
            self.status_icon.setText("✅")
            self.setStyleSheet(
                f"ActionCard {{ background: {theme.BG_PANEL}; border: 1px solid {theme.BORDER}; "
                f"border-left: 3px solid {theme.GREEN}; border-radius: 8px; }}"
            )
        summary = json.dumps(result, ensure_ascii=False, default=str)
        self.detail.setPlainText(summary[:4000])
        lines = min(8, summary.count("\n") + 1)
        self.detail.setFixedHeight(max(28, min(160, lines * 16 + 14)))


class ChatPanel(QWidget):
    """Scrolling message list + input box."""

    send_requested = Signal(str)
    stop_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Warning banner (quota etc.) — hidden until needed.
        self.banner = QLabel()
        self.banner.setObjectName("warningBanner")
        self.banner.setWordWrap(True)
        self.banner.setVisible(False)
        layout.addWidget(self.banner)

        # Scroll area hosting the message column.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self.column = QWidget()
        self.column_layout = QVBoxLayout(self.column)
        self.column_layout.setContentsMargins(14, 14, 14, 14)
        self.column_layout.setSpacing(10)
        self.column_layout.addStretch(1)
        scroll.setWidget(self.column)
        layout.addWidget(scroll, 1)
        self._scroll_area = scroll

        # Input row.
        input_row = QHBoxLayout()
        input_row.setContentsMargins(12, 8, 12, 12)
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("Ajana bir görev yazın… (Enter gönderir, Shift+Enter yeni satır)")
        self.input.setFixedHeight(76)
        self.input.installEventFilter(self)
        input_row.addWidget(self.input, 1)

        buttons = QVBoxLayout()
        self.send_btn = QPushButton("▶ Gönder")
        self.send_btn.setObjectName("primaryBtn")
        self.send_btn.clicked.connect(self._send)
        self.stop_btn = QPushButton("⏹ Durdur")
        self.stop_btn.setObjectName("dangerBtn")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_requested.emit)
        buttons.addWidget(self.send_btn)
        buttons.addWidget(self.stop_btn)
        input_row.addLayout(buttons)
        layout.addLayout(input_row)

        self._current_assistant: MessageBubble | None = None
        self._cards: dict[int, ActionCard] = {}
        self._card_seq = 0

    # ------------------------------------------------------------------
    def _insert(self, widget: QWidget) -> None:
        self.column_layout.insertWidget(self.column_layout.count() - 1, widget)
        self._scroll_to_bottom()

    def _scroll_to_bottom(self) -> None:
        from PySide6.QtCore import QTimer

        QTimer.singleShot(30, lambda: self._scroll_area.verticalScrollBar().setValue(
            self._scroll_area.verticalScrollBar().maximum()))

    # -- public API -------------------------------------------------------
    def clear_messages(self) -> None:
        while self.column_layout.count() > 1:
            item = self.column_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._current_assistant = None
        self._cards.clear()

    def add_user_message(self, text: str) -> None:
        self._insert(MessageBubble("user", text))
        self._current_assistant = None

    def begin_assistant_message(self) -> MessageBubble:
        bubble = MessageBubble("assistant", "")
        bubble._raw = ""  # noqa: SLF001 — intentional seed
        self._insert(bubble)
        self._current_assistant = bubble
        return bubble

    def append_assistant_delta(self, delta: str) -> None:
        if self._current_assistant is None:
            self.begin_assistant_message()
        assert self._current_assistant is not None
        self._current_assistant.append_delta(delta)
        self._scroll_to_bottom()

    def add_tool_card(self, payload: dict) -> int:
        self._card_seq += 1
        card = ActionCard(payload.get("tool", "?"), payload.get("args", {}))
        card.set_running()
        self._insert(card)
        self._cards[self._card_seq] = card
        return self._card_seq

    def update_tool_card(self, card_id: int | None, result: dict) -> None:
        """Mark the most recent (or given) card finished with its result."""
        card = self._cards.get(card_id) if card_id else (
            self._cards[max(self._cards)] if self._cards else None
        )
        if card is not None:
            card.set_result(result)
        self._scroll_to_bottom()

    def set_running(self, running: bool) -> None:
        self.send_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self.input.setEnabled(True)

    def show_banner(self, text: str, kind: str = "warning") -> None:
        self.banner.setObjectName("errorBanner" if kind == "error" else "warningBanner")
        self.banner.style().unpolish(self.banner)
        self.banner.style().polish(self.banner)
        self.banner.setText(text)
        self.banner.setVisible(True)

    def hide_banner(self) -> None:
        self.banner.setVisible(False)

    def restore_history(self, messages: list[dict]) -> None:
        """Re-render a persisted session (user/assistant pairs only)."""
        self.clear_messages()
        for message in messages:
            role = message.get("role")
            content = message.get("content", "")
            if role == "user":
                self.add_user_message(content)
            elif role == "assistant":
                bubble = MessageBubble("assistant", content)
                self._insert(bubble)
                self._current_assistant = bubble

    # ------------------------------------------------------------------
    def _send(self) -> None:
        text = self.input.toPlainText().strip()
        if not text:
            return
        self.input.clear()
        self.send_requested.emit(text)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self.input and event.type() == event.Type.KeyPress:
            from PySide6.QtGui import KeyEvent

            key_event: KeyEvent = event
            if key_event.key() in (Qt.Key_Return, Qt.Key_Enter) and not (
                key_event.modifiers() & Qt.ShiftModifier
            ):
                self._send()
                return True
        return super().eventFilter(obj, event)
