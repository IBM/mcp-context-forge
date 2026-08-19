# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/grpc_service.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

gRPC Service Management

This module implements gRPC service management for ContextForge.
It handles gRPC service registration, reflection-based discovery, listing,
retrieval, updates, activation toggling, and deletion.
"""

# Standard
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from datetime import datetime, timezone
import sys
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

try:
    # Third-Party
    import grpc
    from grpc_reflection.v1alpha import reflection_pb2, reflection_pb2_grpc

    GRPC_AVAILABLE = True
except ImportError:
    GRPC_AVAILABLE = False
    # grpc module will not be used if not available
    grpc = None  # type: ignore
    reflection_pb2 = None  # type: ignore
    reflection_pb2_grpc = None  # type: ignore

# Third-Party
from google.protobuf.descriptor_pb2 import FileDescriptorSet
from pydantic import ValidationError
from sqlalchemy import and_, delete, desc, false, or_, select, update
from sqlalchemy.orm import Session

# First-Party
from mcpgateway import translate_grpc
from mcpgateway.config import settings
from mcpgateway.db import EmailTeam
from mcpgateway.db import GrpcSchemaArtifact
from mcpgateway.db import GrpcService as DbGrpcService
from mcpgateway.db import server_tool_association
from mcpgateway.db import Tool as DbTool
from mcpgateway.db import ToolMetric
from mcpgateway.observability import create_child_span
from mcpgateway.schemas import GrpcSchemaDiff, GrpcServiceCreate, GrpcServiceRead, GrpcServiceUpdate
from mcpgateway.services.base_service import BaseService
from mcpgateway.services.encryption_service import get_encryption_service
from mcpgateway.services.grpc_runtime_cache import runtime_cache
from mcpgateway.services.grpc_schema_service import GrpcSchemaService
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.metrics import grpc_client_calls_counter, grpc_client_duration_histogram, grpc_reflection_counter
from mcpgateway.services.team_management_service import TeamManagementService
from mcpgateway.utils.create_slug import slugify
from mcpgateway.utils.display_name import generate_display_name
from mcpgateway.utils.grpc_validation import _validate_grpc_target, _validate_tls_path, GrpcServiceError
from mcpgateway.utils.pagination import unified_paginate

# Initialize logging
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

# Propagate the bounded native gRPC status to ToolService's unified metric row.
# ContextVar keeps overlapping async invocations isolated.
grpc_status_context: ContextVar[Optional[str]] = ContextVar("grpc_status_context", default=None)


# DoS guards for descriptors returned by ``grpc.reflection`` — intentionally hardcoded
# (not exposed via settings) so a config change cannot silently weaken these limits.
_GRPC_MAX_DESCRIPTOR_BYTES = 1 * 1024 * 1024
_GRPC_MAX_DESCRIPTOR_COUNT = 1024
_GRPC_MAX_TOTAL_DESCRIPTOR_BYTES = 8 * 1024 * 1024
_GRPC_TOOL_NAME_MAX_LENGTH = 256
_SENSITIVE_METADATA_FRAGMENTS = ("authorization", "cookie", "password", "secret", "token", "api-key", "api_key", "credential")
_TOKEN_TEAMS_UNSET = object()


def _encrypt_metadata(metadata: Dict[str, str]) -> Dict[str, str]:
    """Encrypt new metadata values and transparently migrate legacy plaintext."""
    encryption = get_encryption_service(settings.auth_encryption_secret)
    return {key: value if encryption.is_encrypted(value) else encryption.encrypt_secret(value) for key, value in metadata.items()}


def _decrypt_metadata(metadata: Dict[str, str]) -> Dict[str, str]:
    """Decrypt stored metadata for an outbound gRPC call only."""
    encryption = get_encryption_service(settings.auth_encryption_secret)
    decrypted: Dict[str, str] = {}
    for key, value in metadata.items():
        plaintext = encryption.decrypt_secret_or_plaintext(value)
        if plaintext is not None:
            decrypted[key] = plaintext
    return decrypted


def _masked_call_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Mask sensitive response metadata before returning debugger diagnostics."""
    result: Dict[str, Any] = {"status": metadata.get("status")}
    for section in ("headers", "trailers"):
        values = metadata.get(section) or {}
        result[section] = {key: ["********"] if any(fragment in key.lower() for fragment in _SENSITIVE_METADATA_FRAGMENTS) else value for key, value in values.items()}
    return result


def _enforce_descriptor_limits(file_descriptor_bytes_set: set) -> None:
    """Enforce per-service descriptor count/size limits before storage.

    Args:
        file_descriptor_bytes_set: Set of raw FileDescriptorProto bytes collected during reflection.

    Raises:
        GrpcServiceError: If any limit is exceeded.
    """
    if len(file_descriptor_bytes_set) > _GRPC_MAX_DESCRIPTOR_COUNT:
        raise GrpcServiceError(f"Reflected descriptor count {len(file_descriptor_bytes_set)} exceeds limit {_GRPC_MAX_DESCRIPTOR_COUNT}")
    total = 0
    for blob in file_descriptor_bytes_set:
        if len(blob) > _GRPC_MAX_DESCRIPTOR_BYTES:
            raise GrpcServiceError(f"Reflected descriptor size {len(blob)} bytes exceeds per-descriptor limit {_GRPC_MAX_DESCRIPTOR_BYTES}")
        total += len(blob)
    if total > _GRPC_MAX_TOTAL_DESCRIPTOR_BYTES:
        raise GrpcServiceError(f"Reflected descriptor total size {total} bytes exceeds aggregate limit {_GRPC_MAX_TOTAL_DESCRIPTOR_BYTES}")


def _collect_reflection_descriptors(channel: Any, timeout_seconds: float) -> set[bytes]:
    """Collect reflection descriptors on a worker thread under one deadline."""
    deadline = time.monotonic() + timeout_seconds

    def remaining() -> float:
        value = deadline - time.monotonic()
        if value <= 0:
            raise TimeoutError("gRPC reflection deadline exceeded")
        return value

    stub = reflection_pb2_grpc.ServerReflectionStub(channel)
    request = reflection_pb2.ServerReflectionRequest(list_services="")  # pylint: disable=no-member
    response = stub.ServerReflectionInfo(iter([request]), timeout=remaining())

    service_names: List[str] = []
    for item in response:
        remaining()
        if item.HasField("list_services_response"):
            for reflected_service in item.list_services_response.service:
                if "ServerReflection" not in reflected_service.name:
                    service_names.append(reflected_service.name)

    descriptor_bytes: set[bytes] = set()
    for service_name in service_names:
        file_request = reflection_pb2.ServerReflectionRequest(file_containing_symbol=service_name)  # pylint: disable=no-member
        try:
            file_response = stub.ServerReflectionInfo(iter([file_request]), timeout=remaining())
            for item in file_response:
                remaining()
                if item.HasField("file_descriptor_response"):
                    descriptor_bytes.update(item.file_descriptor_response.file_descriptor_proto)
        except Exception as exc:
            # Preserve the existing best-effort behavior for one malformed
            # advertised service, but never swallow expiration of the shared
            # total deadline.
            remaining()
            logger.warning("Failed to get reflection details for %s: %s", service_name, exc)

    return descriptor_bytes


