# -*- coding: utf-8 -*-
"""Federation Discovery Service.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

This module implements automatic peer discovery for MCP Gateways.
It supports multiple discovery mechanisms:
- DNS-SD service discovery
- Static peer lists
- Peer exchange protocol
- Manual registration
"""

# Standard
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import os
import socket
from typing import Dict, List, Optional
from urllib.parse import urlparse

# Third-Party
import httpx
from zeroconf import ServiceInfo, ServiceStateChange
from zeroconf.asyncio import AsyncServiceBrowser, AsyncZeroconf

# First-Party
from mcpgateway.config import settings
from mcpgateway.types import ServerCapabilities

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = os.getenv("PROTOCOL_VERSION", "2025-03-26")


@dataclass
class DiscoveredPeer:
    """Information about a discovered peer gateway."""

    url: str
    name: Optional[str]
    protocol_version: Optional[str]
    capabilities: Optional[ServerCapabilities]
    discovered_at: datetime
    last_seen: datetime
    source: str


class LocalDiscoveryService:
    """Super class for DiscoveryService"""

    def __init__(self):
        """Initialize local discovery service"""
        # Service info for local discovery
        self._service_type = "_mcp._tcp.local."
        self._service_info = ServiceInfo(
            self._service_type,
            f"{settings.app_name}.{self._service_type}",
            addresses=[socket.inet_aton(addr) for addr in self._get_local_addresses()],
            port=settings.port,
            properties={
                "name": settings.app_name,
                "version": "1.0.0",
                "protocol": PROTOCOL_VERSION,
            },
        )

    def _get_local_addresses(self) -> List[str]:
        """Get list of local network addresses.

        Returns:
            List of IP addresses
        """
        addresses = []
        try:
            # Get all network interfaces
            for iface in socket.getaddrinfo(socket.gethostname(), None):
                addr = iface[4][0]
                # Skip localhost
                if not addr.startswith("127."):
                    addresses.append(addr)
        except Exception as e:
            logger.warning(f"Failed to get local addresses: {e}")
            # Fall back to localhost
            addresses.append("127.0.0.1")

        return addresses or ["127.0.0.1"]


