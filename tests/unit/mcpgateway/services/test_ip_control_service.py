# -*- coding: utf-8 -*-
"""Tests for ip_control_service."""

# Standard
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import time

# Third-Party
import pytest

# First-Party
from mcpgateway.services import ip_control_service as svc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class DummyResult:
    """Mock query result."""

    def __init__(self, items=None):
        self._items = items or []

    def scalars(self):
        return self

    def first(self):
        return self._items[0] if self._items else None

    def all(self):
        return self._items


class DummyScalar:
    """Mock scalar result for count queries."""

    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class DummySession:
    """Minimal mock DB session for IP control tests."""

    def __init__(self, execute_results=None):
        self._execute_results = execute_results or []
        self._call_idx = 0
        self.committed = False
        self.added = []

    def execute(self, _query):
        if self._call_idx < len(self._execute_results):
            result = self._execute_results[self._call_idx]
            self._call_idx += 1
            return result
        return DummyResult([])

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.committed = True

    def refresh(self, _obj):
        pass

    def rollback(self):
        pass

    def close(self):
        pass

    def delete(self, _obj):
        pass


def _make_rule(
    rule_id="r1",
    ip_pattern="10.0.0.0/8",
    rule_type="deny",
    priority=100,
    path_pattern=None,
    is_active=True,
    expires_at=None,
    hit_count=0,
):
    return SimpleNamespace(
        id=rule_id,
        ip_pattern=ip_pattern,
        rule_type=rule_type,
        priority=priority,
        path_pattern=path_pattern,
        is_active=is_active,
        expires_at=expires_at,
        hit_count=hit_count,
        last_hit_at=None,
    )


def _make_block(block_id="b1", ip_address="1.2.3.4", is_active=True, expires_at=None):
    now = datetime.now(tz=timezone.utc)
    return SimpleNamespace(
        id=block_id,
        ip_address=ip_address,
        is_active=is_active,
        blocked_at=now,
        expires_at=expires_at or (now + timedelta(hours=1)),
        reason="test block",
        blocked_by="admin@test.com",
        unblocked_at=None,
        unblocked_by=None,
    )


def _fresh_service():
    """Create a fresh service instance (bypassing singleton)."""
    service = object.__new__(svc.IPControlService)
    service._cache = {}
    service._cache_lock = __import__("threading").Lock()
    service._initialized = True
    return service


# ---------------------------------------------------------------------------
# Static method tests: _ip_matches
# ---------------------------------------------------------------------------


def test_ip_matches_exact_ipv4():
    assert svc.IPControlService._ip_matches("192.168.1.1", "192.168.1.1") is True


def test_ip_matches_exact_ipv4_no_match():
    assert svc.IPControlService._ip_matches("192.168.1.2", "192.168.1.1") is False


def test_ip_matches_cidr_ipv4():
    assert svc.IPControlService._ip_matches("192.168.1.100", "192.168.1.0/24") is True


def test_ip_matches_cidr_ipv4_no_match():
    assert svc.IPControlService._ip_matches("10.0.0.1", "192.168.1.0/24") is False


def test_ip_matches_ipv6():
    assert svc.IPControlService._ip_matches("::1", "::1") is True


def test_ip_matches_ipv6_cidr():
    assert svc.IPControlService._ip_matches("fd00::1", "fd00::/16") is True


def test_ip_matches_invalid_ip():
    assert svc.IPControlService._ip_matches("not-an-ip", "192.168.1.0/24") is False


def test_ip_matches_invalid_pattern():
    assert svc.IPControlService._ip_matches("192.168.1.1", "garbage") is False


# ---------------------------------------------------------------------------
# Static method tests: _path_matches
# ---------------------------------------------------------------------------


def test_path_matches_none_pattern():
    """None pattern matches any path."""
    assert svc.IPControlService._path_matches("/anything", None) is True


def test_path_matches_regex():
    assert svc.IPControlService._path_matches("/api/v1/tools", "^/api/") is True


def test_path_matches_regex_no_match():
    assert svc.IPControlService._path_matches("/health", "^/api/") is False


def test_path_matches_invalid_regex():
    assert svc.IPControlService._path_matches("/test", "[invalid") is False


# ---------------------------------------------------------------------------
# Disabled mode
# ---------------------------------------------------------------------------


