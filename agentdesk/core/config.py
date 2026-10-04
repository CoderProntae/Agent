"""Application configuration management.

The configuration is persisted as pretty-printed JSON in the user data
directory. All knobs that operators may need to touch — most importantly the
Ollama host/port pair (default ``localhost:11435``) and the primary model —
are exposed here and editable from the Settings dialog at runtime.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from agentdesk.core import paths

logger = logging.getLogger(__name__)

#: Default Ollama endpoint. NOTE: port 11435 is intentional — the stock
#: Ollama port is 11434, but this deployment targets a dedicated local
#: instance listening on 11435 (configurable in Settings).
DEFAULT_OLLAMA_HOST = "localhost"
DEFAULT_OLLAMA_PORT = 11435
DEFAULT_MODEL = "qwen3.5-9b-abliterated"


@dataclass
class AppConfig:
    """Runtime configuration for the AgentDesk desktop application."""

    # --- Ollama backend -------------------------------------------------
    ollama_host: str = DEFAULT_OLLAMA_HOST
    ollama_port: int = DEFAULT_OLLAMA_PORT
    model: str = DEFAULT_MODEL
    temperature: float = 0.2
    max_output_tokens: int = 4096
    context_window: int = 16384

    # --- HTTP behaviour --------------------------------------------------
    connect_timeout: float = 8.0
    read_timeout: float = 600.0
    max_retries: int = 3
    retry_backoff: float = 1.8
    keep_alive: str = "10m"

    # --- Agent loop -------------------------------------------------------
    max_tool_iterations: int = 12
    command_timeout: int = 300
    auto_commit: bool = False

    # --- Workspace ---------------------------------------------------------
    workspace_root: str = ""

    # --- Integrations ---------------------------------------------------
    github_token: str = ""
    github_sync_enabled: bool = False

    # --- UI ----------------------------------------------------------------
    ui_scale: float = 1.0
    show_line_numbers: bool = True

    # ------------------------------------------------------------------
    @property
    def base_url(self) -> str:
        """Base URL of the Ollama server, e.g. ``http://localhost:11435``."""
        host = self.ollama_host.strip() or DEFAULT_OLLAMA_HOST
        if host.startswith("http://") or host.startswith("https://"):
            return f"{host.rstrip('/')}:{int(self.ollama_port)}"
        return f"http://{host}:{int(self.ollama_port)}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppConfig":
        """Build a config from raw JSON, ignoring unknown/invalid keys."""
        valid = {f.name for f in fields(cls)}
        clean = {k: v for k, v in data.items() if k in valid}
        try:
            cfg = cls(**clean)
        except TypeError:
            logger.exception("Invalid configuration payload; using defaults")
            cfg = cls()
        cfg.ollama_port = int(cfg.ollama_port)
        cfg.temperature = max(0.0, min(2.0, float(cfg.temperature)))
        cfg.max_tool_iterations = max(1, int(cfg.max_tool_iterations))
        return cfg


_lock = threading.Lock()


def load_config(path: Path | None = None) -> AppConfig:
    """Load configuration from disk, falling back to defaults."""
    path = Path(path) if path else paths.config_file()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        cfg = AppConfig.from_dict(raw)
        logger.debug("Loaded configuration from %s", path)
        return cfg
    except FileNotFoundError:
        logger.info("No configuration file at %s; using defaults", path)
        return AppConfig()
    except (json.JSONDecodeError, OSError):
        logger.exception("Corrupt configuration at %s; using defaults", path)
        return AppConfig()


def save_config(config: AppConfig, path: Path | None = None) -> Path:
    """Persist configuration atomically (write-tmp-then-rename)."""
    path = Path(path) if path else paths.config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with _lock:
        tmp.write_text(json.dumps(config.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    logger.debug("Saved configuration to %s", path)
    return path
