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
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import ipaddress
import re
from typing import List, Optional, Pattern, Tuple

# Third-Party
from fastapi import HTTPException, Request, status
from fastapi.security import HTTPBearer
from sqlalchemy import and_, func, select

# First-Party
from mcpgateway.auth import normalize_token_teams
from mcpgateway.config import settings
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
    (re.compile(r"/gateways/?([a-f0-9\-]+)"), "gateway"),
]
_AUTH_COOKIE_NAMES = ("jwt_token", "access_token")

# Permission map with precompiled patterns
# Maps (HTTP method, path pattern) to required permission
_PERMISSION_PATTERNS: List[Tuple[str, Pattern[str], str]] = [
    # Tools permissions
    ("GET", re.compile(r"^/tools(?:$|/)"), Permissions.TOOLS_READ),
    ("POST", re.compile(r"^/tools/?$"), Permissions.TOOLS_CREATE),  # Only exact /tools or /tools/
    ("POST", re.compile(r"^/tools/[^/]+/"), Permissions.TOOLS_UPDATE),  # POST to sub-resources (state, toggle)
    ("PUT", re.compile(r"^/tools/[^/]+(?:$|/)"), Permissions.TOOLS_UPDATE),
    ("DELETE", re.compile(r"^/tools/[^/]+(?:$|/)"), Permissions.TOOLS_DELETE),
    ("GET", re.compile(r"^/servers/[^/]+/tools(?:$|/)"), Permissions.TOOLS_READ),
    ("POST", re.compile(r"^/servers/[^/]+/tools/[^/]+/call(?:$|/)"), Permissions.TOOLS_EXECUTE),
    # Resources permissions
    ("GET", re.compile(r"^/resources(?:$|/)"), Permissions.RESOURCES_READ),
    ("POST", re.compile(r"^/resources/?$"), Permissions.RESOURCES_CREATE),  # Only exact /resources or /resources/
    ("POST", re.compile(r"^/resources/subscribe(?:$|/)"), Permissions.RESOURCES_READ),  # SSE subscription
    ("POST", re.compile(r"^/resources/[^/]+/"), Permissions.RESOURCES_UPDATE),  # POST to sub-resources (state, toggle)
    ("PUT", re.compile(r"^/resources/[^/]+(?:$|/)"), Permissions.RESOURCES_UPDATE),
    ("DELETE", re.compile(r"^/resources/[^/]+(?:$|/)"), Permissions.RESOURCES_DELETE),
    ("GET", re.compile(r"^/servers/[^/]+/resources(?:$|/)"), Permissions.RESOURCES_READ),
    # Prompts permissions
    ("GET", re.compile(r"^/prompts(?:$|/)"), Permissions.PROMPTS_READ),
    ("POST", re.compile(r"^/prompts/?$"), Permissions.PROMPTS_CREATE),  # Only exact /prompts or /prompts/
    ("POST", re.compile(r"^/prompts/[^/]+/"), Permissions.PROMPTS_UPDATE),  # POST to sub-resources (state, toggle)
    ("POST", re.compile(r"^/prompts/[^/]+$"), Permissions.PROMPTS_READ),  # MCP spec prompt retrieval (POST /prompts/{id})
    ("PUT", re.compile(r"^/prompts/[^/]+(?:$|/)"), Permissions.PROMPTS_UPDATE),
    ("DELETE", re.compile(r"^/prompts/[^/]+(?:$|/)"), Permissions.PROMPTS_DELETE),
    # Server management permissions
    ("GET", re.compile(r"^/servers/[^/]+/sse(?:$|/)"), Permissions.SERVERS_USE),  # Server SSE access endpoint
    ("GET", re.compile(r"^/servers(?:$|/)"), Permissions.SERVERS_READ),
    ("POST", re.compile(r"^/servers/?$"), Permissions.SERVERS_CREATE),  # Only exact /servers or /servers/
    ("POST", re.compile(r"^/servers/[^/]+/(?:state|toggle)(?:$|/)"), Permissions.SERVERS_UPDATE),  # Server management sub-resources
    ("POST", re.compile(r"^/servers/[^/]+/message(?:$|/)"), Permissions.SERVERS_USE),  # Server message access endpoint
    ("POST", re.compile(r"^/servers/[^/]+/mcp(?:$|/)"), Permissions.SERVERS_USE),  # Server MCP access endpoint
    ("PUT", re.compile(r"^/servers/[^/]+(?:$|/)"), Permissions.SERVERS_UPDATE),
    ("DELETE", re.compile(r"^/servers/[^/]+(?:$|/)"), Permissions.SERVERS_DELETE),
    # Gateway permissions
    ("GET", re.compile(r"^/gateways(?:$|/)"), Permissions.GATEWAYS_READ),
    ("POST", re.compile(r"^/gateways/?$"), Permissions.GATEWAYS_CREATE),  # Only exact /gateways or /gateways/
    ("POST", re.compile(r"^/gateways/[^/]+/"), Permissions.GATEWAYS_UPDATE),  # POST to sub-resources (state, toggle, refresh)
    ("PUT", re.compile(r"^/gateways/[^/]+(?:$|/)"), Permissions.GATEWAYS_UPDATE),
    ("DELETE", re.compile(r"^/gateways/[^/]+(?:$|/)"), Permissions.GATEWAYS_DELETE),
    # Token permissions
    ("GET", re.compile(r"^/tokens(?:$|/)"), Permissions.TOKENS_READ),
    ("POST", re.compile(r"^/tokens/?$"), Permissions.TOKENS_CREATE),  # Only exact /tokens or /tokens/
    ("POST", re.compile(r"^/tokens/teams/[^/]+(?:$|/)"), Permissions.TOKENS_CREATE),
    ("PUT", re.compile(r"^/tokens/[^/]+(?:$|/)"), Permissions.TOKENS_UPDATE),
    ("DELETE", re.compile(r"^/tokens/[^/]+(?:$|/)"), Permissions.TOKENS_REVOKE),
]

