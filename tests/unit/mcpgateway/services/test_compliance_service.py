# -*- coding: utf-8 -*-
"""Tests for compliance_service."""

# Standard
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

# Third-Party
import pytest

# First-Party
from mcpgateway.services import compliance_service as svc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

START = datetime(2025, 1, 1, tzinfo=timezone.utc)
END = datetime(2025, 3, 31, tzinfo=timezone.utc)


class DummyResult:
    """Minimal SQLAlchemy result stub."""

    def __init__(self, items):
        """Initialize with items list."""
        self._items = items

    def scalars(self):
        """Return self for chaining."""
        return self

    def all(self):
        """Return items."""
        return self._items


class DummySession:
    """Minimal SQLAlchemy session stub."""

    def __init__(self, users=None, role_assignments=None, audit_entries=None):
        """Initialize session with optional pre-populated collections.

        Args:
            users: List of mock user objects
            role_assignments: List of mock role assignment objects
            audit_entries: List of mock audit trail entries
        """
        self._users = users or []
        self._role_assignments = role_assignments or []
        self._audit_entries = audit_entries or []
        self.committed = False
        self.closed = False

    def execute(self, query):
        """Return results based on query type inspection.

        Args:
            query: SQLAlchemy select object

        Returns:
            DummyResult with appropriate data
        """
        query_str = str(query)
        if "email_users" in query_str:
            return DummyResult(self._users)
        if "user_roles" in query_str:
            return DummyResult(self._role_assignments)
        if "audit_trails" in query_str:
            return DummyResult(self._audit_entries)
        return DummyResult([])

    def commit(self):
        """Mark session as committed."""
        self.committed = True

    def close(self):
        """Mark session as closed."""
        self.closed = True


def _make_user(email="alice@example.com", is_admin=False, is_active=True):
    """Create a mock EmailUser object."""
    u = MagicMock()
    u.email = email
    u.is_admin = is_admin
    u.is_active = is_active
    return u


def _make_role_assignment(is_active=True):
    """Create a mock UserRole object."""
    r = MagicMock()
    r.is_active = is_active
    return r


def _make_audit_entry(success=True, requires_review=False, resource_type="tool"):
    """Create a mock AuditTrail object."""
    e = MagicMock()
    e.success = success
    e.requires_review = requires_review
    e.resource_type = resource_type
    return e


# ---------------------------------------------------------------------------
# collect_user_role_evidence
# ---------------------------------------------------------------------------


def test_collect_user_role_evidence_counts_users():
    """Should return correct counts for users and role assignments."""
    users = [_make_user("a@x.com", is_admin=True), _make_user("b@x.com", is_active=False), _make_user("c@x.com")]
    roles = [_make_role_assignment(True), _make_role_assignment(False)]
    db = DummySession(users=users, role_assignments=roles)

    service = svc.ComplianceService()
    result = service.collect_user_role_evidence(db, svc.ComplianceFramework.FEDRAMP_MODERATE, "AC-2")

    assert result["total_users"] == 3
    assert result["active_users"] == 2
    assert result["admin_users"] == 1
    assert result["total_role_assignments"] == 2
    assert result["active_role_assignments"] == 1
    assert result["control_id"] == "AC-2"
    assert result["framework"] == svc.ComplianceFramework.FEDRAMP_MODERATE.value


def test_collect_user_role_evidence_empty_db():
    """Should return zeros when no users exist."""
    db = DummySession()
    service = svc.ComplianceService()
    result = service.collect_user_role_evidence(db, svc.ComplianceFramework.HIPAA, "164.312(a)(1)")

    assert result["total_users"] == 0
    assert result["admin_users"] == 0


def test_collect_user_role_evidence_db_error():
    """Should return error dict when DB raises an exception."""
    db = MagicMock()
    db.execute.side_effect = RuntimeError("db boom")

    service = svc.ComplianceService()
    result = service.collect_user_role_evidence(db, svc.ComplianceFramework.SOC2_TYPE2, "CC6.1")

    assert "error" in result
    assert result["control_id"] == "CC6.1"


# ---------------------------------------------------------------------------
# collect_audit_log_evidence
# ---------------------------------------------------------------------------


def test_collect_audit_log_evidence_counts_events():
    """Should count total, success, failure and review events."""
    entries = [
        _make_audit_entry(success=True, requires_review=False),
        _make_audit_entry(success=False, requires_review=True),
        _make_audit_entry(success=True, requires_review=True),
    ]
    db = DummySession(audit_entries=entries)

    service = svc.ComplianceService()
    result = service.collect_audit_log_evidence(db, START, END, "AU-2")

    assert result["total_events"] == 3
    assert result["success_events"] == 2
    assert result["failure_events"] == 1
    assert result["review_required_events"] == 2
    assert result["control_id"] == "AU-2"


