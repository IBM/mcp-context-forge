# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/models/http.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Pydantic models for http hooks and payloads.
"""

# Standard
from enum import Enum

# Third-Party
from pydantic import RootModel

# First-Party
from mcpgateway.plugins.framework.models import PluginPayload, PluginResult


class HttpHeaderPayload(RootModel[dict[str, str]], PluginPayload):
    """An HTTP dictionary of headers used in the pre/post HTTP forwarding hooks."""

    def __iter__(self):  # type: ignore[no-untyped-def]
        """Custom iterator function to override root attribute.

        Returns:
            A custom iterator for header dictionary.
        """
        return iter(self.root)

    def __getitem__(self, item: str) -> str:
        """Custom getitem function to override root attribute.

        Args:
            item: The http header key.

        Returns:
            A custom accesser for the header dictionary.
        """
        return self.root[item]

    def __setitem__(self, key: str, value: str) -> None:
        """Custom setitem function to override root attribute.

        Args:
            key: The http header key.
            value: The http header value to be set.
        """
        self.root[key] = value

    def __len__(self) -> int:
        """Custom len function to override root attribute.

        Returns:
            The len of the header dictionary.
        """
        return len(self.root)


HttpHeaderPayloadResult = PluginResult[HttpHeaderPayload]


class HttpHookType(str, Enum):
    """Hook types for HTTP request processing and authentication.

    These hooks allow plugins to:
    1. Transform request headers before processing (middleware layer)
    2. Implement custom user authentication systems (auth layer)
    3. Check and grant permissions (RBAC layer)
    4. Process responses after request completion (middleware layer)
    """

    HTTP_PRE_REQUEST = "http_pre_request"
    HTTP_POST_REQUEST = "http_post_request"
    HTTP_AUTH_RESOLVE_USER = "http_auth_resolve_user"
    HTTP_AUTH_CHECK_PERMISSION = "http_auth_check_permission"


class HttpPreRequestPayload(PluginPayload):
    """Payload for HTTP pre-request hook (middleware layer).

    This payload contains immutable request metadata and a copy of headers
    that plugins can inspect. Invoked before any authentication processing.
    Plugins return only modified headers via PluginResult[HttpHeaderPayload].

    Attributes:
        path: HTTP path being requested.
        method: HTTP method (GET, POST, etc.).
        client_host: Client IP address (if available).
        client_port: Client port (if available).
        headers: Copy of HTTP headers that plugins can inspect and modify.
    """

    path: str
    method: str
    client_host: str | None = None
    client_port: int | None = None
    headers: HttpHeaderPayload


class HttpPostRequestPayload(HttpPreRequestPayload):
    """Payload for HTTP post-request hook (middleware layer).

    Extends HttpPreRequestPayload with response information.
    Invoked after request processing is complete.
    Plugins can inspect response headers and status codes.

    Attributes:
        response_headers: Response headers from the request (if available).
        status_code: HTTP status code from the response (if available).
    """

    response_headers: HttpHeaderPayload | None = None
    status_code: int | None = None


class HttpAuthResolveUserPayload(PluginPayload):
    """Payload for custom user authentication hook (auth layer).

    Invoked inside get_current_user() to allow plugins to provide
    custom authentication mechanisms (LDAP, mTLS, external auth, etc.).
    Plugins return an authenticated user via PluginResult[dict].

    Attributes:
        credentials: The HTTP authorization credentials from bearer_scheme (if present).
        headers: Full request headers for custom auth extraction.
        client_host: Client IP address (if available).
        client_port: Client port (if available).
    """

    credentials: dict | None = None  # HTTPAuthorizationCredentials serialized
    headers: HttpHeaderPayload
    client_host: str | None = None
    client_port: int | None = None


class HttpAuthCheckPermissionPayload(PluginPayload):
    """Payload for permission checking hook (RBAC layer).

    Invoked before RBAC permission checks to allow plugins to:
    - Grant/deny permissions based on custom logic (e.g., token-based auth)
    - Bypass RBAC for certain authentication methods
    - Add additional permission checks (e.g., time-based, IP-based)
    - Implement custom authorization logic

    Attributes:
        user_email: Email of the authenticated user
        permission: Required permission being checked (e.g., "tools.read", "servers.write")
        resource_type: Type of resource being accessed (e.g., "tool", "server", "prompt")
        team_id: Team context for the permission check (if applicable)
        is_admin: Whether the user has admin privileges
        auth_method: Authentication method used (e.g., "simple_token", "jwt", "oauth")
        client_host: Client IP address for IP-based permission checks
        user_agent: User agent string for device-based permission checks
    """

    user_email: str
    permission: str
    resource_type: str | None = None
    team_id: str | None = None
    is_admin: bool = False
    auth_method: str | None = None
    client_host: str | None = None
    user_agent: str | None = None


class HttpAuthCheckPermissionResultPayload(PluginPayload):
    """Result payload for permission checking hook.

    Plugins return this to indicate whether permission should be granted.

    Attributes:
        granted: Whether permission is granted (True) or denied (False)
        reason: Optional reason for the decision (for logging/auditing)
    """

    granted: bool
    reason: str | None = None


# Type aliases for hook results
HttpPreRequestResult = PluginResult[HttpHeaderPayload]
HttpPostRequestResult = PluginResult[HttpHeaderPayload]
HttpAuthResolveUserResult = PluginResult[dict]  # Returns user dict (EmailUser serialized)
HttpAuthCheckPermissionResult = PluginResult[HttpAuthCheckPermissionResultPayload]


def _register_http_auth_hooks() -> None:
    """Register HTTP authentication and request hooks in the global registry.

    This is called lazily to avoid circular import issues.
    Registers four hook types:
    - HTTP_PRE_REQUEST: Transform headers before authentication (middleware)
    - HTTP_POST_REQUEST: Inspect response after request completion (middleware)
    - HTTP_AUTH_RESOLVE_USER: Custom user authentication (auth layer)
    - HTTP_AUTH_CHECK_PERMISSION: Custom permission checking (RBAC layer)
    """
    # Import here to avoid circular dependency at module load time
    # First-Party
    from mcpgateway.plugins.framework.hooks.registry import get_hook_registry  # pylint: disable=import-outside-toplevel

    registry = get_hook_registry()

    # Only register if not already registered (idempotent)
    if not registry.is_registered(HttpHookType.HTTP_PRE_REQUEST):
        registry.register_hook(HttpHookType.HTTP_PRE_REQUEST, HttpPreRequestPayload, HttpPreRequestResult)
        registry.register_hook(HttpHookType.HTTP_POST_REQUEST, HttpPostRequestPayload, HttpPostRequestResult)
        registry.register_hook(HttpHookType.HTTP_AUTH_RESOLVE_USER, HttpAuthResolveUserPayload, HttpAuthResolveUserResult)
        registry.register_hook(HttpHookType.HTTP_AUTH_CHECK_PERMISSION, HttpAuthCheckPermissionPayload, HttpAuthCheckPermissionResult)


_register_http_auth_hooks()
