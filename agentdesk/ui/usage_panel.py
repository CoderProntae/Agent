"""Left sidebar: live corporate usage statistics panel.

Polls the :class:`UsageTracker` every few seconds and renders request,
token, execution and active-time consumption as progress bars against the
encrypted quota policy. When quotas are exhausted the panel flips into a
red warning state and the main window disables agent actions.
"""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from agentdesk.core.usage_tracker import UsageTracker
from agentdesk.ui import theme


def _bar(value: int, maximum: int) -> QProgressBar:
    bar = QProgressBar()
    bar.setRange(0, max(1, int(maximum)))
    bar.setValue(min(int(value), int(maximum)))
    bar.setFormat(f"{value:,} / {maximum:,}")
    pct = 0 if maximum <= 0 else value / maximum
    if pct >= 1.0:
        bar.setObjectName("critBar")
    elif pct >= 0.8:
        bar.setObjectName("warnBar")
    return bar


class UsagePanel(QWidget):
    """Quota dashboard refreshed on a timer."""

    def __init__(self, usage: UsageTracker, session_id: str | None = None, parent=None) -> None:
        super().__init__(parent)
        self.usage = usage
        self.session_id = session_id

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(6)

        title = QLabel("KULLANIM KOTASI")
        title.setObjectName("sidebarTitle")
        layout.addWidget(title)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self._container = QVBoxLayout()
        layout.addLayout(self._container)
        layout.addStretch(1)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(3000)
        self.refresh()

    def set_session(self, session_id: str) -> None:
        self.session_id = session_id
        self.refresh()

    def refresh(self) -> None:
        try:
            snap = self.usage.snapshot(session_id=self.session_id)
            limits = self.usage.limits()
        except Exception:  # noqa: BLE001 — never let stats kill the UI
            return

        # Clear previous bars.
        while self._container.count():
            item = self._container.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        if not limits.enabled:
            self.status_label.setText("Kota denetimi devre dışı.")
        elif limits.developer_override:
            self.status_label.setText("🛠 Geliştirici geçersiz kılma aktif — sınırlar uygulanmıyor.")
        else:
            self.status_label.setText(f"Durum: aktif • {snap.date}")

        rows = [
            ("İstek (bugün)", snap.requests, limits.max_requests_per_day),
            ("Token (bugün)", snap.tokens_total, limits.max_tokens_per_day),
            ("Token (oturum)", snap.session_tokens, limits.max_tokens_per_session),
            ("Yürütme (bugün)", snap.executions, limits.max_executions_per_day),
            ("Aktif süre (dk)", int(snap.active_seconds // 60), limits.max_active_minutes_per_day),
        ]
        for label_text, value, maximum in rows:
            label = QLabel(label_text)
            label.setObjectName("mutedLabel")
            self._container.addWidget(label)
            self._container.addWidget(_bar(value, maximum))

    def heartbeat(self, seconds: float) -> None:
        """Called by the main window while it is the active app."""
        self.usage.add_active_seconds(seconds)