class DiscoveryService(LocalDiscoveryService):
    """Service for automatic gateway discovery.

    Supports multiple discovery mechanisms:
    - DNS-SD for local network discovery
    - Static peer lists from configuration
    - Peer exchange with known gateways
    - Manual registration via API
    """

    def __init__(self):
        """Initialize discovery service."""
        super().__init__()

        self._zeroconf: Optional[AsyncZeroconf] = None
        self._browser: Optional[AsyncServiceBrowser] = None
        self._http_client = httpx.AsyncClient(timeout=settings.federation_timeout, verify=not settings.skip_ssl_verify)

        # Track discovered peers
        self._discovered_peers: Dict[str, DiscoveredPeer] = {}

        # Start background tasks
        self._cleanup_task: Optional[asyncio.Task] = None
        self._refresh_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """
        Start discovery service.

        Raises:
            Exception: If unable to start discovery service
        """
        try:
            # Initialize DNS-SD
            if settings.federation_discovery:
                self._zeroconf = AsyncZeroconf()
                await self._zeroconf.async_register_service(self._service_info)
                self._browser = AsyncServiceBrowser(
                    self._zeroconf.zeroconf,
                    self._service_type,
                    handlers=[self._on_service_state_change],
                )

            # Start background tasks
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            self._refresh_task = asyncio.create_task(self._refresh_loop())

            # Load static peers
            for peer_url in settings.federation_peers:
                await self.add_peer(peer_url, source="static")

            logger.info("Discovery service started")

        except Exception as e:
            logger.error(f"Failed to start discovery service: {e}")
            await self.stop()
            raise

    async def stop(self) -> None:
        """Stop discovery service."""
        # Cancel background tasks
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        if self._refresh_task:
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass

        # Stop DNS-SD
        if self._browser:
            await self._browser.async_cancel()
            self._browser = None

        if self._zeroconf:
            await self._zeroconf.async_unregister_service(self._service_info)
            await self._zeroconf.async_close()
            self._zeroconf = None

        # Close HTTP client
        await self._http_client.aclose()

        logger.info("Discovery service stopped")

    async def add_peer(self, url: str, source: str, name: Optional[str] = None) -> bool:
        """Add a new peer gateway.

        Args:
            url: Gateway URL
            source: Discovery source
            name: Optional gateway name

        Returns:
            True if peer was added
        """
        # Validate URL
        try:
            parsed = urlparse(url)
            if not parsed.scheme or not parsed.netloc:
                logger.warning(f"Invalid peer URL: {url}")
                return False
        except Exception:
            logger.warning(f"Failed to parse peer URL: {url}")
            return False

        # Skip if already known
        if url in self._discovered_peers:
            peer = self._discovered_peers[url]
            peer.last_seen = datetime.now(timezone.utc)
            return False

        try:
            # Try to get gateway info
            capabilities = await self._get_gateway_info(url)

            # Add to discovered peers
            self._discovered_peers[url] = DiscoveredPeer(
                url=url,
                name=name,
                protocol_version=PROTOCOL_VERSION,
                capabilities=capabilities,
                discovered_at=datetime.now(timezone.utc),
                last_seen=datetime.now(timezone.utc),
                source=source,
            )

            logger.info(f"Added peer gateway: {url} (via {source})")
            return True

        except Exception as e:
            logger.warning(f"Failed to add peer {url}: {e}")
            return False

    def get_discovered_peers(self) -> List[DiscoveredPeer]:
        """Get list of discovered peers.

        Returns:
            List of discovered peer information
        """
        return list(self._discovered_peers.values())

    async def refresh_peer(self, url: str) -> bool:
        """Refresh peer gateway information.

        Args:
            url: Gateway URL to refresh

        Returns:
            True if refresh succeeded
        """
        if url not in self._discovered_peers:
            return False

        try:
            capabilities = await self._get_gateway_info(url)
            self._discovered_peers[url].capabilities = capabilities
            self._discovered_peers[url].last_seen = datetime.now(timezone.utc)
            return True
        except Exception as e:
            logger.warning(f"Failed to refresh peer {url}: {e}")
            return False

    async def remove_peer(self, url: str) -> None:
        """Remove a peer gateway.

        Args:
            url: Gateway URL to remove
        """
        self._discovered_peers.pop(url, None)

    async def _on_service_state_change(
        self,
        zeroconf: AsyncZeroconf,
        service_type: str,
        name: str,
        state_change: ServiceStateChange,
    ) -> None:
        """Handle DNS-SD service changes.

        Args:
            zeroconf: Zeroconf instance
            service_type: Service type
            name: Service name
            state_change: Type of state change
        """
        if state_change is ServiceStateChange.Added:
            info = await zeroconf.async_get_service_info(service_type, name)
            if info:
                try:
                    # Extract gateway info
                    addresses = [socket.inet_ntoa(addr) for addr in info.addresses]
                    if addresses:
                        port = info.port
                        url = f"http://{addresses[0]}:{port}"
                        name = info.properties.get(b"name", b"").decode()

                        # Add peer
                        await self.add_peer(url, source="dns-sd", name=name)

                except Exception as e:
                    logger.warning(f"Failed to process discovered service {name}: {e}")

    async def _cleanup_loop(self) -> None:
        """Periodically clean up stale peers."""
        while True:
            try:
                now = datetime.now(timezone.utc)
                stale_urls = [url for url, peer in self._discovered_peers.items() if now - peer.last_seen > timedelta(minutes=10)]
                for url in stale_urls:
                    await self.remove_peer(url)
                    logger.info(f"Removed stale peer: {url}")

            except Exception as e:
                logger.error(f"Peer cleanup error: {e}")

            await asyncio.sleep(60)

    async def _refresh_loop(self) -> None:
        """Periodically refresh peer information."""
        while True:
            try:
                # Refresh all peers
                for url in list(self._discovered_peers.keys()):
                    await self.refresh_peer(url)

                # Exchange peers
                await self._exchange_peers()

            except Exception as e:
                logger.error(f"Peer refresh error: {e}")

            await asyncio.sleep(300)  # 5 minutes

    async def _get_gateway_info(self, url: str) -> ServerCapabilities:
        """Get gateway capabilities.

        Args:
            url: Gateway URL

        Returns:
            Gateway capabilities

        Raises:
            ValueError: If protocol version is unsupported
        """
        # Build initialize request
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocol_version": PROTOCOL_VERSION,
                "capabilities": {"roots": {"listChanged": True}, "sampling": {}},
                "client_info": {"name": settings.app_name, "version": "1.0.0"},
            },
        }

        # Send request using the persistent HTTP client directly
        response = await self._http_client.post(f"{url}/initialize", json=request, headers=self._get_auth_headers())
        response.raise_for_status()
        result = response.json()

        # Validate response
        if result.get("protocol_version") != PROTOCOL_VERSION:
            raise ValueError(f"Unsupported protocol version: {result.get('protocol_version')}")

        return ServerCapabilities.model_validate(result["capabilities"])

    async def _exchange_peers(self) -> None:
        """Exchange peer lists with known gateways."""
        for url in list(self._discovered_peers.keys()):
            try:
                # Get peer's peer list using the persistent HTTP client directly
                response = await self._http_client.get(f"{url}/peers", headers=self._get_auth_headers())
                response.raise_for_status()
                peers = response.json()

                # Add new peers from the response
                for peer in peers:
                    if isinstance(peer, dict) and "url" in peer:
                        await self.add_peer(peer["url"], source="exchange", name=peer.get("name"))

            except Exception as e:
                logger.warning(f"Failed to exchange peers with {url}: {e}")

    def _get_auth_headers(self) -> Dict[str, str]:
        """
        Get headers for gateway authentication.

        Returns:
            dict: Authorization header dict
        """
        api_key = f"{settings.basic_auth_user}:{settings.basic_auth_password}"
        return {"Authorization": f"Basic {api_key}", "X-API-Key": api_key}
