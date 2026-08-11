# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/grpc_schema.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

gRPC descriptor artifact import, activation, diff, and manifest scanning APIs.
"""

# Standard
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

# Third-Party
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.auth_context import get_token_teams_from_request, get_user_email
from mcpgateway.config import settings
from mcpgateway.db import get_db, GrpcHealthSample, GrpcMetricsHourly
from mcpgateway.db import GrpcService as DbGrpcService
from mcpgateway.db import Tool as DbTool
from mcpgateway.db import ToolMetric
from mcpgateway.middleware.rbac import get_current_user_with_permissions, require_permission
from mcpgateway.schemas import GrpcRegistrySchemaViewRead, GrpcRegistryServiceRead, GrpcRegistryViewRead, GrpcSchemaArtifactRead, GrpcSchemaDiff, GrpcToolSyncPreview
from mcpgateway.services.grpc_registry_service import GrpcRegistryService
from mcpgateway.services.grpc_service import GrpcService, GrpcServiceError, GrpcServiceNotFoundError
from mcpgateway.services.grpc_monitoring_service import get_grpc_monitoring_service
from mcpgateway.services.proto_scan_service import get_proto_scan_service

router = APIRouter(prefix="/grpc", tags=["gRPC Schema"])
grpc_service = GrpcService()
proto_scanner = get_proto_scan_service()


def _require_grpc_enabled() -> None:
    """Hide gRPC management routes while the feature is disabled."""
    if not settings.mcpgateway_grpc_enabled:
        raise HTTPException(status_code=404, detail="gRPC support is disabled")


def _http_error(exc: GrpcServiceError) -> HTTPException:
    """Translate descriptor service errors into stable HTTP statuses."""
    return HTTPException(status_code=404 if isinstance(exc, GrpcServiceNotFoundError) else 422, detail=str(exc))


def _require_service_access(request: Request, user: Any, db: Session, service_id: str) -> DbGrpcService:
    """Resolve a gRPC service through the caller's canonical token scope."""
    statement = select(DbGrpcService).where(DbGrpcService.id == service_id)
    token_teams = get_token_teams_from_request(request)
    if token_teams is not None:
        clauses = [DbGrpcService.visibility == "public", DbGrpcService.owner_email == get_user_email(user)]
        if token_teams:
            clauses.append(DbGrpcService.team_id.in_(token_teams))
        statement = statement.where(or_(*clauses))
    service = db.execute(statement).scalar_one_or_none()
    if service is None:
        raise HTTPException(status_code=404, detail="gRPC service not found")
    return service


def _visible_services(request: Request, user: Any, db: Session) -> list[DbGrpcService]:
    """Resolve the services visible to the caller under their token scope."""
    statement = select(DbGrpcService).order_by(DbGrpcService.name)
    token_teams = get_token_teams_from_request(request)
    if token_teams is not None:
        clauses = [DbGrpcService.visibility == "public", DbGrpcService.owner_email == get_user_email(user)]
        if token_teams:
            clauses.append(DbGrpcService.team_id.in_(token_teams))
        statement = statement.where(or_(*clauses))
    return list(db.execute(statement).scalars().all())


@router.post("/{service_id}/schemas/import", response_model=GrpcSchemaArtifactRead, status_code=201)
@require_permission("admin.grpc", allow_admin_bypass=False)
async def import_schema(
    service_id: str,
    request: Request,
    artifact: UploadFile = File(...),
    activate: bool = Form(True),
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
):
    """Import a .proto, safe ZIP, or FileDescriptorSet."""
    _require_grpc_enabled()
    _require_service_access(request, user, db, service_id)
    payload = await artifact.read(settings.mcpgateway_proto_max_upload_bytes + 1)
    if len(payload) > settings.mcpgateway_proto_max_upload_bytes:
        raise HTTPException(status_code=413, detail="Proto artifact exceeds the upload limit")
    filename = artifact.filename or "schema.protoset"
    if not filename.lower().endswith((".proto", ".zip", ".protoset", ".pb", ".bin")):
        raise HTTPException(status_code=415, detail="Expected .proto, .zip, or protoset artifact")
    try:
        return await grpc_service.import_schema(db, service_id, payload, filename, get_user_email(user), activate=activate)
    except GrpcServiceError as exc:
        raise _http_error(exc) from exc


@router.get("/{service_id}/schemas", response_model=list[GrpcSchemaArtifactRead])
@require_permission("admin.grpc", allow_admin_bypass=False)
async def list_schemas(service_id: str, request: Request, db: Session = Depends(get_db), user=Depends(get_current_user_with_permissions)):
    """List schema versions without returning descriptor bytes."""
    _require_grpc_enabled()
    _require_service_access(request, user, db, service_id)
    try:
        return await grpc_service.list_schemas(db, service_id)
    except GrpcServiceError as exc:
        raise _http_error(exc) from exc


