# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/a2a_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

A2A Agent Service

This module implements A2A (Agent-to-Agent) agent management for the MCP Gateway.
It handles agent registration, listing, retrieval, updates, activation toggling, deletion,
and interactions with A2A-compatible agents.
"""

# Standard
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional

# Third-Party
import httpx
from sqlalchemy import and_, case, delete, desc, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import A2AAgent as DbA2AAgent
from mcpgateway.db import A2AAgentMetric, EmailTeam
from mcpgateway.schemas import A2AAgentCreate, A2AAgentMetrics, A2AAgentRead, A2AAgentUpdate
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.structured_logger import get_structured_logger
from mcpgateway.services.team_management_service import TeamManagementService
from mcpgateway.services.tool_service import ToolService
from mcpgateway.utils.correlation_id import get_correlation_id
from mcpgateway.utils.create_slug import slugify
from mcpgateway.utils.services_auth import encode_auth  # ,decode_auth

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

# Initialize structured logger for A2A lifecycle tracking
structured_logger = get_structured_logger("a2a_service")


class A2AAgentError(Exception):
    """Base class for A2A agent-related errors.

    Examples:
        >>> try:
        ...     raise A2AAgentError("Agent operation failed")
        ... except A2AAgentError as e:
        ...     str(e)
        'Agent operation failed'
        >>> try:
        ...     raise A2AAgentError("Connection error")
        ... except Exception as e:
        ...     isinstance(e, A2AAgentError)
        True
    """


class A2AAgentNotFoundError(A2AAgentError):
    """Raised when a requested A2A agent is not found.

    Examples:
        >>> try:
        ...     raise A2AAgentNotFoundError("Agent 'test-agent' not found")
        ... except A2AAgentNotFoundError as e:
        ...     str(e)
        "Agent 'test-agent' not found"
        >>> try:
        ...     raise A2AAgentNotFoundError("No such agent")
        ... except A2AAgentError as e:
        ...     isinstance(e, A2AAgentError)  # Should inherit from A2AAgentError
        True
    """


class A2AAgentNameConflictError(A2AAgentError):
    """Raised when an A2A agent name conflicts with an existing one."""

    def __init__(self, name: str, is_active: bool = True, agent_id: Optional[str] = None, visibility: Optional[str] = "public"):
        """Initialize an A2AAgentNameConflictError exception.

        Creates an exception that indicates an agent name conflict, with additional
        context about whether the conflicting agent is active and its ID if known.

        Args:
            name: The agent name that caused the conflict.
            is_active: Whether the conflicting agent is currently active.
            agent_id: The ID of the conflicting agent, if known.
            visibility: The visibility level of the conflicting agent (private, team, public).

        Examples:
            >>> error = A2AAgentNameConflictError("test-agent")
            >>> error.name
            'test-agent'
            >>> error.is_active
            True
            >>> error.agent_id is None
            True
            >>> "test-agent" in str(error)
            True
            >>>
            >>> # Test inactive agent conflict
            >>> error = A2AAgentNameConflictError("inactive-agent", is_active=False, agent_id="agent-123")
            >>> error.is_active
            False
            >>> error.agent_id
            'agent-123'
            >>> "inactive" in str(error)
            True
            >>> "agent-123" in str(error)
            True
        """
        self.name = name
        self.is_active = is_active
        self.agent_id = agent_id
        message = f"{visibility.capitalize()} A2A Agent already exists with name: {name}"
        if not is_active:
            message += f" (currently inactive, ID: {agent_id})"
        super().__init__(message)


class A2AAgentService:
    """Service for managing A2A agents in the gateway.

    Provides methods to create, list, retrieve, update, toggle status, and delete agent records.
    Also supports interactions with A2A-compatible agents.
    """

    def __init__(self) -> None:
        """Initialize a new A2AAgentService instance."""
        self._initialized = False
        self._event_streams: List[AsyncGenerator[str, None]] = []

    async def initialize(self) -> None:
        """Initialize the A2A agent service."""
        if not self._initialized:
            logger.info("Initializing A2A Agent Service")
            self._initialized = True

    async def shutdown(self) -> None:
        """Shutdown the A2A agent service and cleanup resources."""
        if self._initialized:
            logger.info("Shutting down A2A Agent Service")
            self._initialized = False

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
        return team.name if team else None

    async def register_agent(
        self,
        db: Session,
        agent_data: A2AAgentCreate,
        created_by: Optional[str] = None,
        created_from_ip: Optional[str] = None,
        created_via: Optional[str] = None,
        created_user_agent: Optional[str] = None,
        import_batch_id: Optional[str] = None,
        federation_source: Optional[str] = None,
        team_id: Optional[str] = None,
        owner_email: Optional[str] = None,
        visibility: Optional[str] = "public",
    ) -> A2AAgentRead:
        """Register a new A2A agent.

        Args:
            db (Session): Database session.
            agent_data (A2AAgentCreate): Data required to create an agent.
            created_by (Optional[str]): User who created the agent.
            created_from_ip (Optional[str]): IP address of the creator.
            created_via (Optional[str]): Method used for creation (e.g., API, import).
            created_user_agent (Optional[str]): User agent of the creation request.
            import_batch_id (Optional[str]): UUID of a bulk import batch.
            federation_source (Optional[str]): Source gateway for federated agents.
            team_id (Optional[str]): ID of the team to assign the agent to.
            owner_email (Optional[str]): Email of the agent owner.
            visibility (Optional[str]): Visibility level ('public', 'team', 'private').

        Returns:
            A2AAgentRead: The created agent object.

        Raises:
            A2AAgentNameConflictError: If another agent with the same name already exists.
            IntegrityError: If a database constraint or integrity violation occurs.
            ValueError: If invalid configuration or data is provided.
            A2AAgentError: For any other unexpected errors during registration.

        Examples:
            # TODO
        """
        try:
            agent_data.slug = slugify(agent_data.name)
            # Check for existing server with the same slug within the same team or public scope
            if visibility.lower() == "public":
                logger.info(f"visibility.lower(): {visibility.lower()}")
                logger.info(f"agent_data.name: {agent_data.name}")
                logger.info(f"agent_data.slug: {agent_data.slug}")
                # Check for existing public a2a agent with the same slug
                existing_agent = db.execute(select(DbA2AAgent).where(DbA2AAgent.slug == agent_data.slug, DbA2AAgent.visibility == "public")).scalar_one_or_none()
                if existing_agent:
                    raise A2AAgentNameConflictError(name=agent_data.slug, is_active=existing_agent.enabled, agent_id=existing_agent.id, visibility=existing_agent.visibility)
            elif visibility.lower() == "team" and team_id:
                # Check for existing team a2a agent with the same slug
                existing_agent = db.execute(select(DbA2AAgent).where(DbA2AAgent.slug == agent_data.slug, DbA2AAgent.visibility == "team", DbA2AAgent.team_id == team_id)).scalar_one_or_none()
                if existing_agent:
                    raise A2AAgentNameConflictError(name=agent_data.slug, is_active=existing_agent.enabled, agent_id=existing_agent.id, visibility=existing_agent.visibility)

            auth_type = getattr(agent_data, "auth_type", None)
            # Support multiple custom headers
            auth_value = getattr(agent_data, "auth_value", {})

            # authentication_headers: Optional[Dict[str, str]] = None

            if hasattr(agent_data, "auth_headers") and agent_data.auth_headers:
                # Convert list of {key, value} to dict
                header_dict = {h["key"]: h["value"] for h in agent_data.auth_headers if h.get("key")}
                # Keep encoded form for persistence, but pass raw headers for initialization
                auth_value = encode_auth(header_dict)  # Encode the dict for consistency
                # authentication_headers = {str(k): str(v) for k, v in header_dict.items()}
            # elif isinstance(auth_value, str) and auth_value:
            #    # Decode persisted auth for initialization
            #    decoded = decode_auth(auth_value)
            # authentication_headers = {str(k): str(v) for k, v in decoded.items()}
            else:
                # authentication_headers = None
                pass
                # auth_value = {}

            oauth_config = getattr(agent_data, "oauth_config", None)

            # Create new agent
            new_agent = DbA2AAgent(
                name=agent_data.name,
                description=agent_data.description,
                endpoint_url=agent_data.endpoint_url,
                agent_type=agent_data.agent_type,
                protocol_version=agent_data.protocol_version,
                capabilities=agent_data.capabilities,
                config=agent_data.config,
                auth_type=auth_type,
                auth_value=auth_value,  # This should be encrypted in practice
                oauth_config=oauth_config,
                tags=agent_data.tags,
                passthrough_headers=getattr(agent_data, "passthrough_headers", None),
                # Team scoping fields - use schema values if provided, otherwise fallback to parameters
                team_id=getattr(agent_data, "team_id", None) or team_id,
                owner_email=getattr(agent_data, "owner_email", None) or owner_email or created_by,
                visibility=getattr(agent_data, "visibility", None) or visibility,
                created_by=created_by,
                created_from_ip=created_from_ip,
                created_via=created_via,
                created_user_agent=created_user_agent,
                import_batch_id=import_batch_id,
                federation_source=federation_source,
            )

            db.add(new_agent)
            db.commit()
            db.refresh(new_agent)

            # Automatically create a tool for the A2A agent if not already present
            tool_service = ToolService()
            await tool_service.create_tool_from_a2a_agent(
                db=db,
                agent=new_agent,
                created_by=created_by,
                created_from_ip=created_from_ip,
                created_via=created_via,
                created_user_agent=created_user_agent,
            )

            logger.info(f"Registered new A2A agent: {new_agent.name} (ID: {new_agent.id})")

            # Log A2A agent registration for lifecycle tracking
            structured_logger.info(
                f"A2A agent '{new_agent.name}' registered successfully",
                user_id=created_by,
                user_email=owner_email,
                team_id=team_id,
                resource_type="a2a_agent",
                resource_id=str(new_agent.id),
                resource_action="create",
                custom_fields={
                    "agent_name": new_agent.name,
                    "agent_type": new_agent.agent_type,
                    "protocol_version": new_agent.protocol_version,
                    "visibility": visibility,
                    "endpoint_url": new_agent.endpoint_url,
                },
            )

            return self._db_to_schema(db=db, db_agent=new_agent)

        except A2AAgentNameConflictError as ie:
            db.rollback()
            raise ie
        except IntegrityError as ie:
            db.rollback()
            logger.error(f"IntegrityErrors in group: {ie}")
            raise ie
        except ValueError as ve:
            raise ve
        except Exception as e:
            db.rollback()
            raise A2AAgentError(f"Failed to register A2A agent: {str(e)}")

    async def list_agents(self, db: Session, cursor: Optional[str] = None, include_inactive: bool = False, tags: Optional[List[str]] = None) -> List[A2AAgentRead]:  # pylint: disable=unused-argument
        """List A2A agents with optional filtering.

        Args:
            db: Database session.
            cursor: Pagination cursor (not implemented yet).
            include_inactive: Whether to include inactive agents.
            tags: List of tags to filter by.

        Returns:
            List of agent data.

        Examples:
            >>> from mcpgateway.services.a2a_service import A2AAgentService
            >>> from unittest.mock import MagicMock
            >>> from mcpgateway.schemas import A2AAgentRead
            >>> import asyncio

            >>> service = A2AAgentService()
            >>> db = MagicMock()

            >>> # Mock a single agent object returned by the DB
            >>> agent_obj = MagicMock()
            >>> db.execute.return_value.scalars.return_value.all.return_value = [agent_obj]

            >>> # Mock the A2AAgentRead schema to return a masked string
            >>> mocked_agent_read = MagicMock()
            >>> mocked_agent_read.masked.return_value = 'agent_read'
            >>> A2AAgentRead.model_validate = MagicMock(return_value=mocked_agent_read)

            >>> # Run the service method
            >>> result = asyncio.run(service.list_agents(db))
            >>> result == ['agent_read']
            True

            >>> # Test include_inactive parameter (same mock works)
            >>> result_with_inactive = asyncio.run(service.list_agents(db, include_inactive=True))
            >>> result_with_inactive == ['agent_read']
            True

            >>> # Test empty result
            >>> db.execute.return_value.scalars.return_value.all.return_value = []
            >>> empty_result = asyncio.run(service.list_agents(db))
            >>> empty_result
            []

        """
        query = select(DbA2AAgent)

        if not include_inactive:
            query = query.where(DbA2AAgent.enabled.is_(True))

        if tags:
            # Filter by tags - agent must have at least one of the specified tags
            tag_conditions = []
            for tag in tags:
                tag_conditions.append(func.json_extract(DbA2AAgent.tags, "$").contains(tag))

            if tag_conditions:
                query = query.where(*tag_conditions)

        query = query.order_by(desc(DbA2AAgent.created_at))

        agents = db.execute(query).scalars().all()

        return [self._db_to_schema(db=db, db_agent=agent) for agent in agents]

    async def list_agents_for_user(
        self, db: Session, user_info: Dict[str, Any], team_id: Optional[str] = None, visibility: Optional[str] = None, include_inactive: bool = False, skip: int = 0, limit: int = 100
    ) -> List[A2AAgentRead]:
        """
        List A2A agents user has access to with team filtering.

        Args:
            db: Database session
            user_info: Object representing identity of the user who is requesting agents
            team_id: Optional team ID to filter by specific team
            visibility: Optional visibility filter (private, team, public)
            include_inactive: Whether to include inactive agents
            skip: Number of agents to skip for pagination
            limit: Maximum number of agents to return

        Returns:
            List[A2AAgentRead]: A2A agents the user has access to
        """

        # Handle case where user_info is a string (email) instead of dict (<0.7.0)
        if isinstance(user_info, str):
            user_email = str(user_info)
        else:
            user_email = user_info.get("email", "")

        # Build query following existing patterns from list_prompts()
        team_service = TeamManagementService(db)
        user_teams = await team_service.get_user_teams(user_email)
        team_ids = [team.id for team in user_teams]

        # Build query following existing patterns from list_agents()
        query = select(DbA2AAgent)

        # Apply active/inactive filter
        if not include_inactive:
            query = query.where(DbA2AAgent.enabled.is_(True))

        if team_id:
            if team_id not in team_ids:
                return []  # No access to team

            access_conditions = []
            # Filter by specific team
            access_conditions.append(and_(DbA2AAgent.team_id == team_id, DbA2AAgent.visibility.in_(["team", "public"])))

            access_conditions.append(and_(DbA2AAgent.team_id == team_id, DbA2AAgent.owner_email == user_email))

            query = query.where(or_(*access_conditions))
        else:
            # Get user's accessible teams
            # Build access conditions following existing patterns
            access_conditions = []
            # 1. User's personal resources (owner_email matches)
            access_conditions.append(DbA2AAgent.owner_email == user_email)
            # 2. Team A2A Agents where user is member
            if team_ids:
                access_conditions.append(and_(DbA2AAgent.team_id.in_(team_ids), DbA2AAgent.visibility.in_(["team", "public"])))
            # 3. Public resources (if visibility allows)
            access_conditions.append(DbA2AAgent.visibility == "public")

            query = query.where(or_(*access_conditions))

        # Apply visibility filter if specified
        if visibility:
            query = query.where(DbA2AAgent.visibility == visibility)

        # Apply pagination following existing patterns
        query = query.order_by(desc(DbA2AAgent.created_at))
        query = query.offset(skip).limit(limit)

        agents = db.execute(query).scalars().all()
        return [self._db_to_schema(db=db, db_agent=agent) for agent in agents]

    async def get_agent(self, db: Session, agent_id: str, include_inactive: bool = True) -> A2AAgentRead:
        """Retrieve an A2A agent by ID.

        Args:
            db: Database session.
            agent_id: Agent ID.
            include_inactive: Whether to include inactive a2a agents

        Returns:
            Agent data.

        Raises:
            A2AAgentNotFoundError: If the agent is not found.

        Examples:
            >>> from unittest.mock import MagicMock
            >>> from datetime import datetime
            >>> import asyncio
            >>> from mcpgateway.schemas import A2AAgentRead
            >>> from mcpgateway.services.a2a_service import A2AAgentService, A2AAgentNotFoundError

            >>> service = A2AAgentService()
            >>> db = MagicMock()

            >>> # Create a mock agent
            >>> agent_mock = MagicMock()
            >>> agent_mock.enabled = True
            >>> agent_mock.id = "agent_id"
            >>> agent_mock.name = "Test Agent"
            >>> agent_mock.slug = "test-agent"
            >>> agent_mock.description = "A2A test agent"
            >>> agent_mock.endpoint_url = "https://example.com"
            >>> agent_mock.agent_type = "rest"
            >>> agent_mock.protocol_version = "v1"
            >>> agent_mock.capabilities = {}
            >>> agent_mock.config = {}
            >>> agent_mock.reachable = True
            >>> agent_mock.created_at = datetime.now()
            >>> agent_mock.updated_at = datetime.now()
            >>> agent_mock.last_interaction = None
            >>> agent_mock.tags = []
            >>> agent_mock.metrics = MagicMock()
            >>> agent_mock.metrics.success_rate = 1.0
            >>> agent_mock.metrics.failure_rate = 0.0
            >>> agent_mock.metrics.last_error = None
            >>> agent_mock.auth_type = None
            >>> agent_mock.auth_value = None
            >>> agent_mock.oauth_config = None
            >>> agent_mock.created_by = "user"
            >>> agent_mock.created_from_ip = "127.0.0.1"
            >>> agent_mock.created_via = "ui"
            >>> agent_mock.created_user_agent = "test-agent"
            >>> agent_mock.modified_by = "user"
            >>> agent_mock.modified_from_ip = "127.0.0.1"
            >>> agent_mock.modified_via = "ui"
            >>> agent_mock.modified_user_agent = "test-agent"
            >>> agent_mock.import_batch_id = None
            >>> agent_mock.federation_source = None
            >>> agent_mock.team_id = "team-1"
            >>> agent_mock.team = "Team 1"
            >>> agent_mock.owner_email = "owner@example.com"
            >>> agent_mock.visibility = "public"

            >>> db.get.return_value = agent_mock

            >>> # Mock _db_to_schema to simplify test
            >>> service._db_to_schema = lambda db, db_agent: 'agent_read'

            >>> # Test with active agent
            >>> result = asyncio.run(service.get_agent(db, 'agent_id'))
            >>> result
            'agent_read'

            >>> # Test with inactive agent but include_inactive=True
            >>> agent_mock.enabled = False
            >>> result_inactive = asyncio.run(service.get_agent(db, 'agent_id', include_inactive=True))
            >>> result_inactive
            'agent_read'

        """
        query = select(DbA2AAgent).where(DbA2AAgent.id == agent_id)
        agent = db.execute(query).scalar_one_or_none()

        if not agent:
            raise A2AAgentNotFoundError(f"A2A Agent not found with ID: {agent_id}")

        # if agent.enabled or include_inactive:
        #    agent.team = self._get_team_name(db, getattr(agent, "team_id", None))
        #    return A2AAgentRead.model_validate(self._prepare_a2a_agent_for_read(agent)).masked()

        # raise A2AAgentNotFoundError(f"A2A Agent not found with ID: {agent_id}")

        if not agent.enabled and not include_inactive:
            raise A2AAgentNotFoundError(f"A2A Agent not found with ID: {agent_id}")

        # ✅ Delegate conversion and masking to _db_to_schema()
        return self._db_to_schema(db=db, db_agent=agent)

    async def get_agent_by_name(self, db: Session, agent_name: str) -> A2AAgentRead:
        """Retrieve an A2A agent by name.

        Args:
            db: Database session.
            agent_name: Agent name.

        Returns:
            Agent data.

        Raises:
            A2AAgentNotFoundError: If the agent is not found.
        """
        query = select(DbA2AAgent).where(DbA2AAgent.name == agent_name)
        agent = db.execute(query).scalar_one_or_none()

        if not agent:
            raise A2AAgentNotFoundError(f"A2A Agent not found with name: {agent_name}")

        return self._db_to_schema(db=db, db_agent=agent)

    async def update_agent(
        self,
        db: Session,
        agent_id: str,
        agent_data: A2AAgentUpdate,
        modified_by: Optional[str] = None,
        modified_from_ip: Optional[str] = None,
        modified_via: Optional[str] = None,
        modified_user_agent: Optional[str] = None,
        user_email: Optional[str] = None,
    ) -> A2AAgentRead:
        """Update an existing A2A agent.

        Args:
            db: Database session.
            agent_id: Agent ID.
            agent_data: Agent update data.
            modified_by: Username who modified this agent.
            modified_from_ip: IP address of modifier.
            modified_via: Modification method.
            modified_user_agent: User agent of modification request.
            user_email: Email of user performing update (for ownership check).

        Returns:
            Updated agent data.

        Raises:
            A2AAgentNotFoundError: If the agent is not found.
            PermissionError: If user doesn't own the agent.
            A2AAgentNameConflictError: If name conflicts with another agent.
            A2AAgentError: For other errors during update.
            IntegrityError: If a database integrity error occurs.
        """
        try:
            query = select(DbA2AAgent).where(DbA2AAgent.id == agent_id)
            agent = db.execute(query).scalar_one_or_none()

            if not agent:
                raise A2AAgentNotFoundError(f"A2A Agent not found with ID: {agent_id}")

            # Check ownership if user_email provided
            if user_email:
                # First-Party
                from mcpgateway.services.permission_service import PermissionService  # pylint: disable=import-outside-toplevel

                permission_service = PermissionService(db)
                if not await permission_service.check_resource_ownership(user_email, agent):
                    raise PermissionError("Only the owner can update this agent")
            # Check for name conflict if name is being updated
            if agent_data.name and agent_data.name != agent.name:
                new_slug = slugify(agent_data.name)
                visibility = agent_data.visibility or agent.visibility
                team_id = agent_data.team_id or agent.team_id
                # Check for existing server with the same slug within the same team or public scope
                if visibility.lower() == "public":
                    # Check for existing public a2a agent with the same slug
                    existing_agent = db.execute(select(DbA2AAgent).where(DbA2AAgent.slug == new_slug, DbA2AAgent.visibility == "public")).scalar_one_or_none()
                    if existing_agent:
                        raise A2AAgentNameConflictError(name=new_slug, is_active=existing_agent.enabled, agent_id=existing_agent.id, visibility=existing_agent.visibility)
                elif visibility.lower() == "team" and team_id:
                    # Check for existing team a2a agent with the same slug
                    existing_agent = db.execute(select(DbA2AAgent).where(DbA2AAgent.slug == new_slug, DbA2AAgent.visibility == "team", DbA2AAgent.team_id == team_id)).scalar_one_or_none()
                    if existing_agent:
                        raise A2AAgentNameConflictError(name=new_slug, is_active=existing_agent.enabled, agent_id=existing_agent.id, visibility=existing_agent.visibility)
            # Update fields
            update_data = agent_data.model_dump(exclude_unset=True)

            for field, value in update_data.items():
                if field == "passthrough_headers":
                    if value is not None:
                        if isinstance(value, list):
                            # Clean list: remove empty or whitespace-only entries
                            cleaned = [h.strip() for h in value if isinstance(h, str) and h.strip()]
                            agent.passthrough_headers = cleaned or None
                        elif isinstance(value, str):
                            # Parse comma-separated string and clean
                            parsed: List[str] = [h.strip() for h in value.split(",") if h.strip()]
                            agent.passthrough_headers = parsed or None
                        else:
                            raise A2AAgentError("Invalid passthrough_headers format: must be list[str] or comma-separated string")
                    else:
                        # Explicitly set to None if value is None
                        agent.passthrough_headers = None
                    continue

                if hasattr(agent, field):
                    setattr(agent, field, value)

            # Update metadata
            if modified_by:
                agent.modified_by = modified_by
            if modified_from_ip:
                agent.modified_from_ip = modified_from_ip
            if modified_via:
                agent.modified_via = modified_via
            if modified_user_agent:
                agent.modified_user_agent = modified_user_agent

            agent.version += 1

            db.commit()
            db.refresh(agent)

            logger.info(f"Updated A2A agent: {agent.name} (ID: {agent.id})")
            return self._db_to_schema(db=db, db_agent=agent)
        except PermissionError:
            db.rollback()
            raise
        except A2AAgentNameConflictError as ie:
            db.rollback()
            raise ie
        except A2AAgentNotFoundError as nf:
            db.rollback()
            raise nf
        except IntegrityError as ie:
            db.rollback()
            logger.error(f"IntegrityErrors in group: {ie}")
            raise ie
        except Exception as e:
            db.rollback()
            raise A2AAgentError(f"Failed to update A2A agent: {str(e)}")

    async def toggle_agent_status(self, db: Session, agent_id: str, activate: bool, reachable: Optional[bool] = None, user_email: Optional[str] = None) -> A2AAgentRead:
        """Toggle the activation status of an A2A agent.

        Args:
            db: Database session.
            agent_id: Agent ID.
            activate: True to activate, False to deactivate.
            reachable: Optional reachability status.
            user_email: Optional[str] The email of the user to check if the user has permission to modify.

        Returns:
            Updated agent data.

        Raises:
            A2AAgentNotFoundError: If the agent is not found.
            PermissionError: If user doesn't own the agent.
        """
        query = select(DbA2AAgent).where(DbA2AAgent.id == agent_id)
        agent = db.execute(query).scalar_one_or_none()

        if not agent:
            raise A2AAgentNotFoundError(f"A2A Agent not found with ID: {agent_id}")

        if user_email:
            # First-Party
            from mcpgateway.services.permission_service import PermissionService  # pylint: disable=import-outside-toplevel

            permission_service = PermissionService(db)
            if not await permission_service.check_resource_ownership(user_email, agent):
                raise PermissionError("Only the owner can activate the Agent" if activate else "Only the owner can deactivate the Agent")

        agent.enabled = activate
        if reachable is not None:
            agent.reachable = reachable

        db.commit()
        db.refresh(agent)

        status = "activated" if activate else "deactivated"
        logger.info(f"A2A agent {status}: {agent.name} (ID: {agent.id})")

        structured_logger.log(
            level="INFO",
            message=f"A2A agent {status}",
            event_type="a2a_agent_status_changed",
            component="a2a_service",
            user_email=user_email,
            resource_type="a2a_agent",
            resource_id=str(agent.id),
            custom_fields={
                "agent_name": agent.name,
                "enabled": agent.enabled,
                "reachable": agent.reachable,
            },
        )

        return self._db_to_schema(db=db, db_agent=agent)

    async def delete_agent(self, db: Session, agent_id: str, user_email: Optional[str] = None) -> None:
        """Delete an A2A agent.

        Args:
            db: Database session.
            agent_id: Agent ID.
            user_email: Email of user performing delete (for ownership check).

        Raises:
            A2AAgentNotFoundError: If the agent is not found.
            PermissionError: If user doesn't own the agent.
        """
        try:
            query = select(DbA2AAgent).where(DbA2AAgent.id == agent_id)
            agent = db.execute(query).scalar_one_or_none()

            if not agent:
                raise A2AAgentNotFoundError(f"A2A Agent not found with ID: {agent_id}")

            # Check ownership if user_email provided
            if user_email:
                # First-Party
                from mcpgateway.services.permission_service import PermissionService  # pylint: disable=import-outside-toplevel

                permission_service = PermissionService(db)
                if not await permission_service.check_resource_ownership(user_email, agent):
                    raise PermissionError("Only the owner can delete this agent")

            agent_name = agent.name
            db.delete(agent)
            db.commit()

            logger.info(f"Deleted A2A agent: {agent_name} (ID: {agent_id})")

            structured_logger.log(
                level="INFO",
                message="A2A agent deleted",
                event_type="a2a_agent_deleted",
                component="a2a_service",
                user_email=user_email,
                resource_type="a2a_agent",
                resource_id=str(agent_id),
                custom_fields={"agent_name": agent_name},
            )
        except PermissionError:
            db.rollback()
            raise

    async def invoke_agent(
        self,
        db: Session,
        agent_name: str,
        parameters: Dict[str, Any],
        interaction_type: str = "query",
        *,
        user_id: Optional[str] = None,
        user_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Invoke an A2A agent.

        Args:
            db: Database session.
            agent_name: Name of the agent to invoke.
            parameters: Parameters for the interaction.
            interaction_type: Type of interaction.
            user_id: Identifier of the user initiating the call.
            user_email: Email of the user initiating the call.

        Returns:
            Agent response.

        Raises:
            A2AAgentNotFoundError: If the agent is not found.
            A2AAgentError: If the agent is disabled or invocation fails.
        """
        agent = await self.get_agent_by_name(db, agent_name)

        if not agent.enabled:
            raise A2AAgentError(f"A2A Agent '{agent_name}' is disabled")

        start_time = datetime.now(timezone.utc)
        success = False
        error_message = None
        response = None

        try:
            # Prepare the request to the A2A agent
            # Format request based on agent type and endpoint
            if agent.agent_type in ["generic", "jsonrpc"] or agent.endpoint_url.endswith("/"):
                # Use JSONRPC format for agents that expect it
                request_data = {"jsonrpc": "2.0", "method": parameters.get("method", "message/send"), "params": parameters.get("params", parameters), "id": 1}
            else:
                # Use custom A2A format
                request_data = {"interaction_type": interaction_type, "parameters": parameters, "protocol_version": agent.protocol_version}

            # Make HTTP request to the agent endpoint
            async with httpx.AsyncClient(timeout=30.0) as client:
                headers = {"Content-Type": "application/json"}

                # Add authentication if configured
                if agent.auth_type in ("api_key", "bearer"):
                    # Fetch raw encrypted auth_value from DB layer for use in header
                    db_row = db.execute(select(DbA2AAgent).where(DbA2AAgent.name == agent_name)).scalar_one_or_none()
                    token_value = getattr(db_row, "auth_value", None) if db_row else None
                    if token_value:
                        headers["Authorization"] = f"Bearer {token_value}"

                # Add correlation ID to outbound headers for distributed tracing
                correlation_id = get_correlation_id()
                if correlation_id:
                    headers["X-Correlation-ID"] = correlation_id

                # Log A2A external call start
                call_start_time = datetime.now(timezone.utc)
                structured_logger.log(
                    level="INFO",
                    message=f"A2A external call started: {agent_name}",
                    component="a2a_service",
                    user_id=user_id,
                    user_email=user_email,
                    correlation_id=correlation_id,
                    metadata={
                        "event": "a2a_call_started",
                        "agent_name": agent_name,
                        "agent_id": agent.id,
                        "endpoint_url": agent.endpoint_url,
                        "interaction_type": interaction_type,
                        "protocol_version": agent.protocol_version,
                    },
                )

                http_response = await client.post(agent.endpoint_url, json=request_data, headers=headers)
                call_duration_ms = (datetime.now(timezone.utc) - call_start_time).total_seconds() * 1000

                if http_response.status_code == 200:
                    response = http_response.json()
                    success = True

                    # Log successful A2A call
                    structured_logger.log(
                        level="INFO",
                        message=f"A2A external call completed: {agent_name}",
                        component="a2a_service",
                        user_id=user_id,
                        user_email=user_email,
                        correlation_id=correlation_id,
                        duration_ms=call_duration_ms,
                        metadata={"event": "a2a_call_completed", "agent_name": agent_name, "agent_id": agent.id, "status_code": http_response.status_code, "success": True},
                    )
                else:
                    error_message = f"HTTP {http_response.status_code}: {http_response.text}"

                    # Log failed A2A call
                    structured_logger.log(
                        level="ERROR",
                        message=f"A2A external call failed: {agent_name}",
                        component="a2a_service",
                        user_id=user_id,
                        user_email=user_email,
                        correlation_id=correlation_id,
                        duration_ms=call_duration_ms,
                        error_details={"error_type": "A2AHTTPError", "error_message": error_message},
                        metadata={"event": "a2a_call_failed", "agent_name": agent_name, "agent_id": agent.id, "status_code": http_response.status_code},
                    )

                    raise A2AAgentError(error_message)

        except Exception as e:
            error_message = str(e)
            logger.error(f"Failed to invoke A2A agent '{agent_name}': {error_message}")
            raise A2AAgentError(f"Failed to invoke A2A agent: {error_message}")

        finally:
            # Record metrics
            end_time = datetime.now(timezone.utc)
            response_time = (end_time - start_time).total_seconds()

            metric = A2AAgentMetric(a2a_agent_id=agent.id, response_time=response_time, is_success=success, error_message=error_message, interaction_type=interaction_type)
            db.add(metric)

            # Update last interaction timestamp
            query = select(DbA2AAgent).where(DbA2AAgent.id == agent.id)
            db_agent = db.execute(query).scalar_one()
            db_agent.last_interaction = end_time

            db.commit()

        return response or {"error": error_message}

    async def aggregate_metrics(self, db: Session) -> Dict[str, Any]:
        """Aggregate metrics for all A2A agents.

        Args:
            db: Database session.

        Returns:
            Aggregated metrics.
        """
        # Get total number of agents
        total_agents = db.execute(select(func.count(DbA2AAgent.id))).scalar()  # pylint: disable=not-callable
        active_agents = db.execute(select(func.count(DbA2AAgent.id)).where(DbA2AAgent.enabled.is_(True))).scalar()  # pylint: disable=not-callable

        # Get overall metrics
        metrics_query = select(
            func.count(A2AAgentMetric.id).label("total_interactions"),  # pylint: disable=not-callable
            func.sum(case((A2AAgentMetric.is_success.is_(True), 1), else_=0)).label("successful_interactions"),
            func.avg(A2AAgentMetric.response_time).label("avg_response_time"),
            func.min(A2AAgentMetric.response_time).label("min_response_time"),
            func.max(A2AAgentMetric.response_time).label("max_response_time"),
        )

        metrics_result = db.execute(metrics_query).first()

        if metrics_result:
            total_interactions = metrics_result.total_interactions or 0
            successful_interactions = metrics_result.successful_interactions or 0
            avg_rt = float(metrics_result.avg_response_time or 0.0)
            min_rt = float(metrics_result.min_response_time or 0.0)
            max_rt = float(metrics_result.max_response_time or 0.0)
        else:
            total_interactions = 0
            successful_interactions = 0
            avg_rt = 0.0
            min_rt = 0.0
            max_rt = 0.0
        failed_interactions = total_interactions - successful_interactions

        return {
            "total_agents": total_agents,
            "active_agents": active_agents,
            "total_interactions": total_interactions,
            "successful_interactions": successful_interactions,
            "failed_interactions": failed_interactions,
            "success_rate": (successful_interactions / total_interactions * 100) if total_interactions > 0 else 0.0,
            "avg_response_time": avg_rt,
            "min_response_time": min_rt,
            "max_response_time": max_rt,
        }

    async def reset_metrics(self, db: Session, agent_id: Optional[str] = None) -> None:
        """Reset metrics for agents.

        Args:
            db: Database session.
            agent_id: Optional agent ID to reset metrics for specific agent.
        """
        if agent_id:
            # Reset metrics for specific agent
            delete_query = delete(A2AAgentMetric).where(A2AAgentMetric.a2a_agent_id == agent_id)
        else:
            # Reset all metrics
            delete_query = delete(A2AAgentMetric)

        db.execute(delete_query)
        db.commit()

        logger.info("Reset A2A agent metrics" + (f" for agent {agent_id}" if agent_id else ""))

    def _prepare_a2a_agent_for_read(self, agent: DbA2AAgent) -> DbA2AAgent:
        """Prepare a a2a agent object for A2AAgentRead validation.

        Ensures auth_value is in the correct format (encoded string) for the schema.

        Args:
            agent: A2A Agent database object

        Returns:
            A2A Agent object with properly formatted auth_value
        """
        # If auth_value is a dict, encode it to string for GatewayRead schema
        if isinstance(agent.auth_value, dict):
            agent.auth_value = encode_auth(agent.auth_value)
        return agent

    def _db_to_schema(self, db: Session, db_agent: DbA2AAgent) -> A2AAgentRead:
        """Convert database model to schema.

        Args:
            db (Session): Database session.
            db_agent (DbA2AAgent): Database agent model.

        Returns:
            A2AAgentRead: Agent read schema.

        Raises:
            A2AAgentNotFoundError: If the provided agent is not found or invalid.

        """

        if not db_agent:
            raise A2AAgentNotFoundError("Agent not found")

        setattr(db_agent, "team", self._get_team_name(db, getattr(db_agent, "team_id", None)))

        # ✅ Compute metrics
        total_executions = len(db_agent.metrics)
        successful_executions = sum(1 for m in db_agent.metrics if m.is_success)
        failed_executions = total_executions - successful_executions
        failure_rate = (failed_executions / total_executions * 100) if total_executions > 0 else 0.0

        min_response_time = max_response_time = avg_response_time = last_execution_time = None
        if db_agent.metrics:
            response_times = [m.response_time for m in db_agent.metrics if m.response_time is not None]
            if response_times:
                min_response_time = min(response_times)
                max_response_time = max(response_times)
                avg_response_time = sum(response_times) / len(response_times)
            last_execution_time = max((m.timestamp for m in db_agent.metrics), default=None)

        metrics = A2AAgentMetrics(
            total_executions=total_executions,
            successful_executions=successful_executions,
            failed_executions=failed_executions,
            failure_rate=failure_rate,
            min_response_time=min_response_time,
            max_response_time=max_response_time,
            avg_response_time=avg_response_time,
            last_execution_time=last_execution_time,
        )

        # Build dict from ORM model
        agent_data = {k: getattr(db_agent, k, None) for k in A2AAgentRead.model_fields.keys()}
        agent_data["metrics"] = metrics
        agent_data["team"] = getattr(db_agent, "team", None)

        # Validate using Pydantic model
        validated_agent = A2AAgentRead.model_validate(agent_data)

        # Return masked version (like GatewayRead)
        return validated_agent.masked()