def test_evaluate_disabled_returns_true(monkeypatch):
    monkeypatch.setattr(svc.settings, "ip_control_enabled", False)
    service = _fresh_service()
    assert service.evaluate_ip("1.2.3.4", "/anything") is True


def test_evaluate_disabled_mode_returns_true(monkeypatch):
    monkeypatch.setattr(svc.settings, "ip_control_enabled", True)
    monkeypatch.setattr(svc.settings, "ip_control_mode", "disabled")
    service = _fresh_service()
    assert service.evaluate_ip("1.2.3.4", "/anything") is True


# ---------------------------------------------------------------------------
# Blocklist mode defaults
# ---------------------------------------------------------------------------


def test_blocklist_default_allows(monkeypatch):
    """In blocklist mode, IPs not matching any rule are allowed."""
    monkeypatch.setattr(svc.settings, "ip_control_enabled", True)
    monkeypatch.setattr(svc.settings, "ip_control_mode", "blocklist")
    monkeypatch.setattr(svc.settings, "ip_control_cache_ttl", 0)

    session = DummySession(execute_results=[
        DummyResult([]),  # no blocks
        DummyResult([]),  # no rules
    ])

    service = _fresh_service()
    assert service._evaluate_ip_uncached("9.9.9.9", "/", session) is True


# ---------------------------------------------------------------------------
# Allowlist mode defaults
# ---------------------------------------------------------------------------


def test_allowlist_default_denies(monkeypatch):
    """In allowlist mode, IPs not matching any rule are denied."""
    monkeypatch.setattr(svc.settings, "ip_control_enabled", True)
    monkeypatch.setattr(svc.settings, "ip_control_mode", "allowlist")
    monkeypatch.setattr(svc.settings, "ip_control_cache_ttl", 0)

    session = DummySession(execute_results=[
        DummyResult([]),  # no blocks
        DummyResult([]),  # no rules
    ])

    service = _fresh_service()
    assert service._evaluate_ip_uncached("9.9.9.9", "/", session) is False


# ---------------------------------------------------------------------------
# Rule matching
# ---------------------------------------------------------------------------


def test_deny_rule_blocks_ip(monkeypatch):
    monkeypatch.setattr(svc.settings, "ip_control_enabled", True)
    monkeypatch.setattr(svc.settings, "ip_control_mode", "blocklist")

    rule = _make_rule(ip_pattern="10.0.0.0/8", rule_type="deny")
    session = DummySession(execute_results=[
        DummyResult([]),       # no blocks
        DummyResult([rule]),   # one deny rule
    ])

    service = _fresh_service()
    assert service._evaluate_ip_uncached("10.0.0.5", "/", session) is False


def test_allow_rule_allows_ip(monkeypatch):
    monkeypatch.setattr(svc.settings, "ip_control_enabled", True)
    monkeypatch.setattr(svc.settings, "ip_control_mode", "allowlist")

    rule = _make_rule(ip_pattern="10.0.0.0/8", rule_type="allow")
    session = DummySession(execute_results=[
        DummyResult([]),       # no blocks
        DummyResult([rule]),   # one allow rule
    ])

    service = _fresh_service()
    assert service._evaluate_ip_uncached("10.0.0.5", "/", session) is True


# ---------------------------------------------------------------------------
# Priority ordering
# ---------------------------------------------------------------------------


def test_priority_ordering_first_match_wins(monkeypatch):
    """Lower priority number matches first."""
    monkeypatch.setattr(svc.settings, "ip_control_enabled", True)
    monkeypatch.setattr(svc.settings, "ip_control_mode", "blocklist")

    allow_rule = _make_rule(rule_id="r1", ip_pattern="10.0.0.0/8", rule_type="allow", priority=10)
    deny_rule = _make_rule(rule_id="r2", ip_pattern="10.0.0.0/8", rule_type="deny", priority=20)
    session = DummySession(execute_results=[
        DummyResult([]),                       # no blocks
        DummyResult([allow_rule, deny_rule]),   # rules sorted by priority
    ])

    service = _fresh_service()
    # The allow rule (priority 10) should match first
    assert service._evaluate_ip_uncached("10.0.0.5", "/", session) is True


# ---------------------------------------------------------------------------
# Path-scoped rules
# ---------------------------------------------------------------------------


