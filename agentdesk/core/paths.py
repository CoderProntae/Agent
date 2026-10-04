"""Platform-specific application directories.

Every persisted artifact (configuration, usage database, chat sessions,
logs) lives under a single per-user data directory so the application never
writes into its own installation folder. Tests redirect the directory via the
``AGENTDESK_HOME`` environment variable.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "AgentDesk"
ENV_OVERRIDE = "AGENTDESK_HOME"


def user_data_dir() -> Path:
    """Return (and create) the per-user data directory for AgentDesk."""
    override = os.environ.get(ENV_OVERRIDE)
    if override:
        path = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
        path = base / APP_DIR_NAME
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
        path = base / APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_file() -> Path:
    """Path of the JSON configuration file."""
    return user_data_dir() / "config.json"


def usage_database() -> Path:
    """Path of the SQLite database holding usage counters + encrypted limits."""
    return user_data_dir() / "usage.db"


def sessions_dir() -> Path:
    """Directory holding persisted chat sessions (one JSON file each)."""
    path = user_data_dir() / "sessions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_dir() -> Path:
    """Directory holding rotating application logs."""
    path = user_data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path
