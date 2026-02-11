# -*- coding: utf-8 -*-
"""Tests for policy_decision_service."""

# Standard
from unittest.mock import MagicMock

# Third-Party
import pytest

# First-Party
from mcpgateway.services import policy_decision_service as svc


class DummyResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return self

    def all(self):
        return self._items

    def scalar(self):
        return self._items[0] if self._items else None

    def __iter__(self):
        return iter(self._items)


class DummySession:
    def __init__(self, fail_add: bool = False):
        self.fail_add = fail_add
        self.committed = False
        self.rolled_back = False
        self.closed = False
        self.added = []

    def add(self, obj):
        if self.fail_add:
            raise RuntimeError("db add failed")
        self.added.append(obj)

    def commit(self):
        self.committed = True

    def refresh(self, _obj):
        return None

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True

    def execute(self, _query):
        return DummyResult([])


def test_disabled_service_returns_policy_decision(monkeypatch):
    """When policy_audit_enabled is False, log_decision still returns a PolicyDecision."""
    monkeypatch.setattr(svc.settings, "policy_audit_enabled", False)
    service = svc.PolicyDecisionService()
    result = service.log_decision(action="tools.invoke", decision="allow")
    assert result is not None
    assert result.action == "tools.invoke"
    assert result.decision == "allow"


def test_happy_path_creates_and_returns_record(monkeypatch):
    """When enabled, log_decision creates a record and commits it."""
    monkeypatch.setattr(svc.settings, "policy_audit_enabled", True)
    dummy_session = DummySession()
    monkeypatch.setattr(svc, "SessionLocal", lambda: dummy_session)

    service = svc.PolicyDecisionService()
    result = service.log_decision(
        action="tools.invoke",
        decision="allow",
        subject_id="user@example.com",
        subject_email="user@example.com",
        resource_type="tool",
        resource_id="tool-1",
    )

    assert result is not None
    assert result.action == "tools.invoke"
    assert result.decision == "allow"
    assert dummy_session.committed is True
    assert dummy_session.closed is True
    assert len(dummy_session.added) == 1


def test_db_exception_returns_fallback_record(monkeypatch):
    """When DB fails, log_decision returns a fallback record (not None)."""
    monkeypatch.setattr(svc.settings, "policy_audit_enabled", True)
    dummy_session = DummySession(fail_add=True)
    monkeypatch.setattr(svc, "SessionLocal", lambda: dummy_session)

    service = svc.PolicyDecisionService()
    result = service.log_decision(action="tools.invoke", decision="deny")

    assert result is not None
    assert result.action == "tools.invoke"
    assert result.decision == "deny"
    assert dummy_session.rolled_back is True
    assert dummy_session.closed is True


def test_sort_column_allowlist_validation(monkeypatch):
    """Invalid sort_by column is replaced with 'timestamp'."""
    monkeypatch.setattr(svc.settings, "policy_audit_enabled", True)
    dummy_session = DummySession()
    monkeypatch.setattr(svc, "SessionLocal", lambda: dummy_session)

    service = svc.PolicyDecisionService()
    # Should not raise - invalid sort_by is sanitized
    result = service.query_decisions(sort_by="DROP TABLE", sort_order="desc")
    assert isinstance(result, list)


def test_sort_order_validation(monkeypatch):
    """Invalid sort_order is replaced with 'desc'."""
    monkeypatch.setattr(svc.settings, "policy_audit_enabled", True)
    dummy_session = DummySession()
    monkeypatch.setattr(svc, "SessionLocal", lambda: dummy_session)

    service = svc.PolicyDecisionService()
    # Should not raise - invalid sort_order is sanitized
    result = service.query_decisions(sort_by="timestamp", sort_order="INVALID")
    assert isinstance(result, list)


def test_get_statistics_returns_structure(monkeypatch):
    """get_statistics returns expected dict structure."""
    monkeypatch.setattr(svc.settings, "policy_audit_enabled", True)

    call_count = 0

    class StatsSession(DummySession):
        def execute(self, _query):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Total count query
                return DummyResult([5])
            elif call_count == 2:
                # Group by query - returns rows of (decision, count)
                return DummyResult([])
            else:
                # Avg duration query
                return DummyResult([1.5])

    dummy_session = StatsSession()
    monkeypatch.setattr(svc, "SessionLocal", lambda: dummy_session)

    service = svc.PolicyDecisionService()
    stats = service.get_statistics()

    assert "total_decisions" in stats
    assert "allowed" in stats
    assert "denied" in stats
    assert "avg_duration_ms" in stats
    assert "time_range" in stats


def test_siem_processor_wiring(monkeypatch):
    """set_siem_processor attaches a processor for SIEM forwarding."""
    service = svc.PolicyDecisionService()
    assert service._siem_processor is None

    mock_processor = MagicMock()
    service.set_siem_processor(mock_processor)
    assert service._siem_processor is mock_processor