@router.get("/registry", response_model=GrpcRegistryViewRead)
@require_permission("admin.grpc", allow_admin_bypass=False)
async def registry_overview(request: Request, db: Session = Depends(get_db), user=Depends(get_current_user_with_permissions)):
    """Read-only registry summary: services with schema versions, methods, and tool exposure."""
    _require_grpc_enabled()
    visible = _visible_services(request, user, db)
    return GrpcRegistryService.build_registry_view(db, [service.id for service in visible])


@router.get("/{service_id}/registry", response_model=GrpcRegistryServiceRead)
@require_permission("admin.grpc", allow_admin_bypass=False)
async def registry_service_detail(service_id: str, request: Request, db: Session = Depends(get_db), user=Depends(get_current_user_with_permissions)):
    """Read-only detail for one service: schema versions and per-method tool status."""
    _require_grpc_enabled()
    _require_service_access(request, user, db, service_id)
    view = GrpcRegistryService.build_service_detail(db, service_id)
    if view is None:
        raise HTTPException(status_code=404, detail="gRPC service not found")
    return view


@router.get("/{service_id}/schemas/{artifact_id}/registry", response_model=GrpcRegistrySchemaViewRead)
@require_permission("admin.grpc", allow_admin_bypass=False)
async def registry_schema_detail(service_id: str, artifact_id: str, request: Request, db: Session = Depends(get_db), user=Depends(get_current_user_with_permissions)):
    """Read-only detail for one schema version: methods with exposure and tool state."""
    _require_grpc_enabled()
    _require_service_access(request, user, db, service_id)
    view = GrpcRegistryService.build_schema_detail(db, artifact_id)
    if view is None:
        raise HTTPException(status_code=404, detail="Schema artifact not found")
    return view


@router.post("/{service_id}/schemas/{artifact_id}/activate", response_model=GrpcSchemaArtifactRead)
@require_permission("admin.grpc", allow_admin_bypass=False)
async def activate_schema(service_id: str, artifact_id: str, request: Request, db: Session = Depends(get_db), user=Depends(get_current_user_with_permissions)):
    """Activate one immutable descriptor version and resynchronize tools."""
    _require_grpc_enabled()
    _require_service_access(request, user, db, service_id)
    try:
        return await grpc_service.activate_schema(db, service_id, artifact_id)
    except GrpcServiceError as exc:
        raise _http_error(exc) from exc


@router.get("/{service_id}/schemas/diff", response_model=GrpcSchemaDiff)
@require_permission("admin.grpc", allow_admin_bypass=False)
async def diff_schemas(
    service_id: str,
    request: Request,
    from_artifact_id: str = Query(..., alias="from"),
    to_artifact_id: str = Query(..., alias="to"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),  # pylint: disable=unused-argument
):
    """Compare service and method signatures between two versions."""
    _require_grpc_enabled()
    _require_service_access(request, user, db, service_id)
    try:
        return await grpc_service.diff_schemas(db, service_id, from_artifact_id, to_artifact_id)
    except GrpcServiceError as exc:
        raise _http_error(exc) from exc


@router.get("/{service_id}/schemas/{artifact_id}/preview", response_model=GrpcToolSyncPreview)
@require_permission("admin.grpc", allow_admin_bypass=False)
async def preview_tool_sync(
    service_id: str,
    artifact_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),  # pylint: disable=unused-argument
):
    """Preview tool synchronization for a candidate schema without mutating anything."""
    _require_grpc_enabled()
    _require_service_access(request, user, db, service_id)
    try:
        return GrpcRegistryService.build_sync_preview(db, service_id, artifact_id)
    except GrpcServiceError as exc:
        raise _http_error(exc) from exc


@router.post("/scan")
@require_permission("admin.grpc", allow_admin_bypass=False)
async def scan_proto_manifests(db: Session = Depends(get_db), user=Depends(get_current_user_with_permissions)):  # pylint: disable=unused-argument
    """Run one primary-worker scan over explicitly allowed roots."""
    _require_grpc_enabled()
    try:
        return await proto_scanner.scan(db)
    except GrpcServiceError as exc:
        raise _http_error(exc) from exc


@router.post("/{service_id}/health")
@require_permission("admin.grpc", allow_admin_bypass=False)
async def check_health(service_id: str, request: Request, db: Session = Depends(get_db), user=Depends(get_current_user_with_permissions)):
    """Run an immediate standards-based health check."""
    _require_grpc_enabled()
    _require_service_access(request, user, db, service_id)
    result = await get_grpc_monitoring_service().check_service(service_id)
    if result.get("status") == "missing":
        raise HTTPException(status_code=404, detail="gRPC service not found")
    if result.get("status") == "unavailable":
        raise HTTPException(status_code=503, detail="gRPC health dependencies are unavailable")
    return result


