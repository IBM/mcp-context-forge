# -*- coding: utf-8 -*-
"""HTTP Authentication Middleware.

This middleware allows plugins to:
1. Transform request headers before authentication (HTTP_PRE_REQUEST)
2. Inspect responses after request completion (HTTP_POST_REQUEST)
"""

# Standard
import logging

# Third-Party
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

# First-Party
from mcpgateway.plugins.framework import GlobalContext, HttpHeaderPayload, HttpHookType, HttpPostRequestPayload, HttpPreRequestPayload, PluginManager
from mcpgateway.utils.correlation_id import generate_correlation_id, get_correlation_id

logger = logging.getLogger(__name__)


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
            return await call_next(request)

        # Use correlation ID from CorrelationIDMiddleware if available
        # This ensures all hooks and downstream code see the same unified request ID
        request_id = get_correlation_id()
        if not request_id:
            # Fallback if correlation ID middleware is disabled
            request_id = generate_correlation_id()
            logger.debug(f"Correlation ID not found, generated fallback: {request_id}")

        request.state.request_id = request_id

        # Create global context for hooks
        global_context = GlobalContext(
            request_id=request_id,
            server_id=None,  # Not specific to any server
            tenant_id=None,  # Not specific to any tenant
        )

        # Extract client information
        client_host = None
        client_port = None
        if request.client:
            client_host = request.client.host
            client_port = request.client.port

        # PRE-REQUEST HOOK: Allow plugins to transform headers before authentication
        try:
            pre_result, context_table = await self.plugin_manager.invoke_hook(
                HttpHookType.HTTP_PRE_REQUEST,
                payload=HttpPreRequestPayload(
                    path=str(request.url.path),
                    method=request.method,
                    headers=HttpHeaderPayload(root=dict(request.headers)),
                    client_host=client_host,
                    client_port=client_port,
                ),
                global_context=global_context,
                local_contexts=None,
                violations_as_exceptions=False,  # Don't block on pre-request violations
            )

            if context_table:
                request.state.plugin_context_table = context_table

            if global_context:
                request.state.plugin_global_context = global_context

            # Apply modified headers if plugin returned them
            if pre_result.modified_payload:
                # Modify request headers by updating request.scope["headers"]
                # This is the proper way to modify headers in Starlette/FastAPI
                # Reference: https://stackoverflow.com/questions/69934160/python-how-to-manipulate-fastapi-request-headers-to-be-mutable
                modified_headers_dict = pre_result.modified_payload.root

                # Merge modified headers with original headers (modified headers take precedence)
                original_headers = dict(request.headers)
                merged_headers = {**original_headers, **modified_headers_dict}

                # Update request.scope["headers"] which is the raw header list Starlette uses
                # Convert dict to list of (name, value) tuples with lowercase byte keys
                request.scope["headers"] = [(name.lower().encode(), value.encode()) for name, value in merged_headers.items()]

                logger.debug(f"Pre-request hook modified headers: {list(modified_headers_dict.keys())}")

        except Exception as e:
            # Log but don't fail the request if pre-hook has issues
            logger.warning(f"HTTP_PRE_REQUEST hook failed: {e}", exc_info=True)

        # Process the request through the rest of the application
        response = await call_next(request)

        # POST-REQUEST HOOK: Allow plugins to inspect and modify response
        try:
            # Extract response headers
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
                local_contexts=context_table,  # Pass context from pre-hook
                violations_as_exceptions=False,  # Don't block on post-request violations
            )

            # Apply modified response headers if plugin returned them
            if post_result.modified_payload:
                modified_response_headers = post_result.modified_payload.root
                # Update response headers (response.headers is mutable)
                for header_name, header_value in modified_response_headers.items():
                    response.headers[header_name] = header_value
                logger.debug(f"Post-request hook modified response headers: {list(modified_response_headers.keys())}")

        except Exception as e:
            # Log but don't fail the response if post-hook has issues
            logger.warning(f"HTTP_POST_REQUEST hook failed: {e}", exc_info=True)

        return response
