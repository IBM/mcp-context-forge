# -*- coding: utf-8 -*-
"""Unit tests for runtime router endpoints."""

# Standard
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.routers.runtime_router import (
    _raise_runtime_http_error,
    approve_runtime_request,
    create_guardrail_profile,
    delete_guardrail_profile,
    delete_runtime,
    get_guardrail_profile,
    get_guardrail_profile_compatibility,
    deploy_runtime,
    get_runtime_approval,
    get_runtime,
    list_guardrails,
    list_runtime_approvals,
    list_runtime_backends,
    list_runtimes,
    reject_runtime_request,
    runtime_logs,
    start_runtime,
    stop_runtime,
    update_guardrail_profile,
)
from mcpgateway.runtime_schemas import (
    RuntimeApprovalDecisionRequest,
    RuntimeApprovalRead,
    RuntimeDeployRequest,
    RuntimeDeployResponse,
    RuntimeGuardrailCompatibilityResponse,
    RuntimeGuardrailProfileCreate,
    RuntimeGuardrailProfileRead,
    RuntimeGuardrailProfileUpdate,
    RuntimeListResponse,
    RuntimeLogsResponse,
    RuntimeRead,
    RuntimeSource,
)
from mcpgateway.runtimes.base import RuntimeBackendError

# Test utilities
from tests.utils.rbac_mocks import patch_rbac_decorators, restore_rbac_decorators


@pytest.fixture(autouse=True)
def setup_rbac_mocks():
    originals = patch_rbac_decorators()
    yield
    restore_rbac_decorators(originals)


@pytest.fixture
def mock_db():
    return MagicMock(spec=Session)


@pytest.fixture
def mock_user(mock_db):
    return {"email": "admin@example.com", "is_admin": True, "permissions": ["*"], "db": mock_db, "auth_method": "jwt"}


def _runtime_read() -> RuntimeRead:
    now = datetime.now(timezone.utc)
    return RuntimeRead(
        id="runtime-1",
        name="Runtime One",
        backend="docker",
        source_type="docker",
        status="running",
        approval_status="not_required",
        runtime_ref="container-1",
        endpoint_url="http://127.0.0.1:8080",
        image="docker.io/acme/runtime:1",
        gateway_id=None,
        catalog_server_id=None,
        guardrails_profile="standard",
        guardrails_warnings=[],
        resource_limits={},
        environment={},
        backend_response={},
        error_message=None,
        created_by="admin@example.com",
        approved_by=None,
        created_at=now,
        updated_at=now,
    )