def test_path_pattern_match(monkeypatch):
    monkeypatch.setattr(svc.settings, "ip_control_enabled", True)
    monkeypatch.setattr(svc.settings, "ip_control_mode", "blocklist")

    rule = _make_rule(ip_pattern="10.0.0.0/8", rule_type="deny", path_pattern="^/api/")
    session = DummySession(execute_results=[
        DummyResult([]),       # no blocks
        DummyResult([rule]),   # one deny rule with path pattern
    ])

    service = _fresh_service()
    assert service._evaluate_ip_uncached("10.0.0.5", "/api/tools", session) is False


def test_path_pattern_no_match_skips_rule(monkeypatch):
    """A rule with a non-matching path pattern is skipped."""
    monkeypatch.setattr(svc.settings, "ip_control_enabled", True)
    monkeypatch.setattr(svc.settings, "ip_control_mode", "blocklist")

    rule = _make_rule(ip_pattern="10.0.0.0/8", rule_type="deny", path_pattern="^/api/")
    session = DummySession(execute_results=[
        DummyResult([]),       # no blocks
        DummyResult([rule]),   # one deny rule with path pattern
    ])

    service = _fresh_service()
    # Path /health doesn't match ^/api/ so rule is skipped -> default allow for blocklist
    assert service._evaluate_ip_uncached("10.0.0.5", "/health", session) is True


# ---------------------------------------------------------------------------
# Temporary blocks
# ---------------------------------------------------------------------------


def test_temp_block_overrides_allow_rules(monkeypatch):
    """Temporary blocks take precedence over allow rules."""
    monkeypatch.setattr(svc.settings, "ip_control_enabled", True)
    monkeypatch.setattr(svc.settings, "ip_control_mode", "allowlist")

    block = _make_block(ip_address="10.0.0.5")
    allow_rule = _make_rule(ip_pattern="10.0.0.0/8", rule_type="allow")
    session = DummySession(execute_results=[
        DummyResult([block]),       # active block
        DummyResult([allow_rule]),  # allow rule
    ])

    service = _fresh_service()
    # Block should override the allow rule
    assert service._evaluate_ip_uncached("10.0.0.5", "/", session) is False


# ---------------------------------------------------------------------------
# Cache tests
# ---------------------------------------------------------------------------


def test_cache_hit(monkeypatch):
    monkeypatch.setattr(svc.settings, "ip_control_enabled", True)
    monkeypatch.setattr(svc.settings, "ip_control_mode", "blocklist")
    monkeypatch.setattr(svc.settings, "ip_control_cache_ttl", 300)
    monkeypatch.setattr(svc.settings, "ip_control_cache_size", 100)

    service = _fresh_service()
    # Manually set a cache entry
    key = service._cache_key("1.2.3.4", "/")
    service._cache[key] = (True, time.monotonic() + 300)

    # Should use cache (no DB call needed)
    assert service.evaluate_ip("1.2.3.4", "/") is True


def test_cache_invalidation(monkeypatch):
    monkeypatch.setattr(svc.settings, "ip_control_cache_ttl", 300)
    monkeypatch.setattr(svc.settings, "ip_control_cache_size", 100)

    service = _fresh_service()
    key = service._cache_key("1.2.3.4", "/")
    service._cache[key] = (True, time.monotonic() + 300)

    service.invalidate_cache()
    assert len(service._cache) == 0


def test_cache_ttl_expiry(monkeypatch):
    monkeypatch.setattr(svc.settings, "ip_control_cache_ttl", 300)
    monkeypatch.setattr(svc.settings, "ip_control_cache_size", 100)

    service = _fresh_service()
    key = service._cache_key("1.2.3.4", "/")
    # Set expired entry
    service._cache[key] = (True, time.monotonic() - 1)

    assert service._cache_get(key) is None


def test_cache_set_eviction(monkeypatch):
    monkeypatch.setattr(svc.settings, "ip_control_cache_ttl", 300)
    monkeypatch.setattr(svc.settings, "ip_control_cache_size", 4)

    service = _fresh_service()
    # Fill cache to capacity
    for i in range(4):
        service._cache_set(f"key{i}", True)
    assert len(service._cache) == 4

    # Adding one more should trigger eviction
    service._cache_set("key_new", False)
    assert len(service._cache) <= 4