async def _collect_reflection_descriptors_async(channel: Any, timeout_seconds: float) -> set[bytes]:
    """Run blocking reflection without occupying the application event loop."""
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="grpc-reflection")
    future = executor.submit(_collect_reflection_descriptors, channel, timeout_seconds)
    deadline = time.monotonic() + timeout_seconds
    try:
        # Poll the concurrent future instead of relying on a loop cross-thread
        # callback. This also remains deterministic in restricted runtimes where
        # the loop's self-pipe notification is unavailable.
        while not future.done():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                future.cancel()
                raise TimeoutError("gRPC reflection deadline exceeded")
            await asyncio.sleep(min(0.01, remaining))
        return future.result()
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _validate_reflected_tool_name(tool_name: str) -> None:
    """Validate a tool name discovered via gRPC reflection.

    Reuses the same SecurityValidator rules applied to user-registered tools so reflected
    tool names cannot bypass length, character, or content-injection checks.

    Args:
        tool_name: ``service.method`` style identifier discovered via reflection.

    Raises:
        GrpcServiceError: If the name is empty, too long, or fails security validation.
    """
    # First-Party
    from mcpgateway.common.validators import SecurityValidator  # pylint: disable=import-outside-toplevel

    if not tool_name or not tool_name.strip():
        raise GrpcServiceError("Reflected tool name is empty")
    if len(tool_name) > _GRPC_TOOL_NAME_MAX_LENGTH:
        raise GrpcServiceError(f"Reflected tool name length {len(tool_name)} exceeds limit {_GRPC_TOOL_NAME_MAX_LENGTH}")
    try:
        SecurityValidator.validate_tool_name(tool_name)
    except ValueError as exc:
        raise GrpcServiceError(f"Reflected tool name '{tool_name}' rejected: {exc}") from exc


def _expected_input_schema(method: Dict[str, Any]) -> Dict[str, Any]:
    """Build the input schema a reflected method would produce as an MCP tool.

    Merges the protobuf-derived JSON schema with the ``x-grpc-*`` transport hints
    so the Tool Sync Preview matches what ``_sync_tools_from_reflection`` writes.

    Args:
        method: A catalog method entry (``input_type``, ``output_type``,
            streaming flags, ``input_schema``, ``request_example``).

    Returns:
        The normalized input schema dict.
    """
    schema = dict(method.get("input_schema") or {"type": "object", "properties": {}})
    schema.update(
        {
            "x-grpc-input-type": method.get("input_type", ""),
            "x-grpc-output-type": method.get("output_type", ""),
            "x-grpc-client-streaming": method.get("client_streaming", False),
            "x-grpc-server-streaming": method.get("server_streaming", False),
            "examples": [method.get("request_example", {})],
        }
    )
    return schema


class GrpcServiceNotFoundError(GrpcServiceError):
    """Raised when a requested gRPC service is not found."""


class GrpcServiceNameConflictError(GrpcServiceError):
    """Raised when a gRPC service name conflicts with an existing one."""

    def __init__(self, name: str, is_active: bool = True, service_id: Optional[str] = None):
        """Initialize the GrpcServiceNameConflictError.

        Args:
            name: The conflicting gRPC service name
            is_active: Whether the conflicting service is currently active
            service_id: The ID of the conflicting service, if known
        """
        self.name = name
        self.is_active = is_active
        self.service_id = service_id
        msg = f"gRPC service with name '{name}' already exists"
        if not is_active:
            msg += " (inactive)"
        if service_id:
            msg += f" (ID: {service_id})"
        super().__init__(msg)


