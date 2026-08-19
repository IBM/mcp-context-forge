# -*- coding: utf-8 -*-
"""Owner-scoped REST API for asynchronous governed tool invocations."""

# Standard
from datetime import datetime, timezone
import re
from typing import Optional

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.auth_context import get_request_identity, get_scoped_resource_access_context
from mcpgateway.config import settings
from mcpgateway.db import get_db
from mcpgateway.middleware.rbac import get_current_user_with_permissions, require_permission
from mcpgateway.schemas_async_jobs import AsyncJobListResponse, AsyncJobRead, AsyncJobStatus, AsyncJobSummaryRead, AsyncToolJobCreate
from mcpgateway.services.async_job_service import (
    AsyncJobAuthorizationError,
    AsyncJobNotFoundError,
    AsyncJobPayloadTooLargeError,
    AsyncJobQueueFullError,
    AsyncJobServiceUnavailableError,
    AsyncJobStateConflictError,
    get_async_job_service,
)
from mcpgateway.services.tool_service import ToolNotFoundError
from mcpgateway.utils.header_filtering import filter_sensitive_headers

router = APIRouter(prefix="/jobs", tags=["Async Jobs"])

_VALID_HTTP_HEADER_NAME = re.compile(r"^[!#$%&'*+\-.0-9A-Z^_`a-z|~]+$")
_FORBIDDEN_QUEUED_HEADERS = frozenset(
    {
        "connection",
        "content-length",
        "cookie",
        "forwarded",
        "host",
        "keep-alive",
        "proxy-authorization",
        "proxy-connection",
        "set-cookie",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "x-forwarded-for",
        "x-forwarded-host",
        "x-forwarded-port",
        "x-forwarded-prefix",
        "x-forwarded-proto",
        "x-real-ip",
    }
)


def _require_async_jobs_enabled() -> None:
    """Hide this experimental process-local API while disabled."""
    if not settings.mcpgateway_async_jobs_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Async jobs are disabled")


def _owner_context(request: Request, user: object) -> tuple[str, Optional[str], Optional[list[str]], bool]:
    """Resolve immutable owner and Layer-1 execution scope for a queued job."""
    owner_email, is_admin = get_request_identity(request, user)
    scoped_email, token_teams = get_scoped_resource_access_context(request, user)
    if not owner_email or owner_email == "unknown":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authenticated user identity is required")
    return owner_email, scoped_email, token_teams, is_admin


