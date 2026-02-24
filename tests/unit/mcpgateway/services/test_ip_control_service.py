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
