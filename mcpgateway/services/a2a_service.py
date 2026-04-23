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
import json
from typing import Any, AsyncGenerator, Dict, List, Optional, Union
from urllib.parse import quote, urlparse

# Third-Party
import httpx
from pydantic import ValidationError
from sqlalchemy import and_, delete, desc, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.cache.a2a_stats_cache import a2a_stats_cache
from mcpgateway.config import settings
from mcpgateway.db import A2AAgent as DbA2AAgent
from mcpgateway.db import A2AAgentMetric, A2AAgentMetricsHourly, A2ATask, EmailTeam
from mcpgateway.db import EmailTeamMember as DbEmailTeamMember
from mcpgateway.db import fresh_db_session, get_for_update
from mcpgateway.db import Tool as DbTool
from mcpgateway.observability import create_span, set_span_attribute, set_span_error
from mcpgateway.schemas import A2AAgentAggregateMetrics, A2AAgentCreate, A2AAgentMetrics, A2AAgentRead, A2AAgentUpdate
from mcpgateway.services.a2a_protocol import prepare_a2a_invocation
from mcpgateway.services.base_service import BaseService
from mcpgateway.services.encryption_service import protect_oauth_config_for_storage
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.metrics_cleanup_service import delete_metrics_in_batches, pause_rollup_during_purge
from mcpgateway.services.rust_a2a_runtime import get_rust_a2a_runtime_client, RustA2ARuntimeError
from mcpgateway.services.structured_logger import get_structured_logger
from mcpgateway.services.team_management_service import TeamManagementService
from mcpgateway.utils.correlation_id import get_correlation_id
from mcpgateway.utils.create_slug import slugify
from mcpgateway.utils.pagination import unified_paginate
from mcpgateway.utils.services_auth import decode_auth, encode_auth
from mcpgateway.utils.sqlalchemy_modifier import json_contains_tag_expr
from mcpgateway.utils.trace_redaction import is_input_capture_enabled, is_output_capture_enabled, serialize_trace_payload

# Cache import (lazy to avoid circular dependencies)
_REGISTRY_CACHE = None
_TOOL_LOOKUP_CACHE = None


def _should_delegate_a2a_to_rust() -> bool:
    """Return whether A2A invocations should be delegated to the Rust runtime.

    Lazy import of ``mcpgateway.version`` avoids the circular import between
    ``mcpgateway.services`` package init and ``mcpgateway.version``.

    Returns:
        ``True`` when the Rust A2A runtime should service invocations.
    """
    # First-Party
    from mcpgateway.version import should_delegate_a2a_to_rust  # pylint: disable=import-outside-toplevel

    return should_delegate_a2a_to_rust()


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


def _get_tool_lookup_cache():
    """Get tool lookup cache singleton lazily.

    Returns:
        ToolLookupCache instance.
    """
    global _TOOL_LOOKUP_CACHE  # pylint: disable=global-statement
    if _TOOL_LOOKUP_CACHE is None:
        # First-Party
        from mcpgateway.cache.tool_lookup_cache import tool_lookup_cache  # pylint: disable=import-outside-toplevel

        _TOOL_LOOKUP_CACHE = tool_lookup_cache
    return _TOOL_LOOKUP_CACHE


# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

# Initialize structured logger for A2A lifecycle tracking
structured_logger = get_structured_logger("a2a_service")

# Flag to track if we've logged the cross-gateway authentication warning (log once per process)
_cross_gateway_auth_warning_logged = False


async def _publish_a2a_invalidation(message_type: str, **kwargs: Any) -> None:
    """Publish a cache invalidation message to Redis for Rust L1 eviction."""
    try:
        # First-Party
        from mcpgateway.utils.redis_client import get_redis_client  # pylint: disable=import-outside-toplevel

        redis = await get_redis_client()
        if redis is None:
            return
        # Third-Party
        import orjson  # pylint: disable=import-outside-toplevel

        payload = orjson.dumps({"type": message_type, **kwargs}).decode()
        await redis.publish("mcpgw:a2a:invalidate", payload)
    except Exception as e:
        logger.warning("Failed to publish A2A cache invalidation: %s", e)


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


def _validate_a2a_team_assignment(db: Session, user_email: Optional[str], target_team_id: Optional[str]) -> None:
    """Validate team assignment for A2A agent updates.

    Args:
        db: Database session used for membership checks.
        user_email: Requesting user email. When omitted, ownership checks are skipped.
        target_team_id: Team identifier to validate.

    Raises:
        ValueError: If team does not exist or caller lacks ownership.
    """
    if not target_team_id:
        raise ValueError("Cannot set visibility to 'team' without a team_id")

    team = db.query(EmailTeam).filter(EmailTeam.id == target_team_id).first()
    if not team:
        raise ValueError(f"Team {target_team_id} not found")

    if not user_email:
        return

    membership = (
        db.query(DbEmailTeamMember)
        .filter(DbEmailTeamMember.team_id == target_team_id, DbEmailTeamMember.user_email == user_email, DbEmailTeamMember.is_active, DbEmailTeamMember.role == "owner")
        .first()
    )
    if not membership:
        raise ValueError("User membership in team not sufficient for this update.")


