# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/middleware/http_auth_middleware.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

HTTP Authentication Middleware.

This middleware allows plugins to:
1. Transform request headers before authentication (HTTP_PRE_REQUEST)
2. Inspect responses after request completion (HTTP_POST_REQUEST)

Implemented as pure ASGI middleware (no BaseHTTPMiddleware): every request used to
pay BaseHTTPMiddleware's task-group + response-buffering cost even though this
middleware almost always exits early (no HTTP hooks registered). The no-hooks exit
is now a cached verdict check, and responses stream unbuffered.
"""

# Standard
import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

# Third-Party
from cpex.framework import GlobalContext, HttpHeaderPayload, HttpHookType, HttpPostRequestPayload, HttpPreRequestPayload, PluginManager
from starlette.types import ASGIApp

# First-Party
from mcpgateway.config import settings
from mcpgateway.plugins import get_plugin_manager
from mcpgateway.plugins.utils import build_request_extensions, record_plugin_metrics
from mcpgateway.services.observability_service import current_trace_id
from mcpgateway.utils.correlation_id import generate_correlation_id, get_correlation_id
from mcpgateway.utils.verify_credentials import _resolve_auth_header_name

logger = logging.getLogger(__name__)

# How long a (has_pre, has_post) verdict stays valid before re-checking the plugin
# manager. Matches the codebase's existing hot-path toggle caching pattern.
_HOOKS_VERDICT_TTL_SECONDS = 1.0


async def run_pre_request_hooks(
    plugin_manager: PluginManager,  # Base class type annotation is intentional - accepts both PluginManager and TenantPluginManager
    headers: dict[str, str],
    path: str,
    method: str,
    client_host: Optional[str] = None,
    client_port: Optional[int] = None,
    global_context: Optional[GlobalContext] = None,
) -> tuple[dict[str, str], Optional[GlobalContext], Optional[dict]]:
    """Run HTTP_PRE_REQUEST plugin hooks and return (possibly modified) headers.

    This is the shared hook runner used by both HttpAuthMiddleware (Python flow)
    and _run_internal_mcp_authentication (Rust flow) to ensure identical
    plugin behavior regardless of transport.

    Args:
        plugin_manager: The plugin manager instance.
        headers: Original request headers (not mutated).
        path: Request path.
        method: HTTP method.
        client_host: Client IP address.
        client_port: Client port.
        global_context: Optional pre-created global context. Created if not provided.

    Returns:
        Tuple of (merged_headers, global_context, context_table).
        merged_headers reflects any plugin modifications with the auth-header
        override guard applied.
    """
    if not plugin_manager.has_hooks_for(HttpHookType.HTTP_PRE_REQUEST):
        return headers, global_context, None

    if global_context is None:
        request_id = get_correlation_id() or generate_correlation_id()
        content_type = headers.get("content-type") if headers else None
        global_context = GlobalContext(request_id=request_id, server_id=None, tenant_id=None, content_type=content_type)

    try:
        pre_result, context_table = await plugin_manager.invoke_hook(
            HttpHookType.HTTP_PRE_REQUEST,
            payload=HttpPreRequestPayload(
                path=path,
                method=method,
                headers=HttpHeaderPayload(root=dict(headers)),
                client_host=client_host,
                client_port=client_port,
            ),
            global_context=global_context,
            local_contexts=None,
            violations_as_exceptions=False,
            extensions=build_request_extensions(),
        )
        record_plugin_metrics(current_trace_id.get(), pre_result.metadata)

        if not pre_result.modified_payload:
            return headers, global_context, context_table

        modified_headers_dict = pre_result.modified_payload.root

        # Security: prevent plugin hooks from overriding auth-sensitive
        # headers that were already present on the inbound request.
        # Plugins MAY create new auth headers (e.g. x-api-key → authorization
        # transform) but MUST NOT replace values the client already sent.
        #
        # This guard can be disabled with PLUGINS_CAN_OVERRIDE_AUTH_HEADERS=true
        # for deployments that require plugin-driven token exchange (e.g. WXO auth).
        #
        # When AUTH_HEADER_NAME is customized (e.g. X-MCP-Gateway-Auth), the
        # standard Authorization header carries the downstream-server token and
        # MUST also stay protected from plugin overrides — otherwise a plugin
        # could swap out a client-supplied downstream token. Both headers are
        # protected; plugins may still create either header when the client
        # did not send it.
        if not settings.plugins_can_override_auth_headers:
            auth_header_name = _resolve_auth_header_name(settings)

            _auth_protected_headers = {
                auth_header_name.lower(),
                "authorization",
                "cookie",
                "x-api-key",
                "proxy-authorization",
            }

            original_lower = {h.lower() for h in headers}
            overridden = {k.lower() for k in modified_headers_dict if k.lower() in _auth_protected_headers and k.lower() in original_lower}
            if overridden:
                logger.warning("Pre-request hook attempted to override existing auth headers (stripped): %s", overridden)
                modified_headers_dict = {k: v for k, v in modified_headers_dict.items() if k.lower() not in overridden}

        # Normalize to lowercase keys to avoid duplicate logical headers from
        # casing differences (e.g. "Authorization" vs "authorization").
        merged_headers = {k.lower(): v for k, v in headers.items()}
        merged_headers.update({k.lower(): v for k, v in modified_headers_dict.items()})
        logger.debug(f"Pre-request hook modified headers: {list(modified_headers_dict.keys())}")
        return merged_headers, global_context, context_table

    except Exception as e:
        logger.warning(f"HTTP_PRE_REQUEST hook failed: {e}", exc_info=True)
        return headers, global_context, None


def _scope_headers_to_dict(scope: Dict[str, Any]) -> Dict[str, str]:
    """Decode ASGI scope headers into a lowercase-keyed dict.

    Args:
        scope: The ASGI connection scope.

    Returns:
        Dict of header name (lowercase) to value; later duplicates win.
    """
    headers: Dict[str, str] = {}
    for item in scope.get("headers") or []:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            continue
        key, value = item
        if isinstance(key, (bytes, bytearray)) and isinstance(value, (bytes, bytearray)):
            headers[key.decode("latin-1").lower()] = value.decode("latin-1")
    return headers


class HttpAuthMiddleware:
    """Middleware for HTTP authentication hooks.

    This middleware invokes plugin hooks for HTTP request processing:
    - HTTP_PRE_REQUEST: Before any authentication, allows header transformation
    - HTTP_POST_REQUEST: After request completion, allows response inspection

    The middleware allows plugins to:
    - Convert custom authentication tokens to standard formats
    - Add tracing/correlation headers
    - Implement custom authentication schemes
    - Audit authentication attempts
    - Log response status and headers

    Pure ASGI implementation: the no-hooks path costs one cached verdict check,
    and responses are never buffered (the post hook runs on the response-start
    message, whose payload only carries status + headers).
    """

    def __init__(self, app: ASGIApp):
        """Initialize the HTTP auth middleware.

        Args:
            app: The ASGI application
        """
        self.app = app
        # (manager identity, has_pre, has_post, monotonic timestamp)
        self._hooks_verdict: Optional[Tuple[int, bool, bool, float]] = None

    async def _http_hooks_verdict(self) -> Tuple[Optional[PluginManager], bool, bool]:
        """Return the plugin manager plus (has_pre, has_post), cached briefly.

        The verdict is keyed on the manager's identity so a manager replacement
        (plugin reload) takes effect immediately, while repeated calls within
        the TTL window skip even the hook-registry lookups.

        Returns:
            Tuple of (plugin_manager or None, has_pre, has_post).
        """
        plugin_manager = await get_plugin_manager()
        if not plugin_manager:
            return None, False, False
        now = asyncio.get_running_loop().time()
        verdict = self._hooks_verdict
        if verdict is not None and verdict[0] == id(plugin_manager) and (now - verdict[3]) < _HOOKS_VERDICT_TTL_SECONDS:
            return plugin_manager, verdict[1], verdict[2]
        has_pre = plugin_manager.has_hooks_for(HttpHookType.HTTP_PRE_REQUEST)
        has_post = plugin_manager.has_hooks_for(HttpHookType.HTTP_POST_REQUEST)
        self._hooks_verdict = (id(plugin_manager), has_pre, has_post, now)
        return plugin_manager, has_pre, has_post

    async def __call__(self, scope: Dict[str, Any], receive: Callable, send: Callable) -> None:
        """ASGI entry point: fast-path past the hooks whenever none are registered.

        Args:
            scope: ASGI connection scope.
            receive: ASGI receive callable.
            send: ASGI send callable.
        """
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        plugin_manager, has_pre, has_post = await self._http_hooks_verdict()
        if plugin_manager is None or (not has_pre and not has_post):
            await self.app(scope, receive, send)
            return

        # Note: HTTP hooks always use global config (__global__ context) because
        # this middleware runs before virtual server routing. Per-tenant HTTP hooks
        # would require extracting server_id from the request path, which is not
        # currently implemented. This is acceptable for auth-layer middleware.

        # Use correlation ID from CorrelationIDMiddleware if available
        request_id = get_correlation_id()
        if not request_id:
            request_id = generate_correlation_id()
            logger.debug("Correlation ID not found, generated fallback: %s", request_id)

        state = scope.setdefault("state", {})
        state["request_id"] = request_id

        headers = _scope_headers_to_dict(scope)
        global_context = GlobalContext(
            request_id=request_id,
            server_id=None,
            tenant_id=None,
            content_type=headers.get("content-type"),
        )

        client = scope.get("client")
        client_host = client[0] if client else None
        client_port = client[1] if client else None

        context_table = None

        # PRE-REQUEST HOOK: Allow plugins to transform headers before authentication
        if has_pre:
            merged_headers, global_context, context_table = await run_pre_request_hooks(
                plugin_manager=plugin_manager,
                headers=headers,
                path=str(scope.get("path", "")),
                method=str(scope.get("method", "")),
                client_host=client_host,
                client_port=client_port,
                global_context=global_context,
            )

            if context_table:
                state["plugin_context_table"] = context_table
            if global_context:
                state["plugin_global_context"] = global_context

            # Apply modified headers to the request scope
            scope["headers"] = [(name.lower().encode(), value.encode()) for name, value in merged_headers.items()]
            headers = dict(merged_headers)

        # POST-REQUEST HOOK: run on the response-start message (payload carries
        # status + headers only), so responses stream unbuffered and modified
        # headers are applied before anything reaches the client.
        async def send_with_post_hook(message: Dict[str, Any]) -> None:
            """Run the post-request hook on response start, then forward."""
            if has_post and message.get("type") == "http.response.start":
                try:
                    start_headers: List[Tuple[bytes, bytes]] = message.setdefault("headers", [])
                    response_headers = HttpHeaderPayload(root={k.decode("latin-1"): v.decode("latin-1") for k, v in start_headers})

                    post_result, _ = await plugin_manager.invoke_hook(
                        HttpHookType.HTTP_POST_REQUEST,
                        payload=HttpPostRequestPayload(
                            path=str(scope.get("path", "")),
                            method=str(scope.get("method", "")),
                            headers=HttpHeaderPayload(root=headers),
                            client_host=client_host,
                            client_port=client_port,
                            response_headers=response_headers,
                            status_code=message.get("status", 0),
                        ),
                        global_context=global_context,
                        local_contexts=context_table,
                        violations_as_exceptions=False,
                        extensions=build_request_extensions(),
                    )
                    record_plugin_metrics(current_trace_id.get(), post_result.metadata)

                    if post_result.modified_payload:
                        modified_response_headers = post_result.modified_payload.root
                        for header_name, header_value in modified_response_headers.items():
                            lname = header_name.lower().encode("latin-1")
                            start_headers[:] = [(k, v) for k, v in start_headers if k.lower() != lname]
                            start_headers.append((lname, header_value.encode("latin-1")))
                        logger.debug("Post-request hook modified response headers: %s", list(modified_response_headers.keys()))

                except Exception as e:
                    logger.warning(f"HTTP_POST_REQUEST hook failed: {e}", exc_info=True)

            await send(message)

        await self.app(scope, receive, send_with_post_hook)
