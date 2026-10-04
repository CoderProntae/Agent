"""Chat session persistence.

Each conversation is stored as a JSON document under the user data
directory. The sidebar lists sessions sorted by recency; switching
sessions restores the full message history (including tool/action cards).
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from agentdesk.core import paths

logger = logging.getLogger(__name__)


@dataclass
class ChatSession:
    """One persisted conversation with the agent."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = "Yeni Oturum"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    workspace: str = ""
    model: str = ""
    messages: list[dict[str, Any]] = field(default_factory=list)


class SessionStore:
    """File-backed store for :class:`ChatSession` objects."""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = Path(directory) if directory else paths.sessions_dir()
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        safe = "".join(c for c in session_id if c.isalnum() or c in "-_")
        return self.directory / f"{safe}.json"

    def new_session(self, workspace: str = "", model: str = "") -> ChatSession:
        return ChatSession(workspace=workspace, model=model)

    def list_sessions(self) -> list[ChatSession]:
        sessions: list[ChatSession] = []
        for path in self.directory.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                sessions.append(
                    ChatSession(
                        id=data.get("id", path.stem),
                        title=data.get("title", "Oturum"),
                        created_at=float(data.get("created_at", 0)),
                        updated_at=float(data.get("updated_at", 0)),
                        workspace=data.get("workspace", ""),
                        model=data.get("model", ""),
                        messages=data.get("messages", []),
                    )
                )
            except (json.JSONDecodeError, OSError, ValueError):
                logger.exception("Skipping corrupt session file %s", path)
        sessions.sort(key=lambda s: s.updated_at, reverse=True)
        return sessions

    def load(self, session_id: str) -> ChatSession | None:
        path = self._path(session_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return ChatSession(
                id=data.get("id", session_id),
                title=data.get("title", "Oturum"),
                created_at=float(data.get("created_at", 0)),
                updated_at=float(data.get("updated_at", 0)),
                workspace=data.get("workspace", ""),
                model=data.get("model", ""),
                messages=data.get("messages", []),
            )
        except (json.JSONDecodeError, OSError, ValueError):
            logger.exception("Failed to load session %s", session_id)
            return None

    def save(self, session: ChatSession) -> None:
        session.updated_at = time.time()
        tmp = self._path(session.id).with_suffix(".tmp")
        tmp.write_text(
            json.dumps(asdict(session), ensure_ascii=False, indent=1), encoding="utf-8"
        )
        tmp.replace(self._path(session.id))

    def delete(self, session_id: str) -> bool:
        path = self._path(session_id)
        if path.exists():
            path.unlink()
            return True
        return False