def test_get_cache_stats(monkeypatch):
    monkeypatch.setattr(svc.settings, "ip_control_cache_ttl", 300)
    monkeypatch.setattr(svc.settings, "ip_control_cache_size", 100)

    service = _fresh_service()
    service._cache_set("k1", True)
    stats = service.get_cache_stats()
    assert stats["total_entries"] == 1
    assert stats["live_entries"] == 1
    assert stats["max_size"] == 100


# ---------------------------------------------------------------------------
# CRUD cache invalidation
# ---------------------------------------------------------------------------


def test_create_rule_invalidates_cache(monkeypatch):
    monkeypatch.setattr(svc.settings, "ip_control_default_priority", 100)
    monkeypatch.setattr(svc.settings, "ip_control_cache_ttl", 300)
    monkeypatch.setattr(svc.settings, "ip_control_cache_size", 100)
    monkeypatch.setattr(svc.settings, "audit_trail_enabled", False)

    service = _fresh_service()
    service._cache_set("some_key", True)
    assert len(service._cache) == 1

    session = MagicMock()

    # Mock IPRule constructor to return a mock
    mock_rule = MagicMock()
    mock_rule.id = "test-id"
    mock_rule.rule_type = "deny"
    mock_rule.ip_pattern = "10.0.0.0/8"
    monkeypatch.setattr(svc, "IPRule", lambda **kwargs: mock_rule)

    service.create_rule(
        data={"ip_pattern": "10.0.0.0/8", "rule_type": "deny"},
        user_email="admin@test.com",
        db=session,
    )

    # Cache should be cleared
    assert len(service._cache) == 0


# ---------------------------------------------------------------------------
# test_ip diagnostic
# ---------------------------------------------------------------------------


def test_test_ip_disabled(monkeypatch):
    monkeypatch.setattr(svc.settings, "ip_control_enabled", False)
    monkeypatch.setattr(svc.settings, "ip_control_mode", "disabled")

    service = _fresh_service()
    result = service.test_ip("1.2.3.4", "/", MagicMock())
    assert result["allowed"] is True
    assert result["mode"] == "disabled"


def test_test_ip_enabled_block_match(monkeypatch):
    """test_ip returns blocked when temp block matches."""
    monkeypatch.setattr(svc.settings, "ip_control_enabled", True)
    monkeypatch.setattr(svc.settings, "ip_control_mode", "blocklist")

    block = _make_block(block_id="b99", ip_address="10.0.0.1")
    session = DummySession(execute_results=[
        DummyResult([block]),  # block found
    ])

    service = _fresh_service()
    result = service.test_ip("10.0.0.1", "/api/tools", session)
    assert result["allowed"] is False
    assert result["blocked_by_temp_block"] is True
    assert result["matched_rule_id"] == "b99"
    assert result["matched_rule_type"] == "block"


def test_test_ip_enabled_rule_match(monkeypatch):
    """test_ip returns matched rule details when a rule matches."""
    monkeypatch.setattr(svc.settings, "ip_control_enabled", True)
    monkeypatch.setattr(svc.settings, "ip_control_mode", "blocklist")

    rule = _make_rule(rule_id="r10", ip_pattern="10.0.0.0/8", rule_type="deny")
    session = DummySession(execute_results=[
        DummyResult([]),       # no blocks
        DummyResult([rule]),   # deny rule
    ])

    service = _fresh_service()
    result = service.test_ip("10.0.0.5", "/", session)
    assert result["allowed"] is False
    assert result["matched_rule_id"] == "r10"
    assert result["matched_rule_type"] == "deny"
    assert result["blocked_by_temp_block"] is False


def test_test_ip_enabled_allow_rule_match(monkeypatch):
    """test_ip returns allowed when allow rule matches."""
    monkeypatch.setattr(svc.settings, "ip_control_enabled", True)
    monkeypatch.setattr(svc.settings, "ip_control_mode", "allowlist")

    rule = _make_rule(rule_id="r11", ip_pattern="10.0.0.0/8", rule_type="allow")
    session = DummySession(execute_results=[
        DummyResult([]),       # no blocks
        DummyResult([rule]),   # allow rule
    ])

    service = _fresh_service()
    result = service.test_ip("10.0.0.5", "/", session)
    assert result["allowed"] is True
    assert result["matched_rule_id"] == "r11"
    assert result["matched_rule_type"] == "allow"


