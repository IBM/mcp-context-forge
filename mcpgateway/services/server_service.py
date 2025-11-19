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
from typing import Any, AsyncGenerator, Dict, List, Optional

# Third-Party
import httpx
from sqlalchemy import and_, case, delete, desc, Float, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import A2AAgent as DbA2AAgent
from mcpgateway.db import EmailTeam as DbEmailTeam
from mcpgateway.db import EmailTeamMember as DbEmailTeamMember
from mcpgateway.db import Prompt as DbPrompt
from mcpgateway.db import Resource as DbResource
from mcpgateway.db import Server as DbServer
from mcpgateway.db import ServerMetric
from mcpgateway.db import Tool as DbTool
from mcpgateway.schemas import ServerCreate, ServerMetrics, ServerRead, ServerUpdate, TopPerformer
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.team_management_service import TeamManagementService
from mcpgateway.utils.metrics_common import build_top_performers
from mcpgateway.utils.sqlalchemy_modifier import json_contains_expr

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class ServerError(Exception):
    """Base class for server-related errors."""


class ServerNotFoundError(ServerError):
    """Raised when a requested server is not found."""


class ServerNameConflictError(ServerError):
    """Raised when a server name conflicts with an existing one."""

    def __init__(self, name: str, is_active: bool = True, server_id: Optional[str] = None, visibility: str = "public") -> None:
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
            is_active: Whether the conflicting server is currently active. Defaults to True.
            server_id: The ID of the conflicting server, if known. Only included in message for inactive servers.
            visibility: The visibility of the conflicting server (e.g., "public", "private", "team").

        Examples:
            >>> error = ServerNameConflictError("My Server")
            >>> str(error)
            'Public Server already exists with name: My Server'
            >>> error = ServerNameConflictError("My Server", is_active=False, server_id=123)
            >>> str(error)
            'Public Server already exists with name: My Server (currently inactive, ID: 123)'
            >>> error.is_active
            False
            >>> error.server_id
            123
            >>> error = ServerNameConflictError("My Server", is_active=False, visibility="team")
            >>> str(error)
            'Team Server already exists with name: My Server (currently inactive, ID: None)'
            >>> error.is_active
            False
            >>> error.server_id is None
            True
        """
        self.name = name
        self.is_active = is_active
        self.server_id = server_id
        message = f"{visibility.capitalize()} Server already exists with name: {name}"
        if not is_active:
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
        self._http_client = httpx.AsyncClient(timeout=settings.federation_timeout, verify=not settings.skip_ssl_verify)

    async def initialize(self) -> None:
        """Initialize the server service."""
        logger.info("Initializing server service")

    async def shutdown(self) -> None:
        """Shutdown the server service."""
        await self._http_client.aclose()
        logger.info("Server service shutdown complete")

    # get_top_server
    async def get_top_servers(self, db: Session, limit: Optional[int] = 5) -> List[TopPerformer]:
        """Retrieve the top-performing servers based on execution count.

        Queries the database to get servers with their metrics, ordered by the number of executions
        in descending order. Returns a list of TopPerformer objects containing server details and
        performance metrics.

        Args:
            db (Session): Database session for querying server metrics.
            limit (Optional[int]): Maximum number of servers to return. Defaults to 5. If None, returns all servers.

        Returns:
            List[TopPerformer]: A list of TopPerformer objects, each containing:
                - id: Server ID.
                - name: Server name.
                - execution_count: Total number of executions.
                - avg_response_time: Average response time in seconds, or None if no metrics.
                - success_rate: Success rate percentage, or None if no metrics.
                - last_execution: Timestamp of the last execution, or None if no metrics.
        """
        query = (
            db.query(
                DbServer.id,
                DbServer.name,
                func.count(ServerMetric.id).label("execution_count"),  # pylint: disable=not-callable
                func.avg(ServerMetric.response_time).label("avg_response_time"),  # pylint: disable=not-callable
                case(
                    (
                        func.count(ServerMetric.id) > 0,  # pylint: disable=not-callable
                        func.sum(case((ServerMetric.is_success.is_(True), 1), else_=0)).cast(Float) / func.count(ServerMetric.id) * 100,  # pylint: disable=not-callable
                    ),
                    else_=None,
                ).label("success_rate"),
                func.max(ServerMetric.timestamp).label("last_execution"),  # pylint: disable=not-callable
            )
            .outerjoin(ServerMetric)
            .group_by(DbServer.id, DbServer.name)
            .order_by(desc("execution_count"))
        )

        if limit is not None:
            query = query.limit(limit)

        results = query.all()

        return build_top_performers(results)

    def _convert_server_to_read(self, server: DbServer) -> ServerRead:
        """
        Converts a DbServer instance into a ServerRead model, including aggregated metrics.

        Args:
            server (DbServer): The ORM instance of the server.

        Returns:
            ServerRead: The Pydantic model representing the server, including aggregated metrics.

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
            ...     created_at=now, updated_at=now, is_active=True,
            ...     associated_tools=[], associated_resources=[], associated_prompts=[], associated_a2a_agents=[],
            ...     tags=[], metrics=[m1, m2],
            ...     tools=[], resources=[], prompts=[], a2a_agents=[]
            ... )
            >>> result = svc._convert_server_to_read(server)
            >>> result.metrics.total_executions
            2
            >>> result.metrics.successful_executions
            1
        """
        server_dict = server.__dict__.copy()
        server_dict.pop("_sa_instance_state", None)
        # Compute aggregated metrics from server.metrics; default to 0/None when no records exist.
        total = len(server.metrics) if hasattr(server, "metrics") else 0
        successful = sum(1 for m in server.metrics if m.is_success) if total > 0 else 0
        failed = sum(1 for m in server.metrics if not m.is_success) if total > 0 else 0
        failure_rate = (failed / total) if total > 0 else 0.0
        min_rt = min((m.response_time for m in server.metrics), default=None) if total > 0 else None
        max_rt = max((m.response_time for m in server.metrics), default=None) if total > 0 else None
        avg_rt = (sum(m.response_time for m in server.metrics) / total) if total > 0 else None
        last_time = max((m.timestamp for m in server.metrics), default=None) if total > 0 else None

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
            >>> from unittest.mock import MagicMock, AsyncMock
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
            >>> service._convert_server_to_read = MagicMock(return_value='server_read')
            >>> ServerRead.model_validate = MagicMock(return_value='server_read')
            >>> import asyncio
            >>> asyncio.run(service.register_server(db, server_in))
            'server_read'
        """
        try:
            # # Create the new server record.
            db_server = DbServer(
                name=server_in.name,
                description=server_in.description,
                icon=server_in.icon,
                is_active=True,
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
                    raise ServerNameConflictError(server_in.name, is_active=existing_server.is_active, server_id=existing_server.id, visibility=existing_server.visibility)
            elif visibility.lower() == "team" and team_id:
                # Check for existing team server with the same name
                existing_server = db.execute(select(DbServer).where(DbServer.name == server_in.name, DbServer.visibility == "team", DbServer.team_id == team_id)).scalar_one_or_none()
                if existing_server:
                    raise ServerNameConflictError(server_in.name, is_active=existing_server.is_active, server_id=existing_server.id, visibility=existing_server.visibility)
            # Set custom UUID if provided
            if server_in.id:
                logger.info(f"Setting custom UUID for server: {server_in.id}")
                db_server.id = server_in.id
            db.add(db_server)

            # Associate tools, verifying each exists.
            if server_in.associated_tools:
                for tool_id in server_in.associated_tools:
                    if tool_id.strip() == "":
                        continue
                    tool_obj = db.get(DbTool, tool_id)
                    if not tool_obj:
                        raise ServerError(f"Tool with id {tool_id} does not exist.")
                    db_server.tools.append(tool_obj)

            # Associate resources, verifying each exists.
            if server_in.associated_resources:
                for resource_id in server_in.associated_resources:
                    if resource_id.strip() == "":
                        continue
                    resource_obj = db.get(DbResource, int(resource_id))
                    if not resource_obj:
                        raise ServerError(f"Resource with id {resource_id} does not exist.")
                    db_server.resources.append(resource_obj)

            # Associate prompts, verifying each exists.
            if server_in.associated_prompts:
                for prompt_id in server_in.associated_prompts:
                    if prompt_id.strip() == "":
                        continue
                    prompt_obj = db.get(DbPrompt, int(prompt_id))
                    if not prompt_obj:
                        raise ServerError(f"Prompt with id {prompt_id} does not exist.")
                    db_server.prompts.append(prompt_obj)

            # Associate A2A agents, verifying each exists and creating corresponding tools
            if server_in.associated_a2a_agents:
                for agent_id in server_in.associated_a2a_agents:
                    if agent_id.strip() == "":
                        continue
                    agent_obj = db.get(DbA2AAgent, agent_id)
                    if not agent_obj:
                        raise ServerError(f"A2A Agent with id {agent_id} does not exist.")
                    db_server.a2a_agents.append(agent_obj)

                    # Note: Auto-tool creation for A2A agents should be handled
                    # by a separate service or background task to avoid circular imports
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
                "is_active": db_server.is_active,
                "associated_tools": [str(tool.id) for tool in db_server.tools],
                "associated_resources": [str(resource.id) for resource in db_server.resources],
                "associated_prompts": [str(prompt.id) for prompt in db_server.prompts],
            }
            logger.debug(f"Server Data: {server_data}")
            await self._notify_server_added(db_server)
            logger.info(f"Registered server: {server_in.name}")
            db_server.team = self._get_team_name(db, db_server.team_id)
            return self._convert_server_to_read(db_server)
        except IntegrityError as ie:
            db.rollback()
            logger.error(f"IntegrityErrors in group: {ie}")
            raise ie
        except ServerNameConflictError as se:
            db.rollback()
            raise se
        except Exception as ex:
            db.rollback()
            raise ServerError(f"Failed to register server: {str(ex)}")

    async def list_servers(self, db: Session, include_inactive: bool = False, tags: Optional[List[str]] = None) -> List[ServerRead]:
        """List all registered servers.

        Args:
            db: Database session.
            include_inactive: Whether to include inactive servers.
            tags: Filter servers by tags. If provided, only servers with at least one matching tag will be returned.

        Returns:
            A list of ServerRead objects.

        Examples:
            >>> from mcpgateway.services.server_service import ServerService
            >>> from unittest.mock import MagicMock
            >>> service = ServerService()
            >>> db = MagicMock()
            >>> server_read = MagicMock()
            >>> service._convert_server_to_read = MagicMock(return_value=server_read)
            >>> db.execute.return_value.scalars.return_value.all.return_value = [MagicMock()]
            >>> import asyncio
            >>> result = asyncio.run(service.list_servers(db))
            >>> isinstance(result, list)
            True
        """
        query = select(DbServer)
        if not include_inactive:
            query = query.where(DbServer.is_active)

        # Add tag filtering if tags are provided
        if tags:
            query = query.where(json_contains_expr(db, DbServer.tags, tags, match_any=True))

        servers = db.execute(query).scalars().all()
        result = []
        for s in servers:
            s.team = self._get_team_name(db, s.team_id)

            result.append(self._convert_server_to_read(s))

        return result

    async def list_servers_for_user(
        self, db: Session, user_email: str, team_id: Optional[str] = None, visibility: Optional[str] = None, include_inactive: bool = False, skip: int = 0, limit: int = 100
    ) -> List[ServerRead]:
        """
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

        query = select(DbServer)

        # Apply active/inactive filter
        if not include_inactive:
            query = query.where(DbServer.is_active)

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
        result = []
        for s in servers:
            s.team = self._get_team_name(db, s.team_id)

            result.append(self._convert_server_to_read(s))
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
            >>> service._convert_server_to_read = MagicMock(return_value='server_read')
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
            "is_active": server.is_active,
            "associated_tools": [tool.name for tool in server.tools],
            "associated_resources": [res.id for res in server.resources],
            "associated_prompts": [prompt.id for prompt in server.prompts],
        }
        logger.debug(f"Server Data: {server_data}")
        server.team = self._get_team_name(db, server.team_id) if server else None
        return self._convert_server_to_read(server)

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
            >>> from unittest.mock import MagicMock, AsyncMock
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
            >>> service._convert_server_to_read = MagicMock(return_value='server_read')
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
                        raise ServerNameConflictError(server_update.name, is_active=existing_server.is_active, server_id=existing_server.id, visibility=existing_server.visibility)
                elif visibility.lower() == "team" and team_id:
                    # Check for existing team server with the same name
                    existing_server = db.execute(select(DbServer).where(DbServer.name == server_update.name, DbServer.visibility == "team", DbServer.team_id == team_id)).scalar_one_or_none()
                    if existing_server:
                        raise ServerNameConflictError(server_update.name, is_active=existing_server.is_active, server_id=existing_server.id, visibility=existing_server.visibility)

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

            # Update associated tools if provided
            if server_update.associated_tools is not None:
                server.tools = []
                for tool_id in server_update.associated_tools:
                    tool_obj = db.get(DbTool, tool_id)
                    if tool_obj:
                        server.tools.append(tool_obj)

            # Update associated resources if provided
            if server_update.associated_resources is not None:
                server.resources = []
                for resource_id in server_update.associated_resources:
                    resource_obj = db.get(DbResource, int(resource_id))
                    if resource_obj:
                        server.resources.append(resource_obj)

            # Update associated prompts if provided
            if server_update.associated_prompts is not None:
                server.prompts = []
                for prompt_id in server_update.associated_prompts:
                    prompt_obj = db.get(DbPrompt, int(prompt_id))
                    if prompt_obj:
                        server.prompts.append(prompt_obj)

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

            await self._notify_server_updated(server)
            logger.info(f"Updated server: {server.name}")

            # Build a dictionary with associated IDs
            server_data = {
                "id": server.id,
                "name": server.name,
                "description": server.description,
                "icon": server.icon,
                "team": self._get_team_name(db, server.team_id),
                "created_at": server.created_at,
                "updated_at": server.updated_at,
                "is_active": server.is_active,
                "associated_tools": [tool.id for tool in server.tools],
                "associated_resources": [res.id for res in server.resources],
                "associated_prompts": [prompt.id for prompt in server.prompts],
            }
            logger.debug(f"Server Data: {server_data}")
            return self._convert_server_to_read(server)
        except IntegrityError as ie:
            db.rollback()
            logger.error(f"IntegrityErrors in group: {ie}")
            raise ie
        except ServerNameConflictError as snce:
            db.rollback()
            logger.error(f"Server name conflict: {snce}")
            raise snce
        except Exception as e:
            db.rollback()
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
            >>> from unittest.mock import MagicMock, AsyncMock
            >>> from mcpgateway.schemas import ServerRead
            >>> service = ServerService()
            >>> db = MagicMock()
            >>> server = MagicMock()
            >>> db.get.return_value = server
            >>> db.commit = MagicMock()
            >>> db.refresh = MagicMock()
            >>> service._notify_server_activated = AsyncMock()
            >>> service._notify_server_deactivated = AsyncMock()
            >>> service._convert_server_to_read = MagicMock(return_value='server_read')
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

            if server.is_active != activate:
                server.is_active = activate
                server.updated_at = datetime.now(timezone.utc)
                db.commit()
                db.refresh(server)
                if activate:
                    await self._notify_server_activated(server)
                else:
                    await self._notify_server_deactivated(server)
                logger.info(f"Server {server.name} {'activated' if activate else 'deactivated'}")

            server_data = {
                "id": server.id,
                "name": server.name,
                "description": server.description,
                "icon": server.icon,
                "team": self._get_team_name(db, server.team_id),
                "created_at": server.created_at,
                "updated_at": server.updated_at,
                "is_active": server.is_active,
                "associated_tools": [tool.id for tool in server.tools],
                "associated_resources": [res.id for res in server.resources],
                "associated_prompts": [prompt.id for prompt in server.prompts],
            }
            logger.debug(f"Server Data: {server_data}")
            return self._convert_server_to_read(server)
        except PermissionError as e:
            raise e
        except Exception as e:
            db.rollback()
            raise ServerError(f"Failed to toggle server status: {str(e)}")

    async def delete_server(self, db: Session, server_id: str, user_email: Optional[str] = None) -> None:
        """Permanently delete a server.

        Args:
            db: Database session.
            server_id: The unique identifier of the server.
            user_email: Email of user performing deletion (for ownership check).

        Raises:
            ServerNotFoundError: If the server is not found.
            PermissionError: If user doesn't own the server.
            ServerError: For other deletion errors.

        Examples:
            >>> from mcpgateway.services.server_service import ServerService
            >>> from unittest.mock import MagicMock, AsyncMock
            >>> service = ServerService()
            >>> db = MagicMock()
            >>> server = MagicMock()
            >>> db.get.return_value = server
            >>> db.delete = MagicMock()
            >>> db.commit = MagicMock()
            >>> service._notify_server_deleted = AsyncMock()
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
            db.delete(server)
            db.commit()

            await self._notify_server_deleted(server_info)
            logger.info(f"Deleted server: {server_info['name']}")
        except PermissionError:
            db.rollback()
            raise
        except Exception as e:
            db.rollback()
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
                "is_active": server.is_active,
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
                "is_active": server.is_active,
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
                "is_active": True,
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
                "is_active": False,
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

        Args:
            db: Database session

        Returns:
            ServerMetrics: Aggregated metrics computed from all ServerMetric records.

        Examples:
            >>> from mcpgateway.services.server_service import ServerService
            >>> from unittest.mock import MagicMock
            >>> service = ServerService()
            >>> db = MagicMock()
            >>> db.execute.return_value.scalar.return_value = 0
            >>> import asyncio
            >>> result = asyncio.run(service.aggregate_metrics(db))
            >>> hasattr(result, 'total_executions')
            True
        """
        total_executions = db.execute(select(func.count()).select_from(ServerMetric)).scalar() or 0  # pylint: disable=not-callable

        successful_executions = db.execute(select(func.count()).select_from(ServerMetric).where(ServerMetric.is_success.is_(True))).scalar() or 0  # pylint: disable=not-callable

        failed_executions = db.execute(select(func.count()).select_from(ServerMetric).where(ServerMetric.is_success.is_(False))).scalar() or 0  # pylint: disable=not-callable

        min_response_time = db.execute(select(func.min(ServerMetric.response_time))).scalar()

        max_response_time = db.execute(select(func.max(ServerMetric.response_time))).scalar()

        avg_response_time = db.execute(select(func.avg(ServerMetric.response_time))).scalar()

        last_execution_time = db.execute(select(func.max(ServerMetric.timestamp))).scalar()

        return ServerMetrics(
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
        Reset all server metrics by deleting all records from the server metrics table.

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
        db.commit()