@router.get("/{service_id}/health/samples")
@require_permission("admin.grpc", allow_admin_bypass=False)
async def health_samples(
    service_id: str,
    request: Request,
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),  # pylint: disable=unused-argument
):
    """Return recent persisted health samples."""
    _require_grpc_enabled()
    _require_service_access(request, user, db, service_id)
    samples = list(db.execute(select(GrpcHealthSample).where(GrpcHealthSample.grpc_service_id == service_id).order_by(GrpcHealthSample.timestamp.desc()).limit(limit)).scalars())
    return {
        "data": [
            {
                "timestamp": sample.timestamp,
                "healthy": sample.healthy,
                "check_type": sample.check_type,
                "status_code": sample.status_code,
                "latency_ms": sample.latency_ms,
                "error_message": sample.error_message,
            }
            for sample in samples
        ]
    }


def _percentile(values: list[float], percent: int) -> Optional[float]:
    """Interpolate a percentile over current-hour raw values."""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percent / 100
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


@router.get("/{service_id}/metrics")
@require_permission("metrics:read", allow_admin_bypass=False)
async def grpc_metrics(
    service_id: str,
    request: Request,
    hours: int = Query(24, ge=1, le=24 * 90),
    method: Optional[str] = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
):
    """Return closed-hour rollups plus live current-hour gRPC metrics."""
    _require_grpc_enabled()
    service = _require_service_access(request, user, db, service_id)
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=hours)
    current_hour = now.replace(minute=0, second=0, microsecond=0)
    hourly_statement = select(GrpcMetricsHourly).where(
        GrpcMetricsHourly.grpc_service_id == service_id,
        GrpcMetricsHourly.hour_start >= start,
        GrpcMetricsHourly.hour_start < current_hour,
    )
    if method:
        hourly_statement = hourly_statement.where(GrpcMetricsHourly.method_name == method)
    hourly_rows = list(db.execute(hourly_statement.order_by(GrpcMetricsHourly.hour_start)).scalars())

    live_statement = (
        select(ToolMetric, DbTool.original_name)
        .join(DbTool, DbTool.id == ToolMetric.tool_id)
        .where(DbTool.grpc_service_id == service_id, ToolMetric.timestamp >= max(start, current_hour), ToolMetric.timestamp <= now)
    )
    if method:
        live_statement = live_statement.where(DbTool.original_name == method)
    live_rows = list(db.execute(live_statement).all())

    trend: list[dict[str, Any]] = [
        {
            "hour": row.hour_start if row.hour_start.tzinfo else row.hour_start.replace(tzinfo=timezone.utc),
            "method": row.method_name,
            "calls": row.total_count,
            "successes": row.success_count,
            "failures": row.failure_count,
            "status_distribution": row.status_counts,
            "p50": row.p50_response_time,
            "p95": row.p95_response_time,
            "p99": row.p99_response_time,
            "request_bytes": row.request_bytes,
            "response_bytes": row.response_bytes,
        }
        for row in hourly_rows
    ]
    live_grouped: dict[str, list[ToolMetric]] = {}
    for row in live_rows:
        live_grouped.setdefault(row.original_name or "unknown", []).append(row.ToolMetric)
    for method_name, samples in live_grouped.items():
        statuses: dict[str, int] = {}
        for sample in samples:
            status_name = sample.status_code or ("OK" if sample.is_success else "ERROR")
            statuses[status_name] = statuses.get(status_name, 0) + 1
        response_times = [float(sample.response_time) for sample in samples]
        successes = sum(1 for sample in samples if sample.is_success)
        trend.append(
            {
                "hour": current_hour,
                "method": method_name,
                "calls": len(samples),
                "successes": successes,
                "failures": len(samples) - successes,
                "status_distribution": statuses,
                "p50": _percentile(response_times, 50),
                "p95": _percentile(response_times, 95),
                "p99": _percentile(response_times, 99),
                "request_bytes": sum(sample.request_bytes or 0 for sample in samples),
                "response_bytes": sum(sample.response_bytes or 0 for sample in samples),
            }
        )
    trend.sort(key=lambda row: (row["hour"], row["method"]))
    total_calls = sum(row["calls"] for row in trend)
    failures = sum(row["failures"] for row in trend)
    status_distribution: dict[str, int] = {}
    for row in trend:
        for status_name, count in row["status_distribution"].items():
            status_distribution[status_name] = status_distribution.get(status_name, 0) + count

    def weighted_percentile(name: str) -> Optional[float]:
        """Estimate a cross-hour percentile from per-hour rollup values."""
        samples = [(row[name], row["calls"]) for row in trend if row[name] is not None and row["calls"]]
        denominator = sum(count for _value, count in samples)
        return sum(float(value) * count for value, count in samples) / denominator if denominator else None

    return {
        "service_id": service_id,
        "service_name": service.name,
        "total_calls": total_calls,
        "success_count": total_calls - failures,
        "failure_count": failures,
        "error_rate": failures / total_calls if total_calls else 0.0,
        "p50": weighted_percentile("p50"),
        "p95": weighted_percentile("p95"),
        "p99": weighted_percentile("p99"),
        "percentiles_estimated": bool(hourly_rows),
        "request_bytes": sum(row["request_bytes"] for row in trend),
        "response_bytes": sum(row["response_bytes"] for row in trend),
        "status_distribution": status_distribution,
        "trend": trend,
    }
