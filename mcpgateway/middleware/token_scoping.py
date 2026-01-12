# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/middleware/token_scoping.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Token Scoping Middleware.
This middleware enforces token scoping restrictions at the API level,
including server_id restrictions, IP restrictions, permission checks,
and time-based restrictions.
"""

# Standard
from datetime import datetime, timezone
import ipaddress
import re
from typing import List, Optional, Pattern, Tuple

# Third-Party
from fastapi import HTTPException, Request, status
from fastapi.security import HTTPBearer

# First-Party
from mcpgateway.db import Permissions
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.utils.orjson_response import ORJSONResponse
from mcpgateway.utils.verify_credentials import verify_jwt_token_cached

# Security scheme
bearer_scheme = HTTPBearer(auto_error=False)

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

# ============================================================================
# Precompiled regex patterns (compiled once at module load for performance)
# ============================================================================

# Server path extraction patterns
_SERVER_PATH_PATTERNS: List[Pattern[str]] = [
    re.compile(r"^/servers/([^/]+)(?:$|/)"),
    re.compile(r"^/sse/([^/?]+)(?:$|\?)"),
    re.compile(r"^/ws/([^/?]+)(?:$|\?)"),
]

# Resource ID extraction patterns (IDs are UUID hex strings)
_RESOURCE_PATTERNS: List[Tuple[Pattern[str], str]] = [
    (re.compile(r"/servers/?([a-f0-9\-]+)"), "server"),
    (re.compile(r"/tools/?([a-f0-9\-]+)"), "tool"),
    (re.compile(r"/resources/?([a-f0-9\-]+)"), "resource"),
    (re.compile(r"/prompts/?([a-f0-9\-]+)"), "prompt"),
]

# Permission map with precompiled patterns
# Maps (HTTP method, path pattern) to required permission
_PERMISSION_PATTERNS: List[Tuple[str, Pattern[str], str]] = [
    # Tools permissions
    ("GET", re.compile(r"^/tools(?:$|/)"), Permissions.TOOLS_READ),
    ("POST", re.compile(r"^/tools(?:$|/)"), Permissions.TOOLS_CREATE),
    ("PUT", re.compile(r"^/tools/[^/]+(?:$|/)"), Permissions.TOOLS_UPDATE),
    ("DELETE", re.compile(r"^/tools/[^/]+(?:$|/)"), Permissions.TOOLS_DELETE),
    ("GET", re.compile(r"^/servers/[^/]+/tools(?:$|/)"), Permissions.TOOLS_READ),
    ("POST", re.compile(r"^/servers/[^/]+/tools/[^/]+/call(?:$|/)"), Permissions.TOOLS_EXECUTE),
    # Resources permissions
    ("GET", re.compile(r"^/resources(?:$|/)"), Permissions.RESOURCES_READ),
    ("POST", re.compile(r"^/resources(?:$|/)"), Permissions.RESOURCES_CREATE),
    ("PUT", re.compile(r"^/resources/[^/]+(?:$|/)"), Permissions.RESOURCES_UPDATE),
    ("DELETE", re.compile(r"^/resources/[^/]+(?:$|/)"), Permissions.RESOURCES_DELETE),
    ("GET", re.compile(r"^/servers/[^/]+/resources(?:$|/)"), Permissions.RESOURCES_READ),
    # Prompts permissions
    ("GET", re.compile(r"^/prompts(?:$|/)"), Permissions.PROMPTS_READ),
    ("POST", re.compile(r"^/prompts(?:$|/)"), Permissions.PROMPTS_CREATE),
    ("PUT", re.compile(r"^/prompts/[^/]+(?:$|/)"), Permissions.PROMPTS_UPDATE),
    ("DELETE", re.compile(r"^/prompts/[^/]+(?:$|/)"), Permissions.PROMPTS_DELETE),
    # Server management permissions
    ("GET", re.compile(r"^/servers(?:$|/)"), Permissions.SERVERS_READ),
    ("POST", re.compile(r"^/servers(?:$|/)"), Permissions.SERVERS_CREATE),
    ("PUT", re.compile(r"^/servers/[^/]+(?:$|/)"), Permissions.SERVERS_UPDATE),
    ("DELETE", re.compile(r"^/servers/[^/]+(?:$|/)"), Permissions.SERVERS_DELETE),
    # Admin permissions
    ("GET", re.compile(r"^/admin(?:$|/)"), Permissions.ADMIN_USER_MANAGEMENT),
    ("POST", re.compile(r"^/admin/[^/]+(?:$|/)"), Permissions.ADMIN_USER_MANAGEMENT),
    ("PUT", re.compile(r"^/admin/[^/]+(?:$|/)"), Permissions.ADMIN_USER_MANAGEMENT),
    ("DELETE", re.compile(r"^/admin/[^/]+(?:$|/)"), Permissions.ADMIN_USER_MANAGEMENT),
]


class TokenScopingMiddleware:
    """Middleware to enforce token scoping restrictions.

    Examples:
        >>> middleware = TokenScopingMiddleware()
        >>> isinstance(middleware, TokenScopingMiddleware)
        True
    """

    def __init__(self):
        """Initialize token scoping middleware.

        Examples:
            >>> middleware = TokenScopingMiddleware()
            >>> hasattr(middleware, '_extract_token_scopes')
            True
        """

    def _normalize_teams(self, teams) -> list:
        """Normalize teams from token payload to list of team IDs.

        Handles various team formats:
        - None -> []
        - List of strings -> as-is
        - List of dicts with 'id' key -> extract IDs

        Args:
            teams: Raw teams value from JWT payload

        Returns:
            List of team ID strings
        """
        if not teams:
            return []
        normalized = []
        for team in teams:
            if isinstance(team, dict):
                team_id = team.get("id")
                if team_id:
                    normalized.append(team_id)
            elif isinstance(team, str):
                normalized.append(team)
        return normalized

    async def _extract_token_scopes(self, request: Request) -> Optional[dict]:
        """Extract token scopes from JWT in request.

        Args:
            request: FastAPI request object

        Returns:
            Dict containing token scopes or None if no valid token
        """
        # Get authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return None

        token = auth_header.split(" ", 1)[1]

        try:
            # Use the centralized verify_jwt_token_cached function for consistent JWT validation
            payload = await verify_jwt_token_cached(token, request)
            return payload
        except HTTPException:
            # Token validation failed (expired, invalid, etc.)
            return None
        except Exception:
            # Any other error in token validation
            return None

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP address from request.

        Args:
            request: FastAPI request object

        Returns:
            str: Client IP address
        """
        # Check for X-Forwarded-For header (proxy/load balancer)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        # Check for X-Real-IP header
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip

        # Fall back to direct client IP
        return request.client.host if request.client else "unknown"

    def _check_ip_restrictions(self, client_ip: str, ip_restrictions: list) -> bool:
        """Check if client IP is allowed by restrictions.

        Args:
            client_ip: Client's IP address
            ip_restrictions: List of allowed IP addresses/CIDR ranges

        Returns:
            bool: True if IP is allowed, False otherwise

        Examples:
            Allow specific IP:
            >>> m = TokenScopingMiddleware()
            >>> m._check_ip_restrictions('192.168.1.10', ['192.168.1.10'])
            True

            Allow CIDR range:
            >>> m._check_ip_restrictions('10.0.0.5', ['10.0.0.0/24'])
            True

            Deny when not in list:
            >>> m._check_ip_restrictions('10.0.1.5', ['10.0.0.0/24'])
            False

            Empty restrictions allow all:
            >>> m._check_ip_restrictions('203.0.113.1', [])
            True
        """
        if not ip_restrictions:
            return True  # No restrictions

        try:
            client_ip_obj = ipaddress.ip_address(client_ip)

            for restriction in ip_restrictions:
                try:
                    # Check if it's a CIDR range
                    if "/" in restriction:
                        network = ipaddress.ip_network(restriction, strict=False)
                        if client_ip_obj in network:
                            return True
                    else:
                        # Single IP address
                        if client_ip_obj == ipaddress.ip_address(restriction):
                            return True
                except (ValueError, ipaddress.AddressValueError):
                    continue

        except (ValueError, ipaddress.AddressValueError):
            return False

        return False

    def _check_time_restrictions(self, time_restrictions: dict) -> bool:
        """Check if current time is allowed by restrictions.

        Args:
            time_restrictions: Dict containing time-based restrictions

        Returns:
            bool: True if current time is allowed, False otherwise

        Examples:
            No restrictions allow access:
            >>> m = TokenScopingMiddleware()
            >>> m._check_time_restrictions({})
            True

            Weekdays only: result depends on current weekday (always bool):
            >>> isinstance(m._check_time_restrictions({'weekdays_only': True}), bool)
            True

            Business hours only: result depends on current hour (always bool):
            >>> isinstance(m._check_time_restrictions({'business_hours_only': True}), bool)
            True
        """
        if not time_restrictions:
            return True  # No restrictions

        now = datetime.now(tz=timezone.utc)

        # Check business hours restriction
        if time_restrictions.get("business_hours_only"):
            # Assume business hours are 9 AM to 5 PM UTC
            # This could be made configurable
            if not 9 <= now.hour < 17:
                return False

        # Check day of week restrictions
        weekdays_only = time_restrictions.get("weekdays_only")
        if weekdays_only and now.weekday() >= 5:  # Saturday=5, Sunday=6
            return False

        return True

    def _check_server_restriction(self, request_path: str, server_id: Optional[str]) -> bool:
        """Check if request path matches server restriction.

        Args:
            request_path: The request path/URL
            server_id: Required server ID (None means no restriction)

        Returns:
            bool: True if request is allowed, False otherwise

        Examples:
            Match server paths:
            >>> m = TokenScopingMiddleware()
            >>> m._check_server_restriction('/servers/abc/tools', 'abc')
            True
            >>> m._check_server_restriction('/sse/xyz', 'xyz')
            True
            >>> m._check_server_restriction('/ws/xyz?x=1', 'xyz')
            True

            Mismatch denies:
            >>> m._check_server_restriction('/servers/def', 'abc')
            False

            General endpoints allowed:
            >>> m._check_server_restriction('/health', 'abc')
            True
            >>> m._check_server_restriction('/', 'abc')
            True
        """
        if not server_id:
            return True  # No server restriction

        # Extract server ID from path patterns (uses precompiled regex)
        # /servers/{server_id}/...
        # /sse/{server_id}
        # /ws/{server_id}
        for pattern in _SERVER_PATH_PATTERNS:
            match = pattern.search(request_path)
            if match:
                path_server_id = match.group(1)
                return path_server_id == server_id

        # If no server ID found in path, allow general endpoints
        general_endpoints = ["/health", "/metrics", "/openapi.json", "/docs", "/redoc"]

        # Check exact root path separately
        if request_path == "/":
            return True

        for endpoint in general_endpoints:
            if request_path.startswith(endpoint):
                return True

        # Default deny for unmatched paths with server restrictions
        return False

    def _check_permission_restrictions(self, request_path: str, request_method: str, permissions: list) -> bool:
        """Check if request is allowed by permission restrictions.

        Args:
            request_path: The request path/URL
            request_method: HTTP method (GET, POST, etc.)
            permissions: List of allowed permissions

        Returns:
            bool: True if request is allowed, False otherwise

        Examples:
            Wildcard allows all:
            >>> m = TokenScopingMiddleware()
            >>> m._check_permission_restrictions('/tools', 'GET', ['*'])
            True

            Requires specific permission:
            >>> m._check_permission_restrictions('/tools', 'POST', ['tools.create'])
            True
            >>> m._check_permission_restrictions('/tools/xyz', 'PUT', ['tools.update'])
            True
            >>> m._check_permission_restrictions('/resources', 'GET', ['resources.read'])
            True
            >>> m._check_permission_restrictions('/servers/s1/tools/abc/call', 'POST', ['tools.execute'])
            True

            Missing permission denies:
            >>> m._check_permission_restrictions('/tools', 'POST', ['tools.read'])
            False
        """
        if not permissions or "*" in permissions:
            return True  # No restrictions or full access

        # Check each permission mapping (uses precompiled regex patterns)
        for method, path_pattern, required_permission in _PERMISSION_PATTERNS:
            if request_method == method and path_pattern.match(request_path):
                return required_permission in permissions

        # Default allow for unmatched paths
        return True

    def _check_team_membership(self, payload: dict, db=None) -> bool:
        """
        Check if user still belongs to teams in the token.

        For public-only tokens (no teams), always returns True.
        For team-scoped tokens, validates membership with caching.

        Uses in-memory cache (per gateway instance, 60s TTL) to avoid repeated
        email_team_members queries for the same user+teams combination.
        Note: Sync path uses in-memory only for performance; Redis is not
        consulted to avoid async overhead in the hot path.

        Args:
            payload: Decoded JWT payload containing teams
            db: Optional database session. If provided, caller manages lifecycle.
                If None, creates and manages its own session.

        Returns:
            bool: True if team membership is valid, False otherwise
        """
        teams = payload.get("teams", [])
        user_email = payload.get("sub")

        # PUBLIC-ONLY TOKEN: No team validation needed
        if not teams or len(teams) == 0:
            logger.debug(f"Public-only token for user {user_email} - no team validation required")
            return True

        # TEAM-SCOPED TOKEN: Validate membership
        if not user_email:
            logger.warning("Token missing user email")
            return False

        # Extract team IDs from token (handles both dict and string formats)
        team_ids = [team["id"] if isinstance(team, dict) else team for team in teams]

        # First-Party
        from mcpgateway.cache.auth_cache import get_auth_cache  # pylint: disable=import-outside-toplevel

        # Check cache first (synchronous in-memory lookup)
        auth_cache = get_auth_cache()
        cached_result = auth_cache.get_team_membership_valid_sync(user_email, team_ids)
        if cached_result is not None:
            if not cached_result:
                logger.warning(f"Token invalid (cached): User {user_email} no longer member of teams")
            return cached_result

        # Cache miss - query database
        # Third-Party
        from sqlalchemy import select  # pylint: disable=import-outside-toplevel

        # First-Party
        from mcpgateway.db import EmailTeamMember, get_db  # pylint: disable=import-outside-toplevel

        # Track if we own the session (and thus must clean it up)
        owns_session = db is None
        if owns_session:
            db = next(get_db())

        try:
            # Single query for all teams (fixes N+1 pattern)
            memberships = (
                db.execute(
                    select(EmailTeamMember.team_id).where(
                        EmailTeamMember.team_id.in_(team_ids),
                        EmailTeamMember.user_email == user_email,
                        EmailTeamMember.is_active.is_(True),
                    )
                )
                .scalars()
                .all()
            )

            # Check if user is member of ALL teams in token
            valid_team_ids = set(memberships)
            missing_teams = set(team_ids) - valid_team_ids

            if missing_teams:
                logger.warning(f"Token invalid: User {user_email} no longer member of teams: {missing_teams}")
                # Cache negative result
                auth_cache.set_team_membership_valid_sync(user_email, team_ids, False)
                return False

            # Cache positive result
            auth_cache.set_team_membership_valid_sync(user_email, team_ids, True)
            return True
        finally:
            # Only commit/close if we created the session
            if owns_session:
                try:
                    db.commit()  # Commit read-only transaction to avoid implicit rollback
                finally:
                    db.close()

    def _check_resource_team_ownership(self, request_path: str, token_teams: list, db=None, _user_email: str = None) -> bool:  # pylint: disable=too-many-return-statements
        """
        Check if the requested resource is accessible by the token.

        Implements Three-Tier Resource Visibility (Public/Team/Private):
        - PUBLIC: Accessible by all tokens (public-only and team-scoped)
        - TEAM: Accessible only by tokens scoped to that specific team
        - PRIVATE: Accessible only by tokens scoped to that specific team

        Token Access Rules:
        - Public-only tokens (empty token_teams): Can access public resources + their own resources
        - Team-scoped tokens: Can access their team's resources + public resources

        Handles URLs like:
        - /servers/{id}/mcp
        - /servers/{id}/sse
        - /servers/{id}
        - /tools/{id}/execute
        - /tools/{id}
        - /resources/{id}
        - /prompts/{id}

        Args:
            request_path: The request path/URL
            token_teams: List of team IDs from the token (empty list = public-only token)
            db: Optional database session. If provided, caller manages lifecycle.
                If None, creates and manages its own session.

        Returns:
            bool: True if resource access is allowed, False otherwise
        """
        # Normalize token_teams: extract team IDs from dict objects (backward compatibility)
        token_team_ids = []
        for team in token_teams:
            if isinstance(team, dict):
                token_team_ids.append(team["id"])
            else:
                token_team_ids.append(team)

        # Determine token type
        is_public_token = not token_team_ids or len(token_team_ids) == 0

        if is_public_token:
            logger.debug("Processing request with PUBLIC-ONLY token")
        else:
            logger.debug(f"Processing request with TEAM-SCOPED token (teams: {token_teams})")

        # Extract resource type and ID from path (uses precompiled regex patterns)
        # IDs are UUID hex strings (32 chars) or UUID with dashes (36 chars)
        resource_id = None
        resource_type = None

        for pattern, rtype in _RESOURCE_PATTERNS:
            match = pattern.search(request_path)
            if match:
                resource_id = match.group(1)
                resource_type = rtype
                logger.debug(f"Extracted {rtype} ID: {resource_id} from path: {request_path}")
                break

        # If no resource ID in path, allow (general endpoints like /health, /tokens, /metrics)
        if not resource_id or not resource_type:
            logger.debug(f"No resource ID found in path {request_path}, allowing access")
            return True

        # Import database models
        # Third-Party
        from sqlalchemy import select  # pylint: disable=import-outside-toplevel

        # First-Party
        from mcpgateway.db import get_db, Prompt, Resource, Server, Tool  # pylint: disable=import-outside-toplevel

        # Track if we own the session (and thus must clean it up)
        owns_session = db is None
        if owns_session:
            db = next(get_db())

        try:
            # Check Virtual Servers
            if resource_type == "server":
                server = db.execute(select(Server).where(Server.id == resource_id)).scalar_one_or_none()

                if not server:
                    logger.warning(f"Server {resource_id} not found in database")
                    return True

                # Get server visibility (default to 'team' if field doesn't exist)
                server_visibility = getattr(server, "visibility", "team")

                # PUBLIC SERVERS: Accessible by everyone (including public-only tokens)
                if server_visibility == "public":
                    logger.debug(f"Access granted: Server {resource_id} is PUBLIC")
                    return True

                # PUBLIC-ONLY TOKEN: Can ONLY access public servers (strict public-only policy)
                # No owner access - if user needs own resources, use a personal team-scoped token
                if is_public_token:
                    logger.warning(f"Access denied: Public-only token cannot access {server_visibility} server {resource_id}")
                    return False

                # TEAM-SCOPED SERVERS: Check if server belongs to token's teams
                if server_visibility == "team":
                    if server.team_id in token_team_ids:
                        logger.debug(f"Access granted: Team server {resource_id} belongs to token's team {server.team_id}")
                        return True

                    logger.warning(f"Access denied: Server {resource_id} is team-scoped to '{server.team_id}', token is scoped to teams {token_team_ids}")
                    return False

                # PRIVATE SERVERS: Check if server belongs to token's teams
                if server_visibility == "private":
                    if server.team_id in token_team_ids:
                        logger.debug(f"Access granted: Private server {resource_id} in token's team {server.team_id}")
                        return True

                    logger.warning(f"Access denied: Server {resource_id} is private to team '{server.team_id}'")
                    return False

                # Unknown visibility - deny by default
                logger.warning(f"Access denied: Server {resource_id} has unknown visibility: {server_visibility}")
                return False

            # CHECK TOOLS
            if resource_type == "tool":
                tool = db.execute(select(Tool).where(Tool.id == resource_id)).scalar_one_or_none()

                if not tool:
                    logger.warning(f"Tool {resource_id} not found in database")
                    return True

                # Get tool visibility (default to 'team' if field doesn't exist)
                tool_visibility = getattr(tool, "visibility", "team")

                # PUBLIC TOOLS: Accessible by everyone (including public-only tokens)
                if tool_visibility == "public":
                    logger.debug(f"Access granted: Tool {resource_id} is PUBLIC")
                    return True

                # PUBLIC-ONLY TOKEN: Can ONLY access public tools (strict public-only policy)
                # No owner access - if user needs own resources, use a personal team-scoped token
                if is_public_token:
                    logger.warning(f"Access denied: Public-only token cannot access {tool_visibility} tool {resource_id}")
                    return False

                # TEAM TOOLS: Check if tool's team matches token's teams
                if tool_visibility == "team":
                    tool_team_id = getattr(tool, "team_id", None)
                    if tool_team_id and tool_team_id in token_team_ids:
                        logger.debug(f"Access granted: Team tool {resource_id} belongs to token's team {tool_team_id}")
                        return True

                    logger.warning(f"Access denied: Tool {resource_id} is team-scoped to '{tool_team_id}', token is scoped to teams {token_team_ids}")
                    return False

                # PRIVATE TOOLS: Check if tool is in token's team context
                if tool_visibility in ["private", "user"]:
                    tool_team_id = getattr(tool, "team_id", None)
                    if tool_team_id and tool_team_id in token_team_ids:
                        logger.debug(f"Access granted: Private tool {resource_id} in token's team {tool_team_id}")
                        return True

                    logger.warning(f"Access denied: Tool {resource_id} is {tool_visibility} and not in token's teams")
                    return False

                # Unknown visibility - deny by default
                logger.warning(f"Access denied: Tool {resource_id} has unknown visibility: {tool_visibility}")
                return False

            # CHECK RESOURCES
            if resource_type == "resource":
                resource = db.execute(select(Resource).where(Resource.id == resource_id)).scalar_one_or_none()

                if not resource:
                    logger.warning(f"Resource {resource_id} not found in database")
                    return True

                # Get resource visibility (default to 'team' if field doesn't exist)
                resource_visibility = getattr(resource, "visibility", "team")

                # PUBLIC RESOURCES: Accessible by everyone (including public-only tokens)
                if resource_visibility == "public":
                    logger.debug(f"Access granted: Resource {resource_id} is PUBLIC")
                    return True

                # PUBLIC-ONLY TOKEN: Can ONLY access public resources (strict public-only policy)
                # No owner access - if user needs own resources, use a personal team-scoped token
                if is_public_token:
                    logger.warning(f"Access denied: Public-only token cannot access {resource_visibility} resource {resource_id}")
                    return False

                # TEAM RESOURCES: Check if resource's team matches token's teams
                if resource_visibility == "team":
                    resource_team_id = getattr(resource, "team_id", None)
                    if resource_team_id and resource_team_id in token_team_ids:
                        logger.debug(f"Access granted: Team resource {resource_id} belongs to token's team {resource_team_id}")
                        return True

                    logger.warning(f"Access denied: Resource {resource_id} is team-scoped to '{resource_team_id}', token is scoped to teams {token_team_ids}")
                    return False

                # PRIVATE RESOURCES: Check if resource is in token's team context
                if resource_visibility in ["private", "user"]:
                    resource_team_id = getattr(resource, "team_id", None)
                    if resource_team_id and resource_team_id in token_team_ids:
                        logger.debug(f"Access granted: Private resource {resource_id} in token's team {resource_team_id}")
                        return True

                    logger.warning(f"Access denied: Resource {resource_id} is {resource_visibility} and not in token's teams")
                    return False

                # Unknown visibility - deny by default
                logger.warning(f"Access denied: Resource {resource_id} has unknown visibility: {resource_visibility}")
                return False

            # CHECK PROMPTS
            if resource_type == "prompt":
                prompt = db.execute(select(Prompt).where(Prompt.id == resource_id)).scalar_one_or_none()

                if not prompt:
                    logger.warning(f"Prompt {resource_id} not found in database")
                    return True

                # Get prompt visibility (default to 'team' if field doesn't exist)
                prompt_visibility = getattr(prompt, "visibility", "team")

                # PUBLIC PROMPTS: Accessible by everyone (including public-only tokens)
                if prompt_visibility == "public":
                    logger.debug(f"Access granted: Prompt {resource_id} is PUBLIC")
                    return True

                # PUBLIC-ONLY TOKEN: Can ONLY access public prompts (strict public-only policy)
                # No owner access - if user needs own resources, use a personal team-scoped token
                if is_public_token:
                    logger.warning(f"Access denied: Public-only token cannot access {prompt_visibility} prompt {resource_id}")
                    return False

                # TEAM PROMPTS: Check if prompt's team matches token's teams
                if prompt_visibility == "team":
                    prompt_team_id = getattr(prompt, "team_id", None)
                    if prompt_team_id and prompt_team_id in token_team_ids:
                        logger.debug(f"Access granted: Team prompt {resource_id} belongs to token's team {prompt_team_id}")
                        return True

                    logger.warning(f"Access denied: Prompt {resource_id} is team-scoped to '{prompt_team_id}', token is scoped to teams {token_team_ids}")
                    return False

                # PRIVATE PROMPTS: Check if prompt is in token's team context
                if prompt_visibility in ["private", "user"]:
                    prompt_team_id = getattr(prompt, "team_id", None)
                    if prompt_team_id and prompt_team_id in token_team_ids:
                        logger.debug(f"Access granted: Private prompt {resource_id} in token's team {prompt_team_id}")
                        return True

                    logger.warning(f"Access denied: Prompt {resource_id} is {prompt_visibility} and not in token's teams")
                    return False

                # Unknown visibility - deny by default
                logger.warning(f"Access denied: Prompt {resource_id} has unknown visibility: {prompt_visibility}")
                return False

            # UNKNOWN RESOURCE TYPE
            logger.warning(f"Unknown resource type '{resource_type}' for path: {request_path}")
            return False

        except Exception as e:
            logger.error(f"Error checking resource team ownership for {request_path}: {e}", exc_info=True)
            # Fail securely - deny access on error
            return False
        finally:
            # Only commit/close if we created the session
            if owns_session:
                try:
                    db.commit()  # Commit read-only transaction to avoid implicit rollback
                finally:
                    db.close()

    async def __call__(self, request: Request, call_next):
        """Middleware function to check token scoping including team-level validation.

        Args:
            request: FastAPI request object
            call_next: Next middleware/handler in chain

        Returns:
            Response from next handler or HTTPException

        Raises:
            HTTPException: If token scoping restrictions are violated
        """
        try:
            # Skip if already scoped (prevents double-scoping for /mcp requests)
            # MCPPathRewriteMiddleware runs scoping via dispatch, then routes through
            # middleware stack which hits BaseHTTPMiddleware's scoping again.
            # Use request.state flag which persists across middleware invocations.
            if getattr(request.state, "_token_scoping_done", False):
                return await call_next(request)

            # Mark as scoped before doing any work
            request.state._token_scoping_done = True

            # Skip scoping for certain paths (truly public endpoints only)
            skip_paths = [
                "/health",
                "/metrics",
                "/openapi.json",
                "/docs",
                "/redoc",
                "/auth/email/login",
                "/auth/email/register",
                "/.well-known/",
            ]

            # Check exact root path separately
            if request.url.path == "/":
                return await call_next(request)

            if any(request.url.path.startswith(path) for path in skip_paths):
                return await call_next(request)

            # Skip server-specific well-known endpoints (RFC 9728)
            if re.match(r"^/servers/[^/]+/\.well-known/", request.url.path):
                return await call_next(request)

            # Extract full token payload (not just scopes)
            payload = await self._extract_token_scopes(request)

            # If no payload, continue (regular auth will handle this)
            if not payload:
                return await call_next(request)

            # TEAM VALIDATION: Use single DB session for both team checks
            # This reduces connection pool overhead from 2 sessions to 1 for resource endpoints
            user_email = payload.get("sub") or payload.get("email")  # Extract user email for ownership check
            is_admin = payload.get("is_admin", False) or payload.get("user", {}).get("is_admin", False)

            # Determine token_teams based on whether "teams" key exists and is not None
            # - Key absent OR null + admin = None (unrestricted bypass)
            # - Key absent OR null + non-admin = [] (public-only, secure default)
            # - Key present with non-None value = normalize the value
            teams_value = payload.get("teams") if "teams" in payload else None
            if teams_value is not None:
                token_teams = self._normalize_teams(teams_value)
            elif is_admin:
                # Admin without teams key (or teams: null) = unrestricted (skip team checks)
                token_teams = None
            else:
                # Non-admin without teams key (or teams: null) = public-only (secure default)
                token_teams = []

            # Admin with no team restrictions bypasses team validation entirely
            if is_admin and token_teams is None:
                logger.debug(f"Admin bypass: skipping team validation for {user_email}")
                # Skip to other checks (server_id, IP, etc.)
            elif token_teams:
                # First-Party
                from mcpgateway.db import get_db  # pylint: disable=import-outside-toplevel

                db = next(get_db())
                try:
                    # Check team membership with shared session
                    if not self._check_team_membership(payload, db=db):
                        logger.warning("Token rejected: User no longer member of associated team(s)")
                        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Token is invalid: User is no longer a member of the associated team")

                    # Check resource team ownership with shared session
                    if not self._check_resource_team_ownership(request.url.path, token_teams, db=db, _user_email=user_email):
                        logger.warning(f"Access denied: Resource does not belong to token's teams {token_teams}")
                        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied: You do not have permission to access this resource using the current token")
                finally:
                    # Ensure session cleanup even if checks raise exceptions
                    try:
                        db.commit()
                    finally:
                        db.close()
            else:
                # Public-only token: no team membership check needed, but still check resource ownership
                if not self._check_team_membership(payload):
                    logger.warning("Token rejected: User no longer member of associated team(s)")
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Token is invalid: User is no longer a member of the associated team")

                if not self._check_resource_team_ownership(request.url.path, token_teams, _user_email=user_email):
                    logger.warning(f"Access denied: Resource does not belong to token's teams {token_teams}")
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied: You do not have permission to access this resource using the current token")

            # Extract scopes from payload
            scopes = payload.get("scopes", {})

            # Check server ID restriction
            server_id = scopes.get("server_id")
            if not self._check_server_restriction(request.url.path, server_id):
                logger.warning(f"Token not authorized for this server. Required: {server_id}")
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Token not authorized for this server. Required: {server_id}")

            # Check IP restrictions
            ip_restrictions = scopes.get("ip_restrictions", [])
            if ip_restrictions:
                client_ip = self._get_client_ip(request)
                if not self._check_ip_restrictions(client_ip, ip_restrictions):
                    logger.warning(f"Request from IP {client_ip} not allowed by token restrictions")
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Request from IP {client_ip} not allowed by token restrictions")

            # Check time restrictions
            time_restrictions = scopes.get("time_restrictions", {})
            if not self._check_time_restrictions(time_restrictions):
                logger.warning("Request not allowed at this time by token restrictions")
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Request not allowed at this time by token restrictions")

            # Check permission restrictions
            permissions = scopes.get("permissions", [])
            if not self._check_permission_restrictions(request.url.path, request.method, permissions):
                logger.warning("Insufficient permissions for this operation")
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions for this operation")

            # All scoping checks passed, continue
            return await call_next(request)

        except HTTPException as exc:
            # Return clean JSON response instead of traceback
            return ORJSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
            )


# Create middleware instance
token_scoping_middleware = TokenScopingMiddleware()
