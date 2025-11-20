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
from typing import Any, AsyncGenerator, cast, Dict, Generator, List, Optional, Set, TYPE_CHECKING
from urllib.parse import urlparse, urlunparse
import uuid

# Third-Party
from filelock import FileLock, Timeout
import httpx
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

try:
    # Third-Party
    import redis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logging.info("Redis is not utilized in this environment.")

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import EmailTeam
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import get_db
from mcpgateway.db import Prompt as DbPrompt
from mcpgateway.db import Resource as DbResource
from mcpgateway.db import SessionLocal
from mcpgateway.db import Tool as DbTool
from mcpgateway.observability import create_span
from mcpgateway.schemas import GatewayCreate, GatewayRead, GatewayUpdate, PromptCreate, ResourceCreate, ToolCreate

# logging.getLogger("httpx").setLevel(logging.WARNING)  # Disables httpx logs for regular health checks
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.oauth_manager import OAuthManager
from mcpgateway.services.team_management_service import TeamManagementService
from mcpgateway.services.tool_service import ToolService
from mcpgateway.utils.create_slug import slugify
from mcpgateway.utils.display_name import generate_display_name
from mcpgateway.utils.retry_manager import ResilientHttpClient
from mcpgateway.utils.services_auth import decode_auth, encode_auth
from mcpgateway.utils.sqlalchemy_modifier import json_contains_expr
from mcpgateway.utils.validate_signature import validate_signature

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


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
            >>> service = GatewayService()
            >>> isinstance(service._event_subscribers, list)
            True
            >>> len(service._event_subscribers)
            0
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
            >>> hasattr(service, '_instance_id') or True  # May not exist if no Redis
            True
        """
        self._event_subscribers: List[asyncio.Queue] = []
        self._http_client = ResilientHttpClient(client_args={"timeout": settings.federation_timeout, "verify": not settings.skip_ssl_verify})
        self._health_check_interval = GW_HEALTH_CHECK_INTERVAL
        self._health_check_task: Optional[asyncio.Task] = None
        self._active_gateways: Set[str] = set()  # Track active gateway URLs
        self._stream_response = None
        self._pending_responses = {}
        self.tool_service = ToolService()
        self._gateway_failure_counts: dict[str, int] = {}
        self.oauth_manager = OAuthManager(request_timeout=int(os.getenv("OAUTH_REQUEST_TIMEOUT", "30")), max_retries=int(os.getenv("OAUTH_MAX_RETRIES", "3")))

        # For health checks, we determine the leader instance.
        self.redis_url = settings.redis_url if settings.cache_type == "redis" else None

        # Initialize optional Redis client holder
        self._redis_client: Optional[Any] = None

        if self.redis_url and REDIS_AVAILABLE:
            self._redis_client = redis.from_url(self.redis_url)
            self._instance_id = str(uuid.uuid4())  # Unique ID for this process
            self._leader_key = "gateway_service_leader"
            self._leader_ttl = 40  # seconds
        elif settings.cache_type != "none":
            # Fallback: File-based lock
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

        Args:
            ca_certificate: CA certificate in PEM format

        Returns:
            ssl.SSLContext: Configured SSL context
        """
        ctx = ssl.create_default_context()
        ctx.load_verify_locations(cadata=ca_certificate)
        return ctx

    async def initialize(self) -> None:
        """Initialize the service and start health check if this instance is the leader.

        Raises:
            ConnectionError: When redis ping fails
        """
        logger.info("Initializing gateway service")

        db_gen: Generator = get_db()
        db: Session = next(db_gen)

        user_email = settings.platform_admin_email

        if self._redis_client:
            # Check if Redis is available
            pong = self._redis_client.ping()
            if not pong:
                raise ConnectionError("Redis ping failed.")

            is_leader = self._redis_client.set(self._leader_key, self._instance_id, ex=self._leader_ttl, nx=True)
            if is_leader:
                logger.info("Acquired Redis leadership. Starting health check task.")
                self._health_check_task = asyncio.create_task(self._run_health_checks(db, user_email))
        else:
            # Always create the health check task in filelock mode; leader check is handled inside.
            self._health_check_task = asyncio.create_task(self._run_health_checks(db, user_email))

    async def shutdown(self) -> None:
        """Shutdown the service.

        Examples:
            >>> service = GatewayService()
            >>> service._event_subscribers = ['test']
            >>> service._active_gateways = {'test_gw'}
            >>> import asyncio
            >>> asyncio.run(service.shutdown())
            >>> len(service._event_subscribers)
            0
            >>> len(service._active_gateways)
            0
        """
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass

        await self._http_client.aclose()
        self._event_subscribers.clear()
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
                # Check for existing public gateway with the same slug
                existing_gateway = db.execute(select(DbGateway).where(DbGateway.slug == slug_name, DbGateway.visibility == "public")).scalar_one_or_none()
                if existing_gateway:
                    raise GatewayNameConflictError(existing_gateway.slug, enabled=existing_gateway.enabled, gateway_id=existing_gateway.id, visibility=existing_gateway.visibility)
            elif visibility.lower() == "team" and team_id:
                # Check for existing team gateway with the same slug
                existing_gateway = db.execute(select(DbGateway).where(DbGateway.slug == slug_name, DbGateway.visibility == "team", DbGateway.team_id == team_id)).scalar_one_or_none()
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

            if hasattr(gateway, "auth_headers") and gateway.auth_headers:
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
            capabilities, tools, resources, prompts = await self._initialize_gateway(normalized_url, authentication_headers, gateway.transport, auth_type, oauth_config, ca_certificate)

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
                    template=r.template,
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
                tags=gateway.tags,
                transport=gateway.transport,
                capabilities=capabilities,
                last_seen=datetime.now(timezone.utc),
                auth_type=auth_type,
                auth_value=auth_value,
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
            db.commit()
            db.refresh(db_gateway)

            # Update tracking
            self._active_gateways.add(db_gateway.url)

            # Notify subscribers
            await self._notify_gateway_added(db_gateway)

            # Add team name for response
            db_gateway.team = self._get_team_name(db, db_gateway.team_id)
            return GatewayRead.model_validate(self._prepare_gateway_for_read(db_gateway)).masked()
        except* GatewayConnectionError as ge:  # pragma: no mutate
            if TYPE_CHECKING:
                ge: ExceptionGroup[GatewayConnectionError]
            logger.error(f"GatewayConnectionError in group: {ge.exceptions}")
            raise ge.exceptions[0]
        except* GatewayNameConflictError as gnce:  # pragma: no mutate
            if TYPE_CHECKING:
                gnce: ExceptionGroup[GatewayNameConflictError]
            logger.error(f"GatewayNameConflictError in group: {gnce.exceptions}")
            raise gnce.exceptions[0]
        except* GatewayDuplicateConflictError as guce:  # pragma: no mutate
            if TYPE_CHECKING:
                guce: ExceptionGroup[GatewayDuplicateConflictError]
            logger.error(f"GatewayDuplicateConflictError in group: {guce.exceptions}")
            raise guce.exceptions[0]
        except* ValueError as ve:  # pragma: no mutate
            if TYPE_CHECKING:
                ve: ExceptionGroup[ValueError]
            logger.error(f"ValueErrors in group: {ve.exceptions}")
            raise ve.exceptions[0]
        except* RuntimeError as re:  # pragma: no mutate
            if TYPE_CHECKING:
                re: ExceptionGroup[RuntimeError]
            logger.error(f"RuntimeErrors in group: {re.exceptions}")
            raise re.exceptions[0]
        except* IntegrityError as ie:  # pragma: no mutate
            if TYPE_CHECKING:
                ie: ExceptionGroup[IntegrityError]
            logger.error(f"IntegrityErrors in group: {ie.exceptions}")
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
            # Get the gateway
            gateway = db.execute(select(DbGateway).where(DbGateway.id == gateway_id)).scalar_one_or_none()

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

            # Delete tools that are no longer available from the gateway
            stale_tools = [tool for tool in gateway.tools if tool.original_name not in new_tool_names]
            for tool in stale_tools:
                db.delete(tool)

            # Delete resources that are no longer available from the gateway
            stale_resources = [resource for resource in gateway.resources if resource.uri not in new_resource_uris]
            for resource in stale_resources:
                db.delete(resource)

            # Delete prompts that are no longer available from the gateway
            stale_prompts = [prompt for prompt in gateway.prompts if prompt.name not in new_prompt_names]
            for prompt in stale_prompts:
                db.delete(prompt)

            # Update gateway relationships to reflect deletions
            gateway.tools = [tool for tool in gateway.tools if tool.original_name in new_tool_names]
            gateway.resources = [resource for resource in gateway.resources if resource.uri in new_resource_uris]
            gateway.prompts = [prompt for prompt in gateway.prompts if prompt.name in new_prompt_names]

            # Log cleanup results
            tools_removed = len(stale_tools)
            resources_removed = len(stale_resources)
            prompts_removed = len(stale_prompts)

            if tools_removed > 0:
                logger.info(f"Removed {tools_removed} tools no longer available from gateway")
            if resources_removed > 0:
                logger.info(f"Removed {resources_removed} resources no longer available from gateway")
            if prompts_removed > 0:
                logger.info(f"Removed {prompts_removed} prompts no longer available from gateway")

            # Update gateway capabilities and last_seen
            gateway.capabilities = capabilities
            gateway.last_seen = datetime.now(timezone.utc)

            # Add new items to DB
            items_added = 0
            if tools_to_add:
                db.add_all(tools_to_add)
                items_added += len(tools_to_add)
                logger.info(f"Added {len(tools_to_add)} new tools to database")

            if resources_to_add:
                db.add_all(resources_to_add)
                items_added += len(resources_to_add)
                logger.info(f"Added {len(resources_to_add)} new resources to database")

            if prompts_to_add:
                db.add_all(prompts_to_add)
                items_added += len(prompts_to_add)
                logger.info(f"Added {len(prompts_to_add)} new prompts to database")

            if items_added > 0:
                db.commit()
                logger.info(f"Total {items_added} new items added to database")
            else:
                logger.info("No new items to add to database")
                # Still commit to save any updates to existing items
                db.commit()

            return {"capabilities": capabilities, "tools": tools, "resources": resources, "prompts": prompts}

        except Exception as e:
            logger.error(f"Failed to fetch tools after OAuth for gateway {gateway_id}: {e}")
            raise GatewayConnectionError(f"Failed to fetch tools after OAuth: {str(e)}")

    async def list_gateways(self, db: Session, include_inactive: bool = False, tags: Optional[List[str]] = None) -> List[GatewayRead]:
        """List all registered gateways.

        Args:
            db: Database session
            include_inactive: Whether to include inactive gateways
            tags (Optional[List[str]]): Filter resources by tags. If provided, only resources with at least one matching tag will be returned.

        Returns:
            List of registered gateways

        Examples:
            >>> from mcpgateway.services.gateway_service import GatewayService
            >>> from unittest.mock import MagicMock
            >>> from mcpgateway.schemas import GatewayRead
            >>> service = GatewayService()
            >>> db = MagicMock()
            >>> gateway_obj = MagicMock()
            >>> db.execute.return_value.scalars.return_value.all.return_value = [gateway_obj]
            >>> mocked_gateway_read = MagicMock()
            >>> mocked_gateway_read.masked.return_value = 'gateway_read'
            >>> GatewayRead.model_validate = MagicMock(return_value=mocked_gateway_read)
            >>> import asyncio
            >>> result = asyncio.run(service.list_gateways(db))
            >>> result == ['gateway_read']
            True

            >>> # Test include_inactive parameter
            >>> result_with_inactive = asyncio.run(service.list_gateways(db, include_inactive=True))
            >>> result_with_inactive == ['gateway_read']
            True

            >>> # Test empty result
            >>> db.execute.return_value.scalars.return_value.all.return_value = []
            >>> empty_result = asyncio.run(service.list_gateways(db))
            >>> empty_result
            []
        """
        query = select(DbGateway)

        if not include_inactive:
            query = query.where(DbGateway.enabled)

        if tags:
            query = query.where(json_contains_expr(db, DbGateway.tags, tags, match_any=True))

        gateways = db.execute(query).scalars().all()

        # print("******************************************************************")
        # for g in gateways:
        #         print("----------------------------")
        #         for attr in dir(g):
        #             if not attr.startswith("_"):
        #                 try:
        #                     value = getattr(g, attr)
        #                 except Exception:
        #                     value = "<unreadable>"
        #                 print(f"{attr}: {value}")
        #         # print(f"Gateway oauth_config: {g}")
        #         # print(f"Gateway auth_type: {g['auth_type']}")
        # print("******************************************************************")

        result = []
        for g in gateways:
            team_name = self._get_team_name(db, getattr(g, "team_id", None))
            g.team = team_name
            result.append(GatewayRead.model_validate(self._prepare_gateway_for_read(g)).masked())
        return result

    async def list_gateways_for_user(
        self, db: Session, user_email: str, team_id: Optional[str] = None, visibility: Optional[str] = None, include_inactive: bool = False, skip: int = 0, limit: int = 100
    ) -> List[GatewayRead]:
        """
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
        result = []
        for g in gateways:
            team_name = self._get_team_name(db, getattr(g, "team_id", None))
            g.team = team_name
            logger.info(f"Gateway: {g.team_id}, Team: {team_name}")
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
            # Find gateway
            gateway = db.get(DbGateway, gateway_id)
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
                        existing_gateway = db.execute(select(DbGateway).where(DbGateway.slug == new_slug, DbGateway.visibility == "public", DbGateway.id != gateway_id)).scalar_one_or_none()
                        if existing_gateway:
                            raise GatewayNameConflictError(
                                new_slug,
                                enabled=existing_gateway.enabled,
                                gateway_id=existing_gateway.id,
                                visibility=existing_gateway.visibility,
                            )
                    elif vis == "team" and gateway.team_id:
                        existing_gateway = db.execute(
                            select(DbGateway).where(DbGateway.slug == new_slug, DbGateway.visibility == "team", DbGateway.team_id == gateway.team_id, DbGateway.id != gateway_id)
                        ).scalar_one_or_none()
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

                # Try to reinitialize connection if URL actually changed
                # if url_changed:
                # Initialize empty lists in case initialization fails
                tools_to_add = []
                resources_to_add = []
                prompts_to_add = []

                try:
                    ca_certificate = getattr(gateway, "ca_certificate", None)
                    capabilities, tools, resources, prompts = await self._initialize_gateway(
                        gateway.url, gateway.auth_value, gateway.transport, gateway.auth_type, gateway.oauth_config, ca_certificate
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

                    # Delete tools that are no longer available from the gateway
                    stale_tools = [tool for tool in gateway.tools if tool.original_name not in new_tool_names]
                    for tool in stale_tools:
                        db.delete(tool)

                    # Delete resources that are no longer available from the gateway
                    stale_resources = [resource for resource in gateway.resources if resource.uri not in new_resource_uris]
                    for resource in stale_resources:
                        db.delete(resource)

                    # Delete prompts that are no longer available from the gateway
                    stale_prompts = [prompt for prompt in gateway.prompts if prompt.name not in new_prompt_names]
                    for prompt in stale_prompts:
                        db.delete(prompt)

                    gateway.capabilities = capabilities
                    gateway.tools = [tool for tool in gateway.tools if tool.original_name in new_tool_names]  # keep only still-valid rows
                    gateway.resources = [resource for resource in gateway.resources if resource.uri in new_resource_uris]  # keep only still-valid rows
                    gateway.prompts = [prompt for prompt in gateway.prompts if prompt.name in new_prompt_names]  # keep only still-valid rows

                    # Log cleanup results
                    tools_removed = len(stale_tools)
                    resources_removed = len(stale_resources)
                    prompts_removed = len(stale_prompts)

                    if tools_removed > 0:
                        logger.info(f"Removed {tools_removed} tools no longer available during gateway update")
                    if resources_removed > 0:
                        logger.info(f"Removed {resources_removed} resources no longer available during gateway update")
                    if prompts_removed > 0:
                        logger.info(f"Removed {prompts_removed} prompts no longer available during gateway update")

                    gateway.last_seen = datetime.now(timezone.utc)

                    # Add new items to database session
                    if tools_to_add:
                        db.add_all(tools_to_add)
                    if resources_to_add:
                        db.add_all(resources_to_add)
                    if prompts_to_add:
                        db.add_all(prompts_to_add)

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

                # Notify subscribers
                await self._notify_gateway_updated(gateway)

                logger.info(f"Updated gateway: {gateway.name}")
                gateway.team = self._get_team_name(db, getattr(gateway, "team_id", None))

                return GatewayRead.model_validate(self._prepare_gateway_for_read(gateway))
            # Gateway is inactive and include_inactive is False → skip update, return None
            return None
        except GatewayNameConflictError as ge:
            logger.error(f"GatewayNameConflictError in group: {ge}")
            raise ge
        except GatewayNotFoundError as gnfe:
            logger.error(f"GatewayNotFoundError: {gnfe}")
            raise gnfe
        except IntegrityError as ie:
            logger.error(f"IntegrityErrors in group: {ie}")
            raise ie
        except PermissionError:
            db.rollback()
            raise
        except Exception as e:
            db.rollback()
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
            return GatewayRead.model_validate(self._prepare_gateway_for_read(gateway)).masked()

        raise GatewayNotFoundError(f"Gateway not found: {gateway_id}")

    async def toggle_gateway_status(self, db: Session, gateway_id: str, activate: bool, reachable: bool = True, only_update_reachable: bool = False, user_email: Optional[str] = None) -> GatewayRead:
        """
        Toggle the activation status of a gateway.

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
            gateway = db.get(DbGateway, gateway_id)
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

                        # Delete tools that are no longer available from the gateway
                        stale_tools = [tool for tool in gateway.tools if tool.original_name not in new_tool_names]
                        for tool in stale_tools:
                            db.delete(tool)

                        # Delete resources that are no longer available from the gateway
                        stale_resources = [resource for resource in gateway.resources if resource.uri not in new_resource_uris]
                        for resource in stale_resources:
                            db.delete(resource)

                        # Delete prompts that are no longer available from the gateway
                        stale_prompts = [prompt for prompt in gateway.prompts if prompt.name not in new_prompt_names]
                        for prompt in stale_prompts:
                            db.delete(prompt)

                        gateway.capabilities = capabilities
                        gateway.tools = [tool for tool in gateway.tools if tool.original_name in new_tool_names]  # keep only still-valid rows
                        gateway.resources = [resource for resource in gateway.resources if resource.uri in new_resource_uris]  # keep only still-valid rows
                        gateway.prompts = [prompt for prompt in gateway.prompts if prompt.name in new_prompt_names]  # keep only still-valid rows

                        # Log cleanup results
                        tools_removed = len(stale_tools)
                        resources_removed = len(stale_resources)
                        prompts_removed = len(stale_prompts)

                        if tools_removed > 0:
                            logger.info(f"Removed {tools_removed} tools no longer available during gateway reactivation")
                        if resources_removed > 0:
                            logger.info(f"Removed {resources_removed} resources no longer available during gateway reactivation")
                        if prompts_removed > 0:
                            logger.info(f"Removed {prompts_removed} prompts no longer available during gateway reactivation")

                        gateway.last_seen = datetime.now(timezone.utc)

                        # Add new items to database session
                        if tools_to_add:
                            db.add_all(tools_to_add)
                        if resources_to_add:
                            db.add_all(resources_to_add)
                        if prompts_to_add:
                            db.add_all(prompts_to_add)
                    except Exception as e:
                        logger.warning(f"Failed to initialize reactivated gateway: {e}")
                else:
                    self._active_gateways.discard(gateway.url)

                db.commit()
                db.refresh(gateway)

                tools = db.query(DbTool).filter(DbTool.gateway_id == gateway_id).all()

                if only_update_reachable:
                    for tool in tools:
                        await self.tool_service.toggle_tool_status(db, tool.id, tool.enabled, reachable)
                else:
                    for tool in tools:
                        await self.tool_service.toggle_tool_status(db, tool.id, activate, reachable)

                # Notify subscribers
                if activate:
                    await self._notify_gateway_activated(gateway)
                else:
                    await self._notify_gateway_deactivated(gateway)

                logger.info(f"Gateway status: {gateway.name} - {'enabled' if activate else 'disabled'} and {'accessible' if reachable else 'inaccessible'}")

            gateway.team = self._get_team_name(db, getattr(gateway, "team_id", None))
            return GatewayRead.model_validate(self._prepare_gateway_for_read(gateway)).masked()

        except PermissionError as e:
            raise e
        except Exception as e:
            db.rollback()
            raise GatewayError(f"Failed to toggle gateway status: {str(e)}")

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
            # Find gateway
            gateway = db.get(DbGateway, gateway_id)
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

            # Hard delete gateway
            db.delete(gateway)
            db.commit()

            # Update tracking
            self._active_gateways.discard(gateway.url)

            # Notify subscribers
            await self._notify_gateway_deleted(gateway_info)

            logger.info(f"Permanently deleted gateway: {gateway.name}")

        except PermissionError:
            db.rollback()
            raise
        except Exception as e:
            db.rollback()
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
                "http.url": f"{gateway.url}/rpc",
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
                response = await self._http_client.post(f"{gateway.url}/rpc", json=request, headers=headers)
                response.raise_for_status()
                result = response.json()

                # Update last seen timestamp
                gateway.last_seen = datetime.now(timezone.utc)

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
        # Get all active gateways
        active_gateways = db.execute(select(DbGateway).where(DbGateway.enabled.is_(True))).scalars().all()

        if not active_gateways:
            raise GatewayConnectionError("No active gateways available to forward request")

        errors: List[str] = []

        # Try each active gateway in order
        for gateway in active_gateways:
            try:
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
                                # System operations cannot use user-specific OAuth tokens
                                # Skip OAuth authorization code gateways in system context
                                logger.warning(f"Skipping OAuth authorization code gateway {gateway.name} - user-specific tokens required but no user email provided")
                                continue

                            # First-Party
                            from mcpgateway.services.token_storage_service import TokenStorageService  # pylint: disable=import-outside-toplevel

                            token_storage = TokenStorageService(db)
                            access_token = await token_storage.get_user_token(str(gateway.id), app_user_email)
                            if access_token:
                                headers = {"Authorization": f"Bearer {access_token}"}
                            else:
                                logger.warning(f"No valid OAuth token for user {app_user_email} and gateway {gateway.name}")
                                continue
                    except Exception as oauth_error:
                        logger.warning(f"Failed to obtain OAuth token for gateway {gateway.name}: {oauth_error}")
                        errors.append(f"Gateway {gateway.name}: OAuth error - {str(oauth_error)}")
                        continue
                else:
                    # Handle non-OAuth authentication
                    auth_data = gateway.auth_value or {}
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
                response = await self._http_client.post(f"{gateway.url}/rpc", json=request, headers=headers)
                response.raise_for_status()
                result = response.json()

                # Update last seen timestamp
                gateway.last_seen = datetime.now(timezone.utc)

                # Check for RPC errors
                if "error" in result:
                    errors.append(f"Gateway {gateway.name}: {result['error'].get('message', 'Unknown RPC error')}")
                    continue

                # Success - return the result
                logger.info(f"Successfully forwarded request to gateway {gateway.name}")
                return result.get("result")

            except Exception as e:
                error_msg = f"Gateway {gateway.name}: {str(e)}"
                errors.append(error_msg)
                logger.warning(f"Failed to forward request to gateway {gateway.name}: {e}")
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
                await self.toggle_gateway_status(db, gateway.id, activate=True, reachable=False, only_update_reachable=True)
                self._gateway_failure_counts[gateway.id] = 0  # Reset after deactivation

    async def check_health_of_gateways(self, db: Session, gateways: List[DbGateway], user_email: Optional[str] = None) -> bool:
        """Check health of a batch of gateways.

        Performs an asynchronous health-check for each gateway in `gateways` using
        an Async HTTP client. The function handles different authentication
        modes (OAuth client_credentials and authorization_code, and non-OAuth
        auth headers). When a gateway uses the authorization_code flow, the
        provided `db` and optional `user_email` are used to look up stored user
        tokens. On individual failures the service will record the failure and
        call internal failure handling which may mark a gateway unreachable or
        deactivate it after repeated failures. If a previously unreachable
        gateway becomes healthy again the service will attempt to update its
        reachable status.

        Args:
            db: Database Session used for token lookups and status updates.
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
            >>> db = MagicMock()
            >>> gateways = [MagicMock()]
            >>> gateways[0].ca_certificate = None
            >>> import asyncio
            >>> result = asyncio.run(service.check_health_of_gateways(db, gateways))
            >>> isinstance(result, bool)
            True

            >>> # Test empty gateway list
            >>> empty_result = asyncio.run(service.check_health_of_gateways(db, []))
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
            >>> multi_result = asyncio.run(service.check_health_of_gateways(db, multiple_gateways))
            >>> isinstance(multi_result, bool)
            True
        """
        start_time = time.monotonic()

        # Create trace span for health check batch
        with create_span("gateway.health_check_batch", {"gateway.count": len(gateways), "check.type": "health"}) as batch_span:
            for gateway in gateways:

                if gateway.auth_type == "one_time_auth":
                    continue  # Skip health check for one-time auth gateways as these are authenticated with passthrough headers only

                # Create span for individual gateway health check
                with create_span(
                    "gateway.health_check",
                    {
                        "gateway.name": gateway.name,
                        "gateway.id": str(gateway.id),
                        "gateway.url": gateway.url,
                        "gateway.transport": gateway.transport,
                        "gateway.enabled": gateway.enabled,
                        "http.method": "GET",
                        "http.url": gateway.url,
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
                        return httpx.AsyncClient(
                            verify=ssl_context if ssl_context else True,  # pylint: disable=cell-var-from-loop
                            follow_redirects=True,
                            headers=headers,
                            timeout=timeout or httpx.Timeout(30.0),
                            auth=auth,
                        )

                    async with httpx.AsyncClient(verify=ssl_context) as client:
                        logger.debug(f"Checking health of gateway: {gateway.name} ({gateway.url})")
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
                                        if not user_email:
                                            if span:
                                                span.set_attribute("health.status", "unhealthy")
                                                span.set_attribute("error.message", "User email required for OAuth token")
                                            await self._handle_gateway_failure(gateway)

                                        access_token: str = await token_storage.get_user_token(gateway.id, user_email)

                                        if access_token:
                                            headers["Authorization"] = f"Bearer {access_token}"
                                        else:
                                            if span:
                                                span.set_attribute("health.status", "unhealthy")
                                                span.set_attribute("error.message", "No valid OAuth token for user")
                                            await self._handle_gateway_failure(gateway)
                                    except Exception as e:
                                        logger.error(f"Failed to obtain stored OAuth token for gateway {gateway.name}: {e}")
                                        if span:
                                            span.set_attribute("health.status", "unhealthy")
                                            span.set_attribute("error.message", "Failed to obtain stored OAuth token")
                                        await self._handle_gateway_failure(gateway)
                                else:
                                    # For Client Credentials flow, get token directly
                                    try:
                                        access_token: str = await self.oauth_manager.get_access_token(gateway.oauth_config)
                                        headers["Authorization"] = f"Bearer {access_token}"
                                    except Exception as e:
                                        if span:
                                            span.set_attribute("health.status", "unhealthy")
                                            span.set_attribute("error.message", str(e))
                                        await self._handle_gateway_failure(gateway)
                            else:
                                # Handle non-OAuth authentication (existing logic)
                                auth_data = gateway.auth_value or {}
                                if isinstance(auth_data, str):
                                    headers = decode_auth(auth_data)
                                elif isinstance(auth_data, dict):
                                    headers = {str(k): str(v) for k, v in auth_data.items()}
                                else:
                                    headers = {}

                            # Perform the GET and raise on 4xx/5xx
                            if (gateway.transport).lower() == "sse":
                                timeout = httpx.Timeout(settings.health_check_timeout)
                                async with client.stream("GET", gateway.url, headers=headers, timeout=timeout) as response:
                                    # This will raise immediately if status is 4xx/5xx
                                    response.raise_for_status()
                                    if span:
                                        span.set_attribute("http.status_code", response.status_code)
                            elif (gateway.transport).lower() == "streamablehttp":
                                async with streamablehttp_client(url=gateway.url, headers=headers, timeout=settings.health_check_timeout, httpx_client_factory=get_httpx_client_factory) as (
                                    read_stream,
                                    write_stream,
                                    _get_session_id,
                                ):
                                    async with ClientSession(read_stream, write_stream) as session:
                                        # Initialize the session
                                        response = await session.initialize()

                            # Reactivate gateway if it was previously inactive and health check passed now
                            if gateway.enabled and not gateway.reachable:
                                logger.info(f"Reactivating gateway: {gateway.name}, as it is healthy now")
                                await self.toggle_gateway_status(db, gateway.id, activate=True, reachable=True, only_update_reachable=True)

                            # Mark successful check
                            gateway.last_seen = datetime.now(timezone.utc)

                            if span:
                                span.set_attribute("health.status", "healthy")
                                span.set_attribute("success", True)

                        except Exception as e:
                            if span:
                                span.set_attribute("health.status", "unhealthy")
                                span.set_attribute("error.message", str(e))
                            await self._handle_gateway_failure(gateway)

            # Set batch span success metrics
            if batch_span:
                batch_span.set_attribute("success", True)
                batch_span.set_attribute("duration.ms", (time.monotonic() - start_time) * 1000)

            # All gateways passed
            return True

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
            >>> len(service._event_subscribers)
            0
            >>> async_gen = service.subscribe_events()
            >>> hasattr(async_gen, '__aiter__')
            True
            >>> # Test event publishing works
            >>> import asyncio
            >>> async def test_event():
            ...     queue = asyncio.Queue()
            ...     service._event_subscribers.append(queue)
            ...     await service._publish_event({"type": "test"})
            ...     event = await queue.get()
            ...     return event["type"]
            >>> asyncio.run(test_event())
            'test'
        """
        queue: asyncio.Queue = asyncio.Queue()
        self._event_subscribers.append(queue)
        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            self._event_subscribers.remove(queue)

    async def _initialize_gateway(
        self,
        url: str,
        authentication: Optional[Dict[str, str]] = None,
        transport: str = "SSE",
        auth_type: Optional[str] = None,
        oauth_config: Optional[Dict[str, Any]] = None,
        ca_certificate: Optional[bytes] = None,
    ) -> tuple[Dict[str, Any], List[ToolCreate], List[ResourceCreate], List[PromptCreate]]:
        """Initialize connection to a gateway and retrieve its capabilities.

        Connects to an MCP gateway using the specified transport protocol,
        performs the MCP handshake, and retrieves capabilities, tools,
        resources, and prompts from the gateway.

        Args:
            url: Gateway URL to connect to
            authentication: Optional authentication headers for the connection
            transport: Transport protocol - "SSE" or "StreamableHTTP"
            auth_type: Authentication type - "basic", "bearer", "headers", "oauth" or None
            oauth_config: OAuth configuration if auth_type is "oauth"
            ca_certificate: CA certificate for SSL verification

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

            # Handle OAuth authentication
            if auth_type == "oauth" and oauth_config:
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
                capabilities, tools, resources, prompts = await self.connect_to_sse_server(url, authentication, ca_certificate)
            elif transport.lower() == "streamablehttp":
                capabilities, tools, resources, prompts = await self.connect_to_streamablehttp_server(url, authentication, ca_certificate)

            return capabilities, tools, resources, prompts
        except Exception as e:
            logger.error(f"Gateway initialization failed for {url}: {str(e)}", exc_info=True)
            raise GatewayConnectionError(f"Failed to initialize gateway at {url}")

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

    async def _run_health_checks(self, db: Session, user_email: str) -> None:
        """Run health checks periodically,
        Uses Redis or FileLock - for multiple workers.
        Uses simple health check for single worker mode.

        Args:
            db: Database session to use for health checks
            user_email: Email of the user to notify in case of issues

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
                    # Redis-based leader check
                    current_leader = self._redis_client.get(self._leader_key)
                    if current_leader != self._instance_id.encode():
                        return
                    self._redis_client.expire(self._leader_key, self._leader_ttl)

                    # Run health checks
                    gateways = await asyncio.to_thread(self._get_gateways)
                    if gateways:
                        await self.check_health_of_gateways(db, gateways, user_email)

                    await asyncio.sleep(self._health_check_interval)

                elif settings.cache_type == "none":
                    try:
                        # For single worker mode, run health checks directly
                        gateways = await asyncio.to_thread(self._get_gateways)
                        if gateways:
                            await self.check_health_of_gateways(db, gateways, user_email)
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
                                await self.check_health_of_gateways(db, gateways, user_email)
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

    def _prepare_gateway_for_read(self, gateway: DbGateway) -> DbGateway:
        """Prepare a gateway object for GatewayRead validation.

        Ensures auth_value is in the correct format (encoded string) for the schema.

        Args:
            gateway: Gateway database object

        Returns:
            Gateway object with properly formatted auth_value
        """
        # If auth_value is a dict, encode it to string for GatewayRead schema
        if isinstance(gateway.auth_value, dict):
            gateway.auth_value = encode_auth(gateway.auth_value)
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
        tools_to_add = []

        for tool in tools:
            if tool is None:
                logger.warning("Skipping None tool in tools list")
                continue

            try:
                # Check if tool already exists for this gateway
                existing_tool = db.execute(select(DbTool).where(DbTool.original_name == tool.name).where(DbTool.gateway_id == gateway.id)).scalar_one_or_none()
                if existing_tool:
                    # Update existing tool if there are changes
                    fields_to_update = False

                    # Check basic field changes
                    basic_fields_changed = (
                        existing_tool.url != gateway.url or existing_tool.description != tool.description or existing_tool.integration_type != "MCP" or existing_tool.request_type != tool.request_type
                    )

                    # Check schema and configuration changes
                    schema_fields_changed = existing_tool.headers != tool.headers or existing_tool.input_schema != tool.input_schema or existing_tool.jsonpath_filter != tool.jsonpath_filter

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
        resources_to_add = []

        for resource in resources:
            if resource is None:
                logger.warning("Skipping None resource in resources list")
                continue

            try:
                # Check if resource already exists for this gateway
                existing_resource = db.execute(select(DbResource).where(DbResource.uri == resource.uri).where(DbResource.gateway_id == gateway.id)).scalar_one_or_none()

                if existing_resource:
                    # Update existing resource if there are changes
                    fields_to_update = False

                    if (
                        existing_resource.name != resource.name
                        or existing_resource.description != resource.description
                        or existing_resource.mime_type != resource.mime_type
                        or existing_resource.template != resource.template
                        or existing_resource.visibility != gateway.visibility
                    ):
                        fields_to_update = True

                    if fields_to_update:
                        existing_resource.name = resource.name
                        existing_resource.description = resource.description
                        existing_resource.mime_type = resource.mime_type
                        existing_resource.template = resource.template
                        existing_resource.visibility = gateway.visibility
                        logger.debug(f"Updated existing resource: {resource.uri}")
                else:
                    # Create new resource if it doesn't exist
                    db_resource = DbResource(
                        uri=resource.uri,
                        name=resource.name,
                        description=resource.description,
                        mime_type=resource.mime_type,
                        template=resource.template,
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
        prompts_to_add = []

        for prompt in prompts:
            if prompt is None:
                logger.warning("Skipping None prompt in prompts list")
                continue

            try:
                # Check if prompt already exists for this gateway
                existing_prompt = db.execute(select(DbPrompt).where(DbPrompt.name == prompt.name).where(DbPrompt.gateway_id == gateway.id)).scalar_one_or_none()

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
                        description=prompt.description,
                        template=prompt.template if hasattr(prompt, "template") else "",
                        argument_schema={},  # Use argument_schema instead of arguments
                        gateway_id=gateway.id,
                        created_by="system",
                        created_via=created_via,
                        visibility=gateway.visibility,
                    )
                    prompts_to_add.append(db_prompt)
                    logger.debug(f"Created new prompt: {prompt.name}")
            except Exception as e:
                logger.warning(f"Failed to process prompt {getattr(prompt, 'name', 'unknown')}: {e}")
                continue

        return prompts_to_add

    async def _publish_event(self, event: Dict[str, Any]) -> None:
        """Publish event to all subscribers.

        Args:
            event: event dictionary

        Examples:
            >>> import asyncio
            >>> service = GatewayService()
            >>> test_queue = asyncio.Queue()
            >>> service._event_subscribers = [test_queue]
            >>> test_event = {"type": "test", "data": {}}
            >>> asyncio.run(service._publish_event(test_event))
            >>> # Verify event was published
            >>> asyncio.run(test_queue.get()) == test_event
            True

            >>> # Test with multiple subscribers
            >>> queue1 = asyncio.Queue()
            >>> queue2 = asyncio.Queue()
            >>> service._event_subscribers = [queue1, queue2]
            >>> event = {"type": "multi_test"}
            >>> asyncio.run(service._publish_event(event))
            >>> asyncio.run(queue1.get())["type"]
            'multi_test'
            >>> asyncio.run(queue2.get())["type"]
            'multi_test'
        """
        for queue in self._event_subscribers:
            await queue.put(event)

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
                    tools = [tool.model_dump(by_alias=True, exclude_none=True) for tool in tools]

                    tools = [ToolCreate.model_validate(tool) for tool in tools]
                    if tools:
                        logger.info(f"Fetched {len(tools)} tools from gateway")
                    # Fetch resources if supported
                    resources = []
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
                                            mime_type=resource_data.get("mime_type"),
                                            template=resource_data.get("template"),
                                            content="",
                                        )
                                    )
                                logger.info(f"Fetched {len(resources)} resources from gateway")
                        except Exception as e:
                            logger.warning(f"Failed to fetch resources: {e}")

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
            logger.error(f"SSE connection error details: {type(e).__name__}: {str(e)}", exc_info=True)
            raise GatewayConnectionError(f"Failed to connect to SSE server at {server_url}: {str(e)}")

    async def connect_to_sse_server(self, server_url: str, authentication: Optional[Dict[str, str]] = None, ca_certificate: Optional[bytes] = None):
        """Connect to an MCP server running with SSE transport.

        Args:
            server_url: The URL of the SSE MCP server to connect to.
            authentication: Optional dictionary containing authentication headers.
            ca_certificate: Optional CA certificate for SSL verification.

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
            if ca_certificate:
                ctx = self.create_ssl_context(ca_certificate)
            else:
                ctx = None
            return httpx.AsyncClient(
                verify=ctx if ctx else True,
                follow_redirects=True,
                headers=headers,
                timeout=timeout or httpx.Timeout(30.0),
                auth=auth,
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
                tools = [tool.model_dump(by_alias=True, exclude_none=True) for tool in tools]

                tools = [ToolCreate.model_validate(tool) for tool in tools]
                if tools:
                    logger.info(f"Fetched {len(tools)} tools from gateway")
                # Fetch resources if supported
                resources = []
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
                                        mime_type=resource_data.get("mime_type"),
                                        template=resource_data.get("template"),
                                        content="",
                                    )
                                )
                            logger.info(f"Fetched {len(resources)} resources from gateway")
                    except Exception as e:
                        logger.warning(f"Failed to fetch resources: {e}")

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
        raise GatewayConnectionError(f"Failed to initialize gateway at {server_url}")

    async def connect_to_streamablehttp_server(self, server_url: str, authentication: Optional[Dict[str, str]] = None, ca_certificate: Optional[bytes] = None):
        """Connect to an MCP server running with Streamable HTTP transport.

        Args:
            server_url: The URL of the Streamable HTTP MCP server to connect to.
            authentication: Optional dictionary containing authentication headers.
            ca_certificate: Optional CA certificate for SSL verification.

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
            if ca_certificate:
                ctx = self.create_ssl_context(ca_certificate)
            else:
                ctx = None
            return httpx.AsyncClient(
                verify=ctx if ctx else True,
                follow_redirects=True,
                headers=headers,
                timeout=timeout or httpx.Timeout(30.0),
                auth=auth,
            )

        async with streamablehttp_client(url=server_url, headers=authentication, httpx_client_factory=get_httpx_client_factory) as (read_stream, write_stream, _get_session_id):
            async with ClientSession(read_stream, write_stream) as session:
                # Initialize the session
                response = await session.initialize()
                capabilities = response.capabilities.model_dump(by_alias=True, exclude_none=True)
                logger.debug(f"Server capabilities: {capabilities}")

                response = await session.list_tools()
                tools = response.tools
                tools = [tool.model_dump(by_alias=True, exclude_none=True) for tool in tools]

                tools = [ToolCreate.model_validate(tool) for tool in tools]
                for tool in tools:
                    tool.request_type = "STREAMABLEHTTP"
                if tools:
                    logger.info(f"Fetched {len(tools)} tools from gateway")

                # Fetch resources if supported
                resources = []
                logger.debug(f"Checking for resources support: {capabilities.get('resources')}")
                if capabilities.get("resources"):
                    try:
                        response = await session.list_resources()
                        raw_resources = response.resources
                        resources = []
                        for resource in raw_resources:
                            resource_data = resource.model_dump(by_alias=True, exclude_none=True)
                            # Convert AnyUrl to string if present
                            if "uri" in resource_data and hasattr(resource_data["uri"], "unicode_string"):
                                resource_data["uri"] = str(resource_data["uri"])
                            # Add default content if not present
                            if "content" not in resource_data:
                                resource_data["content"] = ""
                            resources.append(ResourceCreate.model_validate(resource_data))
                        logger.info(f"Fetched {len(resources)} resources from gateway")
                    except Exception as e:
                        logger.warning(f"Failed to fetch resources: {e}")

                # Fetch prompts if supported
                prompts = []
                logger.debug(f"Checking for prompts support: {capabilities.get('prompts')}")
                if capabilities.get("prompts"):
                    try:
                        response = await session.list_prompts()
                        raw_prompts = response.prompts
                        prompts = []
                        for prompt in raw_prompts:
                            prompt_data = prompt.model_dump(by_alias=True, exclude_none=True)
                            # Add default template if not present
                            if "template" not in prompt_data:
                                prompt_data["template"] = ""
                            prompts.append(PromptCreate.model_validate(prompt_data))
                    except Exception as e:
                        logger.warning(f"Failed to fetch prompts: {e}")

                return capabilities, tools, resources, prompts
        raise GatewayConnectionError(f"Failed to initialize gateway at{server_url}")
