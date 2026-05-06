# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_runtime_admin_router.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for ``mcpgateway.routers.runtime_admin_router``.

The endpoints are decorated with ``@require_permission("admin.system_config")``,
which calls ``PermissionService(db).check_permission(...)``. We patch the
``PermissionService`` class in ``mcpgateway.middleware.rbac`` to return the
desired allow/deny outcome and exercise the endpoint functions directly.
"""

# Standard
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# Third-Party
from fastapi import HTTPException
import pytest

# First-Party
from mcpgateway.routers import runtime_admin_router as router_module
from mcpgateway.runtime_state import (
    reset_runtime_state_coordinator_for_tests,
    reset_runtime_state_for_tests,
)


@pytest.fixture(autouse=True)
def _reset_singletons():
    reset_runtime_state_for_tests()
    reset_runtime_state_coordinator_for_tests()
    yield
    reset_runtime_state_for_tests()
    reset_runtime_state_coordinator_for_tests()


@pytest.fixture
def admin_user():
    return {"email": "admin@example.com", "is_admin": True, "ip_address": "127.0.0.1", "user_agent": "tests"}


@pytest.fixture
def non_admin_user():
    return {"email": "user@example.com", "is_admin": False, "ip_address": "127.0.0.1", "user_agent": "tests"}


@pytest.fixture
def db_session():
    return MagicMock()


@pytest.fixture
def request_no_proxy():
    """Build a minimal Request stand-in whose headers don't trip the reverse-proxy WARN."""
    req = MagicMock()
    req.headers = {}
    return req


@pytest.fixture
def request_via_proxy():
    """Build a Request stand-in carrying X-Forwarded-For so the reverse-proxy WARN fires."""
    req = MagicMock()
    req.headers = {"x-forwarded-for": "203.0.113.1"}
    return req


@pytest.fixture
def allow_admin(monkeypatch: pytest.MonkeyPatch):
    """Patch PermissionService so check_permission always returns True."""

    class AllowAll:
        def __init__(self, _db):
            pass

        async def check_permission(self, **_kwargs):
            return True

    monkeypatch.setattr("mcpgateway.middleware.rbac.PermissionService", AllowAll)


@pytest.fixture
def deny_all(monkeypatch: pytest.MonkeyPatch):
    """Patch PermissionService so check_permission always returns False."""

    class DenyAll:
        def __init__(self, _db):
            pass

        async def check_permission(self, **_kwargs):
            return False

    monkeypatch.setattr("mcpgateway.middleware.rbac.PermissionService", DenyAll)


def _set_mcp_settings(monkeypatch: pytest.MonkeyPatch, *, runtime: bool, session_auth: bool = False, all_cores: bool = False) -> None:
    """Apply the MCP-side settings combination that the boot-mode helpers derive labels from."""
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_mcp_runtime_enabled", runtime, raising=False)
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_mcp_session_auth_reuse_enabled", session_auth, raising=False)
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_mcp_session_core_enabled", all_cores, raising=False)
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_mcp_event_store_enabled", all_cores, raising=False)
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_mcp_resume_core_enabled", all_cores, raising=False)
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_mcp_live_stream_core_enabled", all_cores, raising=False)
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_mcp_affinity_core_enabled", all_cores, raising=False)


def _set_a2a_settings(monkeypatch: pytest.MonkeyPatch, *, runtime: bool, delegate: bool = False) -> None:
    """Apply the A2A-side settings combination."""
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_a2a_runtime_enabled", runtime, raising=False)
    monkeypatch.setattr("mcpgateway.config.settings.experimental_rust_a2a_runtime_delegate_enabled", delegate, raising=False)


@pytest.fixture
def edge_boot(monkeypatch: pytest.MonkeyPatch):
    """Make both runtimes look like ``edge`` boot (runtime + safety flag, no extra cores)."""
    _set_mcp_settings(monkeypatch, runtime=True, session_auth=True, all_cores=False)
    _set_a2a_settings(monkeypatch, runtime=True, delegate=True)
    monkeypatch.setattr(router_module.version_module, "current_mcp_transport_mount", lambda: "rust")
    monkeypatch.setattr(router_module.version_module, "should_delegate_a2a_to_rust", lambda: True)


