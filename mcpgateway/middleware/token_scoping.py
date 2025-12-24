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
from typing import Optional

# Third-Party
from fastapi import HTTPException, Request, status
from fastapi.security import HTTPBearer

# First-Party
from mcpgateway.db import Permissions
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.utils.orjson_response import ORJSONResponse
from mcpgateway.utils.verify_credentials import verify_jwt_token

# Security scheme
bearer_scheme = HTTPBearer(auto_error=False)

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


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
            # Use the centralized verify_jwt_token function for consistent JWT validation
            payload = await verify_jwt_token(token)
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

        # Extract server ID from path patterns:
        # /servers/{server_id}/...
        # /sse/{server_id}
        # /ws/{server_id}
        # Using segment-aware patterns for precise matching
        server_path_patterns = [
            r"^/servers/([^/]+)(?:$|/)",
            r"^/sse/([^/?]+)(?:$|\?)",
            r"^/ws/([^/?]+)(?:$|\?)",
        ]

        for pattern in server_path_patterns:
            match = re.search(pattern, request_path)
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

        # Map HTTP methods and paths to permission requirements
        # Using canonical permissions from mcpgateway.db.Permissions
        # Segment-aware patterns to avoid accidental early matches
        permission_map = {
            # Tools permissions
            ("GET", r"^/tools(?:$|/)"): Permissions.TOOLS_READ,
            ("POST", r"^/tools(?:$|/)"): Permissions.TOOLS_CREATE,
            ("PUT", r"^/tools/[^/]+(?:$|/)"): Permissions.TOOLS_UPDATE,
            ("DELETE", r"^/tools/[^/]+(?:$|/)"): Permissions.TOOLS_DELETE,
            ("GET", r"^/servers/[^/]+/tools(?:$|/)"): Permissions.TOOLS_READ,
            ("POST", r"^/servers/[^/]+/tools/[^/]+/call(?:$|/)"): Permissions.TOOLS_EXECUTE,
            # Resources permissions
            ("GET", r"^/resources(?:$|/)"): Permissions.RESOURCES_READ,
            ("POST", r"^/resources(?:$|/)"): Permissions.RESOURCES_CREATE,
            ("PUT", r"^/resources/[^/]+(?:$|/)"): Permissions.RESOURCES_UPDATE,
            ("DELETE", r"^/resources/[^/]+(?:$|/)"): Permissions.RESOURCES_DELETE,
            ("GET", r"^/servers/[^/]+/resources(?:$|/)"): Permissions.RESOURCES_READ,
            # Prompts permissions
            ("GET", r"^/prompts(?:$|/)"): Permissions.PROMPTS_READ,
            ("POST", r"^/prompts(?:$|/)"): Permissions.PROMPTS_CREATE,
            ("PUT", r"^/prompts/[^/]+(?:$|/)"): Permissions.PROMPTS_UPDATE,
            ("DELETE", r"^/prompts/[^/]+(?:$|/)"): Permissions.PROMPTS_DELETE,
            # Server management permissions
            ("GET", r"^/servers(?:$|/)"): Permissions.SERVERS_READ,
            ("POST", r"^/servers(?:$|/)"): Permissions.SERVERS_CREATE,
            ("PUT", r"^/servers/[^/]+(?:$|/)"): Permissions.SERVERS_UPDATE,
            ("DELETE", r"^/servers/[^/]+(?:$|/)"): Permissions.SERVERS_DELETE,
            # Admin permissions
            ("GET", r"^/admin(?:$|/)"): Permissions.ADMIN_USER_MANAGEMENT,
            ("POST", r"^/admin/[^/]+(?:$|/)"): Permissions.ADMIN_USER_MANAGEMENT,
            ("PUT", r"^/admin/[^/]+(?:$|/)"): Permissions.ADMIN_USER_MANAGEMENT,
            ("DELETE", r"^/admin/[^/]+(?:$|/)"): Permissions.ADMIN_USER_MANAGEMENT,
        }

        # Check each permission mapping
        for (method, path_pattern), required_permission in permission_map.items():
            if request_method == method and re.match(path_pattern, request_path):
                return required_permission in permissions

        # Default allow for unmatched paths
        return True

    def _check_team_membership(self, payload: dict) -> bool:
        """
        Check if user still belongs to teams in the token.

        For public-only tokens (no teams), always returns True.
        For team-scoped tokens, validates membership.

        Args:
            payload: Decoded JWT payload containing teams

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

        # Third-Party
        from sqlalchemy import and_, select  # pylint: disable=import-outside-toplevel

        # First-Party
        from mcpgateway.db import EmailTeamMember, get_db  # pylint: disable=import-outside-toplevel

        db = next(get_db())
        try:
            for team in teams:
                # Extract team ID from dict or use string directly (backward compatibility)
                team_id = team["id"] if isinstance(team, dict) else team

                membership = db.execute(
                    select(EmailTeamMember).where(and_(EmailTeamMember.team_id == team_id, EmailTeamMember.user_email == user_email, EmailTeamMember.is_active))
                ).scalar_one_or_none()

                if not membership:
                    logger.warning(f"Token invalid: User {user_email} no longer member of team {team_id}")
                    return False

            return True
        finally:
            db.commit()  # Commit read-only transaction to avoid implicit rollback
            db.close()

    def _check_resource_team_ownership(self, request_path: str, token_teams: list) -> bool:  # pylint: disable=too-many-return-statements
        """
        Check if the requested resource is accessible by the token.

        Implements Three-Tier Resource Visibility (Public/Team/Private):
        - PUBLIC: Accessible by all tokens (public-only and team-scoped)
        - TEAM: Accessible only by tokens scoped to that specific team
        - PRIVATE: Accessible only by tokens scoped to that specific team

        Token Access Rules:
        - Public-only tokens (empty token_teams): Can ONLY access public resources
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

        # Extract resource type and ID from path using regex patterns
        # IDs are UUID hex strings (32 chars) or UUID with dashes (36 chars)
        resource_patterns = [
            (r"/servers/?([a-f0-9\-]+)", "server"),
            (r"/tools/?([a-f0-9\-]+)", "tool"),
            (r"/resources/?([a-f0-9\-]+)", "resource"),
            (r"/prompts/?([a-f0-9\-]+)", "prompt"),
        ]

        resource_id = None
        resource_type = None

        for pattern, rtype in resource_patterns:
            match = re.search(pattern, request_path)
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

                # PUBLIC-ONLY TOKEN: Can ONLY access public servers
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

                # PUBLIC-ONLY TOKEN: Can ONLY access public tools
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

                # PUBLIC-ONLY TOKEN: Can ONLY access public resources
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

                # PUBLIC-ONLY TOKEN: Can ONLY access public prompts
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
            db.commit()  # Commit read-only transaction to avoid implicit rollback
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

            # Extract full token payload (not just scopes)
            payload = await self._extract_token_scopes(request)

            # If no payload, continue (regular auth will handle this)
            if not payload:
                return await call_next(request)

            # TEAM VALIDATION: Check team membership
            if not self._check_team_membership(payload):
                logger.warning("Token rejected: User no longer member of associated team(s)")
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Token is invalid: User is no longer a member of the associated team")

            # TEAM VALIDATION: Check resource team ownership
            token_teams = payload.get("teams", [])
            if not self._check_resource_team_ownership(request.url.path, token_teams):
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
