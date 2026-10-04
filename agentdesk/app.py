"""AgentDesk desktop application entry point.

Run directly (``python -m agentdesk``), via the console script
(``agentdesk``) or as the PyInstaller-built ``AgentDesk.exe``.
"""

from __future__ import annotations

import logging
import os
import sys

logger = logging.getLogger(__name__)


def main() -> int:
    # High-DPI must be configured before QApplication exists.
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

    from PySide6.QtWidgets import QApplication

    from agentdesk.core.config import load_config
    from agentdesk.core.logging_setup import setup_logging
    from agentdesk.ui import theme
    from agentdesk.ui.main_window import MainWindow

    setup_logging()
    config = load_config()

    app = QApplication(sys.argv)
    app.setApplicationName("AgentDesk")
    app.setOrganizationName("CoderProntae")
    app.setStyleSheet(theme.DARK_QSS)

    window = MainWindow(config)
    window.show()

    logger.info("AgentDesk UI started (Ollama target: %s)", config.base_url)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