def test_collect_audit_log_evidence_empty():
    """Should return zeroed counts when no audit entries exist."""
    db = DummySession(audit_entries=[])
    service = svc.ComplianceService()
    result = service.collect_audit_log_evidence(db, START, END, "AU-3")

    assert result["total_events"] == 0
    assert result["failure_events"] == 0


def test_collect_audit_log_evidence_includes_audit_enabled(monkeypatch):
    """Should include the audit_trail_enabled setting in the result."""
    monkeypatch.setattr(svc.settings, "audit_trail_enabled", True)
    db = DummySession(audit_entries=[_make_audit_entry()])
    service = svc.ComplianceService()
    result = service.collect_audit_log_evidence(db, START, END, "AU-6")

    assert result["audit_enabled"] is True


def test_collect_audit_log_evidence_db_error():
    """Should return error dict when DB raises an exception."""
    db = MagicMock()
    db.execute.side_effect = RuntimeError("audit db error")

    service = svc.ComplianceService()
    result = service.collect_audit_log_evidence(db, START, END, "AU-2")

    assert "error" in result


# ---------------------------------------------------------------------------
# collect_config_snapshot
# ---------------------------------------------------------------------------


def test_collect_config_snapshot_returns_settings(monkeypatch):
    """Should return relevant settings fields."""
    monkeypatch.setattr(svc.settings, "auth_required", True)
    monkeypatch.setattr(svc.settings, "audit_trail_enabled", False)
    monkeypatch.setattr(svc.settings, "require_token_expiration", True)
    monkeypatch.setattr(svc.settings, "require_jti", True)

    service = svc.ComplianceService()
    snap = service.collect_config_snapshot("AC-3")

    assert snap["control_id"] == "AC-3"
    assert snap["auth_required"] is True
    assert snap["audit_trail_enabled"] is False
    assert snap["require_token_expiration"] is True
    assert snap["require_jti"] is True
    assert "app_name" in snap


# ---------------------------------------------------------------------------
# generate_report
# ---------------------------------------------------------------------------


def test_generate_report_fedramp_moderate():
    """Should generate a report with all FedRAMP Moderate controls."""
    db = DummySession()
    service = svc.ComplianceService()
    report = service.generate_report(db, svc.ComplianceFramework.FEDRAMP_MODERATE, START, END)

    assert report.framework == svc.ComplianceFramework.FEDRAMP_MODERATE
    control_ids = [c.control_id for c in report.controls]
    assert "AC-2" in control_ids
    assert "AU-2" in control_ids
    assert len(report.controls) == 6


def test_generate_report_hipaa():
    """Should generate a report with all HIPAA controls."""
    db = DummySession()
    service = svc.ComplianceService()
    report = service.generate_report(db, svc.ComplianceFramework.HIPAA, START, END)

    assert report.framework == svc.ComplianceFramework.HIPAA
    control_ids = [c.control_id for c in report.controls]
    assert "164.312(a)(1)" in control_ids
    assert "164.312(b)" in control_ids
    assert len(report.controls) == 3


def test_generate_report_soc2():
    """Should generate a report with all SOC2 Type II controls."""
    db = DummySession()
    service = svc.ComplianceService()
    report = service.generate_report(db, svc.ComplianceFramework.SOC2_TYPE2, START, END)

    assert report.framework == svc.ComplianceFramework.SOC2_TYPE2
    control_ids = [c.control_id for c in report.controls]
    assert "CC6.1" in control_ids
    assert "CC7.2" in control_ids
    assert len(report.controls) == 4


def test_generate_report_fedramp_high():
    """Should generate a report with all FedRAMP High controls."""
    db = DummySession()
    service = svc.ComplianceService()
    report = service.generate_report(db, svc.ComplianceFramework.FEDRAMP_HIGH, START, END)

    assert report.framework == svc.ComplianceFramework.FEDRAMP_HIGH
    assert len(report.controls) == 6


def test_generate_report_has_summary():
    """Summary should include framework, total_controls, and status counts."""
    db = DummySession()
    service = svc.ComplianceService()
    report = service.generate_report(db, svc.ComplianceFramework.SOC2_TYPE2, START, END)

    assert "framework" in report.summary
    assert "total_controls" in report.summary
    assert report.summary["total_controls"] == len(report.controls)
    assert "implemented" in report.summary or "partial" in report.summary


