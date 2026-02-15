# -*- coding: utf-8 -*-
"""Tests for audit_trail_service."""

# Standard
from unittest.mock import MagicMock

# Third-Party
import pytest

# First-Party
from mcpgateway.services import audit_trail_service as svc


class DummyResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return self

    def all(self):
        return self._items


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
        return DummyResult([MagicMock(id="1")])


def test_log_action_disabled_returns_none(monkeypatch):
    monkeypatch.setattr(svc.settings, "audit_trail_enabled", False)
    service = svc.AuditTrailService()
    result = service.log_action(
        action="CREATE",
        resource_type="tool",
        resource_id="tool-1",
        user_id="user-1",
    )
    assert result is None


def test_log_action_builds_context_and_requires_review(monkeypatch):
    monkeypatch.setattr(svc.settings, "audit_trail_enabled", True)
    dummy_session = DummySession()
    monkeypatch.setattr(svc, "SessionLocal", lambda: dummy_session)

    captured = {}

    def _fake_audit(**kwargs):
        captured.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(svc, "AuditTrail", _fake_audit)

    service = svc.AuditTrailService()
    result = service.log_action(
        action="UPDATE",
        resource_type="tool",
        resource_id="tool-1",
        user_id="user-1",
        details={"d": 1},
        metadata={"m": 2},
        data_classification=svc.DataClassification.CONFIDENTIAL.value,
    )

    assert result is not None
    assert captured["context"]["details"] == {"d": 1}
    assert captured["context"]["metadata"] == {"m": 2}
    assert captured["requires_review"] is True
    assert dummy_session.committed is True


def test_log_action_exception_rolls_back(monkeypatch):
    monkeypatch.setattr(svc.settings, "audit_trail_enabled", True)
    dummy_session = DummySession(fail_add=True)
    monkeypatch.setattr(svc, "SessionLocal", lambda: dummy_session)
    monkeypatch.setattr(svc, "AuditTrail", lambda **_kwargs: MagicMock())

    service = svc.AuditTrailService()
    result = service.log_action(
        action="CREATE",
        resource_type="tool",
        resource_id="tool-1",
        user_id="user-1",
    )
    assert result is None
    assert dummy_session.rolled_back is True


def test_log_crud_operation_changes(monkeypatch):
    service = svc.AuditTrailService()
    captured = {}

    def _fake_log_action(**kwargs):
        captured.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(service, "log_action", _fake_log_action)
    service.log_crud_operation(
        operation="UPDATE",
        resource_type="tool",
        resource_id="tool-1",
        user_id="user-1",
        old_values={"a": 1, "b": 2},
        new_values={"a": 1, "b": 3},
    )

    assert captured["changes"] == {"b": {"old": 2, "new": 3}}
    assert captured["data_classification"] == svc.DataClassification.INTERNAL.value


def test_log_data_access_requires_review(monkeypatch):
    service = svc.AuditTrailService()
    captured = {}

    def _fake_log_action(**kwargs):
        captured.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(service, "log_action", _fake_log_action)
    service.log_data_access(
        resource_type="token",
        resource_id="tok-1",
        user_id="user-1",
        data_classification=svc.DataClassification.CONFIDENTIAL.value,
    )

    assert captured["requires_review"] is True
    assert captured["action"] == "READ"


def test_get_audit_trail_commits_and_returns(monkeypatch):
    monkeypatch.setattr(svc.settings, "audit_trail_enabled", True)
    dummy_session = DummySession()
    monkeypatch.setattr(svc, "SessionLocal", lambda: dummy_session)

    service = svc.AuditTrailService()
    result = service.get_audit_trail(resource_type="tool", limit=1)
    assert len(result) == 1
    assert dummy_session.committed is True
    assert dummy_session.closed is True


def test_determine_requires_review_respects_explicit_param():
    service = svc.AuditTrailService()
    assert service._determine_requires_review(action="CREATE", data_classification=None, requires_review_param=True) is True
    assert service._determine_requires_review(action="CREATE", data_classification=None, requires_review_param=False) is False


def test_determine_requires_review_flags_review_required_actions():
    service = svc.AuditTrailService()
    assert service._determine_requires_review(action="delete_tool", data_classification=None, requires_review_param=None) is True


def test_log_crud_operation_confidential_resource_requires_review(monkeypatch):
    service = svc.AuditTrailService()
    captured = {}

    def _fake_log_action(**kwargs):
        captured.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(service, "log_action", _fake_log_action)
    service.log_crud_operation(
        operation="CREATE",
        resource_type="token",
        resource_id="tok-1",
        user_id="user-1",
    )

    assert captured["data_classification"] == svc.DataClassification.CONFIDENTIAL.value
    assert captured["requires_review"] is True


def test_log_crud_operation_delete_tool_requires_review(monkeypatch):
    service = svc.AuditTrailService()
    captured = {}

    def _fake_log_action(**kwargs):
        captured.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(service, "log_action", _fake_log_action)
    service.log_crud_operation(
        operation="DELETE",
        resource_type="tool",
        resource_id="tool-1",
        user_id="user-1",
    )

    assert captured["requires_review"] is True


def test_log_audit_builds_context_from_description(monkeypatch):
    service = svc.AuditTrailService()
    captured = {}

    def _fake_log_action(**kwargs):
        captured.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(service, "log_action", _fake_log_action)
    service.log_audit(
        user_id="user-1",
        resource_type="tool",
        resource_id="tool-1",
        action="EXECUTE",
        description="ran tool",
    )

    assert captured["context"]["description"] == "ran tool"


def test_get_audit_trail_applies_filters(monkeypatch):
    monkeypatch.setattr(svc.settings, "audit_trail_enabled", True)
    dummy_session = DummySession()
    monkeypatch.setattr(svc, "SessionLocal", lambda: dummy_session)

    service = svc.AuditTrailService()
    now = svc.datetime.now(svc.timezone.utc)
    result = service.get_audit_trail(
        resource_type="tool",
        resource_id="tool-1",
        user_id="user-1",
        action="UPDATE",
        start_time=now,
        end_time=now,
        limit=1,
        offset=0,
    )
    assert len(result) == 1
