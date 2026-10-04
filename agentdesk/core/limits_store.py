"""Encrypted corporate usage-limit store.

Quota policy (daily request caps, token budgets, execution limits, developer
override and the lock flag) is persisted **Fernet-encrypted** inside the
shared SQLite database. The same module backs both executables:

* ``AgentDesk``      — reads the limits live before every billable action.
* ``UsageLimitEditor`` — edits / resets / locks the limits.

The Fernet key is derived with PBKDF2 from an embedded application secret.
This protects casual tampering of the JSON payload; it is *not* a defence
against an attacker with full administrative access to the machine, which is
the accepted threat model for a local quota tool. An additional admin code
(gated by SHA-256 hash) protects lock/unlock and limit changes once locked.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import sqlite3
import threading
from dataclasses import asdict, dataclass, fields

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from agentdesk.core import paths

logger = logging.getLogger(__name__)

# Embedded application secret used for key derivation. Both executables ship
# the same constant so they can read/write the same encrypted blob.
_APP_SECRET = b"AgentDesk::LocalQuotaVault::v1::9f2c7ab4"
_KDF_SALT = b"agentdesk.limits.kdf.salt.v1"
_KDF_ITERATIONS = 200_000
_DEFAULT_ADMIN_HASH = hashlib.sha256(b"admin123").hexdigest()


class LimitsStoreError(Exception):
    """Base error for the limits store."""


class LimitsLockedError(LimitsStoreError):
    """Raised when limits are locked and the admin code was wrong/missing."""


class LimitsIntegrityError(LimitsStoreError):
    """Raised when the encrypted blob cannot be decrypted."""


@dataclass
class UsageLimits:
    """Corporate quota policy applied to the local agent."""

    enabled: bool = True
    max_requests_per_day: int = 500
    max_tokens_per_day: int = 2_000_000
    max_tokens_per_session: int = 100_000
    max_executions_per_day: int = 200
    max_active_minutes_per_day: int = 480
    developer_override: bool = False
    locked: bool = False
    notes: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "UsageLimits":
        valid = {f.name for f in fields(cls)}
        clean = {k: v for k, v in data.items() if k in valid}
        try:
            return cls(**clean)
        except TypeError:
            logger.exception("Invalid limits payload; using defaults")
            return cls()


def _derive_key() -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_KDF_SALT,
        iterations=_KDF_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(_APP_SECRET))


class LimitsStore:
    """CRUD access to the encrypted quota policy blob."""

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = str(db_path or paths.usage_database())
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        self._lock = threading.Lock()
        self._fernet = Fernet(_derive_key())
        self._init_schema()

    # -- schema ---------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS kv ("
                " key TEXT PRIMARY KEY,"
                " value BLOB NOT NULL,"
                " updated_at TEXT DEFAULT (datetime('now'))"
                ")"
            )
            conn.commit()

    def _kv_get(self, key: str) -> bytes | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def _kv_set(self, key: str, value: bytes) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO kv (key, value, updated_at) VALUES (?, ?, datetime('now')) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
                "updated_at = excluded.updated_at",
                (key, value),
            )
            conn.commit()

    # -- admin code -------------------------------------------------------
    def verify_admin(self, code: str) -> bool:
        stored = self._kv_get("admin_hash")
        expected = stored.decode("utf-8") if stored else _DEFAULT_ADMIN_HASH
        return hashlib.sha256(code.encode("utf-8")).hexdigest() == expected

    def set_admin_code(self, old_code: str, new_code: str) -> None:
        if not self.verify_admin(old_code):
            raise LimitsStoreError("Mevcut yönetici kodu hatalı.")
        if len(new_code) < 4:
            raise LimitsStoreError("Yeni yönetici kodu en az 4 karakter olmalı.")
        self._kv_set("admin_hash", hashlib.sha256(new_code.encode("utf-8")).hexdigest().encode())

    # -- limits -----------------------------------------------------------
    def load(self) -> UsageLimits:
        """Decrypt and return the current limits (defaults if absent)."""
        blob = self._kv_get("limits")
        if blob is None:
            return UsageLimits()
        try:
            payload = self._fernet.decrypt(bytes(blob))
            return UsageLimits.from_dict(json.loads(payload.decode("utf-8")))
        except (InvalidToken, ValueError, json.JSONDecodeError):
            logger.exception("Limits blob could not be decrypted; using defaults")
            raise LimitsIntegrityError("Kota yapılandırması çözümlenemedi (bütünlük hatası).")

    def save(self, limits: UsageLimits, admin_code: str = "") -> None:
        """Encrypt and persist limits. Locked stores require the admin code."""
        current = self.load_or_default()
        if current.locked and not current.developer_override:
            if not admin_code or not self.verify_admin(admin_code):
                raise LimitsLockedError(
                    "Kota sınırları kilitli. Değiştirmek için yönetici kodu gerekli."
                )
        payload = json.dumps(asdict(limits), ensure_ascii=False).encode("utf-8")
        self._kv_set("limits", self._fernet.encrypt(payload))
        logger.info("Usage limits saved (enabled=%s, locked=%s)", limits.enabled, limits.locked)

    def load_or_default(self) -> UsageLimits:
        try:
            return self.load()
        except LimitsIntegrityError:
            return UsageLimits()
