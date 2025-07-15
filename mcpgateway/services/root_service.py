# -*- coding: utf-8 -*-
"""Root Service Implementation.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

This module implements root directory management according to the MCP specification.
It handles root registration, validation, and change notifications.
"""

# Standard
import asyncio
import logging
import os
from typing import AsyncGenerator, Dict, List, Optional
from urllib.parse import urlparse

# First-Party
from mcpgateway.config import settings
from mcpgateway.models import Root

logger = logging.getLogger(__name__)


class RootServiceError(Exception):
    """Base class for root service errors."""


class RootService:
    """MCP root service.

    Manages roots that can be exposed to MCP clients.
    Handles:
    - Root registration and validation
    - Change notifications
    - Root permissions and access control
    """

    def __init__(self):
        """Initialize root service."""
        self._roots: Dict[str, Root] = {}
        self._subscribers: List[asyncio.Queue] = []

    async def initialize(self) -> None:
        """Initialize root service.

        Examples:
            >>> from mcpgateway.services.root_service import RootService
            >>> import asyncio
            >>> service = RootService()
            >>> asyncio.run(service.initialize())
        """
        logger.info("Initializing root service")
        # Add any configured default roots
        for root_uri in settings.default_roots:
            try:
                await self.add_root(root_uri)
            except RootServiceError as e:
                logger.error(f"Failed to add default root {root_uri}: {e}")

    async def shutdown(self) -> None:
        """Shutdown root service.

        Examples:
            >>> from mcpgateway.services.root_service import RootService
            >>> import asyncio
            >>> service = RootService()
            >>> asyncio.run(service.shutdown())
        """
        logger.info("Shutting down root service")
        # Clear all roots and subscribers
        self._roots.clear()
        self._subscribers.clear()

    async def list_roots(self) -> List[Root]:
        """List available roots.

        Returns:
            List of registered roots

        Examples:
            >>> from mcpgateway.services.root_service import RootService
            >>> import asyncio
            >>> service = RootService()
            >>> asyncio.run(service.list_roots())
            []
        """
        return list(self._roots.values())

    async def add_root(self, uri: str, name: Optional[str] = None) -> Root:
        """Add a new root.

        Args:
            uri: Root URI
            name: Optional root name

        Returns:
            Created root object

        Raises:
            RootServiceError: If root is invalid or already exists

        Examples:
            >>> from mcpgateway.services.root_service import RootService
            >>> import asyncio
            >>> service = RootService()
            >>> root = asyncio.run(service.add_root('file:///tmp'))
            >>> root.uri == 'file:///tmp'
            True
        """
        try:
            root_uri = self._make_root_uri(uri)
        except ValueError as e:
            raise RootServiceError(f"Invalid root URI: {e}")

        if root_uri in self._roots:
            raise RootServiceError(f"Root already exists: {root_uri}")

        # Skip any access check; just store the key/value.
        root_obj = Root(
            uri=root_uri,
            name=name or os.path.basename(urlparse(root_uri).path) or root_uri,
        )
        self._roots[root_uri] = root_obj

        await self._notify_root_added(root_obj)
        logger.info(f"Added root: {root_uri}")
        return root_obj

    async def remove_root(self, root_uri: str) -> None:
        """Remove a registered root.

        Args:
            root_uri: Root URI to remove

        Raises:
            RootServiceError: If root not found

        Examples:
            >>> from mcpgateway.services.root_service import RootService
            >>> import asyncio
            >>> service = RootService()
            >>> _ = asyncio.run(service.add_root('file:///tmp'))
            >>> asyncio.run(service.remove_root('file:///tmp'))
        """
        if root_uri not in self._roots:
            raise RootServiceError(f"Root not found: {root_uri}")
        root_obj = self._roots.pop(root_uri)
        await self._notify_root_removed(root_obj)
        logger.info(f"Removed root: {root_uri}")

    async def subscribe_changes(self) -> AsyncGenerator[Dict, None]:
        """Subscribe to root changes.

        Yields:
            Root change events

        Examples:
            This example was removed to prevent the test runner from hanging on async generator consumption.
        """
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(queue)
        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            self._subscribers.remove(queue)

    def _make_root_uri(self, uri: str) -> str:
        """Convert input to a valid URI.

        If no scheme is provided, assume a file URI and convert the path to an absolute path.

        Args:
            uri: Input URI or filesystem path

        Returns:
            A valid URI string
        """
        parsed = urlparse(uri)
        if not parsed.scheme:
            # No scheme provided; assume a file URI.
            return f"file://{uri}"
        # If a scheme is present (e.g., http, https, ftp, etc.), return the URI as-is.
        return uri

    async def _notify_root_added(self, root: Root) -> None:
        """Notify subscribers of root addition.

        Args:
            root: Added root
        """
        event = {"type": "root_added", "data": {"uri": root.uri, "name": root.name}}
        await self._notify_subscribers(event)

    async def _notify_root_removed(self, root: Root) -> None:
        """Notify subscribers of root removal.

        Args:
            root: Removed root
        """
        event = {"type": "root_removed", "data": {"uri": root.uri}}
        await self._notify_subscribers(event)

    async def _notify_subscribers(self, event: Dict) -> None:
        """Send event to all subscribers.

        Args:
            event: Event to send
        """
        for queue in self._subscribers:
            try:
                await queue.put(event)
            except Exception as e:
                logger.error(f"Failed to notify subscriber: {e}")
