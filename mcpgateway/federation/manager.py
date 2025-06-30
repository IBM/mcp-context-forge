# -*- coding: utf-8 -*-
"""Federation Manager.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

This module provides the core federation management system for the MCP Gateway.
It coordinates:
- Gateway discovery and registration
- Capability synchronization
- Request forwarding
- Health monitoring

The federation manager serves as the central point for all federation-related
operations, coordinating with discovery, sync and forwarding components.
"""

# Standard
import asyncio
from datetime import datetime, timedelta, timezone
import logging
import os
from typing import Any, Dict, List, Optional, Set

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import Tool as DbTool
from mcpgateway.federation.discovery import DiscoveryService
from mcpgateway.types import (
    ClientCapabilities,
    Implementation,
    InitializeRequest,
    InitializeResult,
    Prompt,
    Resource,
    ServerCapabilities,
    Tool,
)

# Third-Party
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = os.getenv("PROTOCOL_VERSION", "2025-03-26")


class FederationError(Exception):
    """Base class for federation-related errors."""


class FederationManager:
    """Manages federation across MCP gateways.

    Coordinates:
    - Peer discovery and registration
    - Capability synchronization
    - Request forwarding
    - Health monitoring
    """

    def __init__(self):
        """Initialize federation manager."""
        self._discovery = DiscoveryService()
        self._http_client = httpx.AsyncClient(timeout=settings.federation_timeout, verify=not settings.skip_ssl_verify)

        # Track active gateways
        self._active_gateways: Set[str] = set()

        # Background tasks
        self._sync_task: Optional[asyncio.Task] = None
        self._health_task: Optional[asyncio.Task] = None

    async def start(self, db: Session) -> None:
        """Start federation system.

        Args:
            db: Database session

        Raises:
            Exception: If unable to start federation manager
        """
        if not settings.federation_enabled:
            logger.info("Federation disabled by configuration")
            return

        try:
            # Start discovery
            await self._discovery.start()

            # Load existing gateways
            gateways = db.execute(select(DbGateway).where(DbGateway.is_active)).scalars().all()

            for gateway in gateways:
                self._active_gateways.add(gateway.url)

            # Start background tasks
            self._sync_task = asyncio.create_task(self._run_sync_loop(db))
            self._health_task = asyncio.create_task(self._run_health_loop(db))

            logger.info("Federation manager started")

        except Exception as e:
            logger.error(f"Failed to start federation manager: {e}")
            await self.stop()
            raise

    async def stop(self) -> None:
        """Stop federation system."""
        # Stop background tasks
        if self._sync_task:
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass

        if self._health_task:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass

        # Stop discovery
        await self._discovery.stop()

        # Close HTTP client
        await self._http_client.aclose()

        logger.info("Federation manager stopped")

    async def register_gateway(self, db: Session, url: str, name: Optional[str] = None) -> DbGateway:
        """Register a new gateway.

        Args:
            db: Database session
            url: Gateway URL
            name: Optional gateway name

        Returns:
            Registered gateway record

        Raises:
            FederationError: If registration fails
        """
        try:
            # Initialize connection
            capabilities = await self._initialize_gateway(url)
            gateway_name = name or f"Gateway-{len(self._active_gateways) + 1}"

            # Create gateway record
            gateway = DbGateway(
                name=gateway_name,
                url=url,
                capabilities=capabilities,
                last_seen=datetime.now(timezone.utc),
            )
            db.add(gateway)
            db.commit()
            db.refresh(gateway)

            # Update tracking
            self._active_gateways.add(url)

            # Add to discovery
            await self._discovery.add_peer(url, source="manual", name=gateway_name)

            logger.info(f"Registered gateway: {gateway_name} ({url})")
            return gateway

        except Exception as e:
            db.rollback()
            raise FederationError(f"Failed to register gateway: {str(e)}")

    async def unregister_gateway(self, db: Session, gateway_id: str) -> None:
        """Unregister a gateway.

        Args:
            db: Database session
            gateway_id: Gateway ID to unregister

        Raises:
            FederationError: If unregistration fails
        """
        try:
            # Find gateway
            gateway = db.get(DbGateway, gateway_id)
            if not gateway:
                raise FederationError(f"Gateway not found: {gateway_id}")

            # Remove gateway
            gateway.is_active = False
            gateway.updated_at = datetime.now(timezone.utc)

            # Remove associated tools
            db.execute(select(DbTool).where(DbTool.gateway_id == gateway_id)).delete()

            db.commit()

            # Update tracking
            self._active_gateways.discard(gateway.url)

            # Remove from discovery
            await self._discovery.remove_peer(gateway.url)

            logger.info(f"Unregistered gateway: {gateway.name}")

        except Exception as e:
            db.rollback()
            raise FederationError(f"Failed to unregister gateway: {str(e)}")

    async def get_gateway_tools(self, db: Session, gateway_id: str) -> List[Tool]:
        """Get tools provided by a gateway.

        Args:
            db: Database session
            gateway_id: Gateway ID

        Returns:
            List of gateway tools

        Raises:
            FederationError: If tool list cannot be retrieved
        """
        gateway = db.get(DbGateway, gateway_id)
        if not gateway or not gateway.is_active:
            raise FederationError(f"Gateway not found: {gateway_id}")

        try:
            # Get tool list
            tools = await self.forward_request(gateway, "tools/list")
            return [Tool.parse_obj(t) for t in tools]

        except Exception as e:
            raise FederationError(f"Failed to get tools from {gateway.name}: {str(e)}")

    async def get_gateway_resources(self, db: Session, gateway_id: str) -> List[Resource]:
        """Get resources provided by a gateway.

        Args:
            db: Database session
            gateway_id: Gateway ID

        Returns:
            List of gateway resources

        Raises:
            FederationError: If resource list cannot be retrieved
        """
        gateway = db.get(DbGateway, gateway_id)
        if not gateway or not gateway.is_active:
            raise FederationError(f"Gateway not found: {gateway_id}")

        try:
            # Get resource list
            resources = await self.forward_request(gateway, "resources/list")
            return [Resource.parse_obj(r) for r in resources]

        except Exception as e:
            raise FederationError(f"Failed to get resources from {gateway.name}: {str(e)}")

    async def get_gateway_prompts(self, db: Session, gateway_id: str) -> List[Prompt]:
        """Get prompts provided by a gateway.

        Args:
            db: Database session
            gateway_id: Gateway ID

        Returns:
            List of gateway prompts

        Raises:
            FederationError: If prompt list cannot be retrieved
        """
        gateway = db.get(DbGateway, gateway_id)
        if not gateway or not gateway.is_active:
            raise FederationError(f"Gateway not found: {gateway_id}")

        try:
            # Get prompt list
            prompts = await self.forward_request(gateway, "prompts/list")
            return [Prompt.parse_obj(p) for p in prompts]

        except Exception as e:
            raise FederationError(f"Failed to get prompts from {gateway.name}: {str(e)}")

    async def forward_request(self, gateway: DbGateway, method: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Forward a request to a gateway.

        Args:
            gateway: Gateway to forward to
            method: RPC method name
            params: Optional method parameters

        Returns:
            Gateway response

        Raises:
            FederationError: If request forwarding fails
        """
        try:
            # Build request
            request = {"jsonrpc": "2.0", "id": 1, "method": method}
            if params:
                request["params"] = params

            # Send request using the persistent client directly
            response = await self._http_client.post(f"{gateway.url}/rpc", json=request, headers=self._get_auth_headers())
            response.raise_for_status()
            result = response.json()

            # Update last seen
            gateway.last_seen = datetime.now(timezone.utc)

            # Handle response
            if "error" in result:
                raise FederationError(f"Gateway error: {result['error'].get('message')}")
            return result.get("result")

        except Exception as e:
            raise FederationError(f"Failed to forward request to {gateway.name}: {str(e)}")

    async def _run_sync_loop(self, db: Session) -> None:
        """
        Run periodic gateway synchronization.

        Args:
            db: Session object
        """
        while True:
            try:
                # Process discovered peers
                discovered = self._discovery.get_discovered_peers()
                for peer in discovered:
                    if peer.url not in self._active_gateways:
                        try:
                            await self.register_gateway(db, peer.url, peer.name)
                        except Exception as e:
                            logger.warning(f"Failed to register discovered peer {peer.url}: {e}")

                # Sync active gateways
                gateways = db.execute(select(DbGateway).where(DbGateway.is_active)).scalars().all()

                for gateway in gateways:
                    try:
                        # Update capabilities
                        capabilities = await self._initialize_gateway(gateway.url)
                        gateway.capabilities = capabilities
                        gateway.last_seen = datetime.now(timezone.utc)
                        gateway.is_active = True

                    except Exception as e:
                        logger.warning(f"Failed to sync gateway {gateway.name}: {e}")

                db.commit()

            except Exception as e:
                logger.error(f"Sync loop error: {e}")
                db.rollback()

            await asyncio.sleep(settings.federation_sync_interval)

    async def _run_health_loop(self, db: Session) -> None:
        """
        Run periodic gateway health checks.

        Args:
            db: Session object
        """
        while True:
            try:
                gateways = db.execute(select(DbGateway).where(DbGateway.is_active)).scalars().all()

                for gateway in gateways:
                    try:
                        # Check gateway health
                        await self._check_gateway_health(gateway)
                    except Exception as e:
                        logger.warning(f"Health check failed for {gateway.name}: {e}")
                        # Mark inactive if not seen recently
                        if datetime.now(timezone.utc) - gateway.last_seen > timedelta(minutes=5):
                            gateway.is_active = False
                            self._active_gateways.discard(gateway.url)

                db.commit()

            except Exception as e:
                logger.error(f"Health check error: {e}")
                db.rollback()

            await asyncio.sleep(settings.health_check_interval)

    async def _initialize_gateway(self, url: str) -> ServerCapabilities:
        """Initialize connection to a gateway.

        Args:
            url: Gateway URL

        Returns:
            Gateway capabilities

        Raises:
            FederationError: If initialization fails
        """
        try:
            # Build initialize request
            request = InitializeRequest(
                protocol_version=PROTOCOL_VERSION,
                capabilities=ClientCapabilities(roots={"listChanged": True}, sampling={}),
                client_info=Implementation(name=settings.app_name, version="1.0.0"),
            )

            # Send request using the persistent client directly
            response = await self._http_client.post(
                f"{url}/initialize",
                json=request.dict(),
                headers=self._get_auth_headers(),
            )
            response.raise_for_status()
            result = InitializeResult.parse_obj(response.json())

            # Verify protocol version
            if result.protocol_version != PROTOCOL_VERSION:
                raise FederationError(f"Unsupported protocol version: {result.protocol_version}")

            return result.capabilities

        except Exception as e:
            raise FederationError(f"Failed to initialize gateway: {str(e)}")

    async def _check_gateway_health(self, gateway: DbGateway) -> bool:
        """Check if a gateway is healthy.

        Args:
            gateway: Gateway to check

        Returns:
            True if gateway is healthy

        Raises:
            FederationError: If health check fails
        """
        try:
            await self._initialize_gateway(gateway.url)
            return True
        except Exception as e:
            raise FederationError(f"Gateway health check failed: {str(e)}")

    def _get_auth_headers(self) -> Dict[str, str]:
        """
        Get headers for gateway authentication.

        Returns:
            dict: Headers to be used in request
        """
        api_key = f"{settings.basic_auth_user}:{settings.basic_auth_password}"
        return {"Authorization": f"Basic {api_key}", "X-API-Key": api_key}
