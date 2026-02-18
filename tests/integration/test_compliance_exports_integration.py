# -*- coding: utf-8 -*-
"""Integration tests for compliance evidence export datasets."""

# Standard
from datetime import datetime, timedelta, timezone
import uuid

# Third-Party
from fastapi.testclient import TestClient
import pytest

# First-Party
import mcpgateway.plugins.framework as plugin_framework
import mcpgateway.db as db_mod
from mcpgateway.middleware.rbac import PermissionService, get_current_user_with_permissions
from mcpgateway.routers.compliance import router as compliance_router


@pytest.fixture
def compliance_client(app, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Test client with compliance router available and RBAC permission checks bypassed."""
    if not any(getattr(route, "path", "").startswith("/api/compliance") for route in app.routes):
        app.include_router(compliance_router)

    async def _allow_permission(self, **_kwargs):  # type: ignore[no-self-use]
        return True

    async def _mock_user_with_permissions():
        return {
            "email": "admin@example.com",
            "full_name": "Integration Admin",
            "is_admin": True,
            "ip_address": "127.0.0.1",
            "user_agent": "pytest",
            "db": None,
        }

    monkeypatch.setattr(PermissionService, "check_permission", _allow_permission)
    monkeypatch.setattr(plugin_framework, "get_plugin_manager", lambda: None)
    app.dependency_overrides[get_current_user_with_permissions] = _mock_user_with_permissions

    client = TestClient(app)
    try:
        yield client
    finally:
        app.dependency_overrides.pop(get_current_user_with_permissions, None)


@pytest.fixture
def seeded_compliance_events(app) -> dict[str, str]:
    """Seed one audit, permission, and security event row for a unique user."""
    db = db_mod.SessionLocal()
    now = datetime.now(timezone.utc)
    user_suffix = uuid.uuid4().hex[:10]
    user_email = f"compliance-{user_suffix}@example.com"
    user_id = f"user-{user_suffix}"
    correlation_id = f"corr-{user_suffix}"

    audit_row = db_mod.AuditTrail(
        timestamp=now - timedelta(minutes=2),
        correlation_id=correlation_id,
        action="update",
        resource_type="tool",
        resource_id="tool-123",
        resource_name="Compliance Tool",
        user_id=user_id,
        user_email=user_email,
        team_id="team-compliance",
        client_ip="127.0.0.1",
        request_path="/tools/tool-123",
        request_method="PUT",
        data_classification="confidential",
        requires_review=False,
        success=True,
    )
    permission_row = db_mod.PermissionAuditLog(
        timestamp=now - timedelta(minutes=1),
        user_email=user_email,
        permission="tools.update",
        resource_type="tool",
        resource_id="tool-123",
        team_id="team-compliance",
        granted=False,
        ip_address="127.0.0.1",
        user_agent="pytest",
    )
    security_row = db_mod.SecurityEvent(
        timestamp=now,
        detected_at=now,
        correlation_id=correlation_id,
        event_type="suspicious_activity",
        severity="CRITICAL",
        category="authorization",
        user_id=user_id,
        user_email=user_email,
        client_ip="127.0.0.1",
        user_agent="pytest",
        description="Suspicious permission escalation detected.",
        threat_score=0.95,
        threat_indicators={"signal": "escalation"},
        failed_attempts_count=2,
        resolved=False,
    )

    try:
        db.add_all([audit_row, permission_row, security_row])
        db.commit()
    finally:
        db.close()

    return {"user_email": user_email}


def test_export_audit_logs_returns_seeded_rows(compliance_client: TestClient, seeded_compliance_events: dict[str, str]):
    """audit_logs dataset should return the seeded audit row with filters applied."""
    response = compliance_client.get(
        "/api/compliance/evidence/export",
        params={
            "dataset": "audit_logs",
            "format": "json",
            "user_identifier": seeded_compliance_events["user_email"],
            "action": "update",
        },
    )

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["action"] == "update"
    assert rows[0]["user_email"] == seeded_compliance_events["user_email"]


def test_export_access_control_returns_seeded_rows(compliance_client: TestClient, seeded_compliance_events: dict[str, str]):
    """access_control dataset should return the seeded denied permission row."""
    response = compliance_client.get(
        "/api/compliance/evidence/export",
        params={
            "dataset": "access_control",
            "format": "json",
            "user_identifier": seeded_compliance_events["user_email"],
            "granted": "false",
        },
    )

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["permission"] == "tools.update"
    assert rows[0]["granted"] is False


def test_export_security_events_returns_seeded_rows(compliance_client: TestClient, seeded_compliance_events: dict[str, str]):
    """security_events dataset should return the seeded critical unresolved event."""
    response = compliance_client.get(
        "/api/compliance/evidence/export",
        params={
            "dataset": "security_events",
            "format": "json",
            "user_identifier": seeded_compliance_events["user_email"],
            "severity": "critical",
            "success": "false",
        },
    )

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["severity"] == "CRITICAL"
    assert rows[0]["resolved"] is False


def test_export_user_activity_merges_seeded_sources(compliance_client: TestClient, seeded_compliance_events: dict[str, str]):
    """user_activity dataset should merge audit, permission, and security events for a user."""
    response = compliance_client.get(
        "/api/compliance/evidence/export",
        params={
            "dataset": "user_activity",
            "format": "json",
            "user_identifier": seeded_compliance_events["user_email"],
            "limit": "50",
        },
    )

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 3
    assert {row["source"] for row in rows} == {"audit", "permission", "security"}
