"""Right panel: tabbed code editor + colourised diff viewer.

* ``CodeTab`` — editable plain-text editor with line numbers and syntax
  highlighting; Ctrl+S writes back through the sandboxed workspace.
* ``DiffTab`` — read-only unified-diff renderer (green additions, red
  deletions) used for live agent edits and ``git diff`` output.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from agentdesk.ui import theme
from agentdesk.ui.syntax import SyntaxHighlighter
from agentdesk.tools.workspace import Workspace


class _LineNumberArea(QWidget):
    """Gutter widget painting line numbers next to a CodeTab."""

    def __init__(self, editor: "CodeTab") -> None:
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.editor.line_number_area_width(), 0)

    def paintEvent(self, event) -> None:  # noqa: N802
        self.editor.line_number_area_paint_event(event)


class CodeTab(QPlainTextEdit):
    """Single-file editor tab with gutter + highlighting."""

    save_requested = Signal(str, str)  # rel_path, content

    def __init__(self, rel_path: str, content: str, language: str = "", parent=None) -> None:
        super().__init__(parent)
        self.rel_path = rel_path
        self.setFont(theme.mono_font(12))
        self.setPlainText(content)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)
        self.highlighter = SyntaxHighlighter(self.document(), language)
        self._line_area = _LineNumberArea(self)
        self.blockCountChanged.connect(self._update_line_number_area_width)
        self.updateRequest.connect(self._update_line_number_area)
        self._update_line_number_area_width(0)

    # -- gutter ------------------------------------------------------------
    def line_number_area_width(self) -> int:
        digits = max(3, len(str(self.blockCount())))
        return 12 + digits * self.fontMetrics().horizontalAdvance("9")

    def _update_line_number_area_width(self, _count: int) -> None:
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _update_line_number_area(self, rect: QRect, dy: int) -> None:
        if dy:
            self._line_area.scroll(0, dy)
        else:
            self._line_area.update(0, rect.y(), self._line_area.width(), rect.height())

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_area.setGeometry(QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()))

    def line_number_area_paint_event(self, event) -> None:
        painter = QPainter(self._line_area)
        painter.fillRect(event.rect(), QColor(theme.BG_PANEL))
        block = self.firstVisibleBlock()
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        bottom = top + self.blockBoundingRect(block).height()
        painter.setPen(QColor(theme.TEXT_MUTED))
        number = block.blockNumber() + 1
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.drawText(0, int(top), self._line_area.width() - 6,
                                 int(self.blockBoundingRect(block).height()),
                                 Qt.AlignRight | Qt.AlignVCenter, str(number))
            block = block.next()
            top = bottom
            bottom = top + self.blockBoundingRect(block).height()
            number += 1
        painter.end()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.keyCombination() == Qt.CTRL | Qt.Key_S:
            self.save_requested.emit(self.rel_path, self.toPlainText())
            return
        super().keyPressEvent(event)


_DIFF_CSS = f"""
<style>
pre {{ font-family: Consolas, 'Cascadia Mono', monospace; font-size: 12px; margin: 0; white-space: pre-wrap; }}
.diff-file {{ color: {theme.TEXT_MUTED}; font-weight: 600; margin-top: 8px; }}
.diff-add  {{ background: {theme.DIFF_ADD_BG}; color: #7ee787; }}
.diff-del  {{ background: {theme.DIFF_DEL_BG}; color: #ff9b95; }}
.diff-hunk {{ color: {theme.ACCENT}; }}
.diff-ctx  {{ color: {theme.TEXT_MUTED}; }}
</style>
"""


def diff_to_html(diff_text: str) -> str:
    """Convert unified diff text into themed HTML lines."""
    import html as _html

    if not diff_text.strip():
        return f"{_DIFF_CSS}<p style='color:{theme.TEXT_MUTED}'>Fark yok — içerik aynı.</p>"
    lines: list[str] = []
    for raw in diff_text.splitlines():
        escaped = _html.escape(raw)
        if raw.startswith(("+++", "---")):
            lines.append(f"<span class='diff-file'>{escaped}</span>")
        elif raw.startswith("@@"):
            lines.append(f"<span class='diff-hunk'>{escaped}</span>")
        elif raw.startswith("+"):
            lines.append(f"<span class='diff-add'>{escaped}</span>")
        elif raw.startswith("-"):
            lines.append(f"<span class='diff-del'>{escaped}</span>")
        else:
            lines.append(f"<span class='diff-ctx'>{escaped}</span>")
    return f"{_DIFF_CSS}<pre>{'<br/>'.join(lines)}</pre>"


class EditorPanel(QWidget):
    """Tab widget hosting code tabs and diff tabs."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.workspace: Workspace | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(8, 6, 8, 6)
        self.path_label = QLabel("Editör — dosya açık değil")
        self.path_label.setObjectName("mutedLabel")
        toolbar.addWidget(self.path_label)
        toolbar.addStretch(1)
        diff_btn = QPushButton("Git Diff Göster")
        diff_btn.clicked.connect(self._show_git_diff)
        toolbar.addWidget(diff_btn)

        layout.addLayout(toolbar)
        layout.addWidget(self.tabs, 1)

    # ------------------------------------------------------------------
    def bind_workspace(self, workspace: Workspace | None) -> None:
        self.workspace = workspace

    def open_file(self, rel_path: str) -> None:
        """Open (or focus) a workspace file in an editable tab."""
        if not self.workspace:
            return
        for i in range(self.tabs.count()):
            widget = self.tabs.widget(i)
            if isinstance(widget, CodeTab) and widget.rel_path == rel_path:
                self.tabs.setCurrentIndex(i)
                return
        try:
            data = self.workspace.read_text(rel_path)
        except Exception as exc:  # noqa: BLE001
            self.path_label.setText(f"Açılamadı: {exc}")
            return
        language = os.path.splitext(rel_path)[1].lstrip(".").lower()
        tab = CodeTab(rel_path, data["content"], language)
        tab.save_requested.connect(self._save_tab)
        idx = self.tabs.addTab(tab, os.path.basename(rel_path))
        self.tabs.setCurrentIndex(idx)
        self.path_label.setText(rel_path)

    def show_diff(self, title: str, diff_text: str) -> None:
        """Open (or refresh) a diff tab with colourised unified diff."""
        tab_name = f"Δ {title}"
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == tab_name:
                browser = self.tabs.widget(i)
                browser.setHtml(diff_to_html(diff_text))
                self.tabs.setCurrentIndex(i)
                return
        browser = QTextBrowser()
        browser.setOpenExternalLinks(False)
        browser.setHtml(diff_to_html(diff_text))
        idx = self.tabs.addTab(browser, tab_name)
        self.tabs.setCurrentIndex(idx)

    # ------------------------------------------------------------------
    def _save_tab(self, rel_path: str, content: str) -> None:
        if not self.workspace:
            return
        try:
            result = self.workspace.write_text(rel_path, content)
            self.path_label.setText(f"Kaydedildi: {rel_path}")
            if result.get("diff"):
                self.show_diff(rel_path, result["diff"])
        except Exception as exc:  # noqa: BLE001
            self.path_label.setText(f"Kaydetme hatası: {exc}")

    def _show_git_diff(self) -> None:
        from agentdesk.tools.git import GitError, GitManager

        if not self.workspace:
            return
        try:
            git = GitManager(str(self.workspace.root))
            diff = git.diff() or git.diff(staged=True)
            self.show_diff("git diff", diff or "(değişiklik yok)")
        except (GitError, Exception) as exc:  # noqa: BLE001
            self.show_diff("git diff", f"# Hata\n{exc}")

    def _close_tab(self, index: int) -> None:
        self.tabs.widget(index).deleteLater()
        self.tabs.removeTab(index)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(640, 480)
