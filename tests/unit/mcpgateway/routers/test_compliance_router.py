# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_compliance_router.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for compliance_router endpoints.
"""

# Standard
from datetime import datetime, timezone
import sys
from unittest.mock import MagicMock

# Third-Party
import pytest

# Local
from tests.utils.rbac_mocks import patch_rbac_decorators, restore_rbac_decorators

_originals = patch_rbac_decorators()
# First-Party
from mcpgateway.routers import compliance_router as router_mod  # noqa: E402  # pylint: disable=wrong-import-position
from mcpgateway.services.compliance_service import ComplianceFramework, ComplianceReport, ControlEvidence, ControlStatus  # noqa: E402  # pylint: disable=wrong-import-position

restore_rbac_decorators(_originals)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

START = datetime(2025, 1, 1, tzinfo=timezone.utc)
END = datetime(2025, 3, 31, tzinfo=timezone.utc)
NOW = datetime(2025, 4, 1, tzinfo=timezone.utc)


def _make_control_evidence(control_id="AC-2", status=ControlStatus.IMPLEMENTED):
    """Create a stub ControlEvidence object."""
    return ControlEvidence(
        control_id=control_id,
        status=status,
        evidence=f"Evidence for {control_id}",
        artifacts=[],
        findings=[],
        recommendations=[],
    )


def _make_report(report_id="rpt-1", framework=ComplianceFramework.FEDRAMP_MODERATE):
    """Create a stub ComplianceReport object."""
    return ComplianceReport(
        id=report_id,
        framework=framework,
        period_start=START,
        period_end=END,
        generated_at=NOW,
        controls=[_make_control_evidence()],
        summary={"framework": framework.value, "total_controls": 1, "implemented": 1},
    )


def _mock_user():
    """Return a mock admin user context dict."""
    return {"email": "admin@example.com", "is_admin": True}


# ---------------------------------------------------------------------------
# list_frameworks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_frameworks_returns_all():
    """Should return all four supported compliance frameworks."""
    result = await router_mod.list_frameworks(user=_mock_user())

    assert len(result) == 4
    ids = [f.id for f in result]
    assert ComplianceFramework.FEDRAMP_MODERATE.value in ids
    assert ComplianceFramework.FEDRAMP_HIGH.value in ids
    assert ComplianceFramework.HIPAA.value in ids
    assert ComplianceFramework.SOC2_TYPE2.value in ids


# ---------------------------------------------------------------------------
# generate_report
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_report_success(monkeypatch):
    """Should return a ComplianceReportResponse with the report data."""
    report = _make_report()
    mock_service = MagicMock()
    mock_service.generate_report.return_value = report
    monkeypatch.setattr(router_mod, "get_compliance_service", lambda: mock_service)

    body = router_mod.GenerateReportRequest(framework=ComplianceFramework.FEDRAMP_MODERATE, period_start=START, period_end=END)
    result = await router_mod.generate_report(body, user=_mock_user(), db=MagicMock())

    assert result.id == "rpt-1"
    assert result.framework == ComplianceFramework.FEDRAMP_MODERATE.value
    mock_service.generate_report.assert_called_once()


@pytest.mark.asyncio
async def test_generate_report_invalid_period():
    """Should raise validation error when period_start >= period_end."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as exc_info:
        router_mod.GenerateReportRequest(framework=ComplianceFramework.HIPAA, period_start=END, period_end=START)

    assert "period_end must be after period_start" in str(exc_info.value)


@pytest.mark.asyncio
async def test_generate_report_equal_dates_raises():
    """Should raise validation error when period_start equals period_end."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as exc_info:
        router_mod.GenerateReportRequest(framework=ComplianceFramework.SOC2_TYPE2, period_start=START, period_end=START)

    assert "period_end must be after period_start" in str(exc_info.value)


@pytest.mark.asyncio
async def test_generate_report_naive_datetime_rejected():
    """Should reject naive (non-timezone-aware) datetimes."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as exc_info:
        router_mod.GenerateReportRequest(
            framework=ComplianceFramework.HIPAA,
            period_start=datetime(2025, 1, 1),
            period_end=datetime(2025, 3, 31),
        )
    assert "timezone-aware" in str(exc_info.value)


@pytest.mark.asyncio
async def test_generate_report_future_period_end_rejected():
    """Should reject period_end in the future."""
    from datetime import timedelta
    from pydantic import ValidationError

    future = datetime.now(timezone.utc) + timedelta(days=1)
    past = datetime.now(timezone.utc) - timedelta(days=30)

    with pytest.raises(ValidationError) as exc_info:
        router_mod.GenerateReportRequest(
            framework=ComplianceFramework.HIPAA,
            period_start=past,
            period_end=future,
        )
    assert "future" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_generate_report_period_too_long_rejected():
    """Should reject assessment period exceeding 365 days."""
    from datetime import timedelta
    from pydantic import ValidationError

    start = datetime.now(timezone.utc) - timedelta(days=400)
    end = datetime.now(timezone.utc) - timedelta(days=10)

    with pytest.raises(ValidationError) as exc_info:
        router_mod.GenerateReportRequest(
            framework=ComplianceFramework.HIPAA,
            period_start=start,
            period_end=end,
        )
    assert "365" in str(exc_info.value)


# ---------------------------------------------------------------------------
# list_reports
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_reports_empty(monkeypatch):
    """Should return an empty list when no reports have been generated."""
    mock_service = MagicMock()
    mock_service.list_reports.return_value = []
    monkeypatch.setattr(router_mod, "get_compliance_service", lambda: mock_service)

    result = await router_mod.list_reports(user=_mock_user(), db=MagicMock())
    assert result == []


