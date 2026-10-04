"""Corporate usage accounting and quota enforcement engine.

Tracks, per local day: request count, input/output tokens, terminal
executions and active time — plus per-session token totals. All counters
live in SQLite (WAL mode) so the main application and the
``UsageLimitEditor`` can access them concurrently.

The tracker re-reads the (possibly encrypted) :class:`UsageLimits` on every
check, so an administrator editing quotas in ``UsageLimitEditor`` takes
effect live — no restart required. When a quota is hit, a
:class:`QuotaExceededError` is raised; the UI converts it into a warning
banner and the agent loop disables further billable actions.
"""

from __future__ import annotations

import datetime as _dt
import logging
import os
import sqlite3
import threading
from dataclasses import dataclass

from agentdesk.core import paths
from agentdesk.core.limits_store import LimitsStore, UsageLimits

logger = logging.getLogger(__name__)


class QuotaExceededError(Exception):
    """Raised when an action would exceed a configured corporate quota."""

    def __init__(self, message: str, quota: str):
        super().__init__(message)
        self.quota = quota  # e.g. "requests", "tokens_day", "executions", ...


@dataclass
class UsageSnapshot:
    """Point-in-time counters for the current local day."""

    date: str
    requests: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    executions: int = 0
    active_seconds: float = 0.0
    session_tokens: int = 0

    @property
    def tokens_total(self) -> int:
        return self.tokens_in + self.tokens_out


def _today() -> str:
    return _dt.date.today().isoformat()