# Admin route permission map (granular by route group).
# IMPORTANT: Unmatched /admin/* paths are denied by default (fail-secure).
_ADMIN_PERMISSION_PATTERNS: List[Tuple[str, Pattern[str], str]] = [
    # Dashboard/overview surfaces
    ("GET", re.compile(r"^/admin/?$"), Permissions.ADMIN_DASHBOARD),
    ("GET", re.compile(r"^/admin/search(?:$|/)"), Permissions.ADMIN_DASHBOARD),
    ("GET", re.compile(r"^/admin/overview(?:$|/)"), Permissions.ADMIN_OVERVIEW),
    # User management
    ("GET", re.compile(r"^/admin/users(?:$|/)"), Permissions.ADMIN_USER_MANAGEMENT),
    ("POST", re.compile(r"^/admin/users(?:$|/)"), Permissions.ADMIN_USER_MANAGEMENT),
    ("DELETE", re.compile(r"^/admin/users(?:$|/)"), Permissions.ADMIN_USER_MANAGEMENT),
    # Team management
    ("POST", re.compile(r"^/admin/teams/?$"), Permissions.TEAMS_CREATE),
    ("DELETE", re.compile(r"^/admin/teams/[^/]+/join-request/[^/]+(?:$|/)"), Permissions.TEAMS_JOIN),
    ("DELETE", re.compile(r"^/admin/teams/[^/]+(?:$|/)"), Permissions.TEAMS_DELETE),
    ("GET", re.compile(r"^/admin/teams/[^/]+/edit(?:$|/)"), Permissions.TEAMS_UPDATE),
    ("POST", re.compile(r"^/admin/teams/[^/]+/update(?:$|/)"), Permissions.TEAMS_UPDATE),
    ("GET", re.compile(r"^/admin/teams/[^/]+/(?:members/add|members/partial|non-members/partial|join-requests)(?:$|/)"), Permissions.TEAMS_MANAGE_MEMBERS),
    ("POST", re.compile(r"^/admin/teams/[^/]+/(?:add-member|update-member-role|remove-member|join-requests/[^/]+/(?:approve|reject))(?:$|/)"), Permissions.TEAMS_MANAGE_MEMBERS),
    ("POST", re.compile(r"^/admin/teams/[^/]+/(?:leave|join-request(?:/[^/]+)?)(?:$|/)"), Permissions.TEAMS_JOIN),
    ("GET", re.compile(r"^/admin/teams(?:$|/)"), Permissions.TEAMS_READ),
    # Tool management
    ("POST", re.compile(r"^/admin/tools/?$"), Permissions.TOOLS_CREATE),
    ("POST", re.compile(r"^/admin/tools/import(?:$|/)"), Permissions.TOOLS_CREATE),
    ("POST", re.compile(r"^/admin/tools/[^/]+/delete(?:$|/)"), Permissions.TOOLS_DELETE),
    ("POST", re.compile(r"^/admin/tools/[^/]+/(?:edit|state)(?:$|/)"), Permissions.TOOLS_UPDATE),
    ("GET", re.compile(r"^/admin/tools(?:$|/)"), Permissions.TOOLS_READ),
    # Resource management
    ("POST", re.compile(r"^/admin/resources/?$"), Permissions.RESOURCES_CREATE),
    ("POST", re.compile(r"^/admin/resources/[^/]+/delete(?:$|/)"), Permissions.RESOURCES_DELETE),
    ("POST", re.compile(r"^/admin/resources/[^/]+/(?:edit|state)(?:$|/)"), Permissions.RESOURCES_UPDATE),
    ("GET", re.compile(r"^/admin/resources(?:$|/)"), Permissions.RESOURCES_READ),
    # Prompt management
    ("POST", re.compile(r"^/admin/prompts/?$"), Permissions.PROMPTS_CREATE),
    ("POST", re.compile(r"^/admin/prompts/[^/]+/delete(?:$|/)"), Permissions.PROMPTS_DELETE),
    ("POST", re.compile(r"^/admin/prompts/[^/]+/(?:edit|state)(?:$|/)"), Permissions.PROMPTS_UPDATE),
    ("GET", re.compile(r"^/admin/prompts(?:$|/)"), Permissions.PROMPTS_READ),
    # Gateway management
    ("POST", re.compile(r"^/admin/gateways/test(?:$|/)"), Permissions.GATEWAYS_READ),
    ("POST", re.compile(r"^/admin/gateways/?$"), Permissions.GATEWAYS_CREATE),
    ("POST", re.compile(r"^/admin/gateways/[^/]+/delete(?:$|/)"), Permissions.GATEWAYS_DELETE),
    ("POST", re.compile(r"^/admin/gateways/[^/]+/(?:edit|state)(?:$|/)"), Permissions.GATEWAYS_UPDATE),
    ("GET", re.compile(r"^/admin/gateways(?:$|/)"), Permissions.GATEWAYS_READ),
    # Server management
    ("POST", re.compile(r"^/admin/servers/?$"), Permissions.SERVERS_CREATE),
    ("POST", re.compile(r"^/admin/servers/[^/]+/delete(?:$|/)"), Permissions.SERVERS_DELETE),
    ("POST", re.compile(r"^/admin/servers/[^/]+/(?:edit|state)(?:$|/)"), Permissions.SERVERS_UPDATE),
    ("GET", re.compile(r"^/admin/servers(?:$|/)"), Permissions.SERVERS_READ),
    # Token/tag read surfaces
    ("GET", re.compile(r"^/admin/tokens(?:$|/)"), Permissions.TOKENS_READ),
    ("GET", re.compile(r"^/admin/tags(?:$|/)"), Permissions.TAGS_READ),
    # A2A management
    ("POST", re.compile(r"^/admin/a2a/?$"), Permissions.A2A_CREATE),
    ("POST", re.compile(r"^/admin/a2a/[^/]+/delete(?:$|/)"), Permissions.A2A_DELETE),
    ("POST", re.compile(r"^/admin/a2a/[^/]+/(?:edit|state)(?:$|/)"), Permissions.A2A_UPDATE),
    ("POST", re.compile(r"^/admin/a2a/[^/]+/test(?:$|/)"), Permissions.A2A_INVOKE),
    ("GET", re.compile(r"^/admin/a2a(?:$|/)"), Permissions.A2A_READ),
    # Section partials
    ("GET", re.compile(r"^/admin/sections/resources(?:$|/)"), Permissions.RESOURCES_READ),
    ("GET", re.compile(r"^/admin/sections/prompts(?:$|/)"), Permissions.PROMPTS_READ),
    ("GET", re.compile(r"^/admin/sections/servers(?:$|/)"), Permissions.SERVERS_READ),
    ("GET", re.compile(r"^/admin/sections/gateways(?:$|/)"), Permissions.GATEWAYS_READ),
    # Specialized admin domains
    ("GET", re.compile(r"^/admin/events(?:$|/)"), Permissions.ADMIN_EVENTS),
    ("GET", re.compile(r"^/admin/grpc(?:$|/)"), Permissions.ADMIN_GRPC),
    ("POST", re.compile(r"^/admin/grpc(?:$|/)"), Permissions.ADMIN_GRPC),
    ("PUT", re.compile(r"^/admin/grpc(?:$|/)"), Permissions.ADMIN_GRPC),
    ("GET", re.compile(r"^/admin/plugins(?:$|/)"), Permissions.ADMIN_PLUGINS),
    ("POST", re.compile(r"^/admin/plugins(?:$|/)"), Permissions.ADMIN_PLUGINS),
    ("PUT", re.compile(r"^/admin/plugins(?:$|/)"), Permissions.ADMIN_PLUGINS),
    ("DELETE", re.compile(r"^/admin/plugins(?:$|/)"), Permissions.ADMIN_PLUGINS),
    # System configuration/admin operations
    (
        "GET",
        re.compile(r"^/admin/(?:config|cache|mcp-pool|roots|metrics|logs|export|import|mcp-registry|system|support-bundle|maintenance|observability|performance|llm)(?:$|/)"),
        Permissions.ADMIN_SYSTEM_CONFIG,
    ),
    (
        "POST",
        re.compile(r"^/admin/(?:config|cache|mcp-pool|roots|metrics|logs|export|import|mcp-registry|system|support-bundle|maintenance|observability|performance|llm)(?:$|/)"),
        Permissions.ADMIN_SYSTEM_CONFIG,
    ),
    (
        "PUT",
        re.compile(r"^/admin/(?:config|cache|mcp-pool|roots|metrics|logs|export|import|mcp-registry|system|support-bundle|maintenance|observability|performance|llm)(?:$|/)"),
        Permissions.ADMIN_SYSTEM_CONFIG,
    ),
    (
        "DELETE",
        re.compile(r"^/admin/(?:config|cache|mcp-pool|roots|metrics|logs|export|import|mcp-registry|system|support-bundle|maintenance|observability|performance|llm)(?:$|/)"),
        Permissions.ADMIN_SYSTEM_CONFIG,
    ),
]


