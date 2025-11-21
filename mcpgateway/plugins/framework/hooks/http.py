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

    def model_dump_pb(self):
        """Convert to protobuf HttpPreRequestPayload message.

        Returns:
            http_pb2.HttpPreRequestPayload: Protobuf message.
        """
        # First-Party
        from mcpgateway.plugins.framework.generated import http_pb2, types_pb2

        # Convert headers
        headers_dict = self.headers.root if hasattr(self.headers, "root") else self.headers
        headers_pb = types_pb2.HttpHeaders(headers=headers_dict)

        return http_pb2.HttpPreRequestPayload(
            path=self.path,
            method=self.method,
            client_host=self.client_host or "",
            client_port=self.client_port or 0,
            headers=headers_pb,
        )

    @classmethod
    def model_validate_pb(cls, proto) -> "HttpPreRequestPayload":
        """Create from protobuf HttpPreRequestPayload message.

        Args:
            proto: http_pb2.HttpPreRequestPayload protobuf message.

        Returns:
            HttpPreRequestPayload: Pydantic model instance.
        """
        headers = HttpHeaderPayload(dict(proto.headers.headers)) if proto.HasField("headers") else HttpHeaderPayload({})

        return cls(
            path=proto.path,
            method=proto.method,
            client_host=proto.client_host if proto.client_host else None,
            client_port=proto.client_port if proto.client_port else None,
            headers=headers,
        )


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

    def model_dump_pb(self):
        """Convert to protobuf HttpPostRequestPayload message.

        Returns:
            http_pb2.HttpPostRequestPayload: Protobuf message.
        """
        # First-Party
        from mcpgateway.plugins.framework.generated import http_pb2, types_pb2

        # Convert headers
        headers_dict = self.headers.root if hasattr(self.headers, "root") else self.headers
        headers_pb = types_pb2.HttpHeaders(headers=headers_dict)

        # Convert response headers if present
        response_headers_pb = None
        if self.response_headers:
            response_dict = self.response_headers.root if hasattr(self.response_headers, "root") else self.response_headers
            response_headers_pb = types_pb2.HttpHeaders(headers=response_dict)

        return http_pb2.HttpPostRequestPayload(
            path=self.path,
            method=self.method,
            client_host=self.client_host or "",
            client_port=self.client_port or 0,
            headers=headers_pb,
            response_headers=response_headers_pb,
            status_code=self.status_code or 0,
        )

    @classmethod
    def model_validate_pb(cls, proto) -> "HttpPostRequestPayload":
        """Create from protobuf HttpPostRequestPayload message.

        Args:
            proto: http_pb2.HttpPostRequestPayload protobuf message.

        Returns:
            HttpPostRequestPayload: Pydantic model instance.
        """
        headers = HttpHeaderPayload(dict(proto.headers.headers)) if proto.HasField("headers") else HttpHeaderPayload({})
        response_headers = HttpHeaderPayload(dict(proto.response_headers.headers)) if proto.HasField("response_headers") else None

        return cls(
            path=proto.path,
            method=proto.method,
            client_host=proto.client_host if proto.client_host else None,
            client_port=proto.client_port if proto.client_port else None,
            headers=headers,
            response_headers=response_headers,
            status_code=proto.status_code if proto.status_code else None,
        )


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

    def model_dump_pb(self):
        """Convert to protobuf HttpAuthResolveUserPayload message.

        Returns:
            http_pb2.HttpAuthResolveUserPayload: Protobuf message.
        """
        # Third-Party
        from google.protobuf import json_format, struct_pb2

        # First-Party
        from mcpgateway.plugins.framework.generated import http_pb2, types_pb2

        # Convert credentials dict to Struct
        credentials_struct = None
        if self.credentials:
            credentials_struct = struct_pb2.Struct()
            json_format.ParseDict(self.credentials, credentials_struct)

        # Convert headers
        headers_dict = self.headers.root if hasattr(self.headers, "root") else self.headers
        headers_pb = types_pb2.HttpHeaders(headers=headers_dict)

        return http_pb2.HttpAuthResolveUserPayload(
            credentials=credentials_struct,
            headers=headers_pb,
            client_host=self.client_host or "",
            client_port=self.client_port or 0,
        )

    @classmethod
    def model_validate_pb(cls, proto) -> "HttpAuthResolveUserPayload":
        """Create from protobuf HttpAuthResolveUserPayload message.

        Args:
            proto: http_pb2.HttpAuthResolveUserPayload protobuf message.

        Returns:
            HttpAuthResolveUserPayload: Pydantic model instance.
        """
        # Third-Party
        from google.protobuf import json_format

        # Convert Struct to dict
        credentials = None
        if proto.HasField("credentials"):
            credentials = json_format.MessageToDict(proto.credentials)

        headers = HttpHeaderPayload(dict(proto.headers.headers)) if proto.HasField("headers") else HttpHeaderPayload({})

        return cls(
            credentials=credentials,
            headers=headers,
            client_host=proto.client_host if proto.client_host else None,
            client_port=proto.client_port if proto.client_port else None,
        )


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

    def model_dump_pb(self):
        """Convert to protobuf HttpAuthCheckPermissionPayload message.

        Returns:
            http_pb2.HttpAuthCheckPermissionPayload: Protobuf message.
        """
        # First-Party
        from mcpgateway.plugins.framework.generated import http_pb2

        return http_pb2.HttpAuthCheckPermissionPayload(
            user_email=self.user_email,
            permission=self.permission,
            resource_type=self.resource_type or "",
            team_id=self.team_id or "",
            is_admin=self.is_admin,
            auth_method=self.auth_method or "",
            client_host=self.client_host or "",
            user_agent=self.user_agent or "",
        )

    @classmethod
    def model_validate_pb(cls, proto) -> "HttpAuthCheckPermissionPayload":
        """Create from protobuf HttpAuthCheckPermissionPayload message.

        Args:
            proto: http_pb2.HttpAuthCheckPermissionPayload protobuf message.

        Returns:
            HttpAuthCheckPermissionPayload: Pydantic model instance.
        """
        return cls(
            user_email=proto.user_email,
            permission=proto.permission,
            resource_type=proto.resource_type if proto.resource_type else None,
            team_id=proto.team_id if proto.team_id else None,
            is_admin=proto.is_admin,
            auth_method=proto.auth_method if proto.auth_method else None,
            client_host=proto.client_host if proto.client_host else None,
            user_agent=proto.user_agent if proto.user_agent else None,
        )


class HttpAuthCheckPermissionResultPayload(PluginPayload):
    """Result payload for permission checking hook.

    Plugins return this to indicate whether permission should be granted.

    Attributes:
        granted: Whether permission is granted (True) or denied (False)
        reason: Optional reason for the decision (for logging/auditing)
    """

    granted: bool
    reason: str | None = None

    def model_dump_pb(self):
        """Convert to protobuf HttpAuthCheckPermissionResultPayload message.

        Returns:
            http_pb2.HttpAuthCheckPermissionResultPayload: Protobuf message.
        """
        # First-Party
        from mcpgateway.plugins.framework.generated import http_pb2

        return http_pb2.HttpAuthCheckPermissionResultPayload(
            granted=self.granted,
            reason=self.reason or "",
        )

    @classmethod
    def model_validate_pb(cls, proto) -> "HttpAuthCheckPermissionResultPayload":
        """Create from protobuf HttpAuthCheckPermissionResultPayload message.

        Args:
            proto: http_pb2.HttpAuthCheckPermissionResultPayload protobuf message.

        Returns:
            HttpAuthCheckPermissionResultPayload: Pydantic model instance.
        """
        return cls(
            granted=proto.granted,
            reason=proto.reason if proto.reason else None,
        )


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