def test_test_ip_enabled_no_match_allowlist(monkeypatch):
    """test_ip defaults to deny in allowlist mode with no matches."""
    monkeypatch.setattr(svc.settings, "ip_control_enabled", True)
    monkeypatch.setattr(svc.settings, "ip_control_mode", "allowlist")

    session = DummySession(execute_results=[
        DummyResult([]),  # no blocks
        DummyResult([]),  # no rules
    ])

    service = _fresh_service()
    result = service.test_ip("9.9.9.9", "/", session)
    assert result["allowed"] is False
    assert result["matched_rule_id"] is None
    assert result["mode"] == "allowlist"


def test_test_ip_enabled_no_match_blocklist(monkeypatch):
    """test_ip defaults to allow in blocklist mode with no matches."""
    monkeypatch.setattr(svc.settings, "ip_control_enabled", True)
    monkeypatch.setattr(svc.settings, "ip_control_mode", "blocklist")

    session = DummySession(execute_results=[
        DummyResult([]),  # no blocks
        DummyResult([]),  # no rules
    ])

    service = _fresh_service()
    result = service.test_ip("9.9.9.9", "/", session)
    assert result["allowed"] is True
    assert result["matched_rule_id"] is None
    assert result["mode"] == "blocklist"


# ---------------------------------------------------------------------------
# get_status
# ---------------------------------------------------------------------------


def test_get_status(monkeypatch):
    """get_status returns counts and settings."""
    monkeypatch.setattr(svc.settings, "ip_control_enabled", True)
    monkeypatch.setattr(svc.settings, "ip_control_mode", "blocklist")
    monkeypatch.setattr(svc.settings, "ip_control_log_only", False)
    monkeypatch.setattr(svc.settings, "ip_control_cache_ttl", 300)
    monkeypatch.setattr(svc.settings, "ip_control_cache_size", 100)
    monkeypatch.setattr(svc.settings, "ip_control_skip_paths", ["/health"])

    session = DummySession(execute_results=[
        DummyScalar(5),   # total_rules
        DummyScalar(3),   # active_rules
        DummyScalar(2),   # total_blocks
        DummyScalar(1),   # active_blocks
    ])

    service = _fresh_service()
    result = service.get_status(session)
    assert result["enabled"] is True
    assert result["mode"] == "blocklist"
    assert result["total_rules"] == 5
    assert result["active_rules"] == 3
    assert result["total_blocks"] == 2
    assert result["active_blocks"] == 1
    assert result["cache_ttl"] == 300
    assert result["skip_paths"] == ["/health"]


# ---------------------------------------------------------------------------
# evaluate_ip: SessionLocal creation and error paths
# ---------------------------------------------------------------------------


def test_evaluate_ip_creates_session_when_none(monkeypatch):
    """evaluate_ip creates a SessionLocal when no db is passed."""
    monkeypatch.setattr(svc.settings, "ip_control_enabled", True)
    monkeypatch.setattr(svc.settings, "ip_control_mode", "blocklist")
    monkeypatch.setattr(svc.settings, "ip_control_cache_ttl", 0)

    mock_db = DummySession(execute_results=[
        DummyResult([]),  # no blocks
        DummyResult([]),  # no rules
    ])
    monkeypatch.setattr(svc, "SessionLocal", lambda: mock_db)

    service = _fresh_service()
    result = service.evaluate_ip("9.9.9.9", "/")
    assert result is True


def test_evaluate_ip_exception_fails_open(monkeypatch):
    """evaluate_ip returns True (fail open) on exception."""
    monkeypatch.setattr(svc.settings, "ip_control_enabled", True)
    monkeypatch.setattr(svc.settings, "ip_control_mode", "blocklist")
    monkeypatch.setattr(svc.settings, "ip_control_cache_ttl", 0)

    mock_db = MagicMock()
    mock_db.execute.side_effect = RuntimeError("DB error")

    service = _fresh_service()
    result = service.evaluate_ip("9.9.9.9", "/", db=mock_db)
    assert result is True


