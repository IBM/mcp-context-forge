# -*- coding: utf-8 -*-
"""Tests for compliance_router endpoints."""

# Standard
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

# Third-Party
import pytest

# Local
from tests.utils.rbac_mocks import patch_rbac_decorators, restore_rbac_decorators

_originals = patch_rbac_decorators()
# First-Party
from mcpgateway.routers import compliance_router as router_mod  # noqa: E402
from mcpgateway.services.compliance_service import ComplianceFramework, ComplianceReport, ControlEvidence, ControlStatus  # noqa: E402

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
# get_db
# ---------------------------------------------------------------------------


def test_get_db_yields_session_and_commits(monkeypatch):
    """get_db should yield a session, commit, and close on success."""
    db = MagicMock()
    monkeypatch.setattr(router_mod, "SessionLocal", lambda: db)

    gen = router_mod.get_db()
    yielded = next(gen)
    assert yielded is db

    with pytest.raises(StopIteration):
        gen.send(None)

    db.commit.assert_called_once()
    db.close.assert_called_once()


def test_get_db_rolls_back_on_exception(monkeypatch):
    """get_db should rollback and re-raise on exception."""
    db = MagicMock()
    monkeypatch.setattr(router_mod, "SessionLocal", lambda: db)

    gen = router_mod.get_db()
    next(gen)

    with pytest.raises(ValueError):
        gen.throw(ValueError("boom"))

    db.rollback.assert_called_once()
    db.close.assert_called_once()


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
    """Should raise 400 when period_start >= period_end."""
    from fastapi import HTTPException

    body = router_mod.GenerateReportRequest(framework=ComplianceFramework.HIPAA, period_start=END, period_end=START)

    with pytest.raises(HTTPException) as exc_info:
        await router_mod.generate_report(body, user=_mock_user(), db=MagicMock())

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_generate_report_equal_dates_raises():
    """Should raise 400 when period_start equals period_end."""
    from fastapi import HTTPException

    body = router_mod.GenerateReportRequest(framework=ComplianceFramework.SOC2_TYPE2, period_start=START, period_end=START)

    with pytest.raises(HTTPException) as exc_info:
        await router_mod.generate_report(body, user=_mock_user(), db=MagicMock())

    assert exc_info.value.status_code == 400


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
    """Should return JSON content when format=json."""
    report = _make_report("rpt-e1")
    mock_service = MagicMock()
    mock_service.get_report.return_value = report
    mock_service.export_json.return_value = '{"id": "rpt-e1"}'
    monkeypatch.setattr(router_mod, "get_compliance_service", lambda: mock_service)

    result = await router_mod.export_report("rpt-e1", user=_mock_user(), db=MagicMock(), format="json")

    assert result["content_type"] == "application/json"
    assert "rpt-e1" in result["data"]


@pytest.mark.asyncio
async def test_export_report_csv(monkeypatch):
    """Should return CSV content when format=csv."""
    report = _make_report("rpt-e2")
    mock_service = MagicMock()
    mock_service.get_report.return_value = report
    mock_service.export_csv.return_value = "report_id,framework\nrpt-e2,fedramp_moderate\n"
    monkeypatch.setattr(router_mod, "get_compliance_service", lambda: mock_service)

    result = await router_mod.export_report("rpt-e2", user=_mock_user(), db=MagicMock(), format="csv")

    assert result["content_type"] == "text/csv"
    assert "rpt-e2" in result["data"]


@pytest.mark.asyncio
async def test_export_report_unsupported_format(monkeypatch):
    """Should raise 400 for an unsupported export format."""
    from fastapi import HTTPException

    report = _make_report("rpt-e3")
    mock_service = MagicMock()
    mock_service.get_report.return_value = report
    monkeypatch.setattr(router_mod, "get_compliance_service", lambda: mock_service)

    with pytest.raises(HTTPException) as exc_info:
        await router_mod.export_report("rpt-e3", user=_mock_user(), db=MagicMock(), format="xml")

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_export_report_not_found(monkeypatch):
    """Should raise 404 when exporting an unknown report."""
    from fastapi import HTTPException

    mock_service = MagicMock()
    mock_service.get_report.return_value = None
    monkeypatch.setattr(router_mod, "get_compliance_service", lambda: mock_service)

    with pytest.raises(HTTPException) as exc_info:
        await router_mod.export_report("ghost", user=_mock_user(), db=MagicMock(), format="json")

    assert exc_info.value.status_code == 404
