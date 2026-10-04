"""Settings dialog: Ollama endpoint, model, agent tuning, GitHub token.

Saving persists through :func:`agentdesk.core.config.save_config` and the
main window rebuilds the Ollama client so changes apply immediately. The
model selector can enumerate installed models live from ``/api/tags``.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from agentdesk.core.config import AppConfig, save_config
from agentdesk.core.ollama_client import OllamaClient, OllamaError


class SettingsDialog(QDialog):
    """Modal editor for :class:`AppConfig`."""

    def __init__(self, config: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Ayarlar")
        self.setMinimumWidth(560)

        root = QVBoxLayout(self)

        # ---- Ollama -----------------------------------------------------
        ollama_box = QGroupBox("Ollama Sunucusu")
        form = QFormLayout(ollama_box)

        self.host_edit = QLineEdit(config.ollama_host)
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(config.ollama_port)
        host_row = QHBoxLayout()
        host_row.addWidget(self.host_edit, 3)
        host_row.addWidget(QLabel("Port:"), 0)
        host_row.addWidget(self.port_spin, 1)
        form.addRow("Ana bilgisayar / Port:", host_row)

        model_row = QHBoxLayout()
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.setEditText(config.model)
        self.refresh_btn = QPushButton("⟳ Modelleri Getir")
        self.refresh_btn.clicked.connect(self._refresh_models)
        model_row.addWidget(self.model_combo, 1)
        model_row.addWidget(self.refresh_btn)
        form.addRow("Model:", model_row)
        self.model_status = QLabel("")
        self.model_status.setObjectName("mutedLabel")
        form.addRow("", self.model_status)

        self.temp_spin = QDoubleSpinBox()
        self.temp_spin.setRange(0.0, 2.0)
        self.temp_spin.setSingleStep(0.1)
        self.temp_spin.setValue(config.temperature)
        form.addRow("Sıcaklık (temperature):", self.temp_spin)

        self.max_tokens_spin = QSpinBox()
        self.max_tokens_spin.setRange(256, 131072)
        self.max_tokens_spin.setSingleStep(256)
        self.max_tokens_spin.setValue(config.max_output_tokens)
        form.addRow("Maks. çıktı token:", self.max_tokens_spin)

        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(10, 3600)
        self.timeout_spin.setValue(int(config.read_timeout))
        form.addRow("Okuma zaman aşımı (sn):", self.timeout_spin)

        self.retries_spin = QSpinBox()
        self.retries_spin.setRange(0, 10)
        self.retries_spin.setValue(config.max_retries)
        form.addRow("Yeniden deneme sayısı:", self.retries_spin)
        root.addWidget(ollama_box)

        # ---- Agent --------------------------------------------------------
        agent_box = QGroupBox("Ajan Davranışı")
        agent_form = QFormLayout(agent_box)
        self.iter_spin = QSpinBox()
        self.iter_spin.setRange(1, 50)
        self.iter_spin.setValue(config.max_tool_iterations)
        agent_form.addRow("Maks. araç yinelemesi:", self.iter_spin)
        self.cmd_timeout_spin = QSpinBox()
        self.cmd_timeout_spin.setRange(5, 3600)
        self.cmd_timeout_spin.setValue(config.command_timeout)
        agent_form.addRow("Varsayılan komut zaman aşımı (sn):", self.cmd_timeout_spin)
        root.addWidget(agent_box)

        # ---- GitHub -----------------------------------------------------
        gh_box = QGroupBox("GitHub Entegrasyonu")
        gh_form = QFormLayout(gh_box)
        self.token_edit = QLineEdit(config.github_token)
        self.token_edit.setEchoMode(QLineEdit.Password)
        self.token_edit.setPlaceholderText("ghp_… (isteğe bağlı)")
        gh_form.addRow("Kişisel Erişim Belirteci:", self.token_edit)
        self.sync_check = QCheckBox("Depo senkronizasyonunu etkinleştir")
        self.sync_check.setChecked(config.github_sync_enabled)
        gh_form.addRow("", self.sync_check)
        root.addWidget(gh_box)

        # ---- buttons ----------------------------------------------------
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        test_btn = QPushButton("Bağlantıyı Test Et")
        test_btn.clicked.connect(self._test_connection)
        buttons.addButton(test_btn, QDialogButtonBox.ActionRole)
        root.addWidget(buttons)

        # Auto-load the installed model list as soon as the dialog opens.
        from PySide6.QtCore import QTimer

        QTimer.singleShot(0, self._refresh_models)

    # ------------------------------------------------------------------
    def _client_from_form(self) -> OllamaClient:
        cfg = AppConfig(
            ollama_host=self.host_edit.text().strip() or "localhost",
            ollama_port=self.port_spin.value(),
            connect_timeout=self.config.connect_timeout,
            read_timeout=self.timeout_spin.value(),
            max_retries=0,
        )
        return OllamaClient(base_url=cfg.base_url)

    def _refresh_models(self) -> None:
        current = self.model_combo.currentText().strip() or self.config.model
        self.model_status.setText(f"Modeller getiriliyor… ({self._client_from_form().base_url})")
        try:
            models = self._client_from_form().list_models()
        except OllamaError as exc:
            self.model_status.setText(f"⚠ Model listesi alınamadı: {exc}")
            return
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.addItems(models)
        self.model_combo.blockSignals(False)
        if models:
            if current in models:
                self.model_combo.setCurrentText(current)
            else:
                # Keep the configured model visible even if the server list
                # disagrees (editable combo), then the server's first model.
                self.model_combo.setEditText(current)
                self.model_combo.insertItem(0, current)
                self.model_combo.setCurrentIndex(0)
            self.model_status.setText(f"{len(models)} model bulundu — listeden seçebilirsiniz.")
        else:
            self.model_combo.setEditText(current)
            self.model_status.setText("Sunucuda kayıtlı model bulunamadı; model adı elle girilebilir.")

    def _test_connection(self) -> None:
        client = self._client_from_form()
        try:
            version = client.version()
            QMessageBox.information(self, "Bağlantı başarılı", f"Ollama sürümü: {version}\n({client.base_url})")
        except OllamaError as exc:
            QMessageBox.critical(self, "Bağlantı başarısız", str(exc))

    def _save(self) -> None:
        self.config.ollama_host = self.host_edit.text().strip() or "localhost"
        self.config.ollama_port = self.port_spin.value()
        self.config.model = self.model_combo.currentText().strip() or self.config.model
        self.config.temperature = self.temp_spin.value()
        self.config.max_output_tokens = self.max_tokens_spin.value()
        self.config.read_timeout = float(self.timeout_spin.value())
        self.config.max_retries = self.retries_spin.value()
        self.config.max_tool_iterations = self.iter_spin.value()
        self.config.command_timeout = self.cmd_timeout_spin.value()
        self.config.github_token = self.token_edit.text().strip()
        self.config.github_sync_enabled = self.sync_check.isChecked()
        save_config(self.config)
        self.accept()