@pytest.fixture
def off_boot(monkeypatch: pytest.MonkeyPatch):
    """Make both runtimes look like ``off`` boot (no Rust runtime enabled)."""
    _set_mcp_settings(monkeypatch, runtime=False)
    _set_a2a_settings(monkeypatch, runtime=False)
    monkeypatch.setattr(router_module.version_module, "current_mcp_transport_mount", lambda: "python")
    monkeypatch.setattr(router_module.version_module, "should_delegate_a2a_to_rust", lambda: False)


@pytest.fixture
def full_boot(monkeypatch: pytest.MonkeyPatch):
    """Make the MCP runtime look like ``full`` boot (runtime + safety flag + all cores). A2A stays edge."""
    _set_mcp_settings(monkeypatch, runtime=True, session_auth=True, all_cores=True)
    _set_a2a_settings(monkeypatch, runtime=True, delegate=True)
    monkeypatch.setattr(router_module.version_module, "current_mcp_transport_mount", lambda: "rust")
    monkeypatch.setattr(router_module.version_module, "should_delegate_a2a_to_rust", lambda: True)


@pytest.fixture
def shadow_boot(monkeypatch: pytest.MonkeyPatch):
    """Make both runtimes look like ``shadow`` boot (runtime enabled, safety flag NOT set).

    The router must accept ``mode=shadow`` (escape hatch) but reject
    ``mode=edge`` because the safety invariant requires the
    session-auth-reuse / delegate-enabled flag.
    """
    _set_mcp_settings(monkeypatch, runtime=True, session_auth=False, all_cores=False)
    _set_a2a_settings(monkeypatch, runtime=True, delegate=False)
    monkeypatch.setattr(router_module.version_module, "current_mcp_transport_mount", lambda: "python")
    monkeypatch.setattr(router_module.version_module, "should_delegate_a2a_to_rust", lambda: False)


# ---------------------------------------------------------------------------
# GET endpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_mcp_mode_returns_state(allow_admin, edge_boot, admin_user):
    payload = await router_module.get_mcp_mode(user=admin_user)
    assert payload["runtime"] == "mcp"
    assert payload["boot_mode"] == "edge"
    assert payload["effective_mode"] == "edge"
    assert payload["override_active"] is False
    assert payload["mounted"] == "rust"
    assert payload["supported_override_modes"] == ["edge", "shadow"]


@pytest.mark.asyncio
async def test_get_a2a_mode_returns_state(allow_admin, edge_boot, admin_user):
    payload = await router_module.get_a2a_mode(user=admin_user)
    assert payload["runtime"] == "a2a"
    assert payload["boot_mode"] == "edge"
    assert payload["invoke_mode"] == "rust"
    assert payload["override_active"] is False


# ---------------------------------------------------------------------------
# PATCH happy paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_mcp_mode_flips_to_shadow(allow_admin, edge_boot, admin_user, db_session, request_no_proxy, monkeypatch: pytest.MonkeyPatch):
    audit = MagicMock()
    monkeypatch.setattr(router_module, "get_security_logger", lambda: audit)

    body = router_module.RuntimeModeUpdate(mode="shadow")
    payload = await router_module.patch_mcp_mode(body, request=request_no_proxy, user=admin_user, db=db_session)

    assert payload["effective_mode"] == "shadow"
    assert payload["override_active"] is True
    audit.log_data_access.assert_called_once()
    call = audit.log_data_access.call_args.kwargs
    assert call["resource_type"] == "runtime_config"
    assert call["resource_id"] == "mcp_mode"
    assert call["new_values"]["mode"] == "shadow"