def test_generate_report_stored_in_memory():
    """Generated report should be retrievable via get_report."""
    db = DummySession()
    service = svc.ComplianceService()
    report = service.generate_report(db, svc.ComplianceFramework.HIPAA, START, END)

    fetched = service.get_report(report_id=report.id)
    assert fetched is not None
    assert fetched.id == report.id


# ---------------------------------------------------------------------------
# export_json
# ---------------------------------------------------------------------------


def test_export_json_valid_json():
    """export_json should produce parseable JSON."""
    import json

    db = DummySession()
    service = svc.ComplianceService()
    report = service.generate_report(db, svc.ComplianceFramework.HIPAA, START, END)

    raw = service.export_json(report)
    data = json.loads(raw)

    assert data["framework"] == svc.ComplianceFramework.HIPAA.value
    assert "controls" in data
    assert isinstance(data["controls"], list)


def test_export_json_contains_all_controls():
    """JSON export should include one entry per control."""
    import json

    db = DummySession()
    service = svc.ComplianceService()
    report = service.generate_report(db, svc.ComplianceFramework.FEDRAMP_MODERATE, START, END)

    data = json.loads(service.export_json(report))
    assert len(data["controls"]) == 6


# ---------------------------------------------------------------------------
# export_csv
# ---------------------------------------------------------------------------


def test_export_csv_has_header_and_rows():
    """CSV export should have a header row plus one row per control."""
    db = DummySession()
    service = svc.ComplianceService()
    report = service.generate_report(db, svc.ComplianceFramework.SOC2_TYPE2, START, END)

    csv_text = service.export_csv(report)
    lines = [line for line in csv_text.splitlines() if line.strip()]

    # Header + 4 control rows
    assert len(lines) == 5
    assert "control_id" in lines[0]
    assert "status" in lines[0]


def test_export_csv_contains_framework_value():
    """Each CSV data row should contain the framework value."""
    db = DummySession()
    service = svc.ComplianceService()
    report = service.generate_report(db, svc.ComplianceFramework.HIPAA, START, END)

    csv_text = service.export_csv(report)
    assert svc.ComplianceFramework.HIPAA.value in csv_text


# ---------------------------------------------------------------------------
# list_reports / get_report
# ---------------------------------------------------------------------------


def test_list_reports_returns_all_stored(monkeypatch):
    """list_reports should return all previously generated reports."""
    # Clear in-memory store to isolate this test
    monkeypatch.setattr(svc.ComplianceService, "_reports", {})

    db = DummySession()
    service = svc.ComplianceService()

    r1 = service.generate_report(db, svc.ComplianceFramework.HIPAA, START, END)
    r2 = service.generate_report(db, svc.ComplianceFramework.SOC2_TYPE2, START, END)

    reports = service.list_reports()
    ids = [r.id for r in reports]

    assert r1.id in ids
    assert r2.id in ids


def test_get_report_returns_none_for_unknown_id():
    """get_report should return None for a non-existent ID."""
    service = svc.ComplianceService()
    result = service.get_report(report_id="does-not-exist")
    assert result is None


def test_get_report_with_no_report_id():
    """get_report with empty string should return None."""
    service = svc.ComplianceService()
    result = service.get_report(report_id="")
    assert result is None


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


def test_get_compliance_service_returns_singleton(monkeypatch):
    """get_compliance_service should return the same instance on repeated calls."""
    monkeypatch.setattr(svc, "_compliance_service", None)

    s1 = svc.get_compliance_service()
    s2 = svc.get_compliance_service()

    assert s1 is s2
    assert isinstance(s1, svc.ComplianceService)


def test_get_compliance_service_reuses_existing(monkeypatch):
    """get_compliance_service should not create a new instance if one exists."""
    existing = svc.ComplianceService()
    monkeypatch.setattr(svc, "_compliance_service", existing)

    result = svc.get_compliance_service()
    assert result is existing


# ---------------------------------------------------------------------------
# ControlStatus with many-admin finding
# ---------------------------------------------------------------------------


def test_generate_report_flags_high_admin_count():
    """Report should include a finding when admin user count exceeds threshold."""
    users = [_make_user(f"admin{i}@x.com", is_admin=True) for i in range(7)]
    db = DummySession(users=users)
    service = svc.ComplianceService()
    report = service.generate_report(db, svc.ComplianceFramework.FEDRAMP_MODERATE, START, END)

    ac2 = next(c for c in report.controls if c.control_id == "AC-2")
    assert any("admin" in f.lower() for f in ac2.findings)