def test_evaluate_ip_closes_created_session(monkeypatch):
    """evaluate_ip closes the session it creates, even on error."""
    monkeypatch.setattr(svc.settings, "ip_control_enabled", True)
    monkeypatch.setattr(svc.settings, "ip_control_mode", "blocklist")
    monkeypatch.setattr(svc.settings, "ip_control_cache_ttl", 0)

    mock_db = MagicMock()
    mock_db.execute.side_effect = RuntimeError("DB error")
    monkeypatch.setattr(svc, "SessionLocal", lambda: mock_db)

    service = _fresh_service()
    service.evaluate_ip("9.9.9.9", "/")
    mock_db.close.assert_called_once()


def test_evaluate_ip_does_not_close_provided_session(monkeypatch):
    """evaluate_ip does NOT close a session that was passed in."""
    monkeypatch.setattr(svc.settings, "ip_control_enabled", True)
    monkeypatch.setattr(svc.settings, "ip_control_mode", "blocklist")
    monkeypatch.setattr(svc.settings, "ip_control_cache_ttl", 0)

    session = DummySession(execute_results=[
        DummyResult([]),  # no blocks
        DummyResult([]),  # no rules
    ])
    # Track close calls
    close_called = []
    original_close = session.close
    session.close = lambda: close_called.append(True)

    service = _fresh_service()
    service.evaluate_ip("9.9.9.9", "/", db=session)
    assert len(close_called) == 0


# ---------------------------------------------------------------------------
# Hit count rollback path
# ---------------------------------------------------------------------------


def test_hit_count_update_rollback_on_commit_error(monkeypatch):
    """When hit count commit fails, rollback is attempted."""
    monkeypatch.setattr(svc.settings, "ip_control_enabled", True)
    monkeypatch.setattr(svc.settings, "ip_control_mode", "blocklist")

    rule = _make_rule(ip_pattern="10.0.0.0/8", rule_type="deny", hit_count=5)
    session = MagicMock()
    session.execute.side_effect = [
        DummyResult([]),       # no blocks
        DummyResult([rule]),   # deny rule
    ]
    session.commit.side_effect = RuntimeError("commit failed")

    service = _fresh_service()
    result = service._evaluate_ip_uncached("10.0.0.5", "/", session)
    assert result is False
    session.rollback.assert_called_once()


def test_hit_count_update_rollback_also_fails(monkeypatch):
    """When both commit and rollback fail, it should not raise."""
    monkeypatch.setattr(svc.settings, "ip_control_enabled", True)
    monkeypatch.setattr(svc.settings, "ip_control_mode", "blocklist")

    rule = _make_rule(ip_pattern="10.0.0.0/8", rule_type="deny", hit_count=5)
    session = MagicMock()
    session.execute.side_effect = [
        DummyResult([]),       # no blocks
        DummyResult([rule]),   # deny rule
    ]
    session.commit.side_effect = RuntimeError("commit failed")
    session.rollback.side_effect = RuntimeError("rollback also failed")

    service = _fresh_service()
    result = service._evaluate_ip_uncached("10.0.0.5", "/", session)
    assert result is False


# ---------------------------------------------------------------------------
# CRUD: update_rule
# ---------------------------------------------------------------------------


def test_update_rule_success(monkeypatch):
    """update_rule updates fields and invalidates cache."""
    monkeypatch.setattr(svc.settings, "audit_trail_enabled", False)
    monkeypatch.setattr(svc.settings, "ip_control_cache_ttl", 300)
    monkeypatch.setattr(svc.settings, "ip_control_cache_size", 100)

    rule = _make_rule(rule_id="r1", ip_pattern="10.0.0.0/8", rule_type="deny", priority=100)
    rule.updated_by = "admin@test.com"
    session = MagicMock()
    session.execute.return_value = DummyResult([rule])

    service = _fresh_service()
    service._cache_set("stale", True)

    result = service.update_rule("r1", {"priority": 50}, "admin@test.com", session)
    assert result is not None
    assert rule.priority == 50
    assert rule.updated_by == "admin@test.com"
    assert len(service._cache) == 0  # cache cleared
    session.commit.assert_called()
    session.refresh.assert_called_with(rule)


def test_update_rule_not_found(monkeypatch):
    """update_rule returns None when rule is not found."""
    monkeypatch.setattr(svc.settings, "audit_trail_enabled", False)

    session = MagicMock()
    session.execute.return_value = DummyResult([])

    service = _fresh_service()
    result = service.update_rule("missing", {"priority": 50}, "admin@test.com", session)
    assert result is None