@pytest.mark.asyncio
async def test_patch_a2a_mode_flips_to_shadow(allow_admin, edge_boot, admin_user, db_session, request_no_proxy, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(router_module, "get_security_logger", MagicMock)
    body = router_module.RuntimeModeUpdate(mode="shadow")
    payload = await router_module.patch_a2a_mode(body, request=request_no_proxy, user=admin_user, db=db_session)
    assert payload["effective_mode"] == "shadow"
    assert payload["override_active"] is True


# ---------------------------------------------------------------------------
# Validation: 400 / 409
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_mcp_mode_rejects_unsupported_mode_at_pydantic_layer():
    # Pydantic Literal["shadow", "edge"] rejects "off" at construction time.
    with pytest.raises(Exception):
        router_module.RuntimeModeUpdate(mode="off")


@pytest.mark.asyncio
async def test_patch_mcp_mode_409_when_boot_mode_off(allow_admin, off_boot, admin_user, db_session, request_no_proxy, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(router_module, "get_security_logger", MagicMock)
    body = router_module.RuntimeModeUpdate(mode="edge")
    with pytest.raises(HTTPException) as exc:
        await router_module.patch_mcp_mode(body, request=request_no_proxy, user=admin_user, db=db_session)
    assert exc.value.status_code == 409
    # Recommendation must be 'shadow' or 'edge' — must NOT recommend 'full',
    # which would just trade NO_DISPATCHER for BOOT_FULL_STRANDS.
    assert "'shadow' or 'edge'" in exc.value.detail
    assert "'full'" not in exc.value.detail


@pytest.mark.asyncio
async def test_patch_a2a_mode_409_when_boot_mode_off(allow_admin, off_boot, admin_user, db_session, request_no_proxy, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(router_module, "get_security_logger", MagicMock)
    body = router_module.RuntimeModeUpdate(mode="edge")
    with pytest.raises(HTTPException) as exc:
        await router_module.patch_a2a_mode(body, request=request_no_proxy, user=admin_user, db=db_session)
    assert exc.value.status_code == 409
    # A2A has no 'full' mode at all — the recommendation must not mention it.
    assert "'shadow' or 'edge'" in exc.value.detail
    assert "'full'" not in exc.value.detail


@pytest.mark.asyncio
async def test_patch_mcp_mode_409_when_boot_mode_full(allow_admin, full_boot, admin_user, db_session, request_no_proxy, monkeypatch: pytest.MonkeyPatch):
    """boot_mode=full mounts a plain RustMCPRuntimeProxy with no dispatcher; flips would silently no-op."""
    monkeypatch.setattr(router_module, "get_security_logger", MagicMock)
    body = router_module.RuntimeModeUpdate(mode="shadow")
    with pytest.raises(HTTPException) as exc:
        await router_module.patch_mcp_mode(body, request=request_no_proxy, user=admin_user, db=db_session)
    assert exc.value.status_code == 409
    assert "Full-boot" in exc.value.detail


@pytest.mark.asyncio
async def test_patch_mcp_mode_edge_409_when_boot_mode_full(allow_admin, full_boot, admin_user, db_session, request_no_proxy, monkeypatch: pytest.MonkeyPatch):
    """Symmetric: mode=edge on boot=full also 409s. The dispatcher check beats the edge-safety check today,
    but a refactor that reorders the gates could regress silently — pin both target modes against full-boot.
    """
    monkeypatch.setattr(router_module, "get_security_logger", MagicMock)
    body = router_module.RuntimeModeUpdate(mode="edge")
    with pytest.raises(HTTPException) as exc:
        await router_module.patch_mcp_mode(body, request=request_no_proxy, user=admin_user, db=db_session)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_patch_mcp_mode_409_when_boot_mode_shadow(allow_admin, shadow_boot, admin_user, db_session, request_no_proxy, monkeypatch: pytest.MonkeyPatch):
    """Safety invariant: boot=shadow didn't opt into session-auth-reuse, so edge override can't take effect."""
    monkeypatch.setattr(router_module, "get_security_logger", MagicMock)
    body = router_module.RuntimeModeUpdate(mode="edge")
    with pytest.raises(HTTPException) as exc:
        await router_module.patch_mcp_mode(body, request=request_no_proxy, user=admin_user, db=db_session)
    assert exc.value.status_code == 409
    assert "shadow" in exc.value.detail
    assert "experimental_rust_mcp_session_auth_reuse_enabled" in exc.value.detail


@pytest.mark.asyncio
async def test_patch_a2a_mode_409_when_boot_mode_shadow(allow_admin, shadow_boot, admin_user, db_session, request_no_proxy, monkeypatch: pytest.MonkeyPatch):
    """Safety invariant (A2A): boot=shadow didn't opt into delegate-enabled."""
    monkeypatch.setattr(router_module, "get_security_logger", MagicMock)
    body = router_module.RuntimeModeUpdate(mode="edge")
    with pytest.raises(HTTPException) as exc:
        await router_module.patch_a2a_mode(body, request=request_no_proxy, user=admin_user, db=db_session)
    assert exc.value.status_code == 409
    assert "shadow" in exc.value.detail


@pytest.mark.asyncio
async def test_patch_mcp_mode_shadow_clears_stale_override_on_shadow_boot(allow_admin, shadow_boot, admin_user, db_session, request_no_proxy, monkeypatch: pytest.MonkeyPatch):
    """Escape hatch: mode=shadow must be accepted on a shadow-boot deployment even when state
    holds a stale override=edge inherited from a prior edge-boot via Redis hint. Without this,
    the admin API cannot clear lingering state and the operator has to flush Redis manually.
    """
    # First-Party
    from mcpgateway.runtime_state import OverrideMode, get_runtime_state

    monkeypatch.setattr(router_module, "get_security_logger", MagicMock)

    # Simulate a stale override=edge landing in state (e.g. via a hint written
    # by a former edge-boot pod, replayed when this shadow-boot pod started).
    state = get_runtime_state()
    await state.apply_local("mcp", "edge", initiator_user="prior-edge-boot", version=7)
    assert state.override_mode("mcp") == OverrideMode.EDGE

    coordinator = MagicMock()
    coordinator.next_version = AsyncMock(return_value=8)
    coordinator.publish = AsyncMock(return_value=True)
    coordinator.cluster_propagation_enabled = True
    monkeypatch.setattr(router_module, "get_runtime_state_coordinator", lambda: coordinator)

    body = router_module.RuntimeModeUpdate(mode="shadow")
    payload = await router_module.patch_mcp_mode(body, request=request_no_proxy, user=admin_user, db=db_session)

    # The flip succeeded: override is now shadow, publish was called.
    assert state.override_mode("mcp") == OverrideMode.SHADOW
    assert state.version("mcp") == 8
    assert payload["override_active"] is True
    assert payload["effective_mode"] == "shadow"
    coordinator.publish.assert_awaited_once()


# ---------------------------------------------------------------------------
# 403: non-admin without the required permission
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_mcp_mode_403_when_permission_denied(deny_all, edge_boot, non_admin_user, db_session, request_no_proxy, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(router_module, "get_security_logger", MagicMock)
    body = router_module.RuntimeModeUpdate(mode="shadow")
    # is_admin must be false so allow_admin_bypass doesn't shortcut the check.
    with pytest.raises(HTTPException) as exc:
        await router_module.patch_mcp_mode(body, request=request_no_proxy, user=non_admin_user, db=db_session)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_patch_mcp_mode_publishes_via_coordinator(allow_admin, edge_boot, admin_user, db_session, request_no_proxy, monkeypatch: pytest.MonkeyPatch):
    """A successful flip with publish ok and Redis attached reports propagated.

    Also pins the ModeChange payload shape passed to coordinator.publish so a
    future refactor that swaps argument order or drops a field is caught.
    """
    from mcpgateway.runtime_state import OverrideMode, RuntimeKind

    monkeypatch.setattr(router_module, "get_security_logger", MagicMock)
    coordinator = MagicMock()
    coordinator.next_version = AsyncMock(return_value=42)
    coordinator.publish = AsyncMock(return_value=True)
    coordinator.cluster_propagation_enabled = True
    monkeypatch.setattr(router_module, "get_runtime_state_coordinator", lambda: coordinator)

    body = router_module.RuntimeModeUpdate(mode="shadow")
    payload = await router_module.patch_mcp_mode(body, request=request_no_proxy, user=admin_user, db=db_session)

    coordinator.next_version.assert_awaited_once()
    coordinator.publish.assert_awaited_once()
    published = coordinator.publish.await_args.args[0]
    assert published.runtime == RuntimeKind.MCP
    assert published.mode == OverrideMode.SHADOW
    assert published.version == 42
    assert published.initiator_user == admin_user["email"]
    assert payload["override_version"] == 42
    assert payload["publish_status"] == "propagated"
    assert payload["audit_persisted"] is True


@pytest.mark.asyncio
async def test_patch_mcp_mode_reports_publish_failure(allow_admin, edge_boot, admin_user, db_session, request_no_proxy, monkeypatch: pytest.MonkeyPatch):
    """A publish failure surfaces as publish_status=failed but the local flip still succeeds."""
    monkeypatch.setattr(router_module, "get_security_logger", MagicMock)
    coordinator = MagicMock()
    coordinator.next_version = AsyncMock(return_value=7)
    coordinator.publish = AsyncMock(return_value=False)
    coordinator.cluster_propagation_enabled = True
    monkeypatch.setattr(router_module, "get_runtime_state_coordinator", lambda: coordinator)

    body = router_module.RuntimeModeUpdate(mode="shadow")
    payload = await router_module.patch_mcp_mode(body, request=request_no_proxy, user=admin_user, db=db_session)

    assert payload["override_active"] is True
    assert payload["effective_mode"] == "shadow"
    assert payload["publish_status"] == "failed"


@pytest.mark.asyncio
async def test_patch_mcp_mode_503_when_incr_unavailable(allow_admin, edge_boot, admin_user, db_session, request_no_proxy, monkeypatch: pytest.MonkeyPatch):
    """When Redis INCR cannot allocate a safe version, the PATCH must fail closed (503)."""
    from mcpgateway.runtime_state import RuntimeStateError

    monkeypatch.setattr(router_module, "get_security_logger", MagicMock)
    coordinator = MagicMock()
    coordinator.next_version = AsyncMock(side_effect=RuntimeStateError("INCR failed"))
    coordinator.publish = AsyncMock(return_value=True)
    monkeypatch.setattr(router_module, "get_runtime_state_coordinator", lambda: coordinator)

    body = router_module.RuntimeModeUpdate(mode="shadow")
    with pytest.raises(HTTPException) as exc:
        await router_module.patch_mcp_mode(body, request=request_no_proxy, user=admin_user, db=db_session)
    assert exc.value.status_code == 503
    coordinator.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_patch_mcp_mode_audit_failure_does_not_block_flip(allow_admin, edge_boot, admin_user, db_session, request_no_proxy, monkeypatch: pytest.MonkeyPatch):
    """A SQLAlchemyError in audit logging must NOT roll back the override."""
    from sqlalchemy.exc import SQLAlchemyError

    audit = MagicMock()
    audit.log_data_access.side_effect = SQLAlchemyError("db down")
    monkeypatch.setattr(router_module, "get_security_logger", lambda: audit)

    body = router_module.RuntimeModeUpdate(mode="shadow")
    payload = await router_module.patch_mcp_mode(body, request=request_no_proxy, user=admin_user, db=db_session)

    assert payload["override_active"] is True
    assert payload["effective_mode"] == "shadow"
    assert payload["audit_persisted"] is False


@pytest.mark.asyncio
async def test_patch_mcp_mode_non_db_audit_failure_does_not_block_flip(allow_admin, edge_boot, admin_user, db_session, request_no_proxy, monkeypatch: pytest.MonkeyPatch):
    """Non-SQLAlchemy audit failures (network sink, AttributeError, etc.) must also NOT break the response."""
    audit = MagicMock()
    audit.log_data_access.side_effect = AttributeError("misconfigured logger")
    monkeypatch.setattr(router_module, "get_security_logger", lambda: audit)

    body = router_module.RuntimeModeUpdate(mode="shadow")
    payload = await router_module.patch_mcp_mode(body, request=request_no_proxy, user=admin_user, db=db_session)

    assert payload["override_active"] is True
    assert payload["effective_mode"] == "shadow"
    assert payload["audit_persisted"] is False
    assert payload["publish_status"] in ("propagated", "local-only")


@pytest.mark.asyncio
async def test_patch_mcp_mode_superseded_path_writes_audit_and_returns_status(allow_admin, edge_boot, admin_user, db_session, request_no_proxy, monkeypatch: pytest.MonkeyPatch):
    """Race-loser PATCH must surface publish_status=superseded AND write a success=False audit row."""
    audit = MagicMock()
    monkeypatch.setattr(router_module, "get_security_logger", lambda: audit)

    # Pre-load state with a higher version so the next apply_local returns None.
    from mcpgateway.runtime_state import get_runtime_state

    await get_runtime_state().apply_local("mcp", "edge", initiator_user="winner", version=100)

    coordinator = MagicMock()
    # next_version returns a value LOWER than the pre-applied 100, so apply_local drops it.
    coordinator.next_version = AsyncMock(return_value=50)
    coordinator.publish = AsyncMock(return_value=True)
    coordinator.cluster_propagation_enabled = True
    monkeypatch.setattr(router_module, "get_runtime_state_coordinator", lambda: coordinator)

    body = router_module.RuntimeModeUpdate(mode="shadow")
    payload = await router_module.patch_mcp_mode(body, request=request_no_proxy, user=admin_user, db=db_session)

    assert payload["publish_status"] == "superseded"
    coordinator.publish.assert_not_awaited()
    audit.log_data_access.assert_called_once()
    audit_kwargs = audit.log_data_access.call_args.kwargs
    assert audit_kwargs["success"] is False
    assert audit_kwargs["additional_context"]["outcome"] == "superseded"
    assert audit_kwargs["additional_context"]["attempted_version"] == 50
    assert audit_kwargs["additional_context"]["superseded_by_version"] == 100
    assert audit_kwargs["additional_context"]["superseded_by_mode"] == "edge"


# ---------------------------------------------------------------------
# _warn_if_behind_reverse_proxy — diagnostic for non-nginx reverse-proxy
# topologies where the proxy itself won't follow the override.
# ---------------------------------------------------------------------


def test_warn_if_behind_reverse_proxy_logs_when_xforward_headers_detected(caplog):
    """A PATCH that arrives via a reverse proxy (X-Forwarded-* present) gets a warning naming the headers."""
    # First-Party
    from mcpgateway.routers.runtime_admin_router import _warn_if_behind_reverse_proxy
    from mcpgateway.runtime_state import RuntimeKind

    request = SimpleNamespace(headers={"x-forwarded-for": "10.0.0.1", "x-forwarded-proto": "https"})
    caplog.set_level("WARNING", logger="mcpgateway.routers.runtime_admin_router")
    _warn_if_behind_reverse_proxy(request, runtime=RuntimeKind.MCP)

    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert any("reverse proxy" in w.message for w in warnings), [w.message for w in warnings]
    assert any("x-forwarded-for" in w.message and "x-forwarded-proto" in w.message for w in warnings)


def test_warn_if_behind_reverse_proxy_silent_when_no_forwarded_headers(caplog):
    """No X-Forwarded-* present → no warning (silent path covers the early return)."""
    # First-Party
    from mcpgateway.routers.runtime_admin_router import _warn_if_behind_reverse_proxy
    from mcpgateway.runtime_state import RuntimeKind

    request = SimpleNamespace(headers={"content-type": "application/json"})
    caplog.set_level("WARNING", logger="mcpgateway.routers.runtime_admin_router")
    _warn_if_behind_reverse_proxy(request, runtime=RuntimeKind.MCP)
    assert [r for r in caplog.records if "reverse proxy" in r.message] == []


def test_warn_if_behind_reverse_proxy_handles_missing_headers_attribute(caplog):
    """A request stub without a ``headers`` attribute hits the defensive early return without raising."""
    # First-Party
    from mcpgateway.routers.runtime_admin_router import _warn_if_behind_reverse_proxy
    from mcpgateway.runtime_state import RuntimeKind

    caplog.set_level("WARNING", logger="mcpgateway.routers.runtime_admin_router")
    # Build an object that explicitly lacks ``headers`` — getattr returns None,
    # the function returns immediately with no warning.
    request = SimpleNamespace()
    request.headers = None
    _warn_if_behind_reverse_proxy(request, runtime=RuntimeKind.MCP)
    assert [r for r in caplog.records if "reverse proxy" in r.message] == []
