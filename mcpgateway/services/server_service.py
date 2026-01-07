# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/server_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

MCP Gateway Server Service

This module implements server management for the MCP Servers Catalog.
It handles server registration, listing, retrieval, updates, activation toggling, and deletion.
It also publishes event notifications for server changes.
"""

# Standard
import asyncio
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional, Union

# Third-Party
import httpx
from sqlalchemy import and_, delete, desc, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload, Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import A2AAgent as DbA2AAgent
from mcpgateway.db import EmailTeam as DbEmailTeam
from mcpgateway.db import EmailTeamMember as DbEmailTeamMember
from mcpgateway.db import Prompt as DbPrompt
from mcpgateway.db import Resource as DbResource
from mcpgateway.db import Server as DbServer
from mcpgateway.db import ServerMetric, ServerMetricsHourly
from mcpgateway.db import Tool as DbTool
from mcpgateway.schemas import ServerCreate, ServerMetrics, ServerRead, ServerUpdate, TopPerformer
from mcpgateway.services.audit_trail_service import get_audit_trail_service
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.metrics_cleanup_service import delete_metrics_in_batches, pause_rollup_during_purge
from mcpgateway.services.performance_tracker import get_performance_tracker
from mcpgateway.services.structured_logger import get_structured_logger
from mcpgateway.services.team_management_service import TeamManagementService
from mcpgateway.utils.metrics_common import build_top_performers
from mcpgateway.utils.pagination import unified_paginate
from mcpgateway.utils.sqlalchemy_modifier import json_contains_expr

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


class ServerError(Exception):
    """Base class for server-related errors."""


class ServerNotFoundError(ServerError):
    """Raised when a requested server is not found."""


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


class ServerService:
    """Service for managing MCP Servers in the catalog.

    Provides methods to create, list, retrieve, update, toggle status, and delete server records.
    Also supports event notifications for changes in server data.
    """

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
            ...     tools=[], resources=[], prompts=[], a2a_agents=[]
            ... )
            >>> result = svc.convert_server_to_read(server, include_metrics=True)
            >>> result.metrics.total_executions
            2
            >>> result.metrics.successful_executions
            1
        """
        server_dict = server.__dict__.copy()
        server_dict.pop("_sa_instance_state", None)

        # Compute aggregated metrics only if requested (avoids N+1 queries in list operations)
        if include_metrics:
            total = 0
            successful = 0
            failed = 0
            min_rt = None
            max_rt = None
            sum_rt = 0.0
            last_time = None

            if hasattr(server, "metrics") and server.metrics:
                for m in server.metrics:
                    total += 1
                    if m.is_success:
                        successful += 1
                    else:
                        failed += 1

                    # Track min/max response times
                    if min_rt is None or m.response_time < min_rt:
                        min_rt = m.response_time
                    if max_rt is None or m.response_time > max_rt:
                        max_rt = m.response_time

                    sum_rt += m.response_time

                    # Track last execution time
                    if last_time is None or m.timestamp > last_time:
                        last_time = m.timestamp

            failure_rate = (failed / total) if total > 0 else 0.0
            avg_rt = (sum_rt / total) if total > 0 else None

            server_dict["metrics"] = {
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
            server_dict["metrics"] = None
        # Also update associated IDs (if not already done)
        server_dict["associated_tools"] = [tool.name for tool in server.tools] if server.tools else []
        server_dict["associated_resources"] = [res.id for res in server.resources] if server.resources else []
        server_dict["associated_prompts"] = [prompt.id for prompt in server.prompts] if server.prompts else []
        server_dict["associated_a2a_agents"] = [agent.id for agent in server.a2a_agents] if server.a2a_agents else []
        server_dict["tags"] = server.tags or []

        # Include metadata fields for proper API response
        server_dict["created_by"] = getattr(server, "created_by", None)
        server_dict["modified_by"] = getattr(server, "modified_by", None)
        server_dict["created_at"] = getattr(server, "created_at", None)
        server_dict["updated_at"] = getattr(server, "updated_at", None)
        server_dict["version"] = getattr(server, "version", None)
        server_dict["team"] = getattr(server, "team", None)

        return ServerRead.model_validate(server_dict)

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
        team = db.query(DbEmailTeam).filter(DbEmailTeam.id == team_id, DbEmailTeam.is_active.is_(True)).first()
        db.commit()  # Release transaction to avoid idle-in-transaction
        return team.name if team else None

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
                visibility=getattr(server_in, "visibility", None) or visibility,
                # Metadata fields
                created_by=created_by,
                created_from_ip=created_from_ip,
                created_via=created_via,
                created_user_agent=created_user_agent,
                version=1,
            )
            # Check for existing server with the same name
            if visibility.lower() == "public":
                # Check for existing public server with the same name
                existing_server = db.execute(select(DbServer).where(DbServer.name == server_in.name, DbServer.visibility == "public")).scalar_one_or_none()
                if existing_server:
                    raise ServerNameConflictError(server_in.name, enabled=existing_server.enabled, server_id=existing_server.id, visibility=existing_server.visibility)
            elif visibility.lower() == "team" and team_id:
                # Check for existing team server with the same name
                existing_server = db.execute(select(DbServer).where(DbServer.name == server_in.name, DbServer.visibility == "team", DbServer.team_id == team_id)).scalar_one_or_none()
                if existing_server:
                    raise ServerNameConflictError(server_in.name, enabled=existing_server.enabled, server_id=existing_server.id, visibility=existing_server.visibility)
            # Set custom UUID if provided
            if server_in.id:
                logger.info(f"Setting custom UUID for server: {server_in.id}")
                db_server.id = server_in.id
            logger.info(f"Adding server to DB session: {db_server.name}")
            db.add(db_server)

            # Associate tools, verifying each exists using bulk query when multiple items
            if server_in.associated_tools:
                tool_ids = [tool_id.strip() for tool_id in server_in.associated_tools if tool_id.strip()]
                if len(tool_ids) > 1:
                    # Use bulk query for multiple items
                    tools = db.execute(select(DbTool).where(DbTool.id.in_(tool_ids))).scalars().all()
                    found_tool_ids = {tool.id for tool in tools}
                    missing_tool_ids = set(tool_ids) - found_tool_ids
                    if missing_tool_ids:
                        raise ServerError(f"Tools with ids {missing_tool_ids} do not exist.")
                    db_server.tools.extend(tools)
                elif tool_ids:
                    # Use single query for single item (maintains test compatibility)
                    tool_obj = db.get(DbTool, tool_ids[0])
                    if not tool_obj:
                        raise ServerError(f"Tool with id {tool_ids[0]} does not exist.")
                    db_server.tools.append(tool_obj)

            # Associate resources, verifying each exists using bulk query when multiple items
            if server_in.associated_resources:
                resource_ids = [resource_id.strip() for resource_id in server_in.associated_resources if resource_id.strip()]
                if len(resource_ids) > 1:
                    # Use bulk query for multiple items
                    resources = db.execute(select(DbResource).where(DbResource.id.in_(resource_ids))).scalars().all()
                    found_resource_ids = {resource.id for resource in resources}
                    missing_resource_ids = set(resource_ids) - found_resource_ids
                    if missing_resource_ids:
                        raise ServerError(f"Resources with ids {missing_resource_ids} do not exist.")
                    db_server.resources.extend(resources)
                elif resource_ids:
                    # Use single query for single item (maintains test compatibility)
                    resource_obj = db.get(DbResource, resource_ids[0])
                    if not resource_obj:
                        raise ServerError(f"Resource with id {resource_ids[0]} does not exist.")
                    db_server.resources.append(resource_obj)

            # Associate prompts, verifying each exists using bulk query when multiple items
            if server_in.associated_prompts:
                prompt_ids = [prompt_id.strip() for prompt_id in server_in.associated_prompts if prompt_id.strip()]
                if len(prompt_ids) > 1:
                    # Use bulk query for multiple items
                    prompts = db.execute(select(DbPrompt).where(DbPrompt.id.in_(prompt_ids))).scalars().all()
                    found_prompt_ids = {prompt.id for prompt in prompts}
                    missing_prompt_ids = set(prompt_ids) - found_prompt_ids
                    if missing_prompt_ids:
                        raise ServerError(f"Prompts with ids {missing_prompt_ids} do not exist.")
                    db_server.prompts.extend(prompts)
                elif prompt_ids:
                    # Use single query for single item (maintains test compatibility)
                    prompt_obj = db.get(DbPrompt, prompt_ids[0])
                    if not prompt_obj:
                        raise ServerError(f"Prompt with id {prompt_ids[0]} does not exist.")
                    db_server.prompts.append(prompt_obj)

            # Associate A2A agents, verifying each exists using bulk query when multiple items
            if server_in.associated_a2a_agents:
                agent_ids = [agent_id.strip() for agent_id in server_in.associated_a2a_agents if agent_id.strip()]
                if len(agent_ids) > 1:
                    # Use bulk query for multiple items
                    agents = db.execute(select(DbA2AAgent).where(DbA2AAgent.id.in_(agent_ids))).scalars().all()
                    found_agent_ids = {agent.id for agent in agents}
                    missing_agent_ids = set(agent_ids) - found_agent_ids
                    if missing_agent_ids:
                        raise ServerError(f"A2A Agents with ids {missing_agent_ids} do not exist.")
                    db_server.a2a_agents.extend(agents)

                    # Note: Auto-tool creation for A2A agents should be handled
                    # by a separate service or background task to avoid circular imports
                    for agent in agents:
                        logger.info(f"A2A agent {agent.name} associated with server {db_server.name}")
                elif agent_ids:
                    # Use single query for single item (maintains test compatibility)
                    agent_obj = db.get(DbA2AAgent, agent_ids[0])
                    if not agent_obj:
                        raise ServerError(f"A2A Agent with id {agent_ids[0]} does not exist.")
                    db_server.a2a_agents.append(agent_obj)
                    logger.info(f"A2A agent {agent_obj.name} associated with server {db_server.name}")

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

            db_server.team = self._get_team_name(db, db_server.team_id)
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
        tags: Optional[List[str]] = None,
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        per_page: Optional[int] = None,
        user_email: Optional[str] = None,
        team_id: Optional[str] = None,
        visibility: Optional[str] = None,
    ) -> Union[tuple[List[ServerRead], Optional[str]], Dict[str, Any]]:
        """List all registered servers with cursor or page-based pagination and optional team filtering.

        Args:
            db: Database session.
            include_inactive: Whether to include inactive servers.
            tags: Filter servers by tags. If provided, only servers with at least one matching tag will be returned.
            cursor: Cursor for pagination (encoded last created_at and id).
            limit: Maximum number of servers to return. None for default, 0 for unlimited.
            page: Page number for page-based pagination (1-indexed). Mutually exclusive with cursor.
            per_page: Items per page for page-based pagination. Defaults to pagination_default_page_size.
            user_email: Email of user for team-based access control. None for no access control.
            team_id: Optional team ID to filter by specific team (requires user_email).
            visibility: Optional visibility filter (private, team, public) (requires user_email).

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
        # Check cache for first page only - skip when user_email provided or page-based pagination
        cache = _get_registry_cache()
        if cursor is None and user_email is None and page is None:
            filters_hash = cache.hash_filters(include_inactive=include_inactive, tags=sorted(tags) if tags else None)
            cached = await cache.get("servers", filters_hash)
            if cached is not None:
                # Reconstruct ServerRead objects from cached dicts
                cached_servers = [ServerRead.model_validate(s) for s in cached["servers"]]
                return (cached_servers, cached.get("next_cursor"))

        # Build base query with ordering and eager load relationships to avoid N+1
        query = (
            select(DbServer)
            .options(
                selectinload(DbServer.tools),
                selectinload(DbServer.resources),
                selectinload(DbServer.prompts),
                selectinload(DbServer.a2a_agents),
            )
            .order_by(desc(DbServer.created_at), desc(DbServer.id))
        )

        # Apply active/inactive filter
        if not include_inactive:
            query = query.where(DbServer.enabled)

        # Apply team-based access control if user_email is provided
        if user_email:
            team_service = TeamManagementService(db)
            user_teams = await team_service.get_user_teams(user_email)
            team_ids = [team.id for team in user_teams]

            if team_id:
                # User requesting specific team - verify access
                if team_id not in team_ids:
                    return ([], None)
                access_conditions = [
                    and_(DbServer.team_id == team_id, DbServer.visibility.in_(["team", "public"])),
                    and_(DbServer.team_id == team_id, DbServer.owner_email == user_email),
                ]
                query = query.where(or_(*access_conditions))
            else:
                # General access: user's servers + public servers + team servers
                access_conditions = [
                    DbServer.owner_email == user_email,
                    DbServer.visibility == "public",
                ]
                if team_ids:
                    access_conditions.append(and_(DbServer.team_id.in_(team_ids), DbServer.visibility.in_(["team", "public"])))
                query = query.where(or_(*access_conditions))

            if visibility:
                query = query.where(DbServer.visibility == visibility)

        # Add tag filtering if tags are provided
        if tags:
            query = query.where(json_contains_expr(db, DbServer.tags, tags, match_any=True))

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

        # Fetch team names for the servers (common for both pagination types)
        team_ids_set = {s.team_id for s in servers_db if s.team_id}
        team_map = {}
        if team_ids_set:
            teams = db.execute(select(DbEmailTeam.id, DbEmailTeam.name).where(DbEmailTeam.id.in_(team_ids_set), DbEmailTeam.is_active.is_(True))).all()
            team_map = {team.id: team.name for team in teams}

        db.commit()  # Release transaction to avoid idle-in-transaction

        # Convert to ServerRead (common for both pagination types)
        result = []
        for s in servers_db:
            s.team = team_map.get(s.team_id) if s.team_id else None
            result.append(self.convert_server_to_read(s, include_metrics=False))

        # Return appropriate format based on pagination type
        if page is not None:
            # Page-based format
            return {
                "data": result,
                "pagination": pag_result["pagination"],
                "links": pag_result["links"],
            }

        # Cursor-based format

        # Cache first page results - only for non-user-specific queries
        if cursor is None and user_email is None:
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
        query = select(DbServer).options(
            selectinload(DbServer.tools),
            selectinload(DbServer.resources),
            selectinload(DbServer.prompts),
            selectinload(DbServer.a2a_agents),
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

        # Fetch all team names
        server_team_ids = [s.team_id for s in servers if s.team_id]
        team_map = {}
        if server_team_ids:
            teams = db.execute(select(DbEmailTeam.id, DbEmailTeam.name).where(DbEmailTeam.id.in_(server_team_ids), DbEmailTeam.is_active.is_(True))).all()
            team_map = {team.id: team.name for team in teams}

        db.commit()  # Release transaction to avoid idle-in-transaction

        # Skip metrics to avoid N+1 queries in list operations
        result = []
        for s in servers:
            s.team = team_map.get(s.team_id) if s.team_id else None
            result.append(self.convert_server_to_read(s, include_metrics=False))
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
        server = db.get(DbServer, server_id)
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
        server.team = self._get_team_name(db, server.team_id) if server else None
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
            db=db,
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
            >>> import asyncio
            >>> asyncio.run(service.update_server(db, 'server_id', server_update, 'user_email'))
            'server_read'
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
                    raise PermissionError("Only the owner can update this server")

            # Check for name conflict if name is being changed and visibility is public
            if server_update.name and server_update.name != server.name:
                visibility = server_update.visibility or server.visibility
                team_id = server_update.team_id or server.team_id
                if visibility.lower() == "public":
                    # Check for existing public server with the same name
                    existing_server = db.execute(select(DbServer).where(DbServer.name == server_update.name, DbServer.visibility == "public")).scalar_one_or_none()
                    if existing_server:
                        raise ServerNameConflictError(server_update.name, enabled=existing_server.enabled, server_id=existing_server.id, visibility=existing_server.visibility)
                elif visibility.lower() == "team" and team_id:
                    # Check for existing team server with the same name
                    existing_server = db.execute(select(DbServer).where(DbServer.name == server_update.name, DbServer.visibility == "team", DbServer.team_id == team_id)).scalar_one_or_none()
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
                    if not server.team_id and not server_update.team_id:
                        raise ValueError("Cannot set visibility to 'team' without a team_id")

                    # Verify team exists and user is a member
                    if server.team_id:
                        team_id = server.team_id
                    else:
                        team_id = server_update.team_id

                    team = db.query(DbEmailTeam).filter(DbEmailTeam.id == team_id).first()
                    if not team:
                        raise ValueError(f"Team {team_id} not found")

                    # Verify user is a member of the team
                    membership = (
                        db.query(DbEmailTeamMember)
                        .filter(DbEmailTeamMember.team_id == team_id, DbEmailTeamMember.user_email == user_email, DbEmailTeamMember.is_active, DbEmailTeamMember.role == "owner")
                        .first()
                    )
                    if not membership:
                        raise ValueError("User membership in team not sufficient for this update.")

                elif new_visibility == "public":
                    # Optional: Check if user has permission to make resources public
                    # This could be a platform-level permission
                    pass

                server.visibility = new_visibility

            if server_update.team_id is not None:
                server.team_id = server_update.team_id

            if server_update.owner_email is not None:
                server.owner_email = server_update.owner_email

            # Update associated tools if provided using bulk query
            if server_update.associated_tools is not None:
                server.tools = []
                if server_update.associated_tools:
                    tool_ids = [tool_id for tool_id in server_update.associated_tools if tool_id]
                    if tool_ids:
                        tools = db.execute(select(DbTool).where(DbTool.id.in_(tool_ids))).scalars().all()
                        server.tools = list(tools)

            # Update associated resources if provided using bulk query
            if server_update.associated_resources is not None:
                server.resources = []
                if server_update.associated_resources:
                    resource_ids = [resource_id for resource_id in server_update.associated_resources if resource_id]
                    if resource_ids:
                        resources = db.execute(select(DbResource).where(DbResource.id.in_(resource_ids))).scalars().all()
                        server.resources = list(resources)

            # Update associated prompts if provided using bulk query
            if server_update.associated_prompts is not None:
                server.prompts = []
                if server_update.associated_prompts:
                    prompt_ids = [prompt_id for prompt_id in server_update.associated_prompts if prompt_id]
                    if prompt_ids:
                        prompts = db.execute(select(DbPrompt).where(DbPrompt.id.in_(prompt_ids))).scalars().all()
                        server.prompts = list(prompts)

            # Update tags if provided
            if server_update.tags is not None:
                server.tags = server_update.tags

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
            server_data = {
                "id": server.id,
                "name": server.name,
                "description": server.description,
                "icon": server.icon,
                "team": self._get_team_name(db, server.team_id),
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

    async def toggle_server_status(self, db: Session, server_id: str, activate: bool, user_email: Optional[str] = None) -> ServerRead:
        """Toggle the activation status of a server.

        Args:
            db: Database session.
            server_id: The unique identifier of the server.
            activate: True to activate, False to deactivate.
            user_email: Optional[str] The email of the user to check if the user has permission to modify.

        Returns:
            The updated ServerRead object.

        Raises:
            ServerNotFoundError: If the server is not found.
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
            >>> asyncio.run(service.toggle_server_status(db, 'server_id', True))
            'server_read'
        """
        try:
            server = db.get(DbServer, server_id)
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

                # Structured logging: Audit trail for server status toggle
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

            server_data = {
                "id": server.id,
                "name": server.name,
                "description": server.description,
                "icon": server.icon,
                "team": self._get_team_name(db, server.team_id),
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
                message="Server status toggle failed due to insufficient permissions",
                event_type="server_status_toggle_permission_denied",
                component="server_service",
                server_id=server_id,
                user_email=user_email,
            )
            raise e
        except Exception as e:
            db.rollback()

            # Structured logging: Log generic server status toggle failure
            self._structured_logger.log(
                level="ERROR",
                message="Server status toggle failed",
                event_type="server_status_toggle_failed",
                component="server_service",
                server_id=server_id,
                error_type=type(e).__name__,
                error_message=str(e),
                user_email=user_email,
            )
            raise ServerError(f"Failed to toggle server status: {str(e)}")

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
