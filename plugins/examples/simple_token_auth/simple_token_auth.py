# -*- coding: utf-8 -*-
"""Simple Token Authentication Plugin.

This plugin replaces JWT authentication with a simple token-based system.
Tokens are managed through a file-based storage system and can be created
via a login endpoint.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from mcpgateway.plugins.framework import (
    HttpAuthCheckPermissionPayload,
    HttpAuthCheckPermissionResultPayload,
    HttpAuthResolveUserPayload,
    HttpHookType,
    HttpPostRequestPayload,
    HttpPreRequestPayload,
    Plugin,
    PluginConfig,
    PluginContext,
    PluginResult,
    PluginViolation,
    PluginViolationError,
)
from plugins.examples.simple_token_auth.token_storage import TokenStorage
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class SimpleTokenAuthConfig(BaseModel):
    """Configuration for simple token authentication.

    Attributes:
        token_header: HTTP header name for token (default: X-Auth-Token)
        storage_file: Path to file for persisting tokens
        default_token_expiry_days: Default expiration in days (None = never expires)
        transform_to_bearer: Whether to transform token to Authorization: Bearer
    """

    token_header: str = "x-auth-token"
    storage_file: str = "data/auth_tokens.json"
    default_token_expiry_days: Optional[int] = 30
    transform_to_bearer: bool = True


class SimpleTokenAuthPlugin(Plugin):
    """Simple token-based authentication plugin.

    This plugin provides a complete replacement for JWT authentication using
    simple token strings. Features:

    - Token generation and validation
    - File-based token persistence
    - Token expiration
    - User info associated with tokens
    - Admin privilege support

    Hooks:
        - HTTP_PRE_REQUEST: Transform X-Auth-Token to Authorization: Bearer
        - HTTP_AUTH_RESOLVE_USER: Validate token and return user info
        - HTTP_POST_REQUEST: Add auth status headers
    """

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the simple token auth plugin.

        Args:
            config: Plugin configuration
        """
        super().__init__(config)
        logger.info(f"[SimpleTokenAuth] Initializing plugin with config: {config.config}")
        self._cfg = SimpleTokenAuthConfig(**(config.config or {}))
        self._storage = TokenStorage(storage_file=self._cfg.storage_file)

        logger.info(
            f"[SimpleTokenAuth] Plugin initialized successfully: "
            f"header={self._cfg.token_header}, "
            f"storage={self._cfg.storage_file}, "
            f"expiry={self._cfg.default_token_expiry_days} days, "
            f"transform_to_bearer={self._cfg.transform_to_bearer}"
        )

    @property
    def storage(self) -> TokenStorage:
        """Expose token storage for external access (e.g., login endpoints)."""
        return self._storage

    async def http_pre_request(self, payload: HttpPreRequestPayload, context: PluginContext) -> PluginResult:
        """Transform X-Auth-Token to Authorization: Bearer if configured.

        Args:
            payload: HTTP pre-request payload
            context: Plugin context

        Returns:
            PluginResult with potentially modified headers
        """
        if not self._cfg.transform_to_bearer:
            return PluginResult(continue_processing=True)

        headers = dict(payload.headers.root)
        token_header = self._cfg.token_header.lower()
        logger.info(f"[SimpleTokenAuth] http_pre_request - Looking for header: {token_header}, headers: {list(headers.keys())}")

        # Check if token header exists
        if token_header not in headers:
            logger.info(f"[SimpleTokenAuth] Token header '{token_header}' not found in request")
            return PluginResult(continue_processing=True)

        # Don't override existing Authorization header
        if "authorization" in headers:
            logger.info("[SimpleTokenAuth] Authorization header already present, skipping transformation")
            return PluginResult(continue_processing=True)

        # Transform token to Bearer format
        token = headers[token_header]
        headers["authorization"] = f"Bearer {token}"

        logger.info(f"[SimpleTokenAuth] Transformed {token_header} to Authorization: Bearer {token[:20]}...")

        from mcpgateway.plugins.framework import HttpHeaderPayload

        return PluginResult(
            modified_payload=HttpHeaderPayload(root=headers),
            metadata={"transformed": True, "original_header": token_header},
            continue_processing=True,
        )

    async def http_auth_resolve_user(self, payload: HttpAuthResolveUserPayload, context: PluginContext) -> PluginResult:
        """Resolve user from token instead of JWT.

        This completely replaces JWT authentication by validating the token
        and returning user information.

        Args:
            payload: HTTP auth resolve user payload containing credentials
            context: Plugin context

        Returns:
            PluginResult with user data if token is valid

        Raises:
            PluginViolationError: If token is invalid or expired
        """
        # Extract token from credentials
        credentials = payload.credentials
        logger.info(f"[SimpleTokenAuth] http_auth_resolve_user called with credentials: {credentials}")

        if not credentials:
            # No credentials provided, let standard auth try
            logger.info("[SimpleTokenAuth] No credentials provided, continuing to standard auth")
            return PluginResult(
                continue_processing=True,
                metadata={"simple_token_auth": "no_credentials"},
            )

        # Get token from Bearer credentials
        token = credentials.get("credentials") if isinstance(credentials, dict) else None
        logger.info(f"[SimpleTokenAuth] Extracted token: {token[:20] if token else None}...")

        if not token:
            logger.info("[SimpleTokenAuth] No token found in credentials, continuing to standard auth")
            return PluginResult(continue_processing=True, metadata={"simple_token_auth": "no_token"})

        # Validate token
        token_data = self._storage.validate_token(token)

        if token_data is None:
            # Invalid token - raise error to deny access
            logger.warning(f"Invalid or expired token: {token[:10]}...")
            raise PluginViolationError(
                message="Invalid or expired authentication token",
                violation=PluginViolation(
                    code="INVALID_TOKEN",
                    message="The provided authentication token is invalid or has expired",
                    severity="error",
                    details={"token_prefix": token[:10]},
                ),
            )

        # Token is valid - return user information
        logger.info(f"User authenticated via token: {token_data.email}")

        # Store auth method in context state for post-request hook
        context.state["auth_method"] = "simple_token"
        context.state["auth_email"] = token_data.email

        # Return user data (will be converted to EmailUser in auth.py)
        # Use continue_processing=True so plugin manager doesn't treat this as blocking
        # The auth middleware will use our modified_payload and skip JWT validation
        return PluginResult(
            modified_payload={
                "email": token_data.email,
                "full_name": token_data.full_name,
                "is_admin": token_data.is_admin,
                "is_active": True,
                "password_hash": "",  # Not used for token auth
                "email_verified_at": datetime.now(timezone.utc),
                "created_at": token_data.created_at,
                "updated_at": datetime.now(timezone.utc),
            },
            metadata={"auth_method": "simple_token", "token_created": token_data.created_at.isoformat()},
            continue_processing=True,  # Allow other plugins to run, auth middleware will use our payload
        )

    async def http_auth_check_permission(
        self, payload: HttpAuthCheckPermissionPayload, context: PluginContext
    ) -> PluginResult:
        """Check and grant permissions for token-authenticated users.

        Users authenticated via simple tokens bypass RBAC checks and get full permissions.
        This allows token-based access without needing to set up teams/roles in the database.

        Args:
            payload: Permission check payload with user and permission details
            context: Plugin context

        Returns:
            PluginResult with permission decision
        """
        # Only handle users authenticated via our token system
        if payload.auth_method != "simple_token":
            logger.info(f"[SimpleTokenAuth] Skipping permission check for auth_method={payload.auth_method}")
            return PluginResult(continue_processing=True)

        # Grant full permissions to token-authenticated users
        # You could add more granular logic here based on token properties, time, IP, etc.
        logger.info(
            f"[SimpleTokenAuth] Granting permission '{payload.permission}' to token user {payload.user_email} "
            f"(admin={payload.is_admin}, resource={payload.resource_type})"
        )

        result = HttpAuthCheckPermissionResultPayload(
            granted=True,
            reason=f"Token-authenticated user {payload.user_email} granted full access",
        )

        return PluginResult(
            modified_payload=result,
            continue_processing=True,  # Permission granted, let middleware handle the response
        )

    async def http_post_request(self, payload: HttpPostRequestPayload, context: PluginContext) -> PluginResult:
        """Add authentication status headers to responses.

        Args:
            payload: HTTP post-request payload
            context: Plugin context

        Returns:
            PluginResult with modified response headers
        """
        from mcpgateway.plugins.framework import HttpHeaderPayload

        response_headers = dict(payload.response_headers.root) if payload.response_headers else {}

        # Add correlation ID if present in request
        request_headers = dict(payload.headers.root)
        if "x-correlation-id" in request_headers:
            response_headers["x-correlation-id"] = request_headers["x-correlation-id"]

        # Add auth method if available from context
        auth_method = context.state.get("auth_method")
        if auth_method:
            response_headers["x-auth-method"] = auth_method

        # Add auth email if available
        auth_email = context.state.get("auth_email")
        if auth_email:
            response_headers["x-auth-user"] = auth_email

        # Add auth status based on response code
        if payload.status_code:
            if payload.status_code < 400:
                response_headers["x-auth-status"] = "authenticated"
            elif payload.status_code == 401:
                response_headers["x-auth-status"] = "failed"

        return PluginResult(modified_payload=HttpHeaderPayload(root=response_headers), continue_processing=True)

    def get_supported_hooks(self) -> list[str]:
        """Return list of supported hook types."""
        return [
            HttpHookType.HTTP_PRE_REQUEST,
            HttpHookType.HTTP_AUTH_RESOLVE_USER,
            HttpHookType.HTTP_AUTH_CHECK_PERMISSION,
            HttpHookType.HTTP_POST_REQUEST,
        ]
