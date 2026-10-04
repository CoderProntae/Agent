"""UsageLimitEditor entry point and GUI.

A standalone administrator utility that manages the corporate quota policy
stored encrypted in the shared local SQLite database:

* edit daily request / token / execution / active-time caps;
* enable or disable enforcement entirely;
* grant or revoke the developer-mode override;
* lock the policy behind an admin code (and change that code);
* reset today's usage counters.

AgentDesk re-reads this store before every billable action, so edits apply
live.
"""

from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from agentdesk import __version__
from agentdesk.core.limits_store import (
    LimitsLockedError,
    LimitsStore,
    LimitsStoreError,
    UsageLimits,
)
from agentdesk.core.logging_setup import setup_logging
from agentdesk.core.usage_tracker import UsageTracker
from agentdesk.ui import theme

logger = logging.getLogger(__name__)


class UsageLimitEditorWindow(QMainWindow):
    """Quota administration window."""

    def __init__(self) -> None:
        super().__init__()
        self.store = LimitsStore()
        self.tracker = UsageTracker(limits_store=self.store)
        self.setWindowTitle(f"UsageLimitEditor — Kurumsal Kota Yöneticisi v{__version__}")
        self.setFixedWidth(620)

        central = QWidget()
        root = QVBoxLayout(central)
        root.setSpacing(10)

        intro = QLabel(
            "Bu araç, AgentDesk'in canlı olarak uyguladığı kurumsal kullanım kotalarını yönetir. "
            "Kaydedilen her değişiklik anında etkili olur."
        )
        intro.setWordWrap(True)
        intro.setObjectName("mutedLabel")
        root.addWidget(intro)

        # ---- current usage -------------------------------------------------
        snap = self.tracker.snapshot()
        self.usage_label = QLabel(
            f"Bugünkü kullanım ({snap.date}): {snap.requests} istek • "
            f"{snap.tokens_total:,} token • {snap.executions} yürütme • "
            f"{int(snap.active_seconds // 60)} dk aktif"
        )
        self.usage_label.setObjectName("mutedLabel")
        root.addWidget(self.usage_label)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"color: {theme.BORDER};")
        root.addWidget(line)

        # ---- limit editors ------------------------------------------------
        limits = self.store.load_or_default()
        form_box = QGroupBox("Kota Sınırları")
        form = QFormLayout(form_box)

        self.enabled_check = QCheckBox("Kota denetimini etkinleştir")
        self.enabled_check.setChecked(limits.enabled)
        form.addRow(self.enabled_check)

        self.req_spin = self._spin(1, 1_000_000, limits.max_requests_per_day)
        form.addRow("Günlük maks. istek:", self.req_spin)

        self.tok_day_spin = self._spin(10_000, 100_000_000, limits.max_tokens_per_day, step=50_000)
        form.addRow("Günlük maks. token:", self.tok_day_spin)

        self.tok_session_spin = self._spin(1_000, 100_000_000, limits.max_tokens_per_session, step=10_000)
        form.addRow("Oturum başına maks. token:", self.tok_session_spin)

        self.exec_spin = self._spin(1, 100_000, limits.max_executions_per_day)
        form.addRow("Günlük maks. komut yürütme:", self.exec_spin)

        self.active_spin = self._spin(5, 24 * 60, limits.max_active_minutes_per_day)
        form.addRow("Günlük maks. aktif süre (dk):", self.active_spin)

        self.override_check = QCheckBox("Geliştirici modu geçersiz kılma (sınırları uygularmaz)")
        self.override_check.setChecked(limits.developer_override)
        form.addRow(self.override_check)

        self.lock_check = QCheckBox("Sınırları kilitle (değişiklik için yönetici kodu gerekir)")
        self.lock_check.setChecked(limits.locked)
        form.addRow(self.lock_check)

        self.notes_edit = QLineEdit(limits.notes)
        self.notes_edit.setPlaceholderText("Opsiyonel not (ör. politika referansı)")
        form.addRow("Not:", self.notes_edit)
        root.addWidget(form_box)

        # ---- actions --------------------------------------------------------
        actions = QHBoxLayout()
        save_btn = QPushButton("💾 Kaydet")
        save_btn.setObjectName("primaryBtn")
        save_btn.clicked.connect(self._save)
        defaults_btn = QPushButton("Varsayılanlara Dön")
        defaults_btn.clicked.connect(self._reset_defaults)
        reset_btn = QPushButton("Bugünkü Sayaçları Sıfırla")
        reset_btn.setObjectName("dangerBtn")
        reset_btn.clicked.connect(self._reset_counters)
        actions.addWidget(save_btn)
        actions.addWidget(defaults_btn)
        actions.addWidget(reset_btn)
        root.addLayout(actions)

        admin_row = QHBoxLayout()
        change_code_btn = QPushButton("Yönetici kodunu değiştir")
        change_code_btn.clicked.connect(self._change_admin_code)
        admin_row.addWidget(change_code_btn)
        admin_row.addStretch(1)
        root.addLayout(admin_row)

        self.setCentralWidget(central)

    # ------------------------------------------------------------------
    @staticmethod
    def _spin(min_v: int, max_v: int, value: int, step: int = 1) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(min_v, max_v)
        spin.setSingleStep(step)
        spin.setValue(int(value))
        spin.setGroupSeparatorShown(True)
        return spin

    def _gather(self) -> UsageLimits:
        return UsageLimits(
            enabled=self.enabled_check.isChecked(),
            max_requests_per_day=self.req_spin.value(),
            max_tokens_per_day=self.tok_day_spin.value(),
            max_tokens_per_session=self.tok_session_spin.value(),
            max_executions_per_day=self.exec_spin.value(),
            max_active_minutes_per_day=self.active_spin.value(),
            developer_override=self.override_check.isChecked(),
            locked=self.lock_check.isChecked(),
            notes=self.notes_edit.text().strip(),
        )

    def _admin_code_if_needed(self) -> str:
        current = self.store.load_or_default()
        if current.locked and not current.developer_override:
            code, ok = QInputDialog.getText(
                self, "Yönetici kodu", "Sınırlar kilitli. Yönetici kodunu girin:",
                QLineEdit.Password,
            )
            if not ok:
                raise LimitsLockedError("İşlem iptal edildi.")
            return code
        return ""

    def save_limits(self) -> str | None:
        """Persist the form values; returns ``None`` or an error message.

        Kept dialog-free so automation/tests can drive it headlessly.
        """
        try:
            code = self._admin_code_if_needed()
        except LimitsLockedError as exc:
            return str(exc)
        try:
            self.store.save(self._gather(), admin_code=code)
            return None
        except LimitsStoreError as exc:
            return str(exc)

    def _save(self) -> None:
        error = self.save_limits()
        if error:
            QMessageBox.critical(self, "Kaydedilemedi", error)
        else:
            QMessageBox.information(
                self, "Kaydedildi",
                "Kota sınırları şifreli olarak kaydedildi.\nAgentDesk değişiklikleri canlı uygulayacak.",
            )

    def _reset_defaults(self) -> None:
        answer = QMessageBox.question(
            self, "Varsayılanlar", "Tüm sınırlar fabrika varsayılanlarına döndürülsün mü?"
        )
        if answer != QMessageBox.Yes:
            return
        try:
            code = self._admin_code_if_needed()
            defaults = UsageLimits()
            self.store.save(defaults, admin_code=code)
            self._reload()
            QMessageBox.information(self, "Tamam", "Varsayılan sınırlar geri yüklendi.")
        except LimitsStoreError as exc:
            QMessageBox.critical(self, "Hata", str(exc))

    def _reset_counters(self) -> None:
        answer = QMessageBox.question(
            self, "Sayaç sıfırlama", "Bugünkü tüm kullanım sayaçları sıfırlansın mı?"
        )
        if answer == QMessageBox.Yes:
            self.tracker.reset_today()
            snap = self.tracker.snapshot()
            self.usage_label.setText(
                f"Bugünkü kullanım ({snap.date}): {snap.requests} istek • "
                f"{snap.tokens_total:,} token • {snap.executions} yürütme • "
                f"{int(snap.active_seconds // 60)} dk aktif"
            )

    def _change_admin_code(self) -> None:
        old, ok = QInputDialog.getText(
            self, "Eski kod", "Mevcut yönetici kodu:", QLineEdit.Password
        )
        if not ok:
            return
        new, ok = QInputDialog.getText(
            self, "Yeni kod", "Yeni yönetici kodu (en az 4 karakter):", QLineEdit.Password
        )
        if not ok:
            return
        try:
            self.store.set_admin_code(old, new)
            QMessageBox.information(self, "Tamam", "Yönetici kodu güncellendi.")
        except LimitsStoreError as exc:
            QMessageBox.critical(self, "Hata", str(exc))

    def _reload(self) -> None:
        limits = self.store.load_or_default()
        self.enabled_check.setChecked(limits.enabled)
        self.req_spin.setValue(limits.max_requests_per_day)
        self.tok_day_spin.setValue(limits.max_tokens_per_day)
        self.tok_session_spin.setValue(limits.max_tokens_per_session)
        self.exec_spin.setValue(limits.max_executions_per_day)
        self.active_spin.setValue(limits.max_active_minutes_per_day)
        self.override_check.setChecked(limits.developer_override)
        self.lock_check.setChecked(limits.locked)
        self.notes_edit.setText(limits.notes)


def main() -> int:
    setup_logging()
    app = QApplication(sys.argv)
    app.setApplicationName("UsageLimitEditor")
    app.setOrganizationName("CoderProntae")
    app.setStyleSheet(theme.DARK_QSS)
    window = UsageLimitEditorWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
