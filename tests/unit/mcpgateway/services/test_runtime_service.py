# -*- coding: utf-8 -*-
"""Unit tests for runtime service."""

# Standard
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

# Third-Party
import pytest

# First-Party
from mcpgateway.db import RuntimeDeployment, RuntimeDeploymentApproval, RuntimeGuardrailProfile, utc_now
from mcpgateway.runtime_schemas import RuntimeDeployRequest, RuntimeGuardrailProfileCreate, RuntimeGuardrailProfileUpdate, RuntimeSecurityGuardrails, RuntimeSource
from mcpgateway.runtimes import DockerRuntimeBackend
from mcpgateway.runtimes.base import RuntimeBackendCapabilities, RuntimeBackendDeployRequest, RuntimeBackendDeployResult, RuntimeBackendError, RuntimeBackendStatus
from mcpgateway.services.runtime_service import RuntimeService


def _runtime_settings(**overrides):
    defaults = {
        "mcpgateway_runtime_enabled": True,
        "runtime_docker_enabled": True,
        "runtime_docker_binary": "docker",
        "runtime_docker_socket": "/var/run/docker.sock",
        "runtime_docker_network": None,
        "runtime_docker_allowed_registries": [],
        "runtime_ibm_code_engine_enabled": False,
        "runtime_ibm_code_engine_binary": "ibmcloud",
        "runtime_ibm_code_engine_project": None,
        "runtime_ibm_code_engine_region": None,
        "runtime_ibm_code_engine_registry_secret": None,
        "runtime_approval_enabled": False,
        "runtime_approval_required_source_types": ["github"],
        "runtime_approval_registry_allowlist": ["docker.io/library", "docker.io/mcp"],
        "runtime_approval_required_guardrails_profiles": ["unrestricted"],
        "runtime_approvers": [],
        "runtime_approval_timeout_hours": 48,
        "httpx_admin_read_timeout": 30,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _runtime_row(**overrides) -> RuntimeDeployment:
    payload = {
        "id": str(uuid4()),
        "name": "runtime",
        "slug": "runtime",
        "backend": "docker",
        "source_type": "docker",
        "source_config": {"type": "docker", "image": "docker.io/acme/runtime:1"},
        "status": "running",
        "approval_status": "not_required",
        "resource_limits": {},
        "environment": {},
        "guardrails_profile": "standard",
        "guardrails_config": {},
        "guardrails_warnings": [],
        "backend_response": {},
        "runtime_metadata": {"register_gateway": False, "visibility": "public", "tags": []},
    }
    payload.update(overrides)
    return RuntimeDeployment(**payload)


def _guardrail_row(name: str = "custom", **overrides) -> RuntimeGuardrailProfile:
    payload = {
        "id": str(uuid4()),
        "name": name,
        "description": "custom profile",
        "recommended_backends": ["docker"],
        "config": {"network": {"egress_allowed": True, "allowed_hosts": []}, "filesystem": {"read_only_root": True}, "capabilities": {"drop_all": True, "add": []}, "resources": {}},
        "built_in": False,
        "created_by": "owner@example.com",
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    payload.update(overrides)
    return RuntimeGuardrailProfile(**payload)


@pytest.fixture
def docker_caps():
    return RuntimeBackendCapabilities(
        backend="docker",
        supports_compose=True,
        supports_github_build=True,
        supports_allowed_hosts=True,
        supports_readonly_fs=True,
        supports_custom_capabilities=True,
        supports_pids_limit=True,
    )


@pytest.mark.asyncio
async def test_deploy_creates_pending_approval(monkeypatch, test_db, docker_caps):
    monkeypatch.setattr("mcpgateway.services.runtime_service.settings", _runtime_settings(runtime_approval_enabled=True, runtime_approvers=["security@example.com"]))
    service = RuntimeService()
    mock_backend = MagicMock()
    mock_backend.get_capabilities.return_value = docker_caps
    mock_backend.deploy = AsyncMock(return_value=RuntimeBackendDeployResult(status="running", runtime_ref="abc"))
    service.backends = {"docker": mock_backend}

    request = RuntimeDeployRequest(
        name="GitHub Runtime",
        backend="docker",
        source=RuntimeSource(type="github", repo="org/repo", dockerfile="Dockerfile"),
        guardrails_profile="standard",
    )

    runtime = await service.deploy(request, test_db, requested_by="developer@example.com")
    assert runtime.approval_status == "pending"
    assert runtime.status == "pending_approval"

    approval = test_db.query(RuntimeDeploymentApproval).filter_by(runtime_deployment_id=runtime.id).first()
    assert approval is not None
    assert approval.status == "pending"
    assert approval.approvers == ["security@example.com"]


@pytest.mark.asyncio
async def test_approve_executes_deployment(monkeypatch, test_db, docker_caps):
    monkeypatch.setattr("mcpgateway.services.runtime_service.settings", _runtime_settings(runtime_approval_enabled=True, runtime_approvers=["security@example.com"], httpx_admin_read_timeout=20))
    service = RuntimeService()

    mock_backend = MagicMock()
    mock_backend.get_capabilities.return_value = docker_caps
    mock_backend.deploy = AsyncMock(return_value=RuntimeBackendDeployResult(status="running", runtime_ref="container-1", endpoint_url="http://127.0.0.1:8123", image="ghcr.io/acme/app:1"))
    service.backends = {"docker": mock_backend}
    service.gateway_service.register_gateway = AsyncMock(return_value=MagicMock(id="gateway-1"))

    deploy_request = RuntimeDeployRequest(
        name="Approval Runtime",
        backend="docker",
        source=RuntimeSource(type="github", repo="org/repo"),
        guardrails_profile="standard",
    )
    pending = await service.deploy(deploy_request, test_db, requested_by="dev@example.com")
    approval = test_db.query(RuntimeDeploymentApproval).filter_by(runtime_deployment_id=pending.id).one()

    approved_runtime = await service.approve(approval.id, test_db, reviewer="security@example.com", reason="approved")
    assert approved_runtime.approval_status == "approved"
    assert approved_runtime.status in {"running", "connected"}
    assert approved_runtime.runtime_ref == "container-1"


@pytest.mark.asyncio
async def test_get_approval_details(monkeypatch, test_db, docker_caps):
    monkeypatch.setattr("mcpgateway.services.runtime_service.settings", _runtime_settings(runtime_approval_enabled=True, runtime_approvers=["security@example.com"]))
    service = RuntimeService()

    mock_backend = MagicMock()
    mock_backend.get_capabilities.return_value = docker_caps
    mock_backend.deploy = AsyncMock(return_value=RuntimeBackendDeployResult(status="running", runtime_ref="abc"))
    service.backends = {"docker": mock_backend}

    request = RuntimeDeployRequest(
        name="Approval Lookup Runtime",
        backend="docker",
        source=RuntimeSource(type="github", repo="org/repo"),
        guardrails_profile="standard",
    )
    runtime = await service.deploy(request, test_db, requested_by="developer@example.com")
    approval = test_db.query(RuntimeDeploymentApproval).filter_by(runtime_deployment_id=runtime.id).one()

    details = await service.get_approval(approval.id, test_db)
    assert details.id == approval.id
    assert details.runtime_deployment_id == runtime.id
    assert details.status == "pending"


@pytest.mark.asyncio
async def test_guardrail_compatibility_warns_for_code_engine(monkeypatch, test_db):
    monkeypatch.setattr("mcpgateway.services.runtime_service.settings", _runtime_settings(runtime_docker_enabled=False, runtime_ibm_code_engine_enabled=False))
    service = RuntimeService()

    ce_backend = MagicMock()
    ce_backend.get_capabilities.return_value = RuntimeBackendCapabilities(
        backend="ibm_code_engine",
        supports_compose=False,
        supports_github_build=True,
        supports_allowed_hosts=False,
        supports_readonly_fs=False,
        supports_custom_capabilities=False,
        supports_pids_limit=False,
    )
    service.backends = {"ibm_code_engine": ce_backend}

    compatibility = await service.guardrail_compatibility("standard", "ibm_code_engine", test_db)
    assert compatibility.compatible is False
    assert compatibility.warnings
    assert any(w.field == "filesystem.read_only_root" for w in compatibility.warnings)


@pytest.mark.asyncio
async def test_deploy_catalog_enforces_supported_backends(monkeypatch, test_db):
    monkeypatch.setattr("mcpgateway.services.runtime_service.settings", _runtime_settings(runtime_docker_enabled=False, runtime_ibm_code_engine_enabled=False))
    service = RuntimeService()

    ce_caps = RuntimeBackendCapabilities(
        backend="ibm_code_engine",
        supports_compose=False,
        supports_github_build=True,
        supports_allowed_hosts=False,
        supports_readonly_fs=False,
        supports_custom_capabilities=False,
        supports_pids_limit=False,
    )
    mock_backend = MagicMock()
    mock_backend.get_capabilities.return_value = ce_caps
    service.backends = {"ibm_code_engine": mock_backend}
    service.catalog_service.load_catalog = AsyncMock(
        return_value={
            "catalog_servers": [
                {
                    "id": "docker-only-entry",
                    "name": "Docker Only",
                    "supported_backends": ["docker"],
                    "source": {"type": "docker", "image": "docker.io/acme/runtime:1"},
                }
            ]
        }
    )

    request = RuntimeDeployRequest(name="Catalog Runtime", backend="ibm_code_engine", catalog_server_id="docker-only-entry")
    with pytest.raises(RuntimeBackendError, match="does not support runtime backend"):
        await service.deploy(request, test_db, requested_by="dev@example.com")


@pytest.mark.asyncio
async def test_deploy_catalog_uses_catalog_guardrails_profile_by_default(monkeypatch, test_db, docker_caps):
    monkeypatch.setattr("mcpgateway.services.runtime_service.settings", _runtime_settings())
    service = RuntimeService()

    mock_backend = MagicMock()
    mock_backend.get_capabilities.return_value = docker_caps
    mock_backend.deploy = AsyncMock(return_value=RuntimeBackendDeployResult(status="running", runtime_ref="container-1", image="docker.io/acme/runtime:1"))
    service.backends = {"docker": mock_backend}
    service.catalog_service.load_catalog = AsyncMock(
        return_value={
            "catalog_servers": [
                {
                    "id": "catalog-restricted",
                    "name": "Restricted Runtime",
                    "source": {"type": "docker", "image": "docker.io/acme/runtime:1"},
                    "supported_backends": ["docker"],
                    "guardrails_profile": "restricted",
                }
            ]
        }
    )

    request = RuntimeDeployRequest(name="Catalog Runtime", backend="docker", catalog_server_id="catalog-restricted", register_gateway=False)
    runtime = await service.deploy(request, test_db, requested_by="dev@example.com")
    assert runtime.guardrails_profile == "restricted"


@pytest.mark.asyncio
async def test_constructor_enables_ibm_code_engine_backend(monkeypatch):
    monkeypatch.setattr(
        "mcpgateway.services.runtime_service.settings",
        _runtime_settings(runtime_docker_enabled=False, runtime_ibm_code_engine_enabled=True),
    )
    service = RuntimeService()
    assert "ibm_code_engine" in service.backends


@pytest.mark.asyncio
async def test_constructor_passes_runtime_docker_socket_to_backend(monkeypatch):
    monkeypatch.setattr(
        "mcpgateway.services.runtime_service.settings",
        _runtime_settings(runtime_docker_socket="/tmp/docker-custom.sock"),
    )
    service = RuntimeService()
    backend = service.backends["docker"]
    assert isinstance(backend, DockerRuntimeBackend)
    assert backend.docker_socket == "/tmp/docker-custom.sock"


@pytest.mark.asyncio
async def test_list_backend_capabilities_and_get_backend_errors(monkeypatch, docker_caps):
    monkeypatch.setattr("mcpgateway.services.runtime_service.settings", _runtime_settings(runtime_docker_enabled=False))
    service = RuntimeService()
    backend = MagicMock()
    backend.get_capabilities.return_value = docker_caps
    service.backends = {"docker": backend}
    capabilities = service.list_backend_capabilities()
    assert len(capabilities) == 1
    assert capabilities[0].backend == "docker"

    with pytest.raises(RuntimeBackendError, match="not enabled"):
        service._get_backend("missing")


@pytest.mark.asyncio
async def test_deploy_rejects_when_runtime_feature_disabled(monkeypatch, test_db):
    monkeypatch.setattr("mcpgateway.services.runtime_service.settings", _runtime_settings(mcpgateway_runtime_enabled=False, runtime_docker_enabled=False))
    service = RuntimeService()
    service.backends = {"docker": MagicMock()}
    request = RuntimeDeployRequest(name="disabled-runtime", backend="docker", source=RuntimeSource(type="docker", image="docker.io/acme/runtime:1"))
    with pytest.raises(RuntimeBackendError, match="disabled"):
        await service.deploy(request, test_db, requested_by="dev@example.com")


@pytest.mark.asyncio
async def test_runtime_crud_operations(monkeypatch, test_db, docker_caps):
    monkeypatch.setattr("mcpgateway.services.runtime_service.settings", _runtime_settings(runtime_docker_enabled=False))
    service = RuntimeService()
    backend = MagicMock()
    backend.get_capabilities.return_value = docker_caps
    backend.get_status = AsyncMock(return_value=RuntimeBackendStatus(status="running", endpoint_url="http://127.0.0.1:8123", backend_response={"probe": "ok"}))
    backend.start = AsyncMock(return_value=RuntimeBackendStatus(status="running", backend_response={"started": True}))
    backend.stop = AsyncMock(return_value=RuntimeBackendStatus(status="stopped", backend_response={"stopped": True}))
    backend.delete = AsyncMock(return_value=None)
    backend.logs = AsyncMock(return_value=["a", "b"])
    service.backends = {"docker": backend}

    runtime_row = _runtime_row(runtime_ref="container-1", backend_response={"existing": "value"})
    test_db.add(runtime_row)
    test_db.flush()

    runtimes, total = await service.list_runtimes(test_db, backend="docker", status="running", limit=10, offset=0)
    assert total == 1
    assert runtimes[0].id == runtime_row.id

    found = await service.get_runtime(runtime_row.id, test_db)
    assert found.id == runtime_row.id

    refreshed = await service.refresh_runtime_status(runtime_row.id, test_db)
    assert refreshed.status == "running"
    assert refreshed.backend_response["probe"] == "ok"

    started = await service.start_runtime(runtime_row.id, test_db)
    assert started.status == "running"

    stopped = await service.stop_runtime(runtime_row.id, test_db)
    assert stopped.status == "stopped"

    log_lines = await service.logs(runtime_row.id, test_db, tail=50)
    assert log_lines == ["a", "b"]

    deleted = await service.delete_runtime(runtime_row.id, test_db)
    assert deleted.status == "deleted"

    runtime_without_ref = _runtime_row(name="no-ref", slug="no-ref", runtime_ref=None)
    test_db.add(runtime_without_ref)
    test_db.flush()
    assert await service.logs(runtime_without_ref.id, test_db, tail=10) == []
    refreshed_without_ref = await service.refresh_runtime_status(runtime_without_ref.id, test_db)
    assert refreshed_without_ref.id == runtime_without_ref.id


@pytest.mark.asyncio
async def test_runtime_list_all_status_filter_returns_all_rows(monkeypatch, test_db, docker_caps):
    monkeypatch.setattr("mcpgateway.services.runtime_service.settings", _runtime_settings(runtime_docker_enabled=False))
    service = RuntimeService()
    backend = MagicMock()
    backend.get_capabilities.return_value = docker_caps
    service.backends = {"docker": backend}

    running_runtime = _runtime_row(name="all-running", slug="all-running", status="running")
    deleted_runtime = _runtime_row(name="all-deleted", slug="all-deleted", status="deleted")
    test_db.add_all([running_runtime, deleted_runtime])
    test_db.flush()

    runtimes, total = await service.list_runtimes(test_db, backend="docker", status="all", limit=50, offset=0)
    assert total == 2
    runtime_ids = {item.id for item in runtimes}
    assert running_runtime.id in runtime_ids
    assert deleted_runtime.id in runtime_ids


@pytest.mark.asyncio
async def test_runtime_crud_error_paths(monkeypatch, test_db, docker_caps):
    monkeypatch.setattr("mcpgateway.services.runtime_service.settings", _runtime_settings(runtime_docker_enabled=False))
    service = RuntimeService()
    backend = MagicMock()
    backend.get_capabilities.return_value = docker_caps
    service.backends = {"docker": backend}

    deleted_runtime = _runtime_row(name="deleted", slug="deleted", status="deleted", runtime_ref="container-deleted")
    no_ref_runtime = _runtime_row(name="no-ref-runtime", slug="no-ref-runtime", runtime_ref=None)
    test_db.add(deleted_runtime)
    test_db.add(no_ref_runtime)
    test_db.flush()

    with pytest.raises(RuntimeBackendError, match="not found"):
        await service.get_runtime("missing", test_db)
    with pytest.raises(RuntimeBackendError, match="not found"):
        await service._get_runtime_row("missing", test_db)
    with pytest.raises(RuntimeBackendError, match="Cannot start deleted"):
        await service.start_runtime(deleted_runtime.id, test_db)
    with pytest.raises(RuntimeBackendError, match="has no backend reference"):
        await service.start_runtime(no_ref_runtime.id, test_db)
    with pytest.raises(RuntimeBackendError, match="Cannot stop deleted"):
        await service.stop_runtime(deleted_runtime.id, test_db)
    with pytest.raises(RuntimeBackendError, match="has no backend reference"):
        await service.stop_runtime(no_ref_runtime.id, test_db)


@pytest.mark.asyncio
async def test_guardrail_profile_crud_paths(monkeypatch, test_db):
    monkeypatch.setattr("mcpgateway.services.runtime_service.settings", _runtime_settings(runtime_docker_enabled=False))
    service = RuntimeService()

    builtin = await service.get_guardrail_profile("standard", test_db)
    assert builtin.built_in is True

    created = await service.create_guardrail_profile(
        RuntimeGuardrailProfileCreate(name="custom-1", description="desc", recommended_backends=["docker"]),
        test_db,
        created_by="dev@example.com",
    )
    assert created.name == "custom-1"
    fetched_custom = await service.get_guardrail_profile("custom-1", test_db)
    assert fetched_custom.name == "custom-1"

    profiles = await service.list_guardrail_profiles(test_db)
    assert any(profile.name == "custom-1" for profile in profiles)

    updated = await service.update_guardrail_profile(
        "custom-1",
        RuntimeGuardrailProfileUpdate(
            description="updated",
            recommended_backends=["docker", "ibm_code_engine"],
            config=RuntimeSecurityGuardrails(network={"egress_allowed": False}),
        ),
        test_db,
    )
    assert updated.description == "updated"

    await service.delete_guardrail_profile("custom-1", test_db)
    test_db.flush()
    remaining = await service.list_guardrail_profiles(test_db)
    assert not any(profile.name == "custom-1" for profile in remaining)

    with pytest.raises(RuntimeBackendError, match="Cannot overwrite built-in"):
        await service.create_guardrail_profile(RuntimeGuardrailProfileCreate(name="standard"), test_db, created_by=None)
    with pytest.raises(RuntimeBackendError, match="cannot be updated"):
        await service.update_guardrail_profile("standard", RuntimeGuardrailProfileUpdate(description="x"), test_db)
    with pytest.raises(RuntimeBackendError, match="cannot be deleted"):
        await service.delete_guardrail_profile("standard", test_db)
    with pytest.raises(RuntimeBackendError, match="not found"):
        await service.get_guardrail_profile("missing-profile", test_db)
    with pytest.raises(RuntimeBackendError, match="already exists"):
        await service.create_guardrail_profile(RuntimeGuardrailProfileCreate(name="duplicate"), test_db, created_by=None)
        await service.create_guardrail_profile(RuntimeGuardrailProfileCreate(name="duplicate"), test_db, created_by=None)


@pytest.mark.asyncio
async def test_guardrail_profile_duplicate_and_missing_update_delete(monkeypatch, test_db):
    monkeypatch.setattr("mcpgateway.services.runtime_service.settings", _runtime_settings(runtime_docker_enabled=False))
    service = RuntimeService()
    row = _guardrail_row("duplicate")
    test_db.add(row)
    test_db.flush()

    with pytest.raises(RuntimeBackendError, match="already exists"):
        await service.create_guardrail_profile(RuntimeGuardrailProfileCreate(name="duplicate"), test_db, created_by="dev@example.com")
    with pytest.raises(RuntimeBackendError, match="not found"):
        await service.update_guardrail_profile("missing", RuntimeGuardrailProfileUpdate(description="x"), test_db)
    with pytest.raises(RuntimeBackendError, match="not found"):
        await service.delete_guardrail_profile("missing", test_db)


@pytest.mark.asyncio
async def test_approval_listing_and_decisions(monkeypatch, test_db, docker_caps):
    monkeypatch.setattr(
        "mcpgateway.services.runtime_service.settings",
        _runtime_settings(runtime_docker_enabled=False, runtime_approval_enabled=True, runtime_approvers=["security@example.com"]),
    )
    service = RuntimeService()
    backend = MagicMock()
    backend.get_capabilities.return_value = docker_caps
    backend.deploy = AsyncMock(return_value=RuntimeBackendDeployResult(status="running", runtime_ref="container-approved"))
    service.backends = {"docker": backend}

    request = RuntimeDeployRequest(name="approval-runtime", backend="docker", source=RuntimeSource(type="github", repo="org/repo"))
    runtime = await service.deploy(request, test_db, requested_by="dev@example.com")
    approval = test_db.query(RuntimeDeploymentApproval).filter_by(runtime_deployment_id=runtime.id).one()

    approvals, total = await service.list_approvals(test_db, status="pending", limit=50, offset=0)
    assert total >= 1
    assert any(item.id == approval.id for item in approvals)

    all_approvals, all_total = await service.list_approvals(test_db, status="all", limit=50, offset=0)
    assert all_total >= total
    assert any(item.id == approval.id for item in all_approvals)

    approved_runtime = await service.approve(approval.id, test_db, reviewer="security@example.com", reason="ok")
    assert approved_runtime.approval_status == "approved"

    # Create another pending request for rejection path.
    runtime_to_reject = await service.deploy(
        RuntimeDeployRequest(name="reject-runtime", backend="docker", source=RuntimeSource(type="github", repo="org/repo")),
        test_db,
        requested_by="dev@example.com",
    )
    reject_approval = test_db.query(RuntimeDeploymentApproval).filter_by(runtime_deployment_id=runtime_to_reject.id).one()
    rejected_runtime = await service.reject(reject_approval.id, test_db, reviewer="security@example.com", reason="rejecting")
    assert rejected_runtime.approval_status == "rejected"
    assert rejected_runtime.status == "error"


@pytest.mark.asyncio
async def test_approval_error_paths(monkeypatch, test_db):
    monkeypatch.setattr("mcpgateway.services.runtime_service.settings", _runtime_settings(runtime_docker_enabled=False, runtime_approval_enabled=True))
    service = RuntimeService()

    with pytest.raises(RuntimeBackendError, match="not found"):
        await service.get_approval("missing", test_db)
    with pytest.raises(RuntimeBackendError, match="not found"):
        await service.approve("missing", test_db, reviewer=None, reason=None)
    with pytest.raises(RuntimeBackendError, match="not found"):
        await service.reject("missing", test_db, reviewer=None, reason=None)

    runtime = _runtime_row(status="pending_approval", approval_status="pending")
    test_db.add(runtime)
    test_db.flush()
    approval = RuntimeDeploymentApproval(
        id=str(uuid4()),
        runtime_deployment_id=runtime.id,
        status="approved",
        requested_by="dev@example.com",
        approvers=["security@example.com"],
        rule_snapshot={},
        expires_at=utc_now() + timedelta(hours=1),
    )
    test_db.add(approval)
    test_db.flush()
    with pytest.raises(RuntimeBackendError, match="not pending"):
        await service.approve(approval.id, test_db, reviewer=None, reason=None)
    with pytest.raises(RuntimeBackendError, match="not pending"):
        await service.reject(approval.id, test_db, reviewer=None, reason=None)


@pytest.mark.asyncio
async def test_approval_expiry_marks_runtime_failed(monkeypatch, test_db, docker_caps):
    monkeypatch.setattr("mcpgateway.services.runtime_service.settings", _runtime_settings(runtime_docker_enabled=False, runtime_approval_enabled=True))
    service = RuntimeService()
    backend = MagicMock()
    backend.get_capabilities.return_value = docker_caps
    service.backends = {"docker": backend}

    runtime = _runtime_row(status="pending_approval", approval_status="pending")
    test_db.add(runtime)
    test_db.flush()
    approval = RuntimeDeploymentApproval(
        id=str(uuid4()),
        runtime_deployment_id=runtime.id,
        status="pending",
        requested_by="dev@example.com",
        approvers=["security@example.com"],
        rule_snapshot={},
        expires_at=utc_now() - timedelta(hours=1),
    )
    test_db.add(approval)
    test_db.flush()

    with pytest.raises(RuntimeBackendError, match="expired"):
        await service.approve(approval.id, test_db, reviewer="security@example.com", reason="late")

    refreshed_runtime = test_db.query(RuntimeDeployment).filter_by(id=runtime.id).one()
    assert refreshed_runtime.approval_status == "expired"
    assert refreshed_runtime.status == "error"


@pytest.mark.asyncio
async def test_approve_handles_naive_now_and_aware_expiry(monkeypatch, test_db, docker_caps):
    monkeypatch.setattr(
        "mcpgateway.services.runtime_service.settings",
        _runtime_settings(runtime_docker_enabled=False, runtime_approval_enabled=True),
    )
    service = RuntimeService()
    backend = MagicMock()
    backend.get_capabilities.return_value = docker_caps
    backend.deploy = AsyncMock(return_value=RuntimeBackendDeployResult(status="running", runtime_ref="runtime-naive-now"))
    service.backends = {"docker": backend}

    runtime = _runtime_row(status="pending_approval", approval_status="pending")
    test_db.add(runtime)
    test_db.flush()
    approval = RuntimeDeploymentApproval(
        id=str(uuid4()),
        runtime_deployment_id=runtime.id,
        status="pending",
        requested_by="dev@example.com",
        approvers=["security@example.com"],
        rule_snapshot={},
        expires_at=utc_now() + timedelta(hours=1),
    )
    test_db.add(approval)
    test_db.flush()

    monkeypatch.setattr(
        "mcpgateway.services.runtime_service.utc_now",
        lambda: utc_now().replace(tzinfo=None),
    )
    approved = await service.approve(approval.id, test_db, reviewer="security@example.com", reason="ok")
    assert approved.approval_status == "approved"


@pytest.mark.asyncio
async def test_execute_deployment_error_and_gateway_registration_warning(monkeypatch, test_db, docker_caps):
    monkeypatch.setattr("mcpgateway.services.runtime_service.settings", _runtime_settings(runtime_docker_enabled=False))
    service = RuntimeService()
    backend = MagicMock()
    backend.get_capabilities.return_value = docker_caps
    backend.deploy = AsyncMock(side_effect=RuntimeBackendError("deployment failed"))
    service.backends = {"docker": backend}

    runtime = _runtime_row(status="deploying", runtime_ref=None)
    await service._execute_deployment(runtime, backend, test_db)
    assert runtime.status == "error"
    assert "failed" in (runtime.error_message or "")

    backend.deploy = AsyncMock(
        return_value=RuntimeBackendDeployResult(
            status="running",
            runtime_ref="runtime-123",
            endpoint_url="http://127.0.0.1:8080",
            image="docker.io/acme/runtime:1",
            warnings=[{"field": "x", "message": "warn", "backend": "docker"}],
            backend_response={"ok": True},
        )
    )
    service.gateway_service.register_gateway = AsyncMock(side_effect=RuntimeError("gateway offline"))
    runtime.runtime_metadata = {"register_gateway": True, "gateway_name": "gw", "gateway_transport": "SSE", "visibility": "public", "tags": []}
    await service._execute_deployment(runtime, backend, test_db)
    assert runtime.status == "running"
    assert runtime.runtime_ref == "runtime-123"
    assert runtime.endpoint_url == "http://127.0.0.1:8080"
    assert runtime.backend_response["ok"] is True
    assert runtime.guardrails_warnings


@pytest.mark.asyncio
async def test_register_gateway_retries_common_streamable_paths(monkeypatch, test_db):
    monkeypatch.setattr("mcpgateway.services.runtime_service.settings", _runtime_settings(runtime_docker_enabled=False))
    service = RuntimeService()

    runtime = _runtime_row(
        status="running",
        endpoint_url="http://runtime-host:8080",
        runtime_metadata={"register_gateway": True, "gateway_name": "gw-runtime", "gateway_transport": "STREAMABLEHTTP", "visibility": "public", "tags": []},
    )

    attempted_urls: list[str] = []

    async def _register_gateway(*, gateway, **_kwargs):  # noqa: ANN001
        attempted_urls.append(gateway.url)
        if gateway.url.endswith("/http"):
            return SimpleNamespace(id="gw-123")
        raise RuntimeError("initialization failed")

    service.gateway_service.register_gateway = AsyncMock(side_effect=_register_gateway)

    await service._register_gateway(runtime, test_db)

    assert attempted_urls == ["http://runtime-host:8080/http"]
    assert runtime.gateway_id == "gw-123"
    assert runtime.status == "connected"
    assert runtime.endpoint_url == "http://runtime-host:8080/http"


def test_resolve_endpoint_preferences_precedence(monkeypatch):
    monkeypatch.setattr("mcpgateway.services.runtime_service.settings", _runtime_settings(runtime_docker_enabled=False))
    service = RuntimeService()
    request = RuntimeDeployRequest(
        name="endpoint-precedence",
        backend="docker",
        source=RuntimeSource(type="docker", image="docker.io/acme/runtime:1"),
        endpoint_port=19000,
        endpoint_path="http",
        metadata={"endpoint_port": 18000, "endpoint_path": "/mcp"},
    )
    endpoint_port, endpoint_path = service._resolve_endpoint_preferences(
        request,
        {
            "runtime": {
                "endpoint_port": 17000,
                "endpoint_path": "/catalog",
            }
        },
    )
    assert endpoint_port == 19000
    assert endpoint_path == "/http"


@pytest.mark.asyncio
async def test_source_resolution_and_guardrail_resolution_helpers(monkeypatch, test_db):
    monkeypatch.setattr("mcpgateway.services.runtime_service.settings", _runtime_settings(runtime_docker_enabled=False))
    service = RuntimeService()

    explicit_request = RuntimeDeployRequest(name="explicit", backend="docker", source=RuntimeSource(type="docker", image="docker.io/acme/runtime:1"))
    explicit_source, explicit_catalog = await service._resolve_source(explicit_request)
    assert explicit_source["type"] == "docker"
    assert explicit_catalog is None

    service.catalog_service.load_catalog = AsyncMock(
        return_value={
            "catalog_servers": [
                {"id": "with-source", "source": {"type": "docker", "image": "docker.io/acme/runtime:1"}},
                {"id": "no-source"},
            ]
        }
    )
    catalog_source, catalog_entry = await service._resolve_source(RuntimeDeployRequest(name="from-catalog", backend="docker", catalog_server_id="with-source"))
    assert catalog_source["type"] == "docker"
    assert catalog_entry is not None

    with pytest.raises(RuntimeBackendError, match="does not include deployable source metadata"):
        await service._resolve_source(RuntimeDeployRequest(name="bad-catalog", backend="docker", catalog_server_id="no-source"))
    with pytest.raises(RuntimeBackendError, match="not found"):
        await service._resolve_source(RuntimeDeployRequest(name="missing-catalog", backend="docker", catalog_server_id="missing"))

    profile_name, guardrails = await service._resolve_guardrails(
        RuntimeDeployRequest(
            name="guardrails",
            backend="docker",
            source=RuntimeSource(type="docker", image="docker.io/acme/runtime:1"),
            guardrails_overrides={"network": {"allowed_hosts": ["example.com"]}},
            resources={"cpu": "1"},
        ),
        test_db,
        guardrails_profile_override="standard",
    )
    assert profile_name == "standard"
    assert guardrails["network"]["allowed_hosts"] == ["example.com"]
    assert guardrails["resources"]["cpu"] == "1"


def test_guardrail_warnings_and_approval_rules(monkeypatch, docker_caps):
    monkeypatch.setattr(
        "mcpgateway.services.runtime_service.settings",
        _runtime_settings(
            runtime_approval_enabled=True,
            runtime_approval_required_source_types=["github"],
            runtime_approval_required_guardrails_profiles=["standard"],
            runtime_approval_registry_allowlist=["docker.io/trusted"],
            runtime_approvers=["security@example.com"],
        ),
    )
    service = RuntimeService()

    weak_caps = RuntimeBackendCapabilities(
        backend="ibm_code_engine",
        supports_compose=False,
        supports_github_build=True,
        supports_allowed_hosts=False,
        supports_readonly_fs=False,
        supports_custom_capabilities=False,
        supports_pids_limit=False,
    )
    warnings = service._guardrail_warnings_for_backend(
        {
            "network": {"allowed_hosts": ["example.com"]},
            "filesystem": {"read_only_root": True},
            "capabilities": {"add": ["NET_ADMIN"]},
            "resources": {"max_pids": 10},
            "apparmor": "strict",
        },
        "ibm_code_engine",
        weak_caps,
    )
    assert len(warnings) == 5

    required, reasons = service._approval_required(
        RuntimeDeployRequest(name="approval", backend="docker", source=RuntimeSource(type="github", repo="acme/repo")),
        {"type": "github", "image": "docker.io/untrusted/runtime:1"},
        "standard",
        {"id": "catalog-1", "requires_approval": True},
    )
    assert required is True
    assert reasons["source_type_triggered"] is True
    assert reasons["guardrails_profile_triggered"] is True
    assert reasons["registry_triggered"] is True
    assert reasons["catalog_requires_approval"] is True

    monkeypatch.setattr("mcpgateway.services.runtime_service.settings", _runtime_settings(runtime_approval_enabled=False))
    disabled_required, disabled_reasons = service._approval_required(
        RuntimeDeployRequest(name="approval-off", backend="docker", source=RuntimeSource(type="docker", image="docker.io/acme/runtime:1")),
        {"type": "docker", "image": "docker.io/acme/runtime:1"},
        "standard",
        None,
    )
    assert disabled_required is False
    assert disabled_reasons == {}

    monkeypatch.setattr("mcpgateway.services.runtime_service.settings", _runtime_settings(runtime_approval_registry_allowlist=[]))
    assert service._image_allowlisted("docker.io/acme/runtime:1") is False
    monkeypatch.setattr("mcpgateway.services.runtime_service.settings", _runtime_settings(runtime_approval_registry_allowlist=["docker.io/acme"]))
    assert service._image_allowlisted("docker.io/acme/runtime:1") is True

    service._validate_source_backend_compatibility("docker", docker_caps)
    with pytest.raises(RuntimeBackendError, match="compose"):
        service._validate_source_backend_compatibility("compose", RuntimeBackendCapabilities(backend="x", supports_compose=False))
    with pytest.raises(RuntimeBackendError, match="github"):
        service._validate_source_backend_compatibility("github", RuntimeBackendCapabilities(backend="x", supports_github_build=False))

    RuntimeService._validate_catalog_backend_compatibility(None, "docker")
    RuntimeService._validate_catalog_backend_compatibility({"supported_backends": "docker"}, "docker")
    with pytest.raises(RuntimeBackendError, match="does not support runtime backend"):
        RuntimeService._validate_catalog_backend_compatibility({"name": "Only CE", "supported_backends": ["ibm_code_engine"]}, "docker")


def test_runtime_service_static_utilities(test_db):
    target = {"a": {"b": 1}, "x": 1}
    RuntimeService._deep_merge(target, {"a": {"c": 2}, "x": 3})
    assert target == {"a": {"b": 1, "c": 2}, "x": 3}

    merged = RuntimeService._merge_dicts({"a": {"b": 1}}, {"a": {"c": 2}})
    assert merged == {"a": {"b": 1, "c": 2}}

    assert RuntimeService._infer_transport("wss://example.com/ws") == "SSE"
    assert RuntimeService._infer_transport("https://example.com/sse") == "SSE"
    assert RuntimeService._infer_transport("https://example.com/mcp") == "STREAMABLEHTTP"
    assert RuntimeService._append_path("https://example.com", "/http") == "https://example.com/http"
    assert RuntimeService._append_path("https://example.com/base", "mcp") == "https://example.com/base/mcp"
    assert RuntimeService._candidate_gateway_urls("https://example.com", "STREAMABLEHTTP") == [
        "https://example.com/http",
        "https://example.com/mcp",
        "https://example.com",
    ]
    assert RuntimeService._candidate_gateway_urls(
        "https://example.com",
        "STREAMABLEHTTP",
        preferred_path="/custom",
    ) == [
        "https://example.com/custom",
        "https://example.com/http",
        "https://example.com/mcp",
        "https://example.com",
    ]
    assert RuntimeService._candidate_gateway_urls("https://example.com/sse", "SSE") == [
        "https://example.com/sse"
    ]

    runtime = _runtime_row()
    test_db.add(runtime)
    test_db.flush()
    runtime_read = RuntimeService._to_runtime_read(runtime)
    assert runtime_read.id == runtime.id

    approval = RuntimeDeploymentApproval(
        id=str(uuid4()),
        runtime_deployment_id=runtime.id,
        status="pending",
        requested_by="dev@example.com",
        approvers=["security@example.com"],
        rule_snapshot={"rule": True},
        expires_at=None,
    )
    test_db.add(approval)
    test_db.flush()
    approval_read = RuntimeService._to_approval_read(approval)
    assert approval_read.id == approval.id

    profile = _guardrail_row("profile-static")
    profile_read = RuntimeService._to_guardrail_profile_read(profile)
    assert profile_read.name == "profile-static"

    caps = RuntimeBackendCapabilities(backend="docker", supports_compose=True, supports_github_build=True)
    caps_read = RuntimeService._capabilities_to_schema("docker", caps)
    assert caps_read.backend == "docker"


@pytest.mark.asyncio
async def test_docker_backend_run_maps_missing_binary_to_runtime_error(monkeypatch):
    backend = DockerRuntimeBackend(docker_binary="docker")

    async def _missing_binary(*_args, **_kwargs):
        raise FileNotFoundError("missing docker binary")

    monkeypatch.setattr(
        "mcpgateway.runtimes.docker_backend.asyncio.create_subprocess_exec",
        _missing_binary,
    )

    with pytest.raises(RuntimeBackendError, match="Command not found: docker"):
        await backend._run(["docker", "version"])


@pytest.mark.asyncio
async def test_docker_backend_run_sets_docker_host_when_socket_configured(monkeypatch):
    backend = DockerRuntimeBackend(
        docker_binary="docker",
        docker_socket="/tmp/test-docker.sock",
    )
    monkeypatch.delenv("DOCKER_HOST", raising=False)

    captured_kwargs = {}

    class _Process:
        returncode = 0

        async def communicate(self):
            return b"ok", b""

    async def _create_subprocess_exec(*_args, **kwargs):
        captured_kwargs.update(kwargs)
        return _Process()

    monkeypatch.setattr(
        "mcpgateway.runtimes.docker_backend.asyncio.create_subprocess_exec",
        _create_subprocess_exec,
    )

    output = await backend._run(["docker", "version"])
    assert output == "ok"
    assert captured_kwargs["env"]["DOCKER_HOST"] == "unix:///tmp/test-docker.sock"


@pytest.mark.asyncio
async def test_docker_backend_run_can_return_stderr_on_success(monkeypatch):
    backend = DockerRuntimeBackend(docker_binary="docker")

    class _Process:
        returncode = 0

        async def communicate(self):
            return b"", b"line-1\nline-2\n"

    async def _create_subprocess_exec(*_args, **_kwargs):
        return _Process()

    monkeypatch.setattr(
        "mcpgateway.runtimes.docker_backend.asyncio.create_subprocess_exec",
        _create_subprocess_exec,
    )

    output = await backend._run(["docker", "logs", "--tail", "20", "container-123"], include_stderr=True)
    assert output == "line-1\nline-2"


@pytest.mark.asyncio
async def test_docker_backend_logs_uses_combined_output(monkeypatch):
    backend = DockerRuntimeBackend(docker_binary="docker")

    async def _fake_run(cmd, timeout=300, include_stderr=False):  # noqa: ANN001
        assert cmd == ["docker", "logs", "--tail", "5", "container-abc"]
        assert timeout == 120
        assert include_stderr is True
        return "startup line\nrequest line"

    monkeypatch.setattr(backend, "_run", _fake_run)

    lines = await backend.logs("container-abc", tail=5)
    assert lines == ["startup line", "request line"]


@pytest.mark.asyncio
async def test_docker_backend_builds_github_using_clone_relative_dockerfile_path(monkeypatch, tmp_path):
    backend = DockerRuntimeBackend(docker_binary="docker")

    temp_root = tmp_path / "runtime-workdir"
    clone_dir = temp_root / "src"
    calls: list[list[str]] = []

    class _TempDir:
        def __enter__(self):
            temp_root.mkdir(parents=True, exist_ok=True)
            return str(temp_root)

        def __exit__(self, exc_type, exc_val, exc_tb):
            return False

    async def _fake_run(cmd, timeout=300):  # noqa: ANN001
        calls.append(cmd)
        if cmd[:2] == ["git", "clone"]:
            clone_dir.mkdir(parents=True, exist_ok=True)
            (clone_dir / "Dockerfile").write_text("FROM scratch\\n", encoding="utf-8")
        return "ok"

    monkeypatch.setattr("mcpgateway.runtimes.docker_backend.tempfile.TemporaryDirectory", lambda prefix: _TempDir())
    monkeypatch.setattr(backend, "_run", _fake_run)

    image, logs = await backend._build_image_from_github(
        RuntimeBackendDeployRequest(
            runtime_id="12345678-1234-1234-1234-123456789abc",
            name="github-runtime",
            source_type="github",
            source={
                "type": "github",
                "repo": "acme/runtime",
                "branch": "main",
                "dockerfile": "Dockerfile",
            },
        )
    )

    assert image.startswith("mcpgateway-runtime/github-runtime:")
    assert any("Cloned repository" in line for line in logs)
    assert any("Built image" in line for line in logs)

    build_cmd = next(cmd for cmd in calls if len(cmd) > 1 and cmd[1] == "build")
    dockerfile_arg = build_cmd[build_cmd.index("-f") + 1]
    assert Path(dockerfile_arg) == (clone_dir / "Dockerfile").resolve()
    assert Path(build_cmd[-1]) == clone_dir.resolve()


@pytest.mark.asyncio
async def test_docker_backend_builds_github_with_subdirectory_dockerfile_uses_subdirectory_context(monkeypatch, tmp_path):
    backend = DockerRuntimeBackend(docker_binary="docker")

    temp_root = tmp_path / "runtime-workdir-subdir"
    clone_dir = temp_root / "src"
    subdir = clone_dir / "mcp-servers" / "go" / "fast-time-server"
    calls: list[list[str]] = []

    class _TempDir:
        def __enter__(self):
            temp_root.mkdir(parents=True, exist_ok=True)
            return str(temp_root)

        def __exit__(self, exc_type, exc_val, exc_tb):
            return False

    async def _fake_run(cmd, timeout=300):  # noqa: ANN001
        calls.append(cmd)
        if cmd[:2] == ["git", "clone"]:
            subdir.mkdir(parents=True, exist_ok=True)
            (subdir / "Dockerfile").write_text("FROM scratch\\n", encoding="utf-8")
        return "ok"

    monkeypatch.setattr("mcpgateway.runtimes.docker_backend.tempfile.TemporaryDirectory", lambda prefix: _TempDir())
    monkeypatch.setattr(backend, "_run", _fake_run)

    await backend._build_image_from_github(
        RuntimeBackendDeployRequest(
            runtime_id="22345678-1234-1234-1234-123456789abc",
            name="github-runtime-subdir",
            source_type="github",
            source={
                "type": "github",
                "repo": "acme/runtime",
                "branch": "main",
                "dockerfile": "mcp-servers/go/fast-time-server/Dockerfile",
            },
        )
    )

    build_cmd = next(cmd for cmd in calls if len(cmd) > 1 and cmd[1] == "build")
    dockerfile_arg = build_cmd[build_cmd.index("-f") + 1]
    assert Path(dockerfile_arg) == (subdir / "Dockerfile").resolve()
    assert Path(build_cmd[-1]) == subdir.resolve()


@pytest.mark.asyncio
async def test_docker_backend_deploy_ignores_k8s_seccomp_and_missing_apparmor(monkeypatch):
    backend = DockerRuntimeBackend(docker_binary="docker")
    seen_run_cmd: list[str] = []

    async def _fake_run(cmd, timeout=300):  # noqa: ANN001
        if len(cmd) >= 2 and cmd[1] == "run":
            seen_run_cmd.extend(cmd)
            return "container-123\n"
        if len(cmd) >= 2 and cmd[1] == "port":
            raise RuntimeBackendError("no published ports")
        return ""

    monkeypatch.setattr(backend, "_run", _fake_run)
    monkeypatch.setattr(backend, "_apparmor_profile_available", lambda _profile: False)

    result = await backend.deploy(
        RuntimeBackendDeployRequest(
            runtime_id="runtime-12345678",
            name="runtime-name",
            source_type="docker",
            source={"type": "docker", "image": "ghcr.io/ibm/fast-time-server:0.8.0"},
            guardrails={
                "seccomp": "runtime/default",
                "apparmor": "mcp-standard",
                "capabilities": {"drop_all": True, "add": []},
                "filesystem": {"read_only_root": True},
                "network": {"egress_allowed": True},
            },
        )
    )

    warning_fields = {warning.get("field") for warning in result.warnings}
    assert "guardrails.seccomp" in warning_fields
    assert "guardrails.apparmor" in warning_fields
    assert "seccomp=runtime/default" not in seen_run_cmd
    assert "apparmor=mcp-standard" not in seen_run_cmd


@pytest.mark.asyncio
async def test_docker_backend_deploy_uses_ingress_ports_for_endpoint_resolution(monkeypatch):
    backend = DockerRuntimeBackend(docker_binary="docker", default_network="runtime-net")
    run_commands: list[list[str]] = []

    async def _fake_run(cmd, timeout=300):  # noqa: ANN001
        run_commands.append(cmd)
        if len(cmd) >= 2 and cmd[1] == "run":
            return "container-789\n"
        if len(cmd) >= 2 and cmd[1] == "port":
            raise RuntimeBackendError("no published ports")
        return ""

    monkeypatch.setattr(backend, "_run", _fake_run)

    result = await backend.deploy(
        RuntimeBackendDeployRequest(
            runtime_id="12345678-1234-1234-1234-123456789abc",
            name="runtime-name",
            source_type="docker",
            source={"type": "docker", "image": "ghcr.io/ibm/fast-time-server:0.8.0"},
            guardrails={
                "capabilities": {"drop_all": True, "add": []},
                "filesystem": {"read_only_root": True},
                "network": {"egress_allowed": True, "ingress_ports": [8080]},
            },
        )
    )

    run_invocation = next(cmd for cmd in run_commands if len(cmd) >= 2 and cmd[1] == "run")
    assert "--network" in run_invocation
    assert "runtime-net" in run_invocation
    assert "-p" in run_invocation
    assert "127.0.0.1::8080" in run_invocation
    assert result.endpoint_url == "http://mcpruntime-runtime-name-12345678:8080"
    assert result.backend_response["network"] == "runtime-net"
    assert result.backend_response["ingress_ports"] == [8080]


@pytest.mark.asyncio
async def test_docker_backend_deploy_uses_metadata_endpoint_port_override(monkeypatch):
    backend = DockerRuntimeBackend(docker_binary="docker", default_network="runtime-net")
    run_commands: list[list[str]] = []

    async def _fake_run(cmd, timeout=300):  # noqa: ANN001
        run_commands.append(cmd)
        if len(cmd) >= 2 and cmd[1] == "run":
            return "container-321\n"
        if len(cmd) >= 2 and cmd[1] == "port":
            raise RuntimeBackendError("no published ports")
        return ""

    monkeypatch.setattr(backend, "_run", _fake_run)

    result = await backend.deploy(
        RuntimeBackendDeployRequest(
            runtime_id="c0ffee00-1234-1234-1234-123456789abc",
            name="runtime-name",
            source_type="docker",
            source={"type": "docker", "image": "ghcr.io/ibm/fast-time-server:0.8.0"},
            metadata={"endpoint_port": 9090},
            guardrails={
                "capabilities": {"drop_all": True, "add": []},
                "filesystem": {"read_only_root": True},
                "network": {"egress_allowed": True},
            },
        )
    )

    run_invocation = next(cmd for cmd in run_commands if len(cmd) >= 2 and cmd[1] == "run")
    assert "127.0.0.1::9090" in run_invocation
    assert result.endpoint_url == "http://mcpruntime-runtime-name-c0ffee00:9090"
    assert result.backend_response["endpoint_port"] == 9090


@pytest.mark.asyncio
async def test_docker_backend_deploy_retries_without_missing_network(monkeypatch):
    backend = DockerRuntimeBackend(
        docker_binary="docker",
        default_network="missing-network",
    )
    run_commands: list[list[str]] = []

    async def _fake_run(cmd, timeout=300):  # noqa: ANN001
        run_commands.append(cmd)
        if len(cmd) >= 2 and cmd[1] == "rm":
            return ""
        if len(cmd) >= 2 and cmd[1] == "run" and "--network" in cmd:
            raise RuntimeBackendError("Command failed (125): docker run ... network missing-network not found")
        if len(cmd) >= 2 and cmd[1] == "run":
            return "container-456\n"
        if len(cmd) >= 2 and cmd[1] == "port":
            raise RuntimeBackendError("no published ports")
        return ""

    monkeypatch.setattr(backend, "_run", _fake_run)
    monkeypatch.setattr(backend, "_detect_gateway_network", AsyncMock(return_value=None))

    result = await backend.deploy(
        RuntimeBackendDeployRequest(
            runtime_id="runtime-abcdef12",
            name="runtime-name",
            source_type="docker",
            source={"type": "docker", "image": "ghcr.io/ibm/fast-time-server:0.8.0"},
            guardrails={
                "capabilities": {"drop_all": True, "add": []},
                "filesystem": {"read_only_root": True},
                "network": {"egress_allowed": True},
            },
        )
    )

    run_invocations = [cmd for cmd in run_commands if len(cmd) >= 2 and cmd[1] == "run"]
    rm_invocations = [cmd for cmd in run_commands if len(cmd) >= 2 and cmd[1] == "rm"]
    assert len(run_invocations) == 2
    assert len(rm_invocations) == 1
    assert "--network" in run_invocations[0]
    assert "--network" not in run_invocations[1]
    assert any(warning.get("field") == "guardrails.network" for warning in result.warnings)


@pytest.mark.asyncio
async def test_docker_backend_deploy_retries_with_detected_gateway_network(monkeypatch):
    backend = DockerRuntimeBackend(
        docker_binary="docker",
        default_network="missing-network",
    )
    run_commands: list[list[str]] = []

    async def _fake_run(cmd, timeout=300):  # noqa: ANN001
        run_commands.append(cmd)
        if len(cmd) >= 2 and cmd[1] == "rm":
            return ""
        if len(cmd) >= 2 and cmd[1] == "run" and "missing-network" in cmd:
            raise RuntimeBackendError("Command failed (125): docker run ... network missing-network not found")
        if len(cmd) >= 2 and cmd[1] == "run":
            return "container-999\n"
        if len(cmd) >= 2 and cmd[1] == "port":
            raise RuntimeBackendError("no published ports")
        return ""

    monkeypatch.setattr(backend, "_run", _fake_run)
    monkeypatch.setattr(backend, "_detect_gateway_network", AsyncMock(return_value="mcp-context-forge_mcpnet"))

    result = await backend.deploy(
        RuntimeBackendDeployRequest(
            runtime_id="abcdef12-1234-1234-1234-123456789abc",
            name="runtime-name",
            source_type="docker",
            source={"type": "docker", "image": "ghcr.io/ibm/fast-time-server:0.8.0"},
            guardrails={
                "capabilities": {"drop_all": True, "add": []},
                "filesystem": {"read_only_root": True},
                "network": {"egress_allowed": True, "ingress_ports": [8080]},
            },
        )
    )

    run_invocations = [cmd for cmd in run_commands if len(cmd) >= 2 and cmd[1] == "run"]
    assert len(run_invocations) == 2
    assert "missing-network" in run_invocations[0]
    assert "mcp-context-forge_mcpnet" in run_invocations[1]
    assert result.backend_response["network"] == "mcp-context-forge_mcpnet"
    assert result.endpoint_url == "http://mcpruntime-runtime-name-abcdef12:8080"
    warning_messages = [warning.get("message", "") for warning in result.warnings if warning.get("field") == "guardrails.network"]
    assert any("gateway network" in message for message in warning_messages)