@pytest.mark.asyncio
async def test_list_reports_multiple(monkeypatch):
    """Should return all stored reports."""
    reports = [_make_report("r1"), _make_report("r2", ComplianceFramework.HIPAA)]
    mock_service = MagicMock()
    mock_service.list_reports.return_value = reports
    monkeypatch.setattr(router_mod, "get_compliance_service", lambda: mock_service)

    result = await router_mod.list_reports(user=_mock_user(), db=MagicMock())
    assert len(result) == 2
    ids = [r.id for r in result]
    assert "r1" in ids
    assert "r2" in ids


# ---------------------------------------------------------------------------
# get_report
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_report_success(monkeypatch):
    """Should return the report for a known ID."""
    report = _make_report("rpt-42")
    mock_service = MagicMock()
    mock_service.get_report.return_value = report
    monkeypatch.setattr(router_mod, "get_compliance_service", lambda: mock_service)

    result = await router_mod.get_report("rpt-42", user=_mock_user(), db=MagicMock())
    assert result.id == "rpt-42"


@pytest.mark.asyncio
async def test_get_report_not_found(monkeypatch):
    """Should raise 404 when report ID is unknown."""
    from fastapi import HTTPException

    mock_service = MagicMock()
    mock_service.get_report.return_value = None
    monkeypatch.setattr(router_mod, "get_compliance_service", lambda: mock_service)

    with pytest.raises(HTTPException) as exc_info:
        await router_mod.get_report("missing-id", user=_mock_user(), db=MagicMock())

    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# export_report
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_report_json(monkeypatch):
    """Should return JSON content when export_format=json."""
    report = _make_report("rpt-e1")
    mock_service = MagicMock()
    mock_service.get_report.return_value = report
    mock_service.export_json.return_value = '{"id": "rpt-e1"}'
    monkeypatch.setattr(router_mod, "get_compliance_service", lambda: mock_service)

    result = await router_mod.export_report("rpt-e1", user=_mock_user(), db=MagicMock(), export_format="json")

    assert result.media_type == "application/json"
    assert "rpt-e1" in result.body.decode()


@pytest.mark.asyncio
async def test_export_report_csv(monkeypatch):
    """Should return CSV content when export_format=csv."""
    report = _make_report("rpt-e2")
    mock_service = MagicMock()
    mock_service.get_report.return_value = report
    mock_service.export_csv.return_value = "report_id,framework\nrpt-e2,fedramp_moderate\n"
    monkeypatch.setattr(router_mod, "get_compliance_service", lambda: mock_service)

    result = await router_mod.export_report("rpt-e2", user=_mock_user(), db=MagicMock(), export_format="csv")

    assert result.media_type == "text/csv"
    assert "rpt-e2" in result.body.decode()


@pytest.mark.asyncio
async def test_export_report_unsupported_format(monkeypatch):
    """Should raise 400 for an unsupported export format."""
    from fastapi import HTTPException

    report = _make_report("rpt-e3")
    mock_service = MagicMock()
    mock_service.get_report.return_value = report
    monkeypatch.setattr(router_mod, "get_compliance_service", lambda: mock_service)

    with pytest.raises(HTTPException) as exc_info:
        await router_mod.export_report("rpt-e3", user=_mock_user(), db=MagicMock(), export_format="xml")

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_export_report_not_found(monkeypatch):
    """Should raise 404 when exporting an unknown report."""
    from fastapi import HTTPException

    mock_service = MagicMock()
    mock_service.get_report.return_value = None
    monkeypatch.setattr(router_mod, "get_compliance_service", lambda: mock_service)

    with pytest.raises(HTTPException) as exc_info:
        await router_mod.export_report("ghost", user=_mock_user(), db=MagicMock(), export_format="json")

    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Integration / deny-path tests
# ---------------------------------------------------------------------------


def test_compliance_unauthenticated():
    """Should return 401 when no auth context is provided."""
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient
    from mcpgateway.middleware.rbac import get_current_user_with_permissions
    from mcpgateway.routers.compliance_router import router as compliance_router

    app = FastAPI()
    app.include_router(compliance_router)

    async def no_auth():
        raise HTTPException(status_code=401, detail="Not authenticated")

    app.dependency_overrides[get_current_user_with_permissions] = no_auth
    client = TestClient(app)
    response = client.get("/compliance/frameworks")
    assert response.status_code == 401


def test_compliance_non_admin_forbidden():
    """Should return 403 for non-admin authenticated user."""
    from unittest.mock import AsyncMock, patch

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from mcpgateway.middleware.rbac import get_current_user_with_permissions

    # Restore original decorator, reload router module with real decorator
    restore_rbac_decorators(_originals)
    if "mcpgateway.routers.compliance_router" in sys.modules:
        del sys.modules["mcpgateway.routers.compliance_router"]
    from mcpgateway.routers.compliance_router import router as real_compliance_router

    app = FastAPI()
    app.include_router(real_compliance_router)

    async def non_admin_user():
        return {"email": "user@example.com", "is_admin": False}

    app.dependency_overrides[get_current_user_with_permissions] = non_admin_user

    # Patch PermissionService to deny admin access
    with patch("mcpgateway.middleware.rbac.PermissionService") as mock_ps:
        instance = mock_ps.return_value
        instance.check_admin_permission = AsyncMock(return_value=False)
        client = TestClient(app)
        response = client.get("/compliance/frameworks")
        assert response.status_code == 403

    # Re-patch decorators for remaining tests
    patch_rbac_decorators()
