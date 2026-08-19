# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/api_debug.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unified REST, MCP, gRPC, and SQL tool debugger.
"""

# Standard
import asyncio
from datetime import datetime, timedelta, timezone
import json
import logging
import time
from typing import Any, AsyncIterator, Awaitable, Callable, Optional

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
import orjson
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.auth_context import get_scoped_resource_access_context, get_token_teams_from_request, get_user_email
from mcpgateway.config import settings
from mcpgateway.db import APIDebugHistory, fresh_db_session, get_db, ToolMetric
from mcpgateway.db import Tool as DbTool
from mcpgateway.middleware.rbac import get_current_user_with_permissions, require_permission
from mcpgateway.schemas import APIDebugHistoryRead, APIDebugInvokeRequest
from mcpgateway.services.base_service import BaseService
from mcpgateway.services.metrics_buffer_service import debug_invocation_context
from mcpgateway.services.observability_service import current_trace_id
from mcpgateway.services.tool_service import tool_service
from mcpgateway.services.tool_service import ToolError

router = APIRouter(prefix="/debug", tags=["API Debugger"])
logger = logging.getLogger(__name__)
_SENSITIVE_FRAGMENTS = ("authorization", "cookie", "password", "passwd", "secret", "token", "api_key", "apikey", "credential")


def _require_debug_enabled() -> None:
    """Hide the debugger routes while the feature flag is disabled."""
    if not settings.mcpgateway_api_debug_enabled:
        raise HTTPException(status_code=404, detail="API debugger is disabled")


def _redact(value: Any, depth: int = 0) -> Any:
    """Create a bounded, credential-free request preview."""
    if depth > 5:
        return "<truncated>"
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in list(value.items())[:100]:
            lowered = str(key).lower()
            result[str(key)] = "********" if any(fragment in lowered for fragment in _SENSITIVE_FRAGMENTS) else _redact(item, depth + 1)
        return result
    if isinstance(value, list):
        return [_redact(item, depth + 1) for item in value[:100]]
    if isinstance(value, str):
        return value[:512] + ("…" if len(value) > 512 else "")
    return value


def _scope_tool_statement(statement, request: Request, user: Any, db: Session):
    """Apply canonical token visibility to debugger catalog, invoke, and metrics reads."""
    user_email, token_teams = get_scoped_resource_access_context(request, user)
    return BaseService._apply_visibility_scope(  # pylint: disable=protected-access
        statement,
        DbTool,
        user_email=user_email,
        token_teams=token_teams,
        team_ids=token_teams or [],
        db=db,
    )


def _record_history(
    owner_email: str,
    tool_id: Optional[str],
    protocol: str,
    request_preview: dict[str, Any],
    result_metadata: dict[str, Any],
    duration_ms: float,
    status_code: str,
    trace_id: Optional[str],
    success: bool,
) -> None:
    """Persist debug metadata in an independent short-lived session."""
    now = datetime.now(timezone.utc)
    try:
        with fresh_db_session() as history_db:
            history_db.add(
                APIDebugHistory(
                    owner_email=owner_email,
                    tool_id=tool_id,
                    protocol=protocol,
                    request_preview=request_preview,
                    result_metadata=result_metadata,
                    duration_ms=duration_ms,
                    status_code=status_code,
                    trace_id=trace_id,
                    is_success=success,
                    created_at=now,
                )
            )
            history_db.flush()
            history_db.execute(
                delete(APIDebugHistory).where(
                    APIDebugHistory.owner_email == owner_email,
                    APIDebugHistory.created_at < now - timedelta(days=settings.mcpgateway_api_debug_retention_days),
                )
            )
            keep_ids = list(
                history_db.execute(
                    select(APIDebugHistory.id).where(APIDebugHistory.owner_email == owner_email).order_by(APIDebugHistory.created_at.desc()).limit(settings.mcpgateway_api_debug_max_history)
                ).scalars()
            )
            if keep_ids:
                history_db.execute(delete(APIDebugHistory).where(APIDebugHistory.owner_email == owner_email, APIDebugHistory.id.not_in(keep_ids)))
    except Exception:  # pylint: disable=broad-except
        # Debug history is observability metadata. A persistence failure must not
        # replace the real invocation result or its protocol-specific error.
        logger.warning("Unable to persist API debugger history", exc_info=True)


async def _invoke(
    payload: APIDebugInvokeRequest,
    request: Request,
    db: Session,
    user: Any,
    stream_callback: Optional[Callable[[dict[str, Any]], Awaitable[None]]] = None,
) -> dict[str, Any]:
    """Invoke through ToolService and save only metadata/history previews."""
    _require_debug_enabled()
    tool = db.execute(_scope_tool_statement(select(DbTool).where(DbTool.id == payload.tool_id), request, user, db)).scalar_one_or_none()
    if tool is None:
        raise HTTPException(status_code=404, detail="Tool not found")
    owner_email = get_user_email(user)
    protocol = tool.integration_type
    trace_id = current_trace_id.get()
    started = time.monotonic()
    preview = {
        "arguments": _redact(payload.arguments),
        "headers": {key: "********" for key in payload.headers},
        "metadata": {key: "********" for key in payload.metadata},
        "deadline_seconds": payload.deadline_seconds,
    }
    invocation_metadata: Optional[dict[str, Any]] = None
    if protocol == "gRPC":
        invocation_metadata = {"grpc_metadata": payload.metadata, "capture_grpc_call_metadata": True}
        if stream_callback is not None:
            invocation_metadata["grpc_stream_callback"] = stream_callback
    context_token = debug_invocation_context.set(True)
    try:
        invocation = tool_service.invoke_tool(
            db,
            tool.name,
            payload.arguments,
            request_headers={**dict(request.headers), **payload.headers},
            app_user_email=owner_email,
            user_email=owner_email,
            token_teams=get_token_teams_from_request(request),
            meta_data=invocation_metadata,
            timeout_override=payload.deadline_seconds,
        )
        result = await asyncio.wait_for(invocation, timeout=payload.deadline_seconds) if payload.deadline_seconds else await invocation
        duration_ms = (time.monotonic() - started) * 1000
        trace_id = current_trace_id.get() or trace_id
        status_code = "ERROR" if result.is_error else "OK"
        result_dump = result.model_dump(by_alias=True)
        _record_history(
            owner_email,
            tool.id,
            protocol,
            preview,
            {"content_items": len(result.content), "is_error": result.is_error, "has_structured_content": result.structured_content is not None},
            duration_ms,
            status_code,
            trace_id,
            not result.is_error,
        )
        return {"result": result_dump, "duration_ms": duration_ms, "trace_id": trace_id, "status_code": status_code, "protocol": protocol}
    except asyncio.TimeoutError as exc:
        duration_ms = (time.monotonic() - started) * 1000
        _record_history(owner_email, tool.id, protocol, preview, {"error_type": "timeout"}, duration_ms, "DEADLINE_EXCEEDED", trace_id, False)
        raise HTTPException(status_code=504, detail="Debug invocation deadline exceeded") from exc
    except ToolError as exc:
        duration_ms = (time.monotonic() - started) * 1000
        _record_history(owner_email, tool.id, protocol, preview, {"error_type": type(exc).__name__}, duration_ms, "ERROR", trace_id, False)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        debug_invocation_context.reset(context_token)


@router.get("/catalog")
@require_permission("tools.read", allow_admin_bypass=False)
async def debug_catalog(
    request: Request,
    protocol: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
):
    """List invocable tools and schemas visible to the caller."""
    _require_debug_enabled()
    tools, _cursor = await tool_service.list_tools(
        db,
        limit=0,
        user_email=get_user_email(user),
        token_teams=get_token_teams_from_request(request),
        requesting_user_email=get_user_email(user),
        requesting_user_is_admin=bool(isinstance(user, dict) and user.get("is_admin")),
    )
    catalog = [
        {
            "id": tool.id,
            "name": tool.name,
            "description": tool.description,
            "protocol": tool.integration_type,
            "input_schema": tool.input_schema,
            "output_schema": tool.output_schema,
            "enabled": tool.enabled,
            "reachable": tool.reachable,
        }
        for tool in tools
        if protocol is None or tool.integration_type.lower() == protocol.lower()
    ]
    return {"data": catalog}


@router.post("/invoke")
@require_permission("tools.execute", allow_admin_bypass=False)
async def debug_invoke(payload: APIDebugInvokeRequest, request: Request, db: Session = Depends(get_db), user=Depends(get_current_user_with_permissions)):
    """Invoke a tool and return response, error, latency, and trace metadata."""
    return await _invoke(payload, request, db, user)


@router.post("/stream")
@require_permission("tools.execute", allow_admin_bypass=False)
async def debug_stream(payload: APIDebugInvokeRequest, request: Request, db: Session = Depends(get_db), user=Depends(get_current_user_with_permissions)):
    """Return an SSE stream; gRPC streaming items are emitted as individual events."""
    _require_debug_enabled()
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)

    async def receive_item(item: dict[str, Any]) -> None:
        """Queue one governed streaming item for SSE delivery."""
        await queue.put(item)

    invocation = asyncio.create_task(_invoke(payload, request, db, user, stream_callback=receive_item))

    async def events() -> AsyncIterator[str]:
        """Emit lifecycle, item, terminal metadata, and error SSE events."""
        emitted_live = False
        yield "event: start\ndata: {}\n\n"
        try:
            while not invocation.done() or not queue.empty():
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=0.25)
                except asyncio.TimeoutError:
                    continue
                emitted_live = True
                yield f"event: message\ndata: {orjson.dumps(item, default=str).decode()}\n\n"
            response = await invocation
            yield f"event: metadata\ndata: {json.dumps({key: response[key] for key in ('duration_ms', 'trace_id', 'status_code', 'protocol')})}\n\n"
            if not emitted_live:
                result = response["result"]
                content = result.get("content") or []
                emitted_result = False
                for block in content:
                    text_value = block.get("text") if isinstance(block, dict) else None
                    if not isinstance(text_value, str):
                        continue
                    try:
                        decoded = orjson.loads(text_value)
                    except orjson.JSONDecodeError:
                        decoded = text_value
                    emitted_result = True
                    yield f"event: message\ndata: {orjson.dumps(decoded, default=str).decode()}\n\n"
                if not emitted_result:
                    yield "event: message\ndata: null\n\n"
            yield "event: done\ndata: {}\n\n"
        except asyncio.CancelledError:
            invocation.cancel()
            raise
        except HTTPException as exc:
            yield f"event: error\ndata: {orjson.dumps({'status': exc.status_code, 'detail': exc.detail}, default=str).decode()}\n\n"
        except Exception as exc:  # pylint: disable=broad-except
            yield f"event: error\ndata: {orjson.dumps({'detail': str(exc)}, default=str).decode()}\n\n"
        finally:
            if not invocation.done():
                invocation.cancel()

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/history", response_model=list[APIDebugHistoryRead])
@require_permission("tools.read", allow_admin_bypass=False)
async def debug_history(db: Session = Depends(get_db), user=Depends(get_current_user_with_permissions)):
    """Return the current user's unexpired credential-free debug history."""
    _require_debug_enabled()
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.mcpgateway_api_debug_retention_days)
    return list(
        db.execute(
            select(APIDebugHistory)
            .where(APIDebugHistory.owner_email == get_user_email(user), APIDebugHistory.created_at >= cutoff)
            .order_by(APIDebugHistory.created_at.desc())
            .limit(settings.mcpgateway_api_debug_max_history)
        ).scalars()
    )