class GrpcService:
    """Service for managing gRPC services with reflection-based discovery."""

    def __init__(self):
        """Initialize the gRPC service manager."""

    @staticmethod
    def _tool_cache_refs(tools: Any) -> List[tuple[Optional[str], str, Optional[str]]]:
        """Snapshot cache identifiers before a service mutation commits."""
        refs: List[tuple[Optional[str], str, Optional[str]]] = []
        try:
            related_tools = list(tools or [])
        except TypeError:
            return refs
        for tool in related_tools:
            name = getattr(tool, "name", None)
            if not isinstance(name, str) or not name:
                continue
            tool_id = getattr(tool, "id", None)
            gateway_id = getattr(tool, "gateway_id", None)
            refs.append(
                (
                    str(tool_id) if tool_id else None,
                    name,
                    str(gateway_id) if gateway_id else None,
                )
            )
        return refs

    async def _invalidate_tool_caches(self, refs: List[tuple[Optional[str], str, Optional[str]]]) -> None:
        """Invalidate registry, lookup, and result caches after a committed tool change."""
        normalized = sorted(set(refs), key=lambda item: (item[1], item[0] or "", item[2] or ""))
        if not normalized:
            return

        # Lazy imports keep cache initialization out of lightweight gRPC module imports.
        # First-Party
        from mcpgateway.cache.registry_cache import get_registry_cache  # pylint: disable=import-outside-toplevel
        from mcpgateway.cache.tool_lookup_cache import tool_lookup_cache  # pylint: disable=import-outside-toplevel
        from mcpgateway.cache.tool_result_cache import tool_result_cache  # pylint: disable=import-outside-toplevel

        try:
            await get_registry_cache().invalidate_tools()
            await asyncio.gather(
                *(tool_lookup_cache.invalidate(name, gateway_id=gateway_id) for _tool_id, name, gateway_id in normalized),
                *(tool_result_cache.invalidate_tool(tool_id) for tool_id, _name, _gateway_id in normalized if tool_id),
            )
        except Exception as exc:  # pragma: no cover - cache backends are best effort
            # The resource transaction has already committed. Match the existing
            # cache services' best-effort contract without misreporting the CRUD
            # operation as rolled back.
            logger.warning("Failed to invalidate caches for gRPC-derived tools: %s", exc)
    async def _build_team_visibility_clause(
        self,
        db: Session,
        user_email: Optional[str],
        team_id: Optional[str],
    ) -> Any:
        """Build an access-control WHERE clause for gRPC services.

        Mirrors :meth:`BaseService._apply_visibility_filter` semantics using the
        visibility/team_id/owner_email columns on :class:`GrpcService`.

        Args:
            db: Database session
            user_email: Caller email, or None for no identity
            team_id: Optional team filter

        Returns:
            SQLAlchemy clause, or None when no restriction applies
        """
        if team_id:
            user_teams = await TeamManagementService(db).get_user_teams(user_email) if user_email else []
            if not any(team.id == team_id for team in user_teams):
                return false()  # no access: deny everything

            access_conditions = [
                and_(
                    DbGrpcService.team_id == team_id,
                    DbGrpcService.visibility.in_(["team", "public"]),
                ),
                DbGrpcService.visibility == "public",  # globally public items are always visible
            ]
            if user_email:
                access_conditions.append(
                    and_(
                        DbGrpcService.team_id == team_id,
                        DbGrpcService.owner_email == user_email,
                        DbGrpcService.visibility == "private",
                    )
                )
            return or_(*access_conditions)

        if not user_email:
            return None

        user_teams = await TeamManagementService(db).get_user_teams(user_email)
        team_ids = [team.id for team in user_teams]
        clauses = [DbGrpcService.visibility == "public"]
        clauses.append(
            and_(
                DbGrpcService.visibility == "private",
                DbGrpcService.owner_email == user_email,
            )
        )
        if team_ids:
            clauses.append(
                and_(
                    DbGrpcService.team_id.in_(team_ids),
                    DbGrpcService.visibility.in_(["team", "public"]),
                )
            )
        return or_(*clauses)

    async def register_service(
        self,
        db: Session,
        service_data: GrpcServiceCreate,
        user_email: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> GrpcServiceRead:
        """Register a new gRPC service.

        Args:
            db: Database session
            service_data: gRPC service creation data
            user_email: Email of the user creating the service
            metadata: Additional metadata (IP, user agent, etc.)

        Returns:
            GrpcServiceRead: The created service

        Raises:
            GrpcServiceNameConflictError: If service name already exists
        """
        # Check for name conflicts
        existing = db.execute(select(DbGrpcService).where(DbGrpcService.name == service_data.name)).scalar_one_or_none()  # pylint: disable=comparison-with-callable

        if existing:
            raise GrpcServiceNameConflictError(name=service_data.name, is_active=existing.enabled, service_id=existing.id)

        # Create service
        db_service = DbGrpcService(
            name=service_data.name,
            target=service_data.target,
            description=service_data.description,
            reflection_enabled=service_data.reflection_enabled,
            tls_enabled=service_data.tls_enabled,
            tls_cert_path=service_data.tls_cert_path,
            tls_key_path=service_data.tls_key_path,
            grpc_metadata=_encrypt_metadata(service_data.grpc_metadata or {}),
            discovery_mode=service_data.discovery_mode,
            health_check_enabled=service_data.health_check_enabled,
            health_check_interval=service_data.health_check_interval,
            health_check_timeout=service_data.health_check_timeout,
            health_failure_threshold=service_data.health_failure_threshold,
            tags=service_data.tags or [],
            team_id=service_data.team_id,
            owner_email=user_email or service_data.owner_email,
            visibility=service_data.visibility,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        # Set audit metadata if provided
        if metadata:
            db_service.created_by = user_email
            db_service.created_from_ip = metadata.get("created_from_ip")
            db_service.created_via = metadata.get("created_via")
            db_service.created_user_agent = metadata.get("created_user_agent")

        db.add(db_service)
        db.commit()
        db.refresh(db_service)

        logger.info("Registered gRPC service: %s (target: %s)", db_service.name, db_service.target)

        # Perform initial reflection if enabled
        if db_service.reflection_enabled and db_service.discovery_mode != "artifact":
            try:
                await self._perform_reflection(db, db_service)
            except Exception as e:
                logger.warning("Initial reflection failed for %s: %s", db_service.name, e)

        return GrpcServiceRead.model_validate(db_service)

    async def list_services(
        self,
        db: Session,
        cursor: Optional[str] = None,
        include_inactive: bool = False,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        per_page: Optional[int] = None,
        user_email: Optional[str] = None,
        team_id: Optional[str] = None,
        token_teams: Any = _TOKEN_TEAMS_UNSET,
    ) -> Union[tuple[List[GrpcServiceRead], Optional[str]], Dict[str, Any]]:
        """List gRPC services with pagination and optional filtering.

        Args:
            db: Database session
            cursor: Pagination cursor for keyset pagination
            include_inactive: Include disabled services
            limit: Maximum number of services to return. None for default, 0 for unlimited
            page: Page number for page-based pagination (1-indexed). Mutually exclusive with cursor
            per_page: Items per page for page-based pagination
            user_email: Filter by user email for team access control
            team_id: Filter by team ID
            token_teams: Canonical token scope. When supplied (including
                explicit ``None`` for admin bypass), it takes precedence over
                legacy DB-membership expansion.

        Returns:
            If page is provided: Dict with {"data": [...], "pagination": {...}, "links": {...}}
            If cursor is provided or neither: tuple of (list of GrpcServiceRead objects, next_cursor)
        """
        # Build base query with ordering
        query = select(DbGrpcService).order_by(desc(DbGrpcService.created_at), desc(DbGrpcService.id))

        # Admin/API callers that resolved Layer 1 must never be widened back to
        # all DB memberships. Keep the legacy branch only for internal callers
        # that have not yet supplied a canonical token scope.
        if token_teams is not _TOKEN_TEAMS_UNSET:
            canonical_teams = token_teams if token_teams is None else list(token_teams)
            query = BaseService._apply_visibility_scope(  # pylint: disable=protected-access
                query,
                DbGrpcService,
                user_email=user_email,
                token_teams=canonical_teams,
                team_ids=canonical_teams or [],
                db=db,
            )
            if team_id:
                query = query.where(or_(DbGrpcService.team_id == team_id, DbGrpcService.visibility == "public"))
        elif user_email or team_id:
            team_filter = await self._build_team_visibility_clause(db, user_email, team_id)
            if team_filter is not None:
                query = query.where(team_filter)

        # Apply active filter
        if not include_inactive:
            query = query.where(DbGrpcService.enabled.is_(True))  # pylint: disable=singleton-comparison

        # Use unified pagination helper - handles both page and cursor pagination
        pag_result = await unified_paginate(
            db=db,
            query=query,
            page=page,
            per_page=per_page,
            cursor=cursor,
            limit=limit,
            base_url="/admin/grpc",
            query_params={"include_inactive": include_inactive} if include_inactive else {},
        )

        next_cursor = None
        # Extract services based on pagination type
        if page is not None:
            # Page-based: pag_result is a dict
            services_db = pag_result["data"]
        else:
            # Cursor-based: pag_result is a tuple
            services_db, next_cursor = pag_result

        # Fetch team names for the services
        team_ids_set = {s.team_id for s in services_db if s.team_id}
        team_map = {}
        if team_ids_set:
            teams = db.execute(select(EmailTeam.id, EmailTeam.name).where(EmailTeam.id.in_(team_ids_set), EmailTeam.is_active.is_(True))).all()
            team_map = {team.id: team.name for team in teams}

        db.commit()  # Release transaction to avoid idle-in-transaction

        # Convert to GrpcServiceRead
        result = []
        for s in services_db:
            try:
                s.team = team_map.get(s.team_id) if s.team_id else None
                result.append(GrpcServiceRead.model_validate(s))
            except (ValidationError, ValueError, KeyError, TypeError) as e:
                logger.exception("Failed to convert gRPC service %s (%s): %s", getattr(s, "id", "unknown"), getattr(s, "name", "unknown"), e)

        # Return appropriate format based on pagination type
        if page is not None:
            # Page-based format
            return {
                "data": result,
                "pagination": pag_result["pagination"],
                "links": pag_result["links"],
            }

        # Cursor-based format (tuple)
        return (result, next_cursor)

    async def get_service(
        self,
        db: Session,
        service_id: str,
        user_email: Optional[str] = None,
        token_teams: Any = _TOKEN_TEAMS_UNSET,
    ) -> GrpcServiceRead:
        """Get a specific gRPC service by ID.

        Args:
            db: Database session
            service_id: Service ID
            user_email: Email for team access control
            token_teams: Canonical token scope. When supplied, it takes
                precedence over legacy DB-membership expansion.

        Returns:
            The gRPC service

        Raises:
            GrpcServiceNotFoundError: If service not found or access denied
        """
        query = select(DbGrpcService).where(DbGrpcService.id == service_id)

        if token_teams is not _TOKEN_TEAMS_UNSET:
            canonical_teams = token_teams if token_teams is None else list(token_teams)
            query = BaseService._apply_visibility_scope(  # pylint: disable=protected-access
                query,
                DbGrpcService,
                user_email=user_email,
                token_teams=canonical_teams,
                team_ids=canonical_teams or [],
                db=db,
            )
        elif user_email:
            team_filter = await self._build_team_visibility_clause(db, user_email, None)
            if team_filter is not None:
                query = query.where(team_filter)

        service = db.execute(query).scalar_one_or_none()

        if not service:
            raise GrpcServiceNotFoundError(f"gRPC service with ID '{service_id}' not found")

        return GrpcServiceRead.model_validate(service)

    async def update_service(
        self,
        db: Session,
        service_id: str,
        service_data: GrpcServiceUpdate,
        user_email: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> GrpcServiceRead:
        """Update an existing gRPC service.

        Args:
            db: Database session
            service_id: Service ID to update
            service_data: Update data
            user_email: Email of user performing update
            metadata: Audit metadata

        Returns:
            Updated service

        Raises:
            GrpcServiceNotFoundError: If service not found
            GrpcServiceNameConflictError: If new name conflicts
        """
        service = db.execute(select(DbGrpcService).where(DbGrpcService.id == service_id)).scalar_one_or_none()

        if not service:
            raise GrpcServiceNotFoundError(f"gRPC service with ID '{service_id}' not found")

        tool_cache_refs = self._tool_cache_refs(service.tools)

        # Check name conflict if name is being changed
        if service_data.name and service_data.name != service.name:
            existing = db.execute(
                select(DbGrpcService).where(and_(DbGrpcService.name == service_data.name, DbGrpcService.id != service_id))
            ).scalar_one_or_none()  # pylint: disable=comparison-with-callable

            if existing:
                raise GrpcServiceNameConflictError(name=service_data.name, is_active=existing.enabled, service_id=existing.id)

        # Update fields
        update_data = service_data.model_dump(exclude_unset=True)
        if "grpc_metadata" in update_data:
            update_data["grpc_metadata"] = _encrypt_metadata(update_data["grpc_metadata"] or {})
        # Layer 1 invariant: visibility/team/owner changes on the parent service must propagate
        # to every child tool in the same transaction, or already-discovered tools will keep the
        # old token-scoping. Snapshot the previous values before mutation so we know what changed.
        scoping_fields = ("visibility", "team_id", "owner_email")
        previous_scoping = {f: getattr(service, f) for f in scoping_fields}
        for field, value in update_data.items():
            setattr(service, field, value)

        # Updating or synchronizing a service is the migration point for legacy
        # plaintext metadata values.
        service.grpc_metadata = _encrypt_metadata(service.grpc_metadata or {})

        service.updated_at = datetime.now(timezone.utc)

        # Set audit metadata
        if metadata and user_email:
            service.modified_by = user_email
            service.modified_from_ip = metadata.get("modified_from_ip")
            service.modified_via = metadata.get("modified_via")
            service.modified_user_agent = metadata.get("modified_user_agent")

        service.version += 1

        scoping_changed = {f: getattr(service, f) for f in scoping_fields if getattr(service, f) != previous_scoping[f]}
        if scoping_changed:
            db.execute(update(DbTool).where(DbTool.grpc_service_id == service.id).values(**scoping_changed, version=DbTool.version + 1))
            logger.info("Propagated %s change(s) on gRPC service %s to child tools", sorted(scoping_changed), service.name)

        db.commit()
        runtime_cache.invalidate_service(service_id)
        await self._invalidate_tool_caches(tool_cache_refs)
        db.refresh(service)

        logger.info("Updated gRPC service: %s", service.name)

        return GrpcServiceRead.model_validate(service)

    async def set_service_state(
        self,
        db: Session,
        service_id: str,
        activate: bool,
    ) -> GrpcServiceRead:
        """Set a gRPC service's enabled status.

        Args:
            db: Database session
            service_id: Service ID
            activate: True to enable, False to disable

        Returns:
            Updated service

        Raises:
            GrpcServiceNotFoundError: If service not found
        """
        service = db.execute(select(DbGrpcService).where(DbGrpcService.id == service_id)).scalar_one_or_none()

        if not service:
            raise GrpcServiceNotFoundError(f"gRPC service with ID '{service_id}' not found")

        tool_cache_refs = self._tool_cache_refs(service.tools)

        service.enabled = activate
        service.updated_at = datetime.now(timezone.utc)

        db.commit()
        runtime_cache.invalidate_service(service_id)
        await self._invalidate_tool_caches(tool_cache_refs)
        db.refresh(service)

        action = "activated" if activate else "deactivated"
        logger.info("gRPC service %s %s", service.name, action)

        return GrpcServiceRead.model_validate(service)

    async def delete_service(
        self,
        db: Session,
        service_id: str,
    ) -> None:
        """Delete a gRPC service and its associated tools.

        Explicitly deletes child tool records (metrics, server associations, tools)
        before deleting the service itself, following the same pattern as
        gateway_service.delete_gateway() to avoid FK constraint violations.

        Args:
            db: Database session
            service_id: Service ID to delete

        Raises:
            GrpcServiceNotFoundError: If service not found
        """
        service = db.execute(select(DbGrpcService).where(DbGrpcService.id == service_id)).scalar_one_or_none()

        if not service:
            raise GrpcServiceNotFoundError(f"gRPC service with ID '{service_id}' not found")

        # Explicitly delete tool children before deleting the service
        # (mirrors gateway_service.delete_gateway pattern)
        tool_cache_refs = self._tool_cache_refs(service.tools)
        tool_ids = [t.id for t in service.tools]
        if tool_ids:
            for i in range(0, len(tool_ids), 500):
                chunk = tool_ids[i : i + 500]
                db.execute(delete(ToolMetric).where(ToolMetric.tool_id.in_(chunk)))
                db.execute(delete(server_tool_association).where(server_tool_association.c.tool_id.in_(chunk)))
                db.execute(delete(DbTool).where(DbTool.id.in_(chunk)))

        db.delete(service)
        db.commit()
        runtime_cache.invalidate_service(service_id)
        await self._invalidate_tool_caches(tool_cache_refs)

        logger.info("Deleted gRPC service: %s (removed %d tools)", service.name, len(tool_ids))

    async def reflect_service(
        self,
        db: Session,
        service_id: str,
    ) -> GrpcServiceRead:
        """Trigger reflection on a gRPC service to discover services and methods.

        Args:
            db: Database session
            service_id: Service ID

        Returns:
            Updated service with reflection results

        Raises:
            GrpcServiceNotFoundError: If service not found
            GrpcServiceError: If reflection fails
        """
        service = db.execute(select(DbGrpcService).where(DbGrpcService.id == service_id)).scalar_one_or_none()

        if not service:
            raise GrpcServiceNotFoundError(f"gRPC service with ID '{service_id}' not found")

        try:
            await self._perform_reflection(db, service)
            logger.info("Reflection completed for %s: %s services, %s methods", service.name, service.service_count, service.method_count)
        except Exception as e:
            logger.error("Reflection failed for %s: %s", service.name, e)
            service.reachable = False
            if not getattr(service, "last_reflection_error", None):
                service.last_reflection_error = str(e)[:1000]
            db.commit()
            raise GrpcServiceError(f"Reflection failed: {str(e)}")

        return GrpcServiceRead.model_validate(service)

    async def get_service_methods(
        self,
        db: Session,
        service_id: str,
        user_email: Optional[str] = None,
        token_teams: Any = _TOKEN_TEAMS_UNSET,
    ) -> List[Dict[str, Any]]:
        """Get the list of methods for a gRPC service.

        Args:
            db: Database session
            service_id: Service ID
            user_email: Email for team access control
            token_teams: Canonical token scope. When supplied, it takes
                precedence over legacy DB-membership expansion.

        Returns:
            List of method descriptors

        Raises:
            GrpcServiceNotFoundError: If service not found
        """
        query = select(DbGrpcService).where(DbGrpcService.id == service_id)
        if token_teams is not _TOKEN_TEAMS_UNSET:
            canonical_teams = token_teams if token_teams is None else list(token_teams)
            query = BaseService._apply_visibility_scope(  # pylint: disable=protected-access
                query,
                DbGrpcService,
                user_email=user_email,
                token_teams=canonical_teams,
                team_ids=canonical_teams or [],
                db=db,
            )
        elif user_email:
            team_filter = await self._build_team_visibility_clause(db, user_email, None)
            if team_filter is not None:
                query = query.where(team_filter)

        service = db.execute(query).scalar_one_or_none()

        if not service:
            raise GrpcServiceNotFoundError(f"gRPC service with ID '{service_id}' not found")

        methods = []
        discovered = service.discovered_services or {}

        for service_name, service_desc in discovered.items():
            if service_name.startswith("_"):
                continue
            for method in service_desc.get("methods", []):
                methods.append(
                    {
                        "service": service_name,
                        "method": method["name"],
                        "full_name": f"{service_name}.{method['name']}",
                        "input_type": method.get("input_type"),
                        "output_type": method.get("output_type"),
                        "client_streaming": method.get("client_streaming", False),
                        "server_streaming": method.get("server_streaming", False),
                    }
                )

        return methods

    async def _perform_reflection(
        self,
        db: Session,
        service: DbGrpcService,
    ) -> None:
        """Perform gRPC server reflection to discover services.

        Args:
            db: Database session
            service: GrpcService model instance

        Raises:
            GrpcServiceError: If TLS certificate files not found
            Exception: If reflection or connection fails
        """
        tool_cache_refs = self._tool_cache_refs(service.tools)

        # Validate target address against SSRF
        _validate_grpc_target(service.target)

        # Create gRPC channel
        if service.tls_enabled:
            if service.tls_key_path and not service.tls_cert_path:
                raise GrpcServiceError("TLS key path requires a TLS certificate path")
            if service.tls_cert_path:
                # Validate TLS paths against traversal
                cert_path = _validate_tls_path(service.tls_cert_path, "TLS cert path")
                # Load TLS certificates
                try:
                    cert = await asyncio.to_thread(cert_path.read_bytes)
                    if service.tls_key_path:
                        key_path = _validate_tls_path(service.tls_key_path, "TLS key path")
                        key = await asyncio.to_thread(key_path.read_bytes)
                        credentials = grpc.ssl_channel_credentials(private_key=key, certificate_chain=cert)
                    else:
                        credentials = grpc.ssl_channel_credentials(root_certificates=cert)
                except FileNotFoundError as e:
                    raise GrpcServiceError(f"TLS certificate or key file not found: {e}")
            else:
                # Use default system certificates
                credentials = grpc.ssl_channel_credentials()

            channel = grpc.secure_channel(service.target, credentials)
        else:
            channel = grpc.insecure_channel(service.target)

        reflection_outcome = "error"
        span_context = create_child_span(
            "grpc.reflection",
            {"rpc.system": "grpc", "rpc.service": "grpc.reflection.v1alpha.ServerReflection", "grpc.service.id": service.id, "server.address": service.target},
        )
        span_context.__enter__()  # noqa  # Explicit lifecycle preserves the active exception for __exit__.
        try:  # pylint: disable=too-many-nested-blocks
            # grpc's reflection iterator is synchronous. Run it off the event
            # loop, with one absolute budget shared by listing and every detail
            # request so N services cannot multiply the configured timeout.
            reflection_timeout = float(settings.mcpgateway_grpc_timeout)
            file_descriptor_bytes_set = await _collect_reflection_descriptors_async(channel, reflection_timeout)

            _enforce_descriptor_limits(file_descriptor_bytes_set)

            descriptor_set = FileDescriptorSet()
            for descriptor_bytes in file_descriptor_bytes_set:
                descriptor_set.file.add().ParseFromString(descriptor_bytes)

            active_artifact_id = getattr(service, "active_artifact_id", None)
            active_artifact = db.get(GrpcSchemaArtifact, active_artifact_id) if isinstance(active_artifact_id, str) and active_artifact_id else None
            discovery_mode = getattr(service, "discovery_mode", None) or "auto"
            active_source_type = getattr(active_artifact, "source_type", None) if active_artifact is not None else None
            activate_reflection = discovery_mode == "reflection" or active_artifact is None or active_source_type in {"reflection", "legacy"}
            now = datetime.now(timezone.utc)
            if not file_descriptor_bytes_set:
                # Empty/partial reflection must never disable published tools.
                service.last_reflection = now
                if active_artifact is None:
                    service.discovered_services = {}
                    service.service_count = 0
                    service.method_count = 0
                    service.reachable = True
                    service.last_reflection_error = None
                else:
                    service.reachable = True  # transport worked; schema empty/partial
                    service.last_reflection_error = "Reflection returned empty descriptor set; keeping active schema"
            else:
                # Always land a candidate first; promote only when activation
                # policy allows and the catalog is non-empty.
                artifact = GrpcSchemaService.import_artifact(
                    db,
                    service,
                    descriptor_set.SerializeToString(),
                    "reflection.protoset",
                    created_by="system",
                    activate=False,
                    source_type="reflection",
                )
                service.candidate_artifact_id = artifact.id
                service.last_reflection = now
                service.reachable = True
                catalog = (artifact.source_info or {}).get("catalog") or {}
                method_count = sum(len(item.get("methods", [])) for item in catalog.values())
                if activate_reflection and method_count == 0 and (service.method_count or 0) > 0:
                    service.last_reflection_error = "Reflected schema has no methods; keeping active schema"
                elif activate_reflection and (method_count > 0 or active_artifact is None):
                    GrpcSchemaService.activate_artifact(db, service, artifact, catalog=catalog)
                    service.last_reflection_error = None
                    synced_tools = self._sync_tools_from_reflection(db, service)
                    tool_cache_refs.extend(self._tool_cache_refs(synced_tools))
                else:
                    # A conflicting uploaded artifact remains authoritative and drift is
                    # displayed for an administrator to resolve.
                    service.schema_drift = bool(service.active_schema_hash and service.active_schema_hash != artifact.content_hash)
                    service.last_reflection_error = None

            db.commit()
            await self._invalidate_tool_caches(tool_cache_refs)
            reflection_outcome = "success"

        except Exception as e:
            logger.error("Reflection error for %s: %s", service.target, e)
            # Undo any schema activation or tool sync started in this transaction,
            # then persist only the failure state so a partial publish never lands.
            db.rollback()
            service.reachable = False
            service.last_reflection_error = str(e)[:1000]
            db.commit()
            await self._invalidate_tool_caches(tool_cache_refs)
            raise

        finally:
            channel.close()
            grpc_reflection_counter.labels(service=service.slug, outcome=reflection_outcome).inc()
            span_context.__exit__(*sys.exc_info())

    def _sync_tools_from_reflection(
        self,
        db: Session,
        service: DbGrpcService,
    ) -> List[DbTool]:
        """Sync MCP tools from discovered gRPC methods.

        Removes stale tools and creates/updates tools for each discovered method.
        This follows the same pattern as gateway_service._update_or_create_tools().

        Args:
            db: Database session
            service: GrpcService model instance with populated discovered_services

        Returns:
            Tools whose lookup or result cache entries must be invalidated after commit.
        """
        discovered = service.discovered_services or {}

        # Build set of expected tool names from discovered methods
        expected_tool_names: set[str] = set()
        for svc_name, svc_desc in discovered.items():
            if svc_name.startswith("_"):
                continue
            for method in svc_desc.get("methods", []):
                expected_tool_names.add(f"{svc_name}.{method['name']}")

        # Fetch existing tools for this gRPC service
        existing_tools = db.execute(select(DbTool).where(DbTool.grpc_service_id == service.id)).scalars().all()
        existing_tools_map = {tool.original_name: tool for tool in existing_tools}

        # Last-line defense: an empty catalog over published tools would soft-disable
        # everything. Reflection now guards this upstream, but keep the sync itself safe.
        if not expected_tool_names and existing_tools:
            logger.warning(
                "Skipping tool sync for %s: empty catalog would disable %d existing tools",
                service.name,
                len(existing_tools),
            )
            return []

        # Preserve IDs, server relations, and metrics when a method disappears.
        # Reappearing methods are re-enabled below.
        stale_tools = [tool for tool in existing_tools if tool.original_name not in expected_tool_names]
        changed_tools: List[DbTool] = []
        for stale_tool in stale_tools:
            if stale_tool.enabled or not stale_tool.deprecated or stale_tool.reachable:
                stale_tool.enabled = False
                stale_tool.deprecated = True
                stale_tool.reachable = False
                stale_tool.version = (stale_tool.version or 1) + 1
                changed_tools.append(stale_tool)
        if stale_tools:
            logger.info("Deprecated %d stale tools for gRPC service %s", len(stale_tools), service.name)

        tools_created = 0
        tools_updated = 0
        tools_failed = 0
        for svc_name, svc_desc in discovered.items():
            if svc_name.startswith("_"):
                continue
            for method in svc_desc.get("methods", []):
                tool_name = f"{svc_name}.{method['name']}"
                # Client-streaming and bidi methods remain visible in the gRPC
                # catalog but are intentionally not executable MCP tools.
                if method.get("client_streaming"):
                    existing_tool = existing_tools_map.get(tool_name)
                    if existing_tool and (existing_tool.enabled or not existing_tool.deprecated):
                        existing_tool.enabled = False
                        existing_tool.deprecated = True
                        existing_tool.version = (existing_tool.version or 1) + 1
                        changed_tools.append(existing_tool)
                    continue
                # Per-tool try/except: a single bad method must not poison the whole sync.
                try:
                    _validate_reflected_tool_name(tool_name)
                    description = f"gRPC method {tool_name}"
                    input_schema = _expected_input_schema(method)
                    output_schema = method.get("output_schema")

                    existing_tool = existing_tools_map.get(tool_name)
                    if existing_tool:
                        changed = False
                        if existing_tool.original_description != description:
                            if existing_tool.description == existing_tool.original_description:
                                existing_tool.description = description
                            existing_tool.original_description = description
                            changed = True
                        if existing_tool.input_schema != input_schema:
                            existing_tool.input_schema = input_schema
                            changed = True
                        if existing_tool.output_schema != output_schema:
                            existing_tool.output_schema = output_schema
                            changed = True
                        if existing_tool.url != service.target:
                            existing_tool.url = service.target
                            changed = True
                        # Layer 1 invariant: parent visibility/team/owner must propagate to derived tools
                        # so token-scoping changes on the gRPC service take effect immediately.
                        if existing_tool.visibility != service.visibility:
                            existing_tool.visibility = service.visibility
                            changed = True
                        if existing_tool.team_id != service.team_id:
                            existing_tool.team_id = service.team_id
                            changed = True
                        if existing_tool.owner_email != service.owner_email:
                            existing_tool.owner_email = service.owner_email
                            changed = True
                        if not existing_tool.enabled or existing_tool.deprecated or not existing_tool.reachable:
                            existing_tool.enabled = True
                            existing_tool.deprecated = False
                            existing_tool.reachable = True
                            changed = True
                        if changed:
                            existing_tool.version = (existing_tool.version or 1) + 1
                            changed_tools.append(existing_tool)
                            tools_updated += 1
                    else:
                        db_tool = DbTool(
                            original_name=tool_name,
                            custom_name=tool_name,
                            custom_name_slug=slugify(tool_name),
                            display_name=generate_display_name(tool_name),
                            url=service.target,
                            original_description=description,
                            description=description,
                            integration_type="gRPC",
                            input_schema=input_schema,
                            output_schema=output_schema,
                            annotations={"readOnlyHint": False, "x-grpc-server-streaming": method.get("server_streaming", False)},
                            created_by="system",
                            created_via="grpc-schema-sync",
                            federation_source=service.name,
                            version=1,
                            team_id=service.team_id,
                            owner_email=service.owner_email,
                            visibility=service.visibility,
                            grpc_service_id=service.id,
                        )
                        db.add(db_tool)
                        changed_tools.append(db_tool)
                        tools_created += 1
                except Exception as tool_err:  # pylint: disable=broad-except
                    tools_failed += 1
                    logger.warning("Skipping tool %s for gRPC service %s: %s", tool_name, service.name, tool_err, exc_info=True)
                    continue

        logger.info(
            "Synced tools for gRPC service %s: %d created, %d updated, %d failed",
            service.name,
            tools_created,
            tools_updated,
            tools_failed,
        )
        return changed_tools

    async def import_schema(
        self,
        db: Session,
        service_id: str,
        payload: bytes,
        filename: str,
        user_email: Optional[str],
        activate: bool = True,
    ) -> GrpcSchemaArtifact:
        """Import and optionally activate a Proto, ZIP, or protoset artifact."""
        service = db.get(DbGrpcService, service_id)
        if service is None:
            raise GrpcServiceNotFoundError(f"gRPC service with ID '{service_id}' not found")
        tool_cache_refs = self._tool_cache_refs(service.tools)
        artifact = GrpcSchemaService.import_artifact(db, service, payload, filename, user_email, activate=activate)
        if activate:
            service.grpc_metadata = _encrypt_metadata(service.grpc_metadata or {})
            synced_tools = self._sync_tools_from_reflection(db, service)
            tool_cache_refs.extend(self._tool_cache_refs(synced_tools))
        db.commit()
        runtime_cache.invalidate_service(service_id)
        await self._invalidate_tool_caches(tool_cache_refs)
        return artifact

    async def list_schemas(self, db: Session, service_id: str) -> List[GrpcSchemaArtifact]:
        """List immutable schema versions newest first."""
        if db.get(DbGrpcService, service_id) is None:
            raise GrpcServiceNotFoundError(f"gRPC service with ID '{service_id}' not found")
        return list(db.execute(select(GrpcSchemaArtifact).where(GrpcSchemaArtifact.grpc_service_id == service_id).order_by(GrpcSchemaArtifact.version.desc())).scalars())

    async def activate_schema(self, db: Session, service_id: str, artifact_id: str) -> GrpcSchemaArtifact:
        """Activate a descriptor version and synchronize executable methods."""
        service = db.get(DbGrpcService, service_id)
        artifact = db.get(GrpcSchemaArtifact, artifact_id)
        if service is None:
            raise GrpcServiceNotFoundError(f"gRPC service with ID '{service_id}' not found")
        if artifact is None or artifact.grpc_service_id != service_id:
            raise GrpcServiceError("Schema artifact not found for this service")
        tool_cache_refs = self._tool_cache_refs(service.tools)
        GrpcSchemaService.activate_artifact(db, service, artifact)
        service.grpc_metadata = _encrypt_metadata(service.grpc_metadata or {})
        synced_tools = self._sync_tools_from_reflection(db, service)
        tool_cache_refs.extend(self._tool_cache_refs(synced_tools))
        db.commit()
        runtime_cache.invalidate_service(service_id)
        await self._invalidate_tool_caches(tool_cache_refs)
        db.refresh(artifact)
        return artifact

    async def diff_schemas(self, db: Session, service_id: str, left_id: str, right_id: str) -> GrpcSchemaDiff:
        """Compare two schema versions owned by a service."""
        left = db.get(GrpcSchemaArtifact, left_id)
        right = db.get(GrpcSchemaArtifact, right_id)
        if left is None or right is None or left.grpc_service_id != service_id or right.grpc_service_id != service_id:
            raise GrpcServiceError("Both schema artifacts must belong to the requested service")
        return GrpcSchemaService.diff(left, right)

    async def invoke_method(
        self,
        db: Session,
        service_id: str,
        method_name: str,
        request_data: Dict[str, Any],
        timeout: Optional[float] = None,
        metadata_override: Optional[Dict[str, str]] = None,
        stream_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
        capture_call_metadata: bool = False,
    ) -> Dict[str, Any]:
        """Invoke a gRPC method on a registered service.

        Args:
            db: Database session
            service_id: Service ID
            method_name: Full method name (service.Method)
            request_data: JSON request data
            timeout: Per-call deadline in seconds. Falls back to
                ``settings.mcpgateway_grpc_timeout`` when ``None``.
            metadata_override: Per-call debug metadata, never persisted.
            stream_callback: Optional debugger callback receiving server-stream items as they arrive.
            capture_call_metadata: Include masked headers/trailers/status in debugger output.

        Returns:
            JSON response data

        Raises:
            GrpcServiceNotFoundError: If service not found
            GrpcServiceError: If invocation fails
            asyncio.TimeoutError: If the call exceeds ``timeout``
        """
        service = db.execute(select(DbGrpcService).where(DbGrpcService.id == service_id)).scalar_one_or_none()

        if not service:
            raise GrpcServiceNotFoundError(f"gRPC service with ID '{service_id}' not found")

        if not service.enabled:
            raise GrpcServiceError(f"Service '{service.name}' is disabled")

        # Parse method name (service.Method format)
        if "." not in method_name:
            raise GrpcServiceError(f"Invalid method name '{method_name}', expected 'service.Method' format")

        parts = method_name.rsplit(".", 1)
        service_name = ".".join(parts[:-1]) if len(parts) > 1 else parts[0]
        method = parts[-1]

        # Validate target address and TLS paths before connecting
        _validate_grpc_target(service.target)
        if service.tls_cert_path:
            _validate_tls_path(service.tls_cert_path, "TLS cert path")
        if service.tls_key_path:
            _validate_tls_path(service.tls_key_path, "TLS key path")

        discovered = service.discovered_services or {}
        stored_descriptors = GrpcSchemaService.descriptors_for_service(db, service)
        has_stored_descriptors = bool(stored_descriptors)

        effective_timeout = timeout if timeout is not None else float(settings.mcpgateway_grpc_timeout)
        call_started = time.monotonic()
        call_deadline = call_started + effective_timeout

        def remaining_timeout() -> float:
            remaining = call_deadline - time.monotonic()
            if remaining <= 0:
                raise asyncio.TimeoutError
            return remaining

        grpc_status = "ERROR"
        span_context = create_child_span(
            "grpc.client.call",
            {
                "rpc.system": "grpc",
                "rpc.service": service_name,
                "rpc.method": method,
                "server.address": service.target,
                "grpc.service.id": service.id,
            },
        )
        span_context.__enter__()  # noqa  # Explicit lifecycle preserves the active exception for __exit__.

        cache_enabled = bool(getattr(settings, "grpc_runtime_cache_enabled", True)) and GRPC_AVAILABLE
        cache_entry = None
        cache_key = None
        endpoint = None
        try:
            if cache_enabled:
                # Reuse the channel for every registered gRPC service. Persisted
                # descriptor services also share their descriptor pool and message
                # classes. Reflection-only services deliberately keep a fresh pool
                # per call so a live schema change cannot collide with descriptors
                # already loaded by a prior invocation on the same channel.
                metadata_decrypted = _decrypt_metadata(service.grpc_metadata or {})
                cache_key = runtime_cache.key_for(
                    service.id,
                    getattr(service, "active_schema_hash", None) or getattr(service, "reflected_schema_hash", None),
                    service.target,
                    service.tls_enabled,
                    service.tls_cert_path,
                    service.tls_key_path,
                    metadata_decrypted,
                )
                cache_entry = runtime_cache.acquire(
                    cache_key,
                    service.target,
                    service.tls_enabled,
                    service.tls_cert_path,
                    service.tls_key_path,
                )
                endpoint = translate_grpc.GrpcEndpoint(
                    target=service.target,
                    reflection_enabled=not has_stored_descriptors,
                    tls_enabled=service.tls_enabled,
                    tls_cert_path=service.tls_cert_path,
                    tls_key_path=service.tls_key_path,
                    metadata={**metadata_decrypted, **(metadata_override or {})},
                    channel=cache_entry.channel,
                    pool=cache_entry.pool if has_stored_descriptors else None,
                    method_class_cache=cache_entry.method_classes if has_stored_descriptors else None,
                    owns_channel=False,
                )
            else:
                endpoint = translate_grpc.GrpcEndpoint(
                    target=service.target,
                    reflection_enabled=not has_stored_descriptors,
                    tls_enabled=service.tls_enabled,
                    tls_cert_path=service.tls_cert_path,
                    tls_key_path=service.tls_key_path,
                    metadata={**_decrypt_metadata(service.grpc_metadata or {}), **(metadata_override or {})},
                )

            # Both the asyncio wrapper AND the underlying gRPC call get the deadline so a slow
            # upstream cannot keep an executor thread alive after the coroutine is cancelled.
            startup_timeout = remaining_timeout()
            await asyncio.wait_for(endpoint.start(timeout=startup_timeout, trusted_local=True), timeout=startup_timeout)

            if has_stored_descriptors:
                endpoint.load_file_descriptors(stored_descriptors)
                # Strip metadata pseudo-keys (e.g. ``_file_descriptors``); they are not real services.
                endpoint._services = {k: v for k, v in discovered.items() if not k.startswith("_")}  # pylint: disable=protected-access

            method_info = next((item for item in discovered.get(service_name, {}).get("methods", []) if item.get("name") == method), None)
            if method_info and method_info.get("client_streaming"):
                raise GrpcServiceError("Client-streaming and bidirectional gRPC methods are not supported")
            if method_info and method_info.get("server_streaming"):

                async def collect_stream() -> Dict[str, Any]:
                    """Collect at most 100 server-stream items before returning to MCP."""
                    items: List[Dict[str, Any]] = []
                    truncated = False
                    async for item in endpoint.invoke_streaming(service_name, method, request_data, timeout=remaining_timeout()):
                        if len(items) >= 100:
                            truncated = True
                            break
                        items.append(item)
                        if stream_callback is not None:
                            await stream_callback(item)
                    return {"items": items, "truncated": truncated}

                response = await asyncio.wait_for(collect_stream(), timeout=remaining_timeout())
                if capture_call_metadata:
                    response["_grpc"] = _masked_call_metadata(endpoint.get_call_metadata())
                grpc_status = "OK"
                return response

            invoke_timeout = remaining_timeout()
            response = await asyncio.wait_for(endpoint.invoke(service_name, method, request_data, timeout=invoke_timeout), timeout=invoke_timeout)
            if capture_call_metadata:
                response = {**response, "_grpc": _masked_call_metadata(endpoint.get_call_metadata())}
            grpc_status = "OK"
            return response

        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError:
            grpc_status = "DEADLINE_EXCEEDED"
            logger.warning("gRPC call %s on %s timed out after %ss", method_name, service.name, effective_timeout)
            raise
        except (GrpcServiceNotFoundError, GrpcServiceError):
            raise
        except Exception as e:
            if GRPC_AVAILABLE and isinstance(e, grpc.RpcError):
                status = e.code()  # pylint: disable=no-member
                if status is not None:
                    grpc_status = getattr(status, "name", str(status))
            logger.error("Failed to invoke %s on %s: %s", method_name, service.name, e, exc_info=True)
            raise GrpcServiceError(f"Method invocation failed: {e}") from e

        finally:
            grpc_status_context.set(grpc_status)
            if cache_entry is not None and cache_key is not None:
                # Injected channels are owned by the cache; balance the acquire
                # so an evicted entry can be closed once idle.
                runtime_cache.release(cache_key, cache_entry)
            elif endpoint is not None:
                await endpoint.close()
            grpc_client_calls_counter.labels(service=service.slug, method=method_name, status=grpc_status).inc()
            grpc_client_duration_histogram.labels(service=service.slug, method=method_name).observe(time.monotonic() - call_started)
            span_context.__exit__(*sys.exc_info())
