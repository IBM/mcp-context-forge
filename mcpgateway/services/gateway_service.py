# -*- coding: utf-8 -*-
"""Gateway Service Implementation.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

This module implements gateway federation according to the MCP specification.
It handles:
- Gateway discovery and registration
- Request forwarding
- Capability aggregation
- Health monitoring
- Active/inactive gateway management
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Optional, Set

import httpx
from mcp import ClientSession
from mcp.client.sse import sse_client
from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from mcpgateway.config import settings
from mcpgateway.db import Gateway as DbGateway, AsyncSessionLocal
from mcpgateway.db import Tool as DbTool
from mcpgateway.schemas import GatewayCreate, GatewayRead, GatewayUpdate, ToolCreate
from mcpgateway.services.tool_service import ToolService, ToolRead, ToolNameConflictError, ToolError
from mcpgateway.utils.services_auth import decode_auth

logger = logging.getLogger(__name__)


class GatewayError(Exception):
    """Base class for gateway-related errors."""


class GatewayNotFoundError(GatewayError):
    """Raised when a requested gateway is not found."""


class GatewayNameConflictError(GatewayError):
    """Raised when a gateway name conflicts with existing (active or inactive) gateway."""

    def __init__(self, name: str, is_active: bool = True, gateway_id: Optional[int] = None):
        """Initialize the error with gateway information.

        Args:
            name: The conflicting gateway name
            is_active: Whether the existing gateway is active
            gateway_id: ID of the existing gateway if available
        """
        self.name = name
        self.is_active = is_active
        self.gateway_id = gateway_id
        message = f"Gateway already exists with name: {name}"
        if not is_active:
            message += f" (currently inactive, ID: {gateway_id})"
        super().__init__(message)


class GatewayConnectionError(GatewayError):
    """Raised when gateway connection fails."""


class GatewayService:
    """Service for managing federated gateways.

    Handles:
    - Gateway registration and health checks
    - Request forwarding
    - Capability negotiation
    - Federation events
    - Active/inactive status management
    """

    def __init__(self):
        """Initialize the gateway service."""
        self._event_subscribers: List[asyncio.Queue] = []
        self._http_client = httpx.AsyncClient(timeout=settings.federation_timeout, verify=not settings.skip_ssl_verify)
        self._health_check_interval = 60  # seconds
        self._health_check_task: Optional[asyncio.Task] = None
        self._active_gateways: Set[str] = set()  # Track active gateway URLs
        self._stream_response = None
        self._pending_responses = {}
        self.tool_service = ToolService()

    async def initialize(self) -> None:
        """Initialize the service."""
        logger.info("Initializing gateway service")
        self._health_check_task = asyncio.create_task(self._run_health_checks())

    async def shutdown(self) -> None:
        """Shutdown the service."""
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass

        await self._http_client.aclose()
        self._event_subscribers.clear()
        self._active_gateways.clear()
        logger.info("Gateway service shutdown complete")

    async def register_tool(self, db: AsyncSession, tool: ToolCreate) -> ToolRead:
        """Register a new tool.

        Args:
            db: Database session.
            tool: Tool creation schema.

        Returns:
            Created tool information.

        Raises:
            ToolNameConflictError: If tool name already exists.
            ToolError: For other tool registration errors.
        """
        try:
            stmt = (
                select(DbTool)
                .where(DbTool.name == tool.name)
                .options(
                    selectinload(DbTool.gateway),
                    selectinload(DbTool.servers),
                    selectinload(DbTool.federated_with),
                    selectinload(DbTool.metrics),
                )
            )
            result = await db.execute(stmt)
            existing_tool = result.scalar_one_or_none()
            if existing_tool:
                raise ToolNameConflictError(
                    tool.name,
                    is_active=existing_tool.is_active,
                    tool_id=existing_tool.id,
                )

            if tool.auth is None:
                auth_type = None
                auth_value = None
            else:
                auth_type = tool.auth.auth_type
                auth_value = tool.auth.auth_value

            db_tool = DbTool(
                name=tool.name,
                url=str(tool.url),
                description=tool.description,
                integration_type=tool.integration_type,
                request_type=tool.request_type,
                headers=tool.headers,
                input_schema=tool.input_schema,
                jsonpath_filter=tool.jsonpath_filter,
                auth_type=auth_type,
                auth_value=auth_value,
                gateway_id=tool.gateway_id,
            )
            db.add(db_tool)
            await self.tool_service._notify_tool_added(db_tool)
            logger.info(f"Registered tool: {tool.name}")
            return db_tool
        except IntegrityError:
            await db.rollback()
            raise ToolError(f"Tool already exists: {tool.name}")
        except Exception as e:
            await db.rollback()
            raise ToolError(f"Failed to register tool: {str(e)}")

    async def register_gateway(self, db: AsyncSession, gateway: GatewayCreate) -> GatewayRead:
        """Register a new gateway.

        Args:
            db: Database session
            gateway: Gateway creation schema

        Returns:
            Created gateway information

        Raises:
            GatewayNameConflictError: If gateway name already exists
            GatewayError: If registration fails
        """
        try:
            # Check for name conflicts (both active and inactive)
            stmt = (
                select(DbGateway)
                .where(DbGateway.name == gateway.name)
                .options(
                    selectinload(DbGateway.tools),
                    selectinload(DbGateway.prompts),
                    selectinload(DbGateway.resources),
                    selectinload(DbGateway.federated_tools),
                    selectinload(DbGateway.federated_resources),
                    selectinload(DbGateway.federated_prompts),
                )
            )
            result = await db.execute(stmt)
            existing_gateway = result.scalar_one_or_none()

            if existing_gateway:
                raise GatewayNameConflictError(
                    gateway.name,
                    is_active=existing_gateway.is_active,
                    gateway_id=existing_gateway.id,
                )

            auth_type = getattr(gateway, "auth_type", None)
            auth_value = getattr(gateway, "auth_value", {})

            # Initialize connection and get capabilities
            capabilities, tools = await self._initialize_gateway(str(gateway.url), auth_value)

            # Create DB model
            db_gateway = DbGateway(
                name=gateway.name, url=str(gateway.url), description=gateway.description, capabilities=capabilities, last_seen=datetime.utcnow(), auth_type=auth_type, auth_value=auth_value
            )

            # Add to DB
            db.add(db_gateway)
            await db.flush()
            await db.refresh(db_gateway)

            # Update tracking
            self._active_gateways.add(gateway.url)

            # Notify subscribers
            await self._notify_gateway_added(db_gateway)

            stmt = (
                select(DbGateway)
                .where(DbGateway.name == gateway.name)
                .options(
                    selectinload(DbGateway.tools),
                    selectinload(DbGateway.prompts),
                    selectinload(DbGateway.resources),
                    selectinload(DbGateway.federated_tools),
                    selectinload(DbGateway.federated_resources),
                    selectinload(DbGateway.federated_prompts),
                )
            )
            result = await db.execute(stmt)
            inserted_gateway = result.scalar_one_or_none()

            inserted_gateway_id = inserted_gateway.id

            logger.info(f"Registering {len(tools)} tools for gateway: {gateway.name}")

            for tool in tools:
                tool.gateway_id = inserted_gateway_id

            tool_registration_tasks = [
                self.register_tool(db=db, tool=tool) for tool in tools
            ]

            db_tools = []
            if tool_registration_tasks:
                db_tools = await asyncio.gather(*tool_registration_tasks)

            await db.commit()

            if len(db_tools) > 0:
                for db_tool in db_tools:
                    await db.refresh(db_tool, attribute_names=['servers', 'metrics', 'gateway', 'federated_with'])
                    self.tool_service._convert_tool_to_read(db_tool)

            await db.refresh(db_gateway)

            return GatewayRead.model_validate(db_gateway)

        except IntegrityError:
            await db.rollback()
            raise GatewayError(f"Gateway already exists: {gateway.name}")
        except Exception as e:
            await db.rollback()
            raise GatewayError(f"Failed to register gateway: {str(e)}")

    async def list_gateways(self, db: AsyncSession, include_inactive: bool = False) -> List[GatewayRead]:
        """List all registered gateways.

        Args:
            db: Database session
            include_inactive: Whether to include inactive gateways

        Returns:
            List of registered gateways
        """
        query = select(DbGateway)
        query = query.options(
            selectinload(DbGateway.tools),
            selectinload(DbGateway.prompts),
            selectinload(DbGateway.resources),
            selectinload(DbGateway.federated_tools),
            selectinload(DbGateway.federated_resources),
            selectinload(DbGateway.federated_prompts),
        )
        if not include_inactive:
            query = query.where(DbGateway.is_active)

        result = await db.execute(query)
        gateways = result.scalars().all()
        return [GatewayRead.model_validate(g) for g in gateways]

    async def update_gateway(self, db: AsyncSession, gateway_id: int, gateway_update: GatewayUpdate) -> GatewayRead:
        """Update a gateway.

        Args:
            db: Database session
            gateway_id: Gateway ID to update
            gateway_update: Updated gateway data

        Returns:
            Updated gateway information

        Raises:
            GatewayNotFoundError: If gateway not found
            GatewayError: For other update errors
            GatewayNameConflictError: If gateway name conflict occurs
        """
        try:
            # Find gateway
            gateway = await db.get(DbGateway, gateway_id)
            if not gateway:
                raise GatewayNotFoundError(f"Gateway not found: {gateway_id}")

            if not gateway.is_active:
                raise GatewayNotFoundError(f"Gateway '{gateway.name}' exists but is inactive")

            # Check for name conflicts if name is being changed
            if gateway_update.name is not None and gateway_update.name != gateway.name:
                result = await db.execute(select(DbGateway).where(DbGateway.name == gateway_update.name).where(DbGateway.id != gateway_id))
                existing_gateway = result.scalar_one_or_none()

                if existing_gateway:
                    raise GatewayNameConflictError(
                        gateway_update.name,
                        is_active=existing_gateway.is_active,
                        gateway_id=existing_gateway.id,
                    )

            # Update fields if provided
            if gateway_update.name is not None:
                gateway.name = gateway_update.name
            if gateway_update.url is not None:
                gateway.url = str(gateway_update.url)
            if gateway_update.description is not None:
                gateway.description = gateway_update.description

            if getattr(gateway, "auth_type", None) is not None:
                gateway.auth_type = gateway_update.auth_type

                # if auth_type is not None and only then check auth_value
                if getattr(gateway, "auth_value", {}) != {}:
                    gateway.auth_value = gateway_update.auth_value

            # Try to reinitialize connection if URL changed
            if gateway_update.url is not None:
                try:
                    capabilities, _ = await self._initialize_gateway(gateway.url, gateway.auth_value)
                    gateway.capabilities = capabilities
                    gateway.last_seen = datetime.utcnow()

                    # Update tracking with new URL
                    self._active_gateways.discard(gateway.url)
                    self._active_gateways.add(gateway.url)
                except Exception as e:
                    logger.warning(f"Failed to initialize updated gateway: {e}")

            gateway.updated_at = datetime.utcnow()
            await db.commit()
            await db.refresh(gateway)

            # Notify subscribers
            await self._notify_gateway_updated(gateway)

            logger.info(f"Updated gateway: {gateway.name}")
            return GatewayRead.model_validate(gateway)

        except Exception as e:
            await db.rollback()
            raise GatewayError(f"Failed to update gateway: {str(e)}")

    async def get_gateway(self, db: AsyncSession, gateway_id: int, include_inactive: bool = False) -> GatewayRead:
        """Get a specific gateway by ID.

        Args:
            db: Database session
            gateway_id: Gateway ID
            include_inactive: Whether to include inactive gateways

        Returns:
            Gateway information

        Raises:
            GatewayNotFoundError: If gateway not found
        """
        gateway = await db.get(DbGateway, gateway_id)
        if not gateway:
            raise GatewayNotFoundError(f"Gateway not found: {gateway_id}")

        if not gateway.is_active and not include_inactive:
            raise GatewayNotFoundError(f"Gateway '{gateway.name}' exists but is inactive")

        return GatewayRead.model_validate(gateway)

    async def toggle_gateway_status(self, db: AsyncSession, gateway_id: int, activate: bool) -> GatewayRead:
        """Toggle gateway active status.

        Args:
            db: Database session
            gateway_id: Gateway ID to toggle
            activate: True to activate, False to deactivate

        Returns:
            Updated gateway information

        Raises:
            GatewayNotFoundError: If gateway not found
            GatewayError: For other errors
        """
        try:
            gateway = await db.get(DbGateway, gateway_id)
            if not gateway:
                raise GatewayNotFoundError(f"Gateway not found: {gateway_id}")

            # Update status if it's different
            if gateway.is_active != activate:
                gateway.is_active = activate
                gateway.updated_at = datetime.utcnow()

                # Update tracking
                if activate:
                    self._active_gateways.add(gateway.url)
                    # Try to initialize if activating
                    try:
                        capabilities, tools = await self._initialize_gateway(gateway.url, gateway.auth_value)
                        gateway.capabilities = capabilities.dict()
                        gateway.last_seen = datetime.utcnow()
                    except Exception as e:
                        logger.warning(f"Failed to initialize reactivated gateway: {e}")
                else:
                    self._active_gateways.discard(gateway.url)

                await db.commit()
                await db.refresh(gateway)

                result = await db.query(DbTool).filter(DbTool.gateway_id == gateway_id)
                tools = result.all()
                for tool in tools:
                    await self.tool_service.toggle_tool_status(db, tool.id, activate)

                # Notify subscribers
                if activate:
                    await self._notify_gateway_activated(gateway)
                else:
                    await self._notify_gateway_deactivated(gateway)

                logger.info(f"Gateway {gateway.name} {'activated' if activate else 'deactivated'}")

            return GatewayRead.model_validate(gateway)

        except Exception as e:
            await db.rollback()
            raise GatewayError(f"Failed to toggle gateway status: {str(e)}")

    async def _notify_gateway_updated(self, gateway: DbGateway) -> None:
        """
        Notify subscribers of gateway update.

        Args:
            gateway: Gateway to update
        """
        event = {
            "type": "gateway_updated",
            "data": {
                "id": gateway.id,
                "name": gateway.name,
                "url": gateway.url,
                "description": gateway.description,
                "is_active": gateway.is_active,
            },
            "timestamp": datetime.utcnow().isoformat(),
        }
        await self._publish_event(event)

    async def delete_gateway(self, db: AsyncSession, gateway_id: int) -> None:
        """Permanently delete a gateway.

        Args:
            db: Database session
            gateway_id: Gateway ID to delete

        Raises:
            GatewayNotFoundError: If gateway not found
            GatewayError: For other deletion errors
        """
        try:
            # Find gateway
            gateway = await db.get(DbGateway, gateway_id)
            if not gateway:
                raise GatewayNotFoundError(f"Gateway not found: {gateway_id}")

            # Store gateway info for notification before deletion
            gateway_id = gateway.id
            gateway_name = gateway.name
            gateway_url = gateway.url
            gateway_info = {"id": gateway_id, "name": gateway_name, "url": gateway_url}

            # Remove associated tools
            try:
                tool_delete_stmt = delete(DbTool).where(DbTool.gateway_id == gateway_id)
                await db.execute(tool_delete_stmt)
                logger.info(f"Deleted tools associated with gateway: {gateway.name}")
            except Exception as ex:
                logger.error(f"Error deleting tools: {ex}")
                raise ex

            # Hard delete gateway
            gateway_delete_stmt = delete(DbGateway).where(DbGateway.id == gateway_id)
            await db.execute(gateway_delete_stmt)

            # Update tracking
            self._active_gateways.discard(gateway_url)

            # Notify subscribers
            await self._notify_gateway_deleted(gateway_info)

            await db.commit()
            logger.info(f"Permanently deleted gateway: {gateway_name}")

        except Exception as e:
            await db.rollback()
            raise GatewayError(f"Failed to delete gateway: {str(e)}")

    async def forward_request(self, gateway: DbGateway, method: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Forward a request to a gateway.

        Args:
            gateway: Gateway to forward to
            method: RPC method name
            params: Optional method parameters

        Returns:
            Gateway response

        Raises:
            GatewayConnectionError: If forwarding fails
            GatewayError: If gateway gave an error
        """
        if not gateway.is_active:
            raise GatewayConnectionError(f"Cannot forward request to inactive gateway: {gateway.name}")

        try:
            # Build RPC request
            request = {"jsonrpc": "2.0", "id": 1, "method": method}
            if params:
                request["params"] = params

            # Directly use the persistent HTTP client (no async with)
            response = await self._http_client.post(f"{gateway.url}/rpc", json=request, headers=self._get_auth_headers())
            response.raise_for_status()
            result = response.json()

            # Update last seen timestamp
            gateway.last_seen = datetime.utcnow()

            if "error" in result:
                raise GatewayError(f"Gateway error: {result['error'].get('message')}")
            return result.get("result")

        except Exception as e:
            raise GatewayConnectionError(f"Failed to forward request to {gateway.name}: {str(e)}")

    async def check_gateway_health(self, gateway: DbGateway) -> bool:
        """Check if a gateway is healthy.

        Args:
            gateway: Gateway to check

        Returns:
            True if gateway is healthy
        """
        if not gateway.is_active:
            return False

        try:
            # Try to initialize connection
            await self._initialize_gateway(gateway.url, gateway.auth_value)

            # Update last seen
            gateway.last_seen = datetime.utcnow()
            return True

        except Exception:
            return False

    async def aggregate_capabilities(self, db: AsyncSession) -> Dict[str, Any]:
        """Aggregate capabilities from all gateways.

        Args:
            db: Database session

        Returns:
            Combined capabilities
        """
        capabilities = {
            "prompts": {"listChanged": True},
            "resources": {"subscribe": True, "listChanged": True},
            "tools": {"listChanged": True},
            "logging": {},
        }

        # Get all active gateways
        result = await db.execute(select(DbGateway).where(DbGateway.is_active))
        gateways = result.scalars().all()

        # Combine capabilities
        for gateway in gateways:
            if gateway.capabilities:
                for key, value in gateway.capabilities.items():
                    if key not in capabilities:
                        capabilities[key] = value
                    elif isinstance(value, dict):
                        capabilities[key].update(value)

        return capabilities

    async def subscribe_events(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Subscribe to gateway events.

        Yields:
            Gateway event messages
        """
        queue: asyncio.Queue = asyncio.Queue()
        self._event_subscribers.append(queue)
        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            self._event_subscribers.remove(queue)

    async def _initialize_gateway(self, url: str, authentication: Optional[Dict[str, str]] = None) -> Any:
        """Initialize connection to a gateway and retrieve its capabilities.

        Args:
            url: Gateway URL
            authentication: Optional authentication headers

        Returns:
            Capabilities dictionary as provided by the gateway.

        Raises:
            GatewayConnectionError: If initialization fails.
        """
        try:
            if authentication is None:
                authentication = {}

            async def connect_to_sse_server(server_url: str, authentication: Optional[Dict[str, str]] = None):
                """
                Connect to an MCP server running with SSE transport

                Args:
                    server_url: URL to connect to the server
                    authentication: Authentication headers for connection to URL

                Returns:
                    list, list: List of capabilities and tools
                """
                # Store the context managers so they stay alive
                decoded_auth = decode_auth(authentication)

                # Use async with for both sse_client and ClientSession
                async with sse_client(url=server_url, headers=decoded_auth) as streams:
                    async with ClientSession(*streams) as session:
                        # Initialize the session
                        response = await session.initialize()
                        capabilities = response.capabilities.model_dump(by_alias=True, exclude_none=True)

                        response = await session.list_tools()
                        tools = response.tools
                        tools = [tool.model_dump(by_alias=True, exclude_none=True) for tool in tools]
                        tools = [ToolCreate.model_validate(tool) for tool in tools]

                return capabilities, tools
            
            if authentication is None:
                authentication = {}

            capabilities, tools = await connect_to_sse_server(url, authentication)

            return capabilities, tools
        except Exception as e:
            raise GatewayConnectionError(f"Failed to initialize gateway at {url}: {str(e)}")

    async def _run_health_checks(self) -> None:
        """Run periodic health checks on all gateways."""
        while True:
            try:
                async with AsyncSessionLocal() as db:
                    # Get active gateways
                    result = await db.execute(select(DbGateway).where(DbGateway.is_active))
                    gateways = result.scalars().all()

                    # Check each gateway
                    for gateway in gateways:
                        try:
                            is_healthy = await self.check_gateway_health(gateway)
                            if not is_healthy:
                                logger.warning(f"Gateway {gateway.name} is unhealthy")
                        except Exception as e:
                            logger.error(f"Health check failed for {gateway.name}: {str(e)}")

                    await db.commit()

            except Exception as e:
                logger.error(f"Health check run failed: {str(e)}")

            # Wait for next check
            await asyncio.sleep(self._health_check_interval)

    def _get_auth_headers(self) -> Dict[str, str]:
        """
        Get headers for gateway authentication.

        Returns:
            dict: Authorization header dict
        """
        api_key = f"{settings.basic_auth_user}:{settings.basic_auth_password}"
        return {"Authorization": f"Basic {api_key}", "X-API-Key": api_key, "Content-Type": "application/json"}

    async def _notify_gateway_added(self, gateway: DbGateway) -> None:
        """
        Notify subscribers of gateway addition.

        Args:
            gateway: Gateway to add
        """
        event = {
            "type": "gateway_added",
            "data": {
                "id": gateway.id,
                "name": gateway.name,
                "url": gateway.url,
                "description": gateway.description,
                "is_active": gateway.is_active,
            },
            "timestamp": datetime.utcnow().isoformat(),
        }
        await self._publish_event(event)

    async def _notify_gateway_activated(self, gateway: DbGateway) -> None:
        """
        Notify subscribers of gateway activation.

        Args:
            gateway: Gateway to activate
        """
        event = {
            "type": "gateway_activated",
            "data": {
                "id": gateway.id,
                "name": gateway.name,
                "url": gateway.url,
                "is_active": True,
            },
            "timestamp": datetime.utcnow().isoformat(),
        }
        await self._publish_event(event)

    async def _notify_gateway_deactivated(self, gateway: DbGateway) -> None:
        """
        Notify subscribers of gateway deactivation.

        Args:
            gateway: Gateway database object
        """
        event = {
            "type": "gateway_deactivated",
            "data": {
                "id": gateway.id,
                "name": gateway.name,
                "url": gateway.url,
                "is_active": False,
            },
            "timestamp": datetime.utcnow().isoformat(),
        }
        await self._publish_event(event)

    async def _notify_gateway_deleted(self, gateway_info: Dict[str, Any]) -> None:
        """
        Notify subscribers of gateway deletion.

        Args:
            gateway_info: Dict containing information about gateway to delete
        """
        event = {
            "type": "gateway_deleted",
            "data": gateway_info,
            "timestamp": datetime.utcnow().isoformat(),
        }
        await self._publish_event(event)

    async def _notify_gateway_removed(self, gateway: DbGateway) -> None:
        """
        Notify subscribers of gateway removal (deactivation).

        Args:
            gateway: Gateway to remove
        """
        event = {
            "type": "gateway_removed",
            "data": {"id": gateway.id, "name": gateway.name, "is_active": False},
            "timestamp": datetime.utcnow().isoformat(),
        }
        await self._publish_event(event)

    async def _publish_event(self, event: Dict[str, Any]) -> None:
        """
        Publish event to all subscribers.

        Args:
            event: event dictionary
        """
        for queue in self._event_subscribers:
            await queue.put(event)
