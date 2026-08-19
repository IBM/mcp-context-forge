# -*- coding: utf-8 -*-
"""Router and middleware tests for asynchronous tool jobs."""

# Standard
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# Third-Party
from fastapi import APIRouter, HTTPException
import pytest
from pydantic import ValidationError
from starlette.requests import Request

# First-Party
from mcpgateway.api.v1 import build_v1_router
from mcpgateway.config import get_settings, settings
from mcpgateway.middleware.token_scoping import TokenScopingMiddleware
from mcpgateway.routers import async_jobs
from mcpgateway.schemas_async_jobs import AsyncToolJobCreate
from mcpgateway.services.async_job_service import AsyncJobNotFoundError, AsyncJobPayloadTooLargeError, AsyncJobQueueFullError, AsyncJobSnapshot
from tests.helpers.router_helpers import collect_routes


def _request(path: str = "/v1/jobs/tool-invocations", *, extra_headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    """Build a minimal HTTP request for direct handler tests."""
    headers = [(b"authorization", b"Bearer private"), *(extra_headers or [])]
    return Request({"type": "http", "method": "POST", "path": path, "headers": headers})


def _snapshot(status: str = "queued", *, result: dict | None = None) -> AsyncJobSnapshot:
    """Build a valid service response without exposing owner fields."""
    # Standard
    from datetime import datetime, timezone

    return AsyncJobSnapshot(
        id="job-1",
        tool_id="tool-1",
        tool_name="demo-tool",
        status=status,
        timeout_seconds=60,
        created_at=datetime.now(timezone.utc),
        started_at=None,
        finished_at=None,
        duration_ms=None,
        result=result,
        error=None,
    )


def _empty_router_kwargs() -> dict[str, APIRouter]:
    """Return the inline routers required by the v1 factory."""
    return {
        name: APIRouter()
        for name in (
            "protocol_router",
            "tool_router",
            "resource_router",
            "prompt_router",
            "gateway_router",
            "root_router",
            "server_router",
            "metrics_router",
            "tag_router",
            "export_import_router",
            "a2a_router",
        )
    }


def test_router_is_feature_flagged_and_versioned():
    enabled = settings.model_copy(update={"mcpgateway_async_jobs_enabled": True})
    disabled = settings.model_copy(update={"mcpgateway_async_jobs_enabled": False})

    enabled_paths = [path for path, *_rest in collect_routes(build_v1_router(enabled, **_empty_router_kwargs()))]
    disabled_paths = [path for path, *_rest in collect_routes(build_v1_router(disabled, **_empty_router_kwargs()))]

    assert "/v1/jobs/tool-invocations" in enabled_paths
    assert "/v1/jobs/tool-invocations" not in disabled_paths


def test_feature_is_disabled_by_default_and_direct_guard_returns_404(monkeypatch):
    assert type(get_settings()).model_fields["mcpgateway_async_jobs_enabled"].default is False
    monkeypatch.setattr(settings, "mcpgateway_async_jobs_enabled", False)

    with pytest.raises(HTTPException) as exc_info:
        async_jobs._require_async_jobs_enabled()  # pylint: disable=protected-access

    assert exc_info.value.status_code == 404


def test_client_cannot_supply_owner_identity():
    with pytest.raises(ValidationError):
        AsyncToolJobCreate(tool_id="tool-1", owner_email="attacker@example.com")


def test_token_scoping_requires_tools_execute_for_submit_read_and_cancel():
    middleware = TokenScopingMiddleware()

    for method, path in (
        ("POST", "/v1/jobs/tool-invocations"),
        ("GET", "/v1/jobs/job-1"),
        ("POST", "/v1/jobs/job-1/cancel"),
    ):
        assert middleware._check_permission_restrictions(path, method, ["tools.execute"]) is True  # pylint: disable=protected-access
        assert middleware._check_permission_restrictions(path, method, ["tools.read"]) is False  # pylint: disable=protected-access

    assert middleware._check_server_restriction("/v1/jobs/tool-invocations", "server-1") is True  # pylint: disable=protected-access


@pytest.mark.asyncio
async def test_enqueue_forwards_canonical_owner_scope_without_exposing_auth(monkeypatch):
    monkeypatch.setattr(settings, "mcpgateway_async_jobs_enabled", True)
    monkeypatch.setattr(async_jobs, "_owner_context", lambda _request, _user: ("owner@example.com", "owner@example.com", ["team-1"], False))
    service = SimpleNamespace(enqueue_tool_invocation=AsyncMock(return_value=_snapshot()))
    monkeypatch.setattr(async_jobs, "get_async_job_service", lambda: service)

    request = _request(extra_headers=[(b"cookie", b"jwt_token=browser-secret")])
    request.state.auth_method = "api_token"
    request.state.jti = "jti-1"
    request.state.token_scopes = ["tools.execute"]
    request.state._jwt_verified_payload = ("private", {"jti": "jti-1", "exp": "2000000000", "scopes": {"server_id": "server-1"}})
    response = await async_jobs.enqueue_tool_invocation.__wrapped__(  # pylint: disable=no-member
        AsyncToolJobCreate(tool_id="tool-1", arguments={"value": 1}, headers={"x-extra": "ok"}),
        request,
        db=MagicMock(),
        user={"email": "owner@example.com", "ip_address": "192.0.2.10", "user_agent": "async-client/1.0"},
    )

    assert response.id == "job-1"
    call = service.enqueue_tool_invocation.await_args
    assert call.kwargs["owner_email"] == "owner@example.com"
    assert call.kwargs["token_teams"] == ["team-1"]
    assert call.kwargs["auth_method"] == "api_token"
    assert call.kwargs["token_jti"] == "jti-1"
    assert call.kwargs["token_scopes"] == ["tools.execute"]
    assert call.kwargs["token_server_id"] == "server-1"
    assert call.kwargs["token_expires_at"].timestamp() == 2_000_000_000
    assert call.kwargs["policy_client_host"] == "192.0.2.10"
    assert call.kwargs["policy_user_agent"] == "async-client/1.0"
    assert call.kwargs["request_headers"]["authorization"] == "Bearer private"
    assert call.kwargs["request_headers"]["x-extra"] == "ok"
    assert "cookie" not in call.kwargs["request_headers"]
    assert call.kwargs["supplemental_header_names"] == ["x-extra"]
    assert not hasattr(response, "request_headers")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field_name,header_name",
    [
        ("headers", "Authorization"),
        ("headers", "X-Api-Key"),
        ("headers", "X-Upstream-Authorization"),
        ("metadata", "authorization"),
        ("metadata", "X-ContextForge-Session-Validated"),
    ],
)
async def test_enqueue_rejects_sensitive_supplemental_credentials(monkeypatch, field_name, header_name):
    """Credentials supplied in the JSON body are never retained by the queue."""
    monkeypatch.setattr(settings, "mcpgateway_async_jobs_enabled", True)
    monkeypatch.setattr(async_jobs, "_owner_context", lambda _request, _user: ("owner@example.com", "owner@example.com", [], False))
    service = SimpleNamespace(enqueue_tool_invocation=AsyncMock(return_value=_snapshot()))
    monkeypatch.setattr(async_jobs, "get_async_job_service", lambda: service)
    body = {field_name: {header_name: "secret"}}

    with pytest.raises(HTTPException) as exc_info:
        await async_jobs.enqueue_tool_invocation.__wrapped__(  # pylint: disable=no-member
            AsyncToolJobCreate(tool_id="tool-1", **body),
            _request(),
            db=MagicMock(),
            user={"email": "owner@example.com"},
        )

    assert exc_info.value.status_code == 422
    service.enqueue_tool_invocation.assert_not_awaited()


