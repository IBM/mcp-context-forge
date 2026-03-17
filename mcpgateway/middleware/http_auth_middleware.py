# -*- coding: utf-8 -*-
"""HTTP Authentication Middleware.

This middleware allows plugins to:
1. Transform request headers before authentication (HTTP_PRE_REQUEST)
2. Inspect responses after request completion (HTTP_POST_REQUEST)
"""

# Standard
import logging
from typing import Optional

# Third-Party
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

# First-Party
from mcpgateway.config import settings
from mcpgateway.plugins.framework import GlobalContext, HttpHeaderPayload, HttpHookType, HttpPostRequestPayload, HttpPreRequestPayload, PluginManager
from mcpgateway.utils.correlation_id import generate_correlation_id, get_correlation_id

logger = logging.getLogger(__name__)


async def run_pre_request_hooks(
    plugin_manager: PluginManager,
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
        global_context = GlobalContext(request_id=request_id, server_id=None, tenant_id=None)

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
        )

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
        if not settings.plugins_can_override_auth_headers:
            _auth_protected_headers = {"authorization", "cookie", "x-api-key", "proxy-authorization"}
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


class HttpAuthMiddleware(BaseHTTPMiddleware):
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
    """

    def __init__(self, app: ASGIApp, plugin_manager: PluginManager | None = None):
        """Initialize the HTTP auth middleware.

        Args:
            app: The ASGI application
            plugin_manager: Optional plugin manager for hook invocation
        """
        super().__init__(app)
        self.plugin_manager = plugin_manager

    async def dispatch(self, request: Request, call_next):
        """Process request through plugin hooks.

        Args:
            request: The incoming request
            call_next: The next middleware/handler in the chain

        Returns:
            The response from the application
        """
        # Skip hook invocation if no plugin manager
        if not self.plugin_manager:
            logger.debug("HttpAuthMiddleware: no plugin_manager, skipping hooks")
            return await call_next(request)

        # Skip payload creation if no HTTP hooks registered
        has_pre = self.plugin_manager.has_hooks_for(HttpHookType.HTTP_PRE_REQUEST)
        has_post = self.plugin_manager.has_hooks_for(HttpHookType.HTTP_POST_REQUEST)

        if not has_pre and not has_post:
            logger.debug("HttpAuthMiddleware: has_pre=%s has_post=%s, skipping hooks", has_pre, has_post)
            return await call_next(request)

        # Use correlation ID from CorrelationIDMiddleware if available
        request_id = get_correlation_id()
        if not request_id:
            request_id = generate_correlation_id()
            logger.debug(f"Correlation ID not found, generated fallback: {request_id}")

        request.state.request_id = request_id

        global_context = GlobalContext(
            request_id=request_id,
            server_id=None,
            tenant_id=None,
        )

        client_host = None
        client_port = None
        if request.client:
            client_host = request.client.host
            client_port = request.client.port

        context_table = None

        # PRE-REQUEST HOOK: Allow plugins to transform headers before authentication
        if has_pre:
            merged_headers, global_context, context_table = await run_pre_request_hooks(
                plugin_manager=self.plugin_manager,
                headers=dict(request.headers),
                path=str(request.url.path),
                method=request.method,
                client_host=client_host,
                client_port=client_port,
                global_context=global_context,
            )

            if context_table:
                request.state.plugin_context_table = context_table
            if global_context:
                request.state.plugin_global_context = global_context

            # Apply modified headers to the request scope
            request.scope["headers"] = [(name.lower().encode(), value.encode()) for name, value in merged_headers.items()]

        # Process the request through the rest of the application
        response = await call_next(request)

        # POST-REQUEST HOOK: Allow plugins to inspect and modify response
        if has_post:
            try:
                response_headers = HttpHeaderPayload(root=dict(response.headers))

                post_result, _ = await self.plugin_manager.invoke_hook(
                    HttpHookType.HTTP_POST_REQUEST,
                    payload=HttpPostRequestPayload(
                        path=str(request.url.path),
                        method=request.method,
                        headers=HttpHeaderPayload(root=dict(request.headers)),
                        client_host=client_host,
                        client_port=client_port,
                        response_headers=response_headers,
                        status_code=response.status_code,
                    ),
                    global_context=global_context,
                    local_contexts=context_table,
                    violations_as_exceptions=False,
                )

                if post_result.modified_payload:
                    modified_response_headers = post_result.modified_payload.root
                    for header_name, header_value in modified_response_headers.items():
                        response.headers[header_name] = header_value
                    logger.debug(f"Post-request hook modified response headers: {list(modified_response_headers.keys())}")

            except Exception as e:
                logger.warning(f"HTTP_POST_REQUEST hook failed: {e}", exc_info=True)

        return response
