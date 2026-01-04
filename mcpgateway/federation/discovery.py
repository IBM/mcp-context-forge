# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/federation/discovery.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Federation Discovery Service.
This module implements automatic peer discovery for MCP Gateways.
It supports multiple discovery mechanisms:
- DNS-SD service discovery
- Static peer lists
- Peer exchange protocol
- Manual registration

The discovery service automatically finds and connects to other MCP gateways
on the network, maintains a list of active peers, and exchanges peer information
to build a federation of gateways.

# Run doctests with coverage and show missing lines
pytest --doctest-modules --cov=mcpgateway.federation.discovery --cov-report=term-missing mcpgateway/federation/discovery.py -v

# For more detailed line-by-line coverage annotation
pytest --doctest-modules --cov=mcpgateway.federation.discovery --cov-report=annotate mcpgateway/federation/discovery.py -v


Examples:
    Basic usage of the discovery service::

        >>> import asyncio
        >>> from mcpgateway.federation.discovery import DiscoveryService
        >>>
        >>> async def main():
        ...     discovery = DiscoveryService()
        ...     await discovery.start()
        ...
        ...     # Add a manual peer
        ...     await discovery.add_peer("http://gateway.example.com:8080", "manual")
        ...
        ...     # Get discovered peers
        ...     peers = discovery.get_discovered_peers()
        ...     for peer in peers:
        ...         print(f"Found peer: {peer.url} via {peer.source}")
        ...
        ...     await discovery.stop()
        >>>
        >>> # asyncio.run(main())

    Testing peer discovery::

        >>> from datetime import datetime, timezone
        >>> peer = DiscoveredPeer(
        ...     url="http://localhost:8080",
        ...     name="test-gateway",
        ...     protocol_version="2025-03-26",
        ...     capabilities=None,
        ...     discovered_at=datetime.now(timezone.utc),
        ...     last_seen=datetime.now(timezone.utc),
        ...     source="manual"
        ... )
        >>> print(peer.url)
        http://localhost:8080