def _credential_context(request: Request) -> tuple[Optional[str], Optional[str], Optional[datetime], Optional[list[str]], Optional[str]]:
    """Extract only already-verified, credential-free execution claims."""
    cached = getattr(request.state, "_jwt_verified_payload", None)
    payload = cached[1] if isinstance(cached, tuple) and len(cached) == 2 and isinstance(cached[1], dict) else {}
    raw_exp = payload.get("exp")
    expires_at: Optional[datetime] = None
    if "exp" in payload:
        if isinstance(raw_exp, (int, float, str)) and not isinstance(raw_exp, bool):
            try:
                expires_at = datetime.fromtimestamp(float(raw_exp), tz=timezone.utc)
            except (OverflowError, OSError, ValueError):
                expires_at = datetime.min.replace(tzinfo=timezone.utc)
        else:
            expires_at = datetime.min.replace(tzinfo=timezone.utc)
    raw_scopes = getattr(request.state, "token_scopes", None)
    if raw_scopes is not None and (not isinstance(raw_scopes, list) or not all(isinstance(scope, str) for scope in raw_scopes)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication credentials")
    token_scopes = [scope for scope in raw_scopes if isinstance(scope, str)] if isinstance(raw_scopes, list) else None
    scopes = payload.get("scopes")
    if scopes is not None and not isinstance(scopes, dict):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication credentials")
    raw_server_id = scopes.get("server_id") if isinstance(scopes, dict) else None
    if raw_server_id is not None and (not isinstance(raw_server_id, str) or not raw_server_id.strip()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication credentials")
    raw_auth_method = getattr(request.state, "auth_method", None)
    auth_method = raw_auth_method if isinstance(raw_auth_method, str) else None
    raw_jti = getattr(request.state, "jti", None) or payload.get("jti")
    if raw_jti is not None and (not isinstance(raw_jti, str) or not raw_jti.strip()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication credentials")
    return (
        auth_method,
        raw_jti,
        expires_at,
        token_scopes,
        raw_server_id.strip() if isinstance(raw_server_id, str) else None,
    )


def _plugin_policy_inputs(request: Request, user: object) -> tuple[Optional[str], Optional[str]]:
    """Capture the credential-free request attributes used by permission hooks."""
    if isinstance(user, dict) and "ip_address" in user:
        raw_client_host = user.get("ip_address")
    else:
        raw_client_host = request.client.host if request.client else None
    if isinstance(user, dict) and "user_agent" in user:
        raw_user_agent = user.get("user_agent")
    else:
        raw_user_agent = request.headers.get("user-agent")
    if raw_client_host is not None and not isinstance(raw_client_host, str):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication context")
    if raw_user_agent is not None and not isinstance(raw_user_agent, str):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication context")
    return raw_client_host, raw_user_agent


def _is_forbidden_queued_header(name: str) -> bool:
    """Return whether a header can alter identity, routing, or connection state."""
    normalized = name.strip().lower()
    configured_auth_header = settings.auth_header_name.strip().lower()
    return (
        not normalized
        or not _VALID_HTTP_HEADER_NAME.fullmatch(normalized)
        or normalized == configured_auth_header
        or normalized in _FORBIDDEN_QUEUED_HEADERS
        or normalized == "x-upstream-authorization"
        or normalized.startswith(("x-context-forge-", "x-contextforge-"))
        or name not in filter_sensitive_headers({name: "value"})
    )


def _validate_supplemental_headers(headers: dict[str, str], *, field_name: str) -> None:
    """Reject credentials and trusted transport headers supplied in a job body."""
    forbidden = sorted(name for name in headers if _is_forbidden_queued_header(name))
    if forbidden:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{field_name} contains forbidden credential or transport header(s): {', '.join(forbidden)}",
        )


def _safe_inbound_headers(request: Request) -> dict[str, str]:
    """Drop ambient browser/proxy credentials that cannot be used by a queued job."""
    safe: dict[str, str] = {}
    proxy_user_header = settings.proxy_user_header.strip().lower()
    for name, value in request.headers.items():
        normalized = name.lower()
        if normalized == proxy_user_header or normalized in _FORBIDDEN_QUEUED_HEADERS or normalized.startswith(("x-context-forge-", "x-contextforge-")):
            continue
        safe[normalized] = value
    return safe


@router.post("/tool-invocations", response_model=AsyncJobRead, status_code=status.HTTP_202_ACCEPTED)
@require_permission("tools.execute", allow_admin_bypass=False)
async def enqueue_tool_invocation(
    payload: AsyncToolJobCreate,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> AsyncJobRead:
    """Authorize a tool now, then enqueue it for bounded background execution."""
    _require_async_jobs_enabled()
    owner_email, access_user_email, token_teams, is_admin = _owner_context(request, user)
    auth_method, token_jti, token_expires_at, token_scopes, token_server_id = _credential_context(request)
    policy_client_host, policy_user_agent = _plugin_policy_inputs(request, user)
    # Client-supplied supplemental headers must never replace the credential
    # that authenticated this request. ToolService will still apply its normal
    # outbound passthrough allowlist to the merged set.
    _validate_supplemental_headers(payload.headers, field_name="headers")
    _validate_supplemental_headers(payload.metadata, field_name="metadata")
    inbound_headers = _safe_inbound_headers(request)
    supplemental_headers = {key: value for key, value in payload.headers.items() if key.lower() not in inbound_headers}
    request_headers = {**supplemental_headers, **inbound_headers}
    try:
        job = await get_async_job_service().enqueue_tool_invocation(
            db,
            owner_email=owner_email,
            access_user_email=access_user_email,
            access_is_admin=is_admin,
            token_teams=token_teams,
            tool_id=payload.tool_id,
            arguments=payload.arguments,
            request_headers=request_headers,
            supplemental_header_names=list(supplemental_headers),
            metadata=payload.metadata,
            timeout_seconds=payload.timeout_seconds,
            token_use=getattr(request.state, "token_use", None) or (user.get("token_use") if isinstance(user, dict) else None),
            auth_method=auth_method,
            token_jti=token_jti,
            token_expires_at=token_expires_at,
            token_scopes=token_scopes,
            token_server_id=token_server_id,
            policy_client_host=policy_client_host,
            policy_user_agent=policy_user_agent,
        )
    except ToolNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tool not found") from exc
    except AsyncJobAuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied") from exc
    except AsyncJobQueueFullError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc), headers={"Retry-After": "1"}) from exc
    except AsyncJobPayloadTooLargeError as exc:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=str(exc)) from exc
    except AsyncJobServiceUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return AsyncJobRead.model_validate(job)


