# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/server_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

ContextForge Server Service

This module implements server management for the MCP Servers Catalog.
It handles server registration, listing, retrieval, updates, activation toggling, and deletion.
It also publishes event notifications for server changes.
"""

# Standard
import asyncio
import binascii
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, NamedTuple, Optional, Union

# Third-Party
import httpx
from pydantic import ValidationError
from sqlalchemy import and_, delete, desc
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import joinedload, selectinload, Session, with_loader_criteria

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import A2AAgent as DbA2AAgent
from mcpgateway.db import Base
from mcpgateway.db import EmailTeam as DbEmailTeam
from mcpgateway.db import EmailTeamMember as DbEmailTeamMember
from mcpgateway.db import get_for_update
from mcpgateway.db import Prompt as DbPrompt
from mcpgateway.db import Resource as DbResource
from mcpgateway.db import Server as DbServer
from mcpgateway.db import ServerMetric, ServerMetricsHourly
from mcpgateway.db import Tool as DbTool
from mcpgateway.schemas import ServerCreate, ServerMetrics, ServerRead, ServerUpdate, TopPerformer
from mcpgateway.services.audit_trail_service import get_audit_trail_service
from mcpgateway.services.base_service import BaseService
from mcpgateway.services.encryption_service import protect_oauth_config_for_storage
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.metrics_cleanup_service import delete_metrics_in_batches, pause_rollup_during_purge
from mcpgateway.services.performance_tracker import get_performance_tracker
from mcpgateway.services.structured_logger import get_structured_logger
from mcpgateway.services.team_management_service import TeamManagementService
from mcpgateway.utils.metrics_common import build_top_performers
from mcpgateway.utils.pagination import unified_paginate
from mcpgateway.utils.sqlalchemy_modifier import json_contains_tag_expr

# ---------------------------------------------------------------------------
# Server-associable entity registry
# ---------------------------------------------------------------------------
# The single source of truth for entity types that have many-to-many
# relationships with DbServer.  All other metadata (relationship attribute
# name, schema input field, selectinload options) is derived from
# SQLAlchemy mapper introspection so that adding a fifth entity type
# requires only one new entry here.

SERVER_ASSOCIABLE_ENTITY_MODELS: tuple[type[Base], ...] = (DbTool, DbResource, DbPrompt, DbA2AAgent)


class _AssociationType(NamedTuple):
    """Metadata for a single server-associable entity type."""

    model: type[Base]
    rel_attr: str
    input_field: str
    label: str


_server_rels: dict[type[Base], Any] = {rel.mapper.class_: rel for rel in sa_inspect(DbServer).relationships if rel.mapper.class_ in set(SERVER_ASSOCIABLE_ENTITY_MODELS)}
_LABEL_OVERRIDES: dict[type[Base], str] = {DbA2AAgent: "A2A Agent"}

SERVER_ASSOCIATION_TYPES: list[_AssociationType] = [
    _AssociationType(
        model=m,
        rel_attr=_server_rels[m].key,
        input_field=f"associated_{_server_rels[m].key}",
        label=_LABEL_OVERRIDES.get(m, m.__name__),
    )
    for m in SERVER_ASSOCIABLE_ENTITY_MODELS
]

SERVER_ASSOCIATION_SELECTINLOADS: list[Any] = [selectinload(getattr(DbServer, at.rel_attr)) for at in SERVER_ASSOCIATION_TYPES]

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


def _validate_server_team_assignment(db: Session, user_email: Optional[str], target_team_id: Optional[str]) -> None:
    """Validate team assignment and ownership requirements for server updates.

    Args:
        db: Database session used for membership checks.
        user_email: Requesting user email. When omitted, ownership checks are skipped
            for system/internal update paths.
        target_team_id: Team identifier to validate.

    Raises:
        ValueError: If team ID is missing, team does not exist, or caller is not
            an active team owner.
    """
    if not target_team_id:
        raise ValueError("Cannot set visibility to 'team' without a team_id")

    team = db.query(DbEmailTeam).filter(DbEmailTeam.id == target_team_id).first()
    if not team:
        raise ValueError(f"Team {target_team_id} not found")

    # Preserve existing behavior for system/internal updates where
    # user context may be intentionally omitted.
    if not user_email:
        return

    membership = (
        db.query(DbEmailTeamMember)
        .filter(DbEmailTeamMember.team_id == target_team_id, DbEmailTeamMember.user_email == user_email, DbEmailTeamMember.is_active, DbEmailTeamMember.role == "owner")
        .first()
    )
    if not membership:
        raise ValueError("User membership in team not sufficient for this update.")


# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class ServerError(Exception):
    """Base class for server-related errors."""


class ServerNotFoundError(ServerError):
    """Raised when a requested server is not found."""


class ServerLockConflictError(ServerError):
    """Raised when a server row is locked by another transaction."""


class ServerNameConflictError(ServerError):
    """Raised when a server name conflicts with an existing one."""

    def __init__(self, name: str, enabled: bool = True, server_id: Optional[str] = None, visibility: str = "public") -> None:
        """
        Initialize a ServerNameConflictError exception.

        This exception indicates a server name conflict, with additional context about visibility,
        whether the conflicting server is active, and its ID if known. The error message starts
        with the visibility information.

        Visibility rules:
            - public: Restricts server names globally (across all teams).
            - team: Restricts server names only within the same team.

        Args:
            name: The server name that caused the conflict.
            enabled: Whether the conflicting server is currently active. Defaults to True.
            server_id: The ID of the conflicting server, if known. Only included in message for inactive servers.
            visibility: The visibility of the conflicting server (e.g., "public", "private", "team").

        Examples:
            >>> error = ServerNameConflictError("My Server")
            >>> str(error)
            'Public Server already exists with name: My Server'
            >>> error = ServerNameConflictError("My Server", enabled=False, server_id=123)
            >>> str(error)
            'Public Server already exists with name: My Server (currently inactive, ID: 123)'
            >>> error.enabled
            False
            >>> error.server_id
            123
            >>> error = ServerNameConflictError("My Server", enabled=False, visibility="team")
            >>> str(error)
            'Team Server already exists with name: My Server (currently inactive, ID: None)'
            >>> error.enabled
            False
            >>> error.server_id is None
            True
        """
        self.name = name
        self.enabled = enabled
        self.server_id = server_id
        message = f"{visibility.capitalize()} Server already exists with name: {name}"
        if not enabled:
            message += f" (currently inactive, ID: {server_id})"
        super().__init__(message)


def _associate_server_entities(db: Session, db_server: DbServer, server_in: ServerCreate) -> None:
    """Associate tools/resources/prompts/a2a_agents with a server during creation.

    Iterates over ``SERVER_ASSOCIATION_TYPES`` and, for each type whose input
    field is non-empty, validates that the referenced IDs exist and appends
    the loaded objects to the corresponding server relationship.
    """
    for at in SERVER_ASSOCIATION_TYPES:
        input_ids = getattr(server_in, at.input_field, None)
        if not input_ids:
            continue
        ids = [id_.strip() for id_ in input_ids if id_.strip()]
        if not ids:
            continue
        rel = getattr(db_server, at.rel_attr)
        if len(ids) > 1:
            objs = db.execute(select(at.model).where(at.model.id.in_(ids))).scalars().all()
            found = {o.id for o in objs}
            missing = set(ids) - found
            if missing:
                raise ServerError(f"{at.label}s with ids {missing} do not exist.")
            rel.extend(objs)
            if at.model is DbA2AAgent:
                for obj in objs:
                    logger.info(f"A2A agent {obj.name} associated with server {db_server.name}")
        else:
            obj = db.get(at.model, ids[0])
            if not obj:
                raise ServerError(f"{at.label} with id {ids[0]} does not exist.")
            rel.append(obj)
            if at.model is DbA2AAgent:
                logger.info(f"A2A agent {obj.name} associated with server {db_server.name}")


def _update_server_associations(db: Session, server: DbServer, server_update: ServerUpdate) -> None:
    """Replace tool/resource/prompt/a2a_agent associations during server update.

    For each association type whose input field is explicitly provided (not
    ``None``), clears the existing relationship and re-populates it from the
    supplied IDs.
    """
    for at in SERVER_ASSOCIATION_TYPES:
        new_ids = getattr(server_update, at.input_field, None)
        if new_ids is None:
            continue
        setattr(server, at.rel_attr, [])
        ids = [id_ for id_ in new_ids if id_]
        if ids:
            objs = db.execute(select(at.model).where(at.model.id.in_(ids))).scalars().all()
            setattr(server, at.rel_attr, list(objs))


class ServerService(BaseService):
    """Service for managing MCP Servers in the catalog.

    Provides methods to create, list, retrieve, update, set state, and delete server records.
    Also supports event notifications for changes in server data.
    """

    _visibility_model_cls = DbServer

    def __init__(self) -> None:
        """Initialize a new ServerService instance.

        Sets up the service with:
        - An empty list for event subscribers that will receive server change notifications
        - An HTTP client configured with timeout and SSL verification settings from config

        The HTTP client is used for health checks and other server-related HTTP operations.
        Event subscribers can register to receive notifications about server additions,
        updates, activations, deactivations, and deletions.

        Examples:
            >>> from mcpgateway.services.server_service import ServerService
            >>> service = ServerService()
            >>> isinstance(service._event_subscribers, list)
            True
            >>> len(service._event_subscribers)
            0
            >>> hasattr(service, '_http_client')
            True
        """
        self._event_subscribers: List[asyncio.Queue] = []
        self._http_client = httpx.AsyncClient(
            timeout=settings.federation_timeout,
            verify=not settings.skip_ssl_verify,
            limits=httpx.Limits(
                max_connections=settings.httpx_max_connections,
                max_keepalive_connections=settings.httpx_max_keepalive_connections,
                keepalive_expiry=settings.httpx_keepalive_expiry,
            ),
        )
        self._structured_logger = get_structured_logger("server_service")
        self._audit_trail = get_audit_trail_service()
        self._performance_tracker = get_performance_tracker()

    async def initialize(self) -> None:
        """Initialize the server service."""
        logger.info("Initializing server service")

    async def shutdown(self) -> None:
        """Shutdown the server service."""
        await self._http_client.aclose()
        logger.info("Server service shutdown complete")

    # get_top_server
    async def get_top_servers(self, db: Session, limit: Optional[int] = 5, include_deleted: bool = False) -> List[TopPerformer]:
        """Retrieve the top-performing servers based on execution count.

        Queries the database to get servers with their metrics, ordered by the number of executions
        in descending order. Combines recent raw metrics with historical hourly rollups for complete
        historical coverage. Returns a list of TopPerformer objects containing server details and
        performance metrics. Results are cached for performance.

        Args:
            db (Session): Database session for querying server metrics.
            limit (Optional[int]): Maximum number of servers to return. Defaults to 5.
            include_deleted (bool): Whether to include deleted servers from rollups.

        Returns:
            List[TopPerformer]: A list of TopPerformer objects, each containing:
                - id: Server ID.
                - name: Server name.
                - execution_count: Total number of executions.
                - avg_response_time: Average response time in seconds, or None if no metrics.
                - success_rate: Success rate percentage, or None if no metrics.
                - last_execution: Timestamp of the last execution, or None if no metrics.
        """
        # Check cache first (if enabled)
        # First-Party
        from mcpgateway.cache.metrics_cache import is_cache_enabled, metrics_cache  # pylint: disable=import-outside-toplevel

        effective_limit = limit or 5
        cache_key = f"top_servers:{effective_limit}:include_deleted={include_deleted}"

        if is_cache_enabled():
            cached = metrics_cache.get(cache_key)
            if cached is not None:
                return cached

        # Use combined query that includes both raw metrics and rollup data
        # First-Party
        from mcpgateway.services.metrics_query_service import get_top_performers_combined  # pylint: disable=import-outside-toplevel

        results = get_top_performers_combined(
            db=db,
            metric_type="server",
            entity_model=DbServer,
            limit=effective_limit,
            include_deleted=include_deleted,
        )
        top_performers = build_top_performers(results)

        # Cache the result (if enabled)
        if is_cache_enabled():
            metrics_cache.set(cache_key, top_performers)

        return top_performers

    def convert_server_to_read(self, server: DbServer, include_metrics: bool = False) -> ServerRead:
        """
        Converts a DbServer instance into a ServerRead model, optionally including aggregated metrics.

        Args:
            server (DbServer): The ORM instance of the server.
            include_metrics (bool): Whether to include metrics in the result. Defaults to False.
                Set to False for list operations to avoid N+1 query issues.

        Returns:
            ServerRead: The Pydantic model representing the server, optionally including aggregated metrics.

        Examples:
            >>> from types import SimpleNamespace
            >>> from datetime import datetime, timezone
            >>> svc = ServerService()
            >>> now = datetime.now(timezone.utc)
            >>> # Fake metric objects
            >>> m1 = SimpleNamespace(is_success=True, response_time=0.2, timestamp=now)
            >>> m2 = SimpleNamespace(is_success=False, response_time=0.4, timestamp=now)
            >>> server = SimpleNamespace(
            ...     id='s1', name='S', description=None, icon=None,
            ...     created_at=now, updated_at=now, enabled=True,
            ...     associated_tools=[], associated_resources=[], associated_prompts=[], associated_a2a_agents=[],
            ...     tags=[], metrics=[m1, m2],
            ...     metrics_summary={"total_executions": 2, "successful_executions": 1, "failed_executions": 1,
            ...                      "failure_rate": 0.5, "min_response_time": 0.2, "max_response_time": 0.4,
            ...                      "avg_response_time": 0.3, "last_execution_time": now},
            ...     tools=[], resources=[], prompts=[], a2a_agents=[],
            ...     team_id=None, owner_email=None, visibility=None,
            ...     created_by=None, modified_by=None
            ... )
            >>> result = svc.convert_server_to_read(server, include_metrics=True)
            >>> result.metrics.total_executions
            2
            >>> result.metrics.successful_executions
            1
        """
        # Build dict explicitly from attributes to ensure SQLAlchemy populates them
        # (using __dict__.copy() can return empty dict with certain query patterns)
        server_dict = {
            "id": server.id,
            "name": server.name,
            "description": server.description,
            "icon": server.icon,
            "enabled": server.enabled,
            "created_at": server.created_at,
            "updated_at": server.updated_at,
            "team_id": server.team_id,
            "owner_email": server.owner_email,
            "visibility": server.visibility,
            "created_by": server.created_by,
            "created_from_ip": getattr(server, "created_from_ip", None),
            "created_via": getattr(server, "created_via", None),
            "created_user_agent": getattr(server, "created_user_agent", None),
            "modified_by": server.modified_by,
            "modified_from_ip": getattr(server, "modified_from_ip", None),
            "modified_via": getattr(server, "modified_via", None),
            "modified_user_agent": getattr(server, "modified_user_agent", None),
            "import_batch_id": getattr(server, "import_batch_id", None),
            "federation_source": getattr(server, "federation_source", None),
            "version": getattr(server, "version", None),
            "tags": server.tags or [],
            # OAuth 2.0 configuration for RFC 9728 Protected Resource Metadata
            "oauth_enabled": getattr(server, "oauth_enabled", False),
            "oauth_config": getattr(server, "oauth_config", None),
        }

        # Compute aggregated metrics only if requested (avoids N+1 queries in list operations)
        if include_metrics:
            # Use metrics_summary which combines raw + hourly rollup data (matches tool_service pattern)
            metrics = server.metrics_summary
            server_dict["metrics"] = {
                "total_executions": metrics["total_executions"],
                "successful_executions": metrics["successful_executions"],
                "failed_executions": metrics["failed_executions"],
                "failure_rate": metrics["failure_rate"],
                "min_response_time": metrics["min_response_time"],
                "max_response_time": metrics["max_response_time"],
                "avg_response_time": metrics["avg_response_time"],
                "last_execution_time": metrics["last_execution_time"],
            }
        else:
            server_dict["metrics"] = None
        # Add associated IDs from relationships
        # Filter out deactivated entities for consistent API responses
        server_dict["associated_tools"] = [tool.name for tool in server.tools if getattr(tool, "enabled", True)] if server.tools else []
        server_dict["associated_tool_ids"] = [str(tool.id) for tool in server.tools if getattr(tool, "enabled", True)] if server.tools else []
        server_dict["associated_resources"] = [res.id for res in server.resources if getattr(res, "enabled", True)] if server.resources else []
        server_dict["associated_prompts"] = [prompt.id for prompt in server.prompts if getattr(prompt, "enabled", True)] if server.prompts else []
        server_dict["associated_a2a_agents"] = [agent.id for agent in server.a2a_agents if getattr(agent, "enabled", True)] if server.a2a_agents else []

        # Team name is loaded via server.team property from email_team relationship
        server_dict["team"] = getattr(server, "team", None)

        return ServerRead.model_validate(server_dict).masked()

    def _assemble_associated_items(
        self,
        tools: Optional[List[str]],
        resources: Optional[List[str]],
        prompts: Optional[List[str]],
        a2a_agents: Optional[List[str]] = None,
        gateways: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Assemble the associated items dictionary from the separate fields.

        Args:
            tools: List of tool IDs.
            resources: List of resource IDs.
            prompts: List of prompt IDs.
            a2a_agents: List of A2A agent IDs.
            gateways: List of gateway IDs.

        Returns:
            A dictionary with keys "tools", "resources", "prompts", "a2a_agents", and "gateways".

        Examples:
            >>> service = ServerService()
            >>> # Test with all None values
            >>> result = service._assemble_associated_items(None, None, None)
            >>> result
            {'tools': [], 'resources': [], 'prompts': [], 'a2a_agents': [], 'gateways': []}

            >>> # Test with empty lists
            >>> result = service._assemble_associated_items([], [], [])
            >>> result
            {'tools': [], 'resources': [], 'prompts': [], 'a2a_agents': [], 'gateways': []}

            >>> # Test with actual values
            >>> result = service._assemble_associated_items(['tool1', 'tool2'], ['res1'], ['prompt1'])
            >>> result
            {'tools': ['tool1', 'tool2'], 'resources': ['res1'], 'prompts': ['prompt1'], 'a2a_agents': [], 'gateways': []}

            >>> # Test with mixed None and values
            >>> result = service._assemble_associated_items(['tool1'], None, ['prompt1'])
            >>> result
            {'tools': ['tool1'], 'resources': [], 'prompts': ['prompt1'], 'a2a_agents': [], 'gateways': []}
        """
        return {
            "tools": tools or [],
            "resources": resources or [],
            "prompts": prompts or [],
            "a2a_agents": a2a_agents or [],
            "gateways": gateways or [],
        }

    async def register_server(
        self,
        db: Session,
        server_in: ServerCreate,
        created_by: Optional[str] = None,
        created_from_ip: Optional[str] = None,
        created_via: Optional[str] = None,
        created_user_agent: Optional[str] = None,
        team_id: Optional[str] = None,
        owner_email: Optional[str] = None,
        visibility: Optional[str] = "public",
    ) -> ServerRead:
        """
        Register a new server in the catalog and validate that all associated items exist.

        This function performs the following steps:
        1. Checks if a server with the same name already exists.
        2. Creates a new server record.
        3. For each ID provided in associated_tools, associated_resources, and associated_prompts,
            verifies that the corresponding item exists. If an item does not exist, an error is raised.
        4. Associates the verified items to the new server.
        5. Commits the transaction, refreshes the ORM instance, and forces the loading of relationship data.
        6. Constructs a response dictionary that includes lists of associated item IDs.
        7. Notifies subscribers of the addition and returns the validated response.

        Args:
            db (Session): The SQLAlchemy database session.
            server_in (ServerCreate): The server creation schema containing server details and lists of
                associated tool, resource, and prompt IDs (as strings).
            created_by (Optional[str]): Email of the user creating the server, used for ownership tracking.
            created_from_ip (Optional[str]): IP address from which the creation request originated.
            created_via (Optional[str]): Source of creation (api, ui, import).
            created_user_agent (Optional[str]): User agent string from the creation request.
            team_id (Optional[str]): Team ID to assign the server to.
            owner_email (Optional[str]): Email of the user who owns this server.
            visibility (str): Server visibility level (private, team, public).

        Returns:
            ServerRead: The newly created server, with associated item IDs.

        Raises:
            IntegrityError: If a database integrity error occurs.
            ServerNameConflictError: If a server name conflict occurs (public or team visibility).
            ServerError: If any associated tool, resource, or prompt does not exist, or if any other registration error occurs.

        Examples:
            >>> from mcpgateway.services.server_service import ServerService
            >>> from unittest.mock import MagicMock, AsyncMock, patch
            >>> from mcpgateway.schemas import ServerRead
            >>> service = ServerService()
            >>> db = MagicMock()
            >>> server_in = MagicMock()
            >>> server_in.id = None  # No custom UUID for this test
            >>> db.execute.return_value.scalar_one_or_none.return_value = None
            >>> db.add = MagicMock()
            >>> db.commit = MagicMock()
            >>> db.refresh = MagicMock()
            >>> service._notify_server_added = AsyncMock()
            >>> service.convert_server_to_read = MagicMock(return_value='server_read')
            >>> service._structured_logger = MagicMock()  # Mock structured logger to prevent database writes
            >>> service._audit_trail = MagicMock()  # Mock audit trail to prevent database writes
            >>> ServerRead.model_validate = MagicMock(return_value='server_read')
            >>> import asyncio
            >>> asyncio.run(service.register_server(db, server_in))
            'server_read'
        """
        try:
            logger.info(f"Registering server: {server_in.name}")
            oauth_config = await protect_oauth_config_for_storage(getattr(server_in, "oauth_config", None))
            # # Create the new server record.
            db_server = DbServer(
                name=server_in.name,
                description=server_in.description,
                icon=server_in.icon,
                enabled=True,
                tags=server_in.tags or [],
                # Team scoping fields - use schema values if provided, otherwise fallback to parameters
                team_id=getattr(server_in, "team_id", None) or team_id,
                owner_email=getattr(server_in, "owner_email", None) or owner_email or created_by,
                # IMPORTANT: Prefer function parameter over schema default
                # The API has visibility as a separate Body param that should override schema default
                visibility=visibility or getattr(server_in, "visibility", None) or "public",
                # OAuth 2.0 configuration for RFC 9728 Protected Resource Metadata
                oauth_enabled=getattr(server_in, "oauth_enabled", False) or False,
                oauth_config=oauth_config,
                # Metadata fields
                created_by=created_by,
                created_from_ip=created_from_ip,
                created_via=created_via,
                created_user_agent=created_user_agent,
                version=1,
            )
            # Check for existing server with the same name (with row locking to prevent race conditions)
            # The unique constraint is on (team_id, owner_email, name), so we check based on that
            owner_email_to_check = getattr(server_in, "owner_email", None) or owner_email or created_by
            team_id_to_check = getattr(server_in, "team_id", None) or team_id

            # Build conditions based on the actual unique constraint: (team_id, owner_email, name)
            conditions = [
                DbServer.name == server_in.name,  # pylint: disable=comparison-with-callable
                DbServer.team_id == team_id_to_check if team_id_to_check else DbServer.team_id.is_(None),
                DbServer.owner_email == owner_email_to_check if owner_email_to_check else DbServer.owner_email.is_(None),
            ]
            if server_in.id:
                conditions.append(DbServer.id != server_in.id)

            existing_server = get_for_update(db, DbServer, where=and_(*conditions))
            if existing_server:
                raise ServerNameConflictError(server_in.name, enabled=existing_server.enabled, server_id=existing_server.id, visibility=existing_server.visibility)
            # Set custom UUID if provided
            if server_in.id:
                logger.info(f"Setting custom UUID for server: {server_in.id}")
                db_server.id = server_in.id
            logger.info(f"Adding server to DB session: {db_server.name}")
            db.add(db_server)

            _associate_server_entities(db, db_server, server_in)

            # Commit the new record and refresh.
            db.commit()
            db.refresh(db_server)
            # Force load the relationship attributes.
            _ = db_server.tools, db_server.resources, db_server.prompts, db_server.a2a_agents

            # Assemble response data with associated item IDs.
            server_data = {
                "id": db_server.id,
                "name": db_server.name,
                "description": db_server.description,
                "icon": db_server.icon,
                "created_at": db_server.created_at,
                "updated_at": db_server.updated_at,
                "enabled": db_server.enabled,
                "associated_tools": [str(tool.id) for tool in db_server.tools],
                "associated_resources": [str(resource.id) for resource in db_server.resources],
                "associated_prompts": [str(prompt.id) for prompt in db_server.prompts],
            }
            logger.debug(f"Server Data: {server_data}")
            await self._notify_server_added(db_server)
            logger.info(f"Registered server: {server_in.name}")

            # Structured logging: Audit trail for server creation
            self._audit_trail.log_action(
                user_id=created_by or "system",
                action="create_server",
                resource_type="server",
                resource_id=db_server.id,
                details={
                    "server_name": db_server.name,
                    "visibility": visibility,
                    "team_id": team_id,
                    "associated_tools_count": len(db_server.tools),
                    "associated_resources_count": len(db_server.resources),
                    "associated_prompts_count": len(db_server.prompts),
                    "associated_a2a_agents_count": len(db_server.a2a_agents),
                },
                metadata={
                    "created_from_ip": created_from_ip,
                    "created_via": created_via,
                    "created_user_agent": created_user_agent,
                },
            )

            # Structured logging: Log successful server creation
            self._structured_logger.log(
                level="INFO",
                message="Server created successfully",
                event_type="server_created",
                component="server_service",
                server_id=db_server.id,
                server_name=db_server.name,
                visibility=visibility,
                created_by=created_by,
                user_email=created_by,
            )

            # Team name is loaded via db_server.team property from email_team relationship
            return self.convert_server_to_read(db_server)
        except IntegrityError as ie:
            db.rollback()
            logger.error(f"IntegrityErrors in group: {ie}")

            # Structured logging: Log database integrity error
            self._structured_logger.log(
                level="ERROR",
                message="Server creation failed due to database integrity error",
                event_type="server_creation_failed",
                component="server_service",
                server_name=server_in.name,
                error_type="IntegrityError",
                error_message=str(ie),
                created_by=created_by,
                user_email=created_by,
            )
            raise ie
        except ServerNameConflictError as se:
            db.rollback()

            # Structured logging: Log name conflict error
            self._structured_logger.log(
                level="WARNING",
                message="Server creation failed due to name conflict",
                event_type="server_name_conflict",
                component="server_service",
                server_name=server_in.name,
                visibility=visibility,
                created_by=created_by,
                user_email=created_by,
            )
            raise se
        except Exception as ex:
            db.rollback()

            # Structured logging: Log generic server creation failure
            self._structured_logger.log(
                level="ERROR",
                message="Server creation failed",
                event_type="server_creation_failed",
                component="server_service",
                server_name=server_in.name,
                error_type=type(ex).__name__,
                error_message=str(ex),
                created_by=created_by,
                user_email=created_by,
            )
            raise ServerError(f"Failed to register server: {str(ex)}")

    async def list_servers(
        self,
        db: Session,
        include_inactive: bool = False,
        include_metrics: bool = False,
        tags: Optional[List[str]] = None,
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        per_page: Optional[int] = None,
        user_email: Optional[str] = None,
        team_id: Optional[str] = None,
        visibility: Optional[str] = None,
        token_teams: Optional[List[str]] = None,
    ) -> Union[tuple[List[ServerRead], Optional[str]], Dict[str, Any]]:
        """List all registered servers with cursor or page-based pagination and optional team filtering.

        Args:
            db: Database session.
            include_inactive: Whether to include inactive servers.
            include_metrics: Whether to include aggregated metrics in the results.
            tags: Filter servers by tags. If provided, only servers with at least one matching tag will be returned.
            cursor: Cursor for pagination (encoded last created_at and id).
            limit: Maximum number of servers to return. None for default, 0 for unlimited.
            page: Page number for page-based pagination (1-indexed). Mutually exclusive with cursor.
            per_page: Items per page for page-based pagination. Defaults to pagination_default_page_size.
            user_email: Email of user for team-based access control. None for no access control.
            team_id: Optional team ID to filter by specific team (requires user_email).
            visibility: Optional visibility filter (private, team, public) (requires user_email).
            token_teams: Optional list of team IDs from the token (None=unrestricted, []=public-only).

        Returns:
            If page is provided: Dict with {"data": [...], "pagination": {...}, "links": {...}}
            If cursor is provided or neither: tuple of (list of ServerRead objects, next_cursor).

        Examples:
            >>> from mcpgateway.services.server_service import ServerService
            >>> from unittest.mock import MagicMock
            >>> service = ServerService()
            >>> db = MagicMock()
            >>> server_read = MagicMock()
            >>> service.convert_server_to_read = MagicMock(return_value=server_read)
            >>> db.execute.return_value.scalars.return_value.all.return_value = [MagicMock()]
            >>> import asyncio
            >>> servers, cursor = asyncio.run(service.list_servers(db))
            >>> isinstance(servers, list) and cursor is None
            True
        """
        # Check cache for first page only
        # SECURITY: Only cache public-only results (token_teams=[])
        # - token_teams=None (admin bypass): Don't cache - admin sees all, should be fresh
        # - token_teams=[] (public-only): Cache - same result for all public-only users
        # - token_teams=[...] (team-scoped): Don't cache - results vary by team
        # - user_email set: Don't cache - results vary by user ownership
        cache = _get_registry_cache()
        is_public_only = token_teams is not None and len(token_teams) == 0
        use_cache = cursor is None and user_email is None and page is None and is_public_only
        if use_cache:
            filters_hash = cache.hash_filters(include_inactive=include_inactive, tags=sorted(tags) if tags else None, visibility=visibility)
            cached = await cache.get("servers", filters_hash)
            if cached is not None:
                # Reconstruct ServerRead objects from cached dicts
                cached_servers = [ServerRead.model_validate(s).masked() for s in cached["servers"]]
                return (cached_servers, cached.get("next_cursor"))

        # Build base query with ordering and eager load relationships to avoid N+1
        # Filter out deactivated tools, resources, prompts, and agents at query level
        query = (
            select(DbServer)
            .options(
                selectinload(DbServer.tools),
                with_loader_criteria(DbTool, DbTool.enabled.is_(True)),
                selectinload(DbServer.resources),
                with_loader_criteria(DbResource, DbResource.enabled.is_(True)),
                selectinload(DbServer.prompts),
                with_loader_criteria(DbPrompt, DbPrompt.enabled.is_(True)),
                selectinload(DbServer.a2a_agents),
                with_loader_criteria(DbA2AAgent, DbA2AAgent.enabled.is_(True)),
                joinedload(DbServer.email_team),
            )
            .order_by(desc(DbServer.created_at), desc(DbServer.id))
        )

        # Eager load metrics relationships to prevent N+1 queries when include_metrics=true
        if include_metrics:
            query = query.options(selectinload(DbServer.metrics), selectinload(DbServer.metrics_hourly))

        # Apply active/inactive filter
        if not include_inactive:
            query = query.where(DbServer.enabled)

        query = await self._apply_access_control(query, db, user_email, token_teams, team_id)

        if visibility:
            query = query.where(DbServer.visibility == visibility)

        # Add tag filtering if tags are provided (supports both List[str] and List[Dict] formats)
        if tags:
            query = query.where(json_contains_tag_expr(db, DbServer.tags, tags, match_any=True))

        # Use unified pagination helper - handles both page and cursor pagination
        pag_result = await unified_paginate(
            db=db,
            query=query,
            page=page,
            per_page=per_page,
            cursor=cursor,
            limit=limit,
            base_url="/admin/servers",  # Used for page-based links
            query_params={"include_inactive": include_inactive} if include_inactive else {},
        )

        next_cursor = None
        # Extract servers based on pagination type
        if page is not None:
            # Page-based: pag_result is a dict
            servers_db = pag_result["data"]
        else:
            # Cursor-based: pag_result is a tuple
            servers_db, next_cursor = pag_result

        db.commit()  # Release transaction to avoid idle-in-transaction

        # Convert to ServerRead (common for both pagination types)
        # Team names are loaded via joinedload(DbServer.email_team)
        result = []
        for s in servers_db:
            try:
                result.append(self.convert_server_to_read(s, include_metrics=include_metrics))
            except (ValidationError, ValueError, KeyError, TypeError, binascii.Error) as e:
                logger.exception(f"Failed to convert server {getattr(s, 'id', 'unknown')} ({getattr(s, 'name', 'unknown')}): {e}")
                # Continue with remaining servers instead of failing completely

        # Return appropriate format based on pagination type
        if page is not None:
            # Page-based format
            return {
                "data": result,
                "pagination": pag_result["pagination"],
                "links": pag_result["links"],
            }

        # Cursor-based format

        # Cache first page results - only for public-only queries (no user/team filtering)
        # SECURITY: Only cache public-only results (token_teams=[]), never admin bypass or team-scoped
        if cursor is None and user_email is None and is_public_only:
            try:
                cache_data = {"servers": [s.model_dump(mode="json") for s in result], "next_cursor": next_cursor}
                await cache.set("servers", cache_data, filters_hash)
            except AttributeError:
                pass  # Skip caching if result objects don't support model_dump (e.g., in doctests)

        return (result, next_cursor)

    async def list_servers_for_user(
        self, db: Session, user_email: str, team_id: Optional[str] = None, visibility: Optional[str] = None, include_inactive: bool = False, skip: int = 0, limit: int = 100
    ) -> List[ServerRead]:
        """
        DEPRECATED: Use list_servers() with user_email parameter instead.

        This method is maintained for backward compatibility but is no longer used.
        New code should call list_servers() with user_email, team_id, and visibility parameters.

        List servers user has access to with team filtering.

        Args:
            db: Database session
            user_email: Email of the user requesting servers
            team_id: Optional team ID to filter by specific team
            visibility: Optional visibility filter (private, team, public)
            include_inactive: Whether to include inactive servers
            skip: Number of servers to skip for pagination
            limit: Maximum number of servers to return

        Returns:
            List[ServerRead]: Servers the user has access to
        """
        # Build query following existing patterns from list_servers()
        team_service = TeamManagementService(db)
        user_teams = await team_service.get_user_teams(user_email)
        team_ids = [team.id for team in user_teams]

        # Eager load relationships to avoid N+1 queries
        # Filter out deactivated tools, resources, prompts, and agents at query level
        query = select(DbServer).options(
            selectinload(DbServer.tools),
            with_loader_criteria(DbTool, DbTool.enabled.is_(True)),
            selectinload(DbServer.resources),
            with_loader_criteria(DbResource, DbResource.enabled.is_(True)),
            selectinload(DbServer.prompts),
            with_loader_criteria(DbPrompt, DbPrompt.enabled.is_(True)),
            selectinload(DbServer.a2a_agents),
            with_loader_criteria(DbA2AAgent, DbA2AAgent.enabled.is_(True)),
            joinedload(DbServer.email_team),
        )

        # Apply active/inactive filter
        if not include_inactive:
            query = query.where(DbServer.enabled)

        if team_id:
            if team_id not in team_ids:
                return []  # No access to team

            access_conditions = []
            # Filter by specific team
            access_conditions.append(and_(DbServer.team_id == team_id, DbServer.visibility.in_(["team", "public"])))

            access_conditions.append(and_(DbServer.team_id == team_id, DbServer.owner_email == user_email))

            query = query.where(or_(*access_conditions))
        else:
            # Get user's accessible teams
            # Build access conditions following existing patterns
            access_conditions = []

            # 1. User's personal resources (owner_email matches)
            access_conditions.append(DbServer.owner_email == user_email)

            # 2. Team resources where user is member
            if team_ids:
                access_conditions.append(and_(DbServer.team_id.in_(team_ids), DbServer.visibility.in_(["team", "public"])))

            # 3. Public resources (if visibility allows)
            access_conditions.append(DbServer.visibility == "public")

            query = query.where(or_(*access_conditions))

        # Apply visibility filter if specified
        if visibility:
            query = query.where(DbServer.visibility == visibility)

        # Apply pagination following existing patterns
        query = query.offset(skip).limit(limit)

        servers = db.execute(query).scalars().all()

        db.commit()  # Release transaction to avoid idle-in-transaction

        # Skip metrics to avoid N+1 queries in list operations
        # Team names are loaded via joinedload(DbServer.email_team)
        result = []
        for s in servers:
            try:
                result.append(self.convert_server_to_read(s, include_metrics=False))
            except (ValidationError, ValueError, KeyError, TypeError, binascii.Error) as e:
                logger.exception(f"Failed to convert server {getattr(s, 'id', 'unknown')} ({getattr(s, 'name', 'unknown')}): {e}")
                # Continue with remaining servers instead of failing completely
        return result

    async def get_server(self, db: Session, server_id: str) -> ServerRead:
        """Retrieve server details by ID.

        Args:
            db: Database session.
            server_id: The unique identifier of the server.

        Returns:
            The corresponding ServerRead object.

        Raises:
            ServerNotFoundError: If no server with the given ID exists.

        Examples:
            >>> from mcpgateway.services.server_service import ServerService
            >>> from unittest.mock import MagicMock
            >>> service = ServerService()
            >>> db = MagicMock()
            >>> server = MagicMock()
            >>> db.get.return_value = server
            >>> service.convert_server_to_read = MagicMock(return_value='server_read')
            >>> import asyncio
            >>> asyncio.run(service.get_server(db, 'server_id'))
            'server_read'
        """
        server = db.execute(
            select(DbServer)
            .options(
                selectinload(DbServer.tools),
                with_loader_criteria(DbTool, DbTool.enabled.is_(True)),
                selectinload(DbServer.resources),
                with_loader_criteria(DbResource, DbResource.enabled.is_(True)),
                selectinload(DbServer.prompts),
                with_loader_criteria(DbPrompt, DbPrompt.enabled.is_(True)),
                selectinload(DbServer.a2a_agents),
                with_loader_criteria(DbA2AAgent, DbA2AAgent.enabled.is_(True)),
                joinedload(DbServer.email_team),
            )
            .where(DbServer.id == server_id)
        ).scalar_one_or_none()
        if not server:
            raise ServerNotFoundError(f"Server not found: {server_id}")
        server_data = {
            "id": server.id,
            "name": server.name,
            "description": server.description,
            "icon": server.icon,
            "created_at": server.created_at,
            "updated_at": server.updated_at,
            "enabled": server.enabled,
            "associated_tools": [tool.name for tool in server.tools],
            "associated_resources": [res.id for res in server.resources],
            "associated_prompts": [prompt.id for prompt in server.prompts],
        }
        logger.debug(f"Server Data: {server_data}")
        # Team name is loaded via server.team property from email_team relationship
        server_read = self.convert_server_to_read(server)

        self._structured_logger.log(
            level="INFO",
            message="Server retrieved successfully",
            event_type="server_viewed",
            component="server_service",
            server_id=server.id,
            server_name=server.name,
            team_id=getattr(server, "team_id", None),
            resource_type="server",
            resource_id=server.id,
            custom_fields={
                "enabled": server.enabled,
                "tool_count": len(getattr(server, "tools", []) or []),
                "resource_count": len(getattr(server, "resources", []) or []),
                "prompt_count": len(getattr(server, "prompts", []) or []),
            },
        )

        self._audit_trail.log_action(
            action="view_server",
            resource_type="server",
            resource_id=server.id,
            resource_name=server.name,
            user_id="system",
            team_id=getattr(server, "team_id", None),
            context={"enabled": server.enabled},
            db=db,
        )

        return server_read

    async def update_server(
        self,
        db: Session,
        server_id: str,
        server_update: ServerUpdate,
        user_email: str,
        modified_by: Optional[str] = None,
        modified_from_ip: Optional[str] = None,
        modified_via: Optional[str] = None,
        modified_user_agent: Optional[str] = None,
    ) -> ServerRead:
        """Update an existing server.

        Args:
            db: Database session.
            server_id: The unique identifier of the server.
            server_update: Server update schema with new data.
            user_email: email of the user performing the update (for permission checks).
            modified_by: Username who modified this server.
            modified_from_ip: IP address from which modification was made.
            modified_via: Source of modification (api, ui, etc.).
            modified_user_agent: User agent of the client making the modification.

        Returns:
            The updated ServerRead object.

        Raises:
            ServerNotFoundError: If the server is not found.
            PermissionError: If user doesn't own the server.
            ServerNameConflictError: If a new name conflicts with an existing server.
            ServerError: For other update errors.
            IntegrityError: If a database integrity error occurs.
            ValueError: If visibility or team constraints are violated.

        Examples:
            >>> from mcpgateway.services.server_service import ServerService
            >>> from unittest.mock import MagicMock, AsyncMock, patch
            >>> from mcpgateway.schemas import ServerRead
            >>> service = ServerService()
            >>> db = MagicMock()
            >>> server = MagicMock()
            >>> server.id = 'server_id'
            >>> server.name = 'test_server'
            >>> server.owner_email = 'user_email'  # Set owner to match user performing update
            >>> server.team_id = None
            >>> server.visibility = 'public'
            >>> db.get.return_value = server
            >>> db.commit = MagicMock()
            >>> db.refresh = MagicMock()
            >>> db.execute.return_value.scalar_one_or_none.return_value = None
            >>> service.convert_server_to_read = MagicMock(return_value='server_read')
            >>> service._structured_logger = MagicMock()  # Mock structured logger to prevent database writes
            >>> service._audit_trail = MagicMock()  # Mock audit trail to prevent database writes
            >>> ServerRead.model_validate = MagicMock(return_value='server_read')
            >>> server_update = MagicMock()
            >>> server_update.id = None  # No UUID change
            >>> server_update.name = None  # No name change
            >>> server_update.description = None
            >>> server_update.icon = None
            >>> server_update.visibility = None
            >>> server_update.team_id = None
            >>> import asyncio
            >>> with patch('mcpgateway.services.server_service.get_for_update', return_value=server):
            ...     asyncio.run(service.update_server(db, 'server_id', server_update, 'user_email'))
            'server_read'
        """
        try:
            server = get_for_update(
                db,
                DbServer,
                server_id,
                options=[
                    *SERVER_ASSOCIATION_SELECTINLOADS,
                    selectinload(DbServer.email_team),
                ],
            )
            if not server:
                raise ServerNotFoundError(f"Server not found: {server_id}")

            # Check ownership if user_email provided
            if user_email:
                # First-Party
                from mcpgateway.services.permission_service import PermissionService  # pylint: disable=import-outside-toplevel

                permission_service = PermissionService(db)
                if not await permission_service.check_resource_ownership(user_email, server):
                    raise PermissionError("Only the owner can update this server")

            # Check for name conflict if name is being changed and visibility is public
            if server_update.name and server_update.name != server.name:
                visibility = server_update.visibility or server.visibility
                team_id = server_update.team_id or server.team_id
                if visibility.lower() == "public":
                    # Check for existing public server with the same name
                    existing_server = get_for_update(
                        db, DbServer, where=and_(DbServer.name == server_update.name, DbServer.visibility == "public", DbServer.id != server.id)
                    )  # pylint: disable=comparison-with-callable
                    if existing_server:
                        raise ServerNameConflictError(server_update.name, enabled=existing_server.enabled, server_id=existing_server.id, visibility=existing_server.visibility)
                elif visibility.lower() == "team" and team_id:
                    # Check for existing team server with the same name
                    existing_server = get_for_update(
                        db,
                        DbServer,
                        where=and_(
                            DbServer.name == server_update.name, DbServer.visibility == "team", DbServer.team_id == team_id, DbServer.id != server.id
                        ),  # pylint: disable=comparison-with-callable
                    )
                    if existing_server:
                        raise ServerNameConflictError(server_update.name, enabled=existing_server.enabled, server_id=existing_server.id, visibility=existing_server.visibility)

            # Update simple fields
            if server_update.id is not None and server_update.id != server.id:
                # Check if the new UUID is already in use
                existing = db.get(DbServer, server_update.id)
                if existing:
                    raise ServerError(f"Server with ID {server_update.id} already exists")
                server.id = server_update.id
            if server_update.name is not None:
                server.name = server_update.name
            if server_update.description is not None:
                server.description = server_update.description
            if server_update.icon is not None:
                server.icon = server_update.icon

            if server_update.visibility is not None:
                new_visibility = server_update.visibility

                # Validate visibility transitions
                if new_visibility == "team":
                    target_team_id = server_update.team_id if server_update.team_id is not None else server.team_id
                    _validate_server_team_assignment(db, user_email, target_team_id)

                elif new_visibility == "public":
                    # Optional: Check if user has permission to make resources public
                    # This could be a platform-level permission
                    pass

                server.visibility = new_visibility

            if server_update.team_id is not None:
                if server_update.team_id != server.team_id:
                    _validate_server_team_assignment(db, user_email, server_update.team_id)
                server.team_id = server_update.team_id

            _update_server_associations(db, server, server_update)

            # Update tags if provided
            if server_update.tags is not None:
                server.tags = server_update.tags

            # Update OAuth 2.0 configuration if provided
            # Track if OAuth is being explicitly disabled to prevent config re-assignment
            oauth_being_disabled = server_update.oauth_enabled is not None and not server_update.oauth_enabled

            if server_update.oauth_enabled is not None:
                server.oauth_enabled = server_update.oauth_enabled
                # If OAuth is being disabled, clear the config
                if oauth_being_disabled:
                    server.oauth_config = None

            # Only update oauth_config if OAuth is not being explicitly disabled
            # This prevents the case where oauth_enabled=False and oauth_config are both provided
            if not oauth_being_disabled:
                if hasattr(server_update, "model_fields_set") and "oauth_config" in server_update.model_fields_set:
                    server.oauth_config = await protect_oauth_config_for_storage(server_update.oauth_config, existing_oauth_config=server.oauth_config)
                elif server_update.oauth_config is not None:
                    server.oauth_config = await protect_oauth_config_for_storage(server_update.oauth_config, existing_oauth_config=server.oauth_config)

            # Update metadata fields
            server.updated_at = datetime.now(timezone.utc)
            if modified_by:
                server.modified_by = modified_by
            if modified_from_ip:
                server.modified_from_ip = modified_from_ip
            if modified_via:
                server.modified_via = modified_via
            if modified_user_agent:
                server.modified_user_agent = modified_user_agent
            if hasattr(server, "version") and server.version is not None:
                server.version = server.version + 1
            else:
                server.version = 1

            db.commit()
            db.refresh(server)
            # Force loading relationships
            _ = server.tools, server.resources, server.prompts

            # Invalidate cache after successful update
            cache = _get_registry_cache()
            await cache.invalidate_servers()
            # Also invalidate tags cache since server tags may have changed
            # First-Party
            from mcpgateway.cache.admin_stats_cache import admin_stats_cache  # pylint: disable=import-outside-toplevel

            await admin_stats_cache.invalidate_tags()

            await self._notify_server_updated(server)
            logger.info(f"Updated server: {server.name}")

            # Structured logging: Audit trail for server update
            changes = []
            if server_update.name:
                changes.append(f"name: {server_update.name}")
            if server_update.visibility:
                changes.append(f"visibility: {server_update.visibility}")
            if server_update.team_id:
                changes.append(f"team_id: {server_update.team_id}")

            self._audit_trail.log_action(
                user_id=user_email or "system",
                action="update_server",
                resource_type="server",
                resource_id=server.id,
                details={
                    "server_name": server.name,
                    "changes": ", ".join(changes) if changes else "metadata only",
                    "version": server.version,
                },
                metadata={
                    "modified_from_ip": modified_from_ip,
                    "modified_via": modified_via,
                    "modified_user_agent": modified_user_agent,
                },
            )

            # Structured logging: Log successful server update
            self._structured_logger.log(
                level="INFO",
                message="Server updated successfully",
                event_type="server_updated",
                component="server_service",
                server_id=server.id,
                server_name=server.name,
                modified_by=user_email,
                user_email=user_email,
            )

            # Build a dictionary with associated IDs
            # Team name is loaded via server.team property from email_team relationship
            server_data = {
                "id": server.id,
                "name": server.name,
                "description": server.description,
                "icon": server.icon,
                "team": server.team,
                "created_at": server.created_at,
                "updated_at": server.updated_at,
                "enabled": server.enabled,
                "associated_tools": [tool.id for tool in server.tools],
                "associated_resources": [res.id for res in server.resources],
                "associated_prompts": [prompt.id for prompt in server.prompts],
            }
            logger.debug(f"Server Data: {server_data}")
            return self.convert_server_to_read(server)
        except IntegrityError as ie:
            db.rollback()
            logger.error(f"IntegrityErrors in group: {ie}")

            # Structured logging: Log database integrity error
            self._structured_logger.log(
                level="ERROR",
                message="Server update failed due to database integrity error",
                event_type="server_update_failed",
                component="server_service",
                server_id=server_id,
                error_type="IntegrityError",
                error_message=str(ie),
                modified_by=user_email,
                user_email=user_email,
            )
            raise ie
        except ServerNameConflictError as snce:
            db.rollback()
            logger.error(f"Server name conflict: {snce}")

            # Structured logging: Log name conflict error
            self._structured_logger.log(
                level="WARNING",
                message="Server update failed due to name conflict",
                event_type="server_name_conflict",
                component="server_service",
                server_id=server_id,
                modified_by=user_email,
                user_email=user_email,
            )
            raise snce
        except Exception as e:
            db.rollback()

            # Structured logging: Log generic server update failure
            self._structured_logger.log(
                level="ERROR",
                message="Server update failed",
                event_type="server_update_failed",
                component="server_service",
                server_id=server_id,
                error_type=type(e).__name__,
                error_message=str(e),
                modified_by=user_email,
                user_email=user_email,
            )
            raise ServerError(f"Failed to update server: {str(e)}")

    async def set_server_state(self, db: Session, server_id: str, activate: bool, user_email: Optional[str] = None) -> ServerRead:
        """Set the activation status of a server.

        Args:
            db: Database session.
            server_id: The unique identifier of the server.
            activate: True to activate, False to deactivate.
            user_email: Optional[str] The email of the user to check if the user has permission to modify.

        Returns:
            The updated ServerRead object.

        Raises:
            ServerNotFoundError: If the server is not found.
            ServerLockConflictError: If the server row is locked by another transaction.
            ServerError: For other errors.
            PermissionError: If user doesn't own the agent.

        Examples:
            >>> from mcpgateway.services.server_service import ServerService
            >>> from unittest.mock import MagicMock, AsyncMock, patch
            >>> from mcpgateway.schemas import ServerRead
            >>> service = ServerService()
            >>> db = MagicMock()
            >>> server = MagicMock()
            >>> db.get.return_value = server
            >>> db.commit = MagicMock()
            >>> db.refresh = MagicMock()
            >>> service._notify_server_activated = AsyncMock()
            >>> service._notify_server_deactivated = AsyncMock()
            >>> service.convert_server_to_read = MagicMock(return_value='server_read')
            >>> service._structured_logger = MagicMock()  # Mock structured logger to prevent database writes
            >>> service._audit_trail = MagicMock()  # Mock audit trail to prevent database writes
            >>> ServerRead.model_validate = MagicMock(return_value='server_read')
            >>> import asyncio
            >>> asyncio.run(service.set_server_state(db, 'server_id', True))
            'server_read'
        """
        try:
            # Use nowait=True to fail fast if row is locked, preventing lock contention under high load
            try:
                server = get_for_update(
                    db,
                    DbServer,
                    server_id,
                    nowait=True,
                    options=[
                        *SERVER_ASSOCIATION_SELECTINLOADS,
                        selectinload(DbServer.email_team),
                    ],
                )
            except OperationalError as lock_err:
                # Row is locked by another transaction - fail fast with 409
                db.rollback()
                raise ServerLockConflictError(f"Server {server_id} is currently being modified by another request") from lock_err
            if not server:
                raise ServerNotFoundError(f"Server not found: {server_id}")

            if user_email:
                # First-Party
                from mcpgateway.services.permission_service import PermissionService  # pylint: disable=import-outside-toplevel

                permission_service = PermissionService(db)
                if not await permission_service.check_resource_ownership(user_email, server):
                    raise PermissionError("Only the owner can activate the Server" if activate else "Only the owner can deactivate the Server")

            if server.enabled != activate:
                server.enabled = activate
                server.updated_at = datetime.now(timezone.utc)
                db.commit()
                db.refresh(server)

                # Invalidate cache after status change
                cache = _get_registry_cache()
                await cache.invalidate_servers()

                if activate:
                    await self._notify_server_activated(server)
                else:
                    await self._notify_server_deactivated(server)
                logger.info(f"Server {server.name} {'activated' if activate else 'deactivated'}")

                # Structured logging: Audit trail for server state change
                self._audit_trail.log_action(
                    user_id=user_email or "system",
                    action="activate_server" if activate else "deactivate_server",
                    resource_type="server",
                    resource_id=server.id,
                    details={
                        "server_name": server.name,
                        "new_status": "active" if activate else "inactive",
                    },
                )

                # Structured logging: Log server status change
                self._structured_logger.log(
                    level="INFO",
                    message=f"Server {'activated' if activate else 'deactivated'}",
                    event_type="server_status_changed",
                    component="server_service",
                    server_id=server.id,
                    server_name=server.name,
                    new_status="active" if activate else "inactive",
                    changed_by=user_email,
                    user_email=user_email,
                )

            # Team name is loaded via server.team property from email_team relationship
            server_data = {
                "id": server.id,
                "name": server.name,
                "description": server.description,
                "icon": server.icon,
                "team": server.team,
                "created_at": server.created_at,
                "updated_at": server.updated_at,
                "enabled": server.enabled,
                "associated_tools": [tool.id for tool in server.tools],
                "associated_resources": [res.id for res in server.resources],
                "associated_prompts": [prompt.id for prompt in server.prompts],
            }
            logger.info(f"Server Data: {server_data}")
            return self.convert_server_to_read(server)
        except PermissionError as e:
            # Structured logging: Log permission error
            self._structured_logger.log(
                level="WARNING",
                message="Server state change failed due to insufficient permissions",
                event_type="server_state_change_permission_denied",
                component="server_service",
                server_id=server_id,
                user_email=user_email,
            )
            raise e
        except ServerLockConflictError:
            # Re-raise lock conflicts without wrapping - allows 409 response
            raise
        except ServerNotFoundError:
            # Re-raise not found without wrapping - allows 404 response
            raise
        except Exception as e:
            db.rollback()

            # Structured logging: Log generic server state change failure
            self._structured_logger.log(
                level="ERROR",
                message="Server state change failed",
                event_type="server_state_change_failed",
                component="server_service",
                server_id=server_id,
                error_type=type(e).__name__,
                error_message=str(e),
                user_email=user_email,
            )
            raise ServerError(f"Failed to set server state: {str(e)}")

    async def delete_server(self, db: Session, server_id: str, user_email: Optional[str] = None, purge_metrics: bool = False) -> None:
        """Permanently delete a server.

        Args:
            db: Database session.
            server_id: The unique identifier of the server.
            user_email: Email of user performing deletion (for ownership check).
            purge_metrics: If True, delete raw + rollup metrics for this server.

        Raises:
            ServerNotFoundError: If the server is not found.
            PermissionError: If user doesn't own the server.
            ServerError: For other deletion errors.

        Examples:
            >>> from mcpgateway.services.server_service import ServerService
            >>> from unittest.mock import MagicMock, AsyncMock, patch
            >>> service = ServerService()
            >>> db = MagicMock()
            >>> server = MagicMock()
            >>> db.get.return_value = server
            >>> db.delete = MagicMock()
            >>> db.commit = MagicMock()
            >>> service._notify_server_deleted = AsyncMock()
            >>> service._structured_logger = MagicMock()  # Mock structured logger to prevent database writes
            >>> service._audit_trail = MagicMock()  # Mock audit trail to prevent database writes
            >>> import asyncio
            >>> asyncio.run(service.delete_server(db, 'server_id', 'user@example.com'))
        """
        try:
            server = db.get(DbServer, server_id)
            if not server:
                raise ServerNotFoundError(f"Server not found: {server_id}")

            # Check ownership if user_email provided
            if user_email:
                # First-Party
                from mcpgateway.services.permission_service import PermissionService  # pylint: disable=import-outside-toplevel

                permission_service = PermissionService(db)
                if not await permission_service.check_resource_ownership(user_email, server):
                    raise PermissionError("Only the owner can delete this server")

            server_info = {"id": server.id, "name": server.name}
            if purge_metrics:
                with pause_rollup_during_purge(reason=f"purge_server:{server_id}"):
                    delete_metrics_in_batches(db, ServerMetric, ServerMetric.server_id, server_id)
                    delete_metrics_in_batches(db, ServerMetricsHourly, ServerMetricsHourly.server_id, server_id)
            db.delete(server)
            db.commit()

            # Invalidate cache after successful deletion
            cache = _get_registry_cache()
            await cache.invalidate_servers()
            # Also invalidate tags cache since server tags may have changed
            # First-Party
            from mcpgateway.cache.admin_stats_cache import admin_stats_cache  # pylint: disable=import-outside-toplevel

            await admin_stats_cache.invalidate_tags()
            # First-Party
            from mcpgateway.cache.metrics_cache import metrics_cache  # pylint: disable=import-outside-toplevel

            metrics_cache.invalidate_prefix("top_servers:")
            metrics_cache.invalidate("servers")

            await self._notify_server_deleted(server_info)
            logger.info(f"Deleted server: {server_info['name']}")

            # Structured logging: Audit trail for server deletion
            self._audit_trail.log_action(
                user_id=user_email or "system",
                action="delete_server",
                resource_type="server",
                resource_id=server_info["id"],
                details={
                    "server_name": server_info["name"],
                },
            )

            # Structured logging: Log successful server deletion
            self._structured_logger.log(
                level="INFO",
                message="Server deleted successfully",
                event_type="server_deleted",
                component="server_service",
                server_id=server_info["id"],
                server_name=server_info["name"],
                deleted_by=user_email,
                user_email=user_email,
                purge_metrics=purge_metrics,
            )
        except PermissionError as pe:
            db.rollback()

            # Structured logging: Log permission error
            self._structured_logger.log(
                level="WARNING",
                message="Server deletion failed due to insufficient permissions",
                event_type="server_deletion_permission_denied",
                component="server_service",
                server_id=server_id,
                user_email=user_email,
            )
            raise pe
        except Exception as e:
            db.rollback()

            # Structured logging: Log generic server deletion failure
            self._structured_logger.log(
                level="ERROR",
                message="Server deletion failed",
                event_type="server_deletion_failed",
                component="server_service",
                server_id=server_id,
                error_type=type(e).__name__,
                error_message=str(e),
                user_email=user_email,
            )
            raise ServerError(f"Failed to delete server: {str(e)}")

    async def _publish_event(self, event: Dict[str, Any]) -> None:
        """
        Publish an event to all subscribed queues.

        Args:
            event: Event to publish
        """
        for queue in self._event_subscribers:
            await queue.put(event)

    async def subscribe_events(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Subscribe to server events.

        Yields:
            Server event messages.
        """
        queue: asyncio.Queue = asyncio.Queue()
        self._event_subscribers.append(queue)
        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            self._event_subscribers.remove(queue)

    async def _notify_server_added(self, server: DbServer) -> None:
        """
        Notify subscribers that a new server has been added.

        Args:
            server: Server to add
        """
        associated_tools = [tool.id for tool in server.tools] if server.tools else []
        associated_resources = [res.id for res in server.resources] if server.resources else []
        associated_prompts = [prompt.id for prompt in server.prompts] if server.prompts else []
        event = {
            "type": "server_added",
            "data": {
                "id": server.id,
                "name": server.name,
                "description": server.description,
                "icon": server.icon,
                "associated_tools": associated_tools,
                "associated_resources": associated_resources,
                "associated_prompts": associated_prompts,
                "enabled": server.enabled,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._publish_event(event)

    async def _notify_server_updated(self, server: DbServer) -> None:
        """
        Notify subscribers that a server has been updated.

        Args:
            server: Server to update
        """
        associated_tools = [tool.id for tool in server.tools] if server.tools else []
        associated_resources = [res.id for res in server.resources] if server.resources else []
        associated_prompts = [prompt.id for prompt in server.prompts] if server.prompts else []
        event = {
            "type": "server_updated",
            "data": {
                "id": server.id,
                "name": server.name,
                "description": server.description,
                "icon": server.icon,
                "associated_tools": associated_tools,
                "associated_resources": associated_resources,
                "associated_prompts": associated_prompts,
                "enabled": server.enabled,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._publish_event(event)

    async def _notify_server_activated(self, server: DbServer) -> None:
        """
        Notify subscribers that a server has been activated.

        Args:
            server: Server to activate
        """
        event = {
            "type": "server_activated",
            "data": {
                "id": server.id,
                "name": server.name,
                "enabled": True,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._publish_event(event)

    async def _notify_server_deactivated(self, server: DbServer) -> None:
        """
        Notify subscribers that a server has been deactivated.

        Args:
            server: Server to deactivate
        """
        event = {
            "type": "server_deactivated",
            "data": {
                "id": server.id,
                "name": server.name,
                "enabled": False,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._publish_event(event)

    async def _notify_server_deleted(self, server_info: Dict[str, Any]) -> None:
        """
        Notify subscribers that a server has been deleted.

        Args:
            server_info: Dictionary on server to be deleted
        """
        event = {
            "type": "server_deleted",
            "data": server_info,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._publish_event(event)

    # --- Metrics ---
    async def aggregate_metrics(self, db: Session) -> ServerMetrics:
        """
        Aggregate metrics for all server invocations across all servers.

        Combines recent raw metrics (within retention period) with historical
        hourly rollups for complete historical coverage. Uses in-memory caching
        (10s TTL) to reduce database load under high request rates.

        Args:
            db: Database session

        Returns:
            ServerMetrics: Aggregated metrics from raw + hourly rollup tables.

        Examples:
            >>> from mcpgateway.services.server_service import ServerService
            >>> service = ServerService()
            >>> # Method exists and is callable
            >>> callable(service.aggregate_metrics)
            True
        """
        # Check cache first (if enabled)
        # First-Party
        from mcpgateway.cache.metrics_cache import is_cache_enabled, metrics_cache  # pylint: disable=import-outside-toplevel

        if is_cache_enabled():
            cached = metrics_cache.get("servers")
            if cached is not None:
                return ServerMetrics(**cached)

        # Use combined raw + rollup query for full historical coverage
        # First-Party
        from mcpgateway.services.metrics_query_service import aggregate_metrics_combined  # pylint: disable=import-outside-toplevel

        result = aggregate_metrics_combined(db, "server")

        metrics = ServerMetrics(
            total_executions=result.total_executions,
            successful_executions=result.successful_executions,
            failed_executions=result.failed_executions,
            failure_rate=result.failure_rate,
            min_response_time=result.min_response_time,
            max_response_time=result.max_response_time,
            avg_response_time=result.avg_response_time,
            last_execution_time=result.last_execution_time,
        )

        # Cache the result as dict for serialization compatibility (if enabled)
        if is_cache_enabled():
            metrics_cache.set("servers", metrics.model_dump())

        return metrics

    async def reset_metrics(self, db: Session) -> None:
        """
        Reset all server metrics by deleting raw and hourly rollup records.

        Args:
            db: Database session

        Examples:
            >>> from mcpgateway.services.server_service import ServerService
            >>> from unittest.mock import MagicMock
            >>> service = ServerService()
            >>> db = MagicMock()
            >>> db.execute = MagicMock()
            >>> db.commit = MagicMock()
            >>> import asyncio
            >>> asyncio.run(service.reset_metrics(db))
        """
        db.execute(delete(ServerMetric))
        db.execute(delete(ServerMetricsHourly))
        db.commit()

        # Invalidate metrics cache
        # First-Party
        from mcpgateway.cache.metrics_cache import metrics_cache  # pylint: disable=import-outside-toplevel

        metrics_cache.invalidate("servers")
        metrics_cache.invalidate_prefix("top_servers:")

    def get_oauth_protected_resource_metadata(self, db: Session, server_id: str, resource_base_url: str) -> Dict[str, Any]:
        """
        Get RFC 9728 OAuth 2.0 Protected Resource Metadata for a server.

        This method retrieves the OAuth configuration for a server and formats it
        according to RFC 9728 Protected Resource Metadata specification, enabling
        MCP clients to discover OAuth authorization servers for browser-based SSO.

        Args:
            db: Database session.
            server_id: The ID of the server.
            resource_base_url: The base URL for the resource (e.g., "https://gateway.example.com/servers/abc123/mcp").

        Returns:
            Dict containing RFC 9728 Protected Resource Metadata:
            - resource: The protected resource identifier (URL with /mcp suffix)
            - authorization_servers: JSON array of authorization server issuer URIs (RFC 9728 Section 2)
            - bearer_methods_supported: Supported bearer token methods (always ["header"])
            - scopes_supported: Optional list of supported scopes

        Raises:
            ServerNotFoundError: If server doesn't exist, is disabled, or is non-public.
            ServerError: If OAuth is not enabled or not properly configured.

        Examples:
            >>> from mcpgateway.services.server_service import ServerService
            >>> service = ServerService()
            >>> # Method exists and is callable
            >>> callable(service.get_oauth_protected_resource_metadata)
            True
        """
        server = db.get(DbServer, server_id)

        # Return not found for non-existent, disabled, or non-public servers
        # (avoids leaking information about private/team servers)
        if not server:
            raise ServerNotFoundError(f"Server not found: {server_id}")

        if not server.enabled:
            raise ServerNotFoundError(f"Server not found: {server_id}")

        if getattr(server, "visibility", "public") != "public":
            raise ServerNotFoundError(f"Server not found: {server_id}")

        # Check OAuth configuration
        if not getattr(server, "oauth_enabled", False):
            raise ServerError(f"OAuth not enabled for server: {server_id}")

        oauth_config = getattr(server, "oauth_config", None)
        if not oauth_config:
            raise ServerError(f"OAuth not configured for server: {server_id}")

        # Extract authorization server(s) - support both list and single value in config
        authorization_servers = oauth_config.get("authorization_servers", [])
        if not authorization_servers:
            auth_server = oauth_config.get("authorization_server")
            if auth_server:
                authorization_servers = [auth_server] if isinstance(auth_server, str) else auth_server

        if not authorization_servers:
            raise ServerError(f"OAuth authorization_server not configured for server: {server_id}")

        # Build RFC 9728 Protected Resource Metadata response
        response_data: Dict[str, Any] = {
            "resource": resource_base_url,
            "authorization_servers": authorization_servers,
            "bearer_methods_supported": ["header"],
        }

        # Add optional scopes if configured (never include secrets from oauth_config)
        scopes = oauth_config.get("scopes_supported") or oauth_config.get("scopes")
        if scopes:
            response_data["scopes_supported"] = scopes

        logger.debug(f"Returning OAuth protected resource metadata for server {server_id}")
        return response_data


# Lazy singleton - created on first access, not at module import time.
# This avoids instantiation when only exception classes are imported.
_server_service_instance = None  # pylint: disable=invalid-name


def __getattr__(name: str):
    """Module-level __getattr__ for lazy singleton creation.

    Args:
        name: The attribute name being accessed.

    Returns:
        The server_service singleton instance if name is "server_service".

    Raises:
        AttributeError: If the attribute name is not "server_service".
    """
    global _server_service_instance  # pylint: disable=global-statement
    if name == "server_service":
        if _server_service_instance is None:
            _server_service_instance = ServerService()
        return _server_service_instance
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