# ---------------------------------------------------------------------------
# CRUD: delete_rule
# ---------------------------------------------------------------------------


def test_delete_rule_success(monkeypatch):
    """delete_rule deletes and invalidates cache."""
    monkeypatch.setattr(svc.settings, "audit_trail_enabled", False)
    monkeypatch.setattr(svc.settings, "ip_control_cache_ttl", 300)
    monkeypatch.setattr(svc.settings, "ip_control_cache_size", 100)

    rule = _make_rule(rule_id="r1")
    session = MagicMock()
    session.execute.return_value = DummyResult([rule])

    service = _fresh_service()
    service._cache_set("stale", True)

    result = service.delete_rule("r1", "admin@test.com", session)
    assert result is True
    session.delete.assert_called_with(rule)
    session.commit.assert_called()
    assert len(service._cache) == 0


def test_delete_rule_not_found(monkeypatch):
    """delete_rule returns False when rule is not found."""
    monkeypatch.setattr(svc.settings, "audit_trail_enabled", False)

    session = MagicMock()
    session.execute.return_value = DummyResult([])

    service = _fresh_service()
    result = service.delete_rule("missing", "admin@test.com", session)
    assert result is False


# ---------------------------------------------------------------------------
# CRUD: get_rule
# ---------------------------------------------------------------------------


def test_get_rule_found():
    """get_rule returns the rule when found."""
    rule = _make_rule(rule_id="r1")
    session = MagicMock()
    session.execute.return_value = DummyResult([rule])

    service = _fresh_service()
    result = service.get_rule("r1", session)
    assert result is rule


def test_get_rule_not_found():
    """get_rule returns None when rule is not found."""
    session = MagicMock()
    session.execute.return_value = DummyResult([])

    service = _fresh_service()
    result = service.get_rule("missing", session)
    assert result is None


# ---------------------------------------------------------------------------
# CRUD: list_rules
# ---------------------------------------------------------------------------


def test_list_rules_no_filters():
    """list_rules returns all rules with count."""
    rules = [_make_rule("r1"), _make_rule("r2")]
    session = MagicMock()
    session.execute.side_effect = [
        DummyScalar(2),       # count
        DummyResult(rules),   # rules
    ]

    service = _fresh_service()
    result_rules, total = service.list_rules(session, limit=50, offset=0)
    assert total == 2
    assert len(result_rules) == 2


def test_list_rules_with_active_filter():
    """list_rules filters by is_active."""
    rules = [_make_rule("r1")]
    session = MagicMock()
    session.execute.side_effect = [
        DummyScalar(1),       # count
        DummyResult(rules),   # rules
    ]

    service = _fresh_service()
    result_rules, total = service.list_rules(session, is_active=True)
    assert total == 1


def test_list_rules_with_type_filter():
    """list_rules filters by rule_type."""
    rules = [_make_rule("r1", rule_type="deny")]
    session = MagicMock()
    session.execute.side_effect = [
        DummyScalar(1),
        DummyResult(rules),
    ]

    service = _fresh_service()
    result_rules, total = service.list_rules(session, rule_type="deny")
    assert total == 1
    assert result_rules[0].rule_type == "deny"


# ---------------------------------------------------------------------------
# CRUD: create_block
# ---------------------------------------------------------------------------


def test_create_block(monkeypatch):
    """create_block creates a block and invalidates cache."""
    monkeypatch.setattr(svc.settings, "audit_trail_enabled", False)
    monkeypatch.setattr(svc.settings, "ip_control_cache_ttl", 300)
    monkeypatch.setattr(svc.settings, "ip_control_cache_size", 100)

    session = MagicMock()
    mock_block = MagicMock()
    mock_block.id = "block-id"
    mock_block.ip_address = "1.2.3.4"
    monkeypatch.setattr(svc, "IPBlock", lambda **kwargs: mock_block)

    service = _fresh_service()
    service._cache_set("stale", True)

    result = service.create_block(
        data={"ip_address": "1.2.3.4", "reason": "test", "duration_minutes": 60},
        user_email="admin@test.com",
        db=session,
    )
    assert result is mock_block
    session.add.assert_called_with(mock_block)
    session.commit.assert_called()
    assert len(service._cache) == 0