class UsageTracker:
    """Records usage and enforces :class:`UsageLimits` live."""

    def __init__(self, db_path: str | None = None, limits_store: LimitsStore | None = None):
        self.db_path = str(db_path or paths.usage_database())
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        self.limits_store = limits_store or LimitsStore(self.db_path)
        self._lock = threading.Lock()
        self._init_schema()

    # -- schema ----------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS usage_daily ("
                " date TEXT PRIMARY KEY,"
                " requests INTEGER NOT NULL DEFAULT 0,"
                " tokens_in INTEGER NOT NULL DEFAULT 0,"
                " tokens_out INTEGER NOT NULL DEFAULT 0,"
                " executions INTEGER NOT NULL DEFAULT 0,"
                " active_seconds REAL NOT NULL DEFAULT 0"
                ")"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS usage_sessions ("
                " session_id TEXT PRIMARY KEY,"
                " tokens INTEGER NOT NULL DEFAULT 0,"
                " updated_at TEXT DEFAULT (datetime('now'))"
                ")"
            )
            conn.commit()

    # -- recording ---------------------------------------------------------
    def _ensure_day(self, conn: sqlite3.Connection, date: str) -> None:
        conn.execute(
            "INSERT OR IGNORE INTO usage_daily "
            "(date, requests, tokens_in, tokens_out, executions, active_seconds) "
            "VALUES (?, 0, 0, 0, 0, 0)",
            (date,),
        )

    def record_request(self, tokens_in: int, tokens_out: int, session_id: str | None = None) -> None:
        """Record one completed LLM request with its token usage."""
        date = _today()
        with self._lock, self._connect() as conn:
            self._ensure_day(conn, date)
            conn.execute(
                "UPDATE usage_daily SET requests = requests + 1, "
                "tokens_in = tokens_in + ?, tokens_out = tokens_out + ? WHERE date = ?",
                (int(tokens_in), int(tokens_out), date),
            )
            if session_id:
                conn.execute(
                    "INSERT INTO usage_sessions (session_id, tokens, updated_at) "
                    "VALUES (?, ?, datetime('now')) "
                    "ON CONFLICT(session_id) DO UPDATE SET "
                    "tokens = tokens + excluded.tokens, updated_at = excluded.updated_at",
                    (session_id, int(tokens_in) + int(tokens_out)),
                )
            conn.commit()
        logger.debug("Recorded request: +%d in / +%d out", tokens_in, tokens_out)

    def record_execution(self) -> None:
        """Record one terminal execution."""
        date = _today()
        with self._lock, self._connect() as conn:
            self._ensure_day(conn, date)
            conn.execute(
                "UPDATE usage_daily SET executions = executions + 1 WHERE date = ?", (date,)
            )
            conn.commit()

    def add_active_seconds(self, seconds: float) -> None:
        """Accumulate foreground active time (called by the UI heartbeat)."""
        if seconds <= 0:
            return
        date = _today()
        with self._lock, self._connect() as conn:
            self._ensure_day(conn, date)
            conn.execute(
                "UPDATE usage_daily SET active_seconds = active_seconds + ? WHERE date = ?",
                (float(seconds), date),
            )
            conn.commit()

    def reset_today(self) -> None:
        """Zero all counters for the current day (admin action)."""
        date = _today()
        with self._lock, self._connect() as conn:
            self._ensure_day(conn, date)
            conn.execute(
                "UPDATE usage_daily SET requests = 0, tokens_in = 0, tokens_out = 0, "
                "executions = 0, active_seconds = 0 WHERE date = ?",
                (date,),
            )
            conn.execute("DELETE FROM usage_sessions")
            conn.commit()
        logger.info("Daily usage counters reset")

    # -- reading -------------------------------------------------------------
    def snapshot(self, session_id: str | None = None) -> UsageSnapshot:
        date = _today()
        with self._lock, self._connect() as conn:
            self._ensure_day(conn, date)
            row = conn.execute(
                "SELECT requests, tokens_in, tokens_out, executions, active_seconds "
                "FROM usage_daily WHERE date = ?",
                (date,),
            ).fetchone()
            session_tokens = 0
            if session_id:
                srow = conn.execute(
                    "SELECT tokens FROM usage_sessions WHERE session_id = ?", (session_id,)
                ).fetchone()
                session_tokens = int(srow[0]) if srow else 0
            conn.commit()
        return UsageSnapshot(
            date=date,
            requests=int(row[0]),
            tokens_in=int(row[1]),
            tokens_out=int(row[2]),
            executions=int(row[3]),
            active_seconds=float(row[4]),
            session_tokens=session_tokens,
        )

    def limits(self) -> UsageLimits:
        """Live read of the current quota policy."""
        return self.limits_store.load_or_default()

    # -- enforcement -------------------------------------------------------
    def check_request(
        self, estimated_tokens: int = 0, session_id: str | None = None
    ) -> None:
        """Raise :class:`QuotaExceededError` if a new request is forbidden."""
        limits = self.limits()
        if not limits.enabled or limits.developer_override:
            return
        snap = self.snapshot(session_id=session_id)

        if snap.requests >= limits.max_requests_per_day:
            raise QuotaExceededError(
                f"Günlük istek sınırına ulaşıldı ({limits.max_requests_per_day}).",
                "requests",
            )
        if snap.tokens_total + estimated_tokens > limits.max_tokens_per_day:
            raise QuotaExceededError(
                f"Günlük token bütçesi aşılmak üzere ({limits.max_tokens_per_day:,} token).",
                "tokens_day",
            )
        if session_id and snap.session_tokens + estimated_tokens > limits.max_tokens_per_session:
            raise QuotaExceededError(
                f"Oturum token sınırına ulaşıldı ({limits.max_tokens_per_session:,} token). "
                "Yeni bir oturum başlatın.",
                "tokens_session",
            )
        if snap.active_seconds / 60.0 >= limits.max_active_minutes_per_day:
            raise QuotaExceededError(
                f"Günlük aktif kullanım süresi aşıldı ({limits.max_active_minutes_per_day} dk).",
                "active_time",
            )

    def check_execution(self) -> None:
        """Raise if another terminal execution is not allowed today."""
        limits = self.limits()
        if not limits.enabled or limits.developer_override:
            return
        snap = self.snapshot()
        if snap.executions >= limits.max_executions_per_day:
            raise QuotaExceededError(
                f"Günlük komut çalıştırma sınırına ulaşıldı ({limits.max_executions_per_day}).",
                "executions",
            )
