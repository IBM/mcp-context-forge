# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/root_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Root Service Implementation.
This module implements root directory management according to the MCP specification.
It handles root registration, validation, and change notifications.
"""

# Standard
import asyncio
import os
from typing import AsyncGenerator, Dict, List, Optional
from urllib.parse import urlparse

# First-Party
from mcpgateway.config import settings
from mcpgateway.models import Root
from mcpgateway.services.logging_service import LoggingService

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


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

    def __init__(self) -> None:
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

            Test with default roots configured:
            >>> from unittest.mock import patch
            >>> service = RootService()
            >>> with patch('mcpgateway.config.settings.default_roots', ['file:///tmp', 'http://example.com']):
            ...     asyncio.run(service.initialize())
            >>> len(service._roots)
            2
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

            Test cleanup of roots and subscribers:
            >>> service = RootService()
            >>> _ = asyncio.run(service.add_root('file:///tmp'))
            >>> service._subscribers.append(asyncio.Queue())
            >>> asyncio.run(service.shutdown())
            >>> len(service._roots)
            0
            >>> len(service._subscribers)
            0
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

            Test with multiple roots:
            >>> service = RootService()
            >>> _ = asyncio.run(service.add_root('file:///tmp'))
            >>> _ = asyncio.run(service.add_root('file:///home'))
            >>> roots = asyncio.run(service.list_roots())
            >>> len(roots)
            2
            >>> sorted([str(r.uri) for r in roots])
            ['file:///home', 'file:///tmp']
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

            Test with custom name:
            >>> service = RootService()
            >>> root = asyncio.run(service.add_root('file:///home/user', 'MyHome'))
            >>> root.name
            'MyHome'

            Test duplicate root error:
            >>> service = RootService()
            >>> _ = asyncio.run(service.add_root('file:///tmp'))
            >>> try:
            ...     asyncio.run(service.add_root('file:///tmp'))
            ... except RootServiceError as e:
            ...     str(e)
            'Root already exists: file:///tmp'

            Test invalid URI error:
            >>> from unittest.mock import patch
            >>> service = RootService()
            >>> with patch.object(service, '_make_root_uri', side_effect=ValueError('Bad URI')):
            ...     try:
            ...         asyncio.run(service.add_root('bad_uri'))
            ...     except RootServiceError as e:
            ...         str(e)
            'Invalid root URI: Bad URI'
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

            Test root not found error:
            >>> service = RootService()
            >>> try:
            ...     asyncio.run(service.remove_root('file:///nonexistent'))
            ... except RootServiceError as e:
            ...     str(e)
            'Root not found: file:///nonexistent'
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
            This example demonstrates subscription mechanics:
            >>> import asyncio
            >>> from mcpgateway.services.root_service import RootService
            >>> async def test_subscribe():
            ...     service = RootService()
            ...     events = []
            ...     async def collect_events():
            ...         async for event in service.subscribe_changes():
            ...             events.append(event)
            ...             if event['type'] == 'root_removed':
            ...                 break
            ...     task = asyncio.create_task(collect_events())
            ...     await asyncio.sleep(0)  # Let subscription start
            ...     await service.add_root('file:///tmp')
            ...     await service.remove_root('file:///tmp')
            ...     await task
            ...     return events
            >>> events = asyncio.run(test_subscribe())
            >>> len(events)
            2
            >>> events[0]['type']
            'root_added'
            >>> events[1]['type']
            'root_removed'
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

        Examples:
            >>> service = RootService()
            >>> service._make_root_uri('/tmp')
            'file:///tmp'
            >>> service._make_root_uri('file:///home')
            'file:///home'
            >>> service._make_root_uri('http://example.com')
            'http://example.com'
            >>> service._make_root_uri('ftp://server/path')
            'ftp://server/path'
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

        Note:
            The root.uri field returns a FileUrl object which is serialized
            as-is in the event data.

        Examples:
            >>> import asyncio
            >>> from mcpgateway.services.root_service import RootService
            >>> from mcpgateway.models import Root
            >>> service = RootService()
            >>> queue = asyncio.Queue()
            >>> service._subscribers.append(queue)
            >>> root = Root(uri='file:///tmp', name='temp')
            >>> asyncio.run(service._notify_root_added(root))
            >>> event = asyncio.run(queue.get())
            >>> event['type']
            'root_added'
            >>> event['data']['uri']
            FileUrl('file:///tmp')
        """
        event = {"type": "root_added", "data": {"uri": root.uri, "name": root.name}}
        await self._notify_subscribers(event)

    async def _notify_root_removed(self, root: Root) -> None:
        """Notify subscribers of root removal.

        Args:
            root: Removed root

        Examples:
            >>> import asyncio
            >>> from mcpgateway.services.root_service import RootService
            >>> from mcpgateway.models import Root
            >>> service = RootService()
            >>> queue = asyncio.Queue()
            >>> service._subscribers.append(queue)
            >>> root = Root(uri='file:///tmp', name='temp')
            >>> asyncio.run(service._notify_root_removed(root))
            >>> event = asyncio.run(queue.get())
            >>> event['type']
            'root_removed'
            >>> event['data']['uri']
            FileUrl('file:///tmp')
        """
        event = {"type": "root_removed", "data": {"uri": root.uri}}
        await self._notify_subscribers(event)

    async def _notify_subscribers(self, event: Dict) -> None:
        """Send event to all subscribers.

        Args:
            event: Event to send

        Examples:
            >>> import asyncio
            >>> from mcpgateway.services.root_service import RootService
            >>> service = RootService()
            >>> queue1 = asyncio.Queue()
            >>> queue2 = asyncio.Queue()
            >>> service._subscribers.extend([queue1, queue2])
            >>> event = {"type": "test", "data": {}}
            >>> asyncio.run(service._notify_subscribers(event))
            >>> asyncio.run(queue1.get()) == event
            True
            >>> asyncio.run(queue2.get()) == event
            True

            Test error handling with closed queue:
            >>> from unittest.mock import AsyncMock
            >>> service = RootService()
            >>> bad_queue = AsyncMock()
            >>> bad_queue.put.side_effect = Exception("Queue error")
            >>> service._subscribers.append(bad_queue)
            >>> asyncio.run(service._notify_subscribers({"type": "test"}))
        """
        for queue in self._subscribers:
            try:
                await queue.put(event)
            except Exception as e:
                logger.error(f"Failed to notify subscriber: {e}")