"""

# Standard
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import ipaddress
import os
import socket
from typing import Dict, List, Optional
from urllib.parse import urlparse

# Third-Party
import httpx
from zeroconf import ServiceInfo, ServiceStateChange
from zeroconf.asyncio import AsyncServiceBrowser, AsyncZeroconf

# First-Party
from mcpgateway import __version__
from mcpgateway.common.models import ServerCapabilities
from mcpgateway.config import settings
from mcpgateway.services.logging_service import LoggingService

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

PROTOCOL_VERSION = os.getenv("PROTOCOL_VERSION", "2025-03-26")


@dataclass
class DiscoveredPeer:
    """Information about a discovered peer gateway.

    Represents a peer MCP gateway that has been discovered through various
    discovery mechanisms. Tracks when the peer was discovered, last seen,
    and its capabilities.

    Attributes:
        url (str): The base URL of the peer gateway.
        name (Optional[str]): Human-readable name of the peer gateway.
        protocol_version (Optional[str]): MCP protocol version supported by the peer.
        capabilities (Optional[ServerCapabilities]): Server capabilities of the peer.
        discovered_at (datetime): When the peer was first discovered.
        last_seen (datetime): When the peer was last successfully contacted.
        source (str): How the peer was discovered (e.g., "dns-sd", "static", "manual").

    Examples:
        >>> from datetime import datetime, timezone
        >>> peer = DiscoveredPeer(
        ...     url="http://gateway1.local:8080",
        ...     name="Gateway 1",
        ...     protocol_version="2025-03-26",
        ...     capabilities=None,
        ...     discovered_at=datetime.now(timezone.utc),
        ...     last_seen=datetime.now(timezone.utc),
        ...     source="dns-sd"
        ... )
        >>> print(f"{peer.name} at {peer.url}")
        Gateway 1 at http://gateway1.local:8080
        >>> peer.protocol_version
        '2025-03-26'
        >>> peer.source
        'dns-sd'
        >>> isinstance(peer.discovered_at, datetime)
        True
        >>> isinstance(peer.last_seen, datetime)
        True
    """

    url: str
    name: Optional[str]
    protocol_version: Optional[str]
    capabilities: Optional[ServerCapabilities]
    discovered_at: datetime
    last_seen: datetime
    source: str


class LocalDiscoveryService:
    """Base class for local network discovery using DNS-SD.

    Provides functionality for advertising the local gateway on the network
    using DNS Service Discovery (mDNS/Bonjour). This allows other gateways
    on the same network to automatically discover this gateway.

    Attributes:
        _service_type (str): The DNS-SD service type for MCP gateways.
        _service_info (ServiceInfo): Zeroconf service information for advertising.

    Examples:
        >>> service = LocalDiscoveryService()
        >>> service._service_type
        '_mcp._tcp.local.'
        >>> isinstance(service._service_info, ServiceInfo)
        True
        >>> service._service_info.type
        '_mcp._tcp.local.'
        >>> service._service_info.port == settings.port
        True
        >>> b'name' in service._service_info.properties
        True
        >>> b'version' in service._service_info.properties
        True
        >>> b'protocol' in service._service_info.properties
        True
    """

    def __init__(self):
        """Initialize local discovery service.

        Sets up the service information for DNS-SD advertisement including
        the service type, name, port, and properties.
        """
        # Service info for local discovery
        self._service_type = "_mcp._tcp.local."
        self._service_info = ServiceInfo(
            self._service_type,
            f"{settings.app_name}.{self._service_type}",
            addresses=[socket.inet_aton(addr) for addr in self._get_local_addresses()],
            port=settings.port,
            properties={
                "name": settings.app_name,
                "version": __version__,
                "protocol": PROTOCOL_VERSION,
            },
        )

    def _get_local_addresses(self) -> List[str]:
        """Get list of local network addresses.

        Retrieves all non-localhost IP addresses for the local machine.
        Falls back to localhost if no other addresses are found or if
        an error occurs.

        Returns:
            List[str]: List of IP addresses as strings.

        Examples:
            >>> service = LocalDiscoveryService()
            >>> addrs = service._get_local_addresses()
            >>> isinstance(addrs, list)
            True
            >>> all(isinstance(addr, str) for addr in addrs)
            True
            >>> len(addrs) >= 1  # At least localhost
            True
            >>> # Check IP format
            >>> all('.' in addr for addr in addrs)  # IPv4 format
            True
            >>> # Verify no empty addresses
            >>> all(addr for addr in addrs)
            True
            >>> '' not in addrs
            True
        """
        addresses = []
        try:
            # Get all network interfaces
            for iface in socket.getaddrinfo(socket.gethostname(), None):
                addr = iface[4][0]
                ip_obj = ipaddress.ip_address(addr)
                is_ipv4 = isinstance(ip_obj, ipaddress.IPv4Address)
                # Skip localhost and non ipv4 addresses
                if is_ipv4 and not addr.startswith("127."):
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

    The service maintains a list of discovered peers, periodically refreshes
    their information, and removes stale peers that haven't been seen recently.

    Attributes:
        _zeroconf (Optional[AsyncZeroconf]): Zeroconf instance for DNS-SD.
        _browser (Optional[AsyncServiceBrowser]): Service browser for discovering peers.
        _http_client (httpx.AsyncClient): HTTP client for communicating with peers.
        _discovered_peers (Dict[str, DiscoveredPeer]): Map of URL to peer information.
        _cleanup_task (Optional[asyncio.Task]): Background task for cleaning stale peers.
        _refresh_task (Optional[asyncio.Task]): Background task for refreshing peer info.

    Examples:
        >>> import asyncio
        >>> async def test_discovery():
        ...     service = DiscoveryService()
        ...     await service.start()
        ...
        ...     # Add a peer manually
        ...     added = await service.add_peer("http://peer1.local:8080", "manual")
        ...
        ...     # Get all discovered peers
        ...     peers = service.get_discovered_peers()
        ...
        ...     await service.stop()
        ...     return len(peers)
        >>>
        >>> # result = asyncio.run(test_discovery())
    """

    def __init__(self):
        """Initialize discovery service.

        Sets up the HTTP client, peer tracking dictionary, and prepares
        for background tasks. Does not start any network operations.
        """
        super().__init__()

        self._zeroconf: Optional[AsyncZeroconf] = None
        self._browser: Optional[AsyncServiceBrowser] = None
        self._http_client = httpx.AsyncClient(
            timeout=settings.federation_timeout,
            verify=not settings.skip_ssl_verify,
            limits=httpx.Limits(
                max_connections=settings.httpx_max_connections,
                max_keepalive_connections=settings.httpx_max_keepalive_connections,
                keepalive_expiry=settings.httpx_keepalive_expiry,
            ),
        )

        # Track discovered peers
        self._discovered_peers: Dict[str, DiscoveredPeer] = {}

        # Start background tasks
        self._cleanup_task: Optional[asyncio.Task] = None
        self._refresh_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start discovery service.

        Initializes DNS-SD if enabled, starts background tasks for peer
        maintenance, and loads any statically configured peers.

        Raises:
            Exception: If unable to start discovery service.

        Examples:
            >>> import asyncio
            >>> async def test_start():
            ...     service = DiscoveryService()
            ...     await service.start()
            ...     # Service is now running
            ...     await service.stop()
            >>> # asyncio.run(test_start())
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
        """Stop discovery service.

        Cancels background tasks, unregisters DNS-SD service, and closes
        all network connections. Safe to call multiple times.

        Examples:
            >>> import asyncio
            >>> async def test_stop():
            ...     service = DiscoveryService()
            ...     await service.start()
            ...     await service.stop()
            ...     # All resources cleaned up
            >>> # asyncio.run(test_stop())
        """
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

        Validates the URL, checks if the peer is already known, and attempts
        to retrieve the peer's capabilities. If successful, adds the peer to
        the discovered peers list.

        Args:
            url (str): Gateway URL (e.g., "http://gateway.example.com:8080").
            source (str): Discovery source (e.g., "static", "dns-sd", "manual").
            name (Optional[str]): Optional human-readable gateway name.

        Returns:
            bool: True if peer was successfully added, False otherwise.

        Examples:
            >>> import asyncio
            >>> async def test_add_peer():
            ...     service = DiscoveryService()
            ...     # Valid URL
            ...     result = await service.add_peer("http://localhost:8080", "manual")
            ...     # Invalid URL
            ...     invalid = await service.add_peer("not-a-url", "manual")
            ...     return result, invalid
            >>> # valid, invalid = asyncio.run(test_add_peer())
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

        Returns a snapshot of all currently known peer gateways.

        Returns:
            List[DiscoveredPeer]: List of discovered peer information.

        Examples:
            >>> service = DiscoveryService()
            >>> peers = service.get_discovered_peers()
            >>> isinstance(peers, list)
            True
            >>> # After adding peers
            >>> # len(peers) > 0
            >>> # Initially empty
            >>> len(peers)
            0
            >>> # Add a peer manually (sync example)
            >>> from datetime import datetime, timezone
            >>> service._discovered_peers["http://test.com"] = DiscoveredPeer(
            ...     url="http://test.com",
            ...     name="Test",
            ...     protocol_version="2025-03-26",
            ...     capabilities=None,
            ...     discovered_at=datetime.now(timezone.utc),
            ...     last_seen=datetime.now(timezone.utc),
            ...     source="manual"
            ... )
            >>> peers = service.get_discovered_peers()
            >>> len(peers)
            1
            >>> peers[0].url
            'http://test.com'
        """
        return list(self._discovered_peers.values())

    async def refresh_peer(self, url: str) -> bool:
        """Refresh peer gateway information.

        Attempts to update the capabilities and last seen time for a known peer.

        Args:
            url (str): Gateway URL to refresh.

        Returns:
            bool: True if refresh succeeded, False otherwise.

        Examples:
            >>> import asyncio
            >>> async def test_refresh():
            ...     service = DiscoveryService()
            ...     # Add a peer first
            ...     await service.add_peer("http://localhost:8080", "manual")
            ...     # Refresh it
            ...     refreshed = await service.refresh_peer("http://localhost:8080")
            ...     # Unknown peer
            ...     unknown = await service.refresh_peer("http://unknown:8080")
            ...     return refreshed, unknown
            >>> # refreshed, unknown = asyncio.run(test_refresh())
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

        Removes a peer from the discovered peers list. Safe to call even
        if the peer doesn't exist.

        Args:
            url (str): Gateway URL to remove.

        Examples:
            >>> import asyncio
            >>> async def test_remove():
            ...     service = DiscoveryService()
            ...     await service.add_peer("http://localhost:8080", "manual")
            ...     await service.remove_peer("http://localhost:8080")
            ...     peers = service.get_discovered_peers()
            ...     return len(peers)
            >>> # count = asyncio.run(test_remove())

            >>> # Sync example
            >>> from datetime import datetime, timezone
            >>> service = DiscoveryService()
            >>> # Add a peer directly
            >>> service._discovered_peers["http://test.com"] = DiscoveredPeer(
            ...     url="http://test.com",
            ...     name="Test",
            ...     protocol_version="2025-03-26",
            ...     capabilities=None,
            ...     discovered_at=datetime.now(timezone.utc),
            ...     last_seen=datetime.now(timezone.utc),
            ...     source="manual"
            ... )
            >>> len(service._discovered_peers)
            1
            >>> # Remove it (sync version for testing)
            >>> service._discovered_peers.pop("http://test.com", None) is not None
            True
            >>> len(service._discovered_peers)
            0
            >>> # Safe to remove non-existent
            >>> service._discovered_peers.pop("http://nonexistent.com", None) is None
            True
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

        Called by Zeroconf when services are added or removed from the network.
        When a new MCP gateway is discovered, extracts its information and adds
        it as a peer.

        Args:
            zeroconf (AsyncZeroconf): Zeroconf instance.
            service_type (str): Service type that changed.
            name (str): Service name that changed.
            state_change (ServiceStateChange): Type of state change (Added/Removed).
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
        """Periodically clean up stale peers.

        Runs in the background and removes peers that haven't been seen
        for more than 10 minutes. Runs every 60 seconds.

        Raises:
            asyncio.CancelledError: When the task is cancelled during shutdown.
        """
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
        """Periodically refresh peer information.

        Runs in the background and refreshes all peer information and
        performs peer exchange every 5 minutes.

        Raises:
            asyncio.CancelledError: When the task is cancelled during shutdown.
        """
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

        Sends an initialize request to the peer gateway to retrieve its
        capabilities and verify protocol compatibility.

        Args:
            url (str): Gateway URL.

        Returns:
            ServerCapabilities: Gateway capabilities object.

        Raises:
            ValueError: If protocol version is unsupported.
            httpx.HTTPStatusError: If the HTTP request fails.
            httpx.RequestError: If the request cannot be sent.
        """
        # Build initialize request
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocol_version": PROTOCOL_VERSION,
                "capabilities": {"roots": {"listChanged": True}, "sampling": {}},
                "client_info": {"name": settings.app_name, "version": __version__},
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
        """Exchange peer lists with known gateways.

        Contacts each known peer to retrieve their list of known peers,
        potentially discovering new gateways through transitive connections.
        This enables building a mesh network of federated gateways.
        """
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
        """Get headers for gateway authentication.

        Constructs authentication headers using the configured credentials
        for communicating with peer gateways.

        Returns:
            Dict[str, str]: Dictionary containing Authorization and X-API-Key headers.

        Examples:
            >>> service = DiscoveryService()
            >>> headers = service._get_auth_headers()
            >>> "Authorization" in headers
            True
            >>> "X-API-Key" in headers
            True
            >>> headers["Authorization"].startswith("Basic ")
            True
            >>> headers["X-API-Key"] == f"{settings.basic_auth_user}:{settings.basic_auth_password}"
            True
            >>> isinstance(headers, dict)
            True
            >>> len(headers)
            2
        """
        api_key = f"{settings.basic_auth_user}:{settings.basic_auth_password}"
        return {"Authorization": f"Basic {api_key}", "X-API-Key": api_key}