def test_credential_context_fails_closed_for_malformed_exp_and_server_scope():
    """Malformed verified lifecycle claims cannot become unrestricted jobs."""
    for malformed_value in ("not-a-timestamp", True, None, {}):
        malformed_exp = _request()
        malformed_exp.state._jwt_verified_payload = ("token", {"exp": malformed_value})
        assert async_jobs._credential_context(malformed_exp)[2] == async_jobs.datetime.min.replace(tzinfo=async_jobs.timezone.utc)  # pylint: disable=protected-access

    malformed_server = _request()
    malformed_server.state._jwt_verified_payload = ("token", {"scopes": {"server_id": 123}})
    with pytest.raises(HTTPException) as exc_info:
        async_jobs._credential_context(malformed_server)  # pylint: disable=protected-access
    assert exc_info.value.status_code == 401

    malformed_token_scopes, malformed_scope_object, malformed_jti = (_request(), _request(), _request())
    malformed_token_scopes.state.token_scopes = "tools.execute"
    malformed_scope_object.state._jwt_verified_payload = ("token", {"scopes": ["server-1"]})
    malformed_jti.state._jwt_verified_payload = ("token", {"jti": "   "})
    for request in (malformed_token_scopes, malformed_scope_object, malformed_jti):
        with pytest.raises(HTTPException) as malformed_exc:
            async_jobs._credential_context(request)  # pylint: disable=protected-access
        assert malformed_exc.value.status_code == 401