@router.get("/stats")
@require_permission("metrics:read", allow_admin_bypass=False)
async def api_call_stats(
    request: Request,
    protocol: Optional[str] = None,
    service_id: Optional[str] = None,
    method: Optional[str] = None,
    status: Optional[str] = None,
    is_debug: Optional[bool] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
):
    """Return filtered API/gRPC volume, error, latency, byte, and status trends."""
    _require_debug_enabled()
    end = end or datetime.now(timezone.utc)
    start = start or end - timedelta(hours=24)
    statement = (
        select(ToolMetric, DbTool.integration_type, DbTool.grpc_service_id, DbTool.original_name)
        .join(DbTool, DbTool.id == ToolMetric.tool_id)
        .where(ToolMetric.timestamp >= start, ToolMetric.timestamp <= end)
    )
    statement = _scope_tool_statement(statement, request, user, db)
    if protocol:
        statement = statement.where(DbTool.integration_type == protocol)
    if service_id:
        statement = statement.where(DbTool.grpc_service_id == service_id)
    if method:
        statement = statement.where(DbTool.original_name == method)
    if status:
        statement = statement.where(ToolMetric.status_code == status)
    if is_debug is not None:
        statement = statement.where(ToolMetric.is_debug == is_debug)
    rows = list(db.execute(statement).all())
    response_times = sorted(float(row.ToolMetric.response_time) for row in rows)

    def percentile(percent: int) -> Optional[float]:
        """Interpolate a percentile across the filtered raw samples."""
        if not response_times:
            return None
        index = (len(response_times) - 1) * percent / 100
        lower = int(index)
        upper = min(lower + 1, len(response_times) - 1)
        fraction = index - lower
        return response_times[lower] * (1 - fraction) + response_times[upper] * fraction

    statuses: dict[str, int] = {}
    debug_distribution = {"debug": 0, "regular": 0}
    trend: dict[str, dict[str, Any]] = {}
    for row in rows:
        metric = row.ToolMetric
        status_name = metric.status_code or ("OK" if metric.is_success else "ERROR")
        statuses[status_name] = statuses.get(status_name, 0) + 1
        debug_distribution["debug" if metric.is_debug else "regular"] += 1
        timestamp = metric.timestamp if metric.timestamp.tzinfo else metric.timestamp.replace(tzinfo=timezone.utc)
        hour = timestamp.replace(minute=0, second=0, microsecond=0).isoformat()
        bucket = trend.setdefault(hour, {"hour": hour, "calls": 0, "failures": 0})
        bucket["calls"] += 1
        bucket["failures"] += 0 if metric.is_success else 1
    failures = sum(1 for row in rows if not row.ToolMetric.is_success)
    return {
        "total_calls": len(rows),
        "success_count": len(rows) - failures,
        "failure_count": failures,
        "error_rate": failures / len(rows) if rows else 0.0,
        "p50": percentile(50),
        "p95": percentile(95),
        "p99": percentile(99),
        "request_bytes": sum(row.ToolMetric.request_bytes or 0 for row in rows),
        "response_bytes": sum(row.ToolMetric.response_bytes or 0 for row in rows),
        "status_distribution": statuses,
        "debug_distribution": debug_distribution,
        "trend": [trend[key] for key in sorted(trend)],
    }
