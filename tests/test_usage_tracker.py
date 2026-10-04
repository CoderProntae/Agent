"""Usage accounting and live quota enforcement."""

import pytest

from agentdesk.core.limits_store import LimitsStore, UsageLimits
from agentdesk.core.usage_tracker import QuotaExceededError, UsageTracker


@pytest.fixture()
def tracker(tmp_path):
    db = str(tmp_path / "usage.db")
    store = LimitsStore(db)
    return UsageTracker(db_path=db, limits_store=store)


def test_record_and_snapshot(tracker):
    tracker.record_request(100, 50, session_id="s1")
    tracker.record_request(20, 30, session_id="s1")
    snap = tracker.snapshot(session_id="s1")
    assert snap.requests == 2
    assert snap.tokens_in == 120
    assert snap.tokens_out == 80
    assert snap.tokens_total == 200
    assert snap.session_tokens == 200


def test_executions_and_active_time(tracker):
    tracker.record_execution()
    tracker.record_execution()
    tracker.add_active_seconds(95)
    snap = tracker.snapshot()
    assert snap.executions == 2
    assert snap.active_seconds == 95


def test_request_quota_enforced(tracker):
    tracker.limits_store.save(UsageLimits(max_requests_per_day=2))
    tracker.record_request(1, 1)
    tracker.record_request(1, 1)
    with pytest.raises(QuotaExceededError) as exc:
        tracker.check_request()
    assert exc.value.quota == "requests"


def test_token_day_quota_enforced(tracker):
    tracker.limits_store.save(UsageLimits(max_tokens_per_day=1000))
    tracker.record_request(950, 40)
    with pytest.raises(QuotaExceededError) as exc:
        tracker.check_request(estimated_tokens=20)
    assert exc.value.quota == "tokens_day"


def test_session_token_quota_enforced(tracker):
    tracker.limits_store.save(UsageLimits(max_tokens_per_session=100))
    tracker.record_request(90, 5, session_id="abc")
    with pytest.raises(QuotaExceededError) as exc:
        tracker.check_request(estimated_tokens=20, session_id="abc")
    assert exc.value.quota == "tokens_session"


def test_execution_quota_enforced(tracker):
    tracker.limits_store.save(UsageLimits(max_executions_per_day=1))
    tracker.record_execution()
    with pytest.raises(QuotaExceededError):
        tracker.check_execution()


def test_disabled_limits_skip_enforcement(tracker):
    tracker.limits_store.save(UsageLimits(enabled=False, max_requests_per_day=1))
    tracker.record_request(1, 1)
    tracker.check_request()  # must not raise


def test_developer_override_skips_enforcement(tracker):
    tracker.limits_store.save(UsageLimits(developer_override=True, max_requests_per_day=1))
    tracker.record_request(1, 1)
    tracker.check_request()  # must not raise


def test_reset_today(tracker):
    tracker.record_request(10, 10)
    tracker.record_execution()
    tracker.reset_today()
    snap = tracker.snapshot()
    assert snap.requests == 0
    assert snap.executions == 0


def test_limits_live_reload(tmp_path):
    """A second process (UsageLimitEditor) changing limits is seen live."""
    db = str(tmp_path / "shared.db")
    tracker = UsageTracker(db_path=db, limits_store=LimitsStore(db))
    tracker.limits_store.save(UsageLimits(max_requests_per_day=10))

    editor_side = LimitsStore(db)  # simulates the separate executable
    editor_side.save(UsageLimits(max_requests_per_day=1))

    tracker.record_request(1, 1)
    with pytest.raises(QuotaExceededError):
        tracker.check_request()