@pytest.mark.asyncio
async def test_enqueue_maps_capacity_to_retryable_429(monkeypatch):
    monkeypatch.setattr(settings, "mcpgateway_async_jobs_enabled", True)
    monkeypatch.setattr(async_jobs, "_owner_context", lambda _request, _user: ("owner@example.com", "owner@example.com", [], False))
    service = SimpleNamespace(enqueue_tool_invocation=AsyncMock(side_effect=AsyncJobQueueFullError("Async job queue is full")))
    monkeypatch.setattr(async_jobs, "get_async_job_service", lambda: service)

    with pytest.raises(HTTPException) as exc_info:
        await async_jobs.enqueue_tool_invocation.__wrapped__(  # pylint: disable=no-member
            AsyncToolJobCreate(tool_id="tool-1"),
            _request(),
            db=MagicMock(),
            user={"email": "owner@example.com"},
        )

    assert exc_info.value.status_code == 429
    assert exc_info.value.headers == {"Retry-After": "1"}


@pytest.mark.asyncio
async def test_enqueue_maps_oversize_payload_to_413(monkeypatch):
    """Retained payload limits are reported without accepting the job."""
    monkeypatch.setattr(settings, "mcpgateway_async_jobs_enabled", True)
    monkeypatch.setattr(async_jobs, "_owner_context", lambda _request, _user: ("owner@example.com", "owner@example.com", [], False))
    service = SimpleNamespace(enqueue_tool_invocation=AsyncMock(side_effect=AsyncJobPayloadTooLargeError("payload too large")))
    monkeypatch.setattr(async_jobs, "get_async_job_service", lambda: service)

    with pytest.raises(HTTPException) as exc_info:
        await async_jobs.enqueue_tool_invocation.__wrapped__(  # pylint: disable=no-member
            AsyncToolJobCreate(tool_id="tool-1"),
            _request(),
            db=MagicMock(),
            user={"email": "owner@example.com"},
        )

    assert exc_info.value.status_code == 413


@pytest.mark.asyncio
async def test_cross_owner_lookup_is_hidden_as_404(monkeypatch):
    monkeypatch.setattr(settings, "mcpgateway_async_jobs_enabled", True)
    monkeypatch.setattr(async_jobs, "_owner_context", lambda _request, _user: ("other@example.com", "other@example.com", [], False))
    service = SimpleNamespace(get_job=AsyncMock(side_effect=AsyncJobNotFoundError("Job not found")))
    monkeypatch.setattr(async_jobs, "get_async_job_service", lambda: service)

    with pytest.raises(HTTPException) as exc_info:
        await async_jobs.get_job.__wrapped__("job-1", _request("/v1/jobs/job-1"), user={"email": "other@example.com"})  # pylint: disable=no-member

    assert exc_info.value.status_code == 404
    call = service.get_job.await_args
    assert call.kwargs["access_user_email"] == "other@example.com"
    assert call.kwargs["token_teams"] == []


@pytest.mark.asyncio
async def test_read_list_and_cancel_forward_current_layer_one_scope(monkeypatch):
    """Every retained-job operation is scoped by the token making that request."""
    monkeypatch.setattr(settings, "mcpgateway_async_jobs_enabled", True)
    monkeypatch.setattr(async_jobs, "_owner_context", lambda _request, _user: ("owner@example.com", "owner@example.com", ["current-team"], False))
    service = SimpleNamespace(
        list_jobs=AsyncMock(return_value=[_snapshot("succeeded", result={"sensitive": "retained-result"})]),
        get_job=AsyncMock(return_value=_snapshot()),
        cancel_job=AsyncMock(return_value=_snapshot("cancelled")),
    )
    monkeypatch.setattr(async_jobs, "get_async_job_service", lambda: service)

    request = _request("/v1/jobs")
    listed = await async_jobs.list_jobs.__wrapped__(request, job_status=None, limit=20, user={"email": "owner@example.com"})  # pylint: disable=no-member
    fetched = await async_jobs.get_job.__wrapped__("job-1", request, user={"email": "owner@example.com"})  # pylint: disable=no-member
    cancelled = await async_jobs.cancel_job.__wrapped__("job-1", request, user={"email": "owner@example.com"})  # pylint: disable=no-member

    assert listed.count == 1
    assert "result" not in listed.data[0].model_dump()
    assert "retained-result" not in listed.model_dump_json()
    assert fetched.id == "job-1"
    assert cancelled.status == "cancelled"
    for call in (service.list_jobs.await_args, service.get_job.await_args, service.cancel_job.await_args):
        assert call.kwargs["access_user_email"] == "owner@example.com"
        assert call.kwargs["token_teams"] == ["current-team"]
