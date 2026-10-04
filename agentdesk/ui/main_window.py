"""Main application window — the Cursor/Codex-style multi-pane workspace.

Layout
------
* **Left sidebar**  — session switcher, workspace file tree, usage panel.
* **Center**        — agent chat with live action cards.
* **Right**         — tabbed code editor + diff viewer.
* **Bottom**        — embedded terminal console.
* **Status bar**    — Ollama connectivity, model, quota summary.

The window owns all long-lived services (config, usage tracker, Ollama
client, tool registry, agent worker thread) and routes their Qt signals.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QThread, QTimer
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from agentdesk import __app_name__, __version__
from agentdesk.core.agent import AgentWorker
from agentdesk.core.config import AppConfig, load_config, save_config
from agentdesk.core.logging_setup import setup_logging
from agentdesk.core.ollama_client import OllamaClient, OllamaError
from agentdesk.core.session_store import ChatSession, SessionStore
from agentdesk.core.usage_tracker import QuotaExceededError, UsageTracker
from agentdesk.tools.git import GitError, GitManager
from agentdesk.tools.registry import ToolRegistry
from agentdesk.tools.terminal import TerminalRunner
from agentdesk.tools.workspace import Workspace, WorkspaceError
from agentdesk.ui import theme
from agentdesk.ui.chat_panel import ChatPanel
from agentdesk.ui.editor_panel import EditorPanel
from agentdesk.ui.file_tree import FileTreePanel
from agentdesk.ui.settings_dialog import SettingsDialog
from agentdesk.ui.terminal_panel import TerminalPanel
from agentdesk.ui.usage_panel import UsagePanel

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Top-level desktop window wiring every subsystem together."""

    def __init__(self, config: AppConfig | None = None) -> None:
        super().__init__()
        setup_logging()
        self.config = config or load_config()
        self.usage = UsageTracker()
        self.sessions = SessionStore()
        self.workspace: Workspace | None = None
        self.registry: ToolRegistry | None = None
        self.runner = TerminalRunner(default_cwd=None, default_timeout=self.config.command_timeout)
        self.client = self._build_client()

        self.session: ChatSession = self.sessions.new_session(model=self.config.model)
        self._worker: AgentWorker | None = None
        self._worker_thread: QThread | None = None

        self.setWindowTitle(f"{__app_name__} — Yerel Yapay Zeka Kodlama Ajanı v{__version__}")
        self.resize(1520, 920)

        self._build_ui()
        self._build_menus()
        self._build_statusbar()

        if self.config.workspace_root:
            self.open_workspace(self.config.workspace_root, remember=False)

        # Heartbeat: account active time while the app is visible.
        self._heartbeat = QTimer(self)
        self._heartbeat.timeout.connect(lambda: self.usage_panel.heartbeat(15.0))
        self._heartbeat.start(15_000)

        # Connectivity poll for the status bar dot.
        self._conn_timer = QTimer(self)
        self._conn_timer.timeout.connect(self._poll_connection)
        self._conn_timer.start(20_000)
        QTimer.singleShot(300, self._poll_connection)

    # ------------------------------------------------------------------
    def _build_client(self) -> OllamaClient:
        return OllamaClient(
            base_url=self.config.base_url,
            model=self.config.model,
            connect_timeout=self.config.connect_timeout,
            read_timeout=self.config.read_timeout,
            max_retries=self.config.max_retries,
            retry_backoff=self.config.retry_backoff,
            keep_alive=self.config.keep_alive,
        )

    # -- UI construction ------------------------------------------------
    def _build_ui(self) -> None:
        # Left sidebar -----------------------------------------------------
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(8, 8, 8, 8)
        sidebar_layout.setSpacing(8)

        session_title = QLabel("OTURUMLAR")
        session_title.setObjectName("sidebarTitle")
        sidebar_layout.addWidget(session_title)

        session_row = QHBoxLayout()
        self.new_session_btn = QPushButton("＋ Yeni")
        self.new_session_btn.clicked.connect(self._new_session)
        self.del_session_btn = QPushButton("🗑")
        self.del_session_btn.setFixedWidth(40)
        self.del_session_btn.clicked.connect(self._delete_session)
        session_row.addWidget(self.new_session_btn, 1)
        session_row.addWidget(self.del_session_btn)
        sidebar_layout.addLayout(session_row)

        self.session_list = QListWidget()
        self.session_list.setFixedHeight(130)
        self.session_list.itemClicked.connect(self._switch_session)
        sidebar_layout.addWidget(self.session_list)

        ws_row = QHBoxLayout()
        self.open_ws_btn = QPushButton("📁 Çalışma Alanı Aç")
        self.open_ws_btn.clicked.connect(self._choose_workspace)
        ws_row.addWidget(self.open_ws_btn)
        sidebar_layout.addLayout(ws_row)
        self.ws_label = QLabel("Çalışma alanı bağlı değil")
        self.ws_label.setObjectName("mutedLabel")
        self.ws_label.setWordWrap(True)
        sidebar_layout.addWidget(self.ws_label)

        self.file_tree = FileTreePanel()
        sidebar_layout.addWidget(self.file_tree, 3)

        self.usage_panel = UsagePanel(self.usage)
        sidebar_layout.addWidget(self.usage_panel, 2)
        sidebar.setFixedWidth(300)
        self.sidebar = sidebar

        # Center: chat ------------------------------------------------------
        self.chat = ChatPanel()
        self.chat.send_requested.connect(self._on_user_message)
        self.chat.stop_requested.connect(self._stop_agent)

        # Right: editor ------------------------------------------------------
        self.editor = EditorPanel()

        # Bottom: terminal -------------------------------------------------
        self.terminal = TerminalPanel(self.runner, self.usage)

        center_split = QSplitter(Qt.Vertical)
        horiz = QSplitter(Qt.Horizontal)
        horiz.addWidget(self.chat)
        horiz.addWidget(self.editor)
        horiz.setStretchFactor(0, 5)
        horiz.setStretchFactor(1, 6)
        center_split.addWidget(horiz)
        center_split.addWidget(self.terminal)
        center_split.setStretchFactor(0, 4)
        center_split.setStretchFactor(1, 1)

        root = QSplitter(Qt.Horizontal)
        root.addWidget(sidebar)
        root.addWidget(center_split)
        root.setStretchFactor(0, 0)
        root.setStretchFactor(1, 1)
        self.setCentralWidget(root)

        self.file_tree.file_open_requested.connect(self.editor.open_file)
        self._refresh_session_list()

    def _build_menus(self) -> None:
        bar = self.menuBar()

        file_menu = bar.addMenu("&Dosya")
        file_menu.addAction("Çalışma Alanı Aç…", self._choose_workspace, Qt.CTRL | Qt.Key_O)
        file_menu.addAction("Ayarlar…", self.open_settings, Qt.CTRL | Qt.Key_Comma)
        file_menu.addSeparator()
        file_menu.addAction("Çıkış", self.close, Qt.CTRL | Qt.Key_Q)

        agent_menu = bar.addMenu("&Ajan")
        agent_menu.addAction("Yeni Oturum", self._new_session, Qt.CTRL | Qt.Key_N)
        agent_menu.addAction("Ajanı Durdur", self._stop_agent, Qt.CTRL | Qt.Key_Period)

        view_menu = bar.addMenu("&Görünüm")
        view_menu.addAction("Kotayı Yenile", self.usage_panel.refresh)
        view_menu.addAction("Dosya Ağacını Yenile", self.file_tree.refresh)

        help_menu = bar.addMenu("&Yardım")
        help_menu.addAction("Hakkında", self._about)

    def _build_statusbar(self) -> None:
        self.conn_label = QLabel("● Ollama: kontrol ediliyor…")
        self.model_label = QLabel(f"model: {self.config.model}")
        self.quota_label = QLabel("")
        status = self.statusBar()
        status.addWidget(self.conn_label)
        status.addPermanentWidget(self.model_label)
        status.addPermanentWidget(self.quota_label)

    # -- workspace ---------------------------------------------------------
    def _choose_workspace(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Çalışma alanı klasörü seçin")
        if directory:
            self.open_workspace(directory)

    def open_workspace(self, directory: str, remember: bool = True) -> None:
        try:
            self.workspace = Workspace(directory)
        except WorkspaceError as exc:
            QMessageBox.critical(self, "Çalışma alanı hatası", str(exc))
            return
        self.runner.default_cwd = str(self.workspace.root)
        try:
            git = GitManager(str(self.workspace.root))
        except GitError:
            git = None
            logger.warning("git not available on PATH; git tools disabled")
        self.registry = ToolRegistry(self.workspace, self.runner, git, self.usage)
        self.file_tree.bind_workspace(self.workspace)
        self.editor.bind_workspace(self.workspace)
        self.ws_label.setText(str(self.workspace.root))
        self.session.workspace = str(self.workspace.root)
        if remember:
            self.config.workspace_root = str(self.workspace.root)
            save_config(self.config)
        self.chat.show_banner(
            f"✅ Çalışma alanı bağlandı: {self.workspace.root} — tüm ajan eylemleri bu dizinle sınırlıdır."
        )
        QTimer.singleShot(6000, self.chat.hide_banner)

    # -- sessions --------------------------------------------------------
    def _refresh_session_list(self, select_id: str | None = None) -> None:
        self.session_list.clear()
        for session in self.sessions.list_sessions():
            item = QListWidgetItem(f"{session.title[:32]}")
            item.setData(Qt.UserRole, session.id)
            self.session_list.addItem(item)
            if session.id == (select_id or self.session.id):
                self.session_list.setCurrentItem(item)

    def _new_session(self) -> None:
        self._persist_current_session()
        self.session = self.sessions.new_session(
            workspace=str(self.workspace.root) if self.workspace else "",
            model=self.config.model,
        )
        self.chat.clear_messages()
        self.chat.hide_banner()
        self.usage_panel.set_session(self.session.id)
        self._refresh_session_list()

    def _switch_session(self, item: QListWidgetItem) -> None:
        session_id = item.data(Qt.UserRole)
        if session_id == self.session.id:
            return
        self._persist_current_session()
        loaded = self.sessions.load(session_id)
        if loaded is None:
            return
        self.session = loaded
        self.chat.restore_history(loaded.messages)
        self.usage_panel.set_session(loaded.id)

    def _delete_session(self) -> None:
        item = self.session_list.currentItem()
        if not item:
            return
        session_id = item.data(Qt.UserRole)
        if session_id == self.session.id:
            self._new_session()
        self.sessions.delete(session_id)
        self._refresh_session_list()

    def _persist_current_session(self) -> None:
        if not self.session.messages and self.session.title == "Yeni Oturum":
            return
        self.sessions.save(self.session)
        self._refresh_session_list()

    # -- agent orchestration ------------------------------------------------
    def _on_user_message(self, text: str) -> None:
        if self._worker is not None:
            return  # already running
        if self.workspace is None or self.registry is None:
            QMessageBox.warning(
                self, "Çalışma alanı gerekli",
                "Ajana görev vermeden önce bir çalışma alanı klasörü açın (Dosya → Çalışma Alanı Aç).",
            )
            return

        # Live quota gate before spending any tokens.
        try:
            from agentdesk.core.tokenizer import estimate_tokens

            self.usage.check_request(estimated_tokens=estimate_tokens(text),
                                     session_id=self.session.id)
        except QuotaExceededError as exc:
            self.chat.show_banner(f"⚠️ {exc}", kind="error")
            self.usage_panel.refresh()
            return

        if not self.session.messages:
            self.session.title = text[:48]

        self.chat.hide_banner()
        self.chat.add_user_message(text)
        self.chat.set_running(True)

        self._worker = AgentWorker(
            config=self.config,
            client=self.client,
            registry=self.registry,
            usage=self.usage,
            history=self.session.messages,
            user_message=text,
            session_id=self.session.id,
        )
        self._worker_thread = QThread(self)
        self._worker.moveToThread(self._worker_thread)

        signals = self._worker.signals
        signals.text_delta.connect(self.chat.append_assistant_delta)
        signals.assistant_done.connect(self._on_assistant_done)
        signals.tool_started.connect(self._on_tool_started)
        signals.tool_finished.connect(self._on_tool_finished)
        signals.warning.connect(lambda msg: self.chat.show_banner(msg))
        signals.error.connect(lambda msg: self.chat.show_banner(msg, kind="error"))
        signals.retrying.connect(lambda attempt, reason: logger.warning("Retry %s: %s", attempt, reason))
        signals.finished.connect(self._on_run_finished)

        self._worker_thread.started.connect(self._worker.run)
        self._worker_thread.start()

    def _on_assistant_done(self, text: str) -> None:
        # Each model turn closes the current bubble; the next turn (after
        # tool observations) opens a fresh one.
        self.chat._current_assistant = None  # noqa: SLF001
        if text.strip():
            self.session.messages.append({"role": "assistant", "content": text})

    def _on_tool_started(self, payload: dict) -> None:
        card_id = self.chat.add_tool_card(payload)
        self._pending_card = card_id
        if payload.get("tool") == "run_command":
            self.terminal.append_agent_command(str(payload.get("args", {}).get("command", "")))

    def _on_tool_finished(self, result: dict) -> None:
        card_id = getattr(self, "_pending_card", None)
        self.chat.update_tool_card(card_id, result)
        self._pending_card = None
        path = result.get("path")
        diff = result.get("diff")
        if path and diff:
            self.editor.show_diff(path, diff)
        if result.get("error"):
            logger.warning("Tool error fed back to model: %s", result["error"])
        self.file_tree.refresh()
        self.usage_panel.refresh()

    def _on_run_finished(self, summary: dict) -> None:
        self.chat.set_running(False)
        self.session.model = self.config.model
        self._persist_current_session()
        self.usage_panel.refresh()
        self._update_quota_status()

        status = summary.get("status")
        if status == "quota_exceeded":
            self.chat.show_banner("⚠️ Kurumsal kullanım kotasına ulaşıldı — ajan eylemleri devre dışı.", kind="error")
        elif status == "api_error":
            self.chat.show_banner("⚠️ Ollama sunucusuna ulaşılamadı. Ayarlar'dan bağlantıyı kontrol edin.", kind="error")
        logger.info("Agent run finished: %s", summary)

        if self._worker_thread is not None:
            self._worker_thread.quit()
            self._worker_thread.wait(3000)
        self._worker = None
        self._worker_thread = None

    def _stop_agent(self) -> None:
        if self._worker is not None:
            self._worker.stop()

    # -- misc ----------------------------------------------------------------
    def open_settings(self) -> None:
        dialog = SettingsDialog(self.config, self)
        if dialog.exec():
            self.client = self._build_client()
            self.runner.default_timeout = self.config.command_timeout
            self.model_label.setText(f"model: {self.config.model}")
            self._poll_connection()

    def _poll_connection(self) -> None:
        try:
            version = self.client.version()
            self.conn_label.setText(f"🟢 Ollama bağlı ({self.client.base_url}, v{version})")
        except OllamaError:
            self.conn_label.setText(f"🔴 Ollama erişilemiyor ({self.client.base_url})")
        self._update_quota_status()

    def _update_quota_status(self) -> None:
        try:
            snap = self.usage.snapshot()
            limits = self.usage.limits()
            self.quota_label.setText(
                f"bugün: {snap.requests}/{limits.max_requests_per_day} istek • "
                f"{snap.tokens_total:,}/{limits.max_tokens_per_day:,} token"
            )
        except Exception:  # noqa: BLE001
            self.quota_label.setText("")

    def _about(self) -> None:
        QMessageBox.information(
            self, f"{__app_name__} Hakkında",
            f"{__app_name__} v{__version__}\n\n"
            "Yerel Yapay Zeka Kodlama Ajanı ve Çalışma Alanı Masaüstü Uygulaması.\n\n"
            f"• Ollama uç noktası: {self.config.base_url}\n"
            f"• Birincil model: {self.config.model}\n"
            "• Kota yönetimi: UsageLimitEditor.exe ile düzenlenir.",
        )

    def closeEvent(self, event) -> None:  # noqa: N802
        self._stop_agent()
        if self._worker_thread is not None:
            self._worker_thread.quit()
            self._worker_thread.wait(2000)
        self._persist_current_session()
        super().closeEvent(event)
