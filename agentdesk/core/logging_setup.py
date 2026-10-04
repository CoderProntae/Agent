"""Centralised logging configuration.

Logs are written both to a rotating file inside the user data directory and
to stderr (useful when the app is launched from a terminal or packaged with
a console). Tracebacks from failed API calls / tool executions are always
captured here, which is what powers the agent's self-correction reports.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from agentdesk.core import paths

_CONFIGURED = False


def setup_logging(level: int = logging.INFO) -> None:
    """Configure the root ``agentdesk`` logger exactly once."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    root = logging.getLogger("agentdesk")
    root.setLevel(level)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        paths.logs_dir() / "agentdesk.log",
        maxBytes=2_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(fmt)
    stream_handler.setLevel(logging.WARNING)
    root.addHandler(stream_handler)

    _CONFIGURED = True