def _profile_read(name: str = "standard") -> RuntimeGuardrailProfileRead:
    now = datetime.now(timezone.utc)
    return RuntimeGuardrailProfileRead(
        id=f"profile-{name}",
        name=name,
        description=f"{name} profile",
        recommended_backends=["docker"],
        config={},
        built_in=True,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_list_runtime_backends(mock_user):
    with patch("mcpgateway.routers.runtime_router.runtime_service.list_backend_capabilities", return_value=[]):
        response = await list_runtime_backends(_user=mock_user)
        assert response.backends == []


@pytest.mark.asyncio
async def test_deploy_runtime_success(mock_db, mock_user):
    payload = RuntimeDeployRequest(name="runtime", backend="docker", source=RuntimeSource(type="docker", image="docker.io/acme/runtime:1"))
    runtime = _runtime_read()

    with patch("mcpgateway.routers.runtime_router.runtime_service.deploy", AsyncMock(return_value=runtime)):
        response = await deploy_runtime(payload=payload, db=mock_db, user=mock_user)
        assert isinstance(response, RuntimeDeployResponse)
        assert response.runtime.id == "runtime-1"
        assert response.message in {"Deployment submitted", "Deployment started successfully"}


@pytest.mark.asyncio
async def test_deploy_runtime_error_maps_to_http(mock_db, mock_user):
    payload = RuntimeDeployRequest(name="runtime", backend="docker", source=RuntimeSource(type="docker", image="docker.io/acme/runtime:1"))
    with patch("mcpgateway.routers.runtime_router.runtime_service.deploy", AsyncMock(side_effect=RuntimeBackendError("backend disabled"))):
        with pytest.raises(HTTPException) as exc_info:
            await deploy_runtime(payload=payload, db=mock_db, user=mock_user)
        assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_list_runtimes(mock_db, mock_user):
    runtime = _runtime_read()
    with patch("mcpgateway.routers.runtime_router.runtime_service.list_runtimes", AsyncMock(return_value=([runtime], 1))):
        response = await list_runtimes(db=mock_db, _user=mock_user)
        assert isinstance(response, RuntimeListResponse)
        assert response.total == 1
        assert response.runtimes[0].id == "runtime-1"


@pytest.mark.asyncio
async def test_get_runtime_refresh_status(mock_db, mock_user):
    runtime = _runtime_read()
    with patch("mcpgateway.routers.runtime_router.runtime_service.refresh_runtime_status", AsyncMock(return_value=runtime)):
        response = await get_runtime(runtime_id="runtime-1", refresh_status=True, db=mock_db, _user=mock_user)
        assert response.id == "runtime-1"


@pytest.mark.asyncio
async def test_runtime_logs(mock_db, mock_user):
    runtime = _runtime_read()
    with patch("mcpgateway.routers.runtime_router.runtime_service.get_runtime", AsyncMock(return_value=runtime)), patch(
        "mcpgateway.routers.runtime_router.runtime_service.logs", AsyncMock(return_value=["line1", "line2"])
    ):
        response = await runtime_logs(runtime_id="runtime-1", tail=100, db=mock_db, _user=mock_user)
        assert isinstance(response, RuntimeLogsResponse)
        assert response.logs == ["line1", "line2"]


@pytest.mark.asyncio
async def test_get_runtime_approval(mock_db, mock_user):
    now = datetime.now(timezone.utc)
    approval = RuntimeApprovalRead(
        id="approval-1",
        runtime_deployment_id="runtime-1",
        status="pending",
        requested_by="developer@example.com",
        reviewed_by=None,
        requested_reason=None,
        decision_reason=None,
        approvers=["security@example.com"],
        rule_snapshot={"source_type": "github"},
        expires_at=None,
        created_at=now,
        reviewed_at=None,
    )
    with patch("mcpgateway.routers.runtime_router.runtime_service.get_approval", AsyncMock(return_value=approval)):
        response = await get_runtime_approval(approval_id="approval-1", db=mock_db, _user=mock_user)
        assert response.id == "approval-1"


def test_raise_runtime_http_error_maps_statuses():
    with pytest.raises(HTTPException) as not_found:
        _raise_runtime_http_error(RuntimeBackendError("runtime not found"))
    assert not_found.value.status_code == 404

    with pytest.raises(HTTPException) as disabled:
        _raise_runtime_http_error(RuntimeBackendError("backend disabled"))
    assert disabled.value.status_code == 403

    with pytest.raises(HTTPException) as bad_request:
        _raise_runtime_http_error(RuntimeBackendError("invalid payload"))
    assert bad_request.value.status_code == 400


@pytest.mark.asyncio
async def test_list_guardrails(mock_db, mock_user):
    profile = _profile_read()
    with patch("mcpgateway.routers.runtime_router.runtime_service.list_guardrail_profiles", AsyncMock(return_value=[profile])):
        response = await list_guardrails(db=mock_db, _user=mock_user)
    assert len(response) == 1
    assert response[0].name == "standard"


@pytest.mark.asyncio
async def test_get_guardrail_profile_success_and_error(mock_db, mock_user):
    profile = _profile_read("restricted")
    with patch("mcpgateway.routers.runtime_router.runtime_service.get_guardrail_profile", AsyncMock(return_value=profile)):
        response = await get_guardrail_profile(name="restricted", db=mock_db, _user=mock_user)
    assert response.name == "restricted"

    with patch(
        "mcpgateway.routers.runtime_router.runtime_service.get_guardrail_profile",
        AsyncMock(side_effect=RuntimeBackendError("profile not found")),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await get_guardrail_profile(name="missing", db=mock_db, _user=mock_user)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_guardrail_profile_compatibility_success_and_error(mock_db, mock_user):
    compatibility = RuntimeGuardrailCompatibilityResponse(profile="standard", backend="docker", compatible=True, warnings=[])
    with patch("mcpgateway.routers.runtime_router.runtime_service.guardrail_compatibility", AsyncMock(return_value=compatibility)):
        response = await get_guardrail_profile_compatibility(name="standard", backend="docker", db=mock_db, _user=mock_user)
    assert response.compatible is True

    with patch(
        "mcpgateway.routers.runtime_router.runtime_service.guardrail_compatibility",
        AsyncMock(side_effect=RuntimeBackendError("backend disabled")),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await get_guardrail_profile_compatibility(name="standard", backend="docker", db=mock_db, _user=mock_user)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_create_update_delete_guardrail_profile_paths(mock_db, mock_user):
    created_profile = _profile_read("custom")
    create_payload = RuntimeGuardrailProfileCreate(name="custom", description="custom profile")
    update_payload = RuntimeGuardrailProfileUpdate(description="new desc")
    with patch("mcpgateway.routers.runtime_router.runtime_service.create_guardrail_profile", AsyncMock(return_value=created_profile)):
        created = await create_guardrail_profile(payload=create_payload, db=mock_db, user=mock_user)
    assert created.name == "custom"

    with patch("mcpgateway.routers.runtime_router.runtime_service.update_guardrail_profile", AsyncMock(return_value=created_profile)):
        updated = await update_guardrail_profile(name="custom", payload=update_payload, db=mock_db, _user=mock_user)
    assert updated.name == "custom"

    with patch("mcpgateway.routers.runtime_router.runtime_service.delete_guardrail_profile", AsyncMock(return_value=None)):
        deleted = await delete_guardrail_profile(name="custom", db=mock_db, _user=mock_user)
    assert deleted is None

    with patch(
        "mcpgateway.routers.runtime_router.runtime_service.create_guardrail_profile",
        AsyncMock(side_effect=RuntimeBackendError("already exists")),
    ):
        with pytest.raises(HTTPException):
            await create_guardrail_profile(payload=create_payload, db=mock_db, user=mock_user)

    with patch(
        "mcpgateway.routers.runtime_router.runtime_service.update_guardrail_profile",
        AsyncMock(side_effect=RuntimeBackendError("profile not found")),
    ):
        with pytest.raises(HTTPException):
            await update_guardrail_profile(name="missing", payload=update_payload, db=mock_db, _user=mock_user)

    with patch(
        "mcpgateway.routers.runtime_router.runtime_service.delete_guardrail_profile",
        AsyncMock(side_effect=RuntimeBackendError("profile not found")),
    ):
        with pytest.raises(HTTPException):
            await delete_guardrail_profile(name="missing", db=mock_db, _user=mock_user)


@pytest.mark.asyncio
async def test_deploy_runtime_message_variants(mock_db, mock_user):
    payload = RuntimeDeployRequest(name="runtime", backend="docker", source=RuntimeSource(type="docker", image="docker.io/acme/runtime:1"))

    pending = _runtime_read()
    pending.approval_status = "pending"
    with patch("mcpgateway.routers.runtime_router.runtime_service.deploy", AsyncMock(return_value=pending)):
        response = await deploy_runtime(payload=payload, db=mock_db, user=mock_user)
    assert response.message == "Deployment pending approval"

    failed = _runtime_read()
    failed.status = "error"
    with patch("mcpgateway.routers.runtime_router.runtime_service.deploy", AsyncMock(return_value=failed)):
        response = await deploy_runtime(payload=payload, db=mock_db, user=mock_user)
    assert response.message == "Deployment failed"


@pytest.mark.asyncio
async def test_list_runtime_approvals(mock_db, mock_user):
    now = datetime.now(timezone.utc)
    approval = RuntimeApprovalRead(
        id="approval-2",
        runtime_deployment_id="runtime-2",
        status="pending",
        requested_by="developer@example.com",
        reviewed_by=None,
        requested_reason="needs review",
        decision_reason=None,
        approvers=["security@example.com"],
        rule_snapshot={"source_type": "github"},
        expires_at=None,
        created_at=now,
        reviewed_at=None,
    )
    with patch("mcpgateway.routers.runtime_router.runtime_service.list_approvals", AsyncMock(return_value=([approval], 1))):
        response = await list_runtime_approvals(db=mock_db, _user=mock_user)
    assert response.total == 1
    assert response.approvals[0].id == "approval-2"


@pytest.mark.asyncio
async def test_get_runtime_error_path(mock_db, mock_user):
    with patch("mcpgateway.routers.runtime_router.runtime_service.get_runtime", AsyncMock(side_effect=RuntimeBackendError("runtime not found"))):
        with pytest.raises(HTTPException) as exc_info:
            await get_runtime(runtime_id="missing", refresh_status=False, db=mock_db, _user=mock_user)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_approval_actions_success_and_error(mock_db, mock_user):
    runtime = _runtime_read()
    payload = RuntimeApprovalDecisionRequest(reason="looks good")

    with patch("mcpgateway.routers.runtime_router.runtime_service.approve", AsyncMock(return_value=runtime)):
        approved = await approve_runtime_request(approval_id="approval-1", payload=payload, db=mock_db, user=mock_user)
    assert approved.message.startswith("Approved deployment")

    with patch("mcpgateway.routers.runtime_router.runtime_service.reject", AsyncMock(return_value=runtime)):
        rejected = await reject_runtime_request(approval_id="approval-1", payload=payload, db=mock_db, user=mock_user)
    assert rejected.message.startswith("Rejected deployment")

    with patch(
        "mcpgateway.routers.runtime_router.runtime_service.approve",
        AsyncMock(side_effect=RuntimeBackendError("approval not found")),
    ):
        with pytest.raises(HTTPException):
            await approve_runtime_request(approval_id="missing", payload=payload, db=mock_db, user=mock_user)

    with patch(
        "mcpgateway.routers.runtime_router.runtime_service.reject",
        AsyncMock(side_effect=RuntimeBackendError("approval not found")),
    ):
        with pytest.raises(HTTPException):
            await reject_runtime_request(approval_id="missing", payload=payload, db=mock_db, user=mock_user)


@pytest.mark.asyncio
async def test_get_runtime_approval_error_path(mock_db, mock_user):
    with patch("mcpgateway.routers.runtime_router.runtime_service.get_approval", AsyncMock(side_effect=RuntimeBackendError("approval not found"))):
        with pytest.raises(HTTPException) as exc_info:
            await get_runtime_approval(approval_id="missing", db=mock_db, _user=mock_user)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_runtime_actions_and_logs_error_paths(mock_db, mock_user):
    runtime = _runtime_read()
    with patch("mcpgateway.routers.runtime_router.runtime_service.start_runtime", AsyncMock(return_value=runtime)):
        start_response = await start_runtime(runtime_id="runtime-1", db=mock_db, _user=mock_user)
    assert start_response.message.endswith("started")

    with patch("mcpgateway.routers.runtime_router.runtime_service.stop_runtime", AsyncMock(return_value=runtime)):
        stop_response = await stop_runtime(runtime_id="runtime-1", db=mock_db, _user=mock_user)
    assert stop_response.message.endswith("stopped")

    with patch("mcpgateway.routers.runtime_router.runtime_service.delete_runtime", AsyncMock(return_value=runtime)):
        delete_response = await delete_runtime(runtime_id="runtime-1", db=mock_db, _user=mock_user)
    assert delete_response.message.endswith("deleted")

    with patch("mcpgateway.routers.runtime_router.runtime_service.logs", AsyncMock(side_effect=RuntimeBackendError("runtime not found"))), patch(
        "mcpgateway.routers.runtime_router.runtime_service.get_runtime", AsyncMock(return_value=runtime)
    ):
        with pytest.raises(HTTPException) as exc_info:
            await runtime_logs(runtime_id="missing", tail=100, db=mock_db, _user=mock_user)
    assert exc_info.value.status_code == 404

    with patch("mcpgateway.routers.runtime_router.runtime_service.start_runtime", AsyncMock(side_effect=RuntimeBackendError("runtime not found"))):
        with pytest.raises(HTTPException):
            await start_runtime(runtime_id="missing", db=mock_db, _user=mock_user)

    with patch("mcpgateway.routers.runtime_router.runtime_service.stop_runtime", AsyncMock(side_effect=RuntimeBackendError("runtime not found"))):
        with pytest.raises(HTTPException):
            await stop_runtime(runtime_id="missing", db=mock_db, _user=mock_user)

    with patch("mcpgateway.routers.runtime_router.runtime_service.delete_runtime", AsyncMock(side_effect=RuntimeBackendError("runtime not found"))):
        with pytest.raises(HTTPException):
            await delete_runtime(runtime_id="missing", db=mock_db, _user=mock_user)
