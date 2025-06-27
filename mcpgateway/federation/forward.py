# -*- coding: utf-8 -*-
"""Federation Request Forwarding.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

This module implements request forwarding for federated MCP Gateways.
It handles:
- Request routing to appropriate gateways
- Response aggregation
- Error handling and retry logic
- Request/response transformation
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from mcpgateway.config import settings
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import Tool as DbTool
from mcpgateway.types import ToolResult

logger = logging.getLogger(__name__)


class ForwardingError(Exception):
    """Base class for forwarding-related errors."""


class ForwardingService:
    """Service for handling request forwarding across gateways.

    Handles:
    - Request routing
    - Response aggregation
    - Error handling
    - Request transformation
    """

    def __init__(self):
        """Initialize forwarding service."""
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
    ) -> Any:
        """Forward a request to gateway(s).

        Args:
            db: Database session
            method: RPC method name
            params: Optional method parameters
            target_gateway_id: Optional specific gateway ID

        Returns:
            Forwarded response(s)

        Raises:
            ForwardingError: If forwarding fails
        """
        try:
            if target_gateway_id:
                # Forward to specific gateway
                return await self._forward_to_gateway(db, target_gateway_id, method, params)

            # Forward to all relevant gateways
            return await self._forward_to_all(db, method, params)

        except Exception as e:
            raise ForwardingError(f"Forward request failed: {str(e)}")

    async def forward_tool_request(self, db: Session, tool_name: str, arguments: Dict[str, Any]) -> ToolResult:
        """Forward a tool invocation request.

        Args:
            db: Database session
            tool_name: Tool to invoke
            arguments: Tool arguments

        Returns:
            Tool result

        Raises:
            ForwardingError: If forwarding fails
        """
        try:
            # Find tool
            tool = db.execute(select(DbTool).where(DbTool.name == tool_name).where(DbTool.is_active)).scalar_one_or_none()

            if not tool:
                raise ForwardingError(f"Tool not found: {tool_name}")

            if not tool.gateway_id:
                raise ForwardingError(f"Tool {tool_name} is not federated")

            # Forward to gateway
            result = await self._forward_to_gateway(
                db,
                tool.gateway_id,
                "tools/invoke",
                {"name": tool_name, "arguments": arguments},
            )

            # Parse result
            return ToolResult(
                content=result.get("content", []),
                is_error=result.get("is_error", False),
            )

        except Exception as e:
            raise ForwardingError(f"Failed to forward tool request: {str(e)}")

    async def forward_resource_request(self, db: Session, uri: str) -> Tuple[Union[str, bytes], str]:
        """Forward a resource read request.

        Args:
            db: Database session
            uri: Resource URI

        Returns:
            Tuple of (content, mime_type)

        Raises:
            ForwardingError: If forwarding fails
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

    async def _forward_to_gateway(
        self,
        db: Session,
        gateway_id: str,
        method: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Forward request to a specific gateway.

        Args:
            db: Database session
            gateway_id: Gateway to forward to
            method: RPC method name
            params: Optional method parameters

        Returns:
            Gateway response

        Raises:
            ForwardingError: If forwarding fails
            httpx.TimeoutException: If unable to connect after retries
        """
        # Get gateway
        gateway = db.get(DbGateway, gateway_id)
        if not gateway or not gateway.is_active:
            raise ForwardingError(f"Gateway not found: {gateway_id}")

        # Check rate limits
        if not self._check_rate_limit(gateway.url):
            raise ForwardingError("Rate limit exceeded")

        try:
            # Build request
            request = {"jsonrpc": "2.0", "id": 1, "method": method}
            if params:
                request["params"] = params

            # Send request with retries using the persistent client directly
            for attempt in range(settings.max_tool_retries):
                try:
                    response = await self._http_client.post(
                        f"{gateway.url}/rpc",
                        json=request,
                        headers=self._get_auth_headers(),
                    )
                    response.raise_for_status()
                    result = response.json()

                    # Update last seen
                    gateway.last_seen = datetime.utcnow()

                    # Handle response
                    if "error" in result:
                        raise ForwardingError(f"Gateway error: {result['error'].get('message')}")
                    return result.get("result")

                except httpx.TimeoutException:
                    if attempt == settings.max_tool_retries - 1:
                        raise
                    await asyncio.sleep(1 * (attempt + 1))

        except Exception as e:
            raise ForwardingError(f"Failed to forward to {gateway.name}: {str(e)}")

    async def _forward_to_all(self, db: Session, method: str, params: Optional[Dict[str, Any]] = None) -> List[Any]:
        """Forward request to all active gateways.

        Args:
            db: Database session
            method: RPC method name
            params: Optional method parameters

        Returns:
            List of responses

        Raises:
            ForwardingError: If all forwards fail
        """
        # Get active gateways
        gateways = db.execute(select(DbGateway).where(DbGateway.is_active)).scalars().all()

        # Forward to each gateway
        results = []
        errors = []

        for gateway in gateways:
            try:
                result = await self._forward_to_gateway(db, gateway.id, method, params)
                results.append(result)
            except Exception as e:
                errors.append(str(e))

        if not results and errors:
            raise ForwardingError(f"All forwards failed: {'; '.join(errors)}")

        return results

    async def _find_resource_gateway(self, db: Session, uri: str) -> Optional[DbGateway]:
        """Find gateway hosting a resource.

        Args:
            db: Database session
            uri: Resource URI

        Returns:
            Gateway record or None
        """
        # Get active gateways
        gateways = db.execute(select(DbGateway).where(DbGateway.is_active)).scalars().all()

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

        Args:
            gateway_url: Gateway URL

        Returns:
            True if request allowed
        """
        now = datetime.utcnow()

        # Clean old history
        self._request_history[gateway_url] = [t for t in self._request_history.get(gateway_url, []) if (now - t).total_seconds() < 60]

        # Check limit
        if len(self._request_history[gateway_url]) >= settings.tool_rate_limit:
            return False

        # Record request
        self._request_history[gateway_url].append(now)
        return True

    def _get_auth_headers(self) -> Dict[str, str]:
        """
        Get headers for gateway authentication.

        Returns:
            dict: Authorization header dict
        """
        api_key = f"{settings.basic_auth_user}:{settings.basic_auth_password}"
        return {"Authorization": f"Basic {api_key}", "X-API-Key": api_key}
