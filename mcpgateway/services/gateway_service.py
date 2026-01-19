# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/gateway_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Gateway Service Implementation.
This module implements gateway federation according to the MCP specification.
It handles:
- Gateway discovery and registration
- Request forwarding
- Capability aggregation
- Health monitoring
- Active/inactive gateway management

Examples:
    >>> from mcpgateway.services.gateway_service import GatewayService, GatewayError
    >>> service = GatewayService()
    >>> isinstance(service, GatewayService)
    True
    >>> hasattr(service, '_active_gateways')
    True
    >>> isinstance(service._active_gateways, set)
    True

    Test error classes:
    >>> error = GatewayError("Test error")
    >>> str(error)
    'Test error'
    >>> isinstance(error, Exception)
    True

    >>> conflict_error = GatewayNameConflictError("test_gw")
    >>> "test_gw" in str(conflict_error)
    True
    >>> conflict_error.enabled
    True
"""

# Standard
import asyncio
from datetime import datetime, timezone
import logging
import mimetypes
import os
import ssl
import tempfile
import time
from typing import Any, AsyncGenerator, cast, Dict, List, Optional, Set, TYPE_CHECKING, Union
from urllib.parse import urljoin, urlparse, urlunparse
import uuid

# Third-Party
from filelock import FileLock, Timeout
import httpx
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client
from pydantic import ValidationError
from sqlalchemy import and_, delete, desc, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload, Session

try:
    # Third-Party - check if redis is available
    # Third-Party
    import redis.asyncio as _aioredis  # noqa: F401  # pylint: disable=unused-import

    REDIS_AVAILABLE = True
    del _aioredis  # Only needed for availability check
except ImportError:
    REDIS_AVAILABLE = False
    logging.info("Redis is not utilized in this environment.")

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import EmailTeam, fresh_db_session
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import get_db, get_for_update
from mcpgateway.db import Prompt as DbPrompt
from mcpgateway.db import PromptMetric
from mcpgateway.db import Resource as DbResource
from mcpgateway.db import ResourceMetric, ResourceSubscription, server_prompt_association, server_resource_association, server_tool_association, SessionLocal
from mcpgateway.db import Tool as DbTool
from mcpgateway.db import ToolMetric
from mcpgateway.observability import create_span
from mcpgateway.schemas import GatewayCreate, GatewayRead, GatewayUpdate, PromptCreate, ResourceCreate, ToolCreate

# logging.getLogger("httpx").setLevel(logging.WARNING)  # Disables httpx logs for regular health checks
from mcpgateway.services.audit_trail_service import get_audit_trail_service
from mcpgateway.services.event_service import EventService
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.mcp_session_pool import get_mcp_session_pool, register_gateway_capabilities_for_notifications, TransportType
from mcpgateway.services.oauth_manager import OAuthManager
from mcpgateway.services.structured_logger import get_structured_logger
from mcpgateway.services.team_management_service import TeamManagementService
from mcpgateway.services.tool_service import ToolService
from mcpgateway.utils.create_slug import slugify
from mcpgateway.utils.display_name import generate_display_name
from mcpgateway.utils.pagination import unified_paginate
from mcpgateway.utils.passthrough_headers import get_passthrough_headers
from mcpgateway.utils.redis_client import get_redis_client
from mcpgateway.utils.retry_manager import ResilientHttpClient
from mcpgateway.utils.services_auth import decode_auth, encode_auth
from mcpgateway.utils.sqlalchemy_modifier import json_contains_expr
from mcpgateway.utils.ssl_context_cache import get_cached_ssl_context
from mcpgateway.utils.url_auth import apply_query_param_auth, sanitize_url_for_logging
from mcpgateway.utils.validate_signature import validate_signature
from mcpgateway.validation.tags import validate_tags_field

# Cache import (lazy to avoid circular dependencies)
_REGISTRY_CACHE = None
_TOOL_LOOKUP_CACHE = None


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

# Initialize structured logger and audit trail for gateway operations
structured_logger = get_structured_logger("gateway_service")
audit_trail = get_audit_trail_service()


GW_FAILURE_THRESHOLD = settings.unhealthy_threshold
GW_HEALTH_CHECK_INTERVAL = settings.health_check_interval


class GatewayError(Exception):
    """Base class for gateway-related errors.

    Examples:
        >>> error = GatewayError("Test error")
        >>> str(error)
        'Test error'
        >>> isinstance(error, Exception)
        True
    """


class GatewayNotFoundError(GatewayError):
    """Raised when a requested gateway is not found.

    Examples:
        >>> error = GatewayNotFoundError("Gateway not found")
        >>> str(error)
        'Gateway not found'
        >>> isinstance(error, GatewayError)
        True
    """


class GatewayNameConflictError(GatewayError):
    """Raised when a gateway name conflicts with existing (active or inactive) gateway.

    Args:
        name: The conflicting gateway name
        enabled: Whether the existing gateway is enabled
        gateway_id: ID of the existing gateway if available
        visibility: The visibility of the gateway ("public" or "team").

    Examples:
    >>> error = GatewayNameConflictError("test_gateway")
    >>> str(error)
    'Public Gateway already exists with name: test_gateway'
        >>> error.name
        'test_gateway'
        >>> error.enabled
        True
        >>> error.gateway_id is None
        True

    >>> error_inactive = GatewayNameConflictError("inactive_gw", enabled=False, gateway_id=123)
    >>> str(error_inactive)
    'Public Gateway already exists with name: inactive_gw (currently inactive, ID: 123)'
        >>> error_inactive.enabled
        False
        >>> error_inactive.gateway_id
        123
    """

    def __init__(self, name: str, enabled: bool = True, gateway_id: Optional[int] = None, visibility: Optional[str] = "public"):
        """Initialize the error with gateway information.

        Args:
            name: The conflicting gateway name
            enabled: Whether the existing gateway is enabled
            gateway_id: ID of the existing gateway if available
            visibility: The visibility of the gateway ("public" or "team").
        """
        self.name = name
        self.enabled = enabled
        self.gateway_id = gateway_id
        if visibility == "team":
            vis_label = "Team-level"
        else:
            vis_label = "Public"
        message = f"{vis_label} Gateway already exists with name: {name}"
        if not enabled:
            message += f" (currently inactive, ID: {gateway_id})"
        super().__init__(message)


class GatewayDuplicateConflictError(GatewayError):
    """Raised when a gateway conflicts with an existing gateway (same URL + credentials).

    This error is raised when attempting to register a gateway with a URL and
    authentication credentials that already exist within the same scope:
    - Public: Global uniqueness required across all public gateways.
    - Team: Uniqueness required within the same team.
    - Private: Uniqueness required for the same user, a user cannot have two private gateways with the same URL and credentials.

    Args:
        duplicate_gateway: The existing conflicting gateway (DbGateway instance).

    Examples:
        >>> # Public gateway conflict with the same URL and basic auth
        >>> existing_gw = DbGateway(url="https://api.example.com", id="abc-123", enabled=True, visibility="public", team_id=None, name="API Gateway", owner_email="alice@example.com")
        >>> error = GatewayDuplicateConflictError(
        ...     duplicate_gateway=existing_gw
        ... )
        >>> str(error)
        'The Server already exists in Public scope (Name: API Gateway, Status: active)'

        >>> # Team gateway conflict with the same URL and OAuth credentials
        >>> team_gw = DbGateway(url="https://api.example.com", id="def-456", enabled=False, visibility="team", team_id="engineering-team", name="API Gateway", owner_email="bob@example.com")
        >>> error = GatewayDuplicateConflictError(
        ...     duplicate_gateway=team_gw
        ... )
        >>> str(error)
        'The Server already exists in your Team (Name: API Gateway, Status: inactive). You may want to re-enable the existing gateway instead.'

        >>> # Private gateway conflict (same user cannot have two gateways with the same URL)
        >>> private_gw = DbGateway(url="https://api.example.com", id="ghi-789", enabled=True, visibility="private", team_id="none", name="API Gateway", owner_email="charlie@example.com")
        >>> error = GatewayDuplicateConflictError(
        ...     duplicate_gateway=private_gw
        ... )
        >>> str(error)
        'The Server already exists in "private" scope (Name: API Gateway, Status: active)'
    """

    def __init__(
        self,
        duplicate_gateway: "DbGateway",
    ):
        """Initialize the error with gateway information.

        Args:
            duplicate_gateway: The existing conflicting gateway (DbGateway instance)
        """
        self.duplicate_gateway = duplicate_gateway
        self.url = duplicate_gateway.url
        self.gateway_id = duplicate_gateway.id
        self.enabled = duplicate_gateway.enabled
        self.visibility = duplicate_gateway.visibility
        self.team_id = duplicate_gateway.team_id
        self.name = duplicate_gateway.name

        # Build scope description
        if self.visibility == "public":
            scope_desc = "Public scope"
        elif self.visibility == "team" and self.team_id:
            scope_desc = "your Team"
        else:
            scope_desc = f'"{self.visibility}" scope'

        # Build status description
        status = "active" if self.enabled else "inactive"

        # Construct error message
        message = f"The Server already exists in {scope_desc} " f"(Name: {self.name}, Status: {status})"

        # Add helpful hint for inactive gateways
        if not self.enabled:
            message += ". You may want to re-enable the existing gateway instead."

        super().__init__(message)


class GatewayConnectionError(GatewayError):
    """Raised when gateway connection fails.

    Examples:
        >>> error = GatewayConnectionError("Connection failed")
        >>> str(error)
        'Connection failed'
        >>> isinstance(error, GatewayError)
        True
    """


class OAuthToolValidationError(GatewayConnectionError):
    """Raised when tool validation fails during OAuth-driven fetch."""


class GatewayService:  # pylint: disable=too-many-instance-attributes
    """Service for managing federated gateways.

    Handles:
    - Gateway registration and health checks
    - Request forwarding
    - Capability negotiation
    - Federation events
    - Active/inactive status management
    """

    def __init__(self) -> None:
        """Initialize the gateway service.

        Examples:
            >>> from mcpgateway.services.gateway_service import GatewayService
            >>> from mcpgateway.services.event_service import EventService
            >>> from mcpgateway.utils.retry_manager import ResilientHttpClient
            >>> from mcpgateway.services.tool_service import ToolService
            >>> service = GatewayService()
            >>> isinstance(service._event_service, EventService)
            True
            >>> isinstance(service._http_client, ResilientHttpClient)
            True
            >>> service._health_check_interval == GW_HEALTH_CHECK_INTERVAL
            True
            >>> service._health_check_task is None
            True
            >>> isinstance(service._active_gateways, set)
            True
            >>> len(service._active_gateways)
            0
            >>> service._stream_response is None
            True
            >>> isinstance(service._pending_responses, dict)
            True
            >>> len(service._pending_responses)
            0
            >>> isinstance(service.tool_service, ToolService)
            True
            >>> isinstance(service._gateway_failure_counts, dict)
            True
            >>> len(service._gateway_failure_counts)
            0
            >>> hasattr(service, 'redis_url')
            True
        """
        self._http_client = ResilientHttpClient(client_args={"timeout": settings.federation_timeout, "verify": not settings.skip_ssl_verify})
        self._health_check_interval = GW_HEALTH_CHECK_INTERVAL
        self._health_check_task: Optional[asyncio.Task] = None
        self._active_gateways: Set[str] = set()  # Track active gateway URLs
        self._stream_response = None
        self._pending_responses = {}
        self.tool_service = ToolService()
        self._gateway_failure_counts: dict[str, int] = {}
        self.oauth_manager = OAuthManager(request_timeout=int(os.getenv("OAUTH_REQUEST_TIMEOUT", "30")), max_retries=int(os.getenv("OAUTH_MAX_RETRIES", "3")))
        self._event_service = EventService(channel_name="mcpgateway:gateway_events")

        # Per-gateway refresh locks to prevent concurrent refreshes for the same gateway
        self._refresh_locks: Dict[str, asyncio.Lock] = {}

        # For health checks, we determine the leader instance.
        self.redis_url = settings.redis_url if settings.cache_type == "redis" else None

        # Initialize optional Redis client holder (set in initialize())
        self._redis_client: Optional[Any] = None

        # Leader election settings from config
        if self.redis_url and REDIS_AVAILABLE:
            self._instance_id = str(uuid.uuid4())  # Unique ID for this process
            self._leader_key = settings.redis_leader_key
            self._leader_ttl = settings.redis_leader_ttl
            self._leader_heartbeat_interval = settings.redis_leader_heartbeat_interval
            self._leader_heartbeat_task: Optional[asyncio.Task] = None

        # Always initialize file lock as fallback (used if Redis connection fails at runtime)
        if settings.cache_type != "none":
            temp_dir = tempfile.gettempdir()
            user_path = os.path.normpath(settings.filelock_name)
            if os.path.isabs(user_path):
                user_path = os.path.relpath(user_path, start=os.path.splitdrive(user_path)[0] + os.sep)
            full_path = os.path.join(temp_dir, user_path)
            self._lock_path = full_path.replace("\\", "/")
            self._file_lock = FileLock(self._lock_path)

    @staticmethod
    def normalize_url(url: str) -> str:
        """
        Normalize a URL by ensuring it's properly formatted.

        Special handling for localhost to prevent duplicates:
        - Converts 127.0.0.1 to localhost for consistency
        - Preserves all other domain names as-is for CDN/load balancer support

        Args:
            url (str): The URL to normalize.

        Returns:
            str: The normalized URL.

        Examples:
            >>> GatewayService.normalize_url('http://localhost:8080/path')
            'http://localhost:8080/path'
            >>> GatewayService.normalize_url('http://127.0.0.1:8080/path')
            'http://localhost:8080/path'
            >>> GatewayService.normalize_url('https://example.com/api')
            'https://example.com/api'
        """
        parsed = urlparse(url)
        hostname = parsed.hostname

        # Special case: normalize 127.0.0.1 to localhost to prevent duplicates
        # but preserve all other domains as-is for CDN/load balancer support
        if hostname == "127.0.0.1":
            netloc = "localhost"
            if parsed.port:
                netloc += f":{parsed.port}"
            normalized = parsed._replace(netloc=netloc)
            return str(urlunparse(normalized))

        # For all other URLs, preserve the domain name
        return url

    def create_ssl_context(self, ca_certificate: str) -> ssl.SSLContext:
        """Create an SSL context with the provided CA certificate.

        Uses caching to avoid repeated SSL context creation for the same certificate.

        Args:
            ca_certificate: CA certificate in PEM format

        Returns:
            ssl.SSLContext: Configured SSL context
        """
        return get_cached_ssl_context(ca_certificate)

    async def initialize(self) -> None:
        """Initialize the service and start health check if this instance is the leader.

        Raises:
            ConnectionError: When redis ping fails
        """
        logger.info("Initializing gateway service")

        # Initialize event service with shared Redis client
        await self._event_service.initialize()

        # NOTE: We intentionally do NOT create a long-lived DB session here.
        # Health checks use fresh_db_session() only when DB access is actually needed,
        # avoiding holding connections during HTTP calls to MCP servers.

        user_email = settings.platform_admin_email

        # Get shared Redis client from factory
        if self.redis_url and REDIS_AVAILABLE:
            self._redis_client = await get_redis_client()

        if self._redis_client:
            # Check if Redis is available (ping already done by factory, but verify)
            try:
                await self._redis_client.ping()
            except Exception as e:
                raise ConnectionError(f"Redis ping failed: {e}") from e

            is_leader = await self._redis_client.set(self._leader_key, self._instance_id, ex=self._leader_ttl, nx=True)
            if is_leader:
                logger.info("Acquired Redis leadership. Starting health check and heartbeat tasks.")
                self._health_check_task = asyncio.create_task(self._run_health_checks(user_email))
                self._leader_heartbeat_task = asyncio.create_task(self._run_leader_heartbeat())
        else:
            # Always create the health check task in filelock mode; leader check is handled inside.
            self._health_check_task = asyncio.create_task(self._run_health_checks(user_email))

    async def shutdown(self) -> None:
        """Shutdown the service.

        Examples:
            >>> service = GatewayService()
            >>> # Mock internal components
            >>> from unittest.mock import AsyncMock
            >>> service._event_service = AsyncMock()
            >>> service._active_gateways = {'test_gw'}
            >>> import asyncio
            >>> asyncio.run(service.shutdown())
            >>> # Verify event service shutdown was called
            >>> service._event_service.shutdown.assert_awaited_once()
            >>> len(service._active_gateways)
            0
        """
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass

        # Cancel leader heartbeat task if running
        if getattr(self, "_leader_heartbeat_task", None):
            self._leader_heartbeat_task.cancel()
            try:
                await self._leader_heartbeat_task
            except asyncio.CancelledError:
                pass

        # Release Redis leadership atomically if we hold it
        if self._redis_client:
            try:
                # Lua script for atomic check-and-delete (only delete if we own the key)
                release_script = """
                if redis.call("get", KEYS[1]) == ARGV[1] then
                    return redis.call("del", KEYS[1])
                else
                    return 0
                end
                """
                result = await self._redis_client.eval(release_script, 1, self._leader_key, self._instance_id)
                if result:
                    logger.info("Released Redis leadership on shutdown")
            except Exception as e:
                logger.warning(f"Failed to release Redis leader key on shutdown: {e}")

        await self._http_client.aclose()
        await self._event_service.shutdown()
        self._active_gateways.clear()
        logger.info("Gateway service shutdown complete")

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

    def _check_gateway_uniqueness(
        self,
        db: Session,
        url: str,
        auth_value: Optional[Dict[str, str]],
        oauth_config: Optional[Dict[str, Any]],
        team_id: Optional[str],
        owner_email: str,
        visibility: str,
        gateway_id: Optional[str] = None,
    ) -> Optional[DbGateway]:
        """
        Check if a gateway with the same URL and credentials already exists.

        Args:
            db: Database session
            url: Gateway URL (normalized)
            auth_value: Decoded auth_value dict (not encrypted)
            oauth_config: OAuth configuration dict
            team_id: Team ID for team-scoped gateways
            owner_email: Email of the gateway owner
            visibility: Gateway visibility (public/team/private)
            gateway_id: Optional gateway ID to exclude from check (for updates)

        Returns:
            DbGateway if duplicate found, None otherwise
        """
        # Build base query based on visibility
        if visibility == "public":
            query = db.query(DbGateway).filter(DbGateway.url == url, DbGateway.visibility == "public")
        elif visibility == "team" and team_id:
            query = db.query(DbGateway).filter(DbGateway.url == url, DbGateway.visibility == "team", DbGateway.team_id == team_id)
        elif visibility == "private":
            # Check for duplicates within the same user's private gateways
            query = db.query(DbGateway).filter(DbGateway.url == url, DbGateway.visibility == "private", DbGateway.owner_email == owner_email)  # Scoped to same user
        else:
            return None

        # Exclude current gateway if updating
        if gateway_id:
            query = query.filter(DbGateway.id != gateway_id)

        existing_gateways = query.all()

        # Check each existing gateway
        for existing in existing_gateways:
            # Case 1: Both have OAuth config
            if oauth_config and existing.oauth_config:
                # Compare OAuth configs (exclude dynamic fields like tokens)
                existing_oauth = existing.oauth_config or {}
                new_oauth = oauth_config or {}

                # Compare key OAuth fields
                oauth_keys = ["grant_type", "client_id", "authorization_url", "token_url", "scope"]
                if all(existing_oauth.get(k) == new_oauth.get(k) for k in oauth_keys):
                    return existing  # Duplicate OAuth config found

            # Case 2: Both have auth_value (need to decrypt and compare)
            elif auth_value and existing.auth_value:

                try:
                    # Decrypt existing auth_value
                    if isinstance(existing.auth_value, str):
                        existing_decoded = decode_auth(existing.auth_value)

                    elif isinstance(existing.auth_value, dict):
                        existing_decoded = existing.auth_value

                    else:
                        continue

                    # Compare decoded auth values
                    if auth_value == existing_decoded:
                        return existing  # Duplicate credentials found
                except Exception as e:
                    logger.warning(f"Failed to decode auth_value for comparison: {e}")
                    continue

            # Case 3: Both have no auth (URL only, not allowed)
            elif not auth_value and not oauth_config and not existing.auth_value and not existing.oauth_config:
                return existing  # Duplicate URL without credentials

        return None  # No duplicate found

    async def register_gateway(
        self,
        db: Session,
        gateway: GatewayCreate,
        created_by: Optional[str] = None,
        created_from_ip: Optional[str] = None,
        created_via: Optional[str] = None,
        created_user_agent: Optional[str] = None,
        team_id: Optional[str] = None,
        owner_email: Optional[str] = None,
        visibility: Optional[str] = None,
        initialize_timeout: Optional[float] = None,
    ) -> GatewayRead:
        """Register a new gateway.

        Args:
            db: Database session
            gateway: Gateway creation schema
            created_by: Username who created this gateway
            created_from_ip: IP address of creator
            created_via: Creation method (ui, api, federation)
            created_user_agent: User agent of creation request
            team_id (Optional[str]): Team ID to assign the gateway to.
            owner_email (Optional[str]): Email of the user who owns this gateway.
            visibility (Optional[str]): Gateway visibility level (private, team, public).
            initialize_timeout (Optional[float]): Timeout in seconds for gateway initialization.

        Returns:
            Created gateway information

        Raises:
            GatewayNameConflictError: If gateway name already exists
            GatewayConnectionError: If there was an error connecting to the gateway
            ValueError: If required values are missing
            RuntimeError: If there is an error during processing that is not covered by other exceptions
            IntegrityError: If there is a database integrity error
            BaseException: If an unexpected error occurs

        Examples:
            >>> from mcpgateway.services.gateway_service import GatewayService
            >>> from unittest.mock import MagicMock
            >>> service = GatewayService()
            >>> db = MagicMock()
            >>> gateway = MagicMock()
            >>> db.execute.return_value.scalar_one_or_none.return_value = None
            >>> db.add = MagicMock()
            >>> db.commit = MagicMock()
            >>> db.refresh = MagicMock()
            >>> service._notify_gateway_added = MagicMock()
            >>> import asyncio
            >>> try:
            ...     asyncio.run(service.register_gateway(db, gateway))
            ... except Exception:
            ...     pass
        """
        visibility = "public" if visibility not in ("private", "team", "public") else visibility
        try:
            # # Check for name conflicts (both active and inactive)
            # existing_gateway = db.execute(select(DbGateway).where(DbGateway.name == gateway.name)).scalar_one_or_none()

            # if existing_gateway:
            #     raise GatewayNameConflictError(
            #         gateway.name,
            #         enabled=existing_gateway.enabled,
            #         gateway_id=existing_gateway.id,
            #     )
            # Check for existing gateway with the same slug and visibility
            slug_name = slugify(gateway.name)
            if visibility.lower() == "public":
                # Check for existing public gateway with the same slug (row-locked)
                existing_gateway = get_for_update(
                    db,
                    DbGateway,
                    where=and_(DbGateway.slug == slug_name, DbGateway.visibility == "public"),
                )
                if existing_gateway:
                    raise GatewayNameConflictError(existing_gateway.slug, enabled=existing_gateway.enabled, gateway_id=existing_gateway.id, visibility=existing_gateway.visibility)
            elif visibility.lower() == "team" and team_id:
                # Check for existing team gateway with the same slug (row-locked)
                existing_gateway = get_for_update(
                    db,
                    DbGateway,
                    where=and_(DbGateway.slug == slug_name, DbGateway.visibility == "team", DbGateway.team_id == team_id),
                )
                if existing_gateway:
                    raise GatewayNameConflictError(existing_gateway.slug, enabled=existing_gateway.enabled, gateway_id=existing_gateway.id, visibility=existing_gateway.visibility)

            # Normalize the gateway URL
            normalized_url = self.normalize_url(str(gateway.url))

            decoded_auth_value = None
            if gateway.auth_value:
                if isinstance(gateway.auth_value, str):
                    try:
                        decoded_auth_value = decode_auth(gateway.auth_value)
                    except Exception as e:
                        logger.warning(f"Failed to decode provided auth_value: {e}")
                        decoded_auth_value = None
                elif isinstance(gateway.auth_value, dict):
                    decoded_auth_value = gateway.auth_value

            # Check for duplicate gateway
            if not gateway.one_time_auth:
                duplicate_gateway = self._check_gateway_uniqueness(
                    db=db, url=normalized_url, auth_value=decoded_auth_value, oauth_config=gateway.oauth_config, team_id=team_id, owner_email=owner_email, visibility=visibility
                )

                if duplicate_gateway:
                    raise GatewayDuplicateConflictError(duplicate_gateway=duplicate_gateway)

            # Prevent URL-only gateways (no auth at all)
            # if not decoded_auth_value and not gateway.oauth_config:
            #     raise ValueError(
            #         f"Gateway with URL '{normalized_url}' must have either auth_value or oauth_config. "
            #         "URL-only gateways are not allowed."
            #     )

            auth_type = getattr(gateway, "auth_type", None)
            # Support multiple custom headers
            auth_value = getattr(gateway, "auth_value", {})
            authentication_headers: Optional[Dict[str, str]] = None

            # Handle query_param auth - encrypt and prepare for storage
            auth_query_params_encrypted: Optional[Dict[str, str]] = None
            auth_query_params_decrypted: Optional[Dict[str, str]] = None
            init_url = normalized_url  # URL to use for initialization

            if auth_type == "query_param":
                # Extract and encrypt query param auth
                param_key = getattr(gateway, "auth_query_param_key", None)
                param_value = getattr(gateway, "auth_query_param_value", None)
                if param_key and param_value:
                    # Get the actual secret value
                    if hasattr(param_value, "get_secret_value"):
                        raw_value = param_value.get_secret_value()
                    else:
                        raw_value = str(param_value)
                    # Encrypt for storage
                    encrypted_value = encode_auth({param_key: raw_value})
                    auth_query_params_encrypted = {param_key: encrypted_value}
                    auth_query_params_decrypted = {param_key: raw_value}
                    # Append query params to URL for initialization
                    init_url = apply_query_param_auth(normalized_url, auth_query_params_decrypted)
                    # Query param auth doesn't use auth_value
                    auth_value = None
                    authentication_headers = None

            elif hasattr(gateway, "auth_headers") and gateway.auth_headers:
                # Convert list of {key, value} to dict
                header_dict = {h["key"]: h["value"] for h in gateway.auth_headers if h.get("key")}
                # Keep encoded form for persistence, but pass raw headers for initialization
                auth_value = encode_auth(header_dict)  # Encode the dict for consistency
                authentication_headers = {str(k): str(v) for k, v in header_dict.items()}

            elif isinstance(auth_value, str) and auth_value:
                # Decode persisted auth for initialization
                decoded = decode_auth(auth_value)
                authentication_headers = {str(k): str(v) for k, v in decoded.items()}
            else:
                authentication_headers = None

            oauth_config = getattr(gateway, "oauth_config", None)
            ca_certificate = getattr(gateway, "ca_certificate", None)
            if initialize_timeout is not None:
                try:
                    capabilities, tools, resources, prompts = await asyncio.wait_for(
                        self._initialize_gateway(
                            init_url,  # URL with query params if applicable
                            authentication_headers,
                            gateway.transport,
                            auth_type,
                            oauth_config,
                            ca_certificate,
                            auth_query_params=auth_query_params_decrypted,
                        ),
                        timeout=initialize_timeout,
                    )
                except asyncio.TimeoutError as exc:
                    sanitized = sanitize_url_for_logging(init_url, auth_query_params_decrypted)
                    raise GatewayConnectionError(f"Gateway initialization timed out after {initialize_timeout}s for {sanitized}") from exc
            else:
                capabilities, tools, resources, prompts = await self._initialize_gateway(
                    init_url,  # URL with query params if applicable
                    authentication_headers,
                    gateway.transport,
                    auth_type,
                    oauth_config,
                    ca_certificate,
                    auth_query_params=auth_query_params_decrypted,
                )

            if gateway.one_time_auth:
                # For one-time auth, clear auth_type and auth_value after initialization
                auth_type = "one_time_auth"
                auth_value = None
                oauth_config = None

            tools = [
                DbTool(
                    original_name=tool.name,
                    custom_name=tool.name,
                    custom_name_slug=slugify(tool.name),
                    display_name=generate_display_name(tool.name),
                    url=normalized_url,
                    description=tool.description,
                    integration_type="MCP",  # Gateway-discovered tools are MCP type
                    request_type=tool.request_type,
                    headers=tool.headers,
                    input_schema=tool.input_schema,
                    output_schema=tool.output_schema,
                    annotations=tool.annotations,
                    jsonpath_filter=tool.jsonpath_filter,
                    auth_type=auth_type,
                    auth_value=auth_value,
                    # Federation metadata
                    created_by=created_by or "system",
                    created_from_ip=created_from_ip,
                    created_via="federation",  # These are federated tools
                    created_user_agent=created_user_agent,
                    federation_source=gateway.name,
                    version=1,
                    # Inherit team assignment from gateway
                    team_id=team_id,
                    owner_email=owner_email,
                    visibility=visibility,
                )
                for tool in tools
            ]

            # Create resource DB models
            db_resources = [
                DbResource(
                    uri=r.uri,
                    name=r.name,
                    description=r.description,
                    mime_type=(mime_type := (mimetypes.guess_type(r.uri)[0] or ("text/plain" if isinstance(r.content, str) else "application/octet-stream"))),
                    uri_template=r.uri_template or None,
                    text_content=r.content if (mime_type.startswith("text/") or isinstance(r.content, str)) and isinstance(r.content, str) else None,
                    binary_content=(
                        r.content.encode() if (mime_type.startswith("text/") or isinstance(r.content, str)) and isinstance(r.content, str) else r.content if isinstance(r.content, bytes) else None
                    ),
                    size=len(r.content) if r.content else 0,
                    tags=getattr(r, "tags", []) or [],
                    created_by=created_by or "system",
                    created_from_ip=created_from_ip,
                    created_via="federation",
                    created_user_agent=created_user_agent,
                    import_batch_id=None,
                    federation_source=gateway.name,
                    version=1,
                    team_id=getattr(r, "team_id", None) or team_id,
                    owner_email=getattr(r, "owner_email", None) or owner_email or created_by,
                    visibility=getattr(r, "visibility", None) or visibility,
                )
                for r in resources
            ]

            # Create prompt DB models
            db_prompts = [
                DbPrompt(
                    name=prompt.name,
                    original_name=prompt.name,
                    custom_name=prompt.name,
                    display_name=prompt.name,
                    description=prompt.description,
                    template=prompt.template if hasattr(prompt, "template") else "",
                    argument_schema={},  # Use argument_schema instead of arguments
                    # Federation metadata
                    created_by=created_by or "system",
                    created_from_ip=created_from_ip,
                    created_via="federation",  # These are federated prompts
                    created_user_agent=created_user_agent,
                    federation_source=gateway.name,
                    version=1,
                    # Inherit team assignment from gateway
                    team_id=team_id,
                    owner_email=owner_email,
                    visibility=visibility,
                )
                for prompt in prompts
            ]

            # Create DB model
            db_gateway = DbGateway(
                name=gateway.name,
                slug=slug_name,
                url=normalized_url,
                description=gateway.description,
                tags=gateway.tags or [],
                transport=gateway.transport,
                capabilities=capabilities,
                last_seen=datetime.now(timezone.utc),
                auth_type=auth_type,
                auth_value=auth_value,
                auth_query_params=auth_query_params_encrypted,  # Encrypted query param auth
                oauth_config=oauth_config,
                passthrough_headers=gateway.passthrough_headers,
                tools=tools,
                resources=db_resources,
                prompts=db_prompts,
                # Gateway metadata
                created_by=created_by,
                created_from_ip=created_from_ip,
                created_via=created_via or "api",
                created_user_agent=created_user_agent,
                version=1,
                # Team scoping fields
                team_id=team_id,
                owner_email=owner_email,
                visibility=visibility,
                ca_certificate=gateway.ca_certificate,
                ca_certificate_sig=gateway.ca_certificate_sig,
                signing_algorithm=gateway.signing_algorithm,
            )

            # Add to DB
            db.add(db_gateway)
            db.flush()  # Flush to get the ID without committing
            db.refresh(db_gateway)

            # Update tracking
            self._active_gateways.add(db_gateway.url)

            # Notify subscribers
            await self._notify_gateway_added(db_gateway)

            logger.info(f"Registered gateway: {gateway.name}")

            # Structured logging: Audit trail for gateway creation
            audit_trail.log_action(
                user_id=created_by or "system",
                action="create_gateway",
                resource_type="gateway",
                resource_id=str(db_gateway.id),
                resource_name=db_gateway.name,
                user_email=owner_email,
                team_id=team_id,
                client_ip=created_from_ip,
                user_agent=created_user_agent,
                new_values={
                    "name": db_gateway.name,
                    "url": db_gateway.url,
                    "visibility": visibility,
                    "transport": db_gateway.transport,
                    "tools_count": len(tools),
                    "resources_count": len(db_resources),
                    "prompts_count": len(db_prompts),
                },
                context={
                    "created_via": created_via,
                },
                db=db,
            )

            # Structured logging: Log successful gateway creation
            structured_logger.log(
                level="INFO",
                message="Gateway created successfully",
                event_type="gateway_created",
                component="gateway_service",
                user_id=created_by,
                user_email=owner_email,
                team_id=team_id,
                resource_type="gateway",
                resource_id=str(db_gateway.id),
                custom_fields={
                    "gateway_name": db_gateway.name,
                    "gateway_url": normalized_url,
                    "visibility": visibility,
                    "transport": db_gateway.transport,
                },
                db=db,
            )

            # Add team name for response
            db_gateway.team = self._get_team_name(db, db_gateway.team_id)
            return GatewayRead.model_validate(self._prepare_gateway_for_read(db_gateway)).masked()
        except* GatewayConnectionError as ge:  # pragma: no mutate
            if TYPE_CHECKING:
                ge: ExceptionGroup[GatewayConnectionError]
            logger.error(f"GatewayConnectionError in group: {ge.exceptions}")

            structured_logger.log(
                level="ERROR",
                message="Gateway creation failed due to connection error",
                event_type="gateway_creation_failed",
                component="gateway_service",
                user_id=created_by,
                user_email=owner_email,
                error=ge.exceptions[0],
                custom_fields={"gateway_name": gateway.name, "gateway_url": str(gateway.url)},
                db=db,
            )
            raise ge.exceptions[0]
        except* GatewayNameConflictError as gnce:  # pragma: no mutate
            if TYPE_CHECKING:
                gnce: ExceptionGroup[GatewayNameConflictError]
            logger.error(f"GatewayNameConflictError in group: {gnce.exceptions}")

            structured_logger.log(
                level="WARNING",
                message="Gateway creation failed due to name conflict",
                event_type="gateway_name_conflict",
                component="gateway_service",
                user_id=created_by,
                user_email=owner_email,
                custom_fields={"gateway_name": gateway.name, "visibility": visibility},
                db=db,
            )
            raise gnce.exceptions[0]
        except* GatewayDuplicateConflictError as guce:  # pragma: no mutate
            if TYPE_CHECKING:
                guce: ExceptionGroup[GatewayDuplicateConflictError]
            logger.error(f"GatewayDuplicateConflictError in group: {guce.exceptions}")

            structured_logger.log(
                level="WARNING",
                message="Gateway creation failed due to duplicate",
                event_type="gateway_duplicate_conflict",
                component="gateway_service",
                user_id=created_by,
                user_email=owner_email,
                custom_fields={"gateway_name": gateway.name},
                db=db,
            )
            raise guce.exceptions[0]
        except* ValueError as ve:  # pragma: no mutate
            if TYPE_CHECKING:
                ve: ExceptionGroup[ValueError]
            logger.error(f"ValueErrors in group: {ve.exceptions}")

            structured_logger.log(
                level="ERROR",
                message="Gateway creation failed due to validation error",
                event_type="gateway_creation_failed",
                component="gateway_service",
                user_id=created_by,
                user_email=owner_email,
                error=ve.exceptions[0],
                custom_fields={"gateway_name": gateway.name},
                db=db,
            )
            raise ve.exceptions[0]
        except* RuntimeError as re:  # pragma: no mutate
            if TYPE_CHECKING:
                re: ExceptionGroup[RuntimeError]
            logger.error(f"RuntimeErrors in group: {re.exceptions}")

            structured_logger.log(
                level="ERROR",
                message="Gateway creation failed due to runtime error",
                event_type="gateway_creation_failed",
                component="gateway_service",
                user_id=created_by,
                user_email=owner_email,
                error=re.exceptions[0],
                custom_fields={"gateway_name": gateway.name},
                db=db,
            )
            raise re.exceptions[0]
        except* IntegrityError as ie:  # pragma: no mutate
            if TYPE_CHECKING:
                ie: ExceptionGroup[IntegrityError]
            logger.error(f"IntegrityErrors in group: {ie.exceptions}")

            structured_logger.log(
                level="ERROR",
                message="Gateway creation failed due to database integrity error",
                event_type="gateway_creation_failed",
                component="gateway_service",
                user_id=created_by,
                user_email=owner_email,
                error=ie.exceptions[0],
                custom_fields={"gateway_name": gateway.name},
                db=db,
            )
            raise ie.exceptions[0]
        except* BaseException as other:  # catches every other sub-exception  # pragma: no mutate
            if TYPE_CHECKING:
                other: ExceptionGroup[Exception]
            logger.error(f"Other grouped errors: {other.exceptions}")
            raise other.exceptions[0]

    async def fetch_tools_after_oauth(self, db: Session, gateway_id: str, app_user_email: str) -> Dict[str, Any]:
        """Fetch tools from MCP server after OAuth completion for Authorization Code flow.

        Args:
            db: Database session
            gateway_id: ID of the gateway to fetch tools for
            app_user_email: MCP Gateway user email for token retrieval

        Returns:
            Dict containing capabilities, tools, resources, and prompts

        Raises:
            GatewayConnectionError: If connection or OAuth fails
        """
        try:
            # Get the gateway with eager loading for sync operations to avoid N+1 queries
            gateway = db.execute(
                select(DbGateway)
                .options(
                    selectinload(DbGateway.tools),
                    selectinload(DbGateway.resources),
                    selectinload(DbGateway.prompts),
                )
                .where(DbGateway.id == gateway_id)
            ).scalar_one_or_none()

            if not gateway:
                raise ValueError(f"Gateway {gateway_id} not found")

            if not gateway.oauth_config:
                raise ValueError(f"Gateway {gateway_id} has no OAuth configuration")

            grant_type = gateway.oauth_config.get("grant_type")
            if grant_type != "authorization_code":
                raise ValueError(f"Gateway {gateway_id} is not using Authorization Code flow")

            # Get OAuth tokens for this gateway
            # First-Party
            from mcpgateway.services.token_storage_service import TokenStorageService  # pylint: disable=import-outside-toplevel

            token_storage = TokenStorageService(db)

            # Get user-specific OAuth token
            if not app_user_email:
                raise GatewayConnectionError(f"User authentication required for OAuth gateway {gateway.name}")

            access_token = await token_storage.get_user_token(gateway.id, app_user_email)

            if not access_token:
                raise GatewayConnectionError(
                    f"No OAuth tokens found for user {app_user_email} on gateway {gateway.name}. Please complete the OAuth authorization flow first at /oauth/authorize/{gateway.id}"
                )

            # Debug: Check if token was decrypted
            if access_token.startswith("Z0FBQUFBQm"):  # Encrypted tokens start with this
                logger.error(f"Token appears to be encrypted! Encryption service may have failed. Token length: {len(access_token)}")
            else:
                logger.info(f"Using decrypted OAuth token for {gateway.name} (length: {len(access_token)})")

            # Now connect to MCP server with the access token
            authentication = {"Authorization": f"Bearer {access_token}"}

            # Use the existing connection logic
            # Note: For OAuth servers, skip validation since we already validated via OAuth flow
            if gateway.transport.upper() == "SSE":
                capabilities, tools, resources, prompts = await self._connect_to_sse_server_without_validation(gateway.url, authentication)
            elif gateway.transport.upper() == "STREAMABLEHTTP":
                capabilities, tools, resources, prompts = await self.connect_to_streamablehttp_server(gateway.url, authentication)
            else:
                raise ValueError(f"Unsupported transport type: {gateway.transport}")

            # Handle tools, resources, and prompts using helper methods
            tools_to_add = self._update_or_create_tools(db, tools, gateway, "oauth")
            resources_to_add = self._update_or_create_resources(db, resources, gateway, "oauth")
            prompts_to_add = self._update_or_create_prompts(db, prompts, gateway, "oauth")

            # Clean up items that are no longer available from the gateway
            new_tool_names = [tool.name for tool in tools]
            new_resource_uris = [resource.uri for resource in resources]
            new_prompt_names = [prompt.name for prompt in prompts]

            # Count items before cleanup for logging

            # Bulk delete tools that are no longer available from the gateway
            # Use chunking to avoid SQLite's 999 parameter limit for IN clauses
            stale_tool_ids = [tool.id for tool in gateway.tools if tool.original_name not in new_tool_names]
            if stale_tool_ids:
                # Delete child records first to avoid FK constraint violations
                for i in range(0, len(stale_tool_ids), 500):
                    chunk = stale_tool_ids[i : i + 500]
                    db.execute(delete(ToolMetric).where(ToolMetric.tool_id.in_(chunk)))
                    db.execute(delete(server_tool_association).where(server_tool_association.c.tool_id.in_(chunk)))
                    db.execute(delete(DbTool).where(DbTool.id.in_(chunk)))

            # Bulk delete resources that are no longer available from the gateway
            stale_resource_ids = [resource.id for resource in gateway.resources if resource.uri not in new_resource_uris]
            if stale_resource_ids:
                # Delete child records first to avoid FK constraint violations
                for i in range(0, len(stale_resource_ids), 500):
                    chunk = stale_resource_ids[i : i + 500]
                    db.execute(delete(ResourceMetric).where(ResourceMetric.resource_id.in_(chunk)))
                    db.execute(delete(server_resource_association).where(server_resource_association.c.resource_id.in_(chunk)))
                    db.execute(delete(ResourceSubscription).where(ResourceSubscription.resource_id.in_(chunk)))
                    db.execute(delete(DbResource).where(DbResource.id.in_(chunk)))

            # Bulk delete prompts that are no longer available from the gateway
            stale_prompt_ids = [prompt.id for prompt in gateway.prompts if prompt.original_name not in new_prompt_names]
            if stale_prompt_ids:
                # Delete child records first to avoid FK constraint violations
                for i in range(0, len(stale_prompt_ids), 500):
                    chunk = stale_prompt_ids[i : i + 500]
                    db.execute(delete(PromptMetric).where(PromptMetric.prompt_id.in_(chunk)))
                    db.execute(delete(server_prompt_association).where(server_prompt_association.c.prompt_id.in_(chunk)))
                    db.execute(delete(DbPrompt).where(DbPrompt.id.in_(chunk)))

            # Expire gateway to clear cached relationships after bulk deletes
            # This prevents SQLAlchemy from trying to re-delete already-deleted items
            if stale_tool_ids or stale_resource_ids or stale_prompt_ids:
                db.expire(gateway)

            # Update gateway relationships to reflect deletions
            gateway.tools = [tool for tool in gateway.tools if tool.original_name in new_tool_names]
            gateway.resources = [resource for resource in gateway.resources if resource.uri in new_resource_uris]
            gateway.prompts = [prompt for prompt in gateway.prompts if prompt.original_name in new_prompt_names]

            # Log cleanup results
            tools_removed = len(stale_tool_ids)
            resources_removed = len(stale_resource_ids)
            prompts_removed = len(stale_prompt_ids)

            if tools_removed > 0:
                logger.info(f"Removed {tools_removed} tools no longer available from gateway")
            if resources_removed > 0:
                logger.info(f"Removed {resources_removed} resources no longer available from gateway")
            if prompts_removed > 0:
                logger.info(f"Removed {prompts_removed} prompts no longer available from gateway")

            # Update gateway capabilities and last_seen
            gateway.capabilities = capabilities
            gateway.last_seen = datetime.now(timezone.utc)

            # Register capabilities for notification-driven actions
            register_gateway_capabilities_for_notifications(gateway.id, capabilities)

            # Add new items to DB in chunks to prevent lock escalation
            items_added = 0
            chunk_size = 50

            if tools_to_add:
                for i in range(0, len(tools_to_add), chunk_size):
                    chunk = tools_to_add[i : i + chunk_size]
                    db.add_all(chunk)
                    db.flush()  # Flush each chunk to avoid excessive memory usage
                items_added += len(tools_to_add)
                logger.info(f"Added {len(tools_to_add)} new tools to database")

            if resources_to_add:
                for i in range(0, len(resources_to_add), chunk_size):
                    chunk = resources_to_add[i : i + chunk_size]
                    db.add_all(chunk)
                    db.flush()
                items_added += len(resources_to_add)
                logger.info(f"Added {len(resources_to_add)} new resources to database")

            if prompts_to_add:
                for i in range(0, len(prompts_to_add), chunk_size):
                    chunk = prompts_to_add[i : i + chunk_size]
                    db.add_all(chunk)
                    db.flush()
                items_added += len(prompts_to_add)
                logger.info(f"Added {len(prompts_to_add)} new prompts to database")

            if items_added > 0:
                db.commit()
                logger.info(f"Total {items_added} new items added to database")
            else:
                logger.info("No new items to add to database")
                # Still commit to save any updates to existing items
                db.commit()

            cache = _get_registry_cache()
            await cache.invalidate_tools()
            await cache.invalidate_resources()
            await cache.invalidate_prompts()
            tool_lookup_cache = _get_tool_lookup_cache()
            await tool_lookup_cache.invalidate_gateway(str(gateway.id))
            # Also invalidate tags cache since tool/resource tags may have changed
            # First-Party
            from mcpgateway.cache.admin_stats_cache import admin_stats_cache  # pylint: disable=import-outside-toplevel

            await admin_stats_cache.invalidate_tags()

            return {"capabilities": capabilities, "tools": tools, "resources": resources, "prompts": prompts}

        except GatewayConnectionError as gce:
            # Surface validation or depth-related failures directly to the user
            logger.error(f"GatewayConnectionError during OAuth fetch for {gateway_id}: {gce}")
            raise GatewayConnectionError(f"Failed to fetch tools after OAuth: {str(gce)}")
        except Exception as e:
            logger.error(f"Failed to fetch tools after OAuth for gateway {gateway_id}: {e}")
            raise GatewayConnectionError(f"Failed to fetch tools after OAuth: {str(e)}")

    async def list_gateways(
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
    ) -> Union[tuple[List[GatewayRead], Optional[str]], Dict[str, Any]]:
        """List all registered gateways with cursor pagination and optional team filtering.

        Args:
            db: Database session
            include_inactive: Whether to include inactive gateways
            tags (Optional[List[str]]): Filter resources by tags. If provided, only resources with at least one matching tag will be returned.
            cursor: Cursor for pagination (encoded last created_at and id).
            limit: Maximum number of gateways to return. None for default, 0 for unlimited.
            page: Page number for page-based pagination (1-indexed). Mutually exclusive with cursor.
            per_page: Items per page for page-based pagination. Defaults to pagination_default_page_size.
            user_email: Email of user for team-based access control. None for no access control.
            team_id: Optional team ID to filter by specific team (requires user_email).
            visibility: Optional visibility filter (private, team, public) (requires user_email).

        Returns:
            If page is provided: Dict with {"data": [...], "pagination": {...}, "links": {...}}
            If cursor is provided or neither: tuple of (list of GatewayRead objects, next_cursor).

        Examples:
            >>> from mcpgateway.services.gateway_service import GatewayService
            >>> from unittest.mock import MagicMock, AsyncMock, patch
            >>> from mcpgateway.schemas import GatewayRead
            >>> import asyncio
            >>> service = GatewayService()
            >>> db = MagicMock()
            >>> gateway_obj = MagicMock()
            >>> db.execute.return_value.scalars.return_value.all.return_value = [gateway_obj]
            >>> gateway_read_obj = MagicMock(spec=GatewayRead)
            >>> service.convert_gateway_to_read = MagicMock(return_value=gateway_read_obj)
            >>> # Mock the cache to bypass caching logic
            >>> with patch('mcpgateway.services.gateway_service._get_registry_cache') as mock_cache_factory:
            ...     mock_cache = MagicMock()
            ...     mock_cache.get = AsyncMock(return_value=None)
            ...     mock_cache.set = AsyncMock(return_value=None)
            ...     mock_cache.hash_filters = MagicMock(return_value="hash")
            ...     mock_cache_factory.return_value = mock_cache
            ...     gateways, cursor = asyncio.run(service.list_gateways(db))
            ...     gateways == [gateway_read_obj] and cursor is None
            True

            >>> # Test empty result
            >>> db.execute.return_value.scalars.return_value.all.return_value = []
            >>> with patch('mcpgateway.services.gateway_service._get_registry_cache') as mock_cache_factory:
            ...     mock_cache = MagicMock()
            ...     mock_cache.get = AsyncMock(return_value=None)
            ...     mock_cache.set = AsyncMock(return_value=None)
            ...     mock_cache.hash_filters = MagicMock(return_value="hash")
            ...     mock_cache_factory.return_value = mock_cache
            ...     empty_result, cursor = asyncio.run(service.list_gateways(db))
            ...     empty_result == [] and cursor is None
            True
        """
        # Check cache for first page only - skip when user_email provided or page based pagination
        cache = _get_registry_cache()
        if cursor is None and user_email is None and page is None:
            filters_hash = cache.hash_filters(include_inactive=include_inactive, tags=sorted(tags) if tags else None)
            cached = await cache.get("gateways", filters_hash)
            if cached is not None:
                # Reconstruct GatewayRead objects from cached dicts
                cached_gateways = [GatewayRead.model_validate(g) for g in cached["gateways"]]
                return (cached_gateways, cached.get("next_cursor"))

        # Build base query with ordering
        query = select(DbGateway).order_by(desc(DbGateway.created_at), desc(DbGateway.id))

        # Apply active/inactive filter
        if not include_inactive:
            query = query.where(DbGateway.enabled)
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
                    and_(DbGateway.team_id == team_id, DbGateway.visibility.in_(["team", "public"])),
                    and_(DbGateway.team_id == team_id, DbGateway.owner_email == user_email),
                ]
                query = query.where(or_(*access_conditions))
            else:
                # General access: user's gateways + public gateways + team gateways
                access_conditions = [
                    DbGateway.owner_email == user_email,
                    DbGateway.visibility == "public",
                ]
                if team_ids:
                    access_conditions.append(and_(DbGateway.team_id.in_(team_ids), DbGateway.visibility.in_(["team", "public"])))
                query = query.where(or_(*access_conditions))

            if visibility:
                query = query.where(DbGateway.visibility == visibility)

        # Add tag filtering if tags are provided
        if tags:
            query = query.where(json_contains_expr(db, DbGateway.tags, tags, match_any=True))
        # Use unified pagination helper - handles both page and cursor pagination
        pag_result = await unified_paginate(
            db=db,
            query=query,
            page=page,
            per_page=per_page,
            cursor=cursor,
            limit=limit,
            base_url="/admin/gateways",  # Used for page-based links
            query_params={"include_inactive": include_inactive} if include_inactive else {},
        )

        next_cursor = None
        # Extract gateways based on pagination type
        if page is not None:
            # Page-based: pag_result is a dict
            gateways_db = pag_result["data"]
        else:
            # Cursor-based: pag_result is a tuple
            gateways_db, next_cursor = pag_result

        # Fetch team names for the gateways (common for both pagination types)
        team_ids_set = {s.team_id for s in gateways_db if s.team_id}
        team_map = {}
        if team_ids_set:
            teams = db.execute(select(EmailTeam.id, EmailTeam.name).where(EmailTeam.id.in_(team_ids_set), EmailTeam.is_active.is_(True))).all()
            team_map = {team.id: team.name for team in teams}

        db.commit()  # Release transaction to avoid idle-in-transaction

        # Convert to GatewayRead (common for both pagination types)
        result = []
        for s in gateways_db:
            s.team = team_map.get(s.team_id) if s.team_id else None
            result.append(self.convert_gateway_to_read(s))

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
                cache_data = {"gateways": [s.model_dump(mode="json") for s in result], "next_cursor": next_cursor}
                await cache.set("gateways", cache_data, filters_hash)
            except AttributeError:
                pass  # Skip caching if result objects don't support model_dump (e.g., in doctests)

        return (result, next_cursor)

    async def list_gateways_for_user(
        self, db: Session, user_email: str, team_id: Optional[str] = None, visibility: Optional[str] = None, include_inactive: bool = False, skip: int = 0, limit: int = 100
    ) -> List[GatewayRead]:
        """
        DEPRECATED: Use list_gateways() with user_email parameter instead.

        This method is maintained for backward compatibility but is no longer used.
        New code should call list_gateways() with user_email, team_id, and visibility parameters.

        List gateways user has access to with team filtering.

        Args:
            db: Database session
            user_email: Email of the user requesting gateways
            team_id: Optional team ID to filter by specific team
            visibility: Optional visibility filter (private, team, public)
            include_inactive: Whether to include inactive gateways
            skip: Number of gateways to skip for pagination
            limit: Maximum number of gateways to return

        Returns:
            List[GatewayRead]: Gateways the user has access to
        """
        # Build query following existing patterns from list_gateways()
        team_service = TeamManagementService(db)
        user_teams = await team_service.get_user_teams(user_email)
        team_ids = [team.id for team in user_teams]

        query = select(DbGateway)

        # Apply active/inactive filter
        if not include_inactive:
            query = query.where(DbGateway.enabled.is_(True))

        if team_id:
            if team_id not in team_ids:
                return []  # No access to team

            access_conditions = []
            # Filter by specific team

            # Team-owned gateways (team-scoped gateways)
            access_conditions.append(and_(DbGateway.team_id == team_id, DbGateway.visibility.in_(["team", "public"])))

            access_conditions.append(and_(DbGateway.team_id == team_id, DbGateway.owner_email == user_email))

            # Also include global public gateways (no team_id) so public gateways are visible regardless of selected team
            access_conditions.append(DbGateway.visibility == "public")

            query = query.where(or_(*access_conditions))
        else:
            # Get user's accessible teams
            # Build access conditions following existing patterns
            access_conditions = []
            # 1. User's personal resources (owner_email matches)
            access_conditions.append(DbGateway.owner_email == user_email)
            # 2. Team resources where user is member
            if team_ids:
                access_conditions.append(and_(DbGateway.team_id.in_(team_ids), DbGateway.visibility.in_(["team", "public"])))
            # 3. Public resources (if visibility allows)
            access_conditions.append(DbGateway.visibility == "public")

            query = query.where(or_(*access_conditions))

        # Apply visibility filter if specified
        if visibility:
            query = query.where(DbGateway.visibility == visibility)

        # Apply pagination following existing patterns
        query = query.offset(skip).limit(limit)

        gateways = db.execute(query).scalars().all()

        # Batch fetch team names to avoid N+1 queries
        gateway_team_ids = {g.team_id for g in gateways if g.team_id}
        team_names = {}
        if gateway_team_ids:
            teams = db.query(EmailTeam).filter(EmailTeam.id.in_(gateway_team_ids), EmailTeam.is_active.is_(True)).all()
            team_names = {team.id: team.name for team in teams}

        db.commit()  # Release transaction to avoid idle-in-transaction

        result = []
        for g in gateways:
            g.team = team_names.get(g.team_id) if g.team_id else None
            logger.info(f"Gateway: {g.team_id}, Team: {g.team}")
            result.append(GatewayRead.model_validate(self._prepare_gateway_for_read(g)).masked())
        return result

    async def update_gateway(
        self,
        db: Session,
        gateway_id: str,
        gateway_update: GatewayUpdate,
        modified_by: Optional[str] = None,
        modified_from_ip: Optional[str] = None,
        modified_via: Optional[str] = None,
        modified_user_agent: Optional[str] = None,
        include_inactive: bool = True,
        user_email: Optional[str] = None,
    ) -> GatewayRead:
        """Update a gateway.

        Args:
            db: Database session
            gateway_id: Gateway ID to update
            gateway_update: Updated gateway data
            modified_by: Username of the person modifying the gateway
            modified_from_ip: IP address where the modification request originated
            modified_via: Source of modification (ui/api/import)
            modified_user_agent: User agent string from the modification request
            include_inactive: Whether to include inactive gateways
            user_email: Email of user performing update (for ownership check)

        Returns:
            Updated gateway information

        Raises:
            GatewayNotFoundError: If gateway not found
            PermissionError: If user doesn't own the gateway
            GatewayError: For other update errors
            GatewayNameConflictError: If gateway name conflict occurs
            IntegrityError: If there is a database integrity error
            ValidationError: If validation fails
        """
        try:  # pylint: disable=too-many-nested-blocks
            # Acquire row lock and eager-load relationships while locked so
            # concurrent updates are serialized on Postgres.
            gateway = get_for_update(
                db,
                DbGateway,
                gateway_id,
                options=[
                    selectinload(DbGateway.tools),
                    selectinload(DbGateway.resources),
                    selectinload(DbGateway.prompts),
                ],
            )
            if not gateway:
                raise GatewayNotFoundError(f"Gateway not found: {gateway_id}")

            # Check ownership if user_email provided
            if user_email:
                # First-Party
                from mcpgateway.services.permission_service import PermissionService  # pylint: disable=import-outside-toplevel

                permission_service = PermissionService(db)
                if not await permission_service.check_resource_ownership(user_email, gateway):
                    raise PermissionError("Only the owner can update this gateway")

            if gateway.enabled or include_inactive:
                # Check for name conflicts if name is being changed
                if gateway_update.name is not None and gateway_update.name != gateway.name:
                    # existing_gateway = db.execute(select(DbGateway).where(DbGateway.name == gateway_update.name).where(DbGateway.id != gateway_id)).scalar_one_or_none()

                    # if existing_gateway:
                    #     raise GatewayNameConflictError(
                    #         gateway_update.name,
                    #         enabled=existing_gateway.enabled,
                    #         gateway_id=existing_gateway.id,
                    #     )
                    # Check for existing gateway with the same slug and visibility
                    new_slug = slugify(gateway_update.name)
                    if gateway_update.visibility is not None:
                        vis = gateway_update.visibility
                    else:
                        vis = gateway.visibility
                    if vis == "public":
                        # Check for existing public gateway with the same slug (row-locked)
                        existing_gateway = get_for_update(
                            db,
                            DbGateway,
                            where=and_(DbGateway.slug == new_slug, DbGateway.visibility == "public", DbGateway.id != gateway_id),
                        )
                        if existing_gateway:
                            raise GatewayNameConflictError(
                                new_slug,
                                enabled=existing_gateway.enabled,
                                gateway_id=existing_gateway.id,
                                visibility=existing_gateway.visibility,
                            )
                    elif vis == "team" and gateway.team_id:
                        # Check for existing team gateway with the same slug (row-locked)
                        existing_gateway = get_for_update(
                            db,
                            DbGateway,
                            where=and_(DbGateway.slug == new_slug, DbGateway.visibility == "team", DbGateway.team_id == gateway.team_id, DbGateway.id != gateway_id),
                        )
                        if existing_gateway:
                            raise GatewayNameConflictError(
                                new_slug,
                                enabled=existing_gateway.enabled,
                                gateway_id=existing_gateway.id,
                                visibility=existing_gateway.visibility,
                            )
                # Check for existing gateway with the same URL and visibility
                normalized_url = ""
                if gateway_update.url is not None:
                    normalized_url = self.normalize_url(str(gateway_update.url))
                else:
                    normalized_url = None

                # Prepare decoded auth_value for uniqueness check
                decoded_auth_value = None
                if gateway_update.auth_value:
                    if isinstance(gateway_update.auth_value, str):
                        try:
                            decoded_auth_value = decode_auth(gateway_update.auth_value)
                        except Exception as e:
                            logger.warning(f"Failed to decode provided auth_value: {e}")
                    elif isinstance(gateway_update.auth_value, dict):
                        decoded_auth_value = gateway_update.auth_value

                # Determine final values for uniqueness check
                final_auth_value = decoded_auth_value if gateway_update.auth_value is not None else (decode_auth(gateway.auth_value) if isinstance(gateway.auth_value, str) else gateway.auth_value)
                final_oauth_config = gateway_update.oauth_config if gateway_update.oauth_config is not None else gateway.oauth_config
                final_visibility = gateway_update.visibility if gateway_update.visibility is not None else gateway.visibility

                # Check for duplicates with updated credentials
                if not gateway_update.one_time_auth:
                    duplicate_gateway = self._check_gateway_uniqueness(
                        db=db,
                        url=normalized_url,
                        auth_value=final_auth_value,
                        oauth_config=final_oauth_config,
                        team_id=gateway.team_id,
                        visibility=final_visibility,
                        gateway_id=gateway_id,  # Exclude current gateway from check
                        owner_email=user_email,
                    )

                    if duplicate_gateway:
                        raise GatewayDuplicateConflictError(duplicate_gateway=duplicate_gateway)

                # FIX for Issue #1025: Determine if URL actually changed before we update it
                # We need this early because we update gateway.url below, and need to know
                # if it actually changed to decide whether to re-fetch tools
                # tools/resoures/prompts are need to be re-fetched not only if URL changed , in case any update like authentication and visibility changed
                # url_changed = gateway_update.url is not None and self.normalize_url(str(gateway_update.url)) != gateway.url

                # Update fields if provided
                if gateway_update.name is not None:
                    gateway.name = gateway_update.name
                    gateway.slug = slugify(gateway_update.name)
                if gateway_update.url is not None:
                    # Normalize the updated URL
                    gateway.url = self.normalize_url(str(gateway_update.url))
                if gateway_update.description is not None:
                    gateway.description = gateway_update.description
                if gateway_update.transport is not None:
                    gateway.transport = gateway_update.transport
                if gateway_update.tags is not None:
                    gateway.tags = gateway_update.tags
                if gateway_update.visibility is not None:
                    gateway.visibility = gateway_update.visibility
                if gateway_update.visibility is not None:
                    gateway.visibility = gateway_update.visibility
                if gateway_update.passthrough_headers is not None:
                    if isinstance(gateway_update.passthrough_headers, list):
                        gateway.passthrough_headers = gateway_update.passthrough_headers
                    else:
                        if isinstance(gateway_update.passthrough_headers, str):
                            parsed: List[str] = [h.strip() for h in gateway_update.passthrough_headers.split(",") if h.strip()]
                            gateway.passthrough_headers = parsed
                        else:
                            raise GatewayError("Invalid passthrough_headers format: must be list[str] or comma-separated string")

                    logger.info("Updated passthrough_headers for gateway {gateway.id}: {gateway.passthrough_headers}")

                if getattr(gateway, "auth_type", None) is not None:
                    gateway.auth_type = gateway_update.auth_type

                    # If auth_type is empty, update the auth_value too
                    if gateway_update.auth_type == "":
                        gateway.auth_value = cast(Any, "")

                    # if auth_type is not None and only then check auth_value
                # Handle OAuth configuration updates
                if gateway_update.oauth_config is not None:
                    gateway.oauth_config = gateway_update.oauth_config

                # Handle auth_value updates (both existing and new auth values)
                token = gateway_update.auth_token
                password = gateway_update.auth_password
                header_value = gateway_update.auth_header_value

                # Support multiple custom headers on update
                if hasattr(gateway_update, "auth_headers") and gateway_update.auth_headers:
                    existing_auth_raw = getattr(gateway, "auth_value", {}) or {}
                    if isinstance(existing_auth_raw, str):
                        try:
                            existing_auth = decode_auth(existing_auth_raw)
                        except Exception:
                            existing_auth = {}
                    elif isinstance(existing_auth_raw, dict):
                        existing_auth = existing_auth_raw
                    else:
                        existing_auth = {}

                    header_dict: Dict[str, str] = {}
                    for header in gateway_update.auth_headers:
                        key = header.get("key")
                        if not key:
                            continue
                        value = header.get("value", "")
                        if value == settings.masked_auth_value and key in existing_auth:
                            header_dict[key] = existing_auth[key]
                        else:
                            header_dict[key] = value
                    gateway.auth_value = header_dict  # Store as dict for DB JSON field
                elif settings.masked_auth_value not in (token, password, header_value):
                    # Check if values differ from existing ones or if setting for first time
                    decoded_auth = decode_auth(gateway_update.auth_value) if gateway_update.auth_value else {}
                    current_auth = getattr(gateway, "auth_value", {}) or {}
                    if current_auth != decoded_auth:
                        gateway.auth_value = decoded_auth

                # Handle query_param auth updates with service-layer enforcement
                auth_query_params_decrypted: Optional[Dict[str, str]] = None
                init_url = gateway.url

                # Check if updating to query_param auth or updating existing query_param credentials
                is_switching_to_queryparam = gateway_update.auth_type == "query_param"
                is_updating_queryparam_creds = gateway.auth_type == "query_param" and (gateway_update.auth_query_param_key is not None or gateway_update.auth_query_param_value is not None)
                is_url_changing = gateway_update.url is not None and self.normalize_url(str(gateway_update.url)) != gateway.url

                if is_switching_to_queryparam or is_updating_queryparam_creds or (is_url_changing and gateway.auth_type == "query_param"):
                    # Service-layer enforcement: Check feature flag
                    if not settings.insecure_allow_queryparam_auth:
                        # Grandfather clause: Allow updates to existing query_param gateways
                        # unless they're trying to change credentials
                        if is_switching_to_queryparam or is_updating_queryparam_creds:
                            raise ValueError("Query parameter authentication is disabled. " "Set INSECURE_ALLOW_QUERYPARAM_AUTH=true to enable.")

                    # Service-layer enforcement: Check host allowlist
                    if settings.insecure_queryparam_auth_allowed_hosts:
                        check_url = str(gateway_update.url) if gateway_update.url else gateway.url
                        parsed = urlparse(check_url)
                        hostname = (parsed.hostname or "").lower()
                        if hostname not in settings.insecure_queryparam_auth_allowed_hosts:
                            allowed = ", ".join(settings.insecure_queryparam_auth_allowed_hosts)
                            raise ValueError(f"Host '{hostname}' is not in the allowed hosts for query param auth. Allowed: {allowed}")

                    # Process query_param auth credentials
                    param_key = getattr(gateway_update, "auth_query_param_key", None) or (next(iter(gateway.auth_query_params.keys()), None) if gateway.auth_query_params else None)
                    param_value = getattr(gateway_update, "auth_query_param_value", None)

                    if param_key:
                        if param_value:
                            # Get the actual secret value
                            if hasattr(param_value, "get_secret_value"):
                                raw_value = param_value.get_secret_value()
                            else:
                                raw_value = str(param_value)
                            # Encrypt for storage
                            encrypted_value = encode_auth({param_key: raw_value})
                            gateway.auth_query_params = {param_key: encrypted_value}
                            auth_query_params_decrypted = {param_key: raw_value}
                        elif gateway.auth_query_params:
                            # Use existing encrypted value
                            existing_encrypted = gateway.auth_query_params.get(param_key, "")
                            if existing_encrypted:
                                decrypted = decode_auth(existing_encrypted)
                                auth_query_params_decrypted = {param_key: decrypted.get(param_key, "")}

                        # Append query params to URL for initialization
                        if auth_query_params_decrypted:
                            init_url = apply_query_param_auth(gateway.url, auth_query_params_decrypted)

                    # Update auth_type if switching
                    if is_switching_to_queryparam:
                        gateway.auth_type = "query_param"
                        gateway.auth_value = None  # Query param auth doesn't use auth_value

                elif gateway.auth_type == "query_param" and gateway.auth_query_params:
                    # Existing query_param gateway without credential changes - decrypt for init
                    first_key = next(iter(gateway.auth_query_params.keys()), None)
                    if first_key:
                        encrypted_value = gateway.auth_query_params.get(first_key, "")
                        if encrypted_value:
                            decrypted = decode_auth(encrypted_value)
                            auth_query_params_decrypted = {first_key: decrypted.get(first_key, "")}
                            init_url = apply_query_param_auth(gateway.url, auth_query_params_decrypted)

                # Try to reinitialize connection if URL actually changed
                # if url_changed:
                # Initialize empty lists in case initialization fails
                tools_to_add = []
                resources_to_add = []
                prompts_to_add = []

                try:
                    ca_certificate = getattr(gateway, "ca_certificate", None)
                    capabilities, tools, resources, prompts = await self._initialize_gateway(
                        init_url,
                        gateway.auth_value,
                        gateway.transport,
                        gateway.auth_type,
                        gateway.oauth_config,
                        ca_certificate,
                        auth_query_params=auth_query_params_decrypted,
                    )
                    new_tool_names = [tool.name for tool in tools]
                    new_resource_uris = [resource.uri for resource in resources]
                    new_prompt_names = [prompt.name for prompt in prompts]

                    if gateway_update.one_time_auth:
                        # For one-time auth, clear auth_type and auth_value after initialization
                        gateway.auth_type = "one_time_auth"
                        gateway.auth_value = None
                        gateway.oauth_config = None

                    # Update tools using helper method
                    tools_to_add = self._update_or_create_tools(db, tools, gateway, "update")

                    # Update resources using helper method
                    resources_to_add = self._update_or_create_resources(db, resources, gateway, "update")

                    # Update prompts using helper method
                    prompts_to_add = self._update_or_create_prompts(db, prompts, gateway, "update")

                    # Log newly added items
                    items_added = len(tools_to_add) + len(resources_to_add) + len(prompts_to_add)
                    if items_added > 0:
                        if tools_to_add:
                            logger.info(f"Added {len(tools_to_add)} new tools during gateway update")
                        if resources_to_add:
                            logger.info(f"Added {len(resources_to_add)} new resources during gateway update")
                        if prompts_to_add:
                            logger.info(f"Added {len(prompts_to_add)} new prompts during gateway update")
                        logger.info(f"Total {items_added} new items added during gateway update")

                    # Count items before cleanup for logging

                    # Bulk delete tools that are no longer available from the gateway
                    # Use chunking to avoid SQLite's 999 parameter limit for IN clauses
                    stale_tool_ids = [tool.id for tool in gateway.tools if tool.original_name not in new_tool_names]
                    if stale_tool_ids:
                        # Delete child records first to avoid FK constraint violations
                        for i in range(0, len(stale_tool_ids), 500):
                            chunk = stale_tool_ids[i : i + 500]
                            db.execute(delete(ToolMetric).where(ToolMetric.tool_id.in_(chunk)))
                            db.execute(delete(server_tool_association).where(server_tool_association.c.tool_id.in_(chunk)))
                            db.execute(delete(DbTool).where(DbTool.id.in_(chunk)))

                    # Bulk delete resources that are no longer available from the gateway
                    stale_resource_ids = [resource.id for resource in gateway.resources if resource.uri not in new_resource_uris]
                    if stale_resource_ids:
                        # Delete child records first to avoid FK constraint violations
                        for i in range(0, len(stale_resource_ids), 500):
                            chunk = stale_resource_ids[i : i + 500]
                            db.execute(delete(ResourceMetric).where(ResourceMetric.resource_id.in_(chunk)))
                            db.execute(delete(server_resource_association).where(server_resource_association.c.resource_id.in_(chunk)))
                            db.execute(delete(ResourceSubscription).where(ResourceSubscription.resource_id.in_(chunk)))
                            db.execute(delete(DbResource).where(DbResource.id.in_(chunk)))

                    # Bulk delete prompts that are no longer available from the gateway
                    stale_prompt_ids = [prompt.id for prompt in gateway.prompts if prompt.original_name not in new_prompt_names]
                    if stale_prompt_ids:
                        # Delete child records first to avoid FK constraint violations
                        for i in range(0, len(stale_prompt_ids), 500):
                            chunk = stale_prompt_ids[i : i + 500]
                            db.execute(delete(PromptMetric).where(PromptMetric.prompt_id.in_(chunk)))
                            db.execute(delete(server_prompt_association).where(server_prompt_association.c.prompt_id.in_(chunk)))
                            db.execute(delete(DbPrompt).where(DbPrompt.id.in_(chunk)))

                    # Expire gateway to clear cached relationships after bulk deletes
                    # This prevents SQLAlchemy from trying to re-delete already-deleted items
                    if stale_tool_ids or stale_resource_ids or stale_prompt_ids:
                        db.expire(gateway)

                    gateway.capabilities = capabilities

                    # Register capabilities for notification-driven actions
                    register_gateway_capabilities_for_notifications(gateway.id, capabilities)

                    gateway.tools = [tool for tool in gateway.tools if tool.original_name in new_tool_names]  # keep only still-valid rows
                    gateway.resources = [resource for resource in gateway.resources if resource.uri in new_resource_uris]  # keep only still-valid rows
                    gateway.prompts = [prompt for prompt in gateway.prompts if prompt.original_name in new_prompt_names]  # keep only still-valid rows

                    # Log cleanup results
                    tools_removed = len(stale_tool_ids)
                    resources_removed = len(stale_resource_ids)
                    prompts_removed = len(stale_prompt_ids)

                    if tools_removed > 0:
                        logger.info(f"Removed {tools_removed} tools no longer available during gateway update")
                    if resources_removed > 0:
                        logger.info(f"Removed {resources_removed} resources no longer available during gateway update")
                    if prompts_removed > 0:
                        logger.info(f"Removed {prompts_removed} prompts no longer available during gateway update")

                    gateway.last_seen = datetime.now(timezone.utc)

                    # Add new items to database session in chunks to prevent lock escalation
                    chunk_size = 50

                    if tools_to_add:
                        for i in range(0, len(tools_to_add), chunk_size):
                            chunk = tools_to_add[i : i + chunk_size]
                            db.add_all(chunk)
                            db.flush()
                    if resources_to_add:
                        for i in range(0, len(resources_to_add), chunk_size):
                            chunk = resources_to_add[i : i + chunk_size]
                            db.add_all(chunk)
                            db.flush()
                    if prompts_to_add:
                        for i in range(0, len(prompts_to_add), chunk_size):
                            chunk = prompts_to_add[i : i + chunk_size]
                            db.add_all(chunk)
                            db.flush()

                    # Update tracking with new URL
                    self._active_gateways.discard(gateway.url)
                    self._active_gateways.add(gateway.url)
                except Exception as e:
                    logger.warning(f"Failed to initialize updated gateway: {e}")

                # Update tags if provided
                if gateway_update.tags is not None:
                    gateway.tags = gateway_update.tags

                # Update metadata fields
                gateway.updated_at = datetime.now(timezone.utc)
                if modified_by:
                    gateway.modified_by = modified_by
                if modified_from_ip:
                    gateway.modified_from_ip = modified_from_ip
                if modified_via:
                    gateway.modified_via = modified_via
                if modified_user_agent:
                    gateway.modified_user_agent = modified_user_agent
                if hasattr(gateway, "version") and gateway.version is not None:
                    gateway.version = gateway.version + 1
                else:
                    gateway.version = 1

                db.commit()
                db.refresh(gateway)

                # Invalidate cache after successful update
                cache = _get_registry_cache()
                await cache.invalidate_gateways()
                tool_lookup_cache = _get_tool_lookup_cache()
                await tool_lookup_cache.invalidate_gateway(str(gateway.id))
                # Also invalidate tags cache since gateway tags may have changed
                # First-Party
                from mcpgateway.cache.admin_stats_cache import admin_stats_cache  # pylint: disable=import-outside-toplevel

                await admin_stats_cache.invalidate_tags()

                # Notify subscribers
                await self._notify_gateway_updated(gateway)

                logger.info(f"Updated gateway: {gateway.name}")

                # Structured logging: Audit trail for gateway update
                audit_trail.log_action(
                    user_id=user_email or modified_by or "system",
                    action="update_gateway",
                    resource_type="gateway",
                    resource_id=str(gateway.id),
                    resource_name=gateway.name,
                    user_email=user_email,
                    team_id=gateway.team_id,
                    client_ip=modified_from_ip,
                    user_agent=modified_user_agent,
                    new_values={
                        "name": gateway.name,
                        "url": gateway.url,
                        "version": gateway.version,
                    },
                    context={
                        "modified_via": modified_via,
                    },
                    db=db,
                )

                # Structured logging: Log successful gateway update
                structured_logger.log(
                    level="INFO",
                    message="Gateway updated successfully",
                    event_type="gateway_updated",
                    component="gateway_service",
                    user_id=modified_by,
                    user_email=user_email,
                    team_id=gateway.team_id,
                    resource_type="gateway",
                    resource_id=str(gateway.id),
                    custom_fields={
                        "gateway_name": gateway.name,
                        "version": gateway.version,
                    },
                    db=db,
                )

                gateway.team = self._get_team_name(db, getattr(gateway, "team_id", None))

                return GatewayRead.model_validate(self._prepare_gateway_for_read(gateway))
            # Gateway is inactive and include_inactive is False → skip update, return None
            return None
        except GatewayNameConflictError as ge:
            logger.error(f"GatewayNameConflictError in group: {ge}")

            structured_logger.log(
                level="WARNING",
                message="Gateway update failed due to name conflict",
                event_type="gateway_name_conflict",
                component="gateway_service",
                user_email=user_email,
                resource_type="gateway",
                resource_id=gateway_id,
                error=ge,
                db=db,
            )
            raise ge
        except GatewayNotFoundError as gnfe:
            logger.error(f"GatewayNotFoundError: {gnfe}")

            structured_logger.log(
                level="ERROR",
                message="Gateway update failed - gateway not found",
                event_type="gateway_not_found",
                component="gateway_service",
                user_email=user_email,
                resource_type="gateway",
                resource_id=gateway_id,
                error=gnfe,
                db=db,
            )
            raise gnfe
        except IntegrityError as ie:
            logger.error(f"IntegrityErrors in group: {ie}")

            structured_logger.log(
                level="ERROR",
                message="Gateway update failed due to database integrity error",
                event_type="gateway_update_failed",
                component="gateway_service",
                user_email=user_email,
                resource_type="gateway",
                resource_id=gateway_id,
                error=ie,
                db=db,
            )
            raise ie
        except PermissionError as pe:
            db.rollback()

            structured_logger.log(
                level="WARNING",
                message="Gateway update failed due to permission error",
                event_type="gateway_update_permission_denied",
                component="gateway_service",
                user_email=user_email,
                resource_type="gateway",
                resource_id=gateway_id,
                error=pe,
                db=db,
            )
            raise
        except Exception as e:
            db.rollback()

            structured_logger.log(
                level="ERROR",
                message="Gateway update failed",
                event_type="gateway_update_failed",
                component="gateway_service",
                user_email=user_email,
                resource_type="gateway",
                resource_id=gateway_id,
                error=e,
                db=db,
            )
            raise GatewayError(f"Failed to update gateway: {str(e)}")

    async def get_gateway(self, db: Session, gateway_id: str, include_inactive: bool = True) -> GatewayRead:
        """Get a gateway by its ID.

        Args:
            db: Database session
            gateway_id: Gateway ID
            include_inactive: Whether to include inactive gateways

        Returns:
            GatewayRead object

        Raises:
            GatewayNotFoundError: If the gateway is not found

        Examples:
            >>> from unittest.mock import MagicMock
            >>> from mcpgateway.schemas import GatewayRead
            >>> service = GatewayService()
            >>> db = MagicMock()
            >>> gateway_mock = MagicMock()
            >>> gateway_mock.enabled = True
            >>> db.get.return_value = gateway_mock
            >>> mocked_gateway_read = MagicMock()
            >>> mocked_gateway_read.masked.return_value = 'gateway_read'
            >>> GatewayRead.model_validate = MagicMock(return_value=mocked_gateway_read)
            >>> import asyncio
            >>> result = asyncio.run(service.get_gateway(db, 'gateway_id'))
            >>> result == 'gateway_read'
            True

            >>> # Test with inactive gateway but include_inactive=True
            >>> gateway_mock.enabled = False
            >>> result_inactive = asyncio.run(service.get_gateway(db, 'gateway_id', include_inactive=True))
            >>> result_inactive == 'gateway_read'
            True

            >>> # Test gateway not found
            >>> db.get.return_value = None
            >>> try:
            ...     asyncio.run(service.get_gateway(db, 'missing_id'))
            ... except GatewayNotFoundError as e:
            ...     'Gateway not found: missing_id' in str(e)
            True

            >>> # Test inactive gateway with include_inactive=False
            >>> gateway_mock.enabled = False
            >>> db.get.return_value = gateway_mock
            >>> try:
            ...     asyncio.run(service.get_gateway(db, 'gateway_id', include_inactive=False))
            ... except GatewayNotFoundError as e:
            ...     'Gateway not found: gateway_id' in str(e)
            True
        """
        gateway = db.get(DbGateway, gateway_id)

        if not gateway:
            raise GatewayNotFoundError(f"Gateway not found: {gateway_id}")

        if gateway.enabled or include_inactive:
            gateway.team = self._get_team_name(db, getattr(gateway, "team_id", None))

            # Structured logging: Log gateway view
            structured_logger.log(
                level="INFO",
                message="Gateway retrieved successfully",
                event_type="gateway_viewed",
                component="gateway_service",
                team_id=getattr(gateway, "team_id", None),
                resource_type="gateway",
                resource_id=str(gateway.id),
                custom_fields={
                    "gateway_name": gateway.name,
                    "gateway_url": gateway.url,
                    "include_inactive": include_inactive,
                },
                db=db,
            )

            return GatewayRead.model_validate(self._prepare_gateway_for_read(gateway)).masked()

        raise GatewayNotFoundError(f"Gateway not found: {gateway_id}")

    async def set_gateway_state(self, db: Session, gateway_id: str, activate: bool, reachable: bool = True, only_update_reachable: bool = False, user_email: Optional[str] = None) -> GatewayRead:
        """
        Set the activation status of a gateway.

        Args:
            db: Database session
            gateway_id: Gateway ID
            activate: True to activate, False to deactivate
            reachable: Whether the gateway is reachable
            only_update_reachable: Only update reachable status
            user_email: Optional[str] The email of the user to check if the user has permission to modify.

        Returns:
            The updated GatewayRead object

        Raises:
            GatewayNotFoundError: If the gateway is not found
            GatewayError: For other errors
            PermissionError: If user doesn't own the agent.
        """
        try:
            # Eager-load collections for the gateway. Note: we don't use FOR UPDATE
            # here because _initialize_gateway does network I/O, and holding a row
            # lock during network calls would block other operations and risk timeouts.
            gateway = db.execute(
                select(DbGateway)
                .options(
                    selectinload(DbGateway.tools),
                    selectinload(DbGateway.resources),
                    selectinload(DbGateway.prompts),
                )
                .where(DbGateway.id == gateway_id)
            ).scalar_one_or_none()
            if not gateway:
                raise GatewayNotFoundError(f"Gateway not found: {gateway_id}")

            if user_email:
                # First-Party
                from mcpgateway.services.permission_service import PermissionService  # pylint: disable=import-outside-toplevel

                permission_service = PermissionService(db)
                if not await permission_service.check_resource_ownership(user_email, gateway):
                    raise PermissionError("Only the owner can activate the gateway" if activate else "Only the owner can deactivate the gateway")

            # Update status if it's different
            if (gateway.enabled != activate) or (gateway.reachable != reachable):
                gateway.enabled = activate
                gateway.reachable = reachable
                gateway.updated_at = datetime.now(timezone.utc)
                # Update tracking
                if activate and reachable:
                    self._active_gateways.add(gateway.url)

                    # Initialize empty lists in case initialization fails
                    tools_to_add = []
                    resources_to_add = []
                    prompts_to_add = []

                    # Try to initialize if activating
                    try:
                        capabilities, tools, resources, prompts = await self._initialize_gateway(gateway.url, gateway.auth_value, gateway.transport, gateway.auth_type, gateway.oauth_config)
                        new_tool_names = [tool.name for tool in tools]
                        new_resource_uris = [resource.uri for resource in resources]
                        new_prompt_names = [prompt.name for prompt in prompts]

                        # Update tools, resources, and prompts using helper methods
                        tools_to_add = self._update_or_create_tools(db, tools, gateway, "rediscovery")
                        resources_to_add = self._update_or_create_resources(db, resources, gateway, "rediscovery")
                        prompts_to_add = self._update_or_create_prompts(db, prompts, gateway, "rediscovery")

                        # Log newly added items
                        items_added = len(tools_to_add) + len(resources_to_add) + len(prompts_to_add)
                        if items_added > 0:
                            if tools_to_add:
                                logger.info(f"Added {len(tools_to_add)} new tools during gateway reactivation")
                            if resources_to_add:
                                logger.info(f"Added {len(resources_to_add)} new resources during gateway reactivation")
                            if prompts_to_add:
                                logger.info(f"Added {len(prompts_to_add)} new prompts during gateway reactivation")
                            logger.info(f"Total {items_added} new items added during gateway reactivation")

                        # Count items before cleanup for logging

                        # Bulk delete tools that are no longer available from the gateway
                        # Use chunking to avoid SQLite's 999 parameter limit for IN clauses
                        stale_tool_ids = [tool.id for tool in gateway.tools if tool.original_name not in new_tool_names]
                        if stale_tool_ids:
                            # Delete child records first to avoid FK constraint violations
                            for i in range(0, len(stale_tool_ids), 500):
                                chunk = stale_tool_ids[i : i + 500]
                                db.execute(delete(ToolMetric).where(ToolMetric.tool_id.in_(chunk)))
                                db.execute(delete(server_tool_association).where(server_tool_association.c.tool_id.in_(chunk)))
                                db.execute(delete(DbTool).where(DbTool.id.in_(chunk)))

                        # Bulk delete resources that are no longer available from the gateway
                        stale_resource_ids = [resource.id for resource in gateway.resources if resource.uri not in new_resource_uris]
                        if stale_resource_ids:
                            # Delete child records first to avoid FK constraint violations
                            for i in range(0, len(stale_resource_ids), 500):
                                chunk = stale_resource_ids[i : i + 500]
                                db.execute(delete(ResourceMetric).where(ResourceMetric.resource_id.in_(chunk)))
                                db.execute(delete(server_resource_association).where(server_resource_association.c.resource_id.in_(chunk)))
                                db.execute(delete(ResourceSubscription).where(ResourceSubscription.resource_id.in_(chunk)))
                                db.execute(delete(DbResource).where(DbResource.id.in_(chunk)))

                        # Bulk delete prompts that are no longer available from the gateway
                        stale_prompt_ids = [prompt.id for prompt in gateway.prompts if prompt.original_name not in new_prompt_names]
                        if stale_prompt_ids:
                            # Delete child records first to avoid FK constraint violations
                            for i in range(0, len(stale_prompt_ids), 500):
                                chunk = stale_prompt_ids[i : i + 500]
                                db.execute(delete(PromptMetric).where(PromptMetric.prompt_id.in_(chunk)))
                                db.execute(delete(server_prompt_association).where(server_prompt_association.c.prompt_id.in_(chunk)))
                                db.execute(delete(DbPrompt).where(DbPrompt.id.in_(chunk)))

                        # Expire gateway to clear cached relationships after bulk deletes
                        # This prevents SQLAlchemy from trying to re-delete already-deleted items
                        if stale_tool_ids or stale_resource_ids or stale_prompt_ids:
                            db.expire(gateway)

                        gateway.capabilities = capabilities

                        # Register capabilities for notification-driven actions
                        register_gateway_capabilities_for_notifications(gateway.id, capabilities)

                        gateway.tools = [tool for tool in gateway.tools if tool.original_name in new_tool_names]  # keep only still-valid rows
                        gateway.resources = [resource for resource in gateway.resources if resource.uri in new_resource_uris]  # keep only still-valid rows
                        gateway.prompts = [prompt for prompt in gateway.prompts if prompt.original_name in new_prompt_names]  # keep only still-valid rows

                        # Log cleanup results
                        tools_removed = len(stale_tool_ids)
                        resources_removed = len(stale_resource_ids)
                        prompts_removed = len(stale_prompt_ids)

                        if tools_removed > 0:
                            logger.info(f"Removed {tools_removed} tools no longer available during gateway reactivation")
                        if resources_removed > 0:
                            logger.info(f"Removed {resources_removed} resources no longer available during gateway reactivation")
                        if prompts_removed > 0:
                            logger.info(f"Removed {prompts_removed} prompts no longer available during gateway reactivation")

                        gateway.last_seen = datetime.now(timezone.utc)

                        # Add new items to database session in chunks to prevent lock escalation
                        chunk_size = 50

                        if tools_to_add:
                            for i in range(0, len(tools_to_add), chunk_size):
                                chunk = tools_to_add[i : i + chunk_size]
                                db.add_all(chunk)
                                db.flush()
                        if resources_to_add:
                            for i in range(0, len(resources_to_add), chunk_size):
                                chunk = resources_to_add[i : i + chunk_size]
                                db.add_all(chunk)
                                db.flush()
                        if prompts_to_add:
                            for i in range(0, len(prompts_to_add), chunk_size):
                                chunk = prompts_to_add[i : i + chunk_size]
                                db.add_all(chunk)
                                db.flush()
                    except Exception as e:
                        logger.warning(f"Failed to initialize reactivated gateway: {e}")
                else:
                    self._active_gateways.discard(gateway.url)

                db.commit()
                db.refresh(gateway)

                # Invalidate cache after status change
                cache = _get_registry_cache()
                await cache.invalidate_gateways()

                # Notify Subscribers
                if not gateway.enabled:
                    # Inactive
                    await self._notify_gateway_deactivated(gateway)
                elif gateway.enabled and not gateway.reachable:
                    # Offline (Enabled but Unreachable)
                    await self._notify_gateway_offline(gateway)
                else:
                    # Active (Enabled and Reachable)
                    await self._notify_gateway_activated(gateway)

                tools = db.query(DbTool).filter(DbTool.gateway_id == gateway_id).all()

                # Set tools state with skip_cache_invalidation=True to avoid N invalidations
                if only_update_reachable:
                    for tool in tools:
                        await self.tool_service.set_tool_state(db, tool.id, tool.enabled, reachable, skip_cache_invalidation=True)
                else:
                    for tool in tools:
                        await self.tool_service.set_tool_state(db, tool.id, activate, reachable, skip_cache_invalidation=True)

                # Invalidate tools cache once after all tool status changes
                if tools:
                    await cache.invalidate_tools()
                    tool_lookup_cache = _get_tool_lookup_cache()
                    await tool_lookup_cache.invalidate_gateway(str(gateway.id))

                logger.info(f"Gateway status: {gateway.name} - {'enabled' if activate else 'disabled'} and {'accessible' if reachable else 'inaccessible'}")

                # Structured logging: Audit trail for gateway state change
                audit_trail.log_action(
                    user_id=user_email or "system",
                    action="set_gateway_state",
                    resource_type="gateway",
                    resource_id=str(gateway.id),
                    resource_name=gateway.name,
                    user_email=user_email,
                    team_id=gateway.team_id,
                    new_values={
                        "enabled": gateway.enabled,
                        "reachable": gateway.reachable,
                    },
                    context={
                        "action": "activate" if activate else "deactivate",
                        "only_update_reachable": only_update_reachable,
                    },
                    db=db,
                )

                # Structured logging: Log successful gateway state change
                structured_logger.log(
                    level="INFO",
                    message=f"Gateway {'activated' if activate else 'deactivated'} successfully",
                    event_type="gateway_state_changed",
                    component="gateway_service",
                    user_email=user_email,
                    team_id=gateway.team_id,
                    resource_type="gateway",
                    resource_id=str(gateway.id),
                    custom_fields={
                        "gateway_name": gateway.name,
                        "enabled": gateway.enabled,
                        "reachable": gateway.reachable,
                    },
                    db=db,
                )

            gateway.team = self._get_team_name(db, getattr(gateway, "team_id", None))
            return GatewayRead.model_validate(self._prepare_gateway_for_read(gateway)).masked()

        except PermissionError as e:
            # Structured logging: Log permission error
            structured_logger.log(
                level="WARNING",
                message="Gateway state change failed due to permission error",
                event_type="gateway_state_change_permission_denied",
                component="gateway_service",
                user_email=user_email,
                resource_type="gateway",
                resource_id=gateway_id,
                error=e,
                db=db,
            )
            raise e
        except Exception as e:
            db.rollback()

            # Structured logging: Log generic gateway state change failure
            structured_logger.log(
                level="ERROR",
                message="Gateway state change failed",
                event_type="gateway_state_change_failed",
                component="gateway_service",
                user_email=user_email,
                resource_type="gateway",
                resource_id=gateway_id,
                error=e,
                db=db,
            )
            raise GatewayError(f"Failed to set gateway state: {str(e)}")

    async def _notify_gateway_updated(self, gateway: DbGateway) -> None:
        """
        Notify subscribers of gateway update.

        Args:
            gateway: Gateway to update
        """
        event = {
            "type": "gateway_updated",
            "data": {
                "id": gateway.id,
                "name": gateway.name,
                "url": gateway.url,
                "description": gateway.description,
                "enabled": gateway.enabled,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._publish_event(event)

    async def delete_gateway(self, db: Session, gateway_id: str, user_email: Optional[str] = None) -> None:
        """
        Delete a gateway by its ID.

        Args:
            db: Database session
            gateway_id: Gateway ID
            user_email: Email of user performing deletion (for ownership check)

        Raises:
            GatewayNotFoundError: If the gateway is not found
            PermissionError: If user doesn't own the gateway
            GatewayError: For other deletion errors

        Examples:
            >>> from mcpgateway.services.gateway_service import GatewayService
            >>> from unittest.mock import MagicMock
            >>> service = GatewayService()
            >>> db = MagicMock()
            >>> gateway = MagicMock()
            >>> db.get.return_value = gateway
            >>> db.delete = MagicMock()
            >>> db.commit = MagicMock()
            >>> service._notify_gateway_deleted = MagicMock()
            >>> import asyncio
            >>> try:
            ...     asyncio.run(service.delete_gateway(db, 'gateway_id', 'user@example.com'))
            ... except Exception:
            ...     pass
        """
        try:
            # Find gateway with eager loading for deletion to avoid N+1 queries
            gateway = db.execute(
                select(DbGateway)
                .options(
                    selectinload(DbGateway.tools),
                    selectinload(DbGateway.resources),
                    selectinload(DbGateway.prompts),
                )
                .where(DbGateway.id == gateway_id)
            ).scalar_one_or_none()

            if not gateway:
                raise GatewayNotFoundError(f"Gateway not found: {gateway_id}")

            # Check ownership if user_email provided
            if user_email:
                # First-Party
                from mcpgateway.services.permission_service import PermissionService  # pylint: disable=import-outside-toplevel

                permission_service = PermissionService(db)
                if not await permission_service.check_resource_ownership(user_email, gateway):
                    raise PermissionError("Only the owner can delete this gateway")

            # Store gateway info for notification before deletion
            gateway_info = {"id": gateway.id, "name": gateway.name, "url": gateway.url}
            gateway_name = gateway.name
            gateway_team_id = gateway.team_id
            gateway_url = gateway.url  # Store URL before expiring the object

            # Manually delete children first to avoid FK constraint violations
            # (passive_deletes=True means ORM won't auto-cascade, we must do it explicitly)
            # Use chunking to avoid SQLite's 999 parameter limit for IN clauses
            tool_ids = [t.id for t in gateway.tools]
            resource_ids = [r.id for r in gateway.resources]
            prompt_ids = [p.id for p in gateway.prompts]

            # Delete tool children and tools
            if tool_ids:
                for i in range(0, len(tool_ids), 500):
                    chunk = tool_ids[i : i + 500]
                    db.execute(delete(ToolMetric).where(ToolMetric.tool_id.in_(chunk)))
                    db.execute(delete(server_tool_association).where(server_tool_association.c.tool_id.in_(chunk)))
                    db.execute(delete(DbTool).where(DbTool.id.in_(chunk)))

            # Delete resource children and resources
            if resource_ids:
                for i in range(0, len(resource_ids), 500):
                    chunk = resource_ids[i : i + 500]
                    db.execute(delete(ResourceMetric).where(ResourceMetric.resource_id.in_(chunk)))
                    db.execute(delete(server_resource_association).where(server_resource_association.c.resource_id.in_(chunk)))
                    db.execute(delete(ResourceSubscription).where(ResourceSubscription.resource_id.in_(chunk)))
                    db.execute(delete(DbResource).where(DbResource.id.in_(chunk)))

            # Delete prompt children and prompts
            if prompt_ids:
                for i in range(0, len(prompt_ids), 500):
                    chunk = prompt_ids[i : i + 500]
                    db.execute(delete(PromptMetric).where(PromptMetric.prompt_id.in_(chunk)))
                    db.execute(delete(server_prompt_association).where(server_prompt_association.c.prompt_id.in_(chunk)))
                    db.execute(delete(DbPrompt).where(DbPrompt.id.in_(chunk)))

            # Expire gateway to clear cached relationships after bulk deletes
            db.expire(gateway)

            # Use DELETE with rowcount check for database-agnostic atomic delete
            # (RETURNING is not supported on MySQL/MariaDB)
            stmt = delete(DbGateway).where(DbGateway.id == gateway_id)
            result = db.execute(stmt)
            if result.rowcount == 0:
                # Gateway was already deleted by another concurrent request
                raise GatewayNotFoundError(f"Gateway not found: {gateway_id}")

            db.commit()

            # Invalidate cache after successful deletion
            cache = _get_registry_cache()
            await cache.invalidate_gateways()
            tool_lookup_cache = _get_tool_lookup_cache()
            await tool_lookup_cache.invalidate_gateway(str(gateway_id))
            # Also invalidate tags cache since gateway tags may have changed
            # First-Party
            from mcpgateway.cache.admin_stats_cache import admin_stats_cache  # pylint: disable=import-outside-toplevel

            await admin_stats_cache.invalidate_tags()

            # Update tracking
            self._active_gateways.discard(gateway_url)

            # Notify subscribers
            await self._notify_gateway_deleted(gateway_info)

            logger.info(f"Permanently deleted gateway: {gateway_name}")

            # Structured logging: Audit trail for gateway deletion
            audit_trail.log_action(
                user_id=user_email or "system",
                action="delete_gateway",
                resource_type="gateway",
                resource_id=str(gateway_info["id"]),
                resource_name=gateway_name,
                user_email=user_email,
                team_id=gateway_team_id,
                old_values={
                    "name": gateway_name,
                    "url": gateway_info["url"],
                },
                db=db,
            )

            # Structured logging: Log successful gateway deletion
            structured_logger.log(
                level="INFO",
                message="Gateway deleted successfully",
                event_type="gateway_deleted",
                component="gateway_service",
                user_email=user_email,
                team_id=gateway_team_id,
                resource_type="gateway",
                resource_id=str(gateway_info["id"]),
                custom_fields={
                    "gateway_name": gateway_name,
                    "gateway_url": gateway_info["url"],
                },
                db=db,
            )

        except PermissionError as pe:
            db.rollback()

            # Structured logging: Log permission error
            structured_logger.log(
                level="WARNING",
                message="Gateway deletion failed due to permission error",
                event_type="gateway_delete_permission_denied",
                component="gateway_service",
                user_email=user_email,
                resource_type="gateway",
                resource_id=gateway_id,
                error=pe,
                db=db,
            )
            raise
        except Exception as e:
            db.rollback()

            # Structured logging: Log generic gateway deletion failure
            structured_logger.log(
                level="ERROR",
                message="Gateway deletion failed",
                event_type="gateway_deletion_failed",
                component="gateway_service",
                user_email=user_email,
                resource_type="gateway",
                resource_id=gateway_id,
                error=e,
                db=db,
            )
            raise GatewayError(f"Failed to delete gateway: {str(e)}")

    async def forward_request(
        self, gateway_or_db, method: str, params: Optional[Dict[str, Any]] = None, app_user_email: Optional[str] = None
    ) -> Any:  # noqa: F811 # pylint: disable=function-redefined
        """
        Forward a request to a gateway or multiple gateways.

        This method handles two calling patterns:
        1. forward_request(gateway, method, params) - Forward to a specific gateway
        2. forward_request(db, method, params) - Forward to active gateways in the database

        Args:
            gateway_or_db: Either a DbGateway object or database Session
            method: RPC method name
            params: Optional method parameters
            app_user_email: Optional app user email for OAuth token selection

        Returns:
            Gateway response

        Raises:
            GatewayConnectionError: If forwarding fails
            GatewayError: If gateway gave an error
        """
        # Dispatch based on first parameter type
        if hasattr(gateway_or_db, "execute"):
            # This is a database session - forward to all active gateways
            return await self._forward_request_to_all(gateway_or_db, method, params, app_user_email)
        # This is a gateway object - forward to specific gateway
        return await self._forward_request_to_gateway(gateway_or_db, method, params, app_user_email)

    async def _forward_request_to_gateway(self, gateway: DbGateway, method: str, params: Optional[Dict[str, Any]] = None, app_user_email: Optional[str] = None) -> Any:
        """
        Forward a request to a specific gateway.

        Args:
            gateway: Gateway to forward to
            method: RPC method name
            params: Optional method parameters
            app_user_email: Optional app user email for OAuth token selection

        Returns:
            Gateway response

        Raises:
            GatewayConnectionError: If forwarding fails
            GatewayError: If gateway gave an error
        """
        start_time = time.monotonic()

        # Create trace span for gateway federation
        with create_span(
            "gateway.forward_request",
            {
                "gateway.name": gateway.name,
                "gateway.id": str(gateway.id),
                "gateway.url": gateway.url,
                "rpc.method": method,
                "rpc.service": "mcp-gateway",
                "http.method": "POST",
                "http.url": urljoin(gateway.url, "/rpc"),
                "peer.service": gateway.name,
            },
        ) as span:
            if not gateway.enabled:
                raise GatewayConnectionError(f"Cannot forward request to inactive gateway: {gateway.name}")

            response = None  # Initialize response to avoid UnboundLocalError
            try:
                # Build RPC request
                request: Dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": method}
                if params:
                    request["params"] = params
                    if span:
                        span.set_attribute("rpc.params_count", len(params))

                # Handle OAuth authentication for the specific gateway
                headers: Dict[str, str] = {}

                if getattr(gateway, "auth_type", None) == "oauth" and gateway.oauth_config:
                    try:
                        grant_type = gateway.oauth_config.get("grant_type", "client_credentials")

                        if grant_type == "client_credentials":
                            # Use OAuth manager to get access token for Client Credentials flow
                            access_token = await self.oauth_manager.get_access_token(gateway.oauth_config)
                            headers = {"Authorization": f"Bearer {access_token}"}
                        elif grant_type == "authorization_code":
                            # For Authorization Code flow, try to get a stored token
                            if not app_user_email:
                                logger.warning(f"Skipping OAuth authorization code gateway {gateway.name} - user-specific tokens required but no user email provided")
                                raise GatewayConnectionError(f"OAuth authorization code gateway {gateway.name} requires user context")

                            # First-Party
                            from mcpgateway.services.token_storage_service import TokenStorageService  # pylint: disable=import-outside-toplevel

                            # Get database session (this is a bit hacky but necessary for now)
                            db = next(get_db())
                            try:
                                token_storage = TokenStorageService(db)
                                access_token = await token_storage.get_user_token(str(gateway.id), app_user_email)
                                if access_token:
                                    headers = {"Authorization": f"Bearer {access_token}"}
                                else:
                                    raise GatewayConnectionError(f"No valid OAuth token for user {app_user_email} and gateway {gateway.name}")
                            finally:
                                # Ensure close() always runs even if commit() fails
                                # Without this nested try/finally, a commit() failure (e.g., PgBouncer timeout)
                                # would skip close(), leaving the connection in "idle in transaction" state
                                try:
                                    db.commit()  # End read-only transaction cleanly before returning to pool
                                finally:
                                    db.close()
                    except Exception as oauth_error:
                        raise GatewayConnectionError(f"Failed to obtain OAuth token for gateway {gateway.name}: {oauth_error}")
                else:
                    # Handle non-OAuth authentication (existing logic)
                    auth_data = gateway.auth_value or {}
                    if isinstance(auth_data, str):
                        headers = decode_auth(auth_data) if auth_data else self._get_auth_headers()
                    elif isinstance(auth_data, dict):
                        headers = {str(k): str(v) for k, v in auth_data.items()}
                    else:
                        headers = self._get_auth_headers()

                # Directly use the persistent HTTP client (no async with)
                response = await self._http_client.post(urljoin(gateway.url, "/rpc"), json=request, headers=headers)
                response.raise_for_status()
                result = response.json()

                # Update last seen timestamp using fresh DB session
                # (gateway object may be detached from original session)
                try:
                    with fresh_db_session() as update_db:
                        db_gateway = update_db.execute(select(DbGateway).where(DbGateway.id == gateway.id)).scalar_one_or_none()
                        if db_gateway:
                            db_gateway.last_seen = datetime.now(timezone.utc)
                            update_db.commit()
                except Exception as update_error:
                    logger.warning(f"Failed to update last_seen for gateway {gateway.name}: {update_error}")

                # Record success metrics
                if span:
                    span.set_attribute("http.status_code", response.status_code)
                    span.set_attribute("success", True)
                    span.set_attribute("duration.ms", (time.monotonic() - start_time) * 1000)

            except Exception:
                if span:
                    span.set_attribute("http.status_code", getattr(response, "status_code", 0))
                raise GatewayConnectionError(f"Failed to forward request to {gateway.name}")

            if "error" in result:
                if span:
                    span.set_attribute("rpc.error", True)
                    span.set_attribute("rpc.error.message", result["error"].get("message", "Unknown error"))
                raise GatewayError(f"Gateway error: {result['error'].get('message')}")

            return result.get("result")

    async def _forward_request_to_all(self, db: Session, method: str, params: Optional[Dict[str, Any]] = None, app_user_email: Optional[str] = None) -> Any:
        """
        Forward a request to all active gateways that can handle the method.

        Args:
            db: Database session
            method: RPC method name
            params: Optional method parameters
            app_user_email: Optional app user email for OAuth token selection

        Returns:
            Gateway response from the first successful gateway

        Raises:
            GatewayConnectionError: If no gateways can handle the request
        """
        # ═══════════════════════════════════════════════════════════════════════════
        # PHASE 1: Fetch all required data before HTTP calls
        # ═══════════════════════════════════════════════════════════════════════════
        active_gateways = db.execute(select(DbGateway).where(DbGateway.enabled.is_(True))).scalars().all()

        if not active_gateways:
            raise GatewayConnectionError("No active gateways available to forward request")

        # Extract all gateway data to local variables before releasing DB connection
        gateway_data_list: List[Dict[str, Any]] = []
        for gateway in active_gateways:
            gw_data = {
                "id": gateway.id,
                "name": gateway.name,
                "url": gateway.url,
                "auth_type": getattr(gateway, "auth_type", None),
                "auth_value": gateway.auth_value,
                "oauth_config": gateway.oauth_config if hasattr(gateway, "oauth_config") else None,
            }
            gateway_data_list.append(gw_data)

        # For OAuth authorization_code flow, we need to fetch tokens while session is open
        # First-Party
        from mcpgateway.services.token_storage_service import TokenStorageService  # pylint: disable=import-outside-toplevel

        for gw_data in gateway_data_list:
            if gw_data["auth_type"] == "oauth" and gw_data["oauth_config"]:
                grant_type = gw_data["oauth_config"].get("grant_type", "client_credentials")
                if grant_type == "authorization_code" and app_user_email:
                    try:
                        token_storage = TokenStorageService(db)
                        access_token = await token_storage.get_user_token(str(gw_data["id"]), app_user_email)
                        gw_data["_oauth_token"] = access_token
                    except Exception as e:
                        logger.warning(f"Failed to get OAuth token for gateway {gw_data['name']}: {e}")
                        gw_data["_oauth_token"] = None

        # ═══════════════════════════════════════════════════════════════════════════
        # CRITICAL: Release DB connection back to pool BEFORE making HTTP calls
        # This prevents connection pool exhaustion during slow upstream requests.
        # ═══════════════════════════════════════════════════════════════════════════
        db.commit()  # End read-only transaction cleanly (commit not rollback to avoid inflating rollback stats)
        db.close()

        errors: List[str] = []

        # ═══════════════════════════════════════════════════════════════════════════
        # PHASE 2: Make HTTP calls (no DB connection held)
        # ═══════════════════════════════════════════════════════════════════════════
        for gw_data in gateway_data_list:
            try:
                # Handle OAuth authentication for the specific gateway
                headers: Dict[str, str] = {}

                if gw_data["auth_type"] == "oauth" and gw_data["oauth_config"]:
                    try:
                        grant_type = gw_data["oauth_config"].get("grant_type", "client_credentials")

                        if grant_type == "client_credentials":
                            # Use OAuth manager to get access token for Client Credentials flow
                            access_token = await self.oauth_manager.get_access_token(gw_data["oauth_config"])
                            headers = {"Authorization": f"Bearer {access_token}"}
                        elif grant_type == "authorization_code":
                            # For Authorization Code flow, use pre-fetched token
                            if not app_user_email:
                                logger.warning(f"Skipping OAuth authorization code gateway {gw_data['name']} - user-specific tokens required but no user email provided")
                                continue

                            access_token = gw_data.get("_oauth_token")
                            if access_token:
                                headers = {"Authorization": f"Bearer {access_token}"}
                            else:
                                logger.warning(f"No valid OAuth token for user {app_user_email} and gateway {gw_data['name']}")
                                continue
                    except Exception as oauth_error:
                        logger.warning(f"Failed to obtain OAuth token for gateway {gw_data['name']}: {oauth_error}")
                        errors.append(f"Gateway {gw_data['name']}: OAuth error - {str(oauth_error)}")
                        continue
                else:
                    # Handle non-OAuth authentication
                    auth_data = gw_data["auth_value"] or {}
                    if isinstance(auth_data, str):
                        headers = decode_auth(auth_data)
                    elif isinstance(auth_data, dict):
                        headers = {str(k): str(v) for k, v in auth_data.items()}
                    else:
                        headers = {}

                # Build RPC request
                request: Dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": method}
                if params:
                    request["params"] = params

                # Forward request with proper authentication headers
                response = await self._http_client.post(urljoin(gw_data["url"], "/rpc"), json=request, headers=headers)
                response.raise_for_status()
                result = response.json()

                # Check for RPC errors
                if "error" in result:
                    errors.append(f"Gateway {gw_data['name']}: {result['error'].get('message', 'Unknown RPC error')}")
                    continue

                # ═══════════════════════════════════════════════════════════════════════════
                # PHASE 3: Update last_seen using fresh DB session
                # ═══════════════════════════════════════════════════════════════════════════
                try:
                    with fresh_db_session() as update_db:
                        db_gateway = update_db.execute(select(DbGateway).where(DbGateway.id == gw_data["id"])).scalar_one_or_none()
                        if db_gateway:
                            db_gateway.last_seen = datetime.now(timezone.utc)
                            update_db.commit()
                except Exception as update_error:
                    logger.warning(f"Failed to update last_seen for gateway {gw_data['name']}: {update_error}")

                # Success - return the result
                logger.info(f"Successfully forwarded request to gateway {gw_data['name']}")
                return result.get("result")

            except Exception as e:
                error_msg = f"Gateway {gw_data['name']}: {str(e)}"
                errors.append(error_msg)
                logger.warning(f"Failed to forward request to gateway {gw_data['name']}: {e}")
                continue

        # If we get here, all gateways failed
        error_summary = "; ".join(errors)
        raise GatewayConnectionError(f"All gateways failed to handle request '{method}': {error_summary}")

    async def _handle_gateway_failure(self, gateway: DbGateway) -> None:
        """Tracks and handles gateway failures during health checks.
        If the failure count exceeds the threshold, the gateway is deactivated.

        Args:
            gateway: The gateway object that failed its health check.

        Returns:
            None

        Examples:
            >>> from mcpgateway.services.gateway_service import GatewayService
            >>> service = GatewayService()
            >>> gateway = type('Gateway', (), {
            ...     'id': 'gw1', 'name': 'test_gw', 'enabled': True, 'reachable': True
            ... })()
            >>> service._gateway_failure_counts = {}
            >>> import asyncio
            >>> # Test failure counting
            >>> asyncio.run(service._handle_gateway_failure(gateway))  # doctest: +ELLIPSIS
            >>> service._gateway_failure_counts['gw1'] >= 1
            True

            >>> # Test disabled gateway (no action)
            >>> gateway.enabled = False
            >>> old_count = service._gateway_failure_counts.get('gw1', 0)
            >>> asyncio.run(service._handle_gateway_failure(gateway))  # doctest: +ELLIPSIS
            >>> service._gateway_failure_counts.get('gw1', 0) == old_count
            True
        """
        if GW_FAILURE_THRESHOLD == -1:
            return  # Gateway failure action disabled

        if not gateway.enabled:
            return  # No action needed for inactive gateways

        if not gateway.reachable:
            return  # No action needed for unreachable gateways

        count = self._gateway_failure_counts.get(gateway.id, 0) + 1
        self._gateway_failure_counts[gateway.id] = count

        logger.warning(f"Gateway {gateway.name} failed health check {count} time(s).")

        if count >= GW_FAILURE_THRESHOLD:
            logger.error(f"Gateway {gateway.name} failed {GW_FAILURE_THRESHOLD} times. Deactivating...")
            with cast(Any, SessionLocal)() as db:
                await self.set_gateway_state(db, gateway.id, activate=True, reachable=False, only_update_reachable=True)
                self._gateway_failure_counts[gateway.id] = 0  # Reset after deactivation

    async def check_health_of_gateways(self, gateways: List[DbGateway], user_email: Optional[str] = None) -> bool:
        """Check health of a batch of gateways.

        Performs an asynchronous health-check for each gateway in `gateways` using
        an Async HTTP client. The function handles different authentication
        modes (OAuth client_credentials and authorization_code, and non-OAuth
        auth headers). When a gateway uses the authorization_code flow, the
        optional `user_email` is used to look up stored user tokens with
        fresh_db_session(). On individual failures the service will record the
        failure and call internal failure handling which may mark a gateway
        unreachable or deactivate it after repeated failures. If a previously
        unreachable gateway becomes healthy again the service will attempt to
        update its reachable status.

        NOTE: This method intentionally does NOT take a db parameter.
        DB access uses fresh_db_session() only when needed, avoiding holding
        connections during HTTP calls to MCP servers.

        Args:
            gateways: List of DbGateway objects to check.
            user_email: Optional MCP gateway user email used to retrieve
                stored OAuth tokens for gateways using the
                "authorization_code" grant type. If not provided, authorization
                code flows that require a user token will be treated as failed.

        Returns:
            bool: True when the health-check batch completes. This return
            value indicates completion of the checks, not that every gateway
            was healthy. Individual gateway failures are handled internally
            (via _handle_gateway_failure and status updates).

        Examples:
            >>> from mcpgateway.services.gateway_service import GatewayService
            >>> from unittest.mock import MagicMock
            >>> service = GatewayService()
            >>> gateways = [MagicMock()]
            >>> gateways[0].ca_certificate = None
            >>> import asyncio
            >>> result = asyncio.run(service.check_health_of_gateways(gateways))
            >>> isinstance(result, bool)
            True

            >>> # Test empty gateway list
            >>> empty_result = asyncio.run(service.check_health_of_gateways([]))
            >>> empty_result
            True

            >>> # Test multiple gateways (basic smoke)
            >>> multiple_gateways = [MagicMock(), MagicMock(), MagicMock()]
            >>> for i, gw in enumerate(multiple_gateways):
            ...     gw.name = f"gateway_{i}"
            ...     gw.url = f"http://gateway{i}.example.com"
            ...     gw.transport = "SSE"
            ...     gw.enabled = True
            ...     gw.reachable = True
            ...     gw.auth_value = {}
            ...     gw.ca_certificate = None
            >>> multi_result = asyncio.run(service.check_health_of_gateways(multiple_gateways))
            >>> isinstance(multi_result, bool)
            True
        """
        start_time = time.monotonic()
        concurrency_limit = min(settings.max_concurrent_health_checks, max(10, os.cpu_count() * 5))  # adaptive concurrency
        semaphore = asyncio.Semaphore(concurrency_limit)

        async def limited_check(gateway: DbGateway):
            """
            Checks the health of a single gateway while respecting a concurrency limit.

            This function checks the health of the given database gateway, ensuring that
            the number of concurrent checks does not exceed a predefined limit. The check
            is performed asynchronously and uses a semaphore to manage concurrency.

            Args:
                gateway (DbGateway): The database gateway whose health is to be checked.

            Raises:
                Any exceptions raised during the health check will be propagated to the caller.
            """
            async with semaphore:
                try:
                    await asyncio.wait_for(
                        self._check_single_gateway_health(gateway, user_email),
                        timeout=settings.gateway_health_check_timeout,
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"Gateway {getattr(gateway, 'name', 'unknown')} health check timed out after {settings.gateway_health_check_timeout}s")
                    # Treat timeout as a failed health check
                    await self._handle_gateway_failure(gateway)

        # Create trace span for health check batch
        with create_span("gateway.health_check_batch", {"gateway.count": len(gateways), "check.type": "health"}) as batch_span:
            # Chunk processing to avoid overload
            if not gateways:
                return True
            chunk_size = concurrency_limit
            for i in range(0, len(gateways), chunk_size):
                # batch will be a sublist of gateways from index i to i + chunk_size
                batch = gateways[i : i + chunk_size]

                # Each task is a health check for a gateway in the batch, excluding those with auth_type == "one_time_auth"
                tasks = [limited_check(gw) for gw in batch if gw.auth_type != "one_time_auth"]

                # Execute all health checks concurrently
                await asyncio.gather(*tasks, return_exceptions=True)
                await asyncio.sleep(0.05)  # small pause prevents network saturation

            elapsed = time.monotonic() - start_time

            if batch_span:
                batch_span.set_attribute("check.duration_ms", int(elapsed * 1000))
                batch_span.set_attribute("check.completed", True)

            logger.debug(f"Health check batch completed for {len(gateways)} gateways in {elapsed:.2f}s")

        return True

    async def _check_single_gateway_health(self, gateway: DbGateway, user_email: Optional[str] = None) -> None:
        """Check health of a single gateway.

        NOTE: This method intentionally does NOT take a db parameter.
        DB access uses fresh_db_session() only when needed, avoiding holding
        connections during HTTP calls to MCP servers.

        Args:
            gateway: Gateway to check (may be detached from session)
            user_email: Optional user email for OAuth token lookup
        """
        # Extract gateway data upfront (gateway may be detached from session)
        gateway_id = gateway.id
        gateway_name = gateway.name
        gateway_url = gateway.url
        gateway_transport = gateway.transport
        gateway_enabled = gateway.enabled
        gateway_reachable = gateway.reachable
        gateway_ca_certificate = gateway.ca_certificate
        gateway_ca_certificate_sig = gateway.ca_certificate_sig
        gateway_auth_type = gateway.auth_type
        gateway_oauth_config = gateway.oauth_config
        gateway_auth_value = gateway.auth_value

        # Create span for individual gateway health check
        with create_span(
            "gateway.health_check",
            {
                "gateway.name": gateway_name,
                "gateway.id": str(gateway_id),
                "gateway.url": gateway_url,
                "gateway.transport": gateway_transport,
                "gateway.enabled": gateway_enabled,
                "http.method": "GET",
                "http.url": gateway_url,
            },
        ) as span:
            valid = False
            if gateway_ca_certificate:
                if settings.enable_ed25519_signing:
                    public_key_pem = settings.ed25519_public_key
                    valid = validate_signature(gateway_ca_certificate.encode(), gateway_ca_certificate_sig, public_key_pem)
                else:
                    valid = True
            if valid:
                ssl_context = self.create_ssl_context(gateway_ca_certificate)
            else:
                ssl_context = None

            def get_httpx_client_factory(
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
                # First-Party
                from mcpgateway.services.http_client_service import get_default_verify, get_http_timeout  # pylint: disable=import-outside-toplevel

                return httpx.AsyncClient(
                    verify=ssl_context if ssl_context else get_default_verify(),
                    follow_redirects=True,
                    headers=headers,
                    timeout=timeout if timeout else get_http_timeout(),
                    auth=auth,
                    limits=httpx.Limits(
                        max_connections=settings.httpx_max_connections,
                        max_keepalive_connections=settings.httpx_max_keepalive_connections,
                        keepalive_expiry=settings.httpx_keepalive_expiry,
                    ),
                )

            # Use isolated client for gateway health checks (each gateway may have custom CA cert)
            # First-Party
            from mcpgateway.services.http_client_service import get_isolated_http_client  # pylint: disable=import-outside-toplevel

            # Use admin timeout for health checks (fail fast, don't wait 120s for slow upstreams)
            # Pass ssl_context if present, otherwise let get_isolated_http_client use skip_ssl_verify setting
            async with get_isolated_http_client(timeout=settings.httpx_admin_read_timeout, verify=ssl_context) as client:
                logger.debug(f"Checking health of gateway: {gateway_name} ({gateway_url})")
                try:
                    # Handle different authentication types
                    headers = {}

                    if gateway_auth_type == "oauth" and gateway_oauth_config:
                        grant_type = gateway_oauth_config.get("grant_type", "client_credentials")

                        if grant_type == "authorization_code":
                            # For Authorization Code flow, try to get stored tokens
                            try:
                                # First-Party
                                from mcpgateway.services.token_storage_service import TokenStorageService  # pylint: disable=import-outside-toplevel

                                # Use fresh session for OAuth token lookup
                                with fresh_db_session() as token_db:
                                    token_storage = TokenStorageService(token_db)

                                    # Get user-specific OAuth token
                                    if not user_email:
                                        if span:
                                            span.set_attribute("health.status", "unhealthy")
                                            span.set_attribute("error.message", "User email required for OAuth token")
                                        await self._handle_gateway_failure(gateway)
                                        return

                                    access_token = await token_storage.get_user_token(gateway_id, user_email)

                                if access_token:
                                    headers["Authorization"] = f"Bearer {access_token}"
                                else:
                                    if span:
                                        span.set_attribute("health.status", "unhealthy")
                                        span.set_attribute("error.message", "No valid OAuth token for user")
                                    await self._handle_gateway_failure(gateway)
                                    return
                            except Exception as e:
                                logger.error(f"Failed to obtain stored OAuth token for gateway {gateway_name}: {e}")
                                if span:
                                    span.set_attribute("health.status", "unhealthy")
                                    span.set_attribute("error.message", "Failed to obtain stored OAuth token")
                                await self._handle_gateway_failure(gateway)
                                return
                        else:
                            # For Client Credentials flow, get token directly
                            try:
                                access_token = await self.oauth_manager.get_access_token(gateway_oauth_config)
                                headers["Authorization"] = f"Bearer {access_token}"
                            except Exception as e:
                                if span:
                                    span.set_attribute("health.status", "unhealthy")
                                    span.set_attribute("error.message", str(e))
                                await self._handle_gateway_failure(gateway)
                                return
                    else:
                        # Handle non-OAuth authentication (existing logic)
                        auth_data = gateway_auth_value or {}
                        if isinstance(auth_data, str):
                            headers = decode_auth(auth_data)
                        elif isinstance(auth_data, dict):
                            headers = {str(k): str(v) for k, v in auth_data.items()}
                        else:
                            headers = {}

                    # Perform the GET and raise on 4xx/5xx
                    if (gateway_transport).lower() == "sse":
                        timeout = httpx.Timeout(settings.health_check_timeout)
                        async with client.stream("GET", gateway_url, headers=headers, timeout=timeout) as response:
                            # This will raise immediately if status is 4xx/5xx
                            response.raise_for_status()
                            if span:
                                span.set_attribute("http.status_code", response.status_code)
                    elif (gateway_transport).lower() == "streamablehttp":
                        # Use session pool if enabled for faster health checks
                        use_pool = False
                        pool = None
                        if settings.mcp_session_pool_enabled:
                            try:
                                pool = get_mcp_session_pool()
                                use_pool = True
                            except RuntimeError:
                                # Pool not initialized (e.g., in tests), fall back to per-call sessions
                                pass

                        if use_pool and pool is not None:
                            # Health checks are system operations, not user-driven.
                            # Use system identity to isolate from user sessions.
                            async with pool.session(
                                url=gateway_url,
                                headers=headers,
                                transport_type=TransportType.STREAMABLE_HTTP,
                                httpx_client_factory=get_httpx_client_factory,
                                user_identity="_system_health_check",
                                gateway_id=gateway_id,
                            ) as pooled:
                                # Optional explicit RPC verification (off by default for performance).
                                # Pool's internal staleness check handles health via _validate_session.
                                if settings.mcp_session_pool_explicit_health_rpc:
                                    await asyncio.wait_for(
                                        pooled.session.list_tools(),
                                        timeout=settings.health_check_timeout,
                                    )
                        else:
                            async with streamablehttp_client(url=gateway_url, headers=headers, timeout=settings.health_check_timeout, httpx_client_factory=get_httpx_client_factory) as (
                                read_stream,
                                write_stream,
                                _get_session_id,
                            ):
                                async with ClientSession(read_stream, write_stream) as session:
                                    # Initialize the session
                                    response = await session.initialize()

                    # Reactivate gateway if it was previously inactive and health check passed now
                    if gateway_enabled and not gateway_reachable:
                        logger.info(f"Reactivating gateway: {gateway_name}, as it is healthy now")
                        with cast(Any, SessionLocal)() as status_db:
                            await self.set_gateway_state(status_db, gateway_id, activate=True, reachable=True, only_update_reachable=True)

                    # Update last_seen with fresh session (gateway object is detached)
                    try:
                        with fresh_db_session() as update_db:
                            db_gateway = update_db.execute(select(DbGateway).where(DbGateway.id == gateway_id)).scalar_one_or_none()
                            if db_gateway:
                                db_gateway.last_seen = datetime.now(timezone.utc)
                                update_db.commit()
                    except Exception as update_error:
                        logger.warning(f"Failed to update last_seen for gateway {gateway_name}: {update_error}")

                    # Auto-refresh tools/resources/prompts if enabled
                    if settings.auto_refresh_servers:
                        try:
                            # Throttling: Check if refresh is needed based on last_refresh_at
                            refresh_needed = True
                            if gateway.last_refresh_at:
                                # Default to config value if configured interval is missing

                                last_refresh = gateway.last_refresh_at
                                if last_refresh.tzinfo is None:
                                    last_refresh = last_refresh.replace(tzinfo=timezone.utc)

                                # Use per-gateway interval if set, otherwise fall back to global default
                                refresh_interval = getattr(settings, "gateway_auto_refresh_interval", 300)
                                if gateway.refresh_interval_seconds is not None:
                                    refresh_interval = gateway.refresh_interval_seconds

                                time_since_refresh = (datetime.now(timezone.utc) - last_refresh).total_seconds()

                                if time_since_refresh < refresh_interval:
                                    refresh_needed = False
                                    logger.debug(f"Skipping auto-refresh for {gateway_name}: last refreshed {int(time_since_refresh)}s ago")

                            if refresh_needed:
                                # Locking: Try to acquire lock to avoid conflict with manual refresh
                                lock = self._get_refresh_lock(gateway_id)
                                if not lock.locked():
                                    # Acquire lock to prevent concurrent manual refresh
                                    async with lock:
                                        await self._refresh_gateway_tools_resources_prompts(
                                            gateway_id=gateway_id,
                                            _user_email=user_email,
                                            created_via="health_check",
                                            pre_auth_headers=headers if headers else None,
                                            gateway=gateway,
                                        )
                                else:
                                    logger.debug(f"Skipping auto-refresh for {gateway_name}: lock held (likely manual refresh in progress)")
                        except Exception as refresh_error:
                            logger.warning(f"Failed to refresh tools for gateway {gateway_name}: {refresh_error}")

                    if span:
                        span.set_attribute("health.status", "healthy")
                        span.set_attribute("success", True)

                except Exception as e:
                    if span:
                        span.set_attribute("health.status", "unhealthy")
                        span.set_attribute("error.message", str(e))

                    # Set the logger as debug as this check happens for each interval
                    logger.debug(f"Health check failed for gateway {gateway_name}: {e}")
                    await self._handle_gateway_failure(gateway)

    async def aggregate_capabilities(self, db: Session) -> Dict[str, Any]:
        """
        Aggregate capabilities across all gateways.

        Args:
            db: Database session

        Returns:
            Dictionary of aggregated capabilities

        Examples:
            >>> from mcpgateway.services.gateway_service import GatewayService
            >>> from unittest.mock import MagicMock
            >>> service = GatewayService()
            >>> db = MagicMock()
            >>> gateway_mock = MagicMock()
            >>> gateway_mock.capabilities = {"tools": {"listChanged": True}, "custom": {"feature": True}}
            >>> db.execute.return_value.scalars.return_value.all.return_value = [gateway_mock]
            >>> import asyncio
            >>> result = asyncio.run(service.aggregate_capabilities(db))
            >>> isinstance(result, dict)
            True
            >>> 'prompts' in result
            True
            >>> 'resources' in result
            True
            >>> 'tools' in result
            True
            >>> 'logging' in result
            True
            >>> result['prompts']['listChanged']
            True
            >>> result['resources']['subscribe']
            True
            >>> result['resources']['listChanged']
            True
            >>> result['tools']['listChanged']
            True
            >>> isinstance(result['logging'], dict)
            True

            >>> # Test with no gateways
            >>> db.execute.return_value.scalars.return_value.all.return_value = []
            >>> empty_result = asyncio.run(service.aggregate_capabilities(db))
            >>> isinstance(empty_result, dict)
            True
            >>> 'tools' in empty_result
            True

            >>> # Test capability merging
            >>> gateway1 = MagicMock()
            >>> gateway1.capabilities = {"tools": {"feature1": True}}
            >>> gateway2 = MagicMock()
            >>> gateway2.capabilities = {"tools": {"feature2": True}}
            >>> db.execute.return_value.scalars.return_value.all.return_value = [gateway1, gateway2]
            >>> merged_result = asyncio.run(service.aggregate_capabilities(db))
            >>> merged_result['tools']['listChanged']  # Default capability
            True
        """
        capabilities = {
            "prompts": {"listChanged": True},
            "resources": {"subscribe": True, "listChanged": True},
            "tools": {"listChanged": True},
            "logging": {},
        }

        # Get all active gateways
        gateways = db.execute(select(DbGateway).where(DbGateway.enabled)).scalars().all()

        # Combine capabilities
        for gateway in gateways:
            if gateway.capabilities:
                for key, value in gateway.capabilities.items():
                    if key not in capabilities:
                        capabilities[key] = value
                    elif isinstance(value, dict):
                        capabilities[key].update(value)

        return capabilities

    async def subscribe_events(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Subscribe to gateway events.

        Creates a new event queue and subscribes to gateway events. Events are
        yielded as they are published. The subscription is automatically cleaned
        up when the generator is closed or goes out of scope.

        Yields:
            Dict[str, Any]: Gateway event messages with 'type', 'data', and 'timestamp' fields

        Examples:
            >>> service = GatewayService()
            >>> import asyncio
            >>> from unittest.mock import MagicMock
            >>> # Create a mock async generator for the event service
            >>> async def mock_event_gen():
            ...     yield {"type": "test_event", "data": "payload"}
            >>>
            >>> # Mock the event service to return our generator
            >>> service._event_service = MagicMock()
            >>> service._event_service.subscribe_events.return_value = mock_event_gen()
            >>>
            >>> # Test the subscription
            >>> async def test_sub():
            ...     async for event in service.subscribe_events():
            ...         return event
            >>>
            >>> result = asyncio.run(test_sub())
            >>> result
            {'type': 'test_event', 'data': 'payload'}
        """
        async for event in self._event_service.subscribe_events():
            yield event

    async def _initialize_gateway(
        self,
        url: str,
        authentication: Optional[Dict[str, str]] = None,
        transport: str = "SSE",
        auth_type: Optional[str] = None,
        oauth_config: Optional[Dict[str, Any]] = None,
        ca_certificate: Optional[bytes] = None,
        pre_auth_headers: Optional[Dict[str, str]] = None,
        include_resources: bool = True,
        include_prompts: bool = True,
        auth_query_params: Optional[Dict[str, str]] = None,
    ) -> tuple[Dict[str, Any], List[ToolCreate], List[ResourceCreate], List[PromptCreate]]:
        """Initialize connection to a gateway and retrieve its capabilities.

        Connects to an MCP gateway using the specified transport protocol,
        performs the MCP handshake, and retrieves capabilities, tools,
        resources, and prompts from the gateway.

        Args:
            url: Gateway URL to connect to
            authentication: Optional authentication headers for the connection
            transport: Transport protocol - "SSE" or "StreamableHTTP"
            auth_type: Authentication type - "basic", "bearer", "headers", "oauth", "query_param" or None
            oauth_config: OAuth configuration if auth_type is "oauth"
            ca_certificate: CA certificate for SSL verification
            pre_auth_headers: Pre-authenticated headers to skip OAuth token fetch (for reuse)
            include_resources: Whether to include resources in the fetch
            include_prompts: Whether to include prompts in the fetch
            auth_query_params: Query param names for URL sanitization in error logs (decrypted values)

        Returns:
            tuple[Dict[str, Any], List[ToolCreate], List[ResourceCreate], List[PromptCreate]]:
                Capabilities dictionary, list of ToolCreate objects, list of ResourceCreate objects, and list of PromptCreate objects

        Raises:
            GatewayConnectionError: If connection or initialization fails

        Examples:
            >>> service = GatewayService()
            >>> # Test parameter validation
            >>> import asyncio
            >>> async def test_params():
            ...     try:
            ...         await service._initialize_gateway("hello//")
            ...     except Exception as e:
            ...         return isinstance(e, GatewayConnectionError) or "Failed" in str(e)

            >>> asyncio.run(test_params())
            True

            >>> # Test default parameters
            >>> hasattr(service, '_initialize_gateway')
            True
            >>> import inspect
            >>> sig = inspect.signature(service._initialize_gateway)
            >>> sig.parameters['transport'].default
            'SSE'
            >>> sig.parameters['authentication'].default is None
            True
        """
        try:
            if authentication is None:
                authentication = {}

            # Use pre-authenticated headers if provided (avoids duplicate OAuth token fetch)
            if pre_auth_headers:
                authentication = pre_auth_headers
            # Handle OAuth authentication
            elif auth_type == "oauth" and oauth_config:
                grant_type = oauth_config.get("grant_type", "client_credentials")

                if grant_type == "authorization_code":
                    # For Authorization Code flow, we can't initialize immediately
                    # because we need user consent. Just store the configuration
                    # and let the user complete the OAuth flow later.
                    logger.info("""OAuth Authorization Code flow configured for gateway. User must complete authorization before gateway can be used.""")
                    # Don't try to get access token here - it will be obtained during tool invocation
                    authentication = {}

                    # Skip MCP server connection for Authorization Code flow
                    # Tools will be fetched after OAuth completion
                    return {}, [], [], []
                # For Client Credentials flow, we can get the token immediately
                try:
                    logger.debug("Obtaining OAuth access token for Client Credentials flow")
                    access_token = await self.oauth_manager.get_access_token(oauth_config)
                    authentication = {"Authorization": f"Bearer {access_token}"}
                except Exception as e:
                    logger.error(f"Failed to obtain OAuth access token: {e}")
                    raise GatewayConnectionError(f"OAuth authentication failed: {str(e)}")

            capabilities = {}
            tools = []
            resources = []
            prompts = []
            if auth_type in ("basic", "bearer", "headers") and isinstance(authentication, str):
                authentication = decode_auth(authentication)
            if transport.lower() == "sse":
                capabilities, tools, resources, prompts = await self.connect_to_sse_server(url, authentication, ca_certificate, include_prompts, include_resources, auth_query_params)
            elif transport.lower() == "streamablehttp":
                capabilities, tools, resources, prompts = await self.connect_to_streamablehttp_server(url, authentication, ca_certificate, include_prompts, include_resources, auth_query_params)

            return capabilities, tools, resources, prompts
        except Exception as e:
            sanitized_url = sanitize_url_for_logging(url, auth_query_params)
            logger.error(f"Gateway initialization failed for {sanitized_url}: {str(e)}", exc_info=True)
            raise GatewayConnectionError(f"Failed to initialize gateway at {sanitized_url}")

    def _get_gateways(self, include_inactive: bool = True) -> list[DbGateway]:
        """Sync function for database operations (runs in thread).

        Args:
            include_inactive: Whether to include inactive gateways

        Returns:
            List[DbGateway]: List of active gateways

        Examples:
            >>> from unittest.mock import patch, MagicMock
            >>> service = GatewayService()
            >>> with patch('mcpgateway.services.gateway_service.SessionLocal') as mock_session:
            ...     mock_db = MagicMock()
            ...     mock_session.return_value.__enter__.return_value = mock_db
            ...     mock_db.execute.return_value.scalars.return_value.all.return_value = []
            ...     result = service._get_gateways()
            ...     isinstance(result, list)
            True

            >>> # Test include_inactive parameter handling
            >>> with patch('mcpgateway.services.gateway_service.SessionLocal') as mock_session:
            ...     mock_db = MagicMock()
            ...     mock_session.return_value.__enter__.return_value = mock_db
            ...     mock_db.execute.return_value.scalars.return_value.all.return_value = []
            ...     result_active_only = service._get_gateways(include_inactive=False)
            ...     isinstance(result_active_only, list)
            True
        """
        with cast(Any, SessionLocal)() as db:
            if include_inactive:
                return db.execute(select(DbGateway)).scalars().all()
            # Only return active gateways
            return db.execute(select(DbGateway).where(DbGateway.enabled)).scalars().all()

    def get_first_gateway_by_url(self, db: Session, url: str, team_id: Optional[str] = None, include_inactive: bool = False) -> Optional[GatewayRead]:
        """Return the first DbGateway matching the given URL and optional team_id.

        This is a synchronous helper intended for use from request handlers where
        a simple DB lookup is needed. It normalizes the provided URL similar to
        how gateways are stored and matches by the `url` column. If team_id is
        provided, it restricts the search to that team.

        Args:
            db: Database session to use for the query
            url: Gateway base URL to match (will be normalized)
            team_id: Optional team id to restrict search
            include_inactive: Whether to include inactive gateways

        Returns:
            Optional[DbGateway]: First matching gateway or None
        """
        query = select(DbGateway).where(DbGateway.url == url)
        if not include_inactive:
            query = query.where(DbGateway.enabled)
        if team_id:
            query = query.where(DbGateway.team_id == team_id)
        result = db.execute(query).scalars().first()
        # Wrap the DB object in the GatewayRead schema for consistency with
        # other service methods. Return None if no match found.
        if result is None:
            return None
        return GatewayRead.model_validate(result)

    async def _run_leader_heartbeat(self) -> None:
        """Run leader heartbeat loop to keep leader key alive.

        This runs independently from health checks to ensure the leader key
        is refreshed frequently enough (every redis_leader_heartbeat_interval seconds)
        to prevent expiration during long-running health check operations.

        The loop exits if this instance loses leadership.
        """
        while True:
            try:
                await asyncio.sleep(self._leader_heartbeat_interval)

                if not self._redis_client:
                    return

                # Check if we're still the leader
                current_leader = await self._redis_client.get(self._leader_key)
                if current_leader != self._instance_id:
                    logger.info("Lost Redis leadership, stopping heartbeat")
                    return

                # Refresh the leader key TTL
                await self._redis_client.expire(self._leader_key, self._leader_ttl)
                logger.debug(f"Leader heartbeat: refreshed TTL to {self._leader_ttl}s")

            except Exception as e:
                logger.warning(f"Leader heartbeat error: {e}")
                # Continue trying - the main health check loop will handle leadership loss

    async def _run_health_checks(self, user_email: str) -> None:
        """Run health checks periodically,
        Uses Redis or FileLock - for multiple workers.
        Uses simple health check for single worker mode.

        NOTE: This method intentionally does NOT take a db parameter.
        Health checks use fresh_db_session() only when DB access is needed,
        avoiding holding connections during HTTP calls to MCP servers.

        Args:
            user_email: Email of the user for OAuth token lookup

        Examples:
            >>> service = GatewayService()
            >>> service._health_check_interval = 0.1  # Short interval for testing
            >>> service._redis_client = None
            >>> import asyncio
            >>> # Test that method exists and is callable
            >>> callable(service._run_health_checks)
            True
            >>> # Test setup without actual execution (would run forever)
            >>> hasattr(service, '_health_check_interval')
            True
            >>> service._health_check_interval == 0.1
            True
        """

        while True:
            try:
                if self._redis_client and settings.cache_type == "redis":
                    # Redis-based leader check (async, decode_responses=True returns strings)
                    # Note: Leader key TTL refresh is handled by _run_leader_heartbeat task
                    current_leader = await self._redis_client.get(self._leader_key)
                    if current_leader != self._instance_id:
                        return

                    # Run health checks
                    gateways = await asyncio.to_thread(self._get_gateways)
                    if gateways:
                        await self.check_health_of_gateways(gateways, user_email)

                    await asyncio.sleep(self._health_check_interval)

                elif settings.cache_type == "none":
                    try:
                        # For single worker mode, run health checks directly
                        gateways = await asyncio.to_thread(self._get_gateways)
                        if gateways:
                            await self.check_health_of_gateways(gateways, user_email)
                    except Exception as e:
                        logger.error(f"Health check run failed: {str(e)}")

                    await asyncio.sleep(self._health_check_interval)

                else:
                    # FileLock-based leader fallback
                    try:
                        self._file_lock.acquire(timeout=0)
                        logger.info("File lock acquired. Running health checks.")

                        while True:
                            gateways = await asyncio.to_thread(self._get_gateways)
                            if gateways:
                                await self.check_health_of_gateways(gateways, user_email)
                            await asyncio.sleep(self._health_check_interval)

                    except Timeout:
                        logger.debug("File lock already held. Retrying later.")
                        await asyncio.sleep(self._health_check_interval)

                    except Exception as e:
                        logger.error(f"FileLock health check failed: {str(e)}")

                    finally:
                        if self._file_lock.is_locked:
                            try:
                                self._file_lock.release()
                                logger.info("Released file lock.")
                            except Exception as e:
                                logger.warning(f"Failed to release file lock: {str(e)}")

            except Exception as e:
                logger.error(f"Unexpected error in health check loop: {str(e)}")
                await asyncio.sleep(self._health_check_interval)

    def _get_auth_headers(self) -> Dict[str, str]:
        """Get headers for gateway authentication.

        Returns:
            dict: Authorization header dict

        Examples:
            >>> service = GatewayService()
            >>> headers = service._get_auth_headers()
            >>> isinstance(headers, dict)
            True
            >>> 'Authorization' in headers
            True
            >>> 'X-API-Key' in headers
            True
            >>> 'Content-Type' in headers
            True
            >>> headers['Content-Type']
            'application/json'
            >>> headers['Authorization'].startswith('Basic ')
            True
            >>> len(headers)
            3
        """
        api_key = f"{settings.basic_auth_user}:{settings.basic_auth_password}"
        return {"Authorization": f"Basic {api_key}", "X-API-Key": api_key, "Content-Type": "application/json"}

    async def _notify_gateway_added(self, gateway: DbGateway) -> None:
        """Notify subscribers of gateway addition.

        Args:
            gateway: Gateway to add
        """
        event = {
            "type": "gateway_added",
            "data": {
                "id": gateway.id,
                "name": gateway.name,
                "url": gateway.url,
                "description": gateway.description,
                "enabled": gateway.enabled,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._publish_event(event)

    async def _notify_gateway_activated(self, gateway: DbGateway) -> None:
        """Notify subscribers of gateway activation.

        Args:
            gateway: Gateway to activate
        """
        event = {
            "type": "gateway_activated",
            "data": {
                "id": gateway.id,
                "name": gateway.name,
                "url": gateway.url,
                "enabled": gateway.enabled,
                "reachable": gateway.reachable,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._publish_event(event)

    async def _notify_gateway_deactivated(self, gateway: DbGateway) -> None:
        """Notify subscribers of gateway deactivation.

        Args:
            gateway: Gateway database object
        """
        event = {
            "type": "gateway_deactivated",
            "data": {
                "id": gateway.id,
                "name": gateway.name,
                "url": gateway.url,
                "enabled": gateway.enabled,
                "reachable": gateway.reachable,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._publish_event(event)

    async def _notify_gateway_offline(self, gateway: DbGateway) -> None:
        """
        Notify subscribers that gateway is offline (Enabled but Unreachable).

        Args:
            gateway: Gateway database object
        """
        event = {
            "type": "gateway_offline",
            "data": {
                "id": gateway.id,
                "name": gateway.name,
                "url": gateway.url,
                "enabled": True,
                "reachable": False,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._publish_event(event)

    async def _notify_gateway_deleted(self, gateway_info: Dict[str, Any]) -> None:
        """Notify subscribers of gateway deletion.

        Args:
            gateway_info: Dict containing information about gateway to delete
        """
        event = {
            "type": "gateway_deleted",
            "data": gateway_info,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._publish_event(event)

    async def _notify_gateway_removed(self, gateway: DbGateway) -> None:
        """Notify subscribers of gateway removal (deactivation).

        Args:
            gateway: Gateway to remove
        """
        event = {
            "type": "gateway_removed",
            "data": {"id": gateway.id, "name": gateway.name, "enabled": gateway.enabled},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._publish_event(event)

    def convert_gateway_to_read(self, gateway: DbGateway) -> GatewayRead:
        """Convert a DbGateway instance to a GatewayRead Pydantic model.

        Args:
            gateway: Gateway database object

        Returns:
            GatewayRead: Pydantic model instance
        """
        gateway_dict = gateway.__dict__.copy()
        gateway_dict.pop("_sa_instance_state", None)

        # Ensure auth_value is properly encoded
        if isinstance(gateway.auth_value, dict):
            gateway_dict["auth_value"] = encode_auth(gateway.auth_value)

        # Convert tags from List[str] to List[Dict[str, str]] for GatewayRead
        if gateway.tags:
            gateway_dict["tags"] = validate_tags_field(gateway.tags)
        else:
            gateway_dict["tags"] = []

        # Include metadata fields
        gateway_dict["created_by"] = getattr(gateway, "created_by", None)
        gateway_dict["modified_by"] = getattr(gateway, "modified_by", None)
        gateway_dict["created_at"] = getattr(gateway, "created_at", None)
        gateway_dict["updated_at"] = getattr(gateway, "updated_at", None)
        gateway_dict["version"] = getattr(gateway, "version", None)
        gateway_dict["team"] = getattr(gateway, "team", None)

        return GatewayRead.model_validate(gateway_dict)

    def _prepare_gateway_for_read(self, gateway: DbGateway) -> DbGateway:
        """DEPRECATED: Use convert_gateway_to_read instead.

        Prepare a gateway object for GatewayRead validation.

        Ensures auth_value is in the correct format (encoded string) for the schema.
        Converts tags from List[str] (database format) to List[Dict[str, str]] (schema format).

        Args:
            gateway: Gateway database object

        Returns:
            Gateway object with properly formatted auth_value and tags
        """
        # If auth_value is a dict, encode it to string for GatewayRead schema
        if isinstance(gateway.auth_value, dict):
            gateway.auth_value = encode_auth(gateway.auth_value)

        # Convert tags from List[str] to List[Dict[str, str]] for GatewayRead
        # Database stores: ["git", "development"]
        # GatewayRead expects: [{"id": "git", "label": "git"}, {"id": "development", "label": "development"}]
        if gateway.tags:
            gateway.tags = validate_tags_field(gateway.tags)

        return gateway

    def _create_db_tool(
        self,
        tool: ToolCreate,
        gateway: DbGateway,
        created_by: Optional[str] = None,
        created_from_ip: Optional[str] = None,
        created_via: Optional[str] = None,
        created_user_agent: Optional[str] = None,
    ) -> DbTool:
        """Create a DbTool with consistent federation metadata across all scenarios.

        Args:
            tool: Tool creation schema
            gateway: Gateway database object
            created_by: Username who created/updated this tool
            created_from_ip: IP address of creator
            created_via: Creation method (ui, api, federation, rediscovery)
            created_user_agent: User agent of creation request

        Returns:
            DbTool: Consistently configured database tool object
        """
        return DbTool(
            original_name=tool.name,
            custom_name=tool.name,
            custom_name_slug=slugify(tool.name),
            display_name=generate_display_name(tool.name),
            url=gateway.url,
            description=tool.description,
            integration_type="MCP",  # Gateway-discovered tools are MCP type
            request_type=tool.request_type,
            headers=tool.headers,
            input_schema=tool.input_schema,
            annotations=tool.annotations,
            jsonpath_filter=tool.jsonpath_filter,
            auth_type=gateway.auth_type,
            auth_value=encode_auth(gateway.auth_value) if isinstance(gateway.auth_value, dict) else gateway.auth_value,
            # Federation metadata - consistent across all scenarios
            created_by=created_by or "system",
            created_from_ip=created_from_ip,
            created_via=created_via or "federation",
            created_user_agent=created_user_agent,
            federation_source=gateway.name,
            version=1,
            # Inherit team assignment and visibility from gateway
            team_id=gateway.team_id,
            owner_email=gateway.owner_email,
            visibility="public",  # Federated tools should be public for discovery
        )

    def _update_or_create_tools(self, db: Session, tools: List[Any], gateway: DbGateway, created_via: str) -> List[DbTool]:
        """Helper to handle update-or-create logic for tools from MCP server.

        Args:
            db: Database session
            tools: List of tools from MCP server
            gateway: Gateway object
            created_via: String indicating creation source ("oauth", "update", etc.)

        Returns:
            List of new tools to be added to the database
        """
        if not tools:
            return []

        tools_to_add = []

        # Batch fetch all existing tools for this gateway
        tool_names = [tool.name for tool in tools if tool is not None]
        if not tool_names:
            return []

        existing_tools_query = select(DbTool).where(DbTool.gateway_id == gateway.id, DbTool.original_name.in_(tool_names))
        existing_tools = db.execute(existing_tools_query).scalars().all()
        existing_tools_map = {tool.original_name: tool for tool in existing_tools}

        for tool in tools:
            if tool is None:
                logger.warning("Skipping None tool in tools list")
                continue

            try:
                # Check if tool already exists for this gateway from the tools_map
                existing_tool = existing_tools_map.get(tool.name)
                if existing_tool:
                    # Update existing tool if there are changes
                    fields_to_update = False

                    # Check basic field changes
                    basic_fields_changed = (
                        existing_tool.url != gateway.url or existing_tool.description != tool.description or existing_tool.integration_type != "MCP" or existing_tool.request_type != tool.request_type
                    )

                    # Check schema and configuration changes
                    schema_fields_changed = (
                        existing_tool.headers != tool.headers
                        or existing_tool.input_schema != tool.input_schema
                        or existing_tool.output_schema != tool.output_schema
                        or existing_tool.jsonpath_filter != tool.jsonpath_filter
                    )

                    # Check authentication and visibility changes
                    auth_fields_changed = existing_tool.auth_type != gateway.auth_type or existing_tool.auth_value != gateway.auth_value or existing_tool.visibility != gateway.visibility

                    if basic_fields_changed or schema_fields_changed or auth_fields_changed:
                        fields_to_update = True
                    if fields_to_update:
                        existing_tool.url = gateway.url
                        existing_tool.description = tool.description
                        existing_tool.integration_type = "MCP"
                        existing_tool.request_type = tool.request_type
                        existing_tool.headers = tool.headers
                        existing_tool.input_schema = tool.input_schema
                        existing_tool.output_schema = tool.output_schema
                        existing_tool.jsonpath_filter = tool.jsonpath_filter
                        existing_tool.auth_type = gateway.auth_type
                        existing_tool.auth_value = gateway.auth_value
                        existing_tool.visibility = gateway.visibility
                        logger.debug(f"Updated existing tool: {tool.name}")
                else:
                    # Create new tool if it doesn't exist
                    db_tool = self._create_db_tool(
                        tool=tool,
                        gateway=gateway,
                        created_by="system",
                        created_via=created_via,
                    )
                    # Attach relationship to avoid NoneType during flush
                    db_tool.gateway = gateway
                    tools_to_add.append(db_tool)
                    logger.debug(f"Created new tool: {tool.name}")
            except Exception as e:
                logger.warning(f"Failed to process tool {getattr(tool, 'name', 'unknown')}: {e}")
                continue

        return tools_to_add

    def _update_or_create_resources(self, db: Session, resources: List[Any], gateway: DbGateway, created_via: str) -> List[DbResource]:
        """Helper to handle update-or-create logic for resources from MCP server.

        Args:
            db: Database session
            resources: List of resources from MCP server
            gateway: Gateway object
            created_via: String indicating creation source ("oauth", "update", etc.)

        Returns:
            List of new resources to be added to the database
        """
        if not resources:
            return []

        resources_to_add = []

        # Batch fetch all existing resources for this gateway
        resource_uris = [resource.uri for resource in resources if resource is not None]
        if not resource_uris:
            return []

        existing_resources_query = select(DbResource).where(DbResource.gateway_id == gateway.id, DbResource.uri.in_(resource_uris))
        existing_resources = db.execute(existing_resources_query).scalars().all()
        existing_resources_map = {resource.uri: resource for resource in existing_resources}

        for resource in resources:
            if resource is None:
                logger.warning("Skipping None resource in resources list")
                continue

            try:
                # Check if resource already exists for this gateway from the resources_map
                existing_resource = existing_resources_map.get(resource.uri)

                if existing_resource:
                    # Update existing resource if there are changes
                    fields_to_update = False

                    if (
                        existing_resource.name != resource.name
                        or existing_resource.description != resource.description
                        or existing_resource.mime_type != resource.mime_type
                        or existing_resource.uri_template != resource.uri_template
                        or existing_resource.visibility != gateway.visibility
                    ):
                        fields_to_update = True

                    if fields_to_update:
                        existing_resource.name = resource.name
                        existing_resource.description = resource.description
                        existing_resource.mime_type = resource.mime_type
                        existing_resource.uri_template = resource.uri_template
                        existing_resource.visibility = gateway.visibility
                        logger.debug(f"Updated existing resource: {resource.uri}")
                else:
                    # Create new resource if it doesn't exist
                    db_resource = DbResource(
                        uri=resource.uri,
                        name=resource.name,
                        description=resource.description,
                        mime_type=resource.mime_type,
                        uri_template=resource.uri_template,
                        gateway_id=gateway.id,
                        created_by="system",
                        created_via=created_via,
                        visibility=gateway.visibility,
                    )
                    resources_to_add.append(db_resource)
                    logger.debug(f"Created new resource: {resource.uri}")
            except Exception as e:
                logger.warning(f"Failed to process resource {getattr(resource, 'uri', 'unknown')}: {e}")
                continue

        return resources_to_add

    def _update_or_create_prompts(self, db: Session, prompts: List[Any], gateway: DbGateway, created_via: str) -> List[DbPrompt]:
        """Helper to handle update-or-create logic for prompts from MCP server.

        Args:
            db: Database session
            prompts: List of prompts from MCP server
            gateway: Gateway object
            created_via: String indicating creation source ("oauth", "update", etc.)

        Returns:
            List of new prompts to be added to the database
        """
        if not prompts:
            return []

        prompts_to_add = []

        # Batch fetch all existing prompts for this gateway
        prompt_names = [prompt.name for prompt in prompts if prompt is not None]
        if not prompt_names:
            return []

        existing_prompts_query = select(DbPrompt).where(DbPrompt.gateway_id == gateway.id, DbPrompt.original_name.in_(prompt_names))
        existing_prompts = db.execute(existing_prompts_query).scalars().all()
        existing_prompts_map = {prompt.original_name: prompt for prompt in existing_prompts}

        for prompt in prompts:
            if prompt is None:
                logger.warning("Skipping None prompt in prompts list")
                continue

            try:
                # Check if resource already exists for this gateway from the prompts_map
                existing_prompt = existing_prompts_map.get(prompt.name)

                if existing_prompt:
                    # Update existing prompt if there are changes
                    fields_to_update = False

                    if (
                        existing_prompt.description != prompt.description
                        or existing_prompt.template != (prompt.template if hasattr(prompt, "template") else "")
                        or existing_prompt.visibility != gateway.visibility
                    ):
                        fields_to_update = True

                    if fields_to_update:
                        existing_prompt.description = prompt.description
                        existing_prompt.template = prompt.template if hasattr(prompt, "template") else ""
                        existing_prompt.visibility = gateway.visibility
                        logger.debug(f"Updated existing prompt: {prompt.name}")
                else:
                    # Create new prompt if it doesn't exist
                    db_prompt = DbPrompt(
                        name=prompt.name,
                        original_name=prompt.name,
                        custom_name=prompt.name,
                        display_name=prompt.name,
                        description=prompt.description,
                        template=prompt.template if hasattr(prompt, "template") else "",
                        argument_schema={},  # Use argument_schema instead of arguments
                        gateway_id=gateway.id,
                        created_by="system",
                        created_via=created_via,
                        visibility=gateway.visibility,
                    )
                    db_prompt.gateway = gateway
                    prompts_to_add.append(db_prompt)
                    logger.debug(f"Created new prompt: {prompt.name}")
            except Exception as e:
                logger.warning(f"Failed to process prompt {getattr(prompt, 'name', 'unknown')}: {e}")
                continue

        return prompts_to_add

    async def _refresh_gateway_tools_resources_prompts(
        self,
        gateway_id: str,
        _user_email: Optional[str] = None,
        created_via: str = "health_check",
        pre_auth_headers: Optional[Dict[str, str]] = None,
        gateway: Optional[DbGateway] = None,
        include_resources: bool = True,
        include_prompts: bool = True,
    ) -> Dict[str, int]:
        """Refresh tools, resources, and prompts for a gateway during health checks.

        Fetches the latest tools/resources/prompts from the MCP server and syncs
        with the database (add new, update changed, remove stale). Only performs
        DB operations if actual changes are detected.

        This method uses fresh_db_session() internally to avoid holding
        connections during HTTP calls to MCP servers.

        Args:
            gateway_id: ID of the gateway to refresh
            _user_email: Optional user email for OAuth token lookup (unused currently)
            created_via: String indicating creation source (default: "health_check")
            pre_auth_headers: Pre-authenticated headers from health check to avoid duplicate OAuth token fetch
            gateway: Optional DbGateway object to avoid redundant DB lookup
            include_resources: Whether to include resources in the refresh
            include_prompts: Whether to include prompts in the refresh

        Returns:
            Dict with counts: {tools_added, tools_removed, resources_added,
                              resources_removed, prompts_added, prompts_removed}

        Examples:
            >>> from mcpgateway.services.gateway_service import GatewayService
            >>> from unittest.mock import patch, MagicMock, AsyncMock
            >>> import asyncio

            >>> # Test gateway not found returns empty result
            >>> service = GatewayService()
            >>> mock_session = MagicMock()
            >>> mock_session.execute.return_value.scalar_one_or_none.return_value = None
            >>> with patch('mcpgateway.services.gateway_service.fresh_db_session') as mock_fresh:
            ...     mock_fresh.return_value.__enter__.return_value = mock_session
            ...     result = asyncio.run(service._refresh_gateway_tools_resources_prompts('gw-123'))
            >>> result['tools_added'] == 0 and result['tools_removed'] == 0
            True
            >>> result['resources_added'] == 0 and result['resources_removed'] == 0
            True
            >>> result['success'] is True and result['error'] is None
            True

            >>> # Test disabled gateway returns empty result
            >>> mock_gw = MagicMock()
            >>> mock_gw.enabled = False
            >>> mock_gw.reachable = True
            >>> mock_gw.name = 'test_gw'
            >>> mock_session.execute.return_value.scalar_one_or_none.return_value = mock_gw
            >>> with patch('mcpgateway.services.gateway_service.fresh_db_session') as mock_fresh:
            ...     mock_fresh.return_value.__enter__.return_value = mock_session
            ...     result = asyncio.run(service._refresh_gateway_tools_resources_prompts('gw-123'))
            >>> result['tools_added']
            0

            >>> # Test unreachable gateway returns empty result
            >>> mock_gw.enabled = True
            >>> mock_gw.reachable = False
            >>> with patch('mcpgateway.services.gateway_service.fresh_db_session') as mock_fresh:
            ...     mock_fresh.return_value.__enter__.return_value = mock_session
            ...     result = asyncio.run(service._refresh_gateway_tools_resources_prompts('gw-123'))
            >>> result['tools_added']
            0

            >>> # Test method is async and callable
            >>> import inspect
            >>> inspect.iscoroutinefunction(service._refresh_gateway_tools_resources_prompts)
            True
        """
        result = {
            "tools_added": 0,
            "tools_removed": 0,
            "resources_added": 0,
            "resources_removed": 0,
            "prompts_added": 0,
            "prompts_removed": 0,
            "tools_updated": 0,
            "resources_updated": 0,
            "prompts_updated": 0,
            "success": True,
            "error": None,
            "validation_errors": [],
        }

        # Fetch gateway metadata only (no relationships needed for MCP call)
        # Use provided gateway object if available to save a DB call
        gateway_name = None
        gateway_url = None
        gateway_transport = None
        gateway_auth_type = None
        gateway_auth_value = None
        gateway_oauth_config = None
        gateway_ca_certificate = None

        if gateway:
            if not gateway.enabled or not gateway.reachable:
                logger.debug(f"Skipping tool refresh for disabled/unreachable gateway {gateway.name}")
                return result

            gateway_name = gateway.name
            gateway_url = gateway.url
            gateway_transport = gateway.transport
            gateway_auth_type = gateway.auth_type
            gateway_auth_value = gateway.auth_value
            gateway_oauth_config = gateway.oauth_config
            gateway_ca_certificate = gateway.ca_certificate
        else:
            with fresh_db_session() as db:
                gateway_obj = db.execute(select(DbGateway).where(DbGateway.id == gateway_id)).scalar_one_or_none()

                if not gateway_obj:
                    logger.warning(f"Gateway {gateway_id} not found for tool refresh")
                    return result

                if not gateway_obj.enabled or not gateway_obj.reachable:
                    logger.debug(f"Skipping tool refresh for disabled/unreachable gateway {gateway_obj.name}")
                    return result

                # Extract metadata before session closes
                gateway_name = gateway_obj.name
                gateway_url = gateway_obj.url
                gateway_transport = gateway_obj.transport
                gateway_auth_type = gateway_obj.auth_type
                gateway_auth_value = gateway_obj.auth_value
                gateway_oauth_config = gateway_obj.oauth_config
                gateway_ca_certificate = gateway_obj.ca_certificate

        # Fetch tools/resources/prompts from MCP server (no DB connection held)
        try:
            _capabilities, tools, resources, prompts = await self._initialize_gateway(
                url=gateway_url,
                authentication=gateway_auth_value,
                transport=gateway_transport,
                auth_type=gateway_auth_type,
                oauth_config=gateway_oauth_config,
                ca_certificate=gateway_ca_certificate.encode() if gateway_ca_certificate else None,
                pre_auth_headers=pre_auth_headers,
                include_resources=include_resources,
                include_prompts=include_prompts,
            )
        except Exception as e:
            logger.warning(f"Failed to fetch tools from gateway {gateway_name}: {e}")
            result["success"] = False
            result["error"] = str(e)
            return result

        # For authorization_code OAuth gateways, empty responses may indicate incomplete auth flow
        # Skip only if it's an auth_code gateway with no data (user may not have completed authorization)
        is_auth_code_gateway = gateway_oauth_config and isinstance(gateway_oauth_config, dict) and gateway_oauth_config.get("grant_type") == "authorization_code"
        if not tools and not resources and not prompts and is_auth_code_gateway:
            logger.debug(f"No tools/resources/prompts returned from auth_code gateway {gateway_name} (user may not have authorized)")
            return result

        # For non-auth_code gateways, empty responses are legitimate and will clear stale items

        # Update database with fresh session
        with fresh_db_session() as db:
            # Fetch gateway with relationships for update/comparison
            gateway = db.execute(
                select(DbGateway)
                .options(
                    selectinload(DbGateway.tools),
                    selectinload(DbGateway.resources),
                    selectinload(DbGateway.prompts),
                )
                .where(DbGateway.id == gateway_id)
            ).scalar_one_or_none()

            if not gateway:
                result["success"] = False
                result["error"] = f"Gateway {gateway_id} not found during refresh"
                return result

            new_tool_names = [tool.name for tool in tools]
            new_resource_uris = [resource.uri for resource in resources] if include_resources else None
            new_prompt_names = [prompt.name for prompt in prompts] if include_prompts else None

            # Track dirty objects before update operations to count per-type updates
            pending_tools_before = {obj for obj in db.dirty if isinstance(obj, DbTool)}
            pending_resources_before = {obj for obj in db.dirty if isinstance(obj, DbResource)}
            pending_prompts_before = {obj for obj in db.dirty if isinstance(obj, DbPrompt)}

            # Update/create tools, resources, and prompts
            tools_to_add = self._update_or_create_tools(db, tools, gateway, created_via)
            resources_to_add = self._update_or_create_resources(db, resources, gateway, created_via) if include_resources else []
            prompts_to_add = self._update_or_create_prompts(db, prompts, gateway, created_via) if include_prompts else []

            # Count per-type updates
            result["tools_updated"] = len({obj for obj in db.dirty if isinstance(obj, DbTool)} - pending_tools_before)
            result["resources_updated"] = len({obj for obj in db.dirty if isinstance(obj, DbResource)} - pending_resources_before)
            result["prompts_updated"] = len({obj for obj in db.dirty if isinstance(obj, DbPrompt)} - pending_prompts_before)

            # Only delete MCP-discovered items (not user-created entries)
            # Excludes "api", "ui", None (legacy/user-created) to preserve user entries
            mcp_created_via_values = {"MCP", "federation", "health_check", "manual_refresh", "oauth", "update"}

            # Find and remove stale tools (only MCP-discovered ones)
            stale_tool_ids = [tool.id for tool in gateway.tools if tool.original_name not in new_tool_names and tool.created_via in mcp_created_via_values]
            if stale_tool_ids:
                for i in range(0, len(stale_tool_ids), 500):
                    chunk = stale_tool_ids[i : i + 500]
                    db.execute(delete(ToolMetric).where(ToolMetric.tool_id.in_(chunk)))
                    db.execute(delete(server_tool_association).where(server_tool_association.c.tool_id.in_(chunk)))
                    db.execute(delete(DbTool).where(DbTool.id.in_(chunk)))
                result["tools_removed"] = len(stale_tool_ids)

            # Find and remove stale resources (only MCP-discovered ones, only if resources were fetched)
            stale_resource_ids = []
            if new_resource_uris is not None:
                stale_resource_ids = [resource.id for resource in gateway.resources if resource.uri not in new_resource_uris and resource.created_via in mcp_created_via_values]
                if stale_resource_ids:
                    for i in range(0, len(stale_resource_ids), 500):
                        chunk = stale_resource_ids[i : i + 500]
                        db.execute(delete(ResourceMetric).where(ResourceMetric.resource_id.in_(chunk)))
                        db.execute(delete(server_resource_association).where(server_resource_association.c.resource_id.in_(chunk)))
                        db.execute(delete(ResourceSubscription).where(ResourceSubscription.resource_id.in_(chunk)))
                        db.execute(delete(DbResource).where(DbResource.id.in_(chunk)))
                    result["resources_removed"] = len(stale_resource_ids)

            # Find and remove stale prompts (only MCP-discovered ones, only if prompts were fetched)
            stale_prompt_ids = []
            if new_prompt_names is not None:
                stale_prompt_ids = [prompt.id for prompt in gateway.prompts if prompt.original_name not in new_prompt_names and prompt.created_via in mcp_created_via_values]
                if stale_prompt_ids:
                    for i in range(0, len(stale_prompt_ids), 500):
                        chunk = stale_prompt_ids[i : i + 500]
                        db.execute(delete(PromptMetric).where(PromptMetric.prompt_id.in_(chunk)))
                        db.execute(delete(server_prompt_association).where(server_prompt_association.c.prompt_id.in_(chunk)))
                        db.execute(delete(DbPrompt).where(DbPrompt.id.in_(chunk)))
                    result["prompts_removed"] = len(stale_prompt_ids)

            # Expire gateway if stale items were deleted
            if stale_tool_ids or stale_resource_ids or stale_prompt_ids:
                db.expire(gateway)

            # Add new items in chunks
            chunk_size = 50
            if tools_to_add:
                for i in range(0, len(tools_to_add), chunk_size):
                    chunk = tools_to_add[i : i + chunk_size]
                    db.add_all(chunk)
                    db.flush()
                result["tools_added"] = len(tools_to_add)

            if resources_to_add:
                for i in range(0, len(resources_to_add), chunk_size):
                    chunk = resources_to_add[i : i + chunk_size]
                    db.add_all(chunk)
                    db.flush()
                result["resources_added"] = len(resources_to_add)

            if prompts_to_add:
                for i in range(0, len(prompts_to_add), chunk_size):
                    chunk = prompts_to_add[i : i + chunk_size]
                    db.add_all(chunk)
                    db.flush()
                result["prompts_added"] = len(prompts_to_add)

            gateway.last_refresh_at = datetime.now(timezone.utc)

            total_changes = (
                result["tools_added"]
                + result["tools_removed"]
                + result["tools_updated"]
                + result["resources_added"]
                + result["resources_removed"]
                + result["resources_updated"]
                + result["prompts_added"]
                + result["prompts_removed"]
                + result["prompts_updated"]
            )

            has_changes = total_changes > 0

            if has_changes:
                db.commit()
                logger.info(
                    f"Refreshed gateway {gateway_name}: "
                    f"tools(+{result['tools_added']}/-{result['tools_removed']}/~{result['tools_updated']}), "
                    f"resources(+{result['resources_added']}/-{result['resources_removed']}/~{result['resources_updated']}), "
                    f"prompts(+{result['prompts_added']}/-{result['prompts_removed']}/~{result['prompts_updated']})"
                )

                # Invalidate caches per-type based on actual changes
                cache = _get_registry_cache()
                if result["tools_added"] > 0 or result["tools_removed"] > 0 or result["tools_updated"] > 0:
                    await cache.invalidate_tools()
                if result["resources_added"] > 0 or result["resources_removed"] > 0 or result["resources_updated"] > 0:
                    await cache.invalidate_resources()
                if result["prompts_added"] > 0 or result["prompts_removed"] > 0 or result["prompts_updated"] > 0:
                    await cache.invalidate_prompts()

                # Invalidate tool lookup cache for this gateway
                tool_lookup_cache = _get_tool_lookup_cache()
                await tool_lookup_cache.invalidate_gateway(str(gateway_id))
            else:
                db.commit()
                logger.debug(f"No changes detected during refresh of gateway {gateway_name}")

        return result

    def _get_refresh_lock(self, gateway_id: str) -> asyncio.Lock:
        """Get or create a per-gateway refresh lock.

        This ensures only one refresh operation can run for a given gateway at a time.

        Args:
            gateway_id: ID of the gateway to get the lock for

        Returns:
            asyncio.Lock: The lock for the specified gateway

        Examples:
            >>> from mcpgateway.services.gateway_service import GatewayService
            >>> service = GatewayService()
            >>> lock1 = service._get_refresh_lock('gw-123')
            >>> lock2 = service._get_refresh_lock('gw-123')
            >>> lock1 is lock2
            True
            >>> lock3 = service._get_refresh_lock('gw-456')
            >>> lock1 is lock3
            False
        """
        if gateway_id not in self._refresh_locks:
            self._refresh_locks[gateway_id] = asyncio.Lock()
        return self._refresh_locks[gateway_id]

    async def refresh_gateway_manually(
        self,
        gateway_id: str,
        include_resources: bool = True,
        include_prompts: bool = True,
        user_email: Optional[str] = None,
        request_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Manually trigger a refresh of tools/resources/prompts for a gateway.

        This method provides a public API for triggering an immediate refresh
        of a gateway's tools, resources, and prompts from its MCP server.
        It includes concurrency control via per-gateway locking.

        Args:
            gateway_id: Gateway ID to refresh
            include_resources: Whether to include resources in the refresh
            include_prompts: Whether to include prompts in the refresh
            user_email: Email of the user triggering the refresh
            request_headers: Optional request headers for passthrough authentication

        Returns:
            Dict with counts: {tools_added, tools_updated, tools_removed,
                              resources_added, resources_updated, resources_removed,
                              prompts_added, prompts_updated, prompts_removed,
                              validation_errors, duration_ms, refreshed_at}

        Raises:
            GatewayNotFoundError: If the gateway does not exist
            GatewayError: If another refresh is already in progress for this gateway

        Examples:
            >>> from mcpgateway.services.gateway_service import GatewayService
            >>> from unittest.mock import patch, MagicMock, AsyncMock
            >>> import asyncio

            >>> # Test method is async
            >>> service = GatewayService()
            >>> import inspect
            >>> inspect.iscoroutinefunction(service.refresh_gateway_manually)
            True
        """
        start_time = time.monotonic()

        pre_auth_headers = {}

        # Check if gateway exists before acquiring lock
        with fresh_db_session() as db:
            gateway = db.execute(select(DbGateway).where(DbGateway.id == gateway_id)).scalar_one_or_none()
            if not gateway:
                raise GatewayNotFoundError(f"Gateway with ID '{gateway_id}' not found")
            gateway_name = gateway.name

            # Get passthrough headers if request headers provided
            if request_headers:
                pre_auth_headers = get_passthrough_headers(request_headers, {}, db, gateway)

        lock = self._get_refresh_lock(gateway_id)

        # Check if lock is already held (concurrent refresh in progress)
        if lock.locked():
            raise GatewayError(f"Refresh already in progress for gateway {gateway_name}")

        async with lock:
            logger.info(f"Starting manual refresh for gateway {gateway_name} (ID: {gateway_id})")

            result = await self._refresh_gateway_tools_resources_prompts(
                gateway_id=gateway_id,
                _user_email=user_email,
                created_via="manual_refresh",
                pre_auth_headers=pre_auth_headers,
                gateway=gateway,
                include_resources=include_resources,
                include_prompts=include_prompts,
            )
            # Note: last_refresh_at is updated inside _refresh_gateway_tools_resources_prompts on success

        result["duration_ms"] = (time.monotonic() - start_time) * 1000
        result["refreshed_at"] = datetime.now(timezone.utc)

        log_level = logging.INFO if result.get("success", True) else logging.WARNING
        status_msg = "succeeded" if result.get("success", True) else f"failed: {result.get('error')}"

        logger.log(
            log_level,
            f"Manual refresh for gateway {gateway_id} {status_msg}. Stats: "
            f"tools(+{result['tools_added']}/-{result['tools_removed']}), "
            f"resources(+{result['resources_added']}/-{result['resources_removed']}), "
            f"prompts(+{result['prompts_added']}/-{result['prompts_removed']}) "
            f"in {result['duration_ms']:.2f}ms",
        )

        return result

    async def _publish_event(self, event: Dict[str, Any]) -> None:
        """Publish event to all subscribers.

        Args:
            event: event dictionary

        Examples:
            >>> import asyncio
            >>> from unittest.mock import AsyncMock
            >>> service = GatewayService()
            >>> # Mock the underlying event service
            >>> service._event_service = AsyncMock()
            >>> test_event = {"type": "test", "data": {}}
            >>>
            >>> asyncio.run(service._publish_event(test_event))
            >>>
            >>> # Verify the event was passed to the event service
            >>> service._event_service.publish_event.assert_awaited_with(test_event)
        """
        await self._event_service.publish_event(event)

    def _validate_tools(self, tools: list[dict[str, Any]], context: str = "default") -> tuple[list[ToolCreate], list[str]]:
        """Validate tools individually with richer logging and error aggregation.

        Args:
            tools: list of tool dicts
            context: caller context, e.g. "oauth" to tailor errors/messages

        Returns:
            tuple[list[ToolCreate], list[str]]: Tuple of (valid tools, validation errors)

        Raises:
            OAuthToolValidationError: If all tools fail validation in OAuth context
            GatewayConnectionError: If all tools fail validation in default context
        """
        valid_tools: list[ToolCreate] = []
        validation_errors: list[str] = []

        for i, tool_dict in enumerate(tools):
            tool_name = tool_dict.get("name", f"unknown_tool_{i}")
            try:
                logger.debug(f"Validating tool: {tool_name}")
                validated_tool = ToolCreate.model_validate(tool_dict)
                valid_tools.append(validated_tool)
                logger.debug(f"Tool '{tool_name}' validated successfully")
            except ValidationError as e:
                error_msg = f"Validation failed for tool '{tool_name}': {e.errors()}"
                logger.error(error_msg)
                logger.debug(f"Failed tool schema: {tool_dict}")
                validation_errors.append(error_msg)
            except ValueError as e:
                if "JSON structure exceeds maximum depth" in str(e):
                    error_msg = f"Tool '{tool_name}' schema too deeply nested. " f"Current depth limit: {settings.validation_max_json_depth}"
                    logger.error(error_msg)
                    logger.warning("Consider increasing VALIDATION_MAX_JSON_DEPTH environment variable")
                else:
                    error_msg = f"ValueError for tool '{tool_name}': {str(e)}"
                    logger.error(error_msg)
                validation_errors.append(error_msg)
            except Exception as e:  # pragma: no cover - defensive
                error_msg = f"Unexpected error validating tool '{tool_name}': {type(e).__name__}: {str(e)}"
                logger.error(error_msg, exc_info=True)
                validation_errors.append(error_msg)

        if validation_errors:
            logger.warning(f"Tool validation completed with {len(validation_errors)} error(s). " f"Successfully validated {len(valid_tools)} tool(s).")
            for err in validation_errors[:3]:
                logger.debug(f"Validation error: {err}")

        if not valid_tools and validation_errors:
            if context == "oauth":
                raise OAuthToolValidationError(f"OAuth tool fetch failed: all {len(tools)} tools failed validation. " f"First error: {validation_errors[0][:200]}")
            raise GatewayConnectionError(f"Failed to fetch tools: All {len(tools)} tools failed validation. " f"First error: {validation_errors[0][:200]}")

        return valid_tools, validation_errors

    async def _connect_to_sse_server_without_validation(self, server_url: str, authentication: Optional[Dict[str, str]] = None):
        """Connect to an MCP server running with SSE transport, skipping URL validation.

        This is used for OAuth-protected servers where we've already validated the token works.

        Args:
            server_url: The URL of the SSE MCP server to connect to.
            authentication: Optional dictionary containing authentication headers.

        Returns:
            Tuple containing (capabilities, tools, resources, prompts) from the MCP server.
        """
        if authentication is None:
            authentication = {}

        # Skip validation for OAuth servers - we already validated via OAuth flow
        # Use async with for both sse_client and ClientSession
        try:
            async with sse_client(url=server_url, headers=authentication) as streams:
                async with ClientSession(*streams) as session:
                    # Initialize the session
                    response = await session.initialize()
                    capabilities = response.capabilities.model_dump(by_alias=True, exclude_none=True)
                    logger.debug(f"Server capabilities: {capabilities}")

                    response = await session.list_tools()
                    tools = response.tools
                    tools = [tool.model_dump(by_alias=True, exclude_none=True, exclude_unset=True) for tool in tools]

                    tools, _ = self._validate_tools(tools, context="oauth")
                    if tools:
                        logger.info(f"Fetched {len(tools)} tools from gateway")
                    # Fetch resources if supported

                    logger.debug(f"Checking for resources support: {capabilities.get('resources')}")
                    resources = []
                    if capabilities.get("resources"):
                        try:
                            response = await session.list_resources()
                            raw_resources = response.resources
                            for resource in raw_resources:
                                resource_data = resource.model_dump(by_alias=True, exclude_none=True)
                                # Convert AnyUrl to string if present
                                if "uri" in resource_data and hasattr(resource_data["uri"], "unicode_string"):
                                    resource_data["uri"] = str(resource_data["uri"])
                                # Add default content if not present (will be fetched on demand)
                                if "content" not in resource_data:
                                    resource_data["content"] = ""
                                try:
                                    resources.append(ResourceCreate.model_validate(resource_data))
                                except Exception:
                                    # If validation fails, create minimal resource
                                    resources.append(
                                        ResourceCreate(
                                            uri=str(resource_data.get("uri", "")),
                                            name=resource_data.get("name", ""),
                                            description=resource_data.get("description"),
                                            mime_type=resource_data.get("mimeType"),
                                            uri_template=resource_data.get("uriTemplate") or None,
                                            content="",
                                        )
                                    )
                            logger.info(f"Fetched {len(resources)} resources from gateway")
                        except Exception as e:
                            logger.warning(f"Failed to fetch resources: {e}")

                        # resource template URI
                        try:
                            response_templates = await session.list_resource_templates()
                            raw_resources_templates = response_templates.resourceTemplates
                            resource_templates = []
                            for resource_template in raw_resources_templates:
                                resource_template_data = resource_template.model_dump(by_alias=True, exclude_none=True)

                                if "uriTemplate" in resource_template_data:  # and hasattr(resource_template_data["uriTemplate"], "unicode_string"):
                                    resource_template_data["uri_template"] = str(resource_template_data["uriTemplate"])
                                    resource_template_data["uri"] = str(resource_template_data["uriTemplate"])

                                if "content" not in resource_template_data:
                                    resource_template_data["content"] = ""

                                resources.append(ResourceCreate.model_validate(resource_template_data))
                                resource_templates.append(ResourceCreate.model_validate(resource_template_data))
                            logger.info(f"Fetched {len(resource_templates)} resource templates from gateway")
                        except Exception as e:
                            logger.warning(f"Failed to fetch resource templates: {e}")

                    # Fetch prompts if supported
                    prompts = []
                    logger.debug(f"Checking for prompts support: {capabilities.get('prompts')}")
                    if capabilities.get("prompts"):
                        try:
                            response = await session.list_prompts()
                            raw_prompts = response.prompts
                            for prompt in raw_prompts:
                                prompt_data = prompt.model_dump(by_alias=True, exclude_none=True)
                                # Add default template if not present
                                if "template" not in prompt_data:
                                    prompt_data["template"] = ""
                                try:
                                    prompts.append(PromptCreate.model_validate(prompt_data))
                                except Exception:
                                    # If validation fails, create minimal prompt
                                    prompts.append(
                                        PromptCreate(
                                            name=prompt_data.get("name", ""),
                                            description=prompt_data.get("description"),
                                            template=prompt_data.get("template", ""),
                                        )
                                    )
                            logger.info(f"Fetched {len(prompts)} prompts from gateway")
                        except Exception as e:
                            logger.warning(f"Failed to fetch prompts: {e}")

                    return capabilities, tools, resources, prompts
        except Exception as e:
            # Note: This function is for OAuth servers only, which don't use query param auth
            sanitized_url = sanitize_url_for_logging(server_url)
            logger.error(f"SSE connection error details: {type(e).__name__}: {str(e)}", exc_info=True)
            raise GatewayConnectionError(f"Failed to connect to SSE server at {sanitized_url}: {str(e)}")

    async def connect_to_sse_server(
        self,
        server_url: str,
        authentication: Optional[Dict[str, str]] = None,
        ca_certificate: Optional[bytes] = None,
        include_prompts: bool = True,
        include_resources: bool = True,
        auth_query_params: Optional[Dict[str, str]] = None,
    ):
        """Connect to an MCP server running with SSE transport.

        Args:
            server_url: The URL of the SSE MCP server to connect to.
            authentication: Optional dictionary containing authentication headers.
            ca_certificate: Optional CA certificate for SSL verification.
            include_prompts: Whether to fetch prompts from the server.
            include_resources: Whether to fetch resources from the server.
            auth_query_params: Query param names for URL sanitization in error logs.

        Returns:
            Tuple containing (capabilities, tools, resources, prompts) from the MCP server.
        """
        if authentication is None:
            authentication = {}

        def get_httpx_client_factory(
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
            # First-Party
            from mcpgateway.services.http_client_service import get_default_verify, get_http_timeout  # pylint: disable=import-outside-toplevel

            if ca_certificate:
                ctx = self.create_ssl_context(ca_certificate)
            else:
                ctx = None
            return httpx.AsyncClient(
                verify=ctx if ctx else get_default_verify(),
                follow_redirects=True,
                headers=headers,
                timeout=timeout if timeout else get_http_timeout(),
                auth=auth,
                limits=httpx.Limits(
                    max_connections=settings.httpx_max_connections,
                    max_keepalive_connections=settings.httpx_max_keepalive_connections,
                    keepalive_expiry=settings.httpx_keepalive_expiry,
                ),
            )

        # Use async with for both sse_client and ClientSession
        async with sse_client(url=server_url, headers=authentication, httpx_client_factory=get_httpx_client_factory) as streams:
            async with ClientSession(*streams) as session:
                # Initialize the session
                response = await session.initialize()
                capabilities = response.capabilities.model_dump(by_alias=True, exclude_none=True)
                logger.debug(f"Server capabilities: {capabilities}")

                response = await session.list_tools()
                tools = response.tools
                tools = [tool.model_dump(by_alias=True, exclude_none=True, exclude_unset=True) for tool in tools]

                tools, _ = self._validate_tools(tools)
                if tools:
                    logger.info(f"Fetched {len(tools)} tools from gateway")
                # Fetch resources if supported
                resources = []
                if include_resources:
                    logger.debug(f"Checking for resources support: {capabilities.get('resources')}")
                    if capabilities.get("resources"):
                        try:
                            response = await session.list_resources()
                            raw_resources = response.resources
                            for resource in raw_resources:
                                resource_data = resource.model_dump(by_alias=True, exclude_none=True)
                                # Convert AnyUrl to string if present
                                if "uri" in resource_data and hasattr(resource_data["uri"], "unicode_string"):
                                    resource_data["uri"] = str(resource_data["uri"])
                                # Add default content if not present (will be fetched on demand)
                                if "content" not in resource_data:
                                    resource_data["content"] = ""
                                try:
                                    resources.append(ResourceCreate.model_validate(resource_data))
                                except Exception:
                                    # If validation fails, create minimal resource
                                    resources.append(
                                        ResourceCreate(
                                            uri=str(resource_data.get("uri", "")),
                                            name=resource_data.get("name", ""),
                                            description=resource_data.get("description"),
                                            mime_type=resource_data.get("mimeType"),
                                            uri_template=resource_data.get("uriTemplate") or None,
                                            content="",
                                        )
                                    )
                            logger.info(f"Fetched {len(resources)} resources from gateway")
                        except Exception as e:
                            logger.warning(f"Failed to fetch resources: {e}")

                        # resource template URI
                        try:
                            response_templates = await session.list_resource_templates()
                            raw_resources_templates = response_templates.resourceTemplates
                            resource_templates = []
                            for resource_template in raw_resources_templates:
                                resource_template_data = resource_template.model_dump(by_alias=True, exclude_none=True)

                                if "uriTemplate" in resource_template_data:  # and hasattr(resource_template_data["uriTemplate"], "unicode_string"):
                                    resource_template_data["uri_template"] = str(resource_template_data["uriTemplate"])
                                    resource_template_data["uri"] = str(resource_template_data["uriTemplate"])

                                if "content" not in resource_template_data:
                                    resource_template_data["content"] = ""

                                resources.append(ResourceCreate.model_validate(resource_template_data))
                                resource_templates.append(ResourceCreate.model_validate(resource_template_data))
                            logger.info(f"Fetched {len(raw_resources_templates)} resource templates from gateway")
                        except Exception as ei:
                            logger.warning(f"Failed to fetch resource templates: {ei}")

                # Fetch prompts if supported
                prompts = []
                if include_prompts:
                    logger.debug(f"Checking for prompts support: {capabilities.get('prompts')}")
                    if capabilities.get("prompts"):
                        try:
                            response = await session.list_prompts()
                            raw_prompts = response.prompts
                            for prompt in raw_prompts:
                                prompt_data = prompt.model_dump(by_alias=True, exclude_none=True)
                                # Add default template if not present
                                if "template" not in prompt_data:
                                    prompt_data["template"] = ""
                                try:
                                    prompts.append(PromptCreate.model_validate(prompt_data))
                                except Exception:
                                    # If validation fails, create minimal prompt
                                    prompts.append(
                                        PromptCreate(
                                            name=prompt_data.get("name", ""),
                                            description=prompt_data.get("description"),
                                            template=prompt_data.get("template", ""),
                                        )
                                    )
                            logger.info(f"Fetched {len(prompts)} prompts from gateway")
                        except Exception as e:
                            logger.warning(f"Failed to fetch prompts: {e}")

                return capabilities, tools, resources, prompts
        sanitized_url = sanitize_url_for_logging(server_url, auth_query_params)
        raise GatewayConnectionError(f"Failed to initialize gateway at {sanitized_url}")

    async def connect_to_streamablehttp_server(
        self,
        server_url: str,
        authentication: Optional[Dict[str, str]] = None,
        ca_certificate: Optional[bytes] = None,
        include_prompts: bool = True,
        include_resources: bool = True,
        auth_query_params: Optional[Dict[str, str]] = None,
    ):
        """Connect to an MCP server running with Streamable HTTP transport.

        Args:
            server_url: The URL of the Streamable HTTP MCP server to connect to.
            authentication: Optional dictionary containing authentication headers.
            ca_certificate: Optional CA certificate for SSL verification.
            include_prompts: Whether to fetch prompts from the server.
            include_resources: Whether to fetch resources from the server.
            auth_query_params: Query param names for URL sanitization in error logs.

        Returns:
            Tuple containing (capabilities, tools, resources, prompts) from the MCP server.
        """
        if authentication is None:
            authentication = {}

        # Use authentication directly instead
        def get_httpx_client_factory(
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
            # First-Party
            from mcpgateway.services.http_client_service import get_default_verify, get_http_timeout  # pylint: disable=import-outside-toplevel

            if ca_certificate:
                ctx = self.create_ssl_context(ca_certificate)
            else:
                ctx = None
            return httpx.AsyncClient(
                verify=ctx if ctx else get_default_verify(),
                follow_redirects=True,
                headers=headers,
                timeout=timeout if timeout else get_http_timeout(),
                auth=auth,
                limits=httpx.Limits(
                    max_connections=settings.httpx_max_connections,
                    max_keepalive_connections=settings.httpx_max_keepalive_connections,
                    keepalive_expiry=settings.httpx_keepalive_expiry,
                ),
            )

        async with streamablehttp_client(url=server_url, headers=authentication, httpx_client_factory=get_httpx_client_factory) as (read_stream, write_stream, _get_session_id):
            async with ClientSession(read_stream, write_stream) as session:
                # Initialize the session
                response = await session.initialize()
                capabilities = response.capabilities.model_dump(by_alias=True, exclude_none=True)
                logger.debug(f"Server capabilities: {capabilities}")

                response = await session.list_tools()
                tools = response.tools
                tools = [tool.model_dump(by_alias=True, exclude_none=True, exclude_unset=True) for tool in tools]

                tools, _ = self._validate_tools(tools)
                for tool in tools:
                    tool.request_type = "STREAMABLEHTTP"
                if tools:
                    logger.info(f"Fetched {len(tools)} tools from gateway")

                # Fetch resources if supported
                resources = []
                if include_resources:
                    logger.debug(f"Checking for resources support: {capabilities.get('resources')}")
                    if capabilities.get("resources"):
                        try:
                            response = await session.list_resources()
                            raw_resources = response.resources
                            for resource in raw_resources:
                                resource_data = resource.model_dump(by_alias=True, exclude_none=True)
                                # Convert AnyUrl to string if present
                                if "uri" in resource_data and hasattr(resource_data["uri"], "unicode_string"):
                                    resource_data["uri"] = str(resource_data["uri"])
                                # Add default content if not present
                                if "content" not in resource_data:
                                    resource_data["content"] = ""
                                try:
                                    resources.append(ResourceCreate.model_validate(resource_data))
                                except Exception:
                                    # If validation fails, create minimal resource
                                    resources.append(
                                        ResourceCreate(
                                            uri=str(resource_data.get("uri", "")),
                                            name=resource_data.get("name", ""),
                                            description=resource_data.get("description"),
                                            mime_type=resource_data.get("mimeType"),
                                            uri_template=resource_data.get("uriTemplate") or None,
                                            content="",
                                        )
                                    )
                            logger.info(f"Fetched {len(resources)} resources from gateway")
                        except Exception as e:
                            logger.warning(f"Failed to fetch resources: {e}")

                        # resource template URI
                        try:
                            response_templates = await session.list_resource_templates()
                            raw_resources_templates = response_templates.resourceTemplates
                            resource_templates = []
                            for resource_template in raw_resources_templates:
                                resource_template_data = resource_template.model_dump(by_alias=True, exclude_none=True)

                                if "uriTemplate" in resource_template_data:  # and hasattr(resource_template_data["uriTemplate"], "unicode_string"):
                                    resource_template_data["uri_template"] = str(resource_template_data["uriTemplate"])
                                    resource_template_data["uri"] = str(resource_template_data["uriTemplate"])

                                if "content" not in resource_template_data:
                                    resource_template_data["content"] = ""

                                resources.append(ResourceCreate.model_validate(resource_template_data))
                                resource_templates.append(ResourceCreate.model_validate(resource_template_data))
                            logger.info(f"Fetched {len(resource_templates)} resource templates from gateway")
                        except Exception as e:
                            logger.warning(f"Failed to fetch resource templates: {e}")

                # Fetch prompts if supported
                prompts = []
                if include_prompts:
                    logger.debug(f"Checking for prompts support: {capabilities.get('prompts')}")
                    if capabilities.get("prompts"):
                        try:
                            response = await session.list_prompts()
                            raw_prompts = response.prompts
                            for prompt in raw_prompts:
                                prompt_data = prompt.model_dump(by_alias=True, exclude_none=True)
                                # Add default template if not present
                                if "template" not in prompt_data:
                                    prompt_data["template"] = ""
                                prompts.append(PromptCreate.model_validate(prompt_data))
                            logger.info(f"Fetched {len(prompts)} prompts from gateway")
                        except Exception as e:
                            logger.warning(f"Failed to fetch prompts: {e}")

                return capabilities, tools, resources, prompts
        sanitized_url = sanitize_url_for_logging(server_url, auth_query_params)
        raise GatewayConnectionError(f"Failed to initialize gateway at {sanitized_url}")
