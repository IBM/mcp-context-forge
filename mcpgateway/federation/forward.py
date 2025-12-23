# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/federation/forward.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Federation Request Forwarding.

This module implements request forwarding for federated MCP Gateways.
It handles:
- Request routing to appropriate gateways
- Response aggregation
- Error handling and retry logic
- Request/response transformation

The ForwardingService class provides the main interface for forwarding
requests across federated gateways, including tool invocations and
resource reads.

Examples:
    >>> from mcpgateway.federation.forward import ForwardingService
    >>> service = ForwardingService()
    >>> # Forward requests to gateways
    >>> # service.forward_request(db, "tools/list")
"""

# Standard
import asyncio
from datetime import datetime, timezone
import time
from typing import Any, Dict, List, Optional, Set, Tuple, Union

# Third-Party
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.common.models import ToolResult
from mcpgateway.config import settings
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import ServerMetric
from mcpgateway.db import Tool as DbTool
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.utils.passthrough_headers import get_passthrough_headers

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class ForwardingError(Exception):
    """Base class for forwarding-related errors.

    This exception is raised when request forwarding operations fail,
    including network errors, gateway unavailability, or invalid responses.

    Examples:
        >>> try:
        ...     raise ForwardingError("Gateway timeout")
        ... except ForwardingError as e:
        ...     print(f"Error: {e}")
        Error: Gateway timeout

        >>> try:
        ...     raise ForwardingError("Invalid response format")
        ... except ForwardingError as e:
        ...     print(f"Caught: {e}")
        Caught: Invalid response format
    """


class ForwardingService:
    """Service for handling request forwarding across gateways.

    Handles:
    - Request routing
    - Response aggregation
    - Error handling
    - Request transformation
    """

    def __init__(self):
        """Initialize forwarding service.

        Sets up HTTP client with configured timeout and SSL verification settings,
        and initializes tracking structures for active requests, request history,
        and gateway tool caches.

        Examples:
            >>> service = ForwardingService()
            >>> isinstance(service._http_client, httpx.AsyncClient)
            True
            >>> service._active_requests
            {}
            >>> service._request_history
            {}
            >>> service._gateway_tools
            {}
        """
        self._http_client = httpx.AsyncClient(timeout=settings.federation_timeout, verify=not settings.skip_ssl_verify)

        # Track active requests
        self._active_requests: Dict[str, asyncio.Task] = {}

        # Request history for rate limiting
        self._request_history: Dict[str, List[datetime]] = {}

        # Cache gateway information
        self._gateway_tools: Dict[int, Set[str]] = {}

    async def start(self) -> None:
        """Start forwarding service."""
        logger.info("Request forwarding service started")

    async def stop(self) -> None:
        """Stop forwarding service."""
        # Cancel active requests
        for request_id, task in self._active_requests.items():
            logger.info(f"Cancelling request {request_id}")
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        await self._http_client.aclose()
        logger.info("Request forwarding service stopped")

    async def forward_request(
        self,
        db: Session,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        target_gateway_id: Optional[int] = None,
        request_headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        """Forward a request to gateway(s).

        Routes requests to specific gateways or broadcasts to all active gateways
        based on the target_gateway_id parameter. Handles both targeted and
        broadcast forwarding scenarios with proper error handling.

        Args:
            db: Database session for gateway lookups
            method: RPC method name (e.g., "tools/list", "resources/read")
            params: Optional method parameters as key-value pairs
            target_gateway_id: Optional specific gateway ID for targeted forwarding
            request_headers (Optional[Dict[str, str]], optional): Headers from the request to pass through.
                Defaults to None.

        Returns:
            Any: Single gateway response for targeted requests (when target_gateway_id
                is provided), or list of responses from all active gateways for
                broadcast requests (when target_gateway_id is None).

        Raises:
            ForwardingError: If forwarding fails due to network issues,
                invalid gateway, or all gateways failing

        Examples:
            >>> import asyncio
            >>> from unittest.mock import Mock, AsyncMock
            >>>
            >>> # Test targeted forwarding
            >>> service = ForwardingService()
            >>> service._forward_to_gateway = AsyncMock(return_value={"status": "ok"})
            >>> db = Mock()
            >>> result = asyncio.run(service.forward_request(db, "test/method", {"param": "value"}, 123))
            >>> result
            {'status': 'ok'}

            >>> # Test broadcast forwarding
            >>> service._forward_to_all = AsyncMock(return_value=[{"gateway1": "ok"}, {"gateway2": "ok"}])
            >>> results = asyncio.run(service.forward_request(db, "tools/list"))
            >>> len(results)
            2

            >>> # Test error handling
            >>> service._forward_to_gateway = AsyncMock(side_effect=Exception("Network error"))
            >>> try:
            ...     asyncio.run(service.forward_request(db, "test", target_gateway_id=1))
            ... except ForwardingError as e:
            ...     print("Error:", str(e))
            Error: Forward request failed: Network error
        """
        try:
            if target_gateway_id:
                # Forward to specific gateway
                return await self._forward_to_gateway(db, target_gateway_id, method, params, request_headers)

            # Forward to all relevant gateways - headers are passed to each gateway
            return await self._forward_to_all(db, method, params, request_headers)

        except Exception as e:
            raise ForwardingError(f"Forward request failed: {str(e)}")

    async def forward_tool_request(self, db: Session, tool_name: str, arguments: Dict[str, Any], request_headers: Optional[Dict[str, str]] = None) -> ToolResult:
        """Forward a tool invocation request.

        Locates the specified tool in the database, verifies it's federated,
        and forwards the invocation request to the appropriate gateway.
        Handles tool validation and response parsing.

        Args:
            db: Database session for tool and gateway lookups
            tool_name: Name of the tool to invoke
            arguments: Tool arguments as key-value pairs
            request_headers (Optional[Dict[str, str]], optional): Headers from the request to pass through.
                Defaults to None.

        Returns:
            ToolResult object containing the tool execution results

        Raises:
            ForwardingError: If tool not found, not federated, or forwarding fails

        Examples:
            >>> import asyncio
            >>> from unittest.mock import Mock, AsyncMock, MagicMock
            >>>
            >>> # Test successful tool forwarding
            >>> service = ForwardingService()
            >>> db = Mock()
            >>> tool = Mock(name="calculator", gateway_id=1, enabled=True)
            >>> db.execute.return_value.scalar_one_or_none.return_value = tool
            >>> # ToolResult expects content to be a list of content objects
            >>> service._forward_to_gateway = AsyncMock(
            ...     return_value={
            ...         "content": [{"type": "text", "text": "Result: 42"}],
            ...         "is_error": False
            ...     }
            ... )
            >>>
            >>> result = asyncio.run(service.forward_tool_request(
            ...     db, "calculator", {"operation": "add", "a": 20, "b": 22}
            ... ))
            >>> result.content[0].text
            'Result: 42'
            >>> result.is_error
            False

            >>> # Test tool not found
            >>> db.execute.return_value.scalar_one_or_none.return_value = None
            >>> try:
            ...     asyncio.run(service.forward_tool_request(db, "unknown_tool", {}))
            ... except ForwardingError as e:
            ...     print(str(e))
            Failed to forward tool request: Tool not found: unknown_tool

            >>> # Test non-federated tool
            >>> tool = Mock(name="local_tool", gateway_id=None, enabled=True)
            >>> db.execute.return_value.scalar_one_or_none.return_value = tool
            >>> try:
            ...     asyncio.run(service.forward_tool_request(db, "local_tool", {}))
            ... except ForwardingError as e:
            ...     print(str(e))
            Failed to forward tool request: Tool local_tool is not federated
        """
        try:
            # Find tool
            tool = db.execute(select(DbTool).where(DbTool.name == tool_name).where(DbTool.enabled)).scalar_one_or_none()

            if not tool:
                raise ForwardingError(f"Tool not found: {tool_name}")

            if not tool.gateway_id:
                raise ForwardingError(f"Tool {tool_name} is not federated")

            # Forward to gateway
            result = await self._forward_to_gateway(db, tool.gateway_id, "tools/invoke", {"name": tool_name, "arguments": arguments}, request_headers)

            # Parse result
            return ToolResult(
                content=result.get("content", []),
                is_error=result.get("is_error", False),
            )

        except Exception as e:
            raise ForwardingError(f"Failed to forward tool request: {str(e)}")

    async def forward_resource_request(self, db: Session, uri: str) -> Tuple[Union[str, bytes], str]:
        """Forward a resource read request.

        Locates the gateway hosting the specified resource URI and forwards
        the read request. Handles both text and binary resource responses
        with appropriate MIME type detection.

        Args:
            db: Database session for gateway lookups
            uri: Resource URI to read (e.g., "file://data.csv", "https://api/resource")

        Returns:
            Tuple of (content, mime_type) where content is str for text
            or bytes for binary data

        Raises:
            ForwardingError: If no gateway found for resource or forwarding fails

        Examples:
            >>> import asyncio
            >>> from unittest.mock import Mock, AsyncMock
            >>>
            >>> # Test text resource
            >>> service = ForwardingService()
            >>> db = Mock()
            >>> gateway = Mock(id=1, name="gateway1")
            >>> service._find_resource_gateway = AsyncMock(return_value=gateway)
            >>> service._forward_to_gateway = AsyncMock(
            ...     return_value={"text": "Hello, World!", "mime_type": "text/plain"}
            ... )
            >>>
            >>> content, mime_type = asyncio.run(
            ...     service.forward_resource_request(db, "file://hello.txt")
            ... )
            >>> content
            'Hello, World!'
            >>> mime_type
            'text/plain'

            >>> # Test binary resource
            >>> service._forward_to_gateway = AsyncMock(
            ...     return_value={"blob": b"\\x89PNG...", "mime_type": "image/png"}
            ... )
            >>> content, mime_type = asyncio.run(
            ...     service.forward_resource_request(db, "file://image.png")
            ... )
            >>> isinstance(content, bytes)
            True
            >>> mime_type
            'image/png'

            >>> # Test resource not found
            >>> service._find_resource_gateway = AsyncMock(return_value=None)
            >>> try:
            ...     asyncio.run(service.forward_resource_request(db, "unknown://resource"))
            ... except ForwardingError as e:
            ...     print(str(e))
            Failed to forward resource request: No gateway found for resource: unknown://resource
        """
        try:
            # Find gateway for resource
            gateway = await self._find_resource_gateway(db, uri)
            if not gateway:
                raise ForwardingError(f"No gateway found for resource: {uri}")

            # Forward request
            result = await self._forward_to_gateway(db, gateway.id, "resources/read", {"uri": uri})

            # Parse result
            if "text" in result:
                return result["text"], result.get("mime_type", "text/plain")
            if "blob" in result:
                return result["blob"], result.get("mime_type", "application/octet-stream")

            raise ForwardingError("Invalid resource response format")

        except Exception as e:
            raise ForwardingError(f"Failed to forward resource request: {str(e)}")

    async def _record_server_metric(self, db: Session, gateway: DbGateway, start_time: float, success: bool, error_message: Optional[str]) -> None:
        """
        Records a metric for a server interaction.

        Args:
            db: Database session
            gateway: The gateway that was accessed
            start_time: Monotonic start time of the interaction
            success: True if successful, False otherwise
            error_message: Error message if failed, None otherwise
        """
        end_time = time.monotonic()
        response_time = end_time - start_time

        metric = ServerMetric(
            server_id=gateway.id,
            response_time=response_time,
            is_success=success,
            error_message=error_message,
        )
        db.add(metric)
        db.commit()

    async def _forward_to_gateway(
        self,
        db: Session,
        gateway_id: str,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        request_headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        """Forward request to a specific gateway.

        Sends JSON-RPC formatted requests to the specified gateway with
        authentication, retry logic, and rate limiting. Updates gateway
        last_seen timestamp on successful communication.

        Args:
            db: Database session for gateway record updates
            gateway_id: ID of the gateway to forward to
            method: RPC method name
            params: Optional method parameters
            request_headers (Optional[Dict[str, str]], optional): Headers from the request to pass through.
                Defaults to None.

        Returns:
            The 'result' field from the gateway's JSON-RPC response

        Raises:
            ForwardingError: If gateway not found, rate limited, or request fails
            httpx.TimeoutException: If unable to connect after all retries

        Examples:
            >>> import asyncio
            >>> from unittest.mock import Mock, AsyncMock, MagicMock
            >>> from datetime import datetime, timezone
            >>>
            >>> # Test successful forwarding
            >>> service = ForwardingService()
            >>> db = Mock()
            >>> gateway = Mock(id="gw1", name="Gateway 1", url="http://gateway1.com", enabled=True)
            >>> db.get.return_value = gateway
            >>> service._check_rate_limit = Mock(return_value=True)
            >>> service._get_auth_headers = Mock(return_value={"Authorization": "Basic test"})
            >>>
            >>> # Mock HTTP response
            >>> response = Mock()
            >>> response.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": {"tools": ["tool1", "tool2"]}}
            >>> response.raise_for_status = Mock()
            >>> service._http_client.post = AsyncMock(return_value=response)
            >>>
            >>> result = asyncio.run(service._forward_to_gateway(db, "gw1", "tools/list"))
            >>> result
            {'tools': ['tool1', 'tool2']}
            >>> gateway.last_seen is not None
            True

            >>> # Test gateway not found
            >>> db.get.return_value = None
            >>> try:
            ...     asyncio.run(service._forward_to_gateway(db, "invalid", "test"))
            ... except ForwardingError as e:
            ...     print(str(e))
            Gateway not found: invalid

            >>> # Test rate limiting
            >>> db.get.return_value = gateway
            >>> service._check_rate_limit = Mock(return_value=False)
            >>> try:
            ...     asyncio.run(service._forward_to_gateway(db, "gw1", "test"))
            ... except ForwardingError as e:
            ...     print("Rate limit" in str(e))
            True
        """
        start_time = time.monotonic()
        success = False
        error_message = None

        # Get gateway
        gateway = db.get(DbGateway, gateway_id)
        if not gateway or not gateway.enabled:
            raise ForwardingError(f"Gateway not found: {gateway_id}")

        try:
            # Check rate limits
            if not self._check_rate_limit(gateway.url):
                raise ForwardingError("Rate limit exceeded")

            # Build request
            request = {"jsonrpc": "2.0", "id": 1, "method": method}
            if params:
                request["params"] = params

            # Send request with retries using the persistent client directly
            for attempt in range(settings.max_tool_retries):
                try:
                    # Merge auth headers with passthrough headers
                    headers = self._get_auth_headers()
                    if request_headers:
                        headers = get_passthrough_headers(request_headers, headers, db, gateway)

                    response = await self._http_client.post(
                        f"{gateway.url}/rpc",
                        json=request,
                        headers=headers,
                    )
                    response.raise_for_status()
                    result = response.json()

                    # Update last seen
                    gateway.last_seen = datetime.now(timezone.utc)

                    # Handle response
                    if "error" in result:
                        raise ForwardingError(f"Gateway error: {result['error'].get('message')}")

                    success = True
                    return result.get("result")

                except httpx.TimeoutException:
                    if attempt == settings.max_tool_retries - 1:
                        raise
                    await asyncio.sleep(1 * (attempt + 1))

        except Exception as e:
            success = False
            error_message = str(e)
            raise ForwardingError(f"Failed to forward to {gateway.name}: {str(e)}")
        finally:
            # Always record the metric via buffered service
            try:
                # First-Party
                from mcpgateway.services.metrics_buffer_service import get_metrics_buffer_service  # pylint: disable=import-outside-toplevel

                metrics_buffer = get_metrics_buffer_service()
                metrics_buffer.record_server_metric(
                    server_id=gateway.id,
                    start_time=start_time,
                    success=success,
                    error_message=error_message,
                )
            except Exception as metrics_error:
                logger.warning(f"Failed to record server metric: {metrics_error}")

    async def _forward_to_all(self, db: Session, method: str, params: Optional[Dict[str, Any]] = None, request_headers: Optional[Dict[str, str]] = None) -> List[Any]:
        """Forward request to all active gateways.

        Broadcasts the same request to all enabled gateways in parallel,
        collecting successful responses while tracking individual failures.
        Continues forwarding even if some gateways fail.

        Args:
            db: Database session for gateway queries
            method: RPC method name to invoke on all gateways
            params: Optional method parameters
            request_headers (Optional[Dict[str, str]], optional): Headers from the request to pass through.
                Defaults to None.

        Returns:
            List of successful responses from active gateways

        Raises:
            ForwardingError: Only if ALL gateways fail (partial success is allowed)

        Examples:
            >>> import asyncio
            >>> from unittest.mock import Mock, AsyncMock, MagicMock
            >>>
            >>> # Test broadcasting to multiple gateways
            >>> service = ForwardingService()
            >>> db = Mock()
            >>> gw1 = Mock(id=1, name="Gateway 1", enabled=True)
            >>> gw2 = Mock(id=2, name="Gateway 2", enabled=True)
            >>> gw3 = Mock(id=3, name="Gateway 3", enabled=True)
            >>>
            >>> # Mock database query
            >>> mock_result = Mock()
            >>> mock_result.scalars.return_value.all.return_value = [gw1, gw2, gw3]
            >>> db.execute.return_value = mock_result
            >>>
            >>> # Mock forwarding with mixed results
            >>> async def mock_forward(db, gw_id, method, params=None, request_headers=None):
            ...     if gw_id == 1:
            ...         return {"gateway": "gw1", "status": "ok"}
            ...     elif gw_id == 2:
            ...         raise Exception("Gateway 2 is down")
            ...     else:
            ...         return {"gateway": "gw3", "status": "ok"}
            >>>
            >>> service._forward_to_gateway = mock_forward
            >>> results = asyncio.run(service._forward_to_all(db, "health/check"))
            >>> len(results)
            2
            >>> results[0]["gateway"]
            'gw1'
            >>> results[1]["gateway"]
            'gw3'

            >>> # Test all gateways failing
            >>> async def mock_all_fail(db, gw_id, method, params=None, request_headers=None):
            ...     raise Exception(f"Gateway {gw_id} failed")
            >>>
            >>> service._forward_to_gateway = mock_all_fail
            >>> try:
            ...     asyncio.run(service._forward_to_all(db, "test"))
            ... except ForwardingError as e:
            ...     print("All failed:", "Gateway 1 failed" in str(e))
            All failed: True
        """
        # Get active gateways
        gateways = db.execute(select(DbGateway).where(DbGateway.enabled)).scalars().all()

        # Forward to each gateway
        results = []
        errors = []

        for gateway in gateways:
            try:
                result = await self._forward_to_gateway(db, gateway.id, method, params, request_headers)
                results.append(result)
            except Exception as e:
                errors.append(str(e))

        if not results and errors:
            raise ForwardingError(f"All forwards failed: {'; '.join(errors)}")

        return results

    async def _find_resource_gateway(self, db: Session, uri: str) -> Optional[DbGateway]:
        """Find gateway hosting a resource.

        Queries all active gateways for their resource lists to locate
        which gateway hosts the specified resource URI. Uses sequential
        checking with error tolerance for unreachable gateways.

        Args:
            db: Database session for gateway queries
            uri: Resource URI to locate (e.g., "file://data.csv")

        Returns:
            Gateway record hosting the resource, or None if not found

        Examples:
            >>> import asyncio
            >>> from unittest.mock import Mock, AsyncMock, MagicMock
            >>>
            >>> # Test finding resource
            >>> service = ForwardingService()
            >>> db = Mock()
            >>> # Properly configure mock gateway objects
            >>> gw1 = Mock(id=1, enabled=True)
            >>> gw1.name = "Gateway 1"
            >>> gw2 = Mock(id=2, enabled=True)
            >>> gw2.name = "Gateway 2"
            >>>
            >>> # Mock database query
            >>> mock_result = Mock()
            >>> mock_result.scalars.return_value.all.return_value = [gw1, gw2]
            >>> db.execute.return_value = mock_result
            >>>
            >>> # Mock gateway responses
            >>> async def mock_forward(db, gw_id, method, params=None):
            ...     if gw_id == 1:
            ...         return [{"uri": "file://doc1.txt"}, {"uri": "file://doc2.txt"}]
            ...     else:
            ...         return [{"uri": "file://data.csv"}, {"uri": "file://config.json"}]
            >>>
            >>> service._forward_to_gateway = mock_forward
            >>> gateway = asyncio.run(service._find_resource_gateway(db, "file://data.csv"))
            >>> gateway.name
            'Gateway 2'

            >>> # Test resource not found
            >>> gateway = asyncio.run(service._find_resource_gateway(db, "file://missing.txt"))
            >>> gateway is None
            True

            >>> # Test with gateway errors
            >>> async def mock_with_error(db, gw_id, method, params=None):
            ...     if gw_id == 1:
            ...         raise Exception("Gateway unavailable")
            ...     else:
            ...         return [{"uri": "file://found.txt"}]
            >>>
            >>> service._forward_to_gateway = mock_with_error
            >>> gateway = asyncio.run(service._find_resource_gateway(db, "file://found.txt"))
            >>> gateway.name
            'Gateway 2'
        """
        # Get active gateways
        gateways = db.execute(select(DbGateway).where(DbGateway.enabled)).scalars().all()

        # Check each gateway
        for gateway in gateways:
            try:
                resources = await self._forward_to_gateway(db, gateway.id, "resources/list")
                for resource in resources:
                    if resource.get("uri") == uri:
                        return gateway
            except Exception as e:
                logger.error(f"Failed to check gateway {gateway.name} for resource {uri}: {str(e)}")
                continue

        return None

    def _check_rate_limit(self, gateway_url: str) -> bool:
        """Check if gateway request is within rate limits.

        Implements a sliding window rate limiter that tracks requests
        per gateway URL over the last 60 seconds. Automatically cleans
        expired entries from the request history.

        Args:
            gateway_url: Gateway URL to check rate limit for

        Returns:
            True if request is allowed, False if rate limit exceeded

        Examples:
            >>> from datetime import datetime, timezone, timedelta
            >>> from unittest.mock import patch
            >>>
            >>> # Test within rate limit
            >>> service = ForwardingService()
            >>> service._request_history = {}
            >>>
            >>> # First request always allowed
            >>> service._check_rate_limit("http://gateway1.com")
            True
            >>> len(service._request_history["http://gateway1.com"])
            1

            >>> # Multiple requests within limit
            >>> for _ in range(3):
            ...     allowed = service._check_rate_limit("http://gateway1.com")
            >>> allowed
            True
            >>> len(service._request_history["http://gateway1.com"])
            4

            >>> # Test rate limit exceeded
            >>> # Assuming settings.tool_rate_limit = 10
            >>> service._request_history["http://gateway2.com"] = [
            ...     datetime.now(timezone.utc) - timedelta(seconds=i)
            ...     for i in range(10)
            ... ]
            >>> with patch('mcpgateway.config.settings.tool_rate_limit', 10):
            ...     service._check_rate_limit("http://gateway2.com")
            False

            >>> # Test old entries cleanup (older than 60 seconds)
            >>> old_time = datetime.now(timezone.utc) - timedelta(seconds=61)
            >>> recent_time = datetime.now(timezone.utc) - timedelta(seconds=30)
            >>> service._request_history["http://gateway3.com"] = [old_time, old_time, recent_time]
            >>> service._check_rate_limit("http://gateway3.com")
            True
            >>> # Old entries removed, only recent + new one remain
            >>> len(service._request_history["http://gateway3.com"])
            2
        """
        now = datetime.now(timezone.utc)

        # Clean old history
        self._request_history[gateway_url] = [t for t in self._request_history.get(gateway_url, []) if (now - t).total_seconds() < 60]

        # Check limit
        if len(self._request_history[gateway_url]) >= settings.tool_rate_limit:
            return False

        # Record request
        self._request_history[gateway_url].append(now)
        return True

    def _get_auth_headers(self) -> Dict[str, str]:
        """Get headers for gateway authentication.

        Constructs authentication headers using configured credentials.
        Includes both Basic auth and API key headers for compatibility
        with different gateway authentication schemes.

        Returns:
            Dictionary containing Authorization and X-API-Key headers

        Examples:
            >>> from unittest.mock import patch
            >>>
            >>> service = ForwardingService()
            >>>
            >>> # Test header generation
            >>> with patch('mcpgateway.config.settings.basic_auth_user', 'testuser'):
            ...     with patch('mcpgateway.config.settings.basic_auth_password', 'testpass'):
            ...         headers = service._get_auth_headers()
            >>>
            >>> headers["Authorization"]
            'Basic testuser:testpass'
            >>> headers["X-API-Key"]
            'testuser:testpass'
            >>> len(headers)
            2

            >>> # Test with different credentials
            >>> with patch('mcpgateway.config.settings.basic_auth_user', 'admin'):
            ...     with patch('mcpgateway.config.settings.basic_auth_password', 'secret123'):
            ...         headers = service._get_auth_headers()
            >>> headers["X-API-Key"]
            'admin:secret123'
        """
        api_key = f"{settings.basic_auth_user}:{settings.basic_auth_password}"
        return {"Authorization": f"Basic {api_key}", "X-API-Key": api_key}
