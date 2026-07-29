# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/root_service.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Root Service Implementation.
This module implements root directory management according to the MCP specification.
It handles root registration, validation, and change notifications.
"""

# Standard
import asyncio
import os
from pathlib import PurePosixPath
import re
from typing import AsyncGenerator, Dict, List, Optional
from urllib.parse import quote, unquote_to_bytes, urlsplit, urlunsplit

# Third-Party
from pydantic import ValidationError

# First-Party
from mcpgateway.common.models import Root
from mcpgateway.config import settings
from mcpgateway.observability import create_span
from mcpgateway.services.logging_service import LoggingService

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

ROOT_MAX_URI_LENGTH = 2048
ROOT_MAX_NAME_LENGTH = 255
_NETWORK_SCHEMES = {"http", "https", "ws", "wss"}
_DEFAULT_PORTS = {"http": 80, "https": 443, "ws": 80, "wss": 443}
_PERCENT_PATTERN = re.compile(r"%(?![0-9A-Fa-f]{2})")
_ENCODED_SEPARATOR_PATTERN = re.compile(r"%(?:2f|5c)", re.IGNORECASE)


class RootServiceError(Exception):
    """Base class for root service errors."""


class RootServiceValidationError(RootServiceError):
    """Raised when root input violates root URI policy."""

    def __init__(self, reason_code: str, message: str = "Root URI rejected by policy") -> None:
        """Initialize validation error with a stable reason code."""
        self.reason_code = reason_code
        super().__init__(message)


class RootServiceNotFoundError(RootServiceError):
    """Raised when a requested root is not found.

    Examples:
        >>> error = RootServiceNotFoundError("Root Service not found")
        >>> str(error)
        'Root Service not found'
        >>> isinstance(error, RootServiceError)
        True
    """


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
            >>> with patch('mcpgateway.config.settings.root_allowed_schemes', ['https']):
            ...     with patch('mcpgateway.config.settings.default_roots', ['https://example.com/tmp', 'https://example.com/home']):
            ...         asyncio.run(service.initialize())
            ...         len(service._roots)
            2
        """
        logger.info("Initializing root service")
        # Add any configured default roots
        for root_uri in settings.default_roots:
            try:
                await self.add_root(root_uri)
            except RootServiceValidationError as e:
                logger.error("Rejected configured default root: scheme=%s reason=%s", self._safe_scheme(root_uri), e.reason_code)
                raise
            except RootServiceError as e:
                logger.error("Failed to add configured default root: scheme=%s error=%s", self._safe_scheme(root_uri), type(e).__name__)
                raise

    async def shutdown(self) -> None:
        """Shutdown root service.

        Examples:
            >>> from mcpgateway.services.root_service import RootService
            >>> import asyncio
            >>> service = RootService()
            >>> asyncio.run(service.shutdown())

            Test cleanup of roots and subscribers:
            >>> from unittest.mock import patch
            >>> with patch('mcpgateway.config.settings.root_allowed_schemes', ['https']):
            ...     service = RootService()
            ...     _ = asyncio.run(service.add_root('https://example.com/tmp'))
            ...     service._subscribers.append(asyncio.Queue())
            ...     asyncio.run(service.shutdown())
            ...     (len(service._roots), len(service._subscribers))
            (0, 0)
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
            >>> from unittest.mock import patch
            >>> with patch('mcpgateway.config.settings.root_allowed_schemes', ['https']):
            ...     service = RootService()
            ...     _ = asyncio.run(service.add_root('https://example.com/tmp'))
            ...     _ = asyncio.run(service.add_root('https://example.com/home'))
            ...     roots = asyncio.run(service.list_roots())
            ...     sorted([str(r.uri) for r in roots])
            ['https://example.com/home', 'https://example.com/tmp']
        """
        with create_span("root.list", {"root.count": len(self._roots)}):
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
            >>> from unittest.mock import patch
            >>> with patch('mcpgateway.config.settings.root_allowed_schemes', ['https']):
            ...     service = RootService()
            ...     root = asyncio.run(service.add_root('https://example.com/tmp'))
            ...     str(root.uri)
            'https://example.com/tmp'

            Test with custom name:
            >>> with patch('mcpgateway.config.settings.root_allowed_schemes', ['https']):
            ...     service = RootService()
            ...     root = asyncio.run(service.add_root('https://example.com/home/user', 'MyHome'))
            ...     root.name
            'MyHome'

            Test duplicate root error:
            >>> with patch('mcpgateway.config.settings.root_allowed_schemes', ['https']):
            ...     service = RootService()
            ...     _ = asyncio.run(service.add_root('https://example.com/tmp'))
            ...     try:
            ...         asyncio.run(service.add_root('https://example.com/tmp'))
            ...     except RootServiceError as e:
            ...         str(e)
            'Root already exists: https://example.com/tmp'

            Test default-deny file policy:
            >>> from mcpgateway.services.root_service import RootServiceValidationError
            >>> service = RootService()
            >>> try:
            ...     asyncio.run(service.add_root('file:///tmp'))
            ... except RootServiceValidationError as exc:
            ...     exc.reason_code
            'file_disabled'
        """
        root_uri, root_name = self.validate_root_input(uri, name)

        root_obj = Root(
            uri=root_uri,
            name=root_name or os.path.basename(urlsplit(root_uri).path) or root_uri,
        )

        # NORMALIZED URI from the Root object as the dictionary key
        normalized_key = str(root_obj.uri)

        if normalized_key in self._roots:
            raise RootServiceError(f"Root already exists: {root_uri}")

        self._roots[normalized_key] = root_obj

        await self._notify_root_added(root_obj)
        logger.info("Added root: %s", root_uri)
        return root_obj

    async def get_root_by_uri(self, root_uri: str) -> Root:
        """Get a root by URI.

        Args:
            root_uri: Root URI to retrieve

        Returns:
            Root: The found root object

        Raises:
            RootServiceNotFoundError: If root not found

        Examples:
            >>> from mcpgateway.services.root_service import RootService
            >>> import asyncio
            >>> from unittest.mock import patch
            >>> with patch('mcpgateway.config.settings.root_allowed_schemes', ['https']):
            ...     service = RootService()
            ...     _ = asyncio.run(service.add_root('https://example.com/tmp'))
            ...     root = asyncio.run(service.get_root_by_uri('https://example.com/tmp'))
            ...     str(root.uri)
            'https://example.com/tmp'

            Test root not found error:
            >>> with patch('mcpgateway.config.settings.root_allowed_schemes', ['https']):
            ...     service = RootService()
            ...     try:
            ...         asyncio.run(service.get_root_by_uri('https://example.com/nonexistent'))
            ...     except RootServiceError as e:
            ...         str(e)
            'Root not found: https://example.com/nonexistent'
        """
        # Normalize the URI to match how it was stored.
        normalized_uri = self._validate_and_canonicalize_root_uri(root_uri)
        if normalized_uri not in self._roots:
            raise RootServiceNotFoundError(f"Root not found: {root_uri}")
        return self._roots[normalized_uri]

    async def update_root(self, root_uri: str, name: Optional[str] = None) -> Root:
        """Update an existing root.

        Args:
            root_uri: Root URI to update
            name: New name for the root

        Returns:
            Root: The updated root object

        Raises:
            RootServiceNotFoundError: If root is not found

        Examples:
            >>> from mcpgateway.services.root_service import RootService
            >>> import asyncio
            >>> from unittest.mock import patch
            >>> with patch('mcpgateway.config.settings.root_allowed_schemes', ['https']):
            ...     service = RootService()
            ...     _ = asyncio.run(service.add_root('https://example.com/tmp', 'Temp'))
            ...     updated = asyncio.run(service.update_root('https://example.com/tmp', 'Updated Temp'))
            ...     updated.name
            'Updated Temp'

            Test root not found error:
            >>> with patch('mcpgateway.config.settings.root_allowed_schemes', ['https']):
            ...     service = RootService()
            ...     try:
            ...         asyncio.run(service.update_root('https://example.com/nonexistent', 'New Name'))
            ...     except RootServiceError as e:
            ...         str(e)
            'Root not found: https://example.com/nonexistent'
        """
        # Normalize the URI to match how it was stored.
        normalized_uri = self._validate_and_canonicalize_root_uri(root_uri)
        if normalized_uri not in self._roots:
            raise RootServiceNotFoundError(f"Root not found: {root_uri}")

        root_obj = self._roots[normalized_uri]

        # Update name if provided
        if name is not None:
            root_obj.name = self._validate_root_name(name)

        # Notify subscribers of the update
        event = {"type": "root_updated", "data": {"uri": root_obj.uri, "name": root_obj.name}}
        await self._notify_subscribers(event)

        logger.info("Updated root: %s, name: %s", root_uri, name)
        return root_obj

    async def remove_root(self, root_uri: str) -> None:
        """Remove a registered root.

        Args:
            root_uri: Root URI to remove

        Raises:
            RootServiceNotFoundError: If root not found

        Examples:
            >>> from mcpgateway.services.root_service import RootService
            >>> import asyncio
            >>> from unittest.mock import patch
            >>> with patch('mcpgateway.config.settings.root_allowed_schemes', ['https']):
            ...     service = RootService()
            ...     _ = asyncio.run(service.add_root('https://example.com/tmp'))
            ...     asyncio.run(service.remove_root('https://example.com/tmp'))

            Test root not found error:
            >>> with patch('mcpgateway.config.settings.root_allowed_schemes', ['https']):
            ...     service = RootService()
            ...     try:
            ...         asyncio.run(service.remove_root('https://example.com/nonexistent'))
            ...     except RootServiceError as e:
            ...         str(e)
            'Root not found: https://example.com/nonexistent'
        """
        # Normalize the URI to match how it was stored.
        normalized_uri = self._validate_and_canonicalize_root_uri(root_uri)
        if normalized_uri not in self._roots:
            raise RootServiceNotFoundError(f"Root not found: {root_uri}")
        root_obj = self._roots.pop(normalized_uri)
        await self._notify_root_removed(root_obj)
        logger.info("Removed root: %s", root_uri)

    async def subscribe_changes(self) -> AsyncGenerator[Dict, None]:
        """Subscribe to root changes.

        Yields:
            Root change events

        Examples:
            This example demonstrates subscription mechanics:
            >>> import asyncio
            >>> from mcpgateway.services.root_service import RootService
            >>> from unittest.mock import patch
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
            ...     await service.add_root('https://example.com/tmp')
            ...     await service.remove_root('https://example.com/tmp')
            ...     await task
            ...     return events
            >>> with patch('mcpgateway.config.settings.root_allowed_schemes', ['https']):
            ...     events = asyncio.run(test_subscribe())
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

    def validate_root_input(self, uri: str, name: Optional[str]) -> tuple[str, Optional[str]]:
        """Validate root URI/name and return canonical values without mutation."""
        return self._validate_and_canonicalize_root_uri(uri), self._validate_root_name(name)

    def _validate_and_canonicalize_root_uri(self, uri: str) -> str:
        """Return canonical URI or raise RootServiceValidationError."""
        if not isinstance(uri, str) or uri == "":
            raise RootServiceValidationError("empty_uri")
        if len(uri) > ROOT_MAX_URI_LENGTH:
            raise RootServiceValidationError("uri_too_long")
        if uri != uri.strip():
            raise RootServiceValidationError("control_character")
        if self._has_control_character(uri):
            raise RootServiceValidationError("control_character")
        if _PERCENT_PATTERN.search(uri):
            raise RootServiceValidationError("invalid_percent_encoding")

        parsed = urlsplit(uri)
        if not parsed.scheme:
            raise RootServiceValidationError("scheme_missing")
        scheme = parsed.scheme.lower()

        if parsed.query:
            raise RootServiceValidationError("query_not_allowed")
        if parsed.fragment:
            raise RootServiceValidationError("fragment_not_allowed")
        if parsed.username is not None or parsed.password is not None:
            raise RootServiceValidationError("userinfo_not_allowed")

        if scheme == "file":
            canonical_uri = self._canonicalize_file_uri(parsed)
        elif scheme in _NETWORK_SCHEMES:
            canonical_uri = self._canonicalize_network_uri(parsed, scheme)
        else:
            raise RootServiceValidationError("scheme_not_allowed")

        try:
            return str(Root(uri=canonical_uri).uri)
        except ValidationError as exc:
            raise RootServiceValidationError("scheme_not_allowed") from exc

    def _validate_root_name(self, name: Optional[str]) -> Optional[str]:
        """Validate optional root display name."""
        if name is None:
            return None
        if len(name) > ROOT_MAX_NAME_LENGTH:
            raise RootServiceValidationError("name_too_long")
        if self._has_control_character(name):
            raise RootServiceValidationError("control_character")
        return name

    def _canonicalize_network_uri(self, parsed, scheme: str) -> str:
        """Canonicalize http/https/ws/wss root URI."""
        if scheme not in settings.root_allowed_schemes:
            raise RootServiceValidationError("scheme_not_allowed")
        if not parsed.hostname:
            raise RootServiceValidationError("network_host_missing")
        try:
            port = parsed.port
        except ValueError as exc:
            raise RootServiceValidationError("network_port_invalid") from exc

        host = parsed.hostname.lower()
        netloc = host
        if port is not None and port != _DEFAULT_PORTS[scheme]:
            netloc = f"{host}:{port}"
        path = parsed.path or "/"
        return urlunsplit((scheme, netloc, path, "", ""))

    def _canonicalize_file_uri(self, parsed) -> str:
        """Canonicalize supported POSIX file roots."""
        if not settings.root_allow_file_scheme:
            raise RootServiceValidationError("file_disabled")
        if parsed.netloc:
            raise RootServiceValidationError("file_authority_not_allowed")
        if not parsed.path or not parsed.path.startswith("/"):
            raise RootServiceValidationError("file_path_not_absolute")
        if "\\" in parsed.path or re.match(r"^/[A-Za-z]:", parsed.path):
            raise RootServiceValidationError("file_path_unsupported")
        if _ENCODED_SEPARATOR_PATTERN.search(parsed.path):
            raise RootServiceValidationError("file_path_unsafe_encoding")

        try:
            decoded_path = unquote_to_bytes(parsed.path).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RootServiceValidationError("file_path_unsafe_encoding") from exc

        if self._has_control_character(decoded_path) or "\\" in decoded_path:
            raise RootServiceValidationError("file_path_unsupported")
        if unquote_to_bytes(decoded_path).decode("utf-8", errors="ignore") != decoded_path:
            raise RootServiceValidationError("file_path_unsafe_encoding")
        if not decoded_path.startswith("/"):
            raise RootServiceValidationError("file_path_not_absolute")

        raw_parts = PurePosixPath(decoded_path).parts
        if ".." in raw_parts:
            raise RootServiceValidationError("file_path_traversal")

        canonical_path = "/" if raw_parts == ("/",) else "/" + "/".join(part for part in raw_parts if part != "/")
        canonical_parts = PurePosixPath(canonical_path).parts
        if not self._path_under_allowed_prefix(canonical_parts):
            raise RootServiceValidationError("file_path_outside_allowed_prefix")

        encoded_path = quote(canonical_path, safe="/")
        return urlunsplit(("file", "", encoded_path, "", ""))

    def _path_under_allowed_prefix(self, path_parts: tuple[str, ...]) -> bool:
        """Return whether path parts equal or descend from configured prefixes."""
        for prefix in settings.root_allowed_file_prefixes:
            prefix_parts = PurePosixPath(prefix).parts
            if path_parts == prefix_parts or path_parts[: len(prefix_parts)] == prefix_parts:
                return True
        return False

    @staticmethod
    def _has_control_character(value: str) -> bool:
        """Return true when value contains ASCII controls or DEL."""
        return any(ord(ch) < 32 or ord(ch) == 127 for ch in value)

    @staticmethod
    def _safe_scheme(uri: object) -> str:
        """Return sanitized scheme context for logs."""
        if not isinstance(uri, str):
            return "non-string"
        try:
            return (urlsplit(uri).scheme or "missing").lower()
        except Exception:
            return "invalid"

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
            >>> from mcpgateway.common.models import Root
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
            >>> from mcpgateway.common.models import Root
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
            >>> import logging
            >>> logging.disable(logging.CRITICAL)
            >>> from unittest.mock import AsyncMock
            >>> service = RootService()
            >>> bad_queue = AsyncMock()
            >>> bad_queue.put.side_effect = Exception("Queue error")
            >>> service._subscribers.append(bad_queue)
            >>> asyncio.run(service._notify_subscribers({"type": "test"}))
            >>> logging.disable(logging.NOTSET)
        """
        for queue in self._subscribers:
            try:
                await queue.put(event)
            except Exception as e:
                logger.error("Failed to notify subscriber: %s", e)


# Lazy singleton - created on first access, not at module import time.
# This avoids instantiation when only exception classes are imported.
_root_service_instance = None  # pylint: disable=invalid-name


def __getattr__(name: str):
    """Module-level __getattr__ for lazy singleton creation.

    Args:
        name: The attribute name being accessed.

    Returns:
        The root_service singleton instance if name is "root_service".

    Raises:
        AttributeError: If the attribute name is not "root_service".
    """
    global _root_service_instance  # pylint: disable=global-statement
    if name == "root_service":
        if _root_service_instance is None:
            _root_service_instance = RootService()
        return _root_service_instance
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