class A2AAgentService(BaseService):
    """Service for managing A2A agents in the gateway.

    Provides methods to create, list, retrieve, update, set state, and delete agent records.
    Also supports interactions with A2A-compatible agents.
    """

    _visibility_model_cls = DbA2AAgent

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
        - public visibility: Always allowed
        - token_teams is None AND user_email is None: Admin bypass (unrestricted access)
        - No user context (but not admin): Deny access to non-public agents
        - team visibility: Allowed if agent.team_id in token_teams
        - private visibility: Allowed if owner (requires user_email and non-empty token_teams)

        Args:
            agent: The agent to check access for
            user_email: User's email for owner matching
            token_teams: Teams from JWT. None = admin bypass, [] = public-only (no owner access)

        Returns:
            True if access allowed, False otherwise.
        """
        # Public agents are accessible by everyone
        if agent.visibility == "public":
            return True

        # Admin bypass: token_teams=None AND user_email=None means unrestricted admin
        # This happens when is_admin=True and no team scoping in token
        if token_teams is None and user_email is None:
            return True

        # No user context (but not admin) = deny access to non-public agents
        if not user_email:
            return False

        # Public-only tokens (empty teams array) can ONLY access public agents
        is_public_only_token = token_teams is not None and len(token_teams) == 0
        if is_public_only_token:
            return False  # Already checked public above

        # Owner can access their own private agents
        if agent.visibility == "private" and agent.owner_email and agent.owner_email == user_email:
            return True

        # Team agents: check team membership
        # token_teams=None means admin bypass — allow all team agents
        # ([] already handled by public-only check above)
        if agent.visibility == "team":
            if token_teams is None:
                return True
            return agent.team_id in token_teams

        return False

    def _visible_agent_ids(
        self,
        db: Session,
        user_email: Optional[str],
        token_teams: Optional[List[str]],
    ) -> Optional[List[str]]:
        """Return IDs of agents visible to the caller, or None for admin bypass.

        Used by list_tasks to scope results to agents the caller can see.
        Returns None when the caller has unrestricted (admin) access.
        Pushes visibility filtering into SQL to avoid loading all agents.

        Note: admin bypass here requires BOTH token_teams=None AND
        user_email=None.  When token_teams=None but user_email is set
        (admin with email context), the query runs but includes all
        team-scoped agents — this is intentionally more restrictive than
        _check_agent_access's admin bypass to prevent list_tasks from
        returning private agents owned by other users.
        """
        # Admin bypass — only when both are unset (pure admin, no email context)
        if token_teams is None and user_email is None:
            return None

        query = db.query(DbA2AAgent.id).filter(DbA2AAgent.enabled.is_(True))

        # Build visibility predicate matching _check_agent_access rules.
        visibility_filters = [DbA2AAgent.visibility == "public"]

        is_public_only = not user_email or (token_teams is not None and len(token_teams) == 0)
        if not is_public_only:
            if token_teams is not None and len(token_teams) > 0:
                visibility_filters.append(and_(DbA2AAgent.visibility == "team", DbA2AAgent.team_id.in_(token_teams)))
            elif token_teams is None:
                # token_teams is None with user_email set → admin with email context
                visibility_filters.append(DbA2AAgent.visibility == "team")
            visibility_filters.append(and_(DbA2AAgent.visibility == "private", DbA2AAgent.owner_email == user_email))

        query = query.filter(or_(*visibility_filters))
        return [row[0] for row in query.all()]

    def _check_agent_access_by_id(
        self,
        db: Session,
        agent_id: str,
        user_email: Optional[str],
        token_teams: Optional[List[str]],
    ) -> bool:
        """Check if the caller can access the agent identified by ``agent_id``.

        Returns False when the agent does not exist (fail-closed: orphaned
        records from deleted agents are not universally accessible).
        """
        agent = db.query(DbA2AAgent).filter(DbA2AAgent.id == agent_id).first()
        if agent is None:
            return False
        return self._check_agent_access(agent, user_email, token_teams)

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
        with create_span(
            "a2a.register",
            {
                "a2a.agent.name": agent_data.name,
                "a2a.agent.type": agent_data.agent_type,
                "created_by": created_by,
                "team_id": team_id,
                "visibility": visibility,
            },
        ) as span:
            try:
                agent_data.slug = slugify(agent_data.name)
                # Check for existing server with the same slug within the same team or public scope
                if visibility.lower() == "public":
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
                auth_value = getattr(agent_data, "auth_value", {})

                if hasattr(agent_data, "auth_headers") and agent_data.auth_headers:
                    header_dict = {h["key"]: h["value"] for h in agent_data.auth_headers if h.get("key")}
                    auth_value = encode_auth(header_dict)

                oauth_config = await protect_oauth_config_for_storage(getattr(agent_data, "oauth_config", None))

                # Handle query_param auth - encrypt and prepare for storage
                auth_query_params_encrypted: Optional[Dict[str, str]] = None
                if auth_type == "query_param":
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

                # Generate UAID if requested
                uaid_metadata: Dict[str, Optional[str]] = {}

                if getattr(agent_data, "generate_uaid", False):
                    # First-Party
                    from mcpgateway.utils.uaid import generate_uaid  # pylint: disable=import-outside-toplevel

                    try:
                        uaid = generate_uaid(
                            registry=getattr(agent_data, "uaid_registry", None) or "context-forge",
                            name=agent_data.name,
                            version=getattr(agent_data, "version", None) or "1.0.0",
                            protocol=getattr(agent_data, "uaid_protocol", None) or "a2a",
                            native_id=agent_data.endpoint_url,
                            skills=getattr(agent_data, "uaid_skills", None) or [],
                        )

                        # Store UAID in separate field, keep UUID for id (optimal indexing and URL routing)
                        uaid_metadata = {
                            "uaid": uaid,
                            "uaid_registry": getattr(agent_data, "uaid_registry", None) or "context-forge",
                            "uaid_proto": getattr(agent_data, "uaid_protocol", None) or "a2a",
                            "uaid_native_id": agent_data.endpoint_url,
                        }
                        logger.info(f"Generated UAID for agent {agent_data.name}: {uaid!r}")
                    except Exception as uaid_error:
                        logger.warning(f"Failed to generate UAID for agent {agent_data.name}: {uaid_error}. Falling back to UUID only.")
                        uaid_metadata = {}

                # Create new agent (id will be auto-generated as UUID)
                new_agent = DbA2AAgent(
                    name=agent_data.name,
                    **uaid_metadata,  # Add UAID fields if generated
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
                    # Team scoping fields - always use server-derived values to prevent
                    # clients from overriding ownership via request body fields.
                    team_id=team_id,
                    owner_email=owner_email or created_by,
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

                try:
                    # Standard
                    import asyncio  # pylint: disable=import-outside-toplevel

                    loop = asyncio.get_running_loop()
                    loop.create_task(_publish_a2a_invalidation("agent", name=new_agent.name))
                except RuntimeError:
                    pass  # No running event loop (e.g., in tests)
                except Exception as exc:
                    # Best-effort, but log so a Redis outage stops being
                    # invisible — stale Rust L1 caches silently serve old
                    # agent data until TTL expires.
                    logger.warning("Rust-cache invalidation scheduling failed for agent %s: %s", new_agent.name, exc)

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

                if span:
                    set_span_attribute(span, "success", True)
                    set_span_attribute(span, "a2a.agent.id", str(new_agent.id))
                return self.convert_agent_to_read(new_agent, db=db)

            except A2AAgentNameConflictError as ie:
                set_span_error(span, ie)
                db.rollback()
                raise ie
            except IntegrityError as ie:
                set_span_error(span, ie)
                db.rollback()
                logger.error(f"IntegrityErrors in group: {ie}")
                raise ie
            except ValueError as ve:
                set_span_error(span, ve)
                raise ve
            except Exception as e:
                set_span_error(span, e)
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
            filters_hash = cache.hash_filters(include_inactive=include_inactive, tags=sorted(tags) if tags else None, visibility=visibility)
            cached = await cache.get("agents", filters_hash)
            if cached is not None:
                # Reconstruct A2AAgentRead objects from cached dicts
                cached_agents = [A2AAgentRead.model_validate(a).masked() for a in cached["agents"]]
                return (cached_agents, cached.get("next_cursor"))

        # Build base query with ordering
        query = select(DbA2AAgent).order_by(desc(DbA2AAgent.created_at), desc(DbA2AAgent.id))

        # Apply active/inactive filter
        if not include_inactive:
            query = query.where(DbA2AAgent.enabled)

        query = await self._apply_access_control(query, db, user_email, token_teams, team_id)

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
        query = select(DbA2AAgent).where(DbA2AAgent.name == agent_name)  # pylint: disable=comparison-with-callable
        agent = db.execute(query).scalar_one_or_none()

        if not agent:
            raise A2AAgentNotFoundError(f"A2A Agent not found with name: {agent_name}")

        return self.convert_agent_to_read(agent, db=db)

    def get_agent_card(self, db: Session, agent_name: str) -> Optional[Dict[str, Any]]:
        """Build an A2A v1 AgentCard dict for the named agent.

        Queries the database for an enabled agent with the given name and
        returns a dict that conforms to the A2A AgentCard schema.  Returns
        None when no matching enabled agent is found.

        Args:
            db: Database session.
            agent_name: Name of the agent to look up.

        Returns:
            AgentCard dict, or None if the agent is not found / disabled.

        Examples:
            >>> from unittest.mock import MagicMock
            >>> from mcpgateway.services.a2a_service import A2AAgentService
            >>> service = A2AAgentService()
            >>> db = MagicMock()
            >>> db.execute.return_value.scalar_one_or_none.return_value = None
            >>> service.get_agent_card(db, "missing") is None
            True
        """
        query = select(DbA2AAgent).where(DbA2AAgent.name == agent_name, DbA2AAgent.enabled.is_(True))
        agent = db.execute(query).scalar_one_or_none()
        if not agent:
            return None

        capabilities = agent.capabilities or {}

        card: Dict[str, Any] = {
            "name": agent.name,
            "description": agent.description or "",
            "url": agent.endpoint_url,
            "version": str(agent.version),
            "protocolVersion": agent.protocol_version,
            "defaultInputModes": ["text"],
            "defaultOutputModes": ["text"],
            "capabilities": {
                "streaming": bool(capabilities.get("streaming", False)),
                "pushNotifications": bool(capabilities.get("pushNotifications", False)),
                "stateTransitionHistory": bool(capabilities.get("stateTransitionHistory", False)),
            },
            "skills": capabilities.get("skills", []),
            "supportsAuthenticatedExtendedCard": True,
        }
        return card

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

                # auth_headers is on the schema but not the DB model; translate
                # it into auth_value, preserving masked placeholders from the
                # existing encrypted value so an unchanged edit does not
                # overwrite real credentials with the mask string.
                if field == "auth_headers" and value and isinstance(value, list):
                    existing_auth_raw = getattr(agent, "auth_value", None)
                    existing_auth: Dict[str, str] = {}
                    if isinstance(existing_auth_raw, str):
                        try:
                            existing_auth = decode_auth(existing_auth_raw)
                        except Exception:
                            logger.warning("Failed to decrypt existing auth_value for agent %s — preserving raw value", getattr(agent, "id", "?"))
                            existing_auth = {}
                    elif isinstance(existing_auth_raw, dict):
                        existing_auth = existing_auth_raw

                    header_dict: Dict[str, str] = {}
                    for header in value:
                        key = header.get("key")
                        if not key:
                            continue
                        hval = header.get("value", "")
                        if hval == settings.masked_auth_value and key in existing_auth:
                            header_dict[key] = existing_auth[key]
                        else:
                            header_dict[key] = hval

                    if header_dict:
                        agent.auth_value = encode_auth(header_dict)
                    continue

                if field == "oauth_config":
                    value = await protect_oauth_config_for_storage(value, existing_oauth_config=agent.oauth_config)

                # Validate team reassignment before persisting
                if field == "team_id" and value is not None and value != agent.team_id:
                    _validate_a2a_team_assignment(db, user_email, value)

                # Validate visibility transition to "team"
                if field == "visibility" and value == "team":
                    target_team_id = update_data.get("team_id", agent.team_id) if "team_id" in update_data else agent.team_id
                    _validate_a2a_team_assignment(db, user_email, target_team_id)

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

            # Generate UAID if requested and agent doesn't already have one (UAID is immutable)
            if getattr(agent_data, "generate_uaid", False) and not agent.uaid:
                # First-Party
                from mcpgateway.utils.uaid import generate_uaid  # pylint: disable=import-outside-toplevel

                try:
                    uaid = generate_uaid(
                        registry=getattr(agent_data, "uaid_registry", None) or "context-forge",
                        name=agent.name,  # Use current agent name
                        version=getattr(agent_data, "version", None) or "1.0.0",
                        protocol=getattr(agent_data, "uaid_protocol", None) or "a2a",
                        native_id=agent.endpoint_url,  # Use current endpoint_url
                        skills=[],  # Empty skills list for now
                    )

                    # Populate UAID fields (immutable once set)
                    agent.uaid = uaid
                    agent.uaid_registry = getattr(agent_data, "uaid_registry", None) or "context-forge"
                    agent.uaid_proto = getattr(agent_data, "uaid_protocol", None) or "a2a"
                    agent.uaid_native_id = agent.endpoint_url

                    logger.info(f"Generated UAID for existing agent {agent.name} (ID: {agent.id}): {uaid!r}")
                except Exception as uaid_error:
                    logger.warning(f"Failed to generate UAID for agent {agent.name}: {uaid_error}. Continuing without UAID.")

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

            try:
                # Standard
                import asyncio  # pylint: disable=import-outside-toplevel

                loop = asyncio.get_running_loop()
                loop.create_task(_publish_a2a_invalidation("agent", name=agent.name))
            except RuntimeError:
                pass  # No running event loop (e.g., in tests)
            except Exception as exc:
                logger.warning("Rust-cache invalidation scheduling failed for agent %s: %s", agent.name, exc)

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
        with create_span(
            "a2a.state_change",
            {
                "a2a.agent.id": agent_id,
                "a2a.agent.activate": activate,
                "user.email": user_email,
            },
        ) as span:
            try:
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

                # Cascade: update associated tool's enabled status to match agent.
                # This mirrors gateway_service.set_gateway_state() which lets cascade
                # failures propagate so the caller knows the operation was incomplete.
                if agent.tool_id:
                    now = datetime.now(timezone.utc)
                    tool_result = db.execute(update(DbTool).where(DbTool.id == agent.tool_id).where(DbTool.enabled != activate).values(enabled=activate, updated_at=now))
                    if tool_result.rowcount > 0:
                        db.commit()
                        await cache.invalidate_tools()
                        tool_lookup_cache = _get_tool_lookup_cache()
                        if agent.tool and agent.tool.name:
                            await tool_lookup_cache.invalidate(agent.tool.name, gateway_id=str(agent.tool.gateway_id) if agent.tool.gateway_id else None)

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

                result = self.convert_agent_to_read(agent, db=db)
                if span:
                    set_span_attribute(span, "success", True)
                return result
            except Exception as exc:
                set_span_error(span, exc)
                raise

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
        with create_span(
            "a2a.delete",
            {
                "a2a.agent.id": agent_id,
                "user.email": user_email,
                "purge_metrics": purge_metrics,
            },
        ) as span:
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

                try:
                    # Standard
                    import asyncio  # pylint: disable=import-outside-toplevel

                    loop = asyncio.get_running_loop()
                    loop.create_task(_publish_a2a_invalidation("agent", name=agent_name))
                except RuntimeError:
                    pass  # No running event loop (e.g., in tests)
                except Exception as exc:
                    logger.warning("Rust-cache invalidation scheduling failed for agent %s: %s", agent_name, exc)

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
                if span:
                    set_span_attribute(span, "success", True)
            except PermissionError:
                if span:
                    set_span_attribute(span, "error", True)
                db.rollback()
                raise

    async def invoke_agent(
        self,
        db: Session,
        agent_name: str,
        parameters: Dict[str, Any],
        interaction_type: str = "query",
        *,
        agent_id: Optional[str] = None,
        user_id: Optional[str] = None,
        user_email: Optional[str] = None,
        token_teams: Optional[List[str]] = None,
        hop_count: int = 0,
    ) -> Dict[str, Any]:
        """Invoke an A2A agent by name or ID (UUID/UAID).

        Args:
            db: Database session.
            agent_name: Name of the agent to invoke.
            parameters: Parameters for the interaction.
            interaction_type: Type of interaction.
            agent_id: Optional agent ID (UUID or UAID format). If provided, takes precedence over agent_name.
            user_id: Identifier of the user initiating the call.
            user_email: Email of the user initiating the call.
            token_teams: Teams from JWT token. None = admin (no filtering),
                         [] = public-only, [...] = team-scoped access.
            hop_count: Federation hop counter from the inbound
                `X-Contextforge-UAID-Hop` header. Calls at or above
                `settings.uaid_max_federation_hops` are rejected to break
                UAID cross-gateway loops (A->B->A and self-referential
                `endpoint_url`). Outbound calls stamp `hop_count + 1`.

        Returns:
            Agent response.

        Raises:
            A2AAgentNotFoundError: If the agent is not found or user lacks access.
            A2AAgentError: If the agent is disabled or invocation fails.
        """
        # Use agent_id if provided, otherwise use agent_name
        identifier = agent_id if agent_id else agent_name
        is_name_lookup = bool(not agent_id and agent_name)

        # ═══════════════════════════════════════════════════════════════════════════
        # FEDERATION LOOP GUARD
        # ═══════════════════════════════════════════════════════════════════════════
        # Every outbound cross-gateway invocation stamps
        # `X-Contextforge-UAID-Hop: N+1` on its request headers.  The entry
        # handler reads the header and forwards the integer here.  If we've
        # already traversed `uaid_max_federation_hops` hops, refuse.  This
        # check catches BOTH:
        #   (a) A→B→A style federation ping-pong (nativeId of a missing
        #       UAID points back at a peer that doesn't own it), and
        #   (b) self-referential `endpoint_url` loops where a locally-
        #       registered agent's endpoint routes right back into this
        #       handler.  A binary "is-federated" marker would miss (b)
        #       because the UAID still resolves locally on every hop.
        max_hops = settings.uaid_max_federation_hops
        if hop_count >= max_hops:
            logger.warning(
                "UAID federation hop limit reached: hop_count=%d >= max=%d for identifier %r",
                hop_count,
                max_hops,
                identifier,
            )
            raise A2AAgentNotFoundError(f"A2A Agent not found (federation hop limit reached): {identifier}")

        # ═══════════════════════════════════════════════════════════════════════════
        # UAID HANDLING: Check if identifier is UAID format
        # ═══════════════════════════════════════════════════════════════════════════
        # First-Party
        from mcpgateway.utils.uaid import is_uaid  # pylint: disable=import-outside-toplevel

        if is_uaid(identifier):
            # Try local lookup first (by id or uaid column)
            agent_row = db.execute(select(DbA2AAgent.id).where((DbA2AAgent.id == identifier) | (DbA2AAgent.uaid == identifier))).scalar_one_or_none()

            if not agent_row:
                # Not found locally — attempt cross-gateway routing.
                # Hop-count enforcement above already rejected requests
                # that came in at the limit, so this path is safe.
                logger.info(f"UAID agent not found locally, attempting cross-gateway routing: {identifier!r}")
                return await self._invoke_remote_agent(
                    uaid=identifier,
                    parameters=parameters,
                    interaction_type=interaction_type,
                    user_id=user_id,
                    user_email=user_email,
                    token_teams=token_teams,
                    hop_count=hop_count,
                )

            # Found locally - continue with normal invocation
            identifier = agent_row  # Use the actual ID for lookup
            is_name_lookup = False

        # ═══════════════════════════════════════════════════════════════════════════
        # PHASE 1: Acquire a short row lock to read `enabled` + `auth_value`,
        # then release the lock before performing the external HTTP call.
        # This avoids TOCTOU for the critical checks while not holding DB
        # connections during the potentially slow HTTP request.
        # ═══════════════════════════════════════════════════════════════════════════

        # Lookup the agent id, then lock the row by id using get_for_update
        if is_name_lookup:
            agent_row = db.execute(select(DbA2AAgent.id).where(DbA2AAgent.name == identifier)).scalar_one_or_none()  # pylint: disable=comparison-with-callable
            if not agent_row:
                raise A2AAgentNotFoundError(f"A2A Agent not found with name: {identifier}")

            agent = get_for_update(db, DbA2AAgent, agent_row)
            if not agent:
                raise A2AAgentNotFoundError(f"A2A Agent not found with name: {identifier}")
        else:
            agent_row = identifier
            agent = get_for_update(db, DbA2AAgent, agent_row)
            if not agent:
                raise A2AAgentNotFoundError(f"A2A Agent not found: {identifier}")

        # Use agent name for logging throughout
        agent_name = agent.name

        # ═══════════════════════════════════════════════════════════════════════════
        # SECURITY: Check visibility/team access WHILE ROW IS LOCKED
        # Return 404 (not 403) to avoid leaking existence of private agents
        # ═══════════════════════════════════════════════════════════════════════════
        if not self._check_agent_access(agent, user_email, token_teams):
            if is_name_lookup:
                raise A2AAgentNotFoundError(f"A2A Agent not found with name: {identifier}")
            raise A2AAgentNotFoundError(f"A2A Agent not found: {identifier}")

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

        # First-Party
        from mcpgateway.utils.url_auth import sanitize_exception_message  # pylint: disable=import-outside-toplevel

        correlation_id = get_correlation_id()
        try:
            prepared = prepare_a2a_invocation(
                agent_type=agent_type,
                endpoint_url=agent_endpoint_url,
                protocol_version=agent_protocol_version,
                parameters=parameters,
                interaction_type=interaction_type,
                auth_type=agent_auth_type,
                auth_value=agent_auth_value,
                auth_query_params=agent_auth_query_params,
                correlation_id=correlation_id,
            )
        except Exception as e:
            if agent_auth_type in ("basic", "bearer", "authheaders") and agent_auth_value:
                raise A2AAgentError(f"Failed to decrypt authentication for agent '{agent_name}': {e}") from e
            if agent_auth_type == "query_param" and agent_auth_query_params:
                raise A2AAgentError(f"Failed to decrypt query_param authentication for agent '{agent_name}': {e}") from e
            raise A2AAgentError(f"Failed to prepare A2A invocation for agent '{agent_name}': {e}") from e

        span_attributes = {
            "a2a.agent.name": agent_name,
            "a2a.agent.id": str(agent_id),
            "a2a.agent.url": prepared.sanitized_endpoint_url,
            "a2a.agent.type": agent_type,
            "a2a.interaction_type": interaction_type,
        }
        if is_input_capture_enabled("a2a.invoke"):
            span_attributes["langfuse.observation.input"] = serialize_trace_payload(parameters or {})

        # Stamp the outbound hop counter when the target is a known CF
        # peer — a locally-registered agent whose `endpoint_url` points
        # back at this gateway (misconfiguration or attack) would
        # otherwise loop without limit; the hop guard at the top of
        # `invoke_agent` catches the re-entry once this header arrives.
        #
        # Stamping responsibility depends on who actually emits the
        # outbound HTTP request:
        #   - Non-delegate (Python emits): stamp N+1 via `stamp_hop`
        #     so the downstream sees the incremented value.
        #   - Delegate to Rust runtime: pass N as-is (the inbound
        #     value).  Rust's `handle_invoke` reads it, re-checks the
        #     guard, and emits N+1 itself.  If Python also stamped,
        #     the counter would advance twice per logical hop and the
        #     guard would trip `max_hops/2` levels deep — breaking
        #     legitimate federation chains.  Stamping is unconditional:
        #     gating on `uaid_allowed_domains` would skip the header on
        #     any gateway reached via a host alias missing from the
        #     allowlist, and that path self-loops without bound.  The
        #     header is a ContextForge-internal marker and is safe for
        #     third-party agents to receive (they ignore it).
        # First-Party
        from mcpgateway.utils import uaid as uaid_utils  # pylint: disable=import-outside-toplevel

        # Use `_should_delegate_a2a_to_rust()` (not the raw settings flags)
        # so this branch stays in lockstep with the dispatch decision below
        # (`if _should_delegate_a2a_to_rust(): ...`).  The helper also
        # honors the runtime-mutable `A2A_MODE` override introduced by
        # `mcpgateway.version`; reading raw flags here would desync the
        # hop-stamp contract from the dispatch contract when an operator
        # flips the mode at runtime (e.g., `PATCH /admin/runtime/a2a-mode
        # {mode: "shadow"}` while delegate flags are boot-true).  That
        # desync would let Python emit the HTTP POST while the header
        # was stamped for the Rust-delegate path — downstream gateways
        # would then trip the guard at half the configured depth.
        if _should_delegate_a2a_to_rust():
            prepared.headers[uaid_utils.HOP_HEADER] = str(hop_count)
        else:
            uaid_utils.stamp_hop(prepared.headers, hop_count)

        with create_span("a2a.invoke", span_attributes) as span:
            try:
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
                        "endpoint_url": prepared.sanitized_endpoint_url,
                        "interaction_type": interaction_type,
                        "protocol_version": agent_protocol_version,
                        "runtime": "rust" if _should_delegate_a2a_to_rust() else "python",
                    },
                )

                if _should_delegate_a2a_to_rust():
                    runtime_response = await get_rust_a2a_runtime_client().invoke(
                        prepared,
                        timeout_seconds=int(settings.mcpgateway_a2a_default_timeout),
                    )
                    status_code = int(runtime_response.get("status_code", 200))
                    response_json = runtime_response.get("json")
                    response_text = str(runtime_response.get("text") or "")
                else:
                    # Make HTTP request to the agent endpoint using shared HTTP client
                    # First-Party
                    from mcpgateway.services.http_client_service import get_http_client  # pylint: disable=import-outside-toplevel

                    client = await get_http_client()
                    http_response = await client.post(prepared.endpoint_url, json=prepared.request_data, headers=prepared.headers)
                    status_code = http_response.status_code
                    response_json = http_response.json() if status_code == 200 else None
                    response_text = http_response.text

                call_duration_ms = (datetime.now(timezone.utc) - call_start_time).total_seconds() * 1000

                if status_code == 200:
                    response = response_json if response_json is not None else {"response": response_text}
                    success = True
                    if span and is_output_capture_enabled("a2a.invoke"):
                        set_span_attribute(span, "langfuse.observation.output", serialize_trace_payload(response))

                    # Persist task state so GetTask/ListTasks/CancelTask have data.
                    # The response may contain a task object (with id/status) or a
                    # JSON-RPC result wrapping one.
                    try:
                        task_data = response
                        if isinstance(task_data, dict) and "result" in task_data:
                            task_data = task_data["result"]
                        if isinstance(task_data, dict):
                            resp_task_id = task_data.get("id") or task_data.get("task_id")
                            resp_state = None
                            if isinstance(task_data.get("status"), dict):
                                resp_state = task_data["status"].get("state")
                            elif isinstance(task_data.get("state"), str):
                                resp_state = task_data["state"]
                            if resp_task_id and resp_state:
                                self.upsert_task(
                                    db,
                                    agent_id,
                                    str(resp_task_id),
                                    resp_state,
                                    context_id=task_data.get("contextId"),
                                    latest_message=task_data.get("status", {}).get("message") if isinstance(task_data.get("status"), dict) else None,
                                    payload={"history": task_data.get("history"), "artifacts": task_data.get("artifacts")} if task_data.get("history") or task_data.get("artifacts") else None,
                                )
                            else:
                                logger.info(
                                    "A2A response for agent '%s' lacks extractable task_id or state; task not persisted. Keys: %s",
                                    agent_name,
                                    list(task_data.keys()),
                                )
                    except Exception:
                        # Rollback the failed persistence attempt; if rollback
                        # itself fails, mark the connection invalid so the
                        # pool discards it (matches main.py pattern).  A silent
                        # rollback failure here has caused ``task stuck in
                        # working`` with no operator-visible signal.
                        try:
                            db.rollback()
                        except Exception:
                            logger.error("Rollback failed after task persistence error for agent '%s'", agent_name, exc_info=True)
                            try:
                                db.invalidate()
                            except Exception:
                                logger.error("db.invalidate() also failed after rollback error for agent '%s'", agent_name, exc_info=True)
                        logger.warning("Failed to persist task state for agent '%s': task_id=%s", agent_name, locals().get("resp_task_id"), exc_info=True)

                    # Log successful A2A call
                    structured_logger.log(
                        level="INFO",
                        message=f"A2A external call completed: {agent_name}",
                        component="a2a_service",
                        user_id=user_id,
                        user_email=user_email,
                        correlation_id=correlation_id,
                        duration_ms=call_duration_ms,
                        metadata={"event": "a2a_call_completed", "agent_name": agent_name, "agent_id": agent_id, "status_code": status_code, "success": True},
                    )

                    # ═══════════════════════════════════════════════════════════════════════════
                    # SHADOW MODE: log that the Rust runtime is available for this agent.
                    # Previous versions dispatched a second live invoke through the Rust
                    # sidecar for comparison, but that creates duplicate side effects for
                    # non-idempotent agents.  Shadow mode now only logs readiness; use
                    # delegate mode (experimental_rust_a2a_runtime_delegate_enabled=true)
                    # for full Rust-path execution.
                    # ═══════════════════════════════════════════════════════════════════════════
                    if settings.experimental_rust_a2a_runtime_enabled and not _should_delegate_a2a_to_rust():
                        structured_logger.log(
                            level="INFO",
                            message=f"A2A shadow mode active (observe-only): {agent_name}",
                            component="a2a_service",
                            user_id=user_id,
                            user_email=user_email,
                            correlation_id=correlation_id,
                            metadata={
                                "event": "a2a_shadow_active",
                                "agent_name": agent_name,
                                "python_status": status_code,
                            },
                        )
                else:
                    # Sanitize error message to prevent URL secrets from leaking in logs
                    raw_error = f"HTTP {status_code}: {response_text}"
                    error_message = sanitize_exception_message(raw_error, prepared.sensitive_query_param_names)

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
                        metadata={"event": "a2a_call_failed", "agent_name": agent_name, "agent_id": agent_id, "status_code": status_code},
                    )
                    raise A2AAgentError(error_message)

            except A2AAgentError:
                # Re-raise A2AAgentError without wrapping
                if span and error_message:
                    set_span_error(span, error_message)
                raise
            except RustA2ARuntimeError as e:
                error_message = sanitize_exception_message(str(e), prepared.sensitive_query_param_names)
                logger.error(f"Rust A2A runtime failed for agent '{agent_name}': {error_message}")
                if span:
                    set_span_error(span, error_message)
                raise A2AAgentError(f"Failed to invoke A2A agent: {error_message}") from e
            except Exception as e:
                # Sanitize error message to prevent URL secrets from leaking in logs
                error_message = sanitize_exception_message(str(e), prepared.sensitive_query_param_names)
                logger.error(f"Failed to invoke A2A agent '{agent_name}': {error_message}")
                if span:
                    set_span_error(span, error_message)
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
                if span:
                    set_span_attribute(span, "success", success)
                    set_span_attribute(span, "duration.ms", response_time * 1000)

        return response or {"error": error_message}

    async def _invoke_remote_agent(
        self,
        uaid: str,
        parameters: Dict[str, Any],
        interaction_type: str = "query",
        *,
        user_id: Optional[str] = None,
        user_email: Optional[str] = None,
        token_teams: Optional[List[str]] = None,  # pylint: disable=unused-argument
        hop_count: int = 0,
    ) -> Dict[str, Any]:
        """Invoke agent on remote gateway via UAID cross-gateway routing.

        Args:
            uaid: Universal Agent ID with embedded routing metadata
            parameters: Parameters for the interaction
            interaction_type: Type of interaction
            user_id: Identifier of the user initiating the call
            user_email: Email of the user initiating the call
            token_teams: Teams from JWT token
            hop_count: Current federation hop depth (from the inbound
                `X-Contextforge-UAID-Hop` header). The outbound request
                stamps `hop_count + 1` so the receiving gateway can
                enforce `uaid_max_federation_hops`.

        Returns:
            Agent response from remote gateway

        Raises:
            A2AAgentError: If routing fails or remote invocation fails
            ValueError: If UAID parsing fails or endpoint not allowed
        """
        # First-Party
        from mcpgateway.utils.uaid import extract_routing_info  # pylint: disable=import-outside-toplevel

        try:
            routing = extract_routing_info(uaid)
            protocol = routing["protocol"]
            endpoint = routing["endpoint"]
            registry = routing.get("registry")

            logger.info(f"Cross-gateway routing: {uaid!r} -> {protocol}://{endpoint}")

            # ═══════════════════════════════════════════════════════════════════════════
            # SECURITY WARNING: Log authentication gap on first cross-gateway call
            # ═══════════════════════════════════════════════════════════════════════════
            global _cross_gateway_auth_warning_logged  # pylint: disable=global-statement
            if not _cross_gateway_auth_warning_logged:
                logger.warning(
                    "⚠️  SECURITY: First cross-gateway UAID call detected. "
                    "Cross-gateway routing does NOT forward authentication credentials. "
                    "Remote gateways receive unauthenticated requests. "
                    "Ensure target gateways enforce AUTH_REQUIRED=true and configure UAID_ALLOWED_DOMAINS "
                    "to restrict routing to trusted domains only. "
                    "See documentation: .env.example lines 85-125 for security implications and mitigations."
                )
                _cross_gateway_auth_warning_logged = True

            # ═══════════════════════════════════════════════════════════════════════════
            # SECURITY: SSRF Protection - Validate endpoint before URL construction
            # ═══════════════════════════════════════════════════════════════════════════
            # Reject endpoints with SSRF attack vectors:
            # 1. Protocol prefixes (file://, gopher://, etc.)
            # 2. User-info bypass (evil@127.0.0.1)
            # 3. Path injection (example.com/path)
            # 4. Port injection is allowed for legitimate use cases (gateway.example.com:8443)

            if "://" in endpoint:
                raise ValueError(f"Cross-gateway routing to {endpoint!r} rejected: endpoint cannot contain protocol prefix (SSRF protection)")

            if "@" in endpoint:
                raise ValueError(f"Cross-gateway routing to {endpoint!r} rejected: endpoint cannot contain @ character (SSRF protection)")

            # Parse to check for path components (after first slash)
            # Valid: "gateway.example.com", "gateway.example.com:8443"
            # Invalid: "gateway.example.com/path", "127.0.0.1/admin"
            # Also reject `?` and `#` — those would smuggle query/fragment
            # data into the constructed URL path and let an attacker
            # attach arbitrary params to the downstream `/a2a/{uaid}/invoke`
            # call.  The Rust parser already rejects the same characters
            # in `uaid::resolve_routing`; mirror that here.
            if "/" in endpoint or "?" in endpoint or "#" in endpoint:
                raise ValueError(f"Cross-gateway routing to {endpoint!r} rejected: endpoint cannot contain path/query/fragment components (SSRF protection)")

            # Validate it's a valid hostname/IP by attempting to parse as URL
            # This catches malformed hostnames like "not..valid..hostname"
            try:
                parsed = urlparse(f"https://{endpoint}/test")
                if not parsed.netloc:
                    raise ValueError("Empty netloc")
            except Exception as parse_error:
                raise ValueError(f"Cross-gateway routing to {endpoint!r} rejected: invalid hostname format ({parse_error})")

            # Security: Validate endpoint against domain allowlist
            # Use proper subdomain matching: require exact match OR proper subdomain prefix
            allowed_domains = getattr(settings, "uaid_allowed_domains", [])
            if allowed_domains:
                # Extract just the domain part (without port) for allowlist checking
                # Use urlparse to handle URLs correctly (e.g., "https://example.com:8443" -> "example.com")
                # If endpoint doesn't start with scheme, add https:// for parsing
                url_to_parse = endpoint if endpoint.startswith(("http://", "https://")) else f"https://{endpoint}"
                parsed = urlparse(url_to_parse)
                endpoint_domain = parsed.hostname or endpoint.split(":")[0]

                # Require exact match or proper subdomain (e.g., "sub.example.com" matches "example.com", but "evilexample.com" does not)
                if not any(endpoint_domain == d or endpoint_domain.endswith(f".{d}") for d in allowed_domains):
                    raise ValueError(f"Cross-gateway routing to {endpoint!r} not allowed. Endpoint domain {endpoint_domain!r} not in UAID_ALLOWED_DOMAINS.")
            else:
                # WARNING: Empty allowlist permits arbitrary cross-gateway routing
                # This is unsafe in production - operators should configure UAID_ALLOWED_DOMAINS
                logger.warning(
                    f"UAID_ALLOWED_DOMAINS is empty - permitting cross-gateway routing to {endpoint!r} without domain validation. "
                    "This is UNSAFE in production. Configure UAID_ALLOWED_DOMAINS to restrict routing to trusted domains only."
                )

            # Construct URL based on protocol (endpoint is now validated).
            # ContextForge-to-ContextForge federation: target the receiving
            # gateway's existing public invoke route so the UAID is routed
            # through the same `is_uaid()` branch on the other side.
            #
            # URL-encode the UAID before embedding it in the path so a
            # malformed identifier containing `/`, `?`, or `#` cannot
            # smuggle extra path segments or query/fragment data. The
            # parser already validates structure; this is defence in depth.
            if protocol == "a2a":
                url = f"https://{endpoint}/a2a/{quote(uaid, safe='')}/invoke"
            elif protocol == "mcp":
                url = f"https://{endpoint}/mcp/tools/call"
            else:
                raise ValueError(f"Unsupported protocol in UAID: {protocol}")

            # Prepare request payload — matches the receiving gateway's
            # `/a2a/{agent_name}/invoke` body signature. The UAID is carried
            # in the URL path; no need to duplicate it in the body.
            request_data = {
                "parameters": parameters,
                "interaction_type": interaction_type,
            }

            # Make HTTP request using shared client
            # First-Party
            from mcpgateway.services.http_client_service import get_http_client  # pylint: disable=import-outside-toplevel

            client = await get_http_client()
            # Stamp the outbound hop count so the receiving gateway can
            # enforce `uaid_max_federation_hops` and break recursion —
            # covers both A→B→A pingpong and self-referential
            # `endpoint_url` loops.  Uses the shared `stamp_hop` helper
            # so Python and Rust agree on header name and overflow
            # semantics.
            # First-Party
            from mcpgateway.utils import uaid as uaid_utils  # pylint: disable=import-outside-toplevel

            headers = {"Content-Type": "application/json"}
            uaid_utils.stamp_hop(headers, hop_count)

            # ═══════════════════════════════════════════════════════════════════════════
            # SECURITY: Cross-gateway authentication is NOT implemented (as of v1.0)
            #
            # Current Behavior:
            #   Cross-gateway HTTP calls (UAID-based routing) do NOT forward authentication
            #   credentials. Remote gateways receive unauthenticated requests with no bearer
            #   token or session context.
            #
            # Security Implications:
            #   1. Remote Gateway MUST Authenticate: The target gateway MUST enforce its own
            #      authentication layer (AUTH_REQUIRED=true). If disabled, public agents
            #      are accessible without any authentication.
            #
            #   2. No Authorization Context: Remote gateway cannot enforce RBAC based on
            #      originating user. All cross-gateway calls execute with target gateway's
            #      public access level.
            #
            #   3. Trust Boundary: This gateway trusts the remote gateway's access control.
            #      If remote gateway is compromised or misconfigured, this becomes a
            #      security vector.
            #
            # Future Work (Roadmap):
            #   - Bearer token forwarding (requires gateway-to-gateway trust establishment)
            #   - Mutual TLS authentication (gateway certificates)
            #   - Trusted gateway registry with signature verification
            #   - Per-UAID access policies (allowlist/denylist)
            #
            # Current Mitigations:
            #   - UAID_ALLOWED_DOMAINS: Restricts outbound calls to trusted domains
            #   - Correlation ID logging: Enables cross-gateway request tracing
            #   - Operator guidance: Documentation warns about unauthenticated cross-gateway calls
            #
            # Operators: Set UAID_ALLOWED_DOMAINS to a restrictive allowlist of trusted domains only.
            # ═══════════════════════════════════════════════════════════════════════════

            # Add correlation ID for distributed tracing
            correlation_id = get_correlation_id()
            if correlation_id:
                headers["X-Correlation-ID"] = correlation_id

            # Log cross-gateway call start
            call_start_time = datetime.now(timezone.utc)
            structured_logger.log(
                level="INFO",
                message=f"Cross-gateway call started: {uaid!r}",
                component="a2a_service",
                user_id=user_id,
                user_email=user_email,
                correlation_id=correlation_id,
                metadata={
                    "event": "cross_gateway_call_started",
                    "uaid": uaid,
                    "endpoint": endpoint,
                    "protocol": protocol,
                    "registry": registry,
                },
            )

            # Make request
            http_response = await client.post(url, json=request_data, headers=headers, timeout=30.0)
            call_duration_ms = (datetime.now(timezone.utc) - call_start_time).total_seconds() * 1000

            # Any 2xx is success.  Restricting to status 200 would
            # spuriously reject legitimate 201/202/204 responses — an
            # A2A agent returning `201 Created` for an accepted task
            # would otherwise hit the failure sink below.
            if 200 <= http_response.status_code < 300:
                # Empty-body 2xx responses (most importantly `204 No
                # Content`, which is spec-forbidden from carrying a body,
                # and any 2xx that legitimately returns `Content-Length: 0`)
                # have nothing to parse.  Calling `.json()` on an empty
                # body raises `JSONDecodeError` and the block below would
                # then treat this as "2xx with unparseable body" — the
                # exact failure the stop-hook caught.  Short-circuit to
                # an empty dict so the call registers as a clean success
                # with no payload.
                if not http_response.content:
                    response = {}
                    structured_logger.log(
                        level="INFO",
                        message=f"Cross-gateway call completed: {uaid!r}",
                        component="a2a_service",
                        user_id=user_id,
                        user_email=user_email,
                        correlation_id=correlation_id,
                        duration_ms=call_duration_ms,
                        metadata={
                            "event": "cross_gateway_call_completed",
                            "uaid": uaid,
                            "endpoint": endpoint,
                            "status_code": http_response.status_code,
                            "success": True,
                            "empty_body": True,
                        },
                    )
                    return response
                # Wrap `.json()` so a 2xx-with-malformed-body lands in
                # the same dual-sink diagnostic block as a non-2xx
                # remote error.  Without this, JSONDecodeError would
                # skip the structured log + body-snippet capture and
                # land at the terse transport-error sink in the outer
                # except, losing operator-useful context (the advertised
                # 2xx status + the bytes that didn't parse).
                try:
                    response = http_response.json()
                except (json.JSONDecodeError, UnicodeDecodeError) as decode_error:
                    # `log_error_message` goes to the STRUCTURED log
                    # payload (operators filter on `error_message`) and
                    # so includes status prose for context.  The
                    # unstructured `logger.error` below passes the RAW
                    # `remote_body_snippet` so its `body=%r` field shape
                    # matches the non-200 sink at line 2358 — log parsers
                    # can key on `body=%r` uniformly across both paths.
                    remote_body_snippet = http_response.text[:2048] if http_response.text else ""
                    log_error_message = f"HTTP {http_response.status_code} but body failed to decode as JSON: {decode_error}"
                    logger.error("Cross-gateway HTTP %d from endpoint=%r uaid=%r body=%r", http_response.status_code, endpoint, uaid, remote_body_snippet)
                    structured_logger.log(
                        level="ERROR",
                        message=f"Cross-gateway call failed: {uaid!r}",
                        component="a2a_service",
                        user_id=user_id,
                        user_email=user_email,
                        correlation_id=correlation_id,
                        duration_ms=call_duration_ms,
                        error_details={"error_type": "CrossGatewayDecodeError", "error_message": log_error_message},
                        metadata={
                            "event": "cross_gateway_call_failed",
                            "uaid": uaid,
                            "endpoint": endpoint,
                            "status_code": http_response.status_code,
                        },
                    )
                    raise A2AAgentError(f"Cross-gateway routing failed: remote returned HTTP {http_response.status_code} with unparseable body") from decode_error

                # Log successful cross-gateway call
                structured_logger.log(
                    level="INFO",
                    message=f"Cross-gateway call completed: {uaid!r}",
                    component="a2a_service",
                    user_id=user_id,
                    user_email=user_email,
                    correlation_id=correlation_id,
                    duration_ms=call_duration_ms,
                    metadata={
                        "event": "cross_gateway_call_completed",
                        "uaid": uaid,
                        "endpoint": endpoint,
                        "status_code": http_response.status_code,
                        "success": True,
                    },
                )

                return response

            # Capture the remote body for operator-side structured logging
            # (so failures can be diagnosed) but keep the body out of the
            # exception we raise to the caller: a cross-gateway response
            # may contain a stack trace, internal hostnames, or partially
            # trusted data, and surfacing that to the end user is a leak.
            # The public message exposes only the HTTP status.
            remote_body_snippet = http_response.text[:2048] if http_response.text else ""
            # `log_error_message` embeds status for the structured-log
            # payload (which operators may filter on the bare field);
            # the positional `%d` log below carries status separately so
            # we don't double-stamp it in the formatted string.
            log_error_message = f"HTTP {http_response.status_code}: {remote_body_snippet}"
            public_error_message = f"HTTP {http_response.status_code}"

            # Log failed cross-gateway call.  Dual-sink to both the
            # structured logger AND the standard `logger` so the body
            # snippet survives even if structured logging is disabled,
            # mocked out, or misconfigured.  The public exception
            # carries only the status; the body is operator-only.
            logger.error("Cross-gateway HTTP %d from endpoint=%r uaid=%r body=%r", http_response.status_code, endpoint, uaid, remote_body_snippet)
            structured_logger.log(
                level="ERROR",
                message=f"Cross-gateway call failed: {uaid!r}",
                component="a2a_service",
                user_id=user_id,
                user_email=user_email,
                correlation_id=correlation_id,
                duration_ms=call_duration_ms,
                error_details={"error_type": "CrossGatewayHTTPError", "error_message": log_error_message},
                metadata={
                    "event": "cross_gateway_call_failed",
                    "uaid": uaid,
                    "endpoint": endpoint,
                    "status_code": http_response.status_code,
                },
            )

            raise A2AAgentError(f"Cross-gateway routing failed: {public_error_message}")

        # `A2AAgentError` raised inside the try body (e.g., from the
        # 2xx-with-unparseable-body inner except) propagates naturally
        # because it's a direct `Exception` subclass and no handler
        # below catches a superclass of it.
        #
        # Order matters: `JSONDecodeError` and `UnicodeDecodeError` are
        # both subclasses of `ValueError`, so they must be handled
        # BEFORE the generic `ValueError` catch — otherwise they'd be
        # swallowed with the wrong error message.
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            # Stray decode failures from `http_response.text` on the
            # non-2xx path (the 2xx path's inner try already converts
            # these into `A2AAgentError`).  A remote that lies about
            # its Content-Type charset lands here.
            logger.error(f"Cross-gateway routing response decode failure: {e}")
            raise A2AAgentError(f"Cross-gateway routing failed: response decode error: {e}")
        except ValueError as e:
            logger.error(f"Failed to parse UAID or validate endpoint: {e}")
            raise A2AAgentError(f"Invalid UAID or endpoint not allowed: {e}")
        except (httpx.HTTPError, OSError) as e:
            # Narrowed from a bare `except Exception` so we no longer
            # swallow programmer errors (AttributeError, KeyError,
            # asyncio.CancelledError, etc.).  Covered failure modes:
            #   - httpx.HTTPError: parent of TransportError / TimeoutException
            #     / all httpx-level wire failures
            #   - OSError: underlying socket layer
            # Decode errors are caught by the dedicated handler above.
            # Programmer errors and asyncio.CancelledError deliberately
            # propagate.
            logger.error(f"Cross-gateway routing transport failure: {e}")
            raise A2AAgentError(f"Cross-gateway routing failed: {e}")

    async def aggregate_metrics(self, db: Session) -> A2AAgentAggregateMetrics:
        """Aggregate metrics for all A2A agents.

        Combines recent raw metrics (within retention period) with historical
        hourly rollups for complete historical coverage. Uses in-memory caching
        (10s TTL) to reduce database load under high request rates.

        Args:
            db: Database session.

        Returns:
            A2AAgentAggregateMetrics: Aggregated metrics from raw + hourly rollup tables.
        """
        # Check cache first (if enabled)
        # First-Party
        from mcpgateway.cache.metrics_cache import is_cache_enabled, metrics_cache  # pylint: disable=import-outside-toplevel

        if is_cache_enabled():
            cached = metrics_cache.get("a2a")
            if cached is not None and isinstance(cached, dict):
                return A2AAgentAggregateMetrics(**cached)

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

        metrics = A2AAgentAggregateMetrics(
            total_agents=total_agents,
            active_agents=active_agents,
            total_interactions=total_interactions,
            successful_interactions=successful_interactions,
            failed_interactions=failed_interactions,
            success_rate=(successful_interactions / total_interactions * 100) if total_interactions > 0 else 0.0,
            avg_response_time=float(result.avg_response_time or 0.0),
            min_response_time=float(result.min_response_time or 0.0),
            max_response_time=float(result.max_response_time or 0.0),
        )

        # Cache the result as dict for serialization compatibility (if enabled)
        if is_cache_enabled():
            metrics_cache.set("a2a", metrics.model_dump())

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

    @staticmethod
    def _task_to_wire(task: "A2ATask") -> Dict[str, Any]:
        """Convert an A2ATask ORM row to the A2A v1 task wire format.

        The wire format uses ``id`` (not ``task_id``), ``status.state``
        (not a top-level ``state``), and optional ``history``/``artifacts``.
        """
        wire: Dict[str, Any] = {
            "id": task.task_id,
            "contextId": task.context_id,
            "status": {"state": task.state},
        }
        if task.latest_message:
            wire["status"]["message"] = task.latest_message
        if task.last_error and task.state == "failed":
            wire["status"]["message"] = {"role": "agent", "parts": [{"text": task.last_error}]}
        if task.payload and isinstance(task.payload, dict):
            if "history" in task.payload:
                wire["history"] = task.payload["history"]
            if "artifacts" in task.payload:
                wire["artifacts"] = task.payload["artifacts"]
        return wire

    def upsert_task(
        self,
        db: Session,
        agent_id: str,
        task_id: str,
        state: str,
        *,
        context_id: Optional[str] = None,
        latest_message: Optional[Dict[str, Any]] = None,
        payload: Optional[Dict[str, Any]] = None,
        last_error: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create or update a task row and return the wire-format dict.

        Called after SendMessage / streaming calls to persist task state
        so that GetTask, ListTasks, and CancelTask have data to read back.
        """
        task = db.query(A2ATask).filter(A2ATask.a2a_agent_id == agent_id, A2ATask.task_id == task_id).first()
        if task is None:
            task = A2ATask(a2a_agent_id=agent_id, task_id=task_id, state=state, context_id=context_id)
            db.add(task)
        task.state = state
        if context_id is not None:
            task.context_id = context_id
        if latest_message is not None:
            task.latest_message = latest_message
        if payload is not None:
            task.payload = payload
        if last_error is not None:
            task.last_error = last_error
        if state in ("completed", "failed", "canceled"):
            task.completed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(task)
        return self._task_to_wire(task)

    def get_task(
        self,
        db: Session,
        task_id: str,
        agent_id: Optional[str] = None,
        user_email: Optional[str] = None,
        token_teams: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Retrieve an A2A task by its task_id.

        Args:
            db: Database session.
            task_id: The agent-side task ID.
            agent_id: Optional agent ID filter.
            user_email: Caller's email for visibility scoping.
            token_teams: Caller's teams for visibility scoping.
                None = admin bypass, [] = public-only.

        Returns:
            Task data as a dict, or None if not found or not visible.
        """
        task = self._resolve_unique_task(db, task_id, agent_id)
        if task is None:
            return None
        # Enforce agent visibility on the owning agent.
        agent = db.query(DbA2AAgent).filter(DbA2AAgent.id == task.a2a_agent_id).first()
        if agent is not None and not self._check_agent_access(agent, user_email, token_teams):
            return None
        return self._task_to_wire(task)

    def cancel_task(
        self,
        db: Session,
        task_id: str,
        agent_id: Optional[str] = None,
        user_email: Optional[str] = None,
        token_teams: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Cancel an A2A task by setting its state to 'canceled'.

        Args:
            db: Database session.
            task_id: The agent-side task ID.
            agent_id: Optional agent ID filter.
            user_email: Caller's email for visibility scoping.
            token_teams: Caller's teams for visibility scoping.

        Returns:
            Task data as a dict after cancellation, or None if not found/not visible.
            If the task is already in a terminal state (completed/failed/canceled),
            returns it as-is without modification.
        """
        task = self._resolve_unique_task(db, task_id, agent_id)
        if task is None:
            return None
        agent = db.query(DbA2AAgent).filter(DbA2AAgent.id == task.a2a_agent_id).first()
        if agent is not None and not self._check_agent_access(agent, user_email, token_teams):
            return None
        if task.state in ("completed", "failed", "canceled"):
            return self._task_to_wire(task)
        task.state = "canceled"
        task.completed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(task)
        return self._task_to_wire(task)

    @staticmethod
    def _resolve_unique_task(db: Session, task_id: str, agent_id: Optional[str]) -> Optional[A2ATask]:
        """Look up a task by ``task_id`` and refuse cross-agent ambiguity.

        ``a2a_tasks`` is only unique on ``(a2a_agent_id, task_id)``, so two
        agents may legitimately share the same agent-side ``task_id``.  When
        the caller does not supply ``agent_id`` we must refuse to guess which
        row they meant — returning an arbitrary ``.first()`` result would
        let a request read or cancel the wrong agent's task.
        """
        query = db.query(A2ATask).filter(A2ATask.task_id == task_id)
        if agent_id is not None:
            query = query.filter(A2ATask.a2a_agent_id == agent_id)
        matches = query.limit(2).all()
        if not matches:
            return None
        if len(matches) > 1:
            logger.warning(
                "Ambiguous task lookup for task_id=%s with no agent_id filter (matched across multiple agents); refusing to guess",
                task_id,
            )
            return None
        return matches[0]

    def list_tasks(
        self,
        db: Session,
        agent_id: Optional[str] = None,
        state: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        user_email: Optional[str] = None,
        token_teams: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """List A2A tasks with optional filtering.

        Args:
            db: Database session.
            agent_id: Optional agent ID filter.
            state: Optional task state filter.
            limit: Maximum number of results.
            offset: Pagination offset.
            user_email: Caller's email for visibility scoping.
            token_teams: Caller's teams for visibility scoping.
                None = admin bypass, [] = public-only.

        Returns:
            List of task data dicts visible to the caller.
        """
        query = db.query(A2ATask)
        if agent_id is not None:
            query = query.filter(A2ATask.a2a_agent_id == agent_id)
        if state is not None:
            query = query.filter(A2ATask.state == state)
        # Filter to tasks owned by agents the caller can see.
        visible_agent_ids = self._visible_agent_ids(db, user_email, token_teams)
        if visible_agent_ids is not None:
            query = query.filter(A2ATask.a2a_agent_id.in_(visible_agent_ids))
        query = query.order_by(desc(A2ATask.updated_at))
        query = query.limit(limit).offset(offset)
        return [self._task_to_wire(t) for t in query.all()]

    # ---------------------------------------------------------------------------
    # Push notification config CRUD
    # ---------------------------------------------------------------------------

    def create_push_config(self, db: Session, config_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create or update a push notification configuration (upsert on unique key).

        The unique constraint is ``(a2a_agent_id, task_id, webhook_url)``.  When a
        row already exists for that key, the mutable fields (``auth_token``,
        ``events``, ``enabled``) are updated **in place** so that re-registering a
        webhook with a rotated bearer secret or a narrowed event set actually
        takes effect — previously the stale row was returned verbatim, and a
        client attempting to rotate a leaked secret would silently keep using the
        old one.

        Idempotent retries (same URL + same mutable fields) remain a no-op: the
        existing row is returned unchanged and ``updated_at`` is not bumped.

        Args:
            db: Database session.
            config_data: Dict with fields for A2APushNotificationConfig.

        Returns:
            Created, updated, or already-matching config as a dict.
        """
        # First-Party
        from mcpgateway.db import A2APushNotificationConfig  # pylint: disable=import-outside-toplevel
        from mcpgateway.schemas import A2APushNotificationConfigRead  # pylint: disable=import-outside-toplevel

        raw_auth_token = config_data.get("auth_token")
        desired_events = config_data.get("events")
        desired_enabled = config_data.get("enabled", True)

        existing = self._find_push_config_by_unique_key(db, config_data)
        if existing is not None:
            if self._apply_push_config_mutations(existing, raw_auth_token, desired_events, desired_enabled):
                db.commit()
                db.refresh(existing)
            return A2APushNotificationConfigRead.model_validate(existing).model_dump(mode="json")

        # Encrypt webhook bearer token at rest.  Rust push dispatch decrypts
        # via the shared AES-GCM secret; anyone with raw DB access or a
        # backup cannot recover webhook credentials.
        stored_auth_token = encode_auth({"token": raw_auth_token}) if raw_auth_token else None

        cfg = A2APushNotificationConfig(
            a2a_agent_id=config_data["a2a_agent_id"],
            task_id=config_data["task_id"],
            webhook_url=config_data["webhook_url"],
            auth_token=stored_auth_token,
            events=desired_events,
            enabled=desired_enabled,
        )
        db.add(cfg)
        try:
            db.commit()
        except Exception:
            # Race: another request inserted the same config between our
            # check and this insert.  Roll back and apply the same upsert
            # semantics to the winning row.
            db.rollback()
            existing = self._find_push_config_by_unique_key(db, config_data)
            if existing is not None:
                if self._apply_push_config_mutations(existing, raw_auth_token, desired_events, desired_enabled):
                    db.commit()
                    db.refresh(existing)
                return A2APushNotificationConfigRead.model_validate(existing).model_dump(mode="json")
            raise
        db.refresh(cfg)
        return A2APushNotificationConfigRead.model_validate(cfg).model_dump(mode="json")

    @staticmethod
    def _find_push_config_by_unique_key(db: Session, config_data: Dict[str, Any]):
        """Look up a push config row by the ``(agent, task, url)`` unique key."""
        # First-Party
        from mcpgateway.db import A2APushNotificationConfig  # pylint: disable=import-outside-toplevel

        return (
            db.query(A2APushNotificationConfig)
            .filter(
                A2APushNotificationConfig.a2a_agent_id == config_data["a2a_agent_id"],
                A2APushNotificationConfig.task_id == config_data["task_id"],
                A2APushNotificationConfig.webhook_url == config_data["webhook_url"],
            )
            .first()
        )

    @staticmethod
    def _apply_push_config_mutations(existing, raw_auth_token: Optional[str], events, enabled: bool) -> bool:
        """Apply incoming mutable fields to ``existing``; return True if anything changed.

        ``auth_token`` is compared by plaintext (the stored value is encrypted
        with a fresh nonce each time, so raw-string comparison would always
        report a difference and force a re-encrypt on every retry).  When the
        existing ciphertext cannot be decrypted (rotated key, legacy data),
        we treat it as "different" and re-encrypt the incoming plaintext so
        the caller's rotation takes effect — including the rotate-to-None
        case where the caller wants to remove the token entirely.
        """
        changed = False

        # ``decrypt_failed`` distinguishes "existing row has no token" from
        # "existing row has an undecryptable token".  Without it, an incoming
        # ``raw_auth_token=None`` (caller clearing the token) would compare
        # equal to the ``None`` we fell back to on decrypt failure, and the
        # stale ciphertext would silently stay in the row — producing a
        # config that fails to dispatch bearer auth every time.
        current_plaintext: Optional[str] = None
        decrypt_failed = False
        if existing.auth_token:
            try:
                decoded = decode_auth(existing.auth_token)
                if isinstance(decoded, dict):
                    candidate = decoded.get("token")
                    current_plaintext = str(candidate) if candidate is not None else None
                else:
                    decrypt_failed = True
            except Exception:
                decrypt_failed = True

        if decrypt_failed or raw_auth_token != current_plaintext:
            existing.auth_token = encode_auth({"token": raw_auth_token}) if raw_auth_token else None
            changed = True

        if events != existing.events:
            existing.events = events
            changed = True

        if bool(enabled) != bool(existing.enabled):
            existing.enabled = bool(enabled)
            changed = True

        return changed

    def get_push_config(self, db: Session, task_id: str, agent_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Retrieve a push notification config by task_id.

        Args:
            db: Database session.
            task_id: The task ID to look up.
            agent_id: Optional agent ID filter.

        Returns:
            Config data as a dict, or None if not found.
        """
        # First-Party
        from mcpgateway.db import A2APushNotificationConfig  # pylint: disable=import-outside-toplevel
        from mcpgateway.schemas import A2APushNotificationConfigRead  # pylint: disable=import-outside-toplevel

        query = db.query(A2APushNotificationConfig).filter(A2APushNotificationConfig.task_id == task_id)
        if agent_id is not None:
            query = query.filter(A2APushNotificationConfig.a2a_agent_id == agent_id)
        # Without agent_id, two agents can share the same task_id.  Refuse to
        # guess which row the caller meant; require agent_id to disambiguate.
        matches = query.order_by(A2APushNotificationConfig.created_at).limit(2).all()
        if not matches:
            return None
        if len(matches) > 1:
            logger.warning(
                "Ambiguous push-config lookup for task_id=%s with no agent_id filter (matched across multiple agents); refusing to guess",
                task_id,
            )
            return None
        cfg = matches[0]
        if cfg is None:
            return None
        return A2APushNotificationConfigRead.model_validate(cfg).model_dump(mode="json")

    def list_push_configs(self, db: Session, agent_id: Optional[str] = None, task_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """List push notification configs with optional filtering.

        Args:
            db: Database session.
            agent_id: Optional agent ID filter.
            task_id: Optional task ID filter.

        Returns:
            List of config data dicts.  ``auth_token`` is omitted via the
            read schema's ``exclude=True`` flag — use
            :meth:`list_push_configs_for_dispatch` for the Rust sidecar's
            webhook-dispatch path where the plaintext token is required.
        """
        # First-Party
        from mcpgateway.db import A2APushNotificationConfig  # pylint: disable=import-outside-toplevel
        from mcpgateway.schemas import A2APushNotificationConfigRead  # pylint: disable=import-outside-toplevel

        query = db.query(A2APushNotificationConfig)
        if agent_id is not None:
            query = query.filter(A2APushNotificationConfig.a2a_agent_id == agent_id)
        if task_id is not None:
            query = query.filter(A2APushNotificationConfig.task_id == task_id)
        return [A2APushNotificationConfigRead.model_validate(c).model_dump(mode="json") for c in query.all()]

    def list_push_configs_for_dispatch(
        self,
        db: Session,
        agent_id: Optional[str] = None,
        task_id: Optional[str] = None,
        user_email: Optional[str] = None,
        token_teams: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """List push configs with decrypted ``auth_token`` for webhook dispatch.

        Used only by the trusted ``/_internal/a2a/push/list`` endpoint that
        serves the Rust sidecar.  The token is decrypted on the fly and
        returned in plaintext so the sidecar can sign outbound webhook
        requests; at rest the DB column stays encrypted.

        Visibility scoping is pushed into SQL via ``_visible_agent_ids`` —
        the prior Python-side post-filter scanned every row regardless of
        access.  Admin bypass (``token_teams=None`` AND ``user_email=None``)
        returns all configs.
        """
        # First-Party
        from mcpgateway.db import A2APushNotificationConfig  # pylint: disable=import-outside-toplevel

        query = db.query(A2APushNotificationConfig)
        if agent_id is not None:
            query = query.filter(A2APushNotificationConfig.a2a_agent_id == agent_id)
        if task_id is not None:
            query = query.filter(A2APushNotificationConfig.task_id == task_id)

        visible_agent_ids = self._visible_agent_ids(db, user_email, token_teams)
        if visible_agent_ids is not None:
            # Non-admin caller: restrict to configs owned by visible agents.
            # An empty visible set (e.g. public-only user with no public agents
            # matching the filters) collapses to "no rows" without a scan.
            if not visible_agent_ids:
                return []
            query = query.filter(A2APushNotificationConfig.a2a_agent_id.in_(visible_agent_ids))

        results: List[Dict[str, Any]] = []
        decrypt_failed_ids: List[str] = []
        for cfg in query.all():
            auth_token_plain: Optional[str] = None
            if cfg.auth_token:
                try:
                    decoded = decode_auth(cfg.auth_token)
                    if isinstance(decoded, dict):
                        candidate = decoded.get("token")
                        auth_token_plain = str(candidate) if candidate is not None else None
                    else:
                        decrypt_failed_ids.append(cfg.id)
                except Exception:
                    # A decrypt failure means the column holds either a
                    # legacy cleartext value or ciphertext encrypted with a
                    # rotated key.  In either case we refuse to fall back to
                    # the raw column value — sending ciphertext as a bearer
                    # token would leak it to the webhook endpoint.
                    logger.warning(
                        "Failed to decrypt push-config auth_token for config_id=%s; dispatch will proceed without bearer auth",
                        cfg.id,
                    )
                    auth_token_plain = None
                    decrypt_failed_ids.append(cfg.id)
            results.append(
                {
                    "id": cfg.id,
                    "a2a_agent_id": cfg.a2a_agent_id,
                    "task_id": cfg.task_id,
                    "webhook_url": cfg.webhook_url,
                    "auth_token": auth_token_plain,
                    "events": cfg.events,
                    "enabled": cfg.enabled,
                }
            )

        # Surface an aggregate signal for ops dashboards: a misconfigured
        # AUTH_ENCRYPTION_SECRET makes decrypt failures scale with total
        # dispatches, so we log total-and-count rather than relying on log
        # aggregation to count per-config warnings.
        if decrypt_failed_ids:
            logger.warning(
                "A2A push-config dispatch listing: %d of %d configs had undecryptable auth_token (likely rotated AUTH_ENCRYPTION_SECRET or corrupted rows)",
                len(decrypt_failed_ids),
                len(results),
            )
        return results

    def delete_push_config(self, db: Session, config_id: str) -> bool:
        """Delete a push notification config by ID.

        Args:
            db: Database session.
            config_id: The config record ID to delete.

        Returns:
            True if deleted, False if not found.
        """
        # First-Party
        from mcpgateway.db import A2APushNotificationConfig  # pylint: disable=import-outside-toplevel

        cfg = db.query(A2APushNotificationConfig).filter(A2APushNotificationConfig.id == config_id).first()
        if cfg is None:
            return False
        db.delete(cfg)
        db.commit()
        return True

    def flush_events(self, db: Session, events: List[Dict[str, Any]]) -> int:
        """Batch-insert task events to PG.

        Args:
            db: Database session.
            events: List of event dicts with task_id, event_id, sequence, event_type, and optional payload.

        Returns:
            Number of events inserted.
        """
        # First-Party
        from mcpgateway.db import A2ATaskEvent  # pylint: disable=import-outside-toplevel

        count = 0
        for event_data in events:
            event = A2ATaskEvent(
                a2a_agent_id=event_data.get("a2a_agent_id"),
                task_id=event_data["task_id"],
                event_id=event_data["event_id"],
                sequence=event_data["sequence"],
                event_type=event_data["event_type"],
                payload=event_data.get("payload"),
            )
            db.add(event)
            count += 1
        db.commit()
        return count

    def replay_events(self, db: Session, task_id: str, after_sequence: int, limit: int = 1000) -> List[Dict[str, Any]]:
        """Return events for task_id with sequence > after_sequence.

        Args:
            db: Database session.
            task_id: The task whose events to replay.
            after_sequence: Return only events with sequence greater than this value.
            limit: Maximum number of events to return (default 1000).

        Returns:
            List of serialized event dicts ordered by sequence.
        """
        # First-Party
        from mcpgateway.db import A2ATaskEvent  # pylint: disable=import-outside-toplevel
        from mcpgateway.schemas import A2ATaskEventRead  # pylint: disable=import-outside-toplevel

        events = db.query(A2ATaskEvent).filter(A2ATaskEvent.task_id == task_id, A2ATaskEvent.sequence > after_sequence).order_by(A2ATaskEvent.sequence).limit(limit).all()
        return [A2ATaskEventRead.model_validate(e).model_dump(mode="json") for e in events]
