# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/elicitation_service.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Elicitation service for tracking and routing elicitation requests.

This service manages the lifecycle of MCP elicitation requests, which allow
servers to request structured user input through connected clients.

Per MCP specification 2025-06-18, elicitation follows a server→client request
pattern where servers send elicitation/create requests, and clients respond
with user input (accept/decline/cancel actions).
"""

# Standard
import asyncio
from dataclasses import dataclass, field
import logging
import time
from typing import Any, Dict, Optional
from urllib.parse import urlparse
from uuid import uuid4

# First-Party
from mcpgateway.common.models import ElicitResult

logger = logging.getLogger(__name__)


@dataclass
class PendingElicitation:
    """Tracks a pending elicitation request awaiting client response.

    Attributes:
        request_id: Unique identifier for this elicitation request
        upstream_session_id: Session that initiated the request (server)
        downstream_session_id: Session handling the request (client)
        created_at: Unix timestamp when request was created
        timeout: Maximum wait time in seconds
        message: User-facing message describing what input is needed
        schema: JSON Schema defining expected response structure (form mode only)
        future: AsyncIO future that resolves to ElicitResult when complete
        mode: Elicitation mode, "form" (default) or "url" (SEP-1036)
        url: Target URL for URL-mode elicitation (None for form mode)
        elicitation_id: Server-provided opaque correlation id for URL-mode
            elicitations; used to route the later completion notification.
    """

    request_id: str
    upstream_session_id: str
    downstream_session_id: str
    created_at: float
    timeout: float
    message: str
    schema: Optional[Dict[str, Any]] = None
    future: asyncio.Future = field(default_factory=asyncio.Future)
    mode: str = "form"
    url: Optional[str] = None
    elicitation_id: Optional[str] = None


class ElicitationService:
    """Service for managing elicitation request lifecycle.

    This service provides:
    - Tracking of pending elicitation requests
    - Response routing back to original requesters
    - Timeout enforcement and cleanup
    - Schema validation per MCP spec (primitive types only)
    - Concurrency limits to prevent resource exhaustion

    The service maintains a global registry of pending requests and ensures
    proper cleanup through timeout enforcement and background cleanup tasks.
    """

    def __init__(
        self,
        default_timeout: int = 60,
        max_concurrent: int = 100,
        cleanup_interval: int = 300,  # 5 minutes
    ):
        """Initialize the elicitation service.

        Args:
            default_timeout: Default timeout for elicitation requests (seconds)
            max_concurrent: Maximum number of concurrent elicitations
            cleanup_interval: How often to run cleanup task (seconds)
        """
        self.default_timeout = default_timeout
        self.max_concurrent = max_concurrent
        self.cleanup_interval = cleanup_interval
        self._pending: Dict[str, PendingElicitation] = {}
        self._cleanup_task: Optional[asyncio.Task] = None
        logger.info(f"ElicitationService initialized: timeout={default_timeout}s, max_concurrent={max_concurrent}, cleanup_interval={cleanup_interval}s")

    async def start(self):
        """Start background cleanup task."""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            logger.info("Elicitation cleanup task started")

    async def shutdown(self):
        """Shutdown service and cancel all pending requests."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        # Cancel all pending requests
        cancelled_count = 0
        for elicitation in list(self._pending.values()):
            if not elicitation.future.done():
                elicitation.future.set_exception(RuntimeError("ElicitationService shutting down"))
                cancelled_count += 1

        self._pending.clear()
        logger.info("ElicitationService shutdown complete (cancelled %s pending requests)", cancelled_count)

    async def create_elicitation(self, upstream_session_id: str, downstream_session_id: str, message: str, requested_schema: Dict[str, Any], timeout: Optional[float] = None) -> ElicitResult:
        """Create and track an elicitation request.

        This method initiates an elicitation request, validates the schema,
        tracks the request, and awaits the client's response with timeout.

        Args:
            upstream_session_id: Session that initiated the request (server)
            downstream_session_id: Session that will handle the request (client)
            message: Message to present to user
            requested_schema: JSON Schema for expected response
            timeout: Optional timeout override (default: self.default_timeout)

        Returns:
            ElicitResult from the client containing action and optional content

        Raises:
            ValueError: If max concurrent limit reached or invalid schema
            asyncio.TimeoutError: If request times out waiting for response
        """
        # Check concurrent limit
        if len(self._pending) >= self.max_concurrent:
            logger.warning("Max concurrent elicitations reached: %s", self.max_concurrent)
            raise ValueError(f"Maximum concurrent elicitations ({self.max_concurrent}) reached")

        # Validate schema (primitive types only per MCP spec)
        self._validate_schema(requested_schema)

        # Create tracking entry
        request_id = str(uuid4())
        timeout_val = timeout if timeout is not None else self.default_timeout
        future: asyncio.Future = asyncio.Future()

        elicitation = PendingElicitation(
            request_id=request_id,
            upstream_session_id=upstream_session_id,
            downstream_session_id=downstream_session_id,
            created_at=time.time(),
            timeout=timeout_val,
            message=message,
            schema=requested_schema,
            future=future,
        )

        self._pending[request_id] = elicitation
        logger.info("Created elicitation request %s: upstream=%s, downstream=%s, timeout=%ss", request_id, upstream_session_id, downstream_session_id, timeout_val)

        try:
            # Wait for response with timeout
            result = await asyncio.wait_for(future, timeout=timeout_val)
            logger.info("Elicitation %s completed: action=%s", request_id, result.action)
            return result
        except asyncio.TimeoutError:
            logger.warning("Elicitation %s timed out after %ss", request_id, timeout_val)
            raise
        finally:
            # Cleanup
            self._pending.pop(request_id, None)

    async def create_url_elicitation(
        self,
        upstream_session_id: str,
        downstream_session_id: str,
        message: str,
        url: str,
        elicitation_id: str,
        timeout: Optional[float] = None,
        require_https: bool = True,
    ) -> ElicitResult:
        """Create and track a URL-mode elicitation request (SEP-1036).

        URL mode directs the user to an external URL for out-of-band interactions
        (OAuth, credential collection, payments). No schema is validated; instead
        the URL is validated and the request awaits the client's consent action.

        Args:
            upstream_session_id: Session that initiated the request (server)
            downstream_session_id: Session that will handle the request (client)
            message: Message to present to the user
            url: URL the user should navigate to
            elicitation_id: Server-provided opaque correlation id
            timeout: Optional timeout override (default: self.default_timeout)
            require_https: Reject non-HTTPS URLs when True

        Returns:
            ElicitResult from the client containing the consent action

        Raises:
            ValueError: If max concurrent limit reached or URL is invalid
            asyncio.TimeoutError: If request times out waiting for response
        """
        # Check concurrent limit
        if len(self._pending) >= self.max_concurrent:
            logger.warning("Max concurrent elicitations reached: %s", self.max_concurrent)
            raise ValueError(f"Maximum concurrent elicitations ({self.max_concurrent}) reached")

        # Validate URL (scheme / https requirement) per SEP-1036 security guidance
        self._validate_url(url, require_https=require_https)

        # Create tracking entry
        request_id = str(uuid4())
        timeout_val = timeout if timeout is not None else self.default_timeout
        future: asyncio.Future = asyncio.Future()

        elicitation = PendingElicitation(
            request_id=request_id,
            upstream_session_id=upstream_session_id,
            downstream_session_id=downstream_session_id,
            created_at=time.time(),
            timeout=timeout_val,
            message=message,
            schema=None,
            future=future,
            mode="url",
            url=url,
            elicitation_id=elicitation_id,
        )

        self._pending[request_id] = elicitation
        logger.info(
            "Created URL elicitation request %s (elicitationId=%s): upstream=%s, downstream=%s, timeout=%ss", request_id, elicitation_id, upstream_session_id, downstream_session_id, timeout_val
        )

        try:
            result = await asyncio.wait_for(future, timeout=timeout_val)
            logger.info("URL elicitation %s completed: action=%s", request_id, result.action)
            return result
        except asyncio.TimeoutError:
            logger.warning("URL elicitation %s timed out after %ss", request_id, timeout_val)
            raise
        finally:
            self._pending.pop(request_id, None)

    def get_pending_by_elicitation_id(self, elicitation_id: str) -> Optional[PendingElicitation]:
        """Look up a pending URL-mode elicitation by its server-provided id.

        Used to route a ``notifications/elicitation/complete`` notification back to
        the client session that owns the matching elicitation.

        Args:
            elicitation_id: The server-provided opaque correlation id

        Returns:
            PendingElicitation if a matching URL-mode request is pending, else None
        """
        for elicitation in self._pending.values():
            if elicitation.elicitation_id == elicitation_id:
                return elicitation
        return None

    def complete_elicitation(self, request_id: str, result: ElicitResult) -> bool:
        """Complete a pending elicitation with a result from the client.

        Args:
            request_id: ID of the elicitation request to complete
            result: The client's response (action + optional content)

        Returns:
            True if request was found and completed, False otherwise
        """
        elicitation = self._pending.get(request_id)
        if not elicitation:
            logger.warning("Attempted to complete unknown elicitation: %s", request_id)
            return False

        if elicitation.future.done():
            logger.warning("Elicitation %s already completed", request_id)
            return False

        elicitation.future.set_result(result)
        logger.debug("Completed elicitation %s: action=%s", request_id, result.action)
        return True

    def get_pending_elicitation(self, request_id: str) -> Optional[PendingElicitation]:
        """Get a pending elicitation by ID.

        Args:
            request_id: The elicitation request ID to lookup

        Returns:
            PendingElicitation if found, None otherwise
        """
        return self._pending.get(request_id)

    def get_pending_count(self) -> int:
        """Get count of pending elicitations.

        Returns:
            Number of currently pending elicitation requests
        """
        return len(self._pending)

    def get_pending_for_session(self, session_id: str) -> list[PendingElicitation]:
        """Get all pending elicitations for a specific session.

        Args:
            session_id: Session ID to filter by (upstream or downstream)

        Returns:
            List of PendingElicitation objects involving this session
        """
        return [e for e in self._pending.values() if session_id in (e.upstream_session_id, e.downstream_session_id)]

    async def _cleanup_loop(self):
        """Background task to periodically clean up expired elicitations.

        Raises:
            asyncio.CancelledError: If the task is cancelled during shutdown.
        """
        while True:
            try:
                await asyncio.sleep(60)  # Run every minute
                await self._cleanup_expired()
            except asyncio.CancelledError:
                logger.info("Elicitation cleanup loop cancelled")
                raise
            except Exception as e:
                logger.error("Error in elicitation cleanup loop: %s", e, exc_info=True)

    async def _cleanup_expired(self):
        """Remove expired elicitation requests that have timed out."""
        now = time.time()
        expired = []

        for request_id, elicitation in self._pending.items():
            age = now - elicitation.created_at
            if age > elicitation.timeout:
                expired.append(request_id)
                if not elicitation.future.done():
                    elicitation.future.set_exception(asyncio.TimeoutError(f"Elicitation expired after {age:.1f}s"))

        for request_id in expired:
            self._pending.pop(request_id, None)

        if expired:
            logger.info("Cleaned up %s expired elicitations", len(expired))

    def _validate_schema(self, schema: Dict[str, Any]):
        """Validate that schema only contains primitive types per MCP spec.

        MCP spec restricts elicitation schemas to flat objects with primitive properties:
        - string (with optional format: email, uri, date, date-time)
        - number / integer (with optional min/max)
        - boolean
        - enum (array of string values)

        Complex types (nested objects, arrays, refs) are not allowed to keep
        client implementation simple.

        Args:
            schema: JSON Schema object to validate

        Raises:
            ValueError: If schema contains complex types or invalid structure
        """
        if not isinstance(schema, dict):
            raise ValueError("Schema must be an object")

        if schema.get("type") != "object":
            raise ValueError("Top-level schema must be type 'object'")

        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            raise ValueError("Schema properties must be an object")

        # Validate each property is primitive
        allowed_types = {"string", "number", "integer", "boolean"}
        allowed_formats = {"email", "uri", "date", "date-time"}

        for prop_name, prop_schema in properties.items():
            if not isinstance(prop_schema, dict):
                raise ValueError(f"Property '{prop_name}' schema must be an object")

            prop_type = prop_schema.get("type")
            if prop_type not in allowed_types:
                raise ValueError(f"Property '{prop_name}' has invalid type '{prop_type}'. Only primitive types allowed: {allowed_types}")

            # Check for nested structures (not allowed per spec)
            if "properties" in prop_schema or "items" in prop_schema:
                raise ValueError(f"Property '{prop_name}' contains nested structure. MCP elicitation schemas must be flat.")

            # Validate string format if present
            if prop_type == "string" and "format" in prop_schema:
                fmt = prop_schema["format"]
                if fmt not in allowed_formats:
                    logger.warning(f"Property '{prop_name}' has non-standard format '{fmt}'. Allowed formats: {allowed_formats}")

        logger.debug("Schema validation passed: %s properties", len(properties))

    def _validate_url(self, url: str, require_https: bool = True):
        """Validate a URL-mode elicitation target URL (SEP-1036).

        SEP-1036 directs URL mode at sensitive out-of-band flows, so the URL must
        be absolute and (in production) use HTTPS. ``localhost``/loopback hosts are
        permitted over HTTP to support local development.

        Args:
            url: The URL to validate
            require_https: Reject non-HTTPS URLs (except loopback hosts) when True

        Raises:
            ValueError: If the URL is empty, not absolute, or violates the scheme policy
        """
        if not isinstance(url, str) or not url.strip():
            raise ValueError("URL-mode elicitation requires a non-empty 'url'")

        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError(f"Invalid elicitation URL '{url}': must be an absolute URL with scheme and host")

        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"Invalid elicitation URL scheme '{parsed.scheme}': only http/https are allowed")

        if require_https and parsed.scheme != "https":
            host = (parsed.hostname or "").lower()
            if host not in ("localhost", "127.0.0.1", "::1"):
                raise ValueError(f"Insecure elicitation URL '{url}': https is required (set MCPGATEWAY_ELICITATION_URL_REQUIRE_HTTPS=false to allow http)")

        logger.debug("URL validation passed: %s", url)


# Global singleton instance
_elicitation_service: Optional[ElicitationService] = None


def get_elicitation_service() -> ElicitationService:
    """Get the global ElicitationService singleton instance.

    Returns:
        The global ElicitationService instance
    """
    global _elicitation_service  # pylint: disable=global-statement
    if _elicitation_service is None:
        _elicitation_service = ElicitationService()
    return _elicitation_service


def set_elicitation_service(service: ElicitationService):
    """Set the global ElicitationService instance.

    This is primarily used for testing to inject mock services.

    Args:
        service: The ElicitationService instance to use globally
    """
    global _elicitation_service  # pylint: disable=global-statement
    _elicitation_service = service