# ---------------------------------------------------------------------------
# CRUD: remove_block
# ---------------------------------------------------------------------------


def test_remove_block_success(monkeypatch):
    """remove_block deactivates the block."""
    monkeypatch.setattr(svc.settings, "audit_trail_enabled", False)
    monkeypatch.setattr(svc.settings, "ip_control_cache_ttl", 300)
    monkeypatch.setattr(svc.settings, "ip_control_cache_size", 100)

    block = _make_block(block_id="b1")
    session = MagicMock()
    session.execute.return_value = DummyResult([block])

    service = _fresh_service()
    service._cache_set("stale", True)

    result = service.remove_block("b1", "admin@test.com", session)
    assert result is True
    assert block.is_active is False
    assert block.unblocked_by == "admin@test.com"
    assert len(service._cache) == 0


def test_remove_block_not_found(monkeypatch):
    """remove_block returns False when block is not found."""
    monkeypatch.setattr(svc.settings, "audit_trail_enabled", False)

    session = MagicMock()
    session.execute.return_value = DummyResult([])

    service = _fresh_service()
    result = service.remove_block("missing", "admin@test.com", session)
    assert result is False


# ---------------------------------------------------------------------------
# CRUD: list_blocks
# ---------------------------------------------------------------------------


def test_list_blocks_active_only():
    """list_blocks with active_only=True filters."""
    blocks = [_make_block("b1")]
    session = MagicMock()
    session.execute.return_value = DummyResult(blocks)

    service = _fresh_service()
    result = service.list_blocks(session, active_only=True)
    assert len(result) == 1


def test_list_blocks_all():
    """list_blocks with active_only=False returns all."""
    blocks = [_make_block("b1"), _make_block("b2")]
    session = MagicMock()
    session.execute.return_value = DummyResult(blocks)

    service = _fresh_service()
    result = service.list_blocks(session, active_only=False)
    assert len(result) == 2


# ---------------------------------------------------------------------------
# cleanup_expired_blocks
# ---------------------------------------------------------------------------


def test_cleanup_expired_blocks_with_expired(monkeypatch):
    """cleanup deactivates expired blocks and invalidates cache."""
    monkeypatch.setattr(svc.settings, "ip_control_cache_ttl", 300)
    monkeypatch.setattr(svc.settings, "ip_control_cache_size", 100)

    block1 = _make_block("b1")
    block2 = _make_block("b2")
    session = MagicMock()
    session.execute.return_value = DummyResult([block1, block2])

    service = _fresh_service()
    service._cache_set("stale", True)

    count = service.cleanup_expired_blocks(session)
    assert count == 2
    assert block1.is_active is False
    assert block2.is_active is False
    session.commit.assert_called_once()
    assert len(service._cache) == 0


def test_cleanup_expired_blocks_none_expired():
    """cleanup returns 0 when no expired blocks exist."""
    session = MagicMock()
    session.execute.return_value = DummyResult([])

    service = _fresh_service()
    count = service.cleanup_expired_blocks(session)
    assert count == 0
    session.commit.assert_not_called()


# ---------------------------------------------------------------------------
# get_ip_control_service singleton accessor
# ---------------------------------------------------------------------------


def test_get_ip_control_service_creates_instance(monkeypatch):
    """get_ip_control_service creates and caches a singleton."""
    monkeypatch.setattr(svc, "_ip_control_service", None)
    # Reset the class-level singleton so __new__ creates fresh
    original = svc.IPControlService._instance
    svc.IPControlService._instance = None
    try:
        result = svc.get_ip_control_service()
        assert result is not None
        assert isinstance(result, svc.IPControlService)
        # Second call returns same instance
        result2 = svc.get_ip_control_service()
        assert result2 is result
    finally:
        svc.IPControlService._instance = original
        svc._ip_control_service = None


# ---------------------------------------------------------------------------
# _cache_set with TTL <= 0 skips caching
# ---------------------------------------------------------------------------


def test_cache_set_zero_ttl_skips(monkeypatch):
    """_cache_set with TTL=0 does not store anything."""
    monkeypatch.setattr(svc.settings, "ip_control_cache_ttl", 0)

    service = _fresh_service()
    service._cache_set("key1", True)
    assert len(service._cache) == 0