@router.get("", response_model=AsyncJobListResponse)
@require_permission("tools.execute", allow_admin_bypass=False)
async def list_jobs(
    request: Request,
    job_status: Optional[AsyncJobStatus] = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=200),
    user=Depends(get_current_user_with_permissions),
) -> AsyncJobListResponse:
    """List only jobs owned by the authenticated caller."""
    _require_async_jobs_enabled()
    owner_email, access_user_email, token_teams, _is_admin = _owner_context(request, user)
    token_server_id = _credential_context(request)[4]
    try:
        jobs = await get_async_job_service().list_jobs(
            owner_email,
            access_user_email=access_user_email,
            token_teams=token_teams,
            status=job_status,
            limit=limit,
            token_server_id=token_server_id,
        )
    except AsyncJobServiceUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    data = [AsyncJobSummaryRead.model_validate(job) for job in jobs]
    return AsyncJobListResponse(data=data, count=len(data))


@router.get("/{job_id}", response_model=AsyncJobRead)
@require_permission("tools.execute", allow_admin_bypass=False)
async def get_job(job_id: str, request: Request, user=Depends(get_current_user_with_permissions)) -> AsyncJobRead:
    """Read one job if and only if it belongs to the caller."""
    _require_async_jobs_enabled()
    owner_email, access_user_email, token_teams, _is_admin = _owner_context(request, user)
    token_server_id = _credential_context(request)[4]
    try:
        job = await get_async_job_service().get_job(
            job_id,
            owner_email,
            access_user_email=access_user_email,
            token_teams=token_teams,
            token_server_id=token_server_id,
        )
    except AsyncJobNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found") from exc
    except AsyncJobServiceUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return AsyncJobRead.model_validate(job)


@router.post("/{job_id}/cancel", response_model=AsyncJobRead)
@require_permission("tools.execute", allow_admin_bypass=False)
async def cancel_job(job_id: str, request: Request, user=Depends(get_current_user_with_permissions)) -> AsyncJobRead:
    """Cancel one queued/running job owned by the authenticated caller."""
    _require_async_jobs_enabled()
    owner_email, access_user_email, token_teams, _is_admin = _owner_context(request, user)
    token_server_id = _credential_context(request)[4]
    try:
        job = await get_async_job_service().cancel_job(
            job_id,
            owner_email,
            access_user_email=access_user_email,
            token_teams=token_teams,
            token_server_id=token_server_id,
        )
    except AsyncJobNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found") from exc
    except AsyncJobStateConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except AsyncJobServiceUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return AsyncJobRead.model_validate(job)
