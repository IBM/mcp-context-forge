# -*- coding: utf-8 -*-
# pylint: disable=invalid-name, import-outside-toplevel, unused-import, no-name-in-module
"""Location: ./mcpgateway/services/a2a_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

A2A Agent Service

This module implements A2A (Agent-to-Agent) agent management for ContextForge.
It handles agent registration, listing, retrieval, updates, activation toggling, deletion,
and interactions with A2A-compatible agents.
"""

# Standard
import binascii
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional, Union

# Third-Party
from pydantic import ValidationError
from sqlalchemy import and_, delete, desc, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.cache.a2a_stats_cache import a2a_stats_cache
from mcpgateway.db import A2AAgent as DbA2AAgent
from mcpgateway.db import A2AAgentMetric, A2AAgentMetricsHourly, EmailTeam, fresh_db_session, get_for_update
from mcpgateway.schemas import A2AAgentCreate, A2AAgentMetrics, A2AAgentRead, A2AAgentUpdate
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.metrics_cleanup_service import delete_metrics_in_batches, pause_rollup_during_purge
from mcpgateway.services.structured_logger import get_structured_logger
from mcpgateway.services.team_management_service import TeamManagementService
from mcpgateway.utils.correlation_id import get_correlation_id
from mcpgateway.utils.create_slug import slugify
from mcpgateway.utils.pagination import unified_paginate
from mcpgateway.utils.services_auth import decode_auth, encode_auth
from mcpgateway.utils.sqlalchemy_modifier import json_contains_tag_expr

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

    Provides methods to create, list, retrieve, update, set state, and delete agent records.
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
        db.commit()  # Release transaction to avoid idle-in-transaction
        return team.name if team else None

    def _batch_get_team_names(self, db: Session, team_ids: List[str]) -> Dict[str, str]:
        """Batch retrieve team names for multiple team IDs.

        This method fetches team names in a single query to avoid N+1 issues
        when converting multiple agents to schemas in list operations.

        Args:
            db (Session): Database session for querying teams.
            team_ids (List[str]): List of team IDs to look up.

        Returns:
            Dict[str, str]: Mapping of team_id -> team_name for active teams.
        """
        if not team_ids:
            return {}

        # Single query for all teams
        teams = db.query(EmailTeam.id, EmailTeam.name).filter(EmailTeam.id.in_(team_ids), EmailTeam.is_active.is_(True)).all()

        return {team.id: team.name for team in teams}

    def _check_agent_access(
        self,
        agent: DbA2AAgent,
        user_email: Optional[str],
        token_teams: Optional[List[str]],
    ) -> bool:
        """Check if user has access to agent based on visibility rules.

        Access rules (matching tools/resources/prompts):
        - token_teams is None: Admin bypass (unrestricted access)
        - public visibility: Always allowed
        - team visibility: Allowed if agent.team_id in token_teams
        - private visibility: Allowed if owner, BUT NOT for public-only tokens

        Args:
            agent: The agent to check access for
            user_email: User's email for owner matching
            token_teams: Teams from JWT. None = admin, [] = public-only (no owner access)

        Returns:
            True if access allowed, False otherwise.
        """
        # Admin bypass - token_teams is None means unrestricted access
        if token_teams is None:
            return True

        if agent.visibility == "public":
            return True

        if agent.visibility == "team" and token_teams:
            return agent.team_id in token_teams

        # Private visibility: owner can access, BUT NOT for public-only tokens
        # Public-only tokens (empty teams array) should NOT get owner access
        is_public_only_token = len(token_teams) == 0
        if agent.visibility == "private" and user_email and not is_public_only_token:
            return agent.owner_email == user_email

        return False

    def _apply_visibility_filter(
        self,
        query,
        user_email: Optional[str],
        token_teams: List[str],
        team_id: Optional[str] = None,
    ) -> Any:
        """Apply visibility-based access control to query.

        Access rules (matching tools/resources/prompts):
        - public: visible to all
        - team: visible to team members (token_teams contains team_id)
        - private: visible only to owner, BUT NOT for public-only tokens

        Args:
            query: SQLAlchemy query to filter
            user_email: User's email for owner matching
            token_teams: Teams from JWT. [] = public-only (no owner access)
            team_id: Optional specific team filter

        Returns:
            Filtered query
        """
        # Check if this is a public-only token (empty teams array)
        # Public-only tokens can ONLY see public resources - no owner access
        is_public_only_token = len(token_teams) == 0

        # General access: public + team (+ owner if not public-only token)
        access_conditions = [DbA2AAgent.visibility == "public"]

        if team_id:
            # User requesting specific team - verify access
            if team_id not in token_teams:
                # Return query that matches nothing (will return empty result)
                return query.where(False)

            access_conditions.append(and_(DbA2AAgent.team_id == team_id, DbA2AAgent.visibility.in_(["team", "public"])))
            
            # Only include owner access for non-public-only tokens with user_email
            if not is_public_only_token and user_email:
                access_conditions.append(and_(DbA2AAgent.team_id == team_id, DbA2AAgent.owner_email == user_email))
            return query.where(or_(*access_conditions))


        # Only include owner access for non-public-only tokens with user_email
        if not is_public_only_token and user_email:
            access_conditions.append(DbA2AAgent.owner_email == user_email)

        if token_teams:
            access_conditions.append(and_(DbA2AAgent.team_id.in_(token_teams), DbA2AAgent.visibility.in_(["team", "public"])))

        return query.where(or_(*access_conditions))

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
                existing_agent = get_for_update(db, DbA2AAgent, where=and_(DbA2AAgent.slug == agent_data.slug, DbA2AAgent.visibility == "public"))
                if existing_agent:
                    raise A2AAgentNameConflictError(name=agent_data.slug, is_active=existing_agent.enabled, agent_id=existing_agent.id, visibility=existing_agent.visibility)
            elif visibility.lower() == "team" and team_id:
                # Check for existing team a2a agent with the same slug
                existing_agent = get_for_update(db, DbA2AAgent, where=and_(DbA2AAgent.slug == agent_data.slug, DbA2AAgent.visibility == "team", DbA2AAgent.team_id == team_id))
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

            # Handle query_param auth - encrypt and prepare for storage
            auth_query_params_encrypted: Optional[Dict[str, str]] = None
            if auth_type == "query_param":
                # Standard
                from urllib.parse import urlparse  # pylint: disable=import-outside-toplevel

                # First-Party
                from mcpgateway.config import settings  # pylint: disable=import-outside-toplevel

                # Service-layer enforcement: Check feature flag
                if not settings.insecure_allow_queryparam_auth:
                    raise ValueError("Query parameter authentication is disabled. Set INSECURE_ALLOW_QUERYPARAM_AUTH=true to enable.")

                # Service-layer enforcement: Check host allowlist
                if settings.insecure_queryparam_auth_allowed_hosts:
                    parsed = urlparse(str(agent_data.endpoint_url))
                    hostname = (parsed.hostname or "").lower()
                    allowed_hosts = [h.lower() for h in settings.insecure_queryparam_auth_allowed_hosts]
                    if hostname not in allowed_hosts:
                        allowed = ", ".join(settings.insecure_queryparam_auth_allowed_hosts)
                        raise ValueError(f"Host '{hostname}' is not in the allowed hosts for query param auth. " f"Allowed: {allowed}")

                # Extract and encrypt query param auth
                param_key = getattr(agent_data, "auth_query_param_key", None)
                param_value = getattr(agent_data, "auth_query_param_value", None)
                if param_key and param_value:
                    # Handle SecretStr
                    if hasattr(param_value, "get_secret_value"):
                        raw_value = param_value.get_secret_value()
                    else:
                        raw_value = str(param_value)
                    # Encrypt for storage
                    encrypted_value = encode_auth({param_key: raw_value})
                    auth_query_params_encrypted = {param_key: encrypted_value}
                    # Query param auth doesn't use auth_value
                    auth_value = None

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
                auth_query_params=auth_query_params_encrypted,  # Encrypted query param auth
                oauth_config=oauth_config,
                tags=agent_data.tags,
                passthrough_headers=getattr(agent_data, "passthrough_headers", None),
                # Team scoping fields - use schema values if provided, otherwise fallback to parameters
                team_id=getattr(agent_data, "team_id", None) or team_id,
                owner_email=getattr(agent_data, "owner_email", None) or owner_email or created_by,
                # Endpoint visibility parameter takes precedence over schema default
                visibility=visibility if visibility is not None else getattr(agent_data, "visibility", "public"),
                created_by=created_by,
                created_from_ip=created_from_ip,
                created_via=created_via,
                created_user_agent=created_user_agent,
                import_batch_id=import_batch_id,
                federation_source=federation_source,
            )

            db.add(new_agent)
            # Commit agent FIRST to ensure it persists even if tool creation fails
            # This is critical because ToolService.register_tool calls db.rollback()
            # on error, which would undo a pending (flushed but uncommitted) agent
            db.commit()
            db.refresh(new_agent)

            # Invalidate caches since agent count changed
            # Wrapped in try/except to ensure cache failures don't fail the request
            # when the agent is already successfully committed
            try:
                a2a_stats_cache.invalidate()
                cache = _get_registry_cache()
                await cache.invalidate_agents()
                # Also invalidate tags cache since agent tags may have changed
                # First-Party
                from mcpgateway.cache.admin_stats_cache import admin_stats_cache  # pylint: disable=import-outside-toplevel

                await admin_stats_cache.invalidate_tags()
                # First-Party
                from mcpgateway.cache.metrics_cache import metrics_cache  # pylint: disable=import-outside-toplevel

                metrics_cache.invalidate("a2a")
            except Exception as cache_error:
                logger.warning(f"Cache invalidation failed after agent commit: {cache_error}")

            # Automatically create a tool for the A2A agent if not already present
            # Tool creation is wrapped in try/except to ensure agent registration succeeds
            # even if tool creation fails (e.g., due to visibility or permission issues)
            tool_db = None
            try:
                # First-Party
                from mcpgateway.services.tool_service import tool_service

                tool_db = await tool_service.create_tool_from_a2a_agent(
                    db=db,
                    agent=new_agent,
                    created_by=created_by,
                    created_from_ip=created_from_ip,
                    created_via=created_via,
                    created_user_agent=created_user_agent,
                )

                # Associate the tool with the agent using the relationship
                # This sets both the tool_id foreign key and the tool relationship
                new_agent.tool = tool_db
                db.commit()
                db.refresh(new_agent)
                logger.info(f"Registered new A2A agent: {new_agent.name} (ID: {new_agent.id}) with tool ID: {tool_db.id}")
            except Exception as tool_error:
                # Log the error but don't fail agent registration
                # Agent was already committed above, so it persists even if tool creation fails
                logger.warning(f"Failed to create tool for A2A agent {new_agent.name}: {tool_error}")
                structured_logger.warning(
                    f"A2A agent '{new_agent.name}' created without tool association",
                    user_id=created_by,
                    resource_type="a2a_agent",
                    resource_id=str(new_agent.id),
                    custom_fields={"error": str(tool_error), "agent_name": new_agent.name},
                )
                # Refresh the agent to ensure it's in a clean state after any rollback
                db.refresh(new_agent)
                logger.info(f"Registered new A2A agent: {new_agent.name} (ID: {new_agent.id}) without tool")

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

            return self.convert_agent_to_read(new_agent, db=db)

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

    async def list_agents(
        self,
        db: Session,
        cursor: Optional[str] = None,
        include_inactive: bool = False,
        tags: Optional[List[str]] = None,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        per_page: Optional[int] = None,
        user_email: Optional[str] = None,
        token_teams: Optional[List[str]] = None,
        team_id: Optional[str] = None,
        visibility: Optional[str] = None,
    ) -> Union[tuple[List[A2AAgentRead], Optional[str]], Dict[str, Any]]:
        """List A2A agents with cursor pagination and optional team filtering.

        Args:
            db: Database session.
            cursor: Pagination cursor for keyset pagination.
            include_inactive: Whether to include inactive agents.
            tags: List of tags to filter by.
            limit: Maximum number of agents to return. None for default, 0 for unlimited.
            page: Page number for page-based pagination (1-indexed). Mutually exclusive with cursor.
            per_page: Items per page for page-based pagination. Defaults to pagination_default_page_size.
            user_email: Email of user for owner matching in visibility checks.
            token_teams: Teams from JWT token. None = admin (no filtering),
                         [] = public-only, [...] = team-scoped access.
            team_id: Optional team ID to filter by specific team.
            visibility: Optional visibility filter (private, team, public).

        Returns:
            If page is provided: Dict with {"data": [...], "pagination": {...}, "links": {...}}
            If cursor is provided or neither: tuple of (list of A2AAgentRead objects, next_cursor).

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
            >>> agents, cursor = asyncio.run(service.list_agents(db))
            >>> agents == ['agent_read'] and cursor is None
            True

            >>> # Test include_inactive parameter (same mock works)
            >>> agents_with_inactive, cursor = asyncio.run(service.list_agents(db, include_inactive=True))
            >>> agents_with_inactive == ['agent_read'] and cursor is None
            True

            >>> # Test empty result
            >>> db.execute.return_value.scalars.return_value.all.return_value = []
            >>> empty_agents, cursor = asyncio.run(service.list_agents(db))
            >>> empty_agents == [] and cursor is None
            True

        """
        # ══════════════════════════════════════════════════════════════════════
        # CACHE READ: Skip cache when ANY access filtering is applied
        # This prevents leaking admin-level results to filtered requests
        # Cache only when: user_email is None AND token_teams is None AND page is None
        # ══════════════════════════════════════════════════════════════════════
        cache = _get_registry_cache()
        if cursor is None and user_email is None and token_teams is None and page is None:
            filters_hash = cache.hash_filters(include_inactive=include_inactive, tags=sorted(tags) if tags else None)
            cached = await cache.get("agents", filters_hash)
            if cached is not None:
                # Reconstruct A2AAgentRead objects from cached dicts
                cached_agents = [A2AAgentRead.model_validate(a) for a in cached["agents"]]
                return (cached_agents, cached.get("next_cursor"))

        # Build base query with ordering
        query = select(DbA2AAgent).order_by(desc(DbA2AAgent.created_at), desc(DbA2AAgent.id))

        # Apply active/inactive filter
        if not include_inactive:
            query = query.where(DbA2AAgent.enabled)

        # Apply team-based access control if user_email is provided OR token_teams is explicitly set
        # This ensures unauthenticated requests with token_teams=[] only see public agents
        if user_email or token_teams is not None:
            # Use token_teams if provided (for MCP/API token access), otherwise look up from DB
            # Default is public-only access (empty teams) when no teams are available.
            effective_teams: List[str] = []
            if token_teams is not None:
                effective_teams = token_teams
            elif user_email:
                # Look up user's teams from DB (for admin UI / first-party access)
                team_service = TeamManagementService(db)
                user_teams = await team_service.get_user_teams(user_email)
                effective_teams = [team.id for team in user_teams]

            query = self._apply_visibility_filter(query, user_email, effective_teams, team_id)

        # IMPORTANT: Apply visibility filter AFTER access control
        # This allows users to further filter by visibility within their allowed access
        if visibility:
            query = query.where(DbA2AAgent.visibility == visibility)

        # Add tag filtering if tags are provided (supports both List[str] and List[Dict] formats)
        if tags:
            query = query.where(json_contains_tag_expr(db, DbA2AAgent.tags, tags, match_any=True))

        # Use unified pagination helper - handles both page and cursor pagination
        pag_result = await unified_paginate(
            db=db,
            query=query,
            page=page,
            per_page=per_page,
            cursor=cursor,
            limit=limit,
            base_url="/admin/a2a",  # Used for page-based links
            query_params={"include_inactive": include_inactive} if include_inactive else {},
        )

        next_cursor = None
        # Extract servers based on pagination type
        if page is not None:
            # Page-based: pag_result is a dict
            a2a_agents_db = pag_result["data"]
        else:
            # Cursor-based: pag_result is a tuple
            a2a_agents_db, next_cursor = pag_result

        # Fetch team names for the agents (common for both pagination types)
        team_ids_set = {s.team_id for s in a2a_agents_db if s.team_id}
        team_map = {}
        if team_ids_set:
            teams = db.execute(select(EmailTeam.id, EmailTeam.name).where(EmailTeam.id.in_(team_ids_set), EmailTeam.is_active.is_(True))).all()
            team_map = {team.id: team.name for team in teams}

        db.commit()  # Release transaction to avoid idle-in-transaction

        # Convert to A2AAgentRead (common for both pagination types)
        result = []
        for s in a2a_agents_db:
            try:
                s.team = team_map.get(s.team_id) if s.team_id else None
                result.append(self.convert_agent_to_read(s, include_metrics=False, db=db, team_map=team_map))
            except (ValidationError, ValueError, KeyError, TypeError, binascii.Error) as e:
                logger.exception(f"Failed to convert A2A agent {getattr(s, 'id', 'unknown')} ({getattr(s, 'name', 'unknown')}): {e}")
                # Continue with remaining agents instead of failing completely

        # Return appropriate format based on pagination type
        if page is not None:
            # Page-based format
            return {
                "data": result,
                "pagination": pag_result["pagination"],
                "links": pag_result["links"],
            }

        # Cursor-based format

        # ══════════════════════════════════════════════════════════════════════
        # CACHE WRITE: Only cache admin-level results (matches read guard)
        # MUST check token_teams is None to prevent caching scoped responses
        # ══════════════════════════════════════════════════════════════════════
        if cursor is None and user_email is None and token_teams is None:
            try:
                cache_data = {"agents": [s.model_dump(mode="json") for s in result], "next_cursor": next_cursor}
                await cache.set("agents", cache_data, filters_hash)
            except AttributeError:
                pass  # Skip caching if result objects don't support model_dump (e.g., in doctests)

        return (result, next_cursor)

    async def list_agents_for_user(
        self, db: Session, user_info: Dict[str, Any], team_id: Optional[str] = None, visibility: Optional[str] = None, include_inactive: bool = False, skip: int = 0, limit: int = 100
    ) -> List[A2AAgentRead]:
        """
        DEPRECATED: Use list_agents() with user_email parameter instead.

        This method is maintained for backward compatibility but is no longer used.
        New code should call list_agents() with user_email, team_id, and visibility parameters.

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

        # Batch fetch team names to avoid N+1 queries
        team_ids = list({a.team_id for a in agents if a.team_id})
        team_map = self._batch_get_team_names(db, team_ids)

        db.commit()  # Release transaction to avoid idle-in-transaction

        # Skip metrics to avoid N+1 queries in list operations
        result = []
        for agent in agents:
            try:
                result.append(self.convert_agent_to_read(agent, include_metrics=False, db=db, team_map=team_map))
            except (ValidationError, ValueError, KeyError, TypeError, binascii.Error) as e:
                logger.exception(f"Failed to convert A2A agent {getattr(agent, 'id', 'unknown')} ({getattr(agent, 'name', 'unknown')}): {e}")
                # Continue with remaining agents instead of failing completely

        return result

    async def get_agent(
        self,
        db: Session,
        agent_id: str,
        include_inactive: bool = True,
        user_email: Optional[str] = None,
        token_teams: Optional[List[str]] = None,
    ) -> A2AAgentRead:
        """Retrieve an A2A agent by ID.

        Args:
            db: Database session.
            agent_id: Agent ID.
            include_inactive: Whether to include inactive a2a agents.
            user_email: User's email for owner matching in visibility checks.
            token_teams: Teams from JWT token. None = admin (no filtering),
                         [] = public-only, [...] = team-scoped access.

        Returns:
            Agent data.

        Raises:
            A2AAgentNotFoundError: If the agent is not found or user lacks access.

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

            >>> # Mock convert_agent_to_read to simplify test
            >>> service.convert_agent_to_read = lambda db_agent, **kwargs: 'agent_read'

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

        if not agent.enabled and not include_inactive:
            raise A2AAgentNotFoundError(f"A2A Agent not found with ID: {agent_id}")

        # SECURITY: Check visibility/team access
        # Return 404 (not 403) to avoid leaking existence of private agents
        if not self._check_agent_access(agent, user_email, token_teams):
            raise A2AAgentNotFoundError(f"A2A Agent not found with ID: {agent_id}")

        # Delegate conversion and masking to convert_agent_to_read()
        return self.convert_agent_to_read(agent, db=db)

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

        return self.convert_agent_to_read(agent, db=db)

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
            ValueError: If query_param auth is disabled or host not in allowlist.
        """
        try:
            # Acquire row lock for update to avoid lost-update on `version` and other fields
            agent = get_for_update(db, DbA2AAgent, agent_id)

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
                    existing_agent = get_for_update(db, DbA2AAgent, where=and_(DbA2AAgent.slug == new_slug, DbA2AAgent.visibility == "public"))
                    if existing_agent:
                        raise A2AAgentNameConflictError(name=new_slug, is_active=existing_agent.enabled, agent_id=existing_agent.id, visibility=existing_agent.visibility)
                elif visibility.lower() == "team" and team_id:
                    # Check for existing team a2a agent with the same slug
                    existing_agent = get_for_update(db, DbA2AAgent, where=and_(DbA2AAgent.slug == new_slug, DbA2AAgent.visibility == "team", DbA2AAgent.team_id == team_id))
                    if existing_agent:
                        raise A2AAgentNameConflictError(name=new_slug, is_active=existing_agent.enabled, agent_id=existing_agent.id, visibility=existing_agent.visibility)
                # Update the slug when name changes
                agent.slug = new_slug
            # Update fields
            # Avoid `model_dump()` here: tests use `model_construct()` to create intentionally invalid
            # payloads, and `model_dump()` emits serializer warnings when encountering unexpected types.
            update_data = {field: getattr(agent_data, field) for field in agent_data.model_fields_set}

            # Track original auth_type and endpoint_url before updates
            original_auth_type = agent.auth_type
            original_endpoint_url = agent.endpoint_url

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

                # Skip query_param fields - handled separately below
                if field in ("auth_query_param_key", "auth_query_param_value"):
                    continue

                if hasattr(agent, field):
                    setattr(agent, field, value)

            # Handle query_param auth updates
            # Clear auth_query_params when switching away from query_param auth
            if original_auth_type == "query_param" and agent_data.auth_type is not None and agent_data.auth_type != "query_param":
                agent.auth_query_params = None
                logger.debug(f"Cleared auth_query_params for agent {agent.id} (switched from query_param to {agent_data.auth_type})")

            # Handle switching to query_param auth or updating existing query_param credentials
            is_switching_to_queryparam = agent_data.auth_type == "query_param" and original_auth_type != "query_param"
            is_updating_queryparam_creds = original_auth_type == "query_param" and (agent_data.auth_query_param_key is not None or agent_data.auth_query_param_value is not None)
            is_url_changing = agent_data.endpoint_url is not None and str(agent_data.endpoint_url) != original_endpoint_url

            if is_switching_to_queryparam or is_updating_queryparam_creds or (is_url_changing and original_auth_type == "query_param"):
                # Standard
                from urllib.parse import urlparse  # pylint: disable=import-outside-toplevel

                # First-Party
                from mcpgateway.config import settings  # pylint: disable=import-outside-toplevel

                # Service-layer enforcement: Check feature flag
                if not settings.insecure_allow_queryparam_auth:
                    # Grandfather clause: Allow updates to existing query_param agents
                    # unless they're trying to change credentials
                    if is_switching_to_queryparam or is_updating_queryparam_creds:
                        raise ValueError("Query parameter authentication is disabled. Set INSECURE_ALLOW_QUERYPARAM_AUTH=true to enable.")

                # Service-layer enforcement: Check host allowlist
                if settings.insecure_queryparam_auth_allowed_hosts:
                    check_url = str(agent_data.endpoint_url) if agent_data.endpoint_url else agent.endpoint_url
                    parsed = urlparse(check_url)
                    hostname = (parsed.hostname or "").lower()
                    allowed_hosts = [h.lower() for h in settings.insecure_queryparam_auth_allowed_hosts]
                    if hostname not in allowed_hosts:
                        allowed = ", ".join(settings.insecure_queryparam_auth_allowed_hosts)
                        raise ValueError(f"Host '{hostname}' is not in the allowed hosts for query param auth. " f"Allowed: {allowed}")

            if is_switching_to_queryparam or is_updating_queryparam_creds:
                # Get query param key and value
                param_key = getattr(agent_data, "auth_query_param_key", None)
                param_value = getattr(agent_data, "auth_query_param_value", None)

                # If no key provided but value is, reuse existing key (value-only rotation)
                existing_key = next(iter(agent.auth_query_params.keys()), None) if agent.auth_query_params else None
                if not param_key and param_value and existing_key:
                    param_key = existing_key

                if param_key:
                    # Check if value is masked (user didn't change it) or new value provided
                    is_masked_placeholder = False
                    if param_value and hasattr(param_value, "get_secret_value"):
                        raw_value = param_value.get_secret_value()
                        # First-Party
                        from mcpgateway.config import settings  # pylint: disable=import-outside-toplevel

                        is_masked_placeholder = raw_value == settings.masked_auth_value
                    elif param_value:
                        raw_value = str(param_value)
                    else:
                        raw_value = None

                    if raw_value and not is_masked_placeholder:
                        # New value provided - encrypt for storage
                        encrypted_value = encode_auth({param_key: raw_value})
                        agent.auth_query_params = {param_key: encrypted_value}
                    elif agent.auth_query_params and is_masked_placeholder:
                        # Use existing encrypted value (user didn't change the password)
                        # But key may have changed, so preserve with new key if different
                        if existing_key and existing_key != param_key:
                            # Key changed but value is masked - decrypt and re-encrypt with new key
                            existing_encrypted = agent.auth_query_params.get(existing_key, "")
                            if existing_encrypted:
                                decrypted = decode_auth(existing_encrypted)
                                existing_value = decrypted.get(existing_key, "")
                                if existing_value:
                                    encrypted_value = encode_auth({param_key: existing_value})
                                    agent.auth_query_params = {param_key: encrypted_value}

                # Update auth_type if switching
                if is_switching_to_queryparam:
                    agent.auth_type = "query_param"
                    agent.auth_value = None  # Query param auth doesn't use auth_value

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

            # Invalidate cache after successful update
            cache = _get_registry_cache()
            await cache.invalidate_agents()
            # Also invalidate tags cache since agent tags may have changed
            # First-Party
            from mcpgateway.cache.admin_stats_cache import admin_stats_cache  # pylint: disable=import-outside-toplevel

            await admin_stats_cache.invalidate_tags()

            # Update the associated tool if it exists
            # Wrap in try/except to handle tool sync failures gracefully - the agent
            # update is the primary operation and should succeed even if tool sync fails
            try:
                # First-Party
                from mcpgateway.services.tool_service import tool_service

                await tool_service.update_tool_from_a2a_agent(
                    db=db,
                    agent=agent,
                    modified_by=modified_by,
                    modified_from_ip=modified_from_ip,
                    modified_via=modified_via,
                    modified_user_agent=modified_user_agent,
                )
            except Exception as tool_err:
                logger.warning(f"Failed to sync tool for A2A agent {agent.id}: {tool_err}. Agent update succeeded but tool may be out of sync.")

            logger.info(f"Updated A2A agent: {agent.name} (ID: {agent.id})")
            return self.convert_agent_to_read(agent, db=db)
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

    async def set_agent_state(self, db: Session, agent_id: str, activate: bool, reachable: Optional[bool] = None, user_email: Optional[str] = None) -> A2AAgentRead:
        """Set the activation status of an A2A agent.

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

        # Invalidate caches since agent status changed
        a2a_stats_cache.invalidate()
        cache = _get_registry_cache()
        await cache.invalidate_agents()

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

        return self.convert_agent_to_read(agent, db=db)

    async def delete_agent(self, db: Session, agent_id: str, user_email: Optional[str] = None, purge_metrics: bool = False) -> None:
        """Delete an A2A agent.

        Args:
            db: Database session.
            agent_id: Agent ID.
            user_email: Email of user performing delete (for ownership check).
            purge_metrics: If True, delete raw + rollup metrics for this agent.

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

            # Delete the associated tool before deleting the agent
            # First-Party
            from mcpgateway.services.tool_service import tool_service

            await tool_service.delete_tool_from_a2a_agent(db=db, agent=agent, user_email=user_email, purge_metrics=purge_metrics)

            if purge_metrics:
                with pause_rollup_during_purge(reason=f"purge_a2a_agent:{agent_id}"):
                    delete_metrics_in_batches(db, A2AAgentMetric, A2AAgentMetric.a2a_agent_id, agent_id)
                    delete_metrics_in_batches(db, A2AAgentMetricsHourly, A2AAgentMetricsHourly.a2a_agent_id, agent_id)
            db.delete(agent)
            db.commit()

            # Invalidate caches since agent count changed
            a2a_stats_cache.invalidate()
            cache = _get_registry_cache()
            await cache.invalidate_agents()
            # Also invalidate tags cache since agent tags may have changed
            # First-Party
            from mcpgateway.cache.admin_stats_cache import admin_stats_cache  # pylint: disable=import-outside-toplevel

            await admin_stats_cache.invalidate_tags()

            logger.info(f"Deleted A2A agent: {agent_name} (ID: {agent_id})")

            structured_logger.log(
                level="INFO",
                message="A2A agent deleted",
                event_type="a2a_agent_deleted",
                component="a2a_service",
                user_email=user_email,
                resource_type="a2a_agent",
                resource_id=str(agent_id),
                custom_fields={
                    "agent_name": agent_name,
                    "purge_metrics": purge_metrics,
                },
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
        token_teams: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Invoke an A2A agent.

        Args:
            db: Database session.
            agent_name: Name of the agent to invoke.
            parameters: Parameters for the interaction.
            interaction_type: Type of interaction.
            user_id: Identifier of the user initiating the call.
            user_email: Email of the user initiating the call.
            token_teams: Teams from JWT token. None = admin (no filtering),
                         [] = public-only, [...] = team-scoped access.

        Returns:
            Agent response.

        Raises:
            A2AAgentNotFoundError: If the agent is not found or user lacks access.
            A2AAgentError: If the agent is disabled or invocation fails.
        """
        # ═══════════════════════════════════════════════════════════════════════════
        # PHASE 1: Acquire a short row lock to read `enabled` + `auth_value`,
        # then release the lock before performing the external HTTP call.
        # This avoids TOCTOU for the critical checks while not holding DB
        # connections during the potentially slow HTTP request.
        # ═══════════════════════════════════════════════════════════════════════════

        # Lookup the agent id, then lock the row by id using get_for_update
        agent_row = db.execute(select(DbA2AAgent.id).where(DbA2AAgent.name == agent_name)).scalar_one_or_none()
        if not agent_row:
            raise A2AAgentNotFoundError(f"A2A Agent not found with name: {agent_name}")

        agent = get_for_update(db, DbA2AAgent, agent_row)
        if not agent:
            raise A2AAgentNotFoundError(f"A2A Agent not found with name: {agent_name}")

        # ═══════════════════════════════════════════════════════════════════════════
        # SECURITY: Check visibility/team access WHILE ROW IS LOCKED
        # Return 404 (not 403) to avoid leaking existence of private agents
        # ═══════════════════════════════════════════════════════════════════════════
        if not self._check_agent_access(agent, user_email, token_teams):
            raise A2AAgentNotFoundError(f"A2A Agent not found with name: {agent_name}")

        if not agent.enabled:
            raise A2AAgentError(f"A2A Agent '{agent_name}' is disabled")

        # Extract all needed data to local variables before releasing DB connection
        agent_id = agent.id
        agent_endpoint_url = agent.endpoint_url
        agent_type = agent.agent_type
        agent_protocol_version = agent.protocol_version
        agent_auth_type = agent.auth_type
        agent_auth_value = agent.auth_value
        agent_auth_query_params = agent.auth_query_params

        # Handle query_param auth - decrypt and apply to URL
        auth_query_params_decrypted: Optional[Dict[str, str]] = None
        if agent_auth_type == "query_param" and agent_auth_query_params:
            # First-Party
            from mcpgateway.utils.url_auth import apply_query_param_auth  # pylint: disable=import-outside-toplevel

            auth_query_params_decrypted = {}
            for param_key, encrypted_value in agent_auth_query_params.items():
                if encrypted_value:
                    try:
                        decrypted = decode_auth(encrypted_value)
                        auth_query_params_decrypted[param_key] = decrypted.get(param_key, "")
                    except Exception:
                        logger.debug(f"Failed to decrypt query param '{param_key}' for A2A agent invocation")
            if auth_query_params_decrypted:
                agent_endpoint_url = apply_query_param_auth(agent_endpoint_url, auth_query_params_decrypted)

        # Decode auth_value for supported auth types (before closing session)
        auth_headers = {}
        if agent_auth_type in ("basic", "bearer", "authheaders") and agent_auth_value:
            # Decrypt auth_value and extract headers (follows gateway_service pattern)
            if isinstance(agent_auth_value, str):
                try:
                    auth_headers = decode_auth(agent_auth_value)
                except Exception as e:
                    raise A2AAgentError(f"Failed to decrypt authentication for agent '{agent_name}': {e}")
            elif isinstance(agent_auth_value, dict):
                auth_headers = {str(k): str(v) for k, v in agent_auth_value.items()}

        # ═══════════════════════════════════════════════════════════════════════════
        # CRITICAL: Release DB connection back to pool BEFORE making HTTP calls
        # This prevents connection pool exhaustion during slow upstream requests.
        # ═══════════════════════════════════════════════════════════════════════════
        db.commit()  # End read-only transaction cleanly (commit not rollback to avoid inflating rollback stats)
        db.close()

        start_time = datetime.now(timezone.utc)
        success = False
        error_message = None
        response = None

        # ═══════════════════════════════════════════════════════════════════════════
        # PHASE 2: Make HTTP call (no DB connection held)
        # ═══════════════════════════════════════════════════════════════════════════

        # Create sanitized URL for logging (redacts auth query params)
        # First-Party
        from mcpgateway.utils.url_auth import sanitize_exception_message, sanitize_url_for_logging  # pylint: disable=import-outside-toplevel

        sanitized_endpoint_url = sanitize_url_for_logging(agent_endpoint_url, auth_query_params_decrypted)

        try:
            # Prepare the request to the A2A agent
            # Format request based on agent type and endpoint
            if agent_type in ["generic", "jsonrpc"] or agent_endpoint_url.endswith("/"):
                # Use JSONRPC format for agents that expect it
                request_data = {"jsonrpc": "2.0", "method": parameters.get("method", "message/send"), "params": parameters.get("params", parameters), "id": 1}
            else:
                # Use custom A2A format
                request_data = {"interaction_type": interaction_type, "parameters": parameters, "protocol_version": agent_protocol_version}

            # Make HTTP request to the agent endpoint using shared HTTP client
            # First-Party
            from mcpgateway.services.http_client_service import get_http_client  # pylint: disable=import-outside-toplevel

            client = await get_http_client()
            headers = {"Content-Type": "application/json"}

            # Add authentication if configured (using decoded auth headers)
            headers.update(auth_headers)

            # Add correlation ID to outbound headers for distributed tracing
            correlation_id = get_correlation_id()
            if correlation_id:
                headers["X-Correlation-ID"] = correlation_id

            # Log A2A external call start (with sanitized URL to prevent credential leakage)
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
                    "agent_id": agent_id,
                    "endpoint_url": sanitized_endpoint_url,
                    "interaction_type": interaction_type,
                    "protocol_version": agent_protocol_version,
                },
            )

            http_response = await client.post(agent_endpoint_url, json=request_data, headers=headers)
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
                    metadata={"event": "a2a_call_completed", "agent_name": agent_name, "agent_id": agent_id, "status_code": http_response.status_code, "success": True},
                )
            else:
                # Sanitize error message to prevent URL secrets from leaking in logs
                raw_error = f"HTTP {http_response.status_code}: {http_response.text}"
                error_message = sanitize_exception_message(raw_error, auth_query_params_decrypted)

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
                    metadata={"event": "a2a_call_failed", "agent_name": agent_name, "agent_id": agent_id, "status_code": http_response.status_code},
                )

                raise A2AAgentError(error_message)

        except A2AAgentError:
            # Re-raise A2AAgentError without wrapping
            raise
        except Exception as e:
            # Sanitize error message to prevent URL secrets from leaking in logs
            error_message = sanitize_exception_message(str(e), auth_query_params_decrypted)
            logger.error(f"Failed to invoke A2A agent '{agent_name}': {error_message}")
            raise A2AAgentError(f"Failed to invoke A2A agent: {error_message}")

        finally:
            # ═══════════════════════════════════════════════════════════════════════════
            # PHASE 3: Record metrics via buffered service (batches writes for performance)
            # ═══════════════════════════════════════════════════════════════════════════
            end_time = datetime.now(timezone.utc)
            response_time = (end_time - start_time).total_seconds()

            try:
                # First-Party
                from mcpgateway.services.metrics_buffer_service import get_metrics_buffer_service  # pylint: disable=import-outside-toplevel

                metrics_buffer = get_metrics_buffer_service()
                metrics_buffer.record_a2a_agent_metric_with_duration(
                    a2a_agent_id=agent_id,
                    response_time=response_time,
                    success=success,
                    interaction_type=interaction_type,
                    error_message=error_message,
                )
            except Exception as metrics_error:
                logger.warning(f"Failed to record A2A metrics for '{agent_name}': {metrics_error}")

            # Update last interaction timestamp (quick separate write)
            try:
                with fresh_db_session() as ts_db:
                    # Reacquire short lock and re-check enabled before writing
                    db_agent = get_for_update(ts_db, DbA2AAgent, agent_id)
                    if db_agent and getattr(db_agent, "enabled", False):
                        db_agent.last_interaction = end_time
                        ts_db.commit()
            except Exception as ts_error:
                logger.warning(f"Failed to update last_interaction for '{agent_name}': {ts_error}")

        return response or {"error": error_message}

    async def aggregate_metrics(self, db: Session) -> Dict[str, Any]:
        """Aggregate metrics for all A2A agents.

        Combines recent raw metrics (within retention period) with historical
        hourly rollups for complete historical coverage. Uses in-memory caching
        (10s TTL) to reduce database load under high request rates.

        Args:
            db: Database session.

        Returns:
            Aggregated metrics from raw + hourly rollup tables.
        """
        # Check cache first (if enabled)
        # First-Party
        from mcpgateway.cache.metrics_cache import is_cache_enabled, metrics_cache  # pylint: disable=import-outside-toplevel

        if is_cache_enabled():
            cached = metrics_cache.get("a2a")
            if cached is not None:
                return cached

        # Get total/active agent counts from cache (avoids 2 COUNT queries per call)
        counts = a2a_stats_cache.get_counts(db)
        total_agents = counts["total"]
        active_agents = counts["active"]

        # Use combined raw + rollup query for full historical coverage
        # First-Party
        from mcpgateway.services.metrics_query_service import aggregate_metrics_combined  # pylint: disable=import-outside-toplevel

        result = aggregate_metrics_combined(db, "a2a_agent")

        total_interactions = result.total_executions
        successful_interactions = result.successful_executions
        failed_interactions = result.failed_executions

        metrics = {
            "total_agents": total_agents,
            "active_agents": active_agents,
            "total_interactions": total_interactions,
            "successful_interactions": successful_interactions,
            "failed_interactions": failed_interactions,
            "success_rate": (successful_interactions / total_interactions * 100) if total_interactions > 0 else 0.0,
            "avg_response_time": float(result.avg_response_time or 0.0),
            "min_response_time": float(result.min_response_time or 0.0),
            "max_response_time": float(result.max_response_time or 0.0),
        }

        # Cache the result (if enabled)
        if is_cache_enabled():
            metrics_cache.set("a2a", metrics)

        return metrics

    async def reset_metrics(self, db: Session, agent_id: Optional[str] = None) -> None:
        """Reset metrics for agents (raw + hourly rollups).

        Args:
            db: Database session.
            agent_id: Optional agent ID to reset metrics for specific agent.
        """
        if agent_id:
            db.execute(delete(A2AAgentMetric).where(A2AAgentMetric.a2a_agent_id == agent_id))
            db.execute(delete(A2AAgentMetricsHourly).where(A2AAgentMetricsHourly.a2a_agent_id == agent_id))
        else:
            db.execute(delete(A2AAgentMetric))
            db.execute(delete(A2AAgentMetricsHourly))
        db.commit()

        # Invalidate metrics cache
        # First-Party
        from mcpgateway.cache.metrics_cache import metrics_cache  # pylint: disable=import-outside-toplevel

        metrics_cache.invalidate("a2a")

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

    def convert_agent_to_read(self, db_agent: DbA2AAgent, include_metrics: bool = False, db: Optional[Session] = None, team_map: Optional[Dict[str, str]] = None) -> A2AAgentRead:
        """Convert database model to schema.

        Args:
            db_agent (DbA2AAgent): Database agent model.
            include_metrics (bool): Whether to include metrics in the result. Defaults to False.
                Set to False for list operations to avoid N+1 query issues.
            db (Optional[Session]): Database session. Only required if team name is not pre-populated
                on the db_agent object and team_map is not provided.
            team_map (Optional[Dict[str, str]]): Pre-fetched team_id -> team_name mapping.
                If provided, avoids N+1 queries for team name lookups in list operations.

        Returns:
            A2AAgentRead: Agent read schema.

        Raises:
            A2AAgentNotFoundError: If the provided agent is not found or invalid.

        """

        if not db_agent:
            raise A2AAgentNotFoundError("Agent not found")

        # Check if team attribute already exists (pre-populated in batch operations)
        # Otherwise use pre-fetched team map if available, otherwise query individually
        if not hasattr(db_agent, "team") or db_agent.team is None:
            team_id = getattr(db_agent, "team_id", None)
            if team_map is not None and team_id:
                team_name = team_map.get(team_id)
            elif db is not None:
                team_name = self._get_team_name(db, team_id)
            else:
                team_name = None
            setattr(db_agent, "team", team_name)

        # Compute metrics only if requested (avoids N+1 queries in list operations)
        if include_metrics:
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
        else:
            metrics = None

        # Build dict from ORM model
        agent_data = {k: getattr(db_agent, k, None) for k in A2AAgentRead.model_fields.keys()}
        agent_data["metrics"] = metrics
        agent_data["team"] = getattr(db_agent, "team", None)
        # Include auth_query_params for the _mask_query_param_auth validator
        agent_data["auth_query_params"] = getattr(db_agent, "auth_query_params", None)

        # Validate using Pydantic model
        validated_agent = A2AAgentRead.model_validate(agent_data)

        # Return masked version (like GatewayRead)
        return validated_agent.masked()
