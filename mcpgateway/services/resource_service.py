# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/resource_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Resource Service Implementation.
This module implements resource management according to the MCP specification.
It handles:
- Resource registration and retrieval
- Resource templates and URI handling
- Resource subscriptions and updates
- Content type management
- Active/inactive resource management

Examples:
    >>> from mcpgateway.services.resource_service import ResourceService, ResourceError
    >>> service = ResourceService()
    >>> isinstance(service._event_service, EventService)
    True
"""

# Standard
from datetime import datetime, timezone
import mimetypes
import os
import re
import ssl
import time
from typing import Any, AsyncGenerator, Dict, List, Optional, Union
import uuid

# Third-Party
import httpx
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client
import parse
from sqlalchemy import and_, case, delete, desc, Float, func, not_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.common.models import ResourceContent, ResourceTemplate, TextContent
from mcpgateway.common.validators import SecurityValidator
from mcpgateway.config import settings
from mcpgateway.db import EmailTeam, fresh_db_session
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import Resource as DbResource
from mcpgateway.db import ResourceMetric
from mcpgateway.db import ResourceSubscription as DbSubscription
from mcpgateway.db import server_resource_association
from mcpgateway.observability import create_span
from mcpgateway.schemas import ResourceCreate, ResourceMetrics, ResourceRead, ResourceSubscription, ResourceUpdate, TopPerformer
from mcpgateway.services.audit_trail_service import get_audit_trail_service
from mcpgateway.services.event_service import EventService
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.oauth_manager import OAuthManager
from mcpgateway.services.observability_service import current_trace_id, ObservabilityService
from mcpgateway.services.structured_logger import get_structured_logger
from mcpgateway.utils.metrics_common import build_top_performers
from mcpgateway.utils.pagination import decode_cursor, encode_cursor
from mcpgateway.utils.services_auth import decode_auth
from mcpgateway.utils.sqlalchemy_modifier import json_contains_expr
from mcpgateway.utils.validate_signature import validate_signature

# Plugin support imports (conditional)
try:
    # First-Party
    from mcpgateway.plugins.framework import GlobalContext, PluginContextTable, PluginManager, ResourceHookType, ResourcePostFetchPayload, ResourcePreFetchPayload

    PLUGINS_AVAILABLE = True
except ImportError:
    PLUGINS_AVAILABLE = False

# Cache import (lazy to avoid circular dependencies)
_REGISTRY_CACHE = None


def _get_registry_cache():
    """Get registry cache singleton lazily.

    Returns:
        RegistryCache instance.
    """
    global _REGISTRY_CACHE  # pylint: disable=global-statement
    if _REGISTRY_CACHE is None:
        # First-Party
        from mcpgateway.cache.registry_cache import registry_cache  # pylint: disable=import-outside-toplevel

        _REGISTRY_CACHE = registry_cache
    return _REGISTRY_CACHE


# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

# Initialize structured logger and audit trail for resource operations
structured_logger = get_structured_logger("resource_service")
audit_trail = get_audit_trail_service()


class ResourceError(Exception):
    """Base class for resource-related errors."""


class ResourceNotFoundError(ResourceError):
    """Raised when a requested resource is not found."""


class ResourceURIConflictError(ResourceError):
    """Raised when a resource URI conflicts with existing (active or inactive) resource."""

    def __init__(self, uri: str, enabled: bool = True, resource_id: Optional[int] = None, visibility: str = "public") -> None:
        """Initialize the error with resource information.

        Args:
            uri: The conflicting resource URI
            enabled: Whether the existing resource is active
            resource_id: ID of the existing resource if available
            visibility: Visibility status of the resource
        """
        self.uri = uri
        self.enabled = enabled
        self.resource_id = resource_id
        message = f"{visibility.capitalize()} Resource already exists with URI: {uri}"
        logger.info(f"ResourceURIConflictError: {message}")
        if not enabled:
            message += f" (currently inactive, ID: {resource_id})"
        super().__init__(message)


class ResourceValidationError(ResourceError):
    """Raised when resource validation fails."""


class ResourceService:
    """Service for managing resources.

    Handles:
    - Resource registration and retrieval
    - Resource templates and URIs
    - Resource subscriptions
    - Content type detection
    - Active/inactive status management
    """

    def __init__(self) -> None:
        """Initialize the resource service."""
        self._event_service = EventService(channel_name="mcpgateway:resource_events")
        self._template_cache: Dict[str, ResourceTemplate] = {}
        self.oauth_manager = OAuthManager(request_timeout=int(os.getenv("OAUTH_REQUEST_TIMEOUT", "30")), max_retries=int(os.getenv("OAUTH_MAX_RETRIES", "3")))

        # Initialize plugin manager if plugins are enabled in settings
        self._plugin_manager = None
        if PLUGINS_AVAILABLE:
            try:
                # Support env overrides for testability without reloading settings
                env_flag = os.getenv("PLUGINS_ENABLED")
                if env_flag is not None:
                    env_enabled = env_flag.strip().lower() in {"1", "true", "yes", "on"}
                    plugins_enabled = env_enabled
                else:
                    plugins_enabled = settings.plugins_enabled

                config_file = os.getenv("PLUGIN_CONFIG_FILE", settings.plugin_config_file)

                if plugins_enabled:
                    self._plugin_manager = PluginManager(config_file)
                    logger.info(f"Plugin manager initialized for ResourceService with config: {config_file}")
            except Exception as e:
                logger.warning(f"Plugin manager initialization failed in ResourceService: {e}")
                self._plugin_manager = None

        # Initialize mime types
        mimetypes.init()

    async def initialize(self) -> None:
        """Initialize the service."""
        logger.info("Initializing resource service")
        await self._event_service.initialize()

    async def shutdown(self) -> None:
        """Shutdown the service."""
        # Clear subscriptions
        await self._event_service.shutdown()
        logger.info("Resource service shutdown complete")

    async def get_top_resources(self, db: Session, limit: Optional[int] = 5) -> List[TopPerformer]:
        """Retrieve the top-performing resources based on execution count.

        Queries the database to get resources with their metrics, ordered by the number of executions
        in descending order. Uses the resource URI as the name field for TopPerformer objects.
        Returns a list of TopPerformer objects containing resource details and performance metrics.
        Results are cached for performance.

        Args:
            db (Session): Database session for querying resource metrics.
            limit (Optional[int]): Maximum number of resources to return. Defaults to 5.

        Returns:
            List[TopPerformer]: A list of TopPerformer objects, each containing:
                - id: Resource ID.
                - name: Resource URI (used as the name field).
                - execution_count: Total number of executions.
                - avg_response_time: Average response time in seconds, or None if no metrics.
                - success_rate: Success rate percentage, or None if no metrics.
                - last_execution: Timestamp of the last execution, or None if no metrics.
        """
        # Check cache first (if enabled)
        # First-Party
        from mcpgateway.cache.metrics_cache import is_cache_enabled, metrics_cache  # pylint: disable=import-outside-toplevel

        effective_limit = limit or 5
        cache_key = f"top_resources:{effective_limit}"

        if is_cache_enabled():
            cached = metrics_cache.get(cache_key)
            if cached is not None:
                return cached

        query = (
            db.query(
                DbResource.id,
                DbResource.uri.label("name"),  # Using URI as the name field for TopPerformer
                func.count(ResourceMetric.id).label("execution_count"),  # pylint: disable=not-callable
                func.avg(ResourceMetric.response_time).label("avg_response_time"),  # pylint: disable=not-callable
                case(
                    (
                        func.count(ResourceMetric.id) > 0,  # pylint: disable=not-callable
                        func.sum(case((ResourceMetric.is_success.is_(True), 1), else_=0)).cast(Float) / func.count(ResourceMetric.id) * 100,  # pylint: disable=not-callable
                    ),
                    else_=None,
                ).label("success_rate"),
                func.max(ResourceMetric.timestamp).label("last_execution"),  # pylint: disable=not-callable
            )
            .outerjoin(ResourceMetric)
            .group_by(DbResource.id, DbResource.uri)
            .order_by(desc("execution_count"))
        )

        query = query.limit(effective_limit)

        results = query.all()
        top_performers = build_top_performers(results)

        # Cache the result (if enabled)
        if is_cache_enabled():
            metrics_cache.set(cache_key, top_performers)

        return top_performers

    def _convert_resource_to_read(self, resource: DbResource, include_metrics: bool = False) -> ResourceRead:
        """
        Converts a DbResource instance into a ResourceRead model, optionally including aggregated metrics.

        Args:
            resource (DbResource): The ORM instance of the resource.
            include_metrics (bool): Whether to include metrics in the result. Defaults to False.
                Set to False for list operations to avoid N+1 query issues.

        Returns:
            ResourceRead: The Pydantic model representing the resource, optionally including aggregated metrics.

        Examples:
            >>> from types import SimpleNamespace
            >>> from datetime import datetime, timezone
            >>> svc = ResourceService()
            >>> now = datetime.now(timezone.utc)
            >>> # Fake metrics
            >>> m1 = SimpleNamespace(is_success=True, response_time=0.1, timestamp=now)
            >>> m2 = SimpleNamespace(is_success=False, response_time=0.3, timestamp=now)
            >>> r = SimpleNamespace(
            ...     id="ca627760127d409080fdefc309147e08", uri='res://x', name='R', description=None, mime_type='text/plain', size=123,
            ...     created_at=now, updated_at=now, enabled=True, tags=[{"id": "t", "label": "T"}], metrics=[m1, m2]
            ... )
            >>> out = svc._convert_resource_to_read(r, include_metrics=True)
            >>> out.metrics.total_executions
            2
            >>> out.metrics.successful_executions
            1
        """
        resource_dict = resource.__dict__.copy()
        # Remove SQLAlchemy state and any pre-existing 'metrics' attribute
        resource_dict.pop("_sa_instance_state", None)
        resource_dict.pop("metrics", None)

        # Ensure required base fields are present even if SQLAlchemy hasn't loaded them into __dict__ yet
        resource_dict["id"] = getattr(resource, "id", resource_dict.get("id"))
        resource_dict["uri"] = getattr(resource, "uri", resource_dict.get("uri"))
        resource_dict["name"] = getattr(resource, "name", resource_dict.get("name"))
        resource_dict["description"] = getattr(resource, "description", resource_dict.get("description"))
        resource_dict["mime_type"] = getattr(resource, "mime_type", resource_dict.get("mime_type"))
        resource_dict["size"] = getattr(resource, "size", resource_dict.get("size"))
        resource_dict["created_at"] = getattr(resource, "created_at", resource_dict.get("created_at"))
        resource_dict["updated_at"] = getattr(resource, "updated_at", resource_dict.get("updated_at"))
        resource_dict["is_active"] = getattr(resource, "is_active", resource_dict.get("is_active"))
        resource_dict["enabled"] = getattr(resource, "enabled", resource_dict.get("enabled"))

        # Compute aggregated metrics from the resource's metrics list (only if requested)
        if include_metrics:
            total = len(resource.metrics) if hasattr(resource, "metrics") and resource.metrics is not None else 0
            successful = sum(1 for m in resource.metrics if m.is_success) if total > 0 else 0
            failed = sum(1 for m in resource.metrics if not m.is_success) if total > 0 else 0
            failure_rate = (failed / total) if total > 0 else 0.0
            min_rt = min((m.response_time for m in resource.metrics), default=None) if total > 0 else None
            max_rt = max((m.response_time for m in resource.metrics), default=None) if total > 0 else None
            avg_rt = (sum(m.response_time for m in resource.metrics) / total) if total > 0 else None
            last_time = max((m.timestamp for m in resource.metrics), default=None) if total > 0 else None

            resource_dict["metrics"] = {
                "total_executions": total,
                "successful_executions": successful,
                "failed_executions": failed,
                "failure_rate": failure_rate,
                "min_response_time": min_rt,
                "max_response_time": max_rt,
                "avg_response_time": avg_rt,
                "last_execution_time": last_time,
            }
        else:
            resource_dict["metrics"] = None

        resource_dict["tags"] = resource.tags or []
        resource_dict["team"] = getattr(resource, "team", None)

        # Include metadata fields for proper API response
        resource_dict["created_by"] = getattr(resource, "created_by", None)
        resource_dict["modified_by"] = getattr(resource, "modified_by", None)
        resource_dict["created_at"] = getattr(resource, "created_at", None)
        resource_dict["updated_at"] = getattr(resource, "updated_at", None)
        resource_dict["version"] = getattr(resource, "version", None)
        return ResourceRead.model_validate(resource_dict)

    def _get_team_name(self, db: Session, team_id: Optional[str]) -> Optional[str]:
        """Retrieve the team name given a team ID.

        Args:
            db (Session): Database session for querying teams.
            team_id (Optional[str]): The ID of the team.

        Returns:
            Optional[str]: The name of the team if found, otherwise None.
        """
        if not team_id:
            return None
        team = db.query(EmailTeam).filter(EmailTeam.id == team_id, EmailTeam.is_active.is_(True)).first()
        db.commit()  # Release transaction to avoid idle-in-transaction
        return team.name if team else None

    async def register_resource(
        self,
        db: Session,
        resource: ResourceCreate,
        created_by: Optional[str] = None,
        created_from_ip: Optional[str] = None,
        created_via: Optional[str] = None,
        created_user_agent: Optional[str] = None,
        import_batch_id: Optional[str] = None,
        federation_source: Optional[str] = None,
        team_id: Optional[str] = None,
        owner_email: Optional[str] = None,
        visibility: Optional[str] = "public",
    ) -> ResourceRead:
        """Register a new resource.

        Args:
            db: Database session
            resource: Resource creation schema
            created_by: User who created the resource
            created_from_ip: IP address of the creator
            created_via: Method used to create the resource (e.g., API, UI)
            created_user_agent: User agent of the creator
            import_batch_id: Optional batch ID for bulk imports
            federation_source: Optional source of the resource if federated
            team_id (Optional[str]): Team ID to assign the resource to.
            owner_email (Optional[str]): Email of the user who owns this resource.
            visibility (str): Resource visibility level (private, team, public).

        Returns:
            Created resource information

        Raises:
            IntegrityError: If a database integrity error occurs.
            ResourceURIConflictError: If a resource with the same URI already exists.
            ResourceError: For other resource registration errors

        Examples:
            >>> from mcpgateway.services.resource_service import ResourceService
            >>> from unittest.mock import MagicMock, AsyncMock
            >>> from mcpgateway.schemas import ResourceRead
            >>> service = ResourceService()
            >>> db = MagicMock()
            >>> resource = MagicMock()
            >>> db.execute.return_value.scalar_one_or_none.return_value = None
            >>> db.add = MagicMock()
            >>> db.commit = MagicMock()
            >>> db.refresh = MagicMock()
            >>> service._notify_resource_added = AsyncMock()
            >>> service._convert_resource_to_read = MagicMock(return_value='resource_read')
            >>> ResourceRead.model_validate = MagicMock(return_value='resource_read')
            >>> import asyncio
            >>> asyncio.run(service.register_resource(db, resource))
            'resource_read'
        """
        try:
            logger.info(f"Registering resource: {resource.uri}")
            # Check for existing server with the same uri
            if visibility.lower() == "public":
                logger.info(f"visibility:: {visibility}")
                # Check for existing public resource with the same uri
                existing_resource = db.execute(select(DbResource).where(DbResource.uri == resource.uri, DbResource.visibility == "public")).scalar_one_or_none()
                if existing_resource:
                    raise ResourceURIConflictError(resource.uri, enabled=existing_resource.enabled, resource_id=existing_resource.id, visibility=existing_resource.visibility)
            elif visibility.lower() == "team" and team_id:
                # Check for existing team resource with the same uri
                existing_resource = db.execute(select(DbResource).where(DbResource.uri == resource.uri, DbResource.visibility == "team", DbResource.team_id == team_id)).scalar_one_or_none()
                if existing_resource:
                    raise ResourceURIConflictError(resource.uri, enabled=existing_resource.enabled, resource_id=existing_resource.id, visibility=existing_resource.visibility)

            # Detect mime type if not provided
            mime_type = resource.mime_type
            if not mime_type:
                mime_type = self._detect_mime_type(resource.uri, resource.content)

            # Determine content storage
            is_text = mime_type and mime_type.startswith("text/") or isinstance(resource.content, str)

            # Create DB model
            db_resource = DbResource(
                uri=resource.uri,
                name=resource.name,
                description=resource.description,
                mime_type=mime_type,
                uri_template=resource.uri_template,
                text_content=resource.content if is_text else None,
                binary_content=(resource.content.encode() if is_text and isinstance(resource.content, str) else resource.content if isinstance(resource.content, bytes) else None),
                size=len(resource.content) if resource.content else 0,
                tags=resource.tags or [],
                created_by=created_by,
                created_from_ip=created_from_ip,
                created_via=created_via,
                created_user_agent=created_user_agent,
                import_batch_id=import_batch_id,
                federation_source=federation_source,
                version=1,
                # Team scoping fields - use schema values if provided, otherwise fallback to parameters
                team_id=getattr(resource, "team_id", None) or team_id,
                owner_email=getattr(resource, "owner_email", None) or owner_email or created_by,
                visibility=getattr(resource, "visibility", None) or visibility,
            )

            # Add to DB
            db.add(db_resource)
            db.commit()
            db.refresh(db_resource)

            # Notify subscribers
            await self._notify_resource_added(db_resource)

            logger.info(f"Registered resource: {resource.uri}")

            # Structured logging: Audit trail for resource creation
            audit_trail.log_action(
                user_id=created_by or "system",
                action="create_resource",
                resource_type="resource",
                resource_id=str(db_resource.id),
                resource_name=db_resource.name,
                user_email=owner_email,
                team_id=team_id,
                client_ip=created_from_ip,
                user_agent=created_user_agent,
                new_values={
                    "uri": db_resource.uri,
                    "name": db_resource.name,
                    "visibility": visibility,
                    "mime_type": db_resource.mime_type,
                },
                context={
                    "created_via": created_via,
                    "import_batch_id": import_batch_id,
                    "federation_source": federation_source,
                },
                db=db,
            )

            # Structured logging: Log successful resource creation
            structured_logger.log(
                level="INFO",
                message="Resource created successfully",
                event_type="resource_created",
                component="resource_service",
                user_id=created_by,
                user_email=owner_email,
                team_id=team_id,
                resource_type="resource",
                resource_id=str(db_resource.id),
                custom_fields={
                    "resource_uri": db_resource.uri,
                    "resource_name": db_resource.name,
                    "visibility": visibility,
                },
                db=db,
            )

            db_resource.team = self._get_team_name(db, db_resource.team_id)
            return self._convert_resource_to_read(db_resource)
        except IntegrityError as ie:
            logger.error(f"IntegrityErrors in group: {ie}")

            # Structured logging: Log database integrity error
            structured_logger.log(
                level="ERROR",
                message="Resource creation failed due to database integrity error",
                event_type="resource_creation_failed",
                component="resource_service",
                user_id=created_by,
                user_email=owner_email,
                error=ie,
                custom_fields={
                    "resource_uri": resource.uri,
                },
                db=db,
            )
            raise ie
        except ResourceURIConflictError as rce:
            logger.error(f"ResourceURIConflictError in group: {resource.uri}")

            # Structured logging: Log URI conflict error
            structured_logger.log(
                level="WARNING",
                message="Resource creation failed due to URI conflict",
                event_type="resource_uri_conflict",
                component="resource_service",
                user_id=created_by,
                user_email=owner_email,
                custom_fields={
                    "resource_uri": resource.uri,
                    "visibility": visibility,
                },
                db=db,
            )
            raise rce
        except Exception as e:
            db.rollback()

            # Structured logging: Log generic resource creation failure
            structured_logger.log(
                level="ERROR",
                message="Resource creation failed",
                event_type="resource_creation_failed",
                component="resource_service",
                user_id=created_by,
                user_email=owner_email,
                error=e,
                custom_fields={
                    "resource_uri": resource.uri,
                },
                db=db,
            )
            raise ResourceError(f"Failed to register resource: {str(e)}")

    async def register_resources_bulk(
        self,
        db: Session,
        resources: List[ResourceCreate],
        created_by: Optional[str] = None,
        created_from_ip: Optional[str] = None,
        created_via: Optional[str] = None,
        created_user_agent: Optional[str] = None,
        import_batch_id: Optional[str] = None,
        federation_source: Optional[str] = None,
        team_id: Optional[str] = None,
        owner_email: Optional[str] = None,
        visibility: Optional[str] = "public",
        conflict_strategy: str = "skip",
    ) -> Dict[str, Any]:
        """Register multiple resources in bulk with a single commit.

        This method provides significant performance improvements over individual
        resource registration by:
        - Using db.add_all() instead of individual db.add() calls
        - Performing a single commit for all resources
        - Batch conflict detection
        - Chunking for very large imports (>500 items)

        Args:
            db: Database session
            resources: List of resource creation schemas
            created_by: Username who created these resources
            created_from_ip: IP address of creator
            created_via: Creation method (ui, api, import, federation)
            created_user_agent: User agent of creation request
            import_batch_id: UUID for bulk import operations
            federation_source: Source gateway for federated resources
            team_id: Team ID to assign the resources to
            owner_email: Email of the user who owns these resources
            visibility: Resource visibility level (private, team, public)
            conflict_strategy: How to handle conflicts (skip, update, rename, fail)

        Returns:
            Dict with statistics:
                - created: Number of resources created
                - updated: Number of resources updated
                - skipped: Number of resources skipped
                - failed: Number of resources that failed
                - errors: List of error messages

        Raises:
            ResourceError: If bulk registration fails critically

        Examples:
            >>> from mcpgateway.services.resource_service import ResourceService
            >>> from unittest.mock import MagicMock
            >>> service = ResourceService()
            >>> db = MagicMock()
            >>> resources = [MagicMock(), MagicMock()]
            >>> import asyncio
            >>> try:
            ...     result = asyncio.run(service.register_resources_bulk(db, resources))
            ... except Exception:
            ...     pass
        """
        if not resources:
            return {"created": 0, "updated": 0, "skipped": 0, "failed": 0, "errors": []}

        stats = {"created": 0, "updated": 0, "skipped": 0, "failed": 0, "errors": []}

        # Process in chunks to avoid memory issues and SQLite parameter limits
        chunk_size = 500

        for chunk_start in range(0, len(resources), chunk_size):
            chunk = resources[chunk_start : chunk_start + chunk_size]

            try:
                # Batch check for existing resources to detect conflicts
                resource_uris = [resource.uri for resource in chunk]

                if visibility.lower() == "public":
                    existing_resources_query = select(DbResource).where(DbResource.uri.in_(resource_uris), DbResource.visibility == "public")
                elif visibility.lower() == "team" and team_id:
                    existing_resources_query = select(DbResource).where(DbResource.uri.in_(resource_uris), DbResource.visibility == "team", DbResource.team_id == team_id)
                else:
                    # Private resources - check by owner
                    existing_resources_query = select(DbResource).where(DbResource.uri.in_(resource_uris), DbResource.visibility == "private", DbResource.owner_email == (owner_email or created_by))

                existing_resources = db.execute(existing_resources_query).scalars().all()
                existing_resources_map = {resource.uri: resource for resource in existing_resources}

                resources_to_add = []
                resources_to_update = []

                for resource in chunk:
                    try:
                        # Use provided parameters or schema values
                        resource_team_id = team_id if team_id is not None else getattr(resource, "team_id", None)
                        resource_owner_email = owner_email or getattr(resource, "owner_email", None) or created_by
                        resource_visibility = visibility if visibility is not None else getattr(resource, "visibility", "public")

                        existing_resource = existing_resources_map.get(resource.uri)

                        if existing_resource:
                            # Handle conflict based on strategy
                            if conflict_strategy == "skip":
                                stats["skipped"] += 1
                                continue
                            if conflict_strategy == "update":
                                # Update existing resource
                                existing_resource.name = resource.name
                                existing_resource.description = resource.description
                                existing_resource.mime_type = resource.mime_type
                                existing_resource.size = getattr(resource, "size", None)
                                existing_resource.uri_template = resource.uri_template
                                existing_resource.tags = resource.tags or []
                                existing_resource.modified_by = created_by
                                existing_resource.modified_from_ip = created_from_ip
                                existing_resource.modified_via = created_via
                                existing_resource.modified_user_agent = created_user_agent
                                existing_resource.updated_at = datetime.now(timezone.utc)
                                existing_resource.version = (existing_resource.version or 1) + 1

                                resources_to_update.append(existing_resource)
                                stats["updated"] += 1
                            elif conflict_strategy == "rename":
                                # Create with renamed resource
                                new_uri = f"{resource.uri}_imported_{int(datetime.now().timestamp())}"
                                db_resource = DbResource(
                                    uri=new_uri,
                                    name=resource.name,
                                    description=resource.description,
                                    mime_type=resource.mime_type,
                                    size=getattr(resource, "size", None),
                                    uri_template=resource.uri_template,
                                    gateway_id=getattr(resource, "gateway_id", None),
                                    tags=resource.tags or [],
                                    created_by=created_by,
                                    created_from_ip=created_from_ip,
                                    created_via=created_via,
                                    created_user_agent=created_user_agent,
                                    import_batch_id=import_batch_id,
                                    federation_source=federation_source,
                                    version=1,
                                    team_id=resource_team_id,
                                    owner_email=resource_owner_email,
                                    visibility=resource_visibility,
                                )
                                resources_to_add.append(db_resource)
                                stats["created"] += 1
                            elif conflict_strategy == "fail":
                                stats["failed"] += 1
                                stats["errors"].append(f"Resource URI conflict: {resource.uri}")
                                continue
                        else:
                            # Create new resource
                            db_resource = DbResource(
                                uri=resource.uri,
                                name=resource.name,
                                description=resource.description,
                                mime_type=resource.mime_type,
                                size=getattr(resource, "size", None),
                                uri_template=resource.uri_template,
                                gateway_id=getattr(resource, "gateway_id", None),
                                tags=resource.tags or [],
                                created_by=created_by,
                                created_from_ip=created_from_ip,
                                created_via=created_via,
                                created_user_agent=created_user_agent,
                                import_batch_id=import_batch_id,
                                federation_source=federation_source,
                                version=1,
                                team_id=resource_team_id,
                                owner_email=resource_owner_email,
                                visibility=resource_visibility,
                            )
                            resources_to_add.append(db_resource)
                            stats["created"] += 1

                    except Exception as e:
                        stats["failed"] += 1
                        stats["errors"].append(f"Failed to process resource {resource.uri}: {str(e)}")
                        logger.warning(f"Failed to process resource {resource.uri} in bulk operation: {str(e)}")
                        continue

                # Bulk add new resources
                if resources_to_add:
                    db.add_all(resources_to_add)

                # Commit the chunk
                db.commit()

                # Refresh resources for notifications and audit trail
                for db_resource in resources_to_add:
                    db.refresh(db_resource)
                    # Notify subscribers
                    await self._notify_resource_added(db_resource)

                # Log bulk audit trail entry
                if resources_to_add or resources_to_update:
                    audit_trail.log_action(
                        user_id=created_by or "system",
                        action="bulk_create_resources" if resources_to_add else "bulk_update_resources",
                        resource_type="resource",
                        resource_id=import_batch_id or "bulk_operation",
                        resource_name=f"Bulk operation: {len(resources_to_add)} created, {len(resources_to_update)} updated",
                        user_email=owner_email,
                        team_id=team_id,
                        client_ip=created_from_ip,
                        user_agent=created_user_agent,
                        new_values={
                            "resources_created": len(resources_to_add),
                            "resources_updated": len(resources_to_update),
                            "visibility": visibility,
                        },
                        context={
                            "created_via": created_via,
                            "import_batch_id": import_batch_id,
                            "federation_source": federation_source,
                            "conflict_strategy": conflict_strategy,
                        },
                        db=db,
                    )

                logger.info(f"Bulk registered {len(resources_to_add)} resources, updated {len(resources_to_update)} resources in chunk")

            except Exception as e:
                db.rollback()
                logger.error(f"Failed to process chunk in bulk resource registration: {str(e)}")
                stats["failed"] += len(chunk)
                stats["errors"].append(f"Chunk processing failed: {str(e)}")
                continue

        # Final structured logging
        structured_logger.log(
            level="INFO",
            message="Bulk resource registration completed",
            event_type="resources_bulk_created",
            component="resource_service",
            user_id=created_by,
            user_email=owner_email,
            team_id=team_id,
            resource_type="resource",
            custom_fields={
                "resources_created": stats["created"],
                "resources_updated": stats["updated"],
                "resources_skipped": stats["skipped"],
                "resources_failed": stats["failed"],
                "total_resources": len(resources),
                "visibility": visibility,
                "conflict_strategy": conflict_strategy,
            },
            db=db,
        )

        return stats

    async def list_resources(self, db: Session, include_inactive: bool = False, cursor: Optional[str] = None, tags: Optional[List[str]] = None) -> tuple[List[ResourceRead], Optional[str]]:
        """
        Retrieve a list of registered resources from the database with pagination support.

        This method retrieves resources from the database and converts them into a list
        of ResourceRead objects. It supports filtering out inactive resources based on the
        include_inactive parameter and cursor-based pagination.

        Args:
            db (Session): The SQLAlchemy database session.
            include_inactive (bool): If True, include inactive resources in the result.
                Defaults to False.
            cursor (Optional[str], optional): An opaque cursor token for pagination.
                Opaque base64-encoded string containing last item's ID.
            tags (Optional[List[str]]): Filter resources by tags. If provided, only resources with at least one matching tag will be returned.

        Returns:
            tuple[List[ResourceRead], Optional[str]]: Tuple containing:
                - List of resources for current page
                - Next cursor token if more results exist, None otherwise

        Examples:
            >>> from mcpgateway.services.resource_service import ResourceService
            >>> from unittest.mock import MagicMock
            >>> service = ResourceService()
            >>> db = MagicMock()
            >>> resource_read = MagicMock()
            >>> service._convert_resource_to_read = MagicMock(return_value=resource_read)
            >>> db.execute.return_value.scalars.return_value.all.return_value = [MagicMock()]
            >>> import asyncio
            >>> resources, next_cursor = asyncio.run(service.list_resources(db))
            >>> isinstance(resources, list)
            True

            With tags filter:
            >>> db2 = MagicMock()
            >>> bind = MagicMock()
            >>> bind.dialect = MagicMock()
            >>> bind.dialect.name = "sqlite"           # or "postgresql" / "mysql"
            >>> db2.get_bind.return_value = bind
            >>> db2.execute.return_value.scalars.return_value.all.return_value = [MagicMock()]
            >>> result2, _ = asyncio.run(service.list_resources(db2, tags=['api']))
            >>> isinstance(result2, list)
            True
        """
        # Check cache for first page only (cursor=None)
        cache = _get_registry_cache()
        if cursor is None:
            filters_hash = cache.hash_filters(include_inactive=include_inactive, tags=sorted(tags) if tags else None)
            cached = await cache.get("resources", filters_hash)
            if cached is not None:
                # Reconstruct ResourceRead objects from cached dicts
                cached_resources = [ResourceRead.model_validate(r) for r in cached["resources"]]
                return (cached_resources, cached.get("next_cursor"))

        page_size = settings.pagination_default_page_size
        query = select(DbResource).where(DbResource.uri_template.is_(None)).order_by(DbResource.id)  # Consistent ordering for cursor pagination

        # Decode cursor to get last_id if provided
        last_id = None
        if cursor:
            try:
                cursor_data = decode_cursor(cursor)
                last_id = cursor_data.get("id")
                logger.debug(f"Decoded cursor: last_id={last_id}")
            except ValueError as e:
                logger.warning(f"Invalid cursor, ignoring: {e}")

        # Apply cursor filter (WHERE id > last_id)
        if last_id:
            query = query.where(DbResource.id > last_id)

        if not include_inactive:
            query = query.where(DbResource.enabled)

        # Add tag filtering if tags are provided
        if tags:
            query = query.where(json_contains_expr(db, DbResource.tags, tags, match_any=True))

        # Fetch page_size + 1 to determine if there are more results
        query = query.limit(page_size + 1)
        resources = db.execute(query).scalars().all()

        # Check if there are more results
        has_more = len(resources) > page_size
        if has_more:
            resources = resources[:page_size]  # Trim to page_size

        # Batch fetch team names to avoid N+1 queries
        team_ids = {r.team_id for r in resources if r.team_id}
        team_map = {}
        if team_ids:
            teams = db.execute(select(EmailTeam.id, EmailTeam.name).where(EmailTeam.id.in_(team_ids), EmailTeam.is_active.is_(True))).all()
            team_map = {str(team.id): team.name for team in teams}

        db.commit()  # Release transaction to avoid idle-in-transaction

        # Convert to ResourceRead objects (skip metrics to avoid N+1 queries)
        result = []
        for t in resources:
            t.team = team_map.get(str(t.team_id)) if t.team_id else None
            result.append(self._convert_resource_to_read(t, include_metrics=False))

        # Generate next_cursor if there are more results
        next_cursor = None
        if has_more and result:
            last_resource = resources[-1]  # Get last DB object
            next_cursor = encode_cursor({"id": last_resource.id})
            logger.debug(f"Generated next_cursor for id={last_resource.id}")

        # Cache first page results
        if cursor is None:
            try:
                cache_data = {"resources": [r.model_dump(mode="json") for r in result], "next_cursor": next_cursor}
                await cache.set("resources", cache_data, filters_hash)
            except AttributeError:
                pass  # Skip caching if result objects don't support model_dump (e.g., in doctests)

        return (result, next_cursor)

    async def list_resources_for_user(
        self, db: Session, user_email: str, team_id: Optional[str] = None, visibility: Optional[str] = None, include_inactive: bool = False, skip: int = 0, limit: int = 100
    ) -> List[ResourceRead]:
        """
        List resources user has access to with team filtering.

        Args:
            db: Database session
            user_email: Email of the user requesting resources
            team_id: Optional team ID to filter by specific team
            visibility: Optional visibility filter (private, team, public)
            include_inactive: Whether to include inactive resources
            skip: Number of resources to skip for pagination
            limit: Maximum number of resources to return

        Returns:
            List[ResourceRead]: Resources the user has access to

        Examples:
            >>> from unittest.mock import MagicMock
            >>> import asyncio
            >>> service = ResourceService()
            >>> db = MagicMock()
            >>> # Patch out TeamManagementService so it doesn't run real logic
            >>> import mcpgateway.services.resource_service as _rs
            >>> class FakeTeamService:
            ...     def __init__(self, db): pass
            ...     async def get_user_teams(self, email): return []
            >>> _rs.TeamManagementService = FakeTeamService
            >>> # Force DB to return one fake row with a 'team' attribute
            >>> class FakeResource:
            ...     team_id = None
            >>> fake_resource = FakeResource()
            >>> db.execute.return_value.scalars.return_value.all.return_value = [fake_resource]
            >>> service._convert_resource_to_read = MagicMock(return_value="converted")
            >>> asyncio.run(service.list_resources_for_user(db, "user@example.com"))
            ['converted']

            Without team_id (default/public access):
            >>> db2 = MagicMock()
            >>> class FakeResource2:
            ...     team_id = None
            >>> fake_resource2 = FakeResource2()
            >>> db2.execute.return_value.scalars.return_value.all.return_value = [fake_resource2]
            >>> service._convert_resource_to_read = MagicMock(return_value="converted2")
            >>> out2 = asyncio.run(service.list_resources_for_user(db2, "user@example.com"))
            >>> out2
            ['converted2']
        """
        # First-Party
        from mcpgateway.services.team_management_service import TeamManagementService  # pylint: disable=import-outside-toplevel

        # Build query following existing patterns from list_resources()
        team_service = TeamManagementService(db)
        user_teams = await team_service.get_user_teams(user_email)
        team_ids = [team.id for team in user_teams]

        # Build query following existing patterns from list_resources()
        query = select(DbResource)

        # Apply active/inactive filter
        if not include_inactive:
            query = query.where(DbResource.enabled)

        if team_id:
            if team_id not in team_ids:
                return []  # No access to team

            access_conditions = []
            # Filter by specific team
            access_conditions.append(and_(DbResource.team_id == team_id, DbResource.visibility.in_(["team", "public"])))

            access_conditions.append(and_(DbResource.team_id == team_id, DbResource.owner_email == user_email))

            query = query.where(or_(*access_conditions))
        else:
            # Get user's accessible teams
            # Build access conditions following existing patterns
            access_conditions = []
            # 1. User's personal resources (owner_email matches)
            access_conditions.append(DbResource.owner_email == user_email)
            # 2. Team resources where user is member
            if team_ids:
                access_conditions.append(and_(DbResource.team_id.in_(team_ids), DbResource.visibility.in_(["team", "public"])))
            # 3. Public resources (if visibility allows)
            access_conditions.append(DbResource.visibility == "public")

            query = query.where(or_(*access_conditions))

        # Apply visibility filter if specified
        if visibility:
            query = query.where(DbResource.visibility == visibility)

        # Apply pagination following existing patterns
        query = query.offset(skip).limit(limit)

        resources = db.execute(query).scalars().all()

        # Batch fetch team names to avoid N+1 queries
        resource_team_ids = {r.team_id for r in resources if r.team_id}
        team_map = {}
        if resource_team_ids:
            teams = db.execute(select(EmailTeam.id, EmailTeam.name).where(EmailTeam.id.in_(resource_team_ids), EmailTeam.is_active.is_(True))).all()
            team_map = {str(team.id): team.name for team in teams}

        db.commit()  # Release transaction to avoid idle-in-transaction

        result = []
        for t in resources:
            t.team = team_map.get(str(t.team_id)) if t.team_id else None
            result.append(self._convert_resource_to_read(t, include_metrics=False))
        return result

    async def list_server_resources(self, db: Session, server_id: str, include_inactive: bool = False) -> List[ResourceRead]:
        """
        Retrieve a list of registered resources from the database.

        This method retrieves resources from the database and converts them into a list
        of ResourceRead objects. It supports filtering out inactive resources based on the
        include_inactive parameter. The cursor parameter is reserved for future pagination support
        but is currently not implemented.

        Args:
            db (Session): The SQLAlchemy database session.
            server_id (str): Server ID
            include_inactive (bool): If True, include inactive resources in the result.
                Defaults to False.

        Returns:
            List[ResourceRead]: A list of resources represented as ResourceRead objects.

        Examples:
            >>> from mcpgateway.services.resource_service import ResourceService
            >>> from unittest.mock import MagicMock
            >>> service = ResourceService()
            >>> db = MagicMock()
            >>> resource_read = MagicMock()
            >>> service._convert_resource_to_read = MagicMock(return_value=resource_read)
            >>> db.execute.return_value.scalars.return_value.all.return_value = [MagicMock()]
            >>> import asyncio
            >>> result = asyncio.run(service.list_server_resources(db, 'server1'))
            >>> isinstance(result, list)
            True
            >>> # Include inactive branch
            >>> result = asyncio.run(service.list_server_resources(db, 'server1', include_inactive=True))
            >>> isinstance(result, list)
            True
        """
        logger.debug(f"Listing resources for server_id: {server_id}, include_inactive: {include_inactive}")
        query = (
            select(DbResource)
            .join(server_resource_association, DbResource.id == server_resource_association.c.resource_id)
            .where(DbResource.uri_template.is_(None))
            .where(server_resource_association.c.server_id == server_id)
        )
        if not include_inactive:
            query = query.where(DbResource.enabled)
        # Cursor-based pagination logic can be implemented here in the future.
        resources = db.execute(query).scalars().all()

        # Batch fetch team names to avoid N+1 queries
        resource_team_ids = {r.team_id for r in resources if r.team_id}
        team_map = {}
        if resource_team_ids:
            teams = db.execute(select(EmailTeam.id, EmailTeam.name).where(EmailTeam.id.in_(resource_team_ids), EmailTeam.is_active.is_(True))).all()
            team_map = {str(team.id): team.name for team in teams}

        db.commit()  # Release transaction to avoid idle-in-transaction

        result = []
        for t in resources:
            t.team = team_map.get(str(t.team_id)) if t.team_id else None
            result.append(self._convert_resource_to_read(t, include_metrics=False))
        return result

    async def _record_resource_metric(self, db: Session, resource: DbResource, start_time: float, success: bool, error_message: Optional[str]) -> None:
        """
        Records a metric for a resource access.

        Args:
            db: Database session
            resource: The resource that was accessed
            start_time: Monotonic start time of the access
            success: True if successful, False otherwise
            error_message: Error message if failed, None otherwise
        """
        end_time = time.monotonic()
        response_time = end_time - start_time

        metric = ResourceMetric(
            resource_id=resource.id,
            response_time=response_time,
            is_success=success,
            error_message=error_message,
        )
        db.add(metric)
        db.commit()

    async def _record_invoke_resource_metric(self, db: Session, resource_id: str, start_time: float, success: bool, error_message: Optional[str]) -> None:
        """
        Records a metric for invoking resource.

        Args:
            db: Database Session
            resource_id: unique identifier to access & invoke resource
            start_time: Monotonic start time of the access
            success: True if successful, False otherwise
            error_message: Error message if failed, None otherwise
        """
        end_time = time.monotonic()
        response_time = end_time - start_time

        metric = ResourceMetric(
            resource_id=resource_id,
            response_time=response_time,
            is_success=success,
            error_message=error_message,
        )
        db.add(metric)
        db.commit()

    def create_ssl_context(self, ca_certificate: str) -> ssl.SSLContext:
        """Create an SSL context with the provided CA certificate.

        Args:
            ca_certificate: CA certificate in PEM format

        Returns:
            ssl.SSLContext: Configured SSL context
        """
        ctx = ssl.create_default_context()
        ctx.load_verify_locations(cadata=ca_certificate)
        return ctx

    async def invoke_resource(self, db: Session, resource_id: str, resource_uri: str, resource_template_uri: Optional[str] = None) -> Any:
        """
        Invoke a resource via its configured gateway using SSE or StreamableHTTP transport.

        This method determines the correct URI to invoke, loads the associated resource
        and gateway from the database, validates certificates if applicable, prepares
        authentication headers (OAuth, header-based, or none), and then connects to
        the gateway to read the resource using the appropriate transport.

        The function supports:
        - CA certificate validation / SSL context creation
        - OAuth client-credentials and authorization-code flow
        - Header-based auth
        - SSE transport gateways
        - StreamableHTTP transport gateways

        Args:
            db (Session):
                SQLAlchemy session for retrieving resource and gateway information.
            resource_id (str):
                ID of the resource to invoke.
            resource_uri (str):
                Direct resource URI configured for the resource.
            resource_template_uri (Optional[str]):
                URI from the template. Overrides `resource_uri` when provided.

        Returns:
            Any: The text content returned by the remote resource, or ``None`` if the
            gateway could not be contacted or an error occurred.

        Raises:
            Exception: Any unhandled internal errors (e.g., DB issues).

        ---
        Doctest Examples
        ----------------

        >>> class FakeDB:
        ...     "Simple DB stub returning fake resource and gateway rows."
        ...     def execute(self, query):
        ...         class Result:
        ...             def scalar_one_or_none(self):
        ...                 # Return fake objects with the needed attributes
        ...                 class FakeResource:
        ...                     id = "res123"
        ...                     name = "Demo Resource"
        ...                     gateway_id = "gw1"
        ...                 return FakeResource()
        ...         return Result()

        >>> class FakeGateway:
        ...     id = "gw1"
        ...     name = "Fake Gateway"
        ...     url = "https://fake.gateway"
        ...     ca_certificate = None
        ...     ca_certificate_sig = None
        ...     transport = "sse"
        ...     auth_type = None
        ...     auth_value = {}

        >>> # Monkeypatch the DB lookup for gateway
        >>> def fake_execute_gateway(self, query):
        ...     class Result:
        ...         def scalar_one_or_none(self_inner):
        ...             return FakeGateway()
        ...     return Result()

        >>> FakeDB.execute_gateway = fake_execute_gateway

        >>> class FakeService:
        ...     "Service stub replacing network calls with predictable outputs."
        ...     async def invoke_resource(self, db, resource_id, resource_uri, resource_template_uri=None):
        ...         # Represent the behavior of a successful SSE response.
        ...         return "hello from gateway"

        >>> svc = FakeService()
        >>> import asyncio
        >>> asyncio.run(svc.invoke_resource(FakeDB(), "res123", "/test"))
        'hello from gateway'

        ---
        Example: Template URI overrides resource URI
        --------------------------------------------

        >>> class FakeService2(FakeService):
        ...     async def invoke_resource(self, db, resource_id, resource_uri, resource_template_uri=None):
        ...         if resource_template_uri:
        ...             return f"using template: {resource_template_uri}"
        ...         return f"using direct: {resource_uri}"

        >>> svc2 = FakeService2()
        >>> asyncio.run(svc2.invoke_resource(FakeDB(), "res123", "/direct", "/template"))
        'using template: /template'

        """
        uri = None
        if resource_uri and resource_template_uri:
            uri = resource_template_uri
        elif resource_uri:
            uri = resource_uri

        logger.info(f"Invoking the resource: {uri}")
        gateway_id = None
        resource_info = None
        resource_info = db.execute(select(DbResource).where(DbResource.id == resource_id)).scalar_one_or_none()
        user_email = settings.platform_admin_email

        if resource_info:
            gateway_id = getattr(resource_info, "gateway_id", None)
            resource_name = getattr(resource_info, "name", None)
            if gateway_id:
                gateway = db.execute(select(DbGateway).where(DbGateway.id == gateway_id)).scalar_one_or_none()

                start_time = time.monotonic()
                success = False
                error_message = None

                # Create database span for observability dashboard
                trace_id = current_trace_id.get()
                db_span_id = None
                db_span_ended = False
                observability_service = ObservabilityService() if trace_id else None

                if trace_id and observability_service:
                    try:
                        db_span_id = observability_service.start_span(
                            db=db,
                            trace_id=trace_id,
                            name="invoke.resource",
                            attributes={
                                "resource.name": resource_name if resource_name else "unknown",
                                "resource.id": str(resource_id) if resource_id else "unknown",
                                "resource.uri": str(uri) or "unknown",
                                "gateway.transport": getattr(gateway, "transport") or "uknown",
                                "gateway.url": getattr(gateway, "url") or "unknown",
                            },
                        )
                        logger.debug(f"✓ Created resource.read span: {db_span_id} for resource: {resource_id} & {uri}")
                    except Exception as e:
                        logger.warning(f"Failed to start the observability span for invoking resource: {e}")
                        db_span_id = None

                with create_span(
                    "invoke.resource",
                    {
                        "resource.name": resource_name if resource_name else "unknown",
                        "resource.id": str(resource_id) if resource_id else "unknown",
                        "resource.uri": str(uri) or "unknown",
                        "gateway.transport": getattr(gateway, "transport") or "uknown",
                        "gateway.url": getattr(gateway, "url") or "unknown",
                    },
                ) as span:
                    valid = False
                    if gateway.ca_certificate:
                        if settings.enable_ed25519_signing:
                            public_key_pem = settings.ed25519_public_key
                            valid = validate_signature(gateway.ca_certificate.encode(), gateway.ca_certificate_sig, public_key_pem)
                        else:
                            valid = True

                    if valid:
                        ssl_context = self.create_ssl_context(gateway.ca_certificate)
                    else:
                        ssl_context = None

                    def _get_httpx_client_factory(
                        headers: dict[str, str] | None = None,
                        timeout: httpx.Timeout | None = None,
                        auth: httpx.Auth | None = None,
                    ) -> httpx.AsyncClient:
                        """Factory function to create httpx.AsyncClient with optional CA certificate.

                        Args:
                            headers: Optional headers for the client
                            timeout: Optional timeout for the client
                            auth: Optional auth for the client

                        Returns:
                            httpx.AsyncClient: Configured HTTPX async client
                        """
                        return httpx.AsyncClient(
                            verify=ssl_context if ssl_context else True,  # pylint: disable=cell-var-from-loop
                            follow_redirects=True,
                            headers=headers,
                            timeout=timeout or httpx.Timeout(30.0),
                            auth=auth,
                        )

                    try:
                        # Handle different authentication types
                        headers = {}
                        if gateway and gateway.auth_type == "oauth" and gateway.oauth_config:
                            grant_type = gateway.oauth_config.get("grant_type", "client_credentials")

                            if grant_type == "authorization_code":
                                # For Authorization Code flow, try to get stored tokens
                                try:
                                    # First-Party
                                    from mcpgateway.services.token_storage_service import TokenStorageService  # pylint: disable=import-outside-toplevel

                                    token_storage = TokenStorageService(db)
                                    # Get user-specific OAuth token
                                    # if not user_email:
                                    #     if span:
                                    #         span.set_attribute("health.status", "unhealthy")
                                    #         span.set_attribute("error.message", "User email required for OAuth token")
                                    #     await self._handle_gateway_failure(gateway)

                                    access_token: str = await token_storage.get_user_token(gateway.id, user_email)

                                    if access_token:
                                        headers["Authorization"] = f"Bearer {access_token}"
                                    else:
                                        if span:
                                            span.set_attribute("health.status", "unhealthy")
                                            span.set_attribute("error.message", "No valid OAuth token for user")
                                        # await self._handle_gateway_failure(gateway)

                                except Exception as e:
                                    logger.error(f"Failed to obtain stored OAuth token for gateway {gateway.name}: {e}")
                                    if span:
                                        span.set_attribute("health.status", "unhealthy")
                                        span.set_attribute("error.message", "Failed to obtain stored OAuth token")
                                    # await self._handle_gateway_failure(gateway)
                            else:
                                # For Client Credentials flow, get token directly
                                try:
                                    access_token: str = await self.oauth_manager.get_access_token(gateway.oauth_config)
                                    headers["Authorization"] = f"Bearer {access_token}"
                                except Exception as e:
                                    if span:
                                        span.set_attribute("health.status", "unhealthy")
                                        span.set_attribute("error.message", str(e))
                                    # await self._handle_gateway_failure(gateway)
                        else:
                            # Handle non-OAuth authentication (existing logic)
                            auth_data = gateway.auth_value or {}
                            if isinstance(auth_data, str):
                                headers = decode_auth(auth_data)
                            elif isinstance(auth_data, dict):
                                headers = {str(k): str(v) for k, v in auth_data.items()}
                            else:
                                headers = {}

                        # ═══════════════════════════════════════════════════════════════════════════
                        # Extract gateway data to local variables BEFORE releasing DB connection
                        # ═══════════════════════════════════════════════════════════════════════════
                        gateway_url = gateway.url
                        gateway_transport = gateway.transport

                        # ═══════════════════════════════════════════════════════════════════════════
                        # CRITICAL: Release DB connection back to pool BEFORE making HTTP calls
                        # This prevents connection pool exhaustion during slow upstream requests.
                        # All needed data has been extracted to local variables above.
                        # The session will be closed again by FastAPI's get_db() finally block (safe no-op).
                        # ═══════════════════════════════════════════════════════════════════════════
                        db.commit()  # End read-only transaction cleanly (commit not rollback to avoid inflating rollback stats)
                        db.close()

                        async def connect_to_sse_session(server_url: str, uri: str, authentication: Optional[Dict[str, str]] = None) -> str | None:
                            """
                            Connect to an SSE-based gateway and retrieve the text content of a resource.

                            This helper establishes an SSE (Server-Sent Events) session with the remote
                            gateway, initializes a `ClientSession`, invokes `read_resource()` for the
                            given URI, and returns the textual content from the first item in the
                            response's `contents` list.

                            If any error occurs (network failure, unexpected response format, session
                            initialization failure, etc.), the method logs the exception and returns
                            ``None`` instead of raising.

                            Args:
                                server_url (str):
                                    The base URL of the SSE gateway to connect to.
                                uri (str):
                                    The resource URI that should be requested from the gateway.
                                authentication (Optional[Dict[str, str]]):
                                    Optional dictionary of headers (e.g., OAuth Bearer tokens) to
                                    include in the SSE connection request. Defaults to an empty
                                    dictionary when not provided.

                            Returns:
                                str | None:
                                    The text content returned by the remote resource, or ``None`` if the
                                    SSE connection fails or the response is invalid.

                            Notes:
                                - This function assumes the SSE client context manager yields:
                                    ``(read_stream, write_stream, get_session_id)``.
                                - The expected response object from `session.read_resource()` must have a
                                `contents` attribute containing a list, where the first element has a
                                `text` attribute.
                            """
                            if authentication is None:
                                authentication = {}
                            try:
                                async with sse_client(url=server_url, headers=authentication, timeout=settings.health_check_timeout, httpx_client_factory=_get_httpx_client_factory) as (
                                    read_stream,
                                    write_stream,
                                    _get_session_id,
                                ):
                                    async with ClientSession(read_stream, write_stream) as session:
                                        _ = await session.initialize()
                                        resource_response = await session.read_resource(uri=uri)
                                        return getattr(getattr(resource_response, "contents")[0], "text")
                            except Exception as e:
                                logger.debug(f"Exception while connecting to sse gateway: {e}")
                                return None

                        async def connect_to_streamablehttp_server(server_url: str, uri: str, authentication: Optional[Dict[str, str]] = None) -> str | None:
                            """
                            Connect to a StreamableHTTP gateway and retrieve the text content of a resource.

                            This helper establishes a StreamableHTTP client session with the specified
                            gateway, initializes a `ClientSession`, invokes `read_resource()` for the
                            given URI, and returns the textual content from the first element in the
                            response's `contents` list.

                            If any exception occurs during connection, session initialization, or
                            resource reading, the function logs the error and returns ``None`` instead
                            of propagating the exception.

                            Args:
                                server_url (str):
                                    The endpoint URL of the StreamableHTTP gateway.
                                uri (str):
                                    The resource URI to request from the gateway.
                                authentication (Optional[Dict[str, str]]):
                                    Optional dictionary of authentication headers (e.g., API keys or
                                    Bearer tokens). Defaults to an empty dictionary when not provided.

                            Returns:
                                str | None:
                                    The text content returned by the StreamableHTTP resource, or ``None``
                                    if the connection fails or the response format is invalid.

                            Notes:
                                - The `streamablehttp_client` context manager must yield a tuple:
                                ``(read_stream, write_stream, get_session_id)``.
                                - The expected `resource_response` returned by ``session.read_resource()``
                                must contain a `contents` list, whose first element exposes a `text`
                                attribute.
                            """
                            if authentication is None:
                                authentication = {}
                            try:
                                async with streamablehttp_client(url=server_url, headers=authentication, timeout=settings.health_check_timeout, httpx_client_factory=_get_httpx_client_factory) as (
                                    read_stream,
                                    write_stream,
                                    _get_session_id,
                                ):
                                    async with ClientSession(read_stream, write_stream) as session:
                                        _ = await session.initialize()
                                        resource_response = await session.read_resource(uri=uri)
                                        return getattr(getattr(resource_response, "contents")[0], "text")
                            except Exception as e:
                                logger.debug(f"Exception while connecting to streamablehttp gateway: {e}")
                                return None

                        if span:
                            span.set_attribute("success", True)
                            span.set_attribute("duration.ms", (time.monotonic() - start_time) * 1000)

                        resource_text = ""
                        if (gateway_transport).lower() == "sse":
                            resource_text = await connect_to_sse_session(server_url=gateway_url, authentication=headers, uri=uri)
                        else:
                            resource_text = await connect_to_streamablehttp_server(server_url=gateway_url, authentication=headers, uri=uri)
                        success = True  # Mark as successful before returning
                        return resource_text
                    except Exception as e:
                        success = False
                        error_message = str(e)
                        raise
                    finally:
                        if resource_text:
                            try:
                                # First-Party
                                from mcpgateway.services.metrics_buffer_service import get_metrics_buffer_service  # pylint: disable=import-outside-toplevel

                                metrics_buffer = get_metrics_buffer_service()
                                metrics_buffer.record_resource_metric(
                                    resource_id=resource_id,
                                    start_time=start_time,
                                    success=success,
                                    error_message=error_message,
                                )
                            except Exception as metrics_error:
                                logger.warning(f"Failed to invoke resource metric: {metrics_error}")

                            # End Invoke resource span for Observability dashboard
                            # NOTE: Use fresh_db_session() since the original db was released
                            # before making HTTP calls to prevent connection pool exhaustion
                            if db_span_id and observability_service and not db_span_ended:
                                try:
                                    with fresh_db_session() as fresh_db:
                                        observability_service.end_span(
                                            db=fresh_db,
                                            span_id=db_span_id,
                                            status="ok" if success else "error",
                                            status_message=error_message if error_message else None,
                                        )
                                    db_span_ended = True
                                    logger.debug(f"✓ Ended invoke.resource span: {db_span_id}")
                                except Exception as e:
                                    logger.warning(f"Failed to end observability span for invoking resource: {e}")

    async def read_resource(
        self,
        db: Session,
        resource_id: Optional[Union[int, str]] = None,
        resource_uri: Optional[str] = None,
        request_id: Optional[str] = None,
        user: Optional[str] = None,
        server_id: Optional[str] = None,
        include_inactive: bool = False,
        plugin_context_table: Optional[PluginContextTable] = None,
        plugin_global_context: Optional[GlobalContext] = None,
    ) -> ResourceContent:
        """Read a resource's content with plugin hook support.

        Args:
            db: Database session.
            resource_id: Optional ID of the resource to read.
            resource_uri: Optional URI of the resource to read.
            request_id: Optional request ID for tracing.
            user: Optional user making the request.
            server_id: Optional server ID for context.
            include_inactive: Whether to include inactive resources. Defaults to False.
            plugin_context_table: Optional plugin context table from previous hooks for cross-hook state sharing.
            plugin_global_context: Optional global context from middleware for consistency across hooks.

        Returns:
            Resource content object

        Raises:
            ResourceNotFoundError: If resource not found
            ResourceError: If blocked by plugin
            PluginError: If encounters issue with plugin
            PluginViolationError: If plugin violated the request. Example - In case of OPA plugin, if the request is denied by policy.
            ValueError: If neither resource_id nor resource_uri is provided

        Examples:
            >>> from mcpgateway.common.models import ResourceContent
            >>> from mcpgateway.services.resource_service import ResourceService
            >>> from unittest.mock import MagicMock
            >>> service = ResourceService()
            >>> db = MagicMock()
            >>> uri = 'http://example.com/resource.txt'
            >>> import types
            >>> mock_resource = types.SimpleNamespace(id=123,content='test', uri=uri)
            >>> db.execute.return_value.scalar_one_or_none.return_value = mock_resource
            >>> db.get.return_value = mock_resource
            >>> import asyncio
            >>> result = asyncio.run(service.read_resource(db, resource_uri=uri))
            >>> result.__class__.__name__ == 'ResourceContent'
            True

        Not found case returns ResourceNotFoundError:

            >>> db2 = MagicMock()
            >>> db2.execute.return_value.scalar_one_or_none.return_value = None
            >>> import asyncio
            >>> def _nf():
            ...     try:
            ...         asyncio.run(service.read_resource(db2, resource_uri='abc'))
            ...     except ResourceNotFoundError:
            ...         return True
            >>> _nf()
            True
        """
        start_time = time.monotonic()
        success = False
        error_message = None
        resource_db = None
        content = None
        uri = resource_uri or "unknown"
        if resource_id:
            resource_db = db.get(DbResource, resource_id)
            uri = resource_db.uri if resource_db else None

        # Create database span for observability dashboard
        trace_id = current_trace_id.get()
        db_span_id = None
        db_span_ended = False
        observability_service = ObservabilityService() if trace_id else None

        if trace_id and observability_service:
            try:
                db_span_id = observability_service.start_span(
                    db=db,
                    trace_id=trace_id,
                    name="resource.read",
                    attributes={
                        "resource.uri": str(resource_uri) if resource_uri else "unknown",
                        "user": user or "anonymous",
                        "server_id": server_id,
                        "request_id": request_id,
                        "http.url": uri if uri is not None and uri.startswith("http") else None,
                        "resource.type": "template" if (uri is not None and "{" in uri and "}" in uri) else "static",
                    },
                )
                logger.debug(f"✓ Created resource.read span: {db_span_id} for resource: {uri}")
            except Exception as e:
                logger.warning(f"Failed to start observability span for resource reading: {e}")
                db_span_id = None

        with create_span(
            "resource.read",
            {
                "resource.uri": resource_uri or "unknown",
                "user": user or "anonymous",
                "server_id": server_id,
                "request_id": request_id,
                "http.url": uri if uri is not None and uri.startswith("http") else None,
                "resource.type": "template" if (uri is not None and "{" in uri and "}" in uri) else "static",
            },
        ) as span:
            try:
                # Generate request ID if not provided
                if not request_id:
                    request_id = str(uuid.uuid4())

                original_uri = uri
                contexts = None
                # Call pre-fetch hooks if plugin manager is available
                plugin_eligible = bool(self._plugin_manager and PLUGINS_AVAILABLE and uri and ("://" in uri))
                if plugin_eligible:
                    # Initialize plugin manager if needed
                    # pylint: disable=protected-access
                    if not self._plugin_manager._initialized:
                        await self._plugin_manager.initialize()
                    # pylint: enable=protected-access

                    # Create plugin context
                    # Normalize user to an identifier string if provided
                    user_id = None
                    if user is not None:
                        if isinstance(user, dict) and "email" in user:
                            user_id = user.get("email")
                        elif isinstance(user, str):
                            user_id = user
                        else:
                            # Attempt to fallback to attribute access
                            user_id = getattr(user, "email", None)

                    # Use existing global_context from middleware or create new one
                    if plugin_global_context:
                        global_context = plugin_global_context
                        # Update fields with resource-specific information
                        if user_id:
                            global_context.user = user_id
                        if server_id:
                            global_context.server_id = server_id
                    else:
                        # Create new context (fallback when middleware didn't run)
                        global_context = GlobalContext(request_id=request_id, user=user_id, server_id=server_id)

                    # Create pre-fetch payload
                    pre_payload = ResourcePreFetchPayload(uri=uri, metadata={})

                    # Execute pre-fetch hooks with context from previous hooks
                    pre_result, contexts = await self._plugin_manager.invoke_hook(
                        ResourceHookType.RESOURCE_PRE_FETCH,
                        pre_payload,
                        global_context,
                        local_contexts=plugin_context_table,  # Pass context from previous hooks
                        violations_as_exceptions=True,
                    )
                    # Use modified URI if plugin changed it
                    if pre_result.modified_payload:
                        uri = pre_result.modified_payload.uri
                        logger.debug(f"Resource URI modified by plugin: {original_uri} -> {uri}")

                # Validate resource path if experimental validation is enabled
                if getattr(settings, "experimental_validate_io", False) and uri and isinstance(uri, str):
                    try:
                        SecurityValidator.validate_path(uri, getattr(settings, "allowed_roots", None))
                    except ValueError as e:
                        raise ResourceError(f"Path validation failed: {e}")

                # Original resource fetching logic
                logger.info(f"Fetching resource: {resource_id} (URI: {uri})")
                # Check for template

                if uri is not None:  # and "{" in uri and "}" in uri:
                    # Matches uri (modified value from pluggins if applicable)
                    # with uri from resource DB
                    # if uri is of type resource template then resource is retreived from DB
                    query = select(DbResource).where(DbResource.uri == str(uri)).where(DbResource.enabled)
                    if include_inactive:
                        query = select(DbResource).where(DbResource.uri == str(uri))
                    resource_db = db.execute(query).scalar_one_or_none()
                    if resource_db:
                        # resource_id = resource_db.id
                        content = resource_db.content
                    else:
                        # Check the inactivity first
                        check_inactivity = db.execute(select(DbResource).where(DbResource.uri == str(resource_uri)).where(not_(DbResource.enabled))).scalar_one_or_none()
                        if check_inactivity:
                            raise ResourceNotFoundError(f"Resource '{resource_uri}' exists but is inactive")

                if resource_db is None:
                    if resource_uri:
                        # if resource_uri is provided
                        # modified uri have templatized resource with prefilled value
                        # triggers _read_template_resource
                        # it internally checks which uri matches the pattern of modified uri and fetches
                        # the one which matches else raises ResourceNotFoundError
                        try:
                            content = await self._read_template_resource(db, uri) or None
                        except Exception as e:
                            raise ResourceNotFoundError(f"Resource template not found for '{resource_uri}'") from e

                if resource_uri:
                    if content is None and resource_db is None:
                        raise ResourceNotFoundError(f"Resource template not found for '{resource_uri}'")

                if resource_id:
                    # if resource_id provided instead of resource_uri
                    # retrieves resource based on resource_id
                    query = select(DbResource).where(DbResource.id == str(resource_id)).where(DbResource.enabled)
                    if include_inactive:
                        query = select(DbResource).where(DbResource.id == str(resource_id))
                    resource_db = db.execute(query).scalar_one_or_none()
                    if resource_db:
                        original_uri = resource_db.uri or None
                        content = resource_db.content
                    else:
                        check_inactivity = db.execute(select(DbResource).where(DbResource.id == str(resource_id)).where(not_(DbResource.enabled))).scalar_one_or_none()
                        if check_inactivity:
                            raise ResourceNotFoundError(f"Resource '{resource_id}' exists but is inactive")
                        raise ResourceNotFoundError(f"Resource not found for the resource id: {resource_id}")

                # Call post-fetch hooks if plugin manager is available
                if plugin_eligible:
                    # Create post-fetch payload
                    post_payload = ResourcePostFetchPayload(uri=original_uri, content=content)
                    # Execute post-fetch hooks
                    post_result, _ = await self._plugin_manager.invoke_hook(
                        ResourceHookType.RESOURCE_POST_FETCH, post_payload, global_context, contexts, violations_as_exceptions=True
                    )  # Pass contexts from pre-fetch

                    # Use modified content if plugin changed it
                    if post_result.modified_payload:
                        content = post_result.modified_payload.content

                # Set success attributes on span
                if span:
                    span.set_attribute("success", True)
                    span.set_attribute("duration.ms", (time.monotonic() - start_time) * 1000)
                    if content:
                        span.set_attribute("content.size", len(str(content)))

                success = True
                # Return standardized content without breaking callers that expect passthrough
                # Prefer returning first-class content models or objects with content-like attributes.
                # ResourceContent and TextContent already imported at top level

                # If content is already a Pydantic content model, return as-is
                if isinstance(content, (ResourceContent, TextContent)):
                    resource_response = await self.invoke_resource(
                        db=db, resource_id=getattr(content, "id"), resource_uri=getattr(content, "uri") or None, resource_template_uri=getattr(content, "text") or None
                    )
                    if resource_response:
                        setattr(content, "text", resource_response)
                    return content
                # If content is any object that quacks like content (e.g., MagicMock with .text/.blob), return as-is
                if hasattr(content, "text") or hasattr(content, "blob"):
                    if hasattr(content, "blob"):
                        resource_response = await self.invoke_resource(
                            db=db, resource_id=getattr(content, "id"), resource_uri=getattr(content, "uri") or None, resource_template_uri=getattr(content, "blob") or None
                        )
                        setattr(content, "blob", resource_response)
                    elif hasattr(content, "text"):
                        resource_response = await self.invoke_resource(
                            db=db, resource_id=getattr(content, "id"), resource_uri=getattr(content, "uri") or None, resource_template_uri=getattr(content, "text") or None
                        )
                        setattr(content, "text", resource_response)
                    return content
                # Normalize primitive types to ResourceContent
                if isinstance(content, bytes):
                    return ResourceContent(type="resource", id=str(resource_id), uri=original_uri, blob=content)
                if isinstance(content, str):
                    return ResourceContent(type="resource", id=str(resource_id), uri=original_uri, text=content)

                # Fallback to stringified content
                return ResourceContent(type="resource", id=str(resource_id) or str(content.id), uri=original_uri or content.uri, text=str(content))
            except Exception as e:
                success = False
                error_message = str(e)
                raise
            finally:
                # Record metrics only if we found a resource (not for templates)
                if resource_db:
                    try:
                        # First-Party
                        from mcpgateway.services.metrics_buffer_service import get_metrics_buffer_service  # pylint: disable=import-outside-toplevel

                        metrics_buffer = get_metrics_buffer_service()
                        metrics_buffer.record_resource_metric(
                            resource_id=resource_db.id,
                            start_time=start_time,
                            success=success,
                            error_message=error_message,
                        )
                    except Exception as metrics_error:
                        logger.warning(f"Failed to record resource metric: {metrics_error}")

                # End database span for observability dashboard
                if db_span_id and observability_service and not db_span_ended:
                    try:
                        observability_service.end_span(
                            db=db,
                            span_id=db_span_id,
                            status="ok" if success else "error",
                            status_message=error_message if error_message else None,
                        )
                        db_span_ended = True
                        logger.debug(f"✓ Ended resource.read span: {db_span_id}")
                    except Exception as e:
                        logger.warning(f"Failed to end observability span for resource reading: {e}")

    async def toggle_resource_status(self, db: Session, resource_id: int, activate: bool, user_email: Optional[str] = None) -> ResourceRead:
        """
        Toggle the activation status of a resource.

        Args:
            db: Database session
            resource_id: Resource ID
            activate: True to activate, False to deactivate
            user_email: Optional[str] The email of the user to check if the user has permission to modify.

        Returns:
            The updated ResourceRead object

        Raises:
            ResourceNotFoundError: If the resource is not found
            ResourceError: For other errors
            PermissionError: If user doesn't own the agent.

        Examples:
            >>> from mcpgateway.services.resource_service import ResourceService
            >>> from unittest.mock import MagicMock, AsyncMock
            >>> from mcpgateway.schemas import ResourceRead
            >>> service = ResourceService()
            >>> db = MagicMock()
            >>> resource = MagicMock()
            >>> db.get.return_value = resource
            >>> db.commit = MagicMock()
            >>> db.refresh = MagicMock()
            >>> service._notify_resource_activated = AsyncMock()
            >>> service._notify_resource_deactivated = AsyncMock()
            >>> service._convert_resource_to_read = MagicMock(return_value='resource_read')
            >>> ResourceRead.model_validate = MagicMock(return_value='resource_read')
            >>> import asyncio
            >>> asyncio.run(service.toggle_resource_status(db, 1, True))
            'resource_read'
        """
        try:
            resource = db.get(DbResource, resource_id)
            if not resource:
                raise ResourceNotFoundError(f"Resource not found: {resource_id}")

            if user_email:
                # First-Party
                from mcpgateway.services.permission_service import PermissionService  # pylint: disable=import-outside-toplevel

                permission_service = PermissionService(db)
                if not await permission_service.check_resource_ownership(user_email, resource):
                    raise PermissionError("Only the owner can activate the Resource" if activate else "Only the owner can deactivate the Resource")

            # Update status if it's different
            if resource.enabled != activate:
                resource.enabled = activate
                resource.updated_at = datetime.now(timezone.utc)
                db.commit()
                db.refresh(resource)

                # Invalidate cache after status change
                cache = _get_registry_cache()
                await cache.invalidate_resources()

                # Notify subscribers
                if activate:
                    await self._notify_resource_activated(resource)
                else:
                    await self._notify_resource_deactivated(resource)

                logger.info(f"Resource {resource.uri} {'activated' if activate else 'deactivated'}")

                # Structured logging: Audit trail for resource status toggle
                audit_trail.log_action(
                    user_id=user_email or "system",
                    action="toggle_resource_status",
                    resource_type="resource",
                    resource_id=str(resource.id),
                    resource_name=resource.name,
                    user_email=user_email,
                    team_id=resource.team_id,
                    new_values={
                        "enabled": resource.enabled,
                    },
                    context={
                        "action": "activate" if activate else "deactivate",
                    },
                    db=db,
                )

                # Structured logging: Log successful resource status toggle
                structured_logger.log(
                    level="INFO",
                    message=f"Resource {'activated' if activate else 'deactivated'} successfully",
                    event_type="resource_status_toggled",
                    component="resource_service",
                    user_email=user_email,
                    team_id=resource.team_id,
                    resource_type="resource",
                    resource_id=str(resource.id),
                    custom_fields={
                        "resource_uri": resource.uri,
                        "enabled": resource.enabled,
                    },
                    db=db,
                )

            resource.team = self._get_team_name(db, resource.team_id)
            return self._convert_resource_to_read(resource)
        except PermissionError as e:
            # Structured logging: Log permission error
            structured_logger.log(
                level="WARNING",
                message="Resource status toggle failed due to permission error",
                event_type="resource_toggle_permission_denied",
                component="resource_service",
                user_email=user_email,
                resource_type="resource",
                resource_id=str(resource_id),
                error=e,
                db=db,
            )
            raise e
        except Exception as e:
            db.rollback()

            # Structured logging: Log generic resource status toggle failure
            structured_logger.log(
                level="ERROR",
                message="Resource status toggle failed",
                event_type="resource_toggle_failed",
                component="resource_service",
                user_email=user_email,
                resource_type="resource",
                resource_id=str(resource_id),
                error=e,
                db=db,
            )
            raise ResourceError(f"Failed to toggle resource status: {str(e)}")

    async def subscribe_resource(self, db: Session, subscription: ResourceSubscription) -> None:
        """
        Subscribe to a resource.

        Args:
            db: Database session
            subscription: Resource subscription object

        Raises:
            ResourceNotFoundError: If the resource is not found or is inactive
            ResourceError: For other subscription errors

        Examples:
            >>> from mcpgateway.services.resource_service import ResourceService
            >>> from unittest.mock import MagicMock
            >>> service = ResourceService()
            >>> db = MagicMock()
            >>> subscription = MagicMock()
            >>> import asyncio
            >>> asyncio.run(service.subscribe_resource(db, subscription))
        """
        try:
            # Verify resource exists
            resource = db.execute(select(DbResource).where(DbResource.uri == subscription.uri).where(DbResource.enabled)).scalar_one_or_none()

            if not resource:
                # Check if inactive resource exists
                inactive_resource = db.execute(select(DbResource).where(DbResource.uri == subscription.uri).where(not_(DbResource.enabled))).scalar_one_or_none()

                if inactive_resource:
                    raise ResourceNotFoundError(f"Resource '{subscription.uri}' exists but is inactive")

                raise ResourceNotFoundError(f"Resource not found: {subscription.uri}")

            # Create subscription
            db_sub = DbSubscription(resource_id=resource.id, subscriber_id=subscription.subscriber_id)
            db.add(db_sub)
            db.commit()

            logger.info(f"Added subscription for {subscription.uri} by {subscription.subscriber_id}")

        except Exception as e:
            db.rollback()
            raise ResourceError(f"Failed to subscribe: {str(e)}")

    async def unsubscribe_resource(self, db: Session, subscription: ResourceSubscription) -> None:
        """
        Unsubscribe from a resource.

        Args:
            db: Database session
            subscription: Resource subscription object

        Raises:

        Examples:
            >>> from mcpgateway.services.resource_service import ResourceService
            >>> from unittest.mock import MagicMock
            >>> service = ResourceService()
            >>> db = MagicMock()
            >>> subscription = MagicMock()
            >>> import asyncio
            >>> asyncio.run(service.unsubscribe_resource(db, subscription))
        """
        try:
            # Find resource
            resource = db.execute(select(DbResource).where(DbResource.uri == subscription.uri)).scalar_one_or_none()

            if not resource:
                return

            # Remove subscription
            db.execute(select(DbSubscription).where(DbSubscription.resource_id == resource.id).where(DbSubscription.subscriber_id == subscription.subscriber_id)).delete()
            db.commit()

            logger.info(f"Removed subscription for {subscription.uri} by {subscription.subscriber_id}")

        except Exception as e:
            db.rollback()
            logger.error(f"Failed to unsubscribe: {str(e)}")

    async def update_resource(
        self,
        db: Session,
        resource_id: Union[int, str],
        resource_update: ResourceUpdate,
        modified_by: Optional[str] = None,
        modified_from_ip: Optional[str] = None,
        modified_via: Optional[str] = None,
        modified_user_agent: Optional[str] = None,
        user_email: Optional[str] = None,
    ) -> ResourceRead:
        """
        Update a resource.

        Args:
            db: Database session
            resource_id: Resource ID
            resource_update: Resource update object
            modified_by: Username of the person modifying the resource
            modified_from_ip: IP address where the modification request originated
            modified_via: Source of modification (ui/api/import)
            modified_user_agent: User agent string from the modification request
            user_email: Email of user performing update (for ownership check)

        Returns:
            The updated ResourceRead object

        Raises:
            ResourceNotFoundError: If the resource is not found
            ResourceURIConflictError: If a resource with the same URI already exists.
            PermissionError: If user doesn't own the resource
            ResourceError: For other update errors
            IntegrityError: If a database integrity error occurs.
            Exception: For unexpected errors

        Example:
            >>> from mcpgateway.services.resource_service import ResourceService
            >>> from unittest.mock import MagicMock, AsyncMock
            >>> from mcpgateway.schemas import ResourceRead
            >>> service = ResourceService()
            >>> db = MagicMock()
            >>> resource = MagicMock()
            >>> db.get.return_value = resource
            >>> db.commit = MagicMock()
            >>> db.refresh = MagicMock()
            >>> service._notify_resource_updated = AsyncMock()
            >>> service._convert_resource_to_read = MagicMock(return_value='resource_read')
            >>> ResourceRead.model_validate = MagicMock(return_value='resource_read')
            >>> import asyncio
            >>> asyncio.run(service.update_resource(db, 'resource_id', MagicMock()))
            'resource_read'
        """
        try:
            logger.info(f"Updating resource: {resource_id}")
            resource = db.get(DbResource, resource_id)
            if not resource:
                raise ResourceNotFoundError(f"Resource not found: {resource_id}")

            # # Check for uri conflict if uri is being changed and visibility is public
            if resource_update.uri and resource_update.uri != resource.uri:
                visibility = resource_update.visibility or resource.visibility
                team_id = resource_update.team_id or resource.team_id
                if visibility.lower() == "public":
                    # Check for existing public resources with the same uri
                    existing_resource = db.execute(select(DbResource).where(DbResource.uri == resource_update.uri, DbResource.visibility == "public")).scalar_one_or_none()
                    if existing_resource:
                        raise ResourceURIConflictError(resource_update.uri, enabled=existing_resource.enabled, resource_id=existing_resource.id, visibility=existing_resource.visibility)
                elif visibility.lower() == "team" and team_id:
                    # Check for existing team resource with the same uri
                    existing_resource = db.execute(select(DbResource).where(DbResource.uri == resource_update.uri, DbResource.visibility == "team", DbResource.team_id == team_id)).scalar_one_or_none()
                    if existing_resource:
                        raise ResourceURIConflictError(resource_update.uri, enabled=existing_resource.enabled, resource_id=existing_resource.id, visibility=existing_resource.visibility)

            # Check ownership if user_email provided
            if user_email:
                # First-Party
                from mcpgateway.services.permission_service import PermissionService  # pylint: disable=import-outside-toplevel

                permission_service = PermissionService(db)
                if not await permission_service.check_resource_ownership(user_email, resource):
                    raise PermissionError("Only the owner can update this resource")

            # Update fields if provided
            if resource_update.uri is not None:
                resource.uri = resource_update.uri
            if resource_update.name is not None:
                resource.name = resource_update.name
            if resource_update.description is not None:
                resource.description = resource_update.description
            if resource_update.mime_type is not None:
                resource.mime_type = resource_update.mime_type
            if resource_update.uri_template is not None:
                resource.uri_template = resource_update.uri_template
            if resource_update.visibility is not None:
                resource.visibility = resource_update.visibility

            # Update content if provided
            if resource_update.content is not None:
                # Determine content storage
                is_text = resource.mime_type and resource.mime_type.startswith("text/") or isinstance(resource_update.content, str)

                resource.text_content = resource_update.content if is_text else None
                resource.binary_content = (
                    resource_update.content.encode() if is_text and isinstance(resource_update.content, str) else resource_update.content if isinstance(resource_update.content, bytes) else None
                )
                resource.size = len(resource_update.content)

            # Update tags if provided
            if resource_update.tags is not None:
                resource.tags = resource_update.tags

            # Update metadata fields
            resource.updated_at = datetime.now(timezone.utc)
            if modified_by:
                resource.modified_by = modified_by
            if modified_from_ip:
                resource.modified_from_ip = modified_from_ip
            if modified_via:
                resource.modified_via = modified_via
            if modified_user_agent:
                resource.modified_user_agent = modified_user_agent
            if hasattr(resource, "version") and resource.version is not None:
                resource.version = resource.version + 1
            else:
                resource.version = 1
            db.commit()
            db.refresh(resource)

            # Invalidate cache after successful update
            cache = _get_registry_cache()
            await cache.invalidate_resources()
            # Also invalidate tags cache since resource tags may have changed
            # First-Party
            from mcpgateway.cache.admin_stats_cache import admin_stats_cache  # pylint: disable=import-outside-toplevel

            await admin_stats_cache.invalidate_tags()

            # Notify subscribers
            await self._notify_resource_updated(resource)

            logger.info(f"Updated resource: {resource.uri}")

            # Structured logging: Audit trail for resource update
            changes = []
            if resource_update.uri:
                changes.append(f"uri: {resource_update.uri}")
            if resource_update.visibility:
                changes.append(f"visibility: {resource_update.visibility}")
            if resource_update.description:
                changes.append("description updated")

            audit_trail.log_action(
                user_id=user_email or modified_by or "system",
                action="update_resource",
                resource_type="resource",
                resource_id=str(resource.id),
                resource_name=resource.name,
                user_email=user_email,
                team_id=resource.team_id,
                client_ip=modified_from_ip,
                user_agent=modified_user_agent,
                new_values={
                    "uri": resource.uri,
                    "name": resource.name,
                    "version": resource.version,
                },
                context={
                    "modified_via": modified_via,
                    "changes": ", ".join(changes) if changes else "metadata only",
                },
                db=db,
            )

            # Structured logging: Log successful resource update
            structured_logger.log(
                level="INFO",
                message="Resource updated successfully",
                event_type="resource_updated",
                component="resource_service",
                user_id=modified_by,
                user_email=user_email,
                team_id=resource.team_id,
                resource_type="resource",
                resource_id=str(resource.id),
                custom_fields={
                    "resource_uri": resource.uri,
                    "version": resource.version,
                },
                db=db,
            )

            return self._convert_resource_to_read(resource)
        except PermissionError as pe:
            db.rollback()

            # Structured logging: Log permission error
            structured_logger.log(
                level="WARNING",
                message="Resource update failed due to permission error",
                event_type="resource_update_permission_denied",
                component="resource_service",
                user_email=user_email,
                resource_type="resource",
                resource_id=str(resource_id),
                error=pe,
                db=db,
            )
            raise
        except IntegrityError as ie:
            db.rollback()
            logger.error(f"IntegrityErrors in group: {ie}")

            # Structured logging: Log database integrity error
            structured_logger.log(
                level="ERROR",
                message="Resource update failed due to database integrity error",
                event_type="resource_update_failed",
                component="resource_service",
                user_id=modified_by,
                user_email=user_email,
                resource_type="resource",
                resource_id=str(resource_id),
                error=ie,
                db=db,
            )
            raise ie
        except ResourceURIConflictError as pe:
            logger.error(f"Resource URI conflict: {pe}")

            # Structured logging: Log URI conflict error
            structured_logger.log(
                level="WARNING",
                message="Resource update failed due to URI conflict",
                event_type="resource_uri_conflict",
                component="resource_service",
                user_id=modified_by,
                user_email=user_email,
                resource_type="resource",
                resource_id=str(resource_id),
                error=pe,
                db=db,
            )
            raise pe
        except Exception as e:
            db.rollback()
            if isinstance(e, ResourceNotFoundError):
                # Structured logging: Log not found error
                structured_logger.log(
                    level="ERROR",
                    message="Resource update failed - resource not found",
                    event_type="resource_not_found",
                    component="resource_service",
                    user_email=user_email,
                    resource_type="resource",
                    resource_id=str(resource_id),
                    error=e,
                    db=db,
                )
                raise e

            # Structured logging: Log generic resource update failure
            structured_logger.log(
                level="ERROR",
                message="Resource update failed",
                event_type="resource_update_failed",
                component="resource_service",
                user_id=modified_by,
                user_email=user_email,
                resource_type="resource",
                resource_id=str(resource_id),
                error=e,
                db=db,
            )
            raise ResourceError(f"Failed to update resource: {str(e)}")

    async def delete_resource(self, db: Session, resource_id: Union[int, str], user_email: Optional[str] = None) -> None:
        """
        Delete a resource.

        Args:
            db: Database session
            resource_id: Resource ID
            user_email: Email of user performing delete (for ownership check)

        Raises:
            ResourceNotFoundError: If the resource is not found
            PermissionError: If user doesn't own the resource
            ResourceError: For other deletion errors

        Example:
            >>> from mcpgateway.services.resource_service import ResourceService
            >>> from unittest.mock import MagicMock, AsyncMock
            >>> service = ResourceService()
            >>> db = MagicMock()
            >>> resource = MagicMock()
            >>> db.get.return_value = resource
            >>> db.delete = MagicMock()
            >>> db.commit = MagicMock()
            >>> service._notify_resource_deleted = AsyncMock()
            >>> import asyncio
            >>> asyncio.run(service.delete_resource(db, 'resource_id'))
        """
        try:
            # Find resource by its URI.
            resource = db.execute(select(DbResource).where(DbResource.id == resource_id)).scalar_one_or_none()

            if not resource:
                # If resource doesn't exist, rollback and re-raise a ResourceNotFoundError.
                db.rollback()
                raise ResourceNotFoundError(f"Resource not found: {resource_id}")

            # Check ownership if user_email provided
            if user_email:
                # First-Party
                from mcpgateway.services.permission_service import PermissionService  # pylint: disable=import-outside-toplevel

                permission_service = PermissionService(db)
                if not await permission_service.check_resource_ownership(user_email, resource):
                    raise PermissionError("Only the owner can delete this resource")

            # Store resource info for notification before deletion.
            resource_info = {
                "id": resource.id,
                "uri": resource.uri,
                "name": resource.name,
            }

            # Remove subscriptions using SQLAlchemy's delete() expression.
            db.execute(delete(DbSubscription).where(DbSubscription.resource_id == resource.id))

            # Hard delete the resource.
            resource_uri = resource.uri
            resource_name = resource.name
            resource_team_id = resource.team_id

            db.delete(resource)
            db.commit()

            # Invalidate cache after successful deletion
            cache = _get_registry_cache()
            await cache.invalidate_resources()
            # Also invalidate tags cache since resource tags may have changed
            # First-Party
            from mcpgateway.cache.admin_stats_cache import admin_stats_cache  # pylint: disable=import-outside-toplevel

            await admin_stats_cache.invalidate_tags()

            # Notify subscribers.
            await self._notify_resource_deleted(resource_info)

            logger.info(f"Permanently deleted resource: {resource.uri}")

            # Structured logging: Audit trail for resource deletion
            audit_trail.log_action(
                user_id=user_email or "system",
                action="delete_resource",
                resource_type="resource",
                resource_id=str(resource_info["id"]),
                resource_name=resource_name,
                user_email=user_email,
                team_id=resource_team_id,
                old_values={
                    "uri": resource_uri,
                    "name": resource_name,
                },
                db=db,
            )

            # Structured logging: Log successful resource deletion
            structured_logger.log(
                level="INFO",
                message="Resource deleted successfully",
                event_type="resource_deleted",
                component="resource_service",
                user_email=user_email,
                team_id=resource_team_id,
                resource_type="resource",
                resource_id=str(resource_info["id"]),
                custom_fields={
                    "resource_uri": resource_uri,
                },
                db=db,
            )

        except PermissionError as pe:
            db.rollback()

            # Structured logging: Log permission error
            structured_logger.log(
                level="WARNING",
                message="Resource deletion failed due to permission error",
                event_type="resource_delete_permission_denied",
                component="resource_service",
                user_email=user_email,
                resource_type="resource",
                resource_id=str(resource_id),
                error=pe,
                db=db,
            )
            raise
        except ResourceNotFoundError as rnfe:
            # ResourceNotFoundError is re-raised to be handled in the endpoint.
            # Structured logging: Log not found error
            structured_logger.log(
                level="ERROR",
                message="Resource deletion failed - resource not found",
                event_type="resource_not_found",
                component="resource_service",
                user_email=user_email,
                resource_type="resource",
                resource_id=str(resource_id),
                error=rnfe,
                db=db,
            )
            raise
        except Exception as e:
            db.rollback()

            # Structured logging: Log generic resource deletion failure
            structured_logger.log(
                level="ERROR",
                message="Resource deletion failed",
                event_type="resource_deletion_failed",
                component="resource_service",
                user_email=user_email,
                resource_type="resource",
                resource_id=str(resource_id),
                error=e,
                db=db,
            )
            raise ResourceError(f"Failed to delete resource: {str(e)}")

    async def get_resource_by_id(self, db: Session, resource_id: str, include_inactive: bool = False) -> ResourceRead:
        """
        Get a resource by ID.

        Args:
            db: Database session
            resource_id: Resource ID
            include_inactive: Whether to include inactive resources

        Returns:
            ResourceRead: The resource object

        Raises:
            ResourceNotFoundError: If the resource is not found

        Example:
            >>> from mcpgateway.services.resource_service import ResourceService
            >>> from unittest.mock import MagicMock
            >>> service = ResourceService()
            >>> db = MagicMock()
            >>> resource = MagicMock()
            >>> db.execute.return_value.scalar_one_or_none.return_value = resource
            >>> service._convert_resource_to_read = MagicMock(return_value='resource_read')
            >>> import asyncio
            >>> asyncio.run(service.get_resource_by_id(db, "39334ce0ed2644d79ede8913a66930c9"))
            'resource_read'
        """
        query = select(DbResource).where(DbResource.id == resource_id)

        if not include_inactive:
            query = query.where(DbResource.enabled)

        resource = db.execute(query).scalar_one_or_none()

        if not resource:
            if not include_inactive:
                # Check if inactive resource exists
                inactive_resource = db.execute(select(DbResource).where(DbResource.id == resource_id).where(not_(DbResource.enabled))).scalar_one_or_none()

                if inactive_resource:
                    raise ResourceNotFoundError(f"Resource '{resource_id}' exists but is inactive")

            raise ResourceNotFoundError(f"Resource not found: {resource_id}")

        resource_read = self._convert_resource_to_read(resource)

        structured_logger.log(
            level="INFO",
            message="Resource retrieved successfully",
            event_type="resource_viewed",
            component="resource_service",
            team_id=getattr(resource, "team_id", None),
            resource_type="resource",
            resource_id=str(resource.id),
            custom_fields={
                "resource_uri": resource.uri,
                "include_inactive": include_inactive,
            },
            db=db,
        )

        return resource_read

    async def _notify_resource_activated(self, resource: DbResource) -> None:
        """
        Notify subscribers of resource activation.

        Args:
            resource: Resource to activate
        """
        event = {
            "type": "resource_activated",
            "data": {
                "id": resource.id,
                "uri": resource.uri,
                "name": resource.name,
                "enabled": True,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._publish_event(event)

    async def _notify_resource_deactivated(self, resource: DbResource) -> None:
        """
        Notify subscribers of resource deactivation.

        Args:
            resource: Resource to deactivate
        """
        event = {
            "type": "resource_deactivated",
            "data": {
                "id": resource.id,
                "uri": resource.uri,
                "name": resource.name,
                "enabled": False,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._publish_event(event)

    async def _notify_resource_deleted(self, resource_info: Dict[str, Any]) -> None:
        """
        Notify subscribers of resource deletion.

        Args:
            resource_info: Dictionary of resource to delete
        """
        event = {
            "type": "resource_deleted",
            "data": resource_info,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._publish_event(event)

    async def _notify_resource_removed(self, resource: DbResource) -> None:
        """
        Notify subscribers of resource removal.

        Args:
            resource: Resource to remove
        """
        event = {
            "type": "resource_removed",
            "data": {
                "id": resource.id,
                "uri": resource.uri,
                "name": resource.name,
                "enabled": False,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._publish_event(event)

    async def subscribe_events(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Subscribe to Resource events via the EventService.

        Yields:
            Resource event messages.
        """
        async for event in self._event_service.subscribe_events():
            yield event

    def _detect_mime_type(self, uri: str, content: Union[str, bytes]) -> str:
        """Detect mime type from URI and content.

        Args:
            uri: Resource URI
            content: Resource content

        Returns:
            Detected mime type
        """
        # Try from URI first
        mime_type, _ = mimetypes.guess_type(uri)
        if mime_type:
            return mime_type

        # Check content type
        if isinstance(content, str):
            return "text/plain"

        return "application/octet-stream"

    async def _read_template_resource(self, db: Session, uri: str, include_inactive: Optional[bool] = False) -> ResourceContent:
        """
        Read a templated resource.

        Args:
            db: Database session.
            uri: Template URI with parameters.
            include_inactive: Whether to include inactive resources in DB lookups.

        Returns:
            ResourceContent: The resolved content from the matching template.

        Raises:
            ResourceNotFoundError: If no matching template is found.
            ResourceError: For other template resolution errors.
            NotImplementedError: If a binary template resource is encountered.
        """
        # Find matching template # DRT BREAKPOINT
        template = None
        if not self._template_cache:
            logger.info("_template_cache is empty, fetching exisitng resource templates")
            resource_templates = await self.list_resource_templates(db=db, include_inactive=include_inactive)
            for i in resource_templates:
                self._template_cache[i.name] = i
        for cached in self._template_cache.values():
            if self._uri_matches_template(uri, cached.uri_template):
                template = cached
                break

        if template:
            check_inactivity = db.execute(select(DbResource).where(DbResource.id == str(template.id)).where(not_(DbResource.enabled))).scalar_one_or_none()
            if check_inactivity:
                raise ResourceNotFoundError(f"Resource '{template.id}' exists but is inactive")
        else:
            raise ResourceNotFoundError(f"No template matches URI: {uri}")

        try:
            # Extract parameters
            params = self._extract_template_params(uri, template.uri_template)
            # Generate content
            if template.mime_type and template.mime_type.startswith("text/"):
                content = template.uri_template.format(**params)
                return ResourceContent(type="resource", id=str(template.id) or None, uri=template.uri_template or None, mime_type=template.mime_type or None, text=content)
            # # Handle binary template
            raise NotImplementedError("Binary resource templates not yet supported")

        except ResourceNotFoundError:
            raise
        except Exception as e:
            raise ResourceError(f"Failed to process template: {str(e)}") from e

    def _build_regex(self, template: str) -> re.Pattern:
        """
        Convert a URI template into a compiled regular expression.

        This parser supports a subset of RFC 6570–style templates for path
        matching. It extracts path parameters and converts them into named
        regex groups.

        Supported template features:
        - `{var}`
        A simple path parameter. Matches a single URI segment
        (i.e., any characters except `/`).
        → Translates to `(?P<var>[^/]+)`
        - `{var*}`
        A wildcard parameter. Matches one or more URI segments,
        including `/`.
        → Translates to `(?P<var>.+)`
        - `{?var1,var2}`
        Query-parameter expressions. These are ignored when building
        the regex for path matching and are stripped from the template.

        Example:
            Template: "files://root/{path*}/meta/{id}{?expand,debug}"
            Regex: r"^files://root/(?P<path>.+)/meta/(?P<id>[^/]+)$"

        Args:
            template: The URI template string containing parameter expressions.

        Returns:
            A compiled regular expression (re.Pattern) that can be used to
            match URIs and extract parameter values.
        """
        # Remove query parameter syntax for path matching
        template_without_query = re.sub(r"\{\?[^}]+\}", "", template)

        parts = re.split(r"(\{[^}]+\})", template_without_query)
        pattern = ""
        for part in parts:
            if part.startswith("{") and part.endswith("}"):
                name = part[1:-1]
                if name.endswith("*"):
                    name = name[:-1]
                    pattern += f"(?P<{name}>.+)"
                else:
                    pattern += f"(?P<{name}>[^/]+)"
            else:
                pattern += re.escape(part)
        return re.compile(f"^{pattern}$")

    def _extract_template_params(self, uri: str, template: str) -> Dict[str, str]:
        """
        Extract parameters from a URI based on a template.

        Args:
            uri: The actual URI containing parameter values.
            template: The template pattern (e.g. "file:///{name}/{id}").

        Returns:
            Dict of parameter names and extracted values.
        """
        result = parse.parse(template, uri)
        return result.named if result else {}

    def _uri_matches_template(self, uri: str, template: str) -> bool:
        """
        Check whether a URI matches a given template pattern.

        Args:
            uri: The URI to check.
            template: The template pattern.

        Returns:
            True if the URI matches the template, otherwise False.
        """

        uri_path, _, _ = uri.partition("?")
        regex = self._build_regex(template)
        return bool(regex.match(uri_path))

    async def _notify_resource_added(self, resource: DbResource) -> None:
        """
        Notify subscribers of resource addition.

        Args:
            resource: Resource to add
        """
        event = {
            "type": "resource_added",
            "data": {
                "id": resource.id,
                "uri": resource.uri,
                "name": resource.name,
                "description": resource.description,
                "enabled": resource.enabled,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._publish_event(event)

    async def _notify_resource_updated(self, resource: DbResource) -> None:
        """
        Notify subscribers of resource update.

        Args:
            resource: Resource to update
        """
        event = {
            "type": "resource_updated",
            "data": {
                "id": resource.id,
                "uri": resource.uri,
                "content": resource.content,
                "enabled": resource.enabled,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._publish_event(event)

    async def _publish_event(self, event: Dict[str, Any]) -> None:
        """
        Publish event to all subscribers via the EventService.

        Args:
            event: Event to publish
        """
        await self._event_service.publish_event(event)

    # --- Resource templates ---
    async def list_resource_templates(self, db: Session, include_inactive: bool = False) -> List[ResourceTemplate]:
        """
        List resource templates.

        Args:
            db: Database session
            include_inactive: Whether to include inactive templates

        Returns:
            List of ResourceTemplate objects

        Examples:
            >>> from mcpgateway.services.resource_service import ResourceService
            >>> from unittest.mock import MagicMock, patch
            >>> service = ResourceService()
            >>> db = MagicMock()
            >>> template_obj = MagicMock()
            >>> db.execute.return_value.scalars.return_value.all.return_value = [template_obj]
            >>> with patch('mcpgateway.services.resource_service.ResourceTemplate') as MockResourceTemplate:
            ...     MockResourceTemplate.model_validate.return_value = 'resource_template'
            ...     import asyncio
            ...     result = asyncio.run(service.list_resource_templates(db))
            ...     result == ['resource_template']
            True
        """
        query = select(DbResource).where(DbResource.uri_template.isnot(None))
        if not include_inactive:
            query = query.where(DbResource.enabled)
        # Cursor-based pagination logic can be implemented here in the future.
        templates = db.execute(query).scalars().all()
        result = [ResourceTemplate.model_validate(t) for t in templates]
        return result

    # --- Metrics ---
    async def aggregate_metrics(self, db: Session) -> ResourceMetrics:
        """
        Aggregate metrics for all resource invocations across all resources.

        Uses in-memory caching (10s TTL) to reduce database load under high
        request rates. Cache is invalidated when metrics are reset.

        Args:
            db: Database session

        Returns:
            ResourceMetrics: Aggregated metrics computed from all ResourceMetric records.

        Examples:
            >>> from mcpgateway.services.resource_service import ResourceService
            >>> from unittest.mock import MagicMock
            >>> service = ResourceService()
            >>> db = MagicMock()
            >>> db.execute.return_value.one.return_value = MagicMock(total_executions=0, successful_executions=0, failed_executions=0, min_response_time=None, max_response_time=None, avg_response_time=None, last_execution_time=None)
            >>> import asyncio
            >>> result = asyncio.run(service.aggregate_metrics(db))
            >>> hasattr(result, 'total_executions')
            True
        """
        # Check cache first (if enabled)
        # First-Party
        from mcpgateway.cache.metrics_cache import is_cache_enabled, metrics_cache  # pylint: disable=import-outside-toplevel

        if is_cache_enabled():
            cached = metrics_cache.get("resources")
            if cached is not None:
                return ResourceMetrics(**cached)

        # Execute a single query to get all metrics at once
        result = db.execute(
            select(
                func.count().label("total_executions"),  # pylint: disable=not-callable
                func.sum(case((ResourceMetric.is_success.is_(True), 1), else_=0)).label("successful_executions"),  # pylint: disable=not-callable
                func.sum(case((ResourceMetric.is_success.is_(False), 1), else_=0)).label("failed_executions"),  # pylint: disable=not-callable
                func.min(ResourceMetric.response_time).label("min_response_time"),  # pylint: disable=not-callable
                func.max(ResourceMetric.response_time).label("max_response_time"),  # pylint: disable=not-callable
                func.avg(ResourceMetric.response_time).label("avg_response_time"),  # pylint: disable=not-callable
                func.max(ResourceMetric.timestamp).label("last_execution_time"),  # pylint: disable=not-callable
            ).select_from(ResourceMetric)
        ).one()

        total_executions = result.total_executions or 0
        successful_executions = result.successful_executions or 0
        failed_executions = result.failed_executions or 0

        metrics = ResourceMetrics(
            total_executions=total_executions,
            successful_executions=successful_executions,
            failed_executions=failed_executions,
            failure_rate=(failed_executions / total_executions) if total_executions > 0 else 0.0,
            min_response_time=result.min_response_time,
            max_response_time=result.max_response_time,
            avg_response_time=result.avg_response_time,
            last_execution_time=result.last_execution_time,
        )

        # Cache the result as dict for serialization compatibility (if enabled)
        if is_cache_enabled():
            metrics_cache.set("resources", metrics.model_dump())

        return metrics

    async def reset_metrics(self, db: Session) -> None:
        """
        Reset all resource metrics by deleting all records from the resource metrics table.

        Args:
            db: Database session

        Examples:
            >>> from mcpgateway.services.resource_service import ResourceService
            >>> from unittest.mock import MagicMock
            >>> service = ResourceService()
            >>> db = MagicMock()
            >>> db.execute = MagicMock()
            >>> db.commit = MagicMock()
            >>> import asyncio
            >>> asyncio.run(service.reset_metrics(db))
        """
        db.execute(delete(ResourceMetric))
        db.commit()

        # Invalidate metrics cache
        # First-Party
        from mcpgateway.cache.metrics_cache import metrics_cache  # pylint: disable=import-outside-toplevel

        metrics_cache.invalidate("resources")
        metrics_cache.invalidate_prefix("top_resources:")
