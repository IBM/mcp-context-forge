# -*- coding: utf-8 -*-
"""Elicitation service for tracking and routing elicitation requests.

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
from uuid import uuid4

# First-Party
from mcpgateway.common.models import ElicitResult
from mcpgateway.services import task_scheduler, Priority

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
        schema: JSON Schema defining expected response structure
        future: AsyncIO future that resolves to ElicitResult when complete
    """

    request_id: str
    upstream_session_id: str
    downstream_session_id: str
    created_at: float
    timeout: float
    message: str
    schema: Dict[str, Any]
    future: asyncio.Future = field(default_factory=asyncio.Future)


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
        logger.info(f"ElicitationService initialized: timeout={default_timeout}s, " f"max_concurrent={max_concurrent}, cleanup_interval={cleanup_interval}s")

    async def start(self):
        """Start background cleanup task."""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = task_scheduler.schedule(self._cleanup_loop, Priority.NORMAL)
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
        logger.info(f"ElicitationService shutdown complete (cancelled {cancelled_count} pending requests)")

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
            logger.warning(f"Max concurrent elicitations reached: {self.max_concurrent}")
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
        logger.info(f"Created elicitation request {request_id}: upstream={upstream_session_id}, downstream={downstream_session_id}, timeout={timeout_val}s")

        try:
            # Wait for response with timeout
            result = await asyncio.wait_for(future, timeout=timeout_val)
            logger.info(f"Elicitation {request_id} completed: action={result.action}")
            return result
        except asyncio.TimeoutError:
            logger.warning(f"Elicitation {request_id} timed out after {timeout_val}s")
            raise
        finally:
            # Cleanup
            self._pending.pop(request_id, None)

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
            logger.warning(f"Attempted to complete unknown elicitation: {request_id}")
            return False

        if elicitation.future.done():
            logger.warning(f"Elicitation {request_id} already completed")
            return False

        elicitation.future.set_result(result)
        logger.debug(f"Completed elicitation {request_id}: action={result.action}")
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
        """Background task to periodically clean up expired elicitations."""
        while True:
            try:
                await asyncio.sleep(60)  # Run every minute
                await self._cleanup_expired()
            except asyncio.CancelledError:
                logger.info("Elicitation cleanup loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in elicitation cleanup loop: {e}", exc_info=True)

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
            logger.info(f"Cleaned up {len(expired)} expired elicitations")

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
                raise ValueError(f"Property '{prop_name}' has invalid type '{prop_type}'. " f"Only primitive types allowed: {allowed_types}")

            # Check for nested structures (not allowed per spec)
            if "properties" in prop_schema or "items" in prop_schema:
                raise ValueError(f"Property '{prop_name}' contains nested structure. " "MCP elicitation schemas must be flat.")

            # Validate string format if present
            if prop_type == "string" and "format" in prop_schema:
                fmt = prop_schema["format"]
                if fmt not in allowed_formats:
                    logger.warning(f"Property '{prop_name}' has non-standard format '{fmt}'. " f"Allowed formats: {allowed_formats}")

        logger.debug(f"Schema validation passed: {len(properties)} properties")


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