def _normalize_llm_api_prefix(prefix: Optional[str]) -> str:
    """Normalize llm_api_prefix to a canonical path prefix.

    Args:
        prefix: Raw LLM API prefix setting value.

    Returns:
        str: Normalized path prefix, or empty string when prefix is empty or "/".
    """
    if not prefix:
        return ""
    normalized = "/" + str(prefix).strip().strip("/")
    return "" if normalized == "/" else normalized


def _normalize_scope_path(scope_path: str, root_path: str) -> str:
    """Strip ``root_path`` from ``scope_path`` when the incoming path includes it.

    Args:
        scope_path: Request path observed by middleware.
        root_path: Application root path prefix, if configured.

    Returns:
        Path value normalized for permission and scope pattern matching.
    """
    if root_path and len(root_path) > 1:
        root_path = root_path.rstrip("/")
    if root_path and len(root_path) > 1 and scope_path.startswith(root_path):
        rest = scope_path[len(root_path) :]
        # root_path="/app" must not strip from "/application/..."
        if rest == "" or rest.startswith("/"):
            return rest or "/"
    return scope_path


@lru_cache(maxsize=16)
def _get_llm_permission_patterns(prefix: str) -> Tuple[Tuple[str, Pattern[str], str], ...]:
    """Build precompiled permission patterns for LLM proxy endpoints.

    Args:
        prefix: LLM API prefix used to mount proxy routes.

    Returns:
        Tuple[Tuple[str, Pattern[str], str], ...]: Method/path regex to required permission mappings.
    """
    normalized_prefix = _normalize_llm_api_prefix(prefix)
    escaped_prefix = re.escape(normalized_prefix)
    return (
        # LLM proxy routes are exact endpoints (optionally with a trailing slash),
        # unlike many REST resources that intentionally include sub-resources.
        ("POST", re.compile(rf"^{escaped_prefix}/chat/completions/?$"), Permissions.LLM_INVOKE),
        ("GET", re.compile(rf"^{escaped_prefix}/models/?$"), Permissions.LLM_READ),
    )


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

    def _normalize_path_for_matching(self, request_path: str) -> str:
        """Normalize a path for team scoping and permission matching.

        Args:
            request_path: Raw request path.

        Returns:
            Normalized absolute path suitable for route matching.
        """
        normalized = _normalize_scope_path(request_path or "/", settings.app_root_path or "")
        if not normalized.startswith("/"):
            return f"/{normalized}"
        return normalized

    def _get_normalized_request_path(self, request: Request) -> str:
        """Resolve request path with APP_ROOT_PATH-aware normalization.

        Args:
            request: Request object containing scope and URL data.

        Returns:
            Normalized request path suitable for permission checks.
        """
        scope = getattr(request, "scope", {}) or {}
        if not isinstance(scope, dict):
            scope = {}
        scope_path = request.url.path or scope.get("path") or "/"
        root_path = scope.get("root_path") or settings.app_root_path or ""
        normalized = _normalize_scope_path(scope_path, root_path)
        if not normalized.startswith("/"):
            return f"/{normalized}"
        return normalized

    def _extract_jwt_token_from_request(self, request: Request) -> Optional[str]:
        """Extract JWT token from supported cookie names or Bearer auth header.

        Args:
            request: Request object carrying cookies and headers.

        Returns:
            JWT string when present and validly formatted; otherwise ``None``.
        """
        cookies = getattr(request, "cookies", None)
        if cookies and hasattr(cookies, "get"):
            for cookie_name in _AUTH_COOKIE_NAMES:
                cookie_token = cookies.get(cookie_name)
                if isinstance(cookie_token, str) and cookie_token.strip():
                    return cookie_token.strip()

        # Get authorization header and parse bearer scheme case-insensitively.
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            return None

        parts = auth_header.split(" ", 1)
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return None

        token = parts[1].strip()
        return token or None

    async def _extract_token_scopes(self, request: Request) -> Optional[dict]:
        """Extract token scopes from JWT in request.

        Args:
            request: FastAPI request object

        Returns:
            Dict containing token scopes or None if no valid token
        """
        token = self._extract_jwt_token_from_request(request)
        if not token:
            return None

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

    @staticmethod
    def _parse_positive_limit(value: object) -> Optional[int]:
        """Parse usage-limit values as positive integers.

        Args:
            value: Candidate limit value from token scope configuration.

        Returns:
            Parsed positive integer limit, or ``None`` when invalid/non-positive.
        """
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    def _check_usage_limits(self, jti: Optional[str], usage_limits: dict) -> Tuple[bool, Optional[str]]:
        """Check token usage limits against recorded usage logs.

        Args:
            jti: Token JTI identifier.
            usage_limits: Usage limits from token scope.

        Returns:
            Tuple[bool, Optional[str]]: (allowed, denial_reason)
        """
        if not isinstance(usage_limits, dict) or not usage_limits or not jti:
            return True, None

        requests_per_hour = self._parse_positive_limit(usage_limits.get("requests_per_hour"))
        requests_per_day = self._parse_positive_limit(usage_limits.get("requests_per_day"))

        if not requests_per_hour and not requests_per_day:
            return True, None

        # First-Party
        from mcpgateway.db import get_db, TokenUsageLog  # pylint: disable=import-outside-toplevel

        db = next(get_db())
        try:
            now = datetime.now(timezone.utc)

            if requests_per_hour:
                hour_window_start = now - timedelta(hours=1)
                hourly_count = db.execute(
                    # Pylint false-positive: SQLAlchemy func namespace is callable at runtime.
                    # pylint: disable=not-callable
                    select(func.count(TokenUsageLog.id)).where(and_(TokenUsageLog.token_jti == jti, TokenUsageLog.timestamp >= hour_window_start))
                ).scalar()
                if int(hourly_count or 0) >= requests_per_hour:
                    return False, "Hourly request limit exceeded"

            if requests_per_day:
                day_window_start = now - timedelta(days=1)
                daily_count = db.execute(
                    # Pylint false-positive: SQLAlchemy func namespace is callable at runtime.
                    # pylint: disable=not-callable
                    select(func.count(TokenUsageLog.id)).where(and_(TokenUsageLog.token_jti == jti, TokenUsageLog.timestamp >= day_window_start))
                ).scalar()
                if int(daily_count or 0) >= requests_per_day:
                    return False, "Daily request limit exceeded"
        except Exception as exc:
            logger.warning("Failed to evaluate token usage limits for jti %s: %s", jti, exc)
            return True, None
        finally:
            try:
                db.rollback()
            finally:
                db.close()

        return True, None

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
        request_path = self._normalize_path_for_matching(request_path)

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
        general_endpoints = ["/health", "/metrics", "/openapi.json", "/docs", "/redoc", "/rpc"]

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
        request_path = self._normalize_path_for_matching(request_path)

        if not permissions or "*" in permissions:
            return True  # No restrictions or full access

        # Handle admin routes with granular route-group mapping.
        # Unmapped /admin/* paths are denied by default (fail-secure).
        if request_path.startswith("/admin"):
            for method, path_pattern, required_permission in _ADMIN_PERMISSION_PATTERNS:
                if request_method == method and path_pattern.match(request_path):
                    return required_permission in permissions
            return False

        # Check each permission mapping (uses precompiled regex patterns)
        for method, path_pattern, required_permission in _PERMISSION_PATTERNS:
            if request_method == method and path_pattern.match(request_path):
                return required_permission in permissions

        # LLM proxy permissions (respect configured llm_api_prefix).
        for method, path_pattern, required_permission in _get_llm_permission_patterns(settings.llm_api_prefix):
            if request_method == method and path_pattern.match(request_path):
                return required_permission in permissions

        # Default deny for unmatched paths (requires explicit permission mapping)
        return False

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

    def _check_resource_team_ownership(self, request_path: str, token_teams: list, db=None, _user_email: str = None) -> bool:  # noqa: PLR0911  # pylint: disable=too-many-return-statements
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
        request_path = self._normalize_path_for_matching(request_path)

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
        # First-Party
        from mcpgateway.db import Gateway, get_db, Prompt, Resource, Server, Tool  # pylint: disable=import-outside-toplevel

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
                    return False

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

                # PRIVATE SERVERS: Owner-only access (per RBAC doc)
                if server_visibility == "private":
                    server_owner = getattr(server, "owner_email", None)
                    if server_owner and server_owner == _user_email:
                        logger.debug(f"Access granted: Private server {resource_id} owned by {_user_email}")
                        return True

                    logger.warning(f"Access denied: Server {resource_id} is private, owner is '{server_owner}', requester is '{_user_email}'")
                    return False

                # Unknown visibility - deny by default
                logger.warning(f"Access denied: Server {resource_id} has unknown visibility: {server_visibility}")
                return False

            # CHECK TOOLS
            if resource_type == "tool":
                tool = db.execute(select(Tool).where(Tool.id == resource_id)).scalar_one_or_none()

                if not tool:
                    logger.warning(f"Tool {resource_id} not found in database")
                    return False

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

                # PRIVATE TOOLS: Owner-only access (per RBAC doc)
                if tool_visibility in ["private", "user"]:
                    tool_owner = getattr(tool, "owner_email", None)
                    if tool_owner and tool_owner == _user_email:
                        logger.debug(f"Access granted: Private tool {resource_id} owned by {_user_email}")
                        return True

                    logger.warning(f"Access denied: Tool {resource_id} is {tool_visibility}, owner is '{tool_owner}', requester is '{_user_email}'")
                    return False

                # Unknown visibility - deny by default
                logger.warning(f"Access denied: Tool {resource_id} has unknown visibility: {tool_visibility}")
                return False

            # CHECK RESOURCES
            if resource_type == "resource":
                resource = db.execute(select(Resource).where(Resource.id == resource_id)).scalar_one_or_none()

                if not resource:
                    logger.warning(f"Resource {resource_id} not found in database")
                    return False

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

                # PRIVATE RESOURCES: Owner-only access (per RBAC doc)
                if resource_visibility in ["private", "user"]:
                    resource_owner = getattr(resource, "owner_email", None)
                    if resource_owner and resource_owner == _user_email:
                        logger.debug(f"Access granted: Private resource {resource_id} owned by {_user_email}")
                        return True

                    logger.warning(f"Access denied: Resource {resource_id} is {resource_visibility}, owner is '{resource_owner}', requester is '{_user_email}'")
                    return False

                # Unknown visibility - deny by default
                logger.warning(f"Access denied: Resource {resource_id} has unknown visibility: {resource_visibility}")
                return False

            # CHECK PROMPTS
            if resource_type == "prompt":
                prompt = db.execute(select(Prompt).where(Prompt.id == resource_id)).scalar_one_or_none()

                if not prompt:
                    logger.warning(f"Prompt {resource_id} not found in database")
                    return False

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

                # PRIVATE PROMPTS: Owner-only access (per RBAC doc)
                if prompt_visibility in ["private", "user"]:
                    prompt_owner = getattr(prompt, "owner_email", None)
                    if prompt_owner and prompt_owner == _user_email:
                        logger.debug(f"Access granted: Private prompt {resource_id} owned by {_user_email}")
                        return True

                    logger.warning(f"Access denied: Prompt {resource_id} is {prompt_visibility}, owner is '{prompt_owner}', requester is '{_user_email}'")
                    return False

                # Unknown visibility - deny by default
                logger.warning(f"Access denied: Prompt {resource_id} has unknown visibility: {prompt_visibility}")
                return False

            # CHECK GATEWAYS
            if resource_type == "gateway":
                gateway = db.execute(select(Gateway).where(Gateway.id == resource_id)).scalar_one_or_none()

                if not gateway:
                    logger.warning(f"Gateway {resource_id} not found in database")
                    return False

                # Get gateway visibility (default to 'team' if field doesn't exist)
                gateway_visibility = getattr(gateway, "visibility", "team")

                # PUBLIC GATEWAYS: Accessible by everyone (including public-only tokens)
                if gateway_visibility == "public":
                    logger.debug(f"Access granted: Gateway {resource_id} is PUBLIC")
                    return True

                # PUBLIC-ONLY TOKEN: Can ONLY access public gateways (strict public-only policy)
                # No owner access - if user needs own resources, use a personal team-scoped token
                if is_public_token:
                    logger.warning(f"Access denied: Public-only token cannot access {gateway_visibility} gateway {resource_id}")
                    return False

                # TEAM GATEWAYS: Check if gateway's team matches token's teams
                if gateway_visibility == "team":
                    gateway_team_id = getattr(gateway, "team_id", None)
                    if gateway_team_id and gateway_team_id in token_team_ids:
                        logger.debug(f"Access granted: Team gateway {resource_id} belongs to token's team {gateway_team_id}")
                        return True

                    logger.warning(f"Access denied: Gateway {resource_id} is team-scoped to '{gateway_team_id}', token is scoped to teams {token_team_ids}")
                    return False

                # PRIVATE GATEWAYS: Owner-only access (per RBAC doc)
                if gateway_visibility in ["private", "user"]:
                    gateway_owner = getattr(gateway, "owner_email", None)
                    if gateway_owner and gateway_owner == _user_email:
                        logger.debug(f"Access granted: Private gateway {resource_id} owned by {_user_email}")
                        return True

                    logger.warning(f"Access denied: Gateway {resource_id} is {gateway_visibility}, owner is '{gateway_owner}', requester is '{_user_email}'")
                    return False

                # Unknown visibility - deny by default
                logger.warning(f"Access denied: Gateway {resource_id} has unknown visibility: {gateway_visibility}")
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

            normalized_path = self._get_normalized_request_path(request)

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
            if normalized_path == "/":
                return await call_next(request)

            if any(normalized_path.startswith(path) for path in skip_paths):
                return await call_next(request)

            # Skip server-specific well-known endpoints (RFC 9728)
            if re.match(r"^/servers/[^/]+/\.well-known/", normalized_path):
                return await call_next(request)

            # Extract full token payload (not just scopes)
            payload = await self._extract_token_scopes(request)

            # If no payload, continue (regular auth will handle this)
            if not payload:
                return await call_next(request)

            # TEAM VALIDATION: Use single DB session for both team checks
            # This reduces connection pool overhead from 2 sessions to 1 for resource endpoints
            user_email = payload.get("sub") or payload.get("email")  # Extract user email for ownership check

            # Resolve teams based on token_use claim
            token_use = payload.get("token_use")
            if token_use == "session":  # nosec B105 - Not a password; token_use is a JWT claim type
                # Session token: resolve teams from DB/cache directly
                # Cannot rely on request.state.token_teams — AuthContextMiddleware
                # is gated by security_logging_enabled (defaults to False)
                # First-Party
                from mcpgateway.auth import _resolve_teams_from_db  # pylint: disable=import-outside-toplevel

                is_admin = payload.get("is_admin", False) or payload.get("user", {}).get("is_admin", False)
                user_info = {"is_admin": is_admin}
                token_teams = await _resolve_teams_from_db(user_email, user_info)
            else:
                # API token or legacy: use embedded teams with normalize_token_teams
                token_teams = normalize_token_teams(payload)

            # Check if admin bypass is active (token_teams is None means admin with explicit null teams)
            is_admin_bypass = token_teams is None

            # Admin with explicit null teams bypasses team validation entirely
            if is_admin_bypass:
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
                    if not self._check_resource_team_ownership(normalized_path, token_teams, db=db, _user_email=user_email):
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

                if not self._check_resource_team_ownership(normalized_path, token_teams, _user_email=user_email):
                    logger.warning(f"Access denied: Resource does not belong to token's teams {token_teams}")
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied: You do not have permission to access this resource using the current token")

            # Extract scopes from payload
            scopes = payload.get("scopes", {})

            # Check server ID restriction
            server_id = scopes.get("server_id")
            if not self._check_server_restriction(normalized_path, server_id):
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
            if not self._check_permission_restrictions(normalized_path, request.method, permissions):
                logger.warning("Insufficient permissions for this operation")
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions for this operation")

            # Check optional token usage limits.
            usage_limits = scopes.get("usage_limits", {})
            usage_allowed, usage_reason = self._check_usage_limits(payload.get("jti"), usage_limits)
            if not usage_allowed:
                logger.warning("Token usage limit exceeded for jti %s: %s", payload.get("jti"), usage_reason)
                raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=usage_reason or "Token usage limit exceeded")

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
