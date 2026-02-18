# -*- coding: utf-8 -*-
"""Tests for compliance router."""

# Standard
from datetime import datetime, timezone

# Third-Party
from fastapi import HTTPException
import pytest

# First-Party
from mcpgateway.middleware import rbac as rbac_module
import mcpgateway.plugins.framework as plugin_framework
from mcpgateway.routers import compliance
from mcpgateway.services.compliance_report_service import (
    ComplianceMetrics,
    ComplianceReportService,
)


@pytest.fixture(autouse=True)
def allow_permissions(monkeypatch: pytest.MonkeyPatch):
    async def _ok(self, **_kwargs):  # type: ignore[no-self-use]
        return True

    monkeypatch.setattr(rbac_module.PermissionService, "check_permission", _ok)
    monkeypatch.setattr(plugin_framework, "get_plugin_manager", lambda: None)


def test_rows_to_csv_handles_nested_and_datetime():
    rows = [
        {
            "timestamp": datetime(2025, 1, 1, tzinfo=timezone.utc),
            "name": "entry",
            "details": {"a": 1},
        }
    ]
    content = compliance._rows_to_csv(rows)
    assert "timestamp" in content
    assert "entry" in content
    assert "a" in content


@pytest.mark.asyncio
async def test_get_frameworks_returns_supported():
    response = await compliance.get_frameworks(_user={"email": "admin@example.com"})
    assert "soc2" in response
    assert "iso27001" in response


@pytest.mark.asyncio
async def test_get_compliance_dashboard_success(monkeypatch: pytest.MonkeyPatch):
    class _Service:
        def build_dashboard(self, **_kwargs):
            return {
                "generated_at": datetime.now(timezone.utc),
                "period": {"start_time": datetime.now(timezone.utc), "end_time": datetime.now(timezone.utc)},
                "overall_score": 90.0,
                "overall_status": "compliant",
                "overview": {"audit_events": 10},
                "frameworks": [],
                "trend": [],
                "policy_violations": [],
            }

    monkeypatch.setattr(compliance, "get_compliance_report_service", lambda: _Service())

    response = await compliance.get_compliance_dashboard(
        framework=["soc2"],
        start_time=None,
        end_time=None,
        trend_days=14,
        _user={"email": "admin@example.com"},
        db=None,
    )
    assert response["overall_score"] == 90.0
    assert response["overall_status"] == "compliant"


@pytest.mark.asyncio
async def test_get_compliance_dashboard_validation_error(monkeypatch: pytest.MonkeyPatch):
    class _Service:
        def build_dashboard(self, **_kwargs):
            raise ValueError("bad range")

    monkeypatch.setattr(compliance, "get_compliance_report_service", lambda: _Service())

    with pytest.raises(HTTPException) as exc_info:
        await compliance.get_compliance_dashboard(
            framework=None,
            start_time=datetime(2025, 1, 2, tzinfo=timezone.utc),
            end_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
            trend_days=14,
            _user={"email": "admin@example.com"},
            db=None,
        )
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_get_framework_report_success(monkeypatch: pytest.MonkeyPatch):
    class _Service:
        def build_framework_report(self, **_kwargs):
            return {"framework": "soc2", "summary": {"score": 82.5}}

    monkeypatch.setattr(compliance, "get_compliance_report_service", lambda: _Service())

    response = await compliance.get_framework_report(
        framework="soc2",
        start_time=None,
        end_time=None,
        _user={"email": "admin@example.com"},
        db=None,
    )
    assert response["framework"] == "soc2"


@pytest.mark.asyncio
async def test_get_user_activity_timeline_success(monkeypatch: pytest.MonkeyPatch):
    class _Service:
        def build_user_activity_timeline(self, **_kwargs):
            return {"user_identifier": "alice@example.com", "events": [{"action": "CREATE"}], "sessions": [], "total_events": 1}

    monkeypatch.setattr(compliance, "get_compliance_report_service", lambda: _Service())

    response = await compliance.get_user_activity_timeline(
        user_identifier="alice@example.com",
        start_time=None,
        end_time=None,
        limit=100,
        _user={"email": "admin@example.com"},
        db=None,
    )
    assert response["total_events"] == 1


@pytest.mark.asyncio
async def test_export_evidence_json(monkeypatch: pytest.MonkeyPatch):
    class _Service:
        def build_export_rows(self, **_kwargs):
            return [{"framework": "soc2", "score": 88.0}]

    monkeypatch.setattr(compliance, "get_compliance_report_service", lambda: _Service())

    response = await compliance.export_evidence(
        dataset="compliance_summary",
        format="json",
        framework=["soc2"],
        start_time=None,
        end_time=None,
        limit=100,
        user_identifier=None,
        action=None,
        resource_type=None,
        success=None,
        severity=None,
        granted=None,
        _user={"email": "admin@example.com"},
        db=None,
    )
    assert isinstance(response, list)
    assert response[0]["framework"] == "soc2"


@pytest.mark.asyncio
async def test_export_evidence_csv(monkeypatch: pytest.MonkeyPatch):
    class _Service:
        def build_export_rows(self, **_kwargs):
            return [{"timestamp": datetime(2025, 1, 1, tzinfo=timezone.utc), "action": "CREATE"}]

    monkeypatch.setattr(compliance, "get_compliance_report_service", lambda: _Service())

    response = await compliance.export_evidence(
        dataset="audit_logs",
        format="csv",
        framework=None,
        start_time=None,
        end_time=None,
        limit=100,
        user_identifier=None,
        action=None,
        resource_type=None,
        success=None,
        severity=None,
        granted=None,
        _user={"email": "admin@example.com"},
        db=None,
    )
    assert response.media_type == "text/csv"
    assert "action" in response.body.decode("utf-8")


@pytest.mark.asyncio
async def test_export_evidence_invalid_dataset():
    with pytest.raises(HTTPException) as exc_info:
        await compliance.export_evidence(
            dataset="invalid",
            format="json",
            framework=None,
            start_time=None,
            end_time=None,
            limit=100,
            user_identifier=None,
            action=None,
            resource_type=None,
            success=None,
            severity=None,
            granted=None,
            _user={"email": "admin@example.com"},
            db=None,
        )
    assert exc_info.value.status_code == 400


def test_framework_summary_includes_explainability_fields():
    service = ComplianceReportService()
    summary = service._build_framework_summary(  # pylint: disable=protected-access
        name="soc2",
        metrics=ComplianceMetrics(),
    )

    assert "score_explanation" in summary
    assert "control_details" in summary
    assert "missing_evidence" in summary
    assert "confidence" in summary
    assert summary["confidence"] == "low"
    assert len(summary["control_details"]) > 0
    assert any(item["missing_evidence"] for item in summary["control_details"])
    assert summary["score"] < 70
    assert summary["status"] == "at_risk"


def test_export_dataset_status_includes_estimates():
    datasets = ComplianceReportService._build_export_dataset_status(  # pylint: disable=protected-access
        metrics=ComplianceMetrics(audit_total=11, permission_total=5, security_total=3),
        framework_count=4,
    )
    by_name = {item["dataset"]: item for item in datasets}

    assert by_name["audit_logs"]["estimated_rows"] == 11
    assert by_name["access_control"]["estimated_rows"] == 5
    assert by_name["security_events"]["estimated_rows"] == 3
    assert by_name["compliance_summary"]["estimated_rows"] == 4
