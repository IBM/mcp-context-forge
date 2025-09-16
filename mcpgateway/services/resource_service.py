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
    >>> hasattr(service, '_event_subscribers')
    True
    >>> hasattr(service, '_template_cache')
    True
    >>> isinstance(service._event_subscribers, dict)
    True
"""

# Standard
import asyncio
from datetime import datetime, timezone
import mimetypes
import os
import re
import time
from typing import Any, AsyncGenerator, Dict, List, Optional, Union
import uuid

# Third-Party
import parse
from sqlalchemy import case, delete, desc, Float, func, not_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import Resource as DbResource
from mcpgateway.db import ResourceMetric
from mcpgateway.db import ResourceSubscription as DbSubscription
from mcpgateway.db import server_resource_association
from mcpgateway.models import ResourceContent, ResourceTemplate, TextContent
from mcpgateway.observability import create_span
from mcpgateway.schemas import ResourceCreate, ResourceMetrics, ResourceRead, ResourceSubscription, ResourceUpdate, TopPerformer
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.utils.metrics_common import build_top_performers
from mcpgateway.utils.sqlalchemy_modifier import json_contains_expr

# Plugin support imports (conditional)
try:
    # First-Party
    from mcpgateway.plugins.framework import GlobalContext, PluginManager, ResourcePostFetchPayload, ResourcePreFetchPayload

    PLUGINS_AVAILABLE = True
except ImportError:
    PLUGINS_AVAILABLE = False

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class ResourceError(Exception):
    """Base class for resource-related errors."""


class ResourceNotFoundError(ResourceError):
    """Raised when a requested resource is not found."""


class ResourceURIConflictError(ResourceError):
    """Raised when a resource URI conflicts with existing (active or inactive) resource."""

    def __init__(self, uri: str, is_active: bool = True, resource_id: Optional[int] = None):
        """Initialize the error with resource information.

        Args:
            uri: The conflicting resource URI
            is_active: Whether the existing resource is active
            resource_id: ID of the existing resource if available
        """
        self.uri = uri
        self.is_active = is_active
        self.resource_id = resource_id
        message = f"Resource already exists with URI: {uri}"
        if not is_active:
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
        self._event_subscribers: Dict[str, List[asyncio.Queue]] = {}
        self._template_cache: Dict[str, ResourceTemplate] = {}

        # Initialize plugin manager if plugins are enabled in settings
        self._plugin_manager = None
        if PLUGINS_AVAILABLE:
            try:
                # First-Party
                from mcpgateway.config import settings  # pylint: disable=import-outside-toplevel

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

    async def shutdown(self) -> None:
        """Shutdown the service."""
        # Clear subscriptions
        self._event_subscribers.clear()
        logger.info("Resource service shutdown complete")

    async def get_top_resources(self, db: Session, limit: int = 5) -> List[TopPerformer]:
        """Retrieve the top-performing resources based on execution count.

        Queries the database to get resources with their metrics, ordered by the number of executions
        in descending order. Uses the resource URI as the name field for TopPerformer objects.
        Returns a list of TopPerformer objects containing resource details and performance metrics.

        Args:
            db (Session): Database session for querying resource metrics.
            limit (int): Maximum number of resources to return. Defaults to 5.

        Returns:
            List[TopPerformer]: A list of TopPerformer objects, each containing:
                - id: Resource ID.
                - name: Resource URI (used as the name field).
                - execution_count: Total number of executions.
                - avg_response_time: Average response time in seconds, or None if no metrics.
                - success_rate: Success rate percentage, or None if no metrics.
                - last_execution: Timestamp of the last execution, or None if no metrics.
        """
        results = (
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
            .limit(limit)
            .all()
        )

        return build_top_performers(results)

    def _convert_resource_to_read(self, resource: DbResource) -> ResourceRead:
        """
        Converts a DbResource instance into a ResourceRead model, including aggregated metrics.

        Args:
            resource (DbResource): The ORM instance of the resource.

        Returns:
            ResourceRead: The Pydantic model representing the resource, including aggregated metrics.

        Examples:
            >>> from types import SimpleNamespace
            >>> from datetime import datetime, timezone
            >>> svc = ResourceService()
            >>> now = datetime.now(timezone.utc)
            >>> # Fake metrics
            >>> m1 = SimpleNamespace(is_success=True, response_time=0.1, timestamp=now)
            >>> m2 = SimpleNamespace(is_success=False, response_time=0.3, timestamp=now)
            >>> r = SimpleNamespace(
            ...     id=1, uri='res://x', name='R', description=None, mime_type='text/plain', size=123,
            ...     created_at=now, updated_at=now, is_active=True, tags=['t'], metrics=[m1, m2]
            ... )
            >>> out = svc._convert_resource_to_read(r)
            >>> out.metrics.total_executions
            2
            >>> out.metrics.successful_executions
            1
        """
        resource_dict = resource.__dict__.copy()
        # Remove SQLAlchemy state and any pre-existing 'metrics' attribute
        resource_dict.pop("_sa_instance_state", None)
        resource_dict.pop("metrics", None)

        # Compute aggregated metrics from the resource's metrics list.
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
        resource_dict["tags"] = resource.tags or []

        # Include metadata fields for proper API response
        resource_dict["created_by"] = getattr(resource, "created_by", None)
        resource_dict["modified_by"] = getattr(resource, "modified_by", None)
        resource_dict["created_at"] = getattr(resource, "created_at", None)
        resource_dict["updated_at"] = getattr(resource, "updated_at", None)
        resource_dict["version"] = getattr(resource, "version", None)

        return ResourceRead.model_validate(resource_dict)

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
        visibility: str = "private",
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
                template=resource.template,
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
            return self._convert_resource_to_read(db_resource)
        except IntegrityError as ie:
            logger.error(f"IntegrityErrors in group: {ie}")
            raise ie
        except Exception as e:
            db.rollback()
            raise ResourceError(f"Failed to register resource: {str(e)}")

    async def list_resources(self, db: Session, include_inactive: bool = False, tags: Optional[List[str]] = None) -> List[ResourceRead]:
        """
        Retrieve a list of registered resources from the database.

        This method retrieves resources from the database and converts them into a list
        of ResourceRead objects. It supports filtering out inactive resources based on the
        include_inactive parameter. The cursor parameter is reserved for future pagination support
        but is currently not implemented.

        Args:
            db (Session): The SQLAlchemy database session.
            include_inactive (bool): If True, include inactive resources in the result.
                Defaults to False.
            tags (Optional[List[str]]): Filter resources by tags. If provided, only resources with at least one matching tag will be returned.

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
            >>> result = asyncio.run(service.list_resources(db))
            >>> isinstance(result, list)
            True

            With tags filter:
            >>> db2 = MagicMock()
            >>> bind = MagicMock()
            >>> bind.dialect = MagicMock()
            >>> bind.dialect.name = "sqlite"           # or "postgresql" / "mysql"
            >>> db2.get_bind.return_value = bind
            >>> db2.execute.return_value.scalars.return_value.all.return_value = [MagicMock()]
            >>> result2 = asyncio.run(service.list_resources(db2, tags=['api']))
            >>> isinstance(result2, list)
            True
        """
        query = select(DbResource)
        if not include_inactive:
            query = query.where(DbResource.is_active)

        # Add tag filtering if tags are provided
        if tags:
            query = query.where(json_contains_expr(db, DbResource.tags, tags, match_any=True))

        # Cursor-based pagination logic can be implemented here in the future.
        resources = db.execute(query).scalars().all()
        return [self._convert_resource_to_read(r) for r in resources]

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
            >>> # Force DB to return one fake row
            >>> db.execute.return_value.scalars.return_value.all.return_value = ["raw"]
            >>> service._convert_resource_to_read = MagicMock(return_value="converted")
            >>> asyncio.run(service.list_resources_for_user(db, "user@example.com"))
            ['converted']

            Without team_id (default/public access):
            >>> db2 = MagicMock()
            >>> db2.execute.return_value.scalars.return_value.all.return_value = ["raw_resource2"]
            >>> service._convert_resource_to_read = MagicMock(return_value="converted2")
            >>> out2 = asyncio.run(service.list_resources_for_user(db2, "user@example.com"))
            >>> out2
            ['converted2']
        """
        # First-Party
        from mcpgateway.services.team_management_service import TeamManagementService  # pylint: disable=import-outside-toplevel

        # Build query following existing patterns from list_resources()
        query = select(DbResource)

        # Apply active/inactive filter
        if not include_inactive:
            query = query.where(DbResource.is_active)

        if team_id:
            # Filter by specific team
            query = query.where(DbResource.team_id == team_id)

            # Validate user has access to team
            team_service = TeamManagementService(db)
            user_teams = await team_service.get_user_teams(user_email)
            team_ids = [team.id for team in user_teams]

            if team_id not in team_ids:
                return []  # No access to team
        else:
            # Get user's accessible teams
            team_service = TeamManagementService(db)
            user_teams = await team_service.get_user_teams(user_email)
            team_ids = [team.id for team in user_teams]

            # Build access conditions following existing patterns
            # Third-Party
            from sqlalchemy import and_, or_  # pylint: disable=import-outside-toplevel

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
        return [self._convert_resource_to_read(r) for r in resources]

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
        query = select(DbResource).join(server_resource_association, DbResource.id == server_resource_association.c.resource_id).where(server_resource_association.c.server_id == server_id)
        if not include_inactive:
            query = query.where(DbResource.is_active)
        # Cursor-based pagination logic can be implemented here in the future.
        resources = db.execute(query).scalars().all()
        return [self._convert_resource_to_read(r) for r in resources]

    async def read_resource(self, db: Session, uri: str, request_id: Optional[str] = None, user: Optional[str] = None, server_id: Optional[str] = None) -> ResourceContent:
        """Read a resource's content with plugin hook support.

        Args:
            db: Database session
            uri: Resource URI to read
            request_id: Optional request ID for tracing
            user: Optional user making the request
            server_id: Optional server ID for context

        Returns:
            Resource content object

        Raises:
            ResourceNotFoundError: If resource not found
            ResourceError: If blocked by plugin
            PluginError: If encounters issue with plugin
            PluginViolationError: If plugin violated the request. Example - In case of OPA plugin, if the request is denied by policy.

        Examples:
            >>> from mcpgateway.services.resource_service import ResourceService
            >>> from unittest.mock import MagicMock
            >>> from mcpgateway.models import ResourceContent
            >>> service = ResourceService()
            >>> db = MagicMock()
            >>> uri = 'http://example.com/resource.txt'
            >>> db.execute.return_value.scalar_one_or_none.return_value = MagicMock(content='test')
            >>> import asyncio
            >>> result = asyncio.run(service.read_resource(db, uri))
            >>> isinstance(result, ResourceContent)
            True

            Not found case returns ResourceNotFoundError:
            >>> db2 = MagicMock()
            >>> db2.execute.return_value.scalar_one_or_none.return_value = None
            >>> def _nf():
            ...     try:
            ...         asyncio.run(service.read_resource(db2, 'abc'))
            ...     except ResourceNotFoundError:
            ...         return True
            >>> _nf()
            True
        """
        start_time = time.monotonic()

        # Create trace span for resource reading
        with create_span(
            "resource.read",
            {
                "resource.uri": uri,
                "user": user or "anonymous",
                "server_id": server_id,
                "request_id": request_id,
                "http.url": uri if uri.startswith("http") else None,
                "resource.type": "template" if ("{" in uri and "}" in uri) else "static",
            },
        ) as span:
            # Generate request ID if not provided
            if not request_id:
                request_id = str(uuid.uuid4())

            original_uri = uri
            contexts = None

            # Call pre-fetch hooks if plugin manager is available
            plugin_eligible = bool(self._plugin_manager and PLUGINS_AVAILABLE and ("://" in uri))
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

                global_context = GlobalContext(request_id=request_id, user=user_id, server_id=server_id)

                # Create pre-fetch payload
                pre_payload = ResourcePreFetchPayload(uri=uri, metadata={})

                # Execute pre-fetch hooks
                pre_result, contexts = await self._plugin_manager.resource_pre_fetch(pre_payload, global_context, violations_as_exceptions=True)
                # Use modified URI if plugin changed it
                if pre_result.modified_payload:
                    uri = pre_result.modified_payload.uri
                    logger.debug(f"Resource URI modified by plugin: {original_uri} -> {uri}")

            # Original resource fetching logic
            # Check for template
            if "{" in uri and "}" in uri:
                content = await self._read_template_resource(uri)
            else:
                # Find resource
                resource = db.execute(select(DbResource).where(DbResource.uri == uri).where(DbResource.is_active)).scalar_one_or_none()

                if not resource:
                    # Check if inactive resource exists
                    inactive_resource = db.execute(select(DbResource).where(DbResource.uri == uri).where(not_(DbResource.is_active))).scalar_one_or_none()

                    if inactive_resource:
                        raise ResourceNotFoundError(f"Resource '{uri}' exists but is inactive")

                    raise ResourceNotFoundError(f"Resource not found: {uri}")

                content = resource.content

            # Call post-fetch hooks if plugin manager is available
            if plugin_eligible:
                # Create post-fetch payload
                post_payload = ResourcePostFetchPayload(uri=original_uri, content=content)

                # Execute post-fetch hooks
                post_result, _ = await self._plugin_manager.resource_post_fetch(post_payload, global_context, contexts, violations_as_exceptions=True)  # Pass contexts from pre-fetch

                # Use modified content if plugin changed it
                if post_result.modified_payload:
                    content = post_result.modified_payload.content
                    logger.debug(f"Resource content modified by plugin for URI: {original_uri}")

            # Set success attributes on span
            if span:
                span.set_attribute("success", True)
                span.set_attribute("duration.ms", (time.monotonic() - start_time) * 1000)
                if content:
                    span.set_attribute("content.size", len(str(content)))

            # Return standardized content without breaking callers that expect passthrough
            # Prefer returning first-class content models or objects with content-like attributes.
            # ResourceContent and TextContent already imported at top level

            # If content is already a Pydantic content model, return as-is
            if isinstance(content, (ResourceContent, TextContent)):
                return content

            # If content is any object that quacks like content (e.g., MagicMock with .text/.blob), return as-is
            if hasattr(content, "text") or hasattr(content, "blob"):
                return content

            # Normalize primitive types to ResourceContent
            if isinstance(content, bytes):
                return ResourceContent(type="resource", uri=original_uri, blob=content)
            if isinstance(content, str):
                return ResourceContent(type="resource", uri=original_uri, text=content)

            # Fallback to stringified content
            return ResourceContent(type="resource", uri=original_uri, text=str(content))

    async def toggle_resource_status(self, db: Session, resource_id: int, activate: bool) -> ResourceRead:
        """
        Toggle the activation status of a resource.

        Args:
            db: Database session
            resource_id: Resource ID
            activate: True to activate, False to deactivate

        Returns:
            The updated ResourceRead object

        Raises:
            ResourceNotFoundError: If the resource is not found
            ResourceError: For other errors

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

            # Update status if it's different
            if resource.is_active != activate:
                resource.is_active = activate
                resource.updated_at = datetime.now(timezone.utc)
                db.commit()
                db.refresh(resource)

                # Notify subscribers
                if activate:
                    await self._notify_resource_activated(resource)
                else:
                    await self._notify_resource_deactivated(resource)

                logger.info(f"Resource {resource.uri} {'activated' if activate else 'deactivated'}")

            return self._convert_resource_to_read(resource)

        except Exception as e:
            db.rollback()
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
            resource = db.execute(select(DbResource).where(DbResource.uri == subscription.uri).where(DbResource.is_active)).scalar_one_or_none()

            if not resource:
                # Check if inactive resource exists
                inactive_resource = db.execute(select(DbResource).where(DbResource.uri == subscription.uri).where(not_(DbResource.is_active))).scalar_one_or_none()

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
        uri: str,
        resource_update: ResourceUpdate,
        modified_by: Optional[str] = None,
        modified_from_ip: Optional[str] = None,
        modified_via: Optional[str] = None,
        modified_user_agent: Optional[str] = None,
    ) -> ResourceRead:
        """
        Update a resource.

        Args:
            db: Database session
            uri: Resource URI
            resource_update: Resource update object
            modified_by: Username of the person modifying the resource
            modified_from_ip: IP address where the modification request originated
            modified_via: Source of modification (ui/api/import)
            modified_user_agent: User agent string from the modification request

        Returns:
            The updated ResourceRead object

        Raises:
            ResourceNotFoundError: If the resource is not found
            ResourceError: For other update errors
            IntegrityError: If a database integrity error occurs.
            Exception: For unexpected errors

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
            >>> service._notify_resource_updated = AsyncMock()
            >>> service._convert_resource_to_read = MagicMock(return_value='resource_read')
            >>> ResourceRead.model_validate = MagicMock(return_value='resource_read')
            >>> import asyncio
            >>> asyncio.run(service.update_resource(db, 'uri', MagicMock()))
            'resource_read'
        """
        try:
            # Find resource
            resource = db.execute(select(DbResource).where(DbResource.uri == uri).where(DbResource.is_active)).scalar_one_or_none()

            if not resource:
                # Check if inactive resource exists
                inactive_resource = db.execute(select(DbResource).where(DbResource.uri == uri).where(not_(DbResource.is_active))).scalar_one_or_none()

                if inactive_resource:
                    raise ResourceNotFoundError(f"Resource '{uri}' exists but is inactive")

                raise ResourceNotFoundError(f"Resource not found: {uri}")

            # Update fields if provided
            if resource_update.name is not None:
                resource.name = resource_update.name
            if resource_update.description is not None:
                resource.description = resource_update.description
            if resource_update.mime_type is not None:
                resource.mime_type = resource_update.mime_type
            if resource_update.template is not None:
                resource.template = resource_update.template

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

            # Notify subscribers
            await self._notify_resource_updated(resource)

            logger.info(f"Updated resource: {uri}")
            return self._convert_resource_to_read(resource)
        except IntegrityError as ie:
            db.rollback()
            logger.error(f"IntegrityErrors in group: {ie}")
            raise ie
        except Exception as e:
            db.rollback()
            if isinstance(e, ResourceNotFoundError):
                raise e
            raise ResourceError(f"Failed to update resource: {str(e)}")

    async def delete_resource(self, db: Session, uri: str) -> None:
        """
        Delete a resource.

        Args:
            db: Database session
            uri: Resource URI

        Raises:
            ResourceNotFoundError: If the resource is not found
            ResourceError: For other deletion errors

        Examples:
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
            >>> asyncio.run(service.delete_resource(db, 'uri'))
        """
        try:
            # Find resource by its URI.
            resource = db.execute(select(DbResource).where(DbResource.uri == uri)).scalar_one_or_none()

            if not resource:
                # If resource doesn't exist, rollback and re-raise a ResourceNotFoundError.
                db.rollback()
                raise ResourceNotFoundError(f"Resource not found: {uri}")

            # Store resource info for notification before deletion.
            resource_info = {
                "id": resource.id,
                "uri": resource.uri,
                "name": resource.name,
            }

            # Remove subscriptions using SQLAlchemy's delete() expression.
            db.execute(delete(DbSubscription).where(DbSubscription.resource_id == resource.id))

            # Hard delete the resource.
            db.delete(resource)
            db.commit()

            # Notify subscribers.
            await self._notify_resource_deleted(resource_info)

            logger.info(f"Permanently deleted resource: {uri}")

        except ResourceNotFoundError:
            # ResourceNotFoundError is re-raised to be handled in the endpoint.
            raise
        except Exception as e:
            db.rollback()
            raise ResourceError(f"Failed to delete resource: {str(e)}")

    async def get_resource_by_uri(self, db: Session, uri: str, include_inactive: bool = False) -> ResourceRead:
        """
        Get a resource by URI.

        Args:
            db: Database session
            uri: Resource URI
            include_inactive: Whether to include inactive resources

        Returns:
            ResourceRead object

        Raises:
            ResourceNotFoundError: If the resource is not found

        Examples:
            >>> from mcpgateway.services.resource_service import ResourceService
            >>> from unittest.mock import MagicMock
            >>> service = ResourceService()
            >>> db = MagicMock()
            >>> resource = MagicMock()
            >>> db.execute.return_value.scalar_one_or_none.return_value = resource
            >>> service._convert_resource_to_read = MagicMock(return_value='resource_read')
            >>> import asyncio
            >>> asyncio.run(service.get_resource_by_uri(db, 'uri'))
            'resource_read'
        """
        query = select(DbResource).where(DbResource.uri == uri)

        if not include_inactive:
            query = query.where(DbResource.is_active)

        resource = db.execute(query).scalar_one_or_none()

        if not resource:
            if not include_inactive:
                # Check if inactive resource exists
                inactive_resource = db.execute(select(DbResource).where(DbResource.uri == uri).where(not_(DbResource.is_active))).scalar_one_or_none()

                if inactive_resource:
                    raise ResourceNotFoundError(f"Resource '{uri}' exists but is inactive")

            raise ResourceNotFoundError(f"Resource not found: {uri}")

        return self._convert_resource_to_read(resource)

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
                "is_active": True,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._publish_event(resource.uri, event)

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
                "is_active": False,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._publish_event(resource.uri, event)

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
        await self._publish_event(resource_info["uri"], event)

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
                "is_active": False,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._publish_event(resource.uri, event)

    async def subscribe_events(self, uri: Optional[str] = None) -> AsyncGenerator[Dict[str, Any], None]:
        """Subscribe to resource events.

        Args:
            uri: Optional URI to filter events

        Yields:
            Resource event messages
        """
        queue: asyncio.Queue = asyncio.Queue()

        if uri:
            if uri not in self._event_subscribers:
                self._event_subscribers[uri] = []
            self._event_subscribers[uri].append(queue)
        else:
            self._event_subscribers["*"] = self._event_subscribers.get("*", [])
            self._event_subscribers["*"].append(queue)

        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            if uri:
                self._event_subscribers[uri].remove(queue)
                if not self._event_subscribers[uri]:
                    del self._event_subscribers[uri]
            else:
                self._event_subscribers["*"].remove(queue)
                if not self._event_subscribers["*"]:
                    del self._event_subscribers["*"]

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

    async def _read_template_resource(self, uri: str) -> ResourceContent:
        """Read a templated resource.

        Args:
            uri: Template URI with parameters

        Returns:
            Resource content

        Raises:
            ResourceNotFoundError: If template not found
            ResourceError: For other template errors
            NotImplementedError: When binary template is passed
        """
        # Find matching template
        template = None
        for cached in self._template_cache.values():
            if self._uri_matches_template(uri, cached.uri_template):
                template = cached
                break

        if not template:
            raise ResourceNotFoundError(f"No template matches URI: {uri}")

        try:
            # Extract parameters
            params = self._extract_template_params(uri, template.uri_template)

            # Generate content
            if template.mime_type and template.mime_type.startswith("text/"):
                content = template.uri_template.format(**params)
                return TextContent(type="text", text=content)

            # Handle binary template
            raise NotImplementedError("Binary resource templates not yet supported")

        except Exception as e:
            raise ResourceError(f"Failed to process template: {str(e)}")

    def _uri_matches_template(self, uri: str, template: str) -> bool:
        """Check if URI matches a template pattern.

        Args:
            uri: URI to check
            template: Template pattern

        Returns:
            True if URI matches template
        """
        # Convert template to regex pattern

        pattern = re.escape(template).replace(r"\{.*?\}", r"[^/]+")
        return bool(re.match(pattern, uri))

    def _extract_template_params(self, uri: str, template: str) -> Dict[str, str]:
        """Extract parameters from URI based on template.

        Args:
            uri: URI with parameter values
            template: Template pattern

        Returns:
            Dict of parameter names and values
        """

        result = parse.parse(template, uri)
        return result.named if result else {}

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
                "is_active": resource.is_active,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._publish_event(resource.uri, event)

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
                "is_active": resource.is_active,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._publish_event(resource.uri, event)

    async def _publish_event(self, uri: str, event: Dict[str, Any]) -> None:
        """Publish event to relevant subscribers.

        Args:
            uri: Resource URI event relates to
            event: Event data to publish
        """
        # Notify resource-specific subscribers
        if uri in self._event_subscribers:
            for queue in self._event_subscribers[uri]:
                await queue.put(event)

        # Notify global subscribers
        if "*" in self._event_subscribers:
            for queue in self._event_subscribers["*"]:
                await queue.put(event)

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
        query = select(DbResource).where(DbResource.template.isnot(None))
        if not include_inactive:
            query = query.where(DbResource.is_active)
        # Cursor-based pagination logic can be implemented here in the future.
        templates = db.execute(query).scalars().all()
        return [ResourceTemplate.model_validate(t) for t in templates]

    # --- Metrics ---
    async def aggregate_metrics(self, db: Session) -> ResourceMetrics:
        """
        Aggregate metrics for all resource invocations across all resources.

        Args:
            db: Database session

        Returns:
            ResourceMetrics: Aggregated metrics computed from all ResourceMetric records.

        Examples:
            >>> from mcpgateway.services.resource_service import ResourceService
            >>> from unittest.mock import MagicMock
            >>> service = ResourceService()
            >>> db = MagicMock()
            >>> db.execute.return_value.scalar.return_value = 0
            >>> import asyncio
            >>> result = asyncio.run(service.aggregate_metrics(db))
            >>> hasattr(result, 'total_executions')
            True
        """
        total_executions = db.execute(select(func.count()).select_from(ResourceMetric)).scalar() or 0  # pylint: disable=not-callable

        successful_executions = db.execute(select(func.count()).select_from(ResourceMetric).where(ResourceMetric.is_success.is_(True))).scalar() or 0  # pylint: disable=not-callable

        failed_executions = db.execute(select(func.count()).select_from(ResourceMetric).where(ResourceMetric.is_success.is_(False))).scalar() or 0  # pylint: disable=not-callable

        min_response_time = db.execute(select(func.min(ResourceMetric.response_time))).scalar()

        max_response_time = db.execute(select(func.max(ResourceMetric.response_time))).scalar()

        avg_response_time = db.execute(select(func.avg(ResourceMetric.response_time))).scalar()

        last_execution_time = db.execute(select(func.max(ResourceMetric.timestamp))).scalar()

        return ResourceMetrics(
            total_executions=total_executions,
            successful_executions=successful_executions,
            failed_executions=failed_executions,
            failure_rate=(failed_executions / total_executions) if total_executions > 0 else 0.0,
            min_response_time=min_response_time,
            max_response_time=max_response_time,
            avg_response_time=avg_response_time,
            last_execution_time=last_execution_time,
        )

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
