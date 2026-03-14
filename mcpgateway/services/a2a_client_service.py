# -*- coding: utf-8 -*-
# pylint: disable=import-outside-toplevel
"""Location: ./mcpgateway/services/a2a_client_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

A2A Client Service

HTTP client for communicating with downstream A2A agents.
Supports both non-streaming (JSON-RPC) and streaming (SSE) requests.
"""

# Standard
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, Optional

# Third-Party
import httpx
import httpx_sse

# First-Party
from mcpgateway.config import settings
from mcpgateway.services.a2a_gateway_service import (
    JSONRPC_INTERNAL_ERROR,
    make_jsonrpc_error,
)
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.structured_logger import get_structured_logger
from mcpgateway.utils.correlation_id import get_correlation_id

logging_service = LoggingService()
logger = logging_service.get_logger(__name__)
structured_logger = get_structured_logger()


class A2AClientService:
    """HTTP client for downstream A2A agent communication.

    Provides both non-streaming and streaming (SSE) JSON-RPC request handling.
    Uses httpx.AsyncClient for HTTP and httpx_sse for SSE event parsing.
    """

    async def send_jsonrpc(
        self,
        endpoint_url: str,
        auth_headers: Dict[str, str],
        body: Dict[str, Any],
        *,
        user_id: Optional[str] = None,
        user_email: Optional[str] = None,
        agent_slug: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send a non-streaming JSON-RPC request to a downstream A2A agent.

        Used for: message/send, tasks/get, tasks/cancel, pushNotificationConfig/*.

        Args:
            endpoint_url: The downstream agent's endpoint URL.
            auth_headers: Authentication headers for the downstream agent.
            body: The JSON-RPC request body to forward.
            user_id: User ID for logging.
            user_email: User email for logging.
            agent_slug: Agent slug for logging.

        Returns:
            The JSON-RPC response from the downstream agent.
        """
        from mcpgateway.services.http_client_service import get_http_client
        from mcpgateway.utils.url_auth import sanitize_exception_message, sanitize_url_for_logging

        client = await get_http_client()
        headers = {"Content-Type": "application/json"}
        headers.update(auth_headers)

        correlation_id = get_correlation_id()
        if correlation_id:
            headers["X-Correlation-ID"] = correlation_id

        method = body.get("method", "unknown")
        sanitized_url = sanitize_url_for_logging(endpoint_url)

        structured_logger.log(
            level="INFO",
            message=f"A2A client request: {method} to {agent_slug}",
            component="a2a_client_service",
            user_id=user_id,
            user_email=user_email,
            correlation_id=correlation_id,
            metadata={
                "event": "a2a_client_request_start",
                "agent_slug": agent_slug,
                "method": method,
                "endpoint_url": sanitized_url,
            },
        )

        call_start = datetime.now(timezone.utc)

        try:
            response = await client.post(
                endpoint_url,
                json=body,
                headers=headers,
                timeout=settings.a2a_gateway_client_timeout,
            )
            duration_ms = (datetime.now(timezone.utc) - call_start).total_seconds() * 1000

            if response.status_code == 200:
                result = response.json()
                structured_logger.log(
                    level="INFO",
                    message=f"A2A client request completed: {method} to {agent_slug}",
                    component="a2a_client_service",
                    user_id=user_id,
                    user_email=user_email,
                    correlation_id=correlation_id,
                    duration_ms=duration_ms,
                    metadata={
                        "event": "a2a_client_request_completed",
                        "agent_slug": agent_slug,
                        "method": method,
                        "status_code": response.status_code,
                    },
                )
                return result
            else:
                raw_error = f"HTTP {response.status_code}: {response.text}"
                error_message = sanitize_exception_message(raw_error)

                structured_logger.log(
                    level="ERROR",
                    message=f"A2A client request failed: {method} to {agent_slug}",
                    component="a2a_client_service",
                    user_id=user_id,
                    user_email=user_email,
                    correlation_id=correlation_id,
                    duration_ms=duration_ms,
                    error_details={"error_type": "A2AClientHTTPError", "error_message": error_message},
                    metadata={
                        "event": "a2a_client_request_failed",
                        "agent_slug": agent_slug,
                        "method": method,
                        "status_code": response.status_code,
                    },
                )

                return make_jsonrpc_error(
                    JSONRPC_INTERNAL_ERROR,
                    f"Downstream agent error: {error_message}",
                    body.get("id"),
                )

        except httpx.TimeoutException:
            duration_ms = (datetime.now(timezone.utc) - call_start).total_seconds() * 1000
            structured_logger.log(
                level="ERROR",
                message=f"A2A client request timeout: {method} to {agent_slug}",
                component="a2a_client_service",
                user_id=user_id,
                user_email=user_email,
                correlation_id=correlation_id,
                duration_ms=duration_ms,
                error_details={"error_type": "TimeoutError", "error_message": f"Timeout after {settings.a2a_gateway_client_timeout}s"},
                metadata={"event": "a2a_client_request_timeout", "agent_slug": agent_slug, "method": method},
            )
            return make_jsonrpc_error(
                JSONRPC_INTERNAL_ERROR,
                f"Downstream agent timed out after {settings.a2a_gateway_client_timeout}s",
                body.get("id"),
            )

        except Exception as e:
            duration_ms = (datetime.now(timezone.utc) - call_start).total_seconds() * 1000
            error_str = sanitize_exception_message(str(e))

            structured_logger.log(
                level="ERROR",
                message=f"A2A client request exception: {method} to {agent_slug}",
                component="a2a_client_service",
                user_id=user_id,
                user_email=user_email,
                correlation_id=correlation_id,
                duration_ms=duration_ms,
                error_details={"error_type": type(e).__name__, "error_message": error_str},
                metadata={"event": "a2a_client_request_exception", "agent_slug": agent_slug, "method": method},
            )

            return make_jsonrpc_error(
                JSONRPC_INTERNAL_ERROR,
                f"Failed to reach downstream agent: {error_str}",
                body.get("id"),
            )

    async def stream_jsonrpc(
        self,
        endpoint_url: str,
        auth_headers: Dict[str, str],
        body: Dict[str, Any],
        *,
        user_id: Optional[str] = None,
        user_email: Optional[str] = None,
        agent_slug: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """Send a streaming JSON-RPC request and yield SSE events.

        Used for: message/stream, tasks/resubscribe.

        Establishes an SSE connection to the downstream agent and yields
        raw SSE event strings that can be forwarded to the client.

        Args:
            endpoint_url: The downstream agent's endpoint URL.
            auth_headers: Authentication headers for the downstream agent.
            body: The JSON-RPC request body to forward.
            user_id: User ID for logging.
            user_email: User email for logging.
            agent_slug: Agent slug for logging.

        Yields:
            SSE event strings in the format "data: {...}\n\n".
        """
        from mcpgateway.utils.url_auth import sanitize_url_for_logging

        headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
        headers.update(auth_headers)

        correlation_id = get_correlation_id()
        if correlation_id:
            headers["X-Correlation-ID"] = correlation_id

        method = body.get("method", "unknown")
        sanitized_url = sanitize_url_for_logging(endpoint_url)

        structured_logger.log(
            level="INFO",
            message=f"A2A client stream started: {method} to {agent_slug}",
            component="a2a_client_service",
            user_id=user_id,
            user_email=user_email,
            correlation_id=correlation_id,
            metadata={
                "event": "a2a_client_stream_start",
                "agent_slug": agent_slug,
                "method": method,
                "endpoint_url": sanitized_url,
            },
        )

        call_start = datetime.now(timezone.utc)
        event_count = 0

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(settings.a2a_gateway_stream_timeout)) as client:
                async with httpx_sse.aconnect_sse(
                    client,
                    "POST",
                    endpoint_url,
                    json=body,
                    headers=headers,
                ) as event_source:
                    event_source.response.raise_for_status()

                    async for event in event_source.aiter_sse():
                        event_count += 1
                        # Forward the SSE event to the client
                        if event.event:
                            yield f"event: {event.event}\ndata: {event.data}\n\n"
                        else:
                            yield f"data: {event.data}\n\n"

        except httpx.TimeoutException:
            duration_ms = (datetime.now(timezone.utc) - call_start).total_seconds() * 1000
            structured_logger.log(
                level="ERROR",
                message=f"A2A client stream timeout: {method} to {agent_slug}",
                component="a2a_client_service",
                user_id=user_id,
                user_email=user_email,
                correlation_id=correlation_id,
                duration_ms=duration_ms,
                error_details={"error_type": "StreamTimeoutError"},
                metadata={"event": "a2a_client_stream_timeout", "agent_slug": agent_slug, "method": method, "event_count": event_count},
            )
            # Yield an error event to the client
            import json

            error_data = json.dumps(make_jsonrpc_error(JSONRPC_INTERNAL_ERROR, "Stream timed out", body.get("id")))
            yield f"data: {error_data}\n\n"

        except Exception as e:
            duration_ms = (datetime.now(timezone.utc) - call_start).total_seconds() * 1000
            from mcpgateway.utils.url_auth import sanitize_exception_message

            error_str = sanitize_exception_message(str(e))

            structured_logger.log(
                level="ERROR",
                message=f"A2A client stream error: {method} to {agent_slug}",
                component="a2a_client_service",
                user_id=user_id,
                user_email=user_email,
                correlation_id=correlation_id,
                duration_ms=duration_ms,
                error_details={"error_type": type(e).__name__, "error_message": error_str},
                metadata={"event": "a2a_client_stream_error", "agent_slug": agent_slug, "method": method, "event_count": event_count},
            )
            import json

            error_data = json.dumps(make_jsonrpc_error(JSONRPC_INTERNAL_ERROR, f"Stream error: {error_str}", body.get("id")))
            yield f"data: {error_data}\n\n"

        finally:
            duration_ms = (datetime.now(timezone.utc) - call_start).total_seconds() * 1000
            structured_logger.log(
                level="INFO",
                message=f"A2A client stream ended: {method} to {agent_slug}",
                component="a2a_client_service",
                user_id=user_id,
                user_email=user_email,
                correlation_id=correlation_id,
                duration_ms=duration_ms,
                metadata={
                    "event": "a2a_client_stream_end",
                    "agent_slug": agent_slug,
                    "method": method,
                    "event_count": event_count,
                },
            )
