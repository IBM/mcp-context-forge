# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/catalog_service.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

MCP Server Catalog Service.

This service manages the catalog of available MCP servers that can be
easily registered with one-click from the admin UI.
"""

# Standard
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from pathlib import Path
import time
from typing import Any, Dict, List, Optional

# Third-Party
from sqlalchemy import select
from sqlalchemy.orm import Session
import yaml

# First-Party
from mcpgateway.config import settings
from mcpgateway.utils.admin_check import is_admin_bypass_granted
from mcpgateway.schemas import (
    CatalogBulkRegisterRequest,
    CatalogBulkRegisterResponse,
    CatalogListRequest,
    CatalogListResponse,
    CatalogServer,
    CatalogServerRegisterRequest,
    CatalogServerRegisterResponse,
    CatalogServerStatusResponse,
)
from mcpgateway.services.gateway_service import GatewayService
from mcpgateway.utils.create_slug import slugify
from mcpgateway.validation.tags import validate_tags_field

logger = logging.getLogger(__name__)

# Business-failure messages the v1 router maps to HTTP 404/409.
CATALOG_REGISTER_NOT_FOUND_MSG = "Server not found in catalog"
CATALOG_REGISTER_ALREADY_REGISTERED_MSG = "Server already registered"


class CatalogRegistrationPermissionError(PermissionError):
    """Raised when a catalog registration is rejected due to scope/team policy."""


@dataclass(frozen=True)
class _CatalogGatewayMatch:
    """Caller-visible gateway data needed to derive catalog registration state."""

    gateway_id: str
    enabled: bool
    auth_type: Optional[str]
    oauth_config: Optional[Dict[str, Any]]
    owner_email: Optional[str]
    created_via: Optional[str]


class CatalogService:
    """Service for managing MCP server catalog."""

    def __init__(self):
        """Initialize the catalog service."""
        self._catalog_cache: Optional[Dict[str, Any]] = None
        self._cache_timestamp: float = 0
        self._gateway_service = GatewayService()

    def _resolve_registration_scope(
        self,
        db: Session,
        request: Optional[CatalogServerRegisterRequest],
        owner_email: str,
        token_teams: Optional[List[str]],
    ) -> tuple:
        """Resolve visibility and team_id for a catalog registration.

        Args:
            db: Database session
            request: Registration request with optional visibility/team overrides
            owner_email: Authenticated caller's email
            token_teams: Token-scoped team list (None=admin bypass, []=public-only)

        Returns:
            Tuple of (visibility, team_id)

        Raises:
            CatalogRegistrationPermissionError: If the caller lacks permission for the requested scope.
        """
        visibility = request.visibility if request and request.visibility else "private"
        # Normalize whitespace-only team IDs the same way as admin handlers.
        raw_team_id = request.team_id if request and request.team_id else None
        requested_team_id = raw_team_id.strip() if raw_team_id and raw_team_id.strip() else None

        # Reject unknown or empty owner
        if not owner_email or owner_email == "unknown":
            raise CatalogRegistrationPermissionError("Authenticated identity required for catalog registration")

        # Public-only tokens can only create explicitly public gateways
        if token_teams is not None and len(token_teams) == 0 and visibility != "public":
            raise CatalogRegistrationPermissionError("Public-only tokens can only create public catalog registrations")

        # Block public visibility for team-scoped registrations when the platform flag is disabled
        if not settings.allow_public_visibility and visibility == "public" and requested_team_id:
            raise CatalogRegistrationPermissionError("Public visibility is disabled by platform configuration (ALLOW_PUBLIC_VISIBILITY=false).")

        # Team visibility requires a team_id
        if visibility == "team" and not requested_team_id:
            raise CatalogRegistrationPermissionError("team_id is required when visibility is 'team'")

        # Validate team_id against token scope
        if requested_team_id and token_teams is not None and requested_team_id not in token_teams:
            raise CatalogRegistrationPermissionError("Requested team is not in the caller's token scope")

        # Validate team membership when a team is specified.
        # One JOIN mirrors TeamManagementService's verify_team_for_user approach and
        # avoids two serial round-trips + an intermediate commit.
        if requested_team_id:
            # First-Party
            from mcpgateway.db import EmailTeam as DbEmailTeam  # pylint: disable=import-outside-toplevel
            from mcpgateway.db import EmailTeamMember as DbEmailTeamMember  # pylint: disable=import-outside-toplevel

            membership = db.execute(
                select(DbEmailTeamMember)
                .join(DbEmailTeam, DbEmailTeam.id == DbEmailTeamMember.team_id)
                .where(
                    DbEmailTeamMember.team_id == requested_team_id,
                    DbEmailTeamMember.user_email == owner_email,
                    DbEmailTeamMember.is_active == True,  # noqa: E712  # pylint: disable=singleton-comparison
                    DbEmailTeam.is_active == True,  # noqa: E712  # pylint: disable=singleton-comparison
                )
            ).scalar_one_or_none()
            if not membership:
                raise CatalogRegistrationPermissionError(f"Caller is not an active member of team '{requested_team_id}' or team is inactive")

            db.commit()

        return (visibility, requested_team_id)

    async def load_catalog(self, force_reload: bool = False) -> Dict[str, Any]:
        """Load catalog from YAML file.

        Args:
            force_reload: Force reload even if cache is valid

        Returns:
            Catalog data dictionary
        """
        # Check cache validity
        cache_age = time.time() - self._cache_timestamp
        if not force_reload and self._catalog_cache and cache_age < settings.mcpgateway_catalog_cache_ttl:
            return self._catalog_cache

        try:
            catalog_path = Path(settings.mcpgateway_catalog_file)

            # Try multiple locations for the catalog file
            if not catalog_path.is_absolute():
                # Try current directory first
                if not catalog_path.exists():
                    # Try project root
                    catalog_path = Path(__file__).parent.parent.parent / settings.mcpgateway_catalog_file

            if not catalog_path.exists():
                logger.warning("Catalog file not found: %s", catalog_path)
                return {"catalog_servers": [], "categories": [], "auth_types": []}

            content = await asyncio.to_thread(catalog_path.read_text, encoding="utf-8")
            catalog_data = yaml.safe_load(content)

            # Update cache
            self._catalog_cache = catalog_data
            self._cache_timestamp = time.time()

            logger.info("Loaded %s servers from catalog", len(catalog_data.get("catalog_servers", [])))
            return catalog_data

        except Exception as e:
            logger.error("Failed to load catalog: %s", e)
            return {"catalog_servers": [], "categories": [], "auth_types": []}

    def _get_registry_cache(self):
        """Get registry cache instance lazily.

        Returns:
            RegistryCache instance or None if unavailable.
        """
        try:
            # First-Party
            from mcpgateway.cache.registry_cache import get_registry_cache  # pylint: disable=import-outside-toplevel

            return get_registry_cache()
        except ImportError:
            return None

    async def get_catalog_servers(self, request: CatalogListRequest, db, user_email: Optional[str] = None, token_teams: Optional[List[str]] = None) -> CatalogListResponse:
        """Get filtered list of catalog servers.

        Args:
            request: Filter criteria
            db: Database session
            user_email: Optional requester email for scoped registration state
            token_teams: Optional requester team scope for scoped registration state

        Returns:
            Filtered catalog servers response
        """
        is_scoped_request = user_email is not None or token_teams is not None

        # Scope is part of the cache key: cached registration state must never
        # cross caller identities or Layer-1 team scopes. Keep ``None``
        # distinct from an empty tuple because it represents admin bypass,
        # while the latter is public-only access.
        cache_token_teams = tuple(sorted(set(token_teams))) if token_teams is not None else None

        # Check cache first
        cache = self._get_registry_cache()
        if cache:
            filters_hash = cache.hash_filters(
                category=request.category,
                auth_type=request.auth_type,
                provider=request.provider,
                search=request.search,
                tags=sorted(request.tags) if request.tags else None,
                show_registered_only=request.show_registered_only,
                show_available_only=request.show_available_only,
                offset=request.offset,
                limit=request.limit,
                user_email=user_email,
                token_teams=cache_token_teams,
            )
            cached = await cache.get("catalog", filters_hash)
            if cached is not None:
                return CatalogListResponse.model_validate(cached)

        catalog_data = await self.load_catalog()
        servers = catalog_data.get("catalog_servers", [])

        # Select one deterministic caller-visible gateway match per catalog URL.
        selected_gateways_by_url: Dict[str, _CatalogGatewayMatch] = {}
        if servers:
            try:
                # Ensure we're using the correct Gateway model
                # First-Party
                from mcpgateway.db import Gateway as DbGateway  # pylint: disable=import-outside-toplevel

                # Query all gateways (enabled and disabled) to properly track registration status
                # Include auth_type and oauth_config to distinguish OAuth servers needing setup
                # from OAuth servers that were manually disabled after configuration
                stmt = select(
                    DbGateway.id,
                    DbGateway.url,
                    DbGateway.enabled,
                    DbGateway.auth_type,
                    DbGateway.oauth_config,
                    DbGateway.visibility,
                    DbGateway.team_id,
                    DbGateway.owner_email,
                    DbGateway.created_via,
                )
                result = db.execute(stmt)
                for row in result:
                    gateway_id, url, enabled, auth_type, oauth_config, visibility, team_id, owner_email, created_via = row
                    if is_scoped_request and not self._can_view_registered_gateway(db, visibility, team_id, owner_email, user_email, token_teams):
                        continue

                    candidate = _CatalogGatewayMatch(
                        gateway_id=str(gateway_id),
                        enabled=enabled,
                        auth_type=auth_type,
                        oauth_config=oauth_config,
                        owner_email=owner_email,
                        created_via=created_via,
                    )
                    selected = selected_gateways_by_url.get(url)
                    if selected is None or self._catalog_gateway_match_priority(candidate, user_email) < self._catalog_gateway_match_priority(selected, user_email):
                        selected_gateways_by_url[url] = candidate
            except Exception as e:
                logger.warning("Failed to check registered servers: %s", e)
                # Continue without marking registered servers
                selected_gateways_by_url = {}

        # Convert to CatalogServer objects and mark registered ones
        catalog_servers = []
        for server_data in servers:
            server = CatalogServer(**server_data)
            selected_gateway = selected_gateways_by_url.get(server.url)
            if selected_gateway is not None:
                server.is_registered = True
                server.gateway_id = selected_gateway.gateway_id
                # Only disabled OAuth gateways with no OAuth config still need setup.
                server.requires_oauth_config = not selected_gateway.enabled and selected_gateway.auth_type == "oauth" and not selected_gateway.oauth_config
            # Set availability based on registration status (registered servers are assumed available)
            # Individual health checks can be done via the /status endpoint
            server.is_available = server.is_registered or server_data.get("is_available", True)
            catalog_servers.append(server)

        # Apply filters
        filtered = catalog_servers

        if request.category:
            filtered = [s for s in filtered if s.category == request.category]

        if request.auth_type:
            filtered = [s for s in filtered if s.auth_type == request.auth_type]

        if request.provider:
            filtered = [s for s in filtered if s.provider == request.provider]

        if request.search:
            search_lower = request.search.lower()
            filtered = [s for s in filtered if search_lower in s.name.lower() or search_lower in s.description.lower()]

        if request.tags:
            filtered = [s for s in filtered if any(tag in s.tags for tag in request.tags)]

        if request.show_registered_only:
            filtered = [s for s in filtered if s.is_registered]

        if request.show_available_only:
            filtered = [s for s in filtered if s.is_available]

        # Pagination
        total = len(filtered)
        start = request.offset
        end = start + request.limit
        paginated = filtered[start:end]

        # Collect unique values for filters
        all_categories = sorted(set(s.category for s in catalog_servers))
        all_auth_types = sorted(set(s.auth_type for s in catalog_servers))
        all_providers = sorted(set(s.provider for s in catalog_servers))
        all_tags = sorted(set(tag for s in catalog_servers for tag in s.tags))

        response = CatalogListResponse(servers=paginated, total=total, categories=all_categories, auth_types=all_auth_types, providers=all_providers, all_tags=all_tags)

        # Store in cache
        if cache:
            try:
                cache_data = response.model_dump(mode="json")
                await cache.set("catalog", cache_data, filters_hash)
            except Exception as e:
                logger.debug("Failed to cache catalog response: %s", e)

        return response

    @staticmethod
    def _catalog_gateway_match_priority(match: _CatalogGatewayMatch, user_email: Optional[str]) -> tuple[int, str]:
        """Return deterministic selection priority for one visible URL match.

        Args:
            match: Visible gateway candidate.
            user_email: Authenticated caller email, when available.

        Returns:
            Priority bucket followed by stable gateway-ID ordering.
        """
        caller_owned = bool(user_email and match.owner_email == user_email)
        catalog_created = match.created_via == "catalog"

        if caller_owned and catalog_created:
            priority = 0
        elif caller_owned:
            priority = 1
        elif catalog_created:
            priority = 2
        else:
            priority = 3

        return priority, match.gateway_id

    @staticmethod
    def _can_view_registered_gateway(
        db: Session,
        visibility: str,
        team_id: Optional[str],
        owner_email: Optional[str],
        user_email: Optional[str],
        token_teams: Optional[List[str]],
    ) -> bool:
        """Return whether a registered gateway is visible to a scoped catalog caller."""
        if visibility == "public":
            return True

        if is_admin_bypass_granted(db, user_email, token_teams):
            if visibility == "private":
                return bool(owner_email and owner_email == user_email)
            return True

        if not user_email:
            return False

        if token_teams is not None and len(token_teams) == 0:
            return False

        if visibility == "private":
            return bool(owner_email and owner_email == user_email)

        if visibility == "team" and team_id:
            return bool(token_teams and team_id in token_teams)

        return False

    async def register_catalog_server(
        self,
        catalog_id: str,
        request: Optional[CatalogServerRegisterRequest],
        db: Session,
        *,
        created_by: str,
        owner_email: str,
        token_teams: Optional[List[str]],
        _resolved_scope: Optional[tuple] = None,
    ) -> CatalogServerRegisterResponse:
        """Register a catalog server as a gateway.

        Args:
            catalog_id: Catalog server ID
            request: Registration request with optional overrides
            db: Database session
            created_by: Identity of the caller creating the gateway
            owner_email: Email of the gateway owner (derived from auth, never client-supplied)
            token_teams: Token-scoped team list (None=admin bypass, []=public-only)
            _resolved_scope: Pre-validated (visibility, team_id) tuple; skips re-validation when set.
                Only pass from bulk_register_servers after upfront validation.

        Returns:
            Registration response

        Raises:
            CatalogRegistrationPermissionError: If scope validation fails.
        """
        try:
            # Resolve visibility and team scope before any persistence
            if _resolved_scope is not None:
                visibility, resolved_team_id = _resolved_scope
            else:
                visibility, resolved_team_id = self._resolve_registration_scope(db, request, owner_email, token_teams)
            # Load catalog to find the server
            catalog_data = await self.load_catalog()
            servers = catalog_data.get("catalog_servers", [])

            # Find the server in catalog
            server_data = None
            for s in servers:
                if s.get("id") == catalog_id:
                    server_data = s
                    break

            if not server_data:
                return CatalogServerRegisterResponse(success=False, server_id="", message=CATALOG_REGISTER_NOT_FOUND_MSG, error="Invalid catalog server ID")

            # Check if already registered
            try:
                # First-Party
                from mcpgateway.db import Gateway as DbGateway  # pylint: disable=import-outside-toplevel

                stmt = select(DbGateway).where(DbGateway.url == server_data["url"])
                result = db.execute(stmt)
                existing = result.scalar_one_or_none()
            except Exception as e:
                logger.warning("Error checking existing registration: %s", e)
                existing = None

            if existing:
                return CatalogServerRegisterResponse(
                    success=False, server_id=str(existing.id), message=CATALOG_REGISTER_ALREADY_REGISTERED_MSG, error="This server is already registered in the system"
                )

            # Prepare gateway creation request using proper schema
            # First-Party
            from mcpgateway.schemas import GatewayCreate  # pylint: disable=import-outside-toplevel

            # Use explicit transport if provided, otherwise auto-detect from URL
            transport = server_data.get("transport")
            if not transport:
                # Detect transport type from URL or use SSE as default
                url = server_data["url"].lower()
                # Check for WebSocket patterns (highest priority)
                if url.startswith("ws://") or url.startswith("wss://"):
                    transport = "WEBSOCKET"  # WebSocket transport for ws:// and wss:// URLs
                # Check for SSE patterns
                elif url.endswith("/sse") or "/sse/" in url:
                    transport = "SSE"  # SSE endpoints or paths containing /sse/
                # Then check for HTTP patterns
                elif "/mcp" in url or url.endswith("/"):
                    transport = "STREAMABLEHTTP"  # Generic MCP endpoints typically use HTTP
                else:
                    transport = "SSE"  # Default to SSE for most catalog servers

            # Check for IPv6 URLs early to provide a clear error message
            url = server_data["url"]
            if "[" in url or "]" in url:
                return CatalogServerRegisterResponse(
                    success=False, server_id="", message="Registration failed", error="IPv6 URLs are not currently supported for security reasons. Please use IPv4 or domain names."
                )

            # Prepare the gateway creation data
            gateway_data = {
                "name": request.name if request and request.name else server_data["name"],
                "url": server_data["url"],
                "description": server_data["description"],
                "transport": transport,
                "tags": server_data.get("tags", []),
            }

            # Set authentication based on server requirements
            auth_type = server_data.get("auth_type", "Open")
            skip_initialization = False  # Flag to skip connection test for OAuth servers without creds

            if request and request.api_key and auth_type != "Open":
                # Handle all possible auth types from the catalog
                if auth_type in ["API Key", "API"]:
                    # Use bearer token for API key authentication
                    gateway_data["auth_type"] = "bearer"
                    gateway_data["auth_token"] = request.api_key
                elif auth_type in ["OAuth2.1", "OAuth", "OAuth2.1 & API Key"]:
                    # OAuth servers and mixed auth may need API key as a bearer token
                    gateway_data["auth_type"] = "bearer"
                    gateway_data["auth_token"] = request.api_key
                else:
                    # For any other auth types, use custom headers (as list of dicts)
                    gateway_data["auth_type"] = "authheaders"
                    gateway_data["auth_headers"] = [{"key": "X-API-Key", "value": request.api_key}]
            elif auth_type in ["OAuth2.1", "OAuth"]:
                # OAuth server without credentials - register but skip initialization
                # User will need to complete OAuth flow later
                skip_initialization = True
                logger.info("Registering OAuth server %s without credentials - OAuth flow required later", server_data["name"])

            # For OAuth servers without credentials, register directly without connection test
            if skip_initialization:
                # Create minimal gateway entry without tool discovery
                # First-Party
                from mcpgateway.db import Gateway as DbGateway  # pylint: disable=import-outside-toplevel

                gateway_create = GatewayCreate(**gateway_data)
                slug_name = slugify(gateway_data["name"])

                db_gateway = DbGateway(
                    name=gateway_data["name"],
                    slug=slug_name,
                    url=gateway_data["url"],
                    description=gateway_data["description"],
                    tags=gateway_data.get("tags", []),
                    transport=gateway_data["transport"],
                    capabilities={},
                    auth_type="oauth",  # Mark as OAuth so it can be identified after page refresh
                    enabled=False,  # Disabled until OAuth is configured
                    created_via="catalog",
                    visibility=visibility,
                    created_by=created_by,
                    owner_email=owner_email,
                    team_id=resolved_team_id,
                    version=1,
                )

                db.add(db_gateway)
                db.commit()
                db.refresh(db_gateway)

                # First-Party
                from mcpgateway.schemas import GatewayRead  # pylint: disable=import-outside-toplevel

                # Build dict for GatewayRead validation with converted tags
                # This avoids mutating the database object
                # Handle both legacy List[str] and new List[Dict[str, str]] tag formats
                if db_gateway.tags:
                    if isinstance(db_gateway.tags[0], str):
                        # Legacy format: convert to dict format
                        tags_for_read = validate_tags_field(db_gateway.tags)
                    else:
                        # Already in dict format, pass through
                        tags_for_read = db_gateway.tags
                else:
                    tags_for_read = []

                gateway_dict = {
                    "id": db_gateway.id,
                    "name": db_gateway.name,
                    "slug": db_gateway.slug,
                    "url": db_gateway.url,
                    "description": db_gateway.description,
                    "tags": tags_for_read,
                    "transport": db_gateway.transport,
                    "capabilities": db_gateway.capabilities,
                    "created_at": db_gateway.created_at,
                    "updated_at": db_gateway.updated_at,
                    "enabled": db_gateway.enabled,
                    "reachable": db_gateway.reachable,
                    "last_seen": db_gateway.last_seen,
                    "auth_type": db_gateway.auth_type,
                    "visibility": db_gateway.visibility,
                    "version": db_gateway.version,
                    "team_id": db_gateway.team_id,
                    "owner_email": db_gateway.owner_email,
                }

                gateway_read = GatewayRead.model_validate(gateway_dict)

                # Invalidate catalog cache since registration status changed
                cache = self._get_registry_cache()
                if cache:
                    await cache.invalidate_catalog()

                return CatalogServerRegisterResponse(
                    success=True,
                    server_id=str(gateway_read.id),
                    message=f"Successfully registered {gateway_read.name} - OAuth configuration required before activation",
                    error=None,
                    oauth_required=True,
                )

            gateway_create = GatewayCreate(**gateway_data)

            # Use the proper gateway registration method which will discover tools
            gateway_read = await self._gateway_service.register_gateway(
                db=db,
                gateway=gateway_create,
                created_via="catalog",
                visibility=visibility,
                created_by=created_by,
                owner_email=owner_email,
                team_id=resolved_team_id,
                initialize_timeout=settings.httpx_admin_read_timeout,
            )

            logger.info("Registered catalog server: %s (%s)", gateway_read.name, catalog_id)

            # Query for tools discovered from this gateway
            # First-Party
            from mcpgateway.db import Tool as DbTool  # pylint: disable=import-outside-toplevel

            tool_count = 0
            if gateway_read.id:
                stmt = select(DbTool).where(DbTool.gateway_id == gateway_read.id)
                result = db.execute(stmt)
                tools = result.scalars().all()
                tool_count = len(tools)

            message = f"Successfully registered {gateway_read.name}"
            if tool_count > 0:
                message += f" with {tool_count} tools discovered"

            # Invalidate catalog cache since registration status changed
            cache = self._get_registry_cache()
            if cache:
                await cache.invalidate_catalog()

            return CatalogServerRegisterResponse(success=True, server_id=str(gateway_read.id), message=message, error=None)

        except CatalogRegistrationPermissionError:
            raise
        except Exception as e:
            logger.error("Failed to register catalog server %s: %s", catalog_id, e)

            # Map common exceptions to user-friendly messages
            error_str = str(e)
            user_message = "Registration failed"

            if "Connection refused" in error_str or "connect" in error_str.lower():
                user_message = "Server is offline or unreachable"
            elif "SSL" in error_str or "certificate" in error_str.lower():
                user_message = "SSL certificate verification failed - check server security settings"
            elif "timeout" in error_str.lower() or "timed out" in error_str.lower():
                user_message = "Server took too long to respond - it may be slow or unavailable"
            elif "401" in error_str or "Unauthorized" in error_str:
                user_message = "Authentication failed - check API key or OAuth credentials"
            elif "403" in error_str or "Forbidden" in error_str:
                user_message = "Access forbidden - check permissions and API key"
            elif "404" in error_str or "Not Found" in error_str:
                user_message = "Server endpoint not found - check URL is correct"
            elif "500" in error_str or "Internal Server Error" in error_str:
                user_message = "Remote server error - the MCP server is experiencing issues"
            elif "IPv6" in error_str:
                user_message = "IPv6 URLs are not supported - please use IPv4 or domain names"

            # Don't rollback here - let FastAPI handle it
            # db.rollback()
            return CatalogServerRegisterResponse(success=False, server_id="", message=user_message, error=error_str)

    async def check_server_availability(self, catalog_id: str) -> CatalogServerStatusResponse:
        """Check if a catalog server is available.

        Args:
            catalog_id: Catalog server ID

        Returns:
            Server status response
        """
        try:
            # Load catalog to find the server
            catalog_data = await self.load_catalog()
            servers = catalog_data.get("catalog_servers", [])

            # Find the server in catalog
            server_data = None
            for s in servers:
                if s.get("id") == catalog_id:
                    server_data = s
                    break

            if not server_data:
                return CatalogServerStatusResponse(server_id=catalog_id, is_available=False, is_registered=False, error="Server not found in catalog")

            # Check if registered (we'll need db passed in for this)
            is_registered = False

            # Perform health check
            start_time = time.time()
            is_available = False
            error = None

            try:
                # First-Party
                from mcpgateway.services.http_client_service import get_http_client  # pylint: disable=import-outside-toplevel

                client = await get_http_client()
                # Try a simple GET request with short timeout
                response = await client.get(server_data["url"], timeout=5.0, follow_redirects=False)
                is_available = response.status_code < 500
            except Exception as e:
                error = str(e)
                is_available = False

            response_time_ms = (time.time() - start_time) * 1000

            return CatalogServerStatusResponse(
                server_id=catalog_id, is_available=is_available, is_registered=is_registered, last_checked=datetime.now(timezone.utc), response_time_ms=response_time_ms, error=error
            )

        except Exception as e:
            logger.error("Failed to check server status for %s: %s", catalog_id, e)
            return CatalogServerStatusResponse(server_id=catalog_id, is_available=False, is_registered=False, error=str(e))

    async def bulk_register_servers(
        self,
        request: CatalogBulkRegisterRequest,
        db: Session,
        *,
        created_by: str,
        owner_email: str,
        token_teams: Optional[List[str]],
    ) -> CatalogBulkRegisterResponse:
        """Register multiple catalog servers.

        Args:
            request: Bulk registration request
            db: Database session
            created_by: Identity of the caller creating the gateways
            owner_email: Email of the gateway owner (derived from auth)
            token_teams: Token-scoped team list (None=admin bypass, []=public-only)

        Returns:
            Bulk registration response

        Raises:
            CatalogRegistrationPermissionError: If scope validation fails on the common scope.
        """
        # Validate scope once; pass the result to each per-server call to skip re-validation.
        scope_request = CatalogServerRegisterRequest(
            server_id="__bulk_validation__",
            visibility=request.visibility,
            team_id=request.team_id,
        )
        resolved_scope = self._resolve_registration_scope(db, scope_request, owner_email, token_teams)

        successful = []
        failed = []

        for server_id in request.server_ids:
            try:
                per_server_request = CatalogServerRegisterRequest(
                    server_id=server_id,
                    visibility=request.visibility,
                    team_id=request.team_id,
                )
                response = await self.register_catalog_server(
                    catalog_id=server_id,
                    request=per_server_request,
                    db=db,
                    created_by=created_by,
                    owner_email=owner_email,
                    token_teams=token_teams,
                    _resolved_scope=resolved_scope,
                )

                if response.success:
                    successful.append(server_id)
                else:
                    failed.append({"server_id": server_id, "error": response.error or "Registration failed"})

                    if not request.skip_errors:
                        break

            except Exception as e:
                failed.append({"server_id": server_id, "error": str(e)})

                if not request.skip_errors:
                    break

        return CatalogBulkRegisterResponse(successful=successful, failed=failed, total_attempted=len(request.server_ids), total_successful=len(successful))


# Global instance
catalog_service = CatalogService()
