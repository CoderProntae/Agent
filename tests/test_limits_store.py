"""Encrypted quota store: roundtrip, locking, admin codes."""

import pytest

from agentdesk.core.limits_store import (
    LimitsLockedError,
    LimitsStore,
    LimitsStoreError,
    UsageLimits,
)


@pytest.fixture()
def store(tmp_path):
    return LimitsStore(str(tmp_path / "usage.db"))


def test_defaults_when_empty(store):
    limits = store.load()
    assert limits.enabled is True
    assert limits.max_requests_per_day == 500
    assert limits.max_tokens_per_session == 100_000


def test_save_and_reload(store):
    limits = UsageLimits(max_requests_per_day=42, max_tokens_per_day=12345)
    store.save(limits)
    loaded = store.load()
    assert loaded.max_requests_per_day == 42
    assert loaded.max_tokens_per_day == 12345


def test_blob_is_encrypted_not_plaintext(store, tmp_path):
    store.save(UsageLimits(notes="SECRET_MARKER"))
    raw = (tmp_path / "usage.db").read_bytes()
    assert b"SECRET_MARKER" not in raw


def test_lock_requires_admin_code(store):
    store.save(UsageLimits(locked=True))
    with pytest.raises(LimitsLockedError):
        store.save(UsageLimits(max_requests_per_day=1))
    # Correct default admin code unlocks the change.
    store.save(UsageLimits(max_requests_per_day=7, locked=True), admin_code="admin123")
    assert store.load().max_requests_per_day == 7


def test_admin_code_change(store):
    store.set_admin_code("admin123", "newcode99")
    assert store.verify_admin("newcode99")
    assert not store.verify_admin("admin123")
    with pytest.raises(LimitsStoreError):
        store.set_admin_code("wrong", "zzzz")


def test_short_admin_code_rejected(store):
    with pytest.raises(LimitsStoreError):
        store.set_admin_code("admin123", "ab")
