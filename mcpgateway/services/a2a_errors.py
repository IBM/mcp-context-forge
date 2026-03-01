# Copyright (c) 2025 IBM Corp. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A2A agent exception hierarchy.

Extracted from ``a2a_service.py`` so that sibling modules
(``a2a_dispatcher.py``, ``tool_service.py``) can import them
without circular dependencies.
"""

# Standard
from typing import Optional


class A2AAgentError(Exception):
    """Base class for A2A agent-related errors.

    Examples:
        >>> try:
        ...     raise A2AAgentError("Agent operation failed")
        ... except A2AAgentError as e:
        ...     str(e)
        'Agent operation failed'
        >>> try:
        ...     raise A2AAgentError("Connection error")
        ... except Exception as e:
        ...     isinstance(e, A2AAgentError)
        True
    """


class A2AAgentNotFoundError(A2AAgentError):
    """Raised when a requested A2A agent is not found.

    Examples:
        >>> try:
        ...     raise A2AAgentNotFoundError("Agent 'test-agent' not found")
        ... except A2AAgentNotFoundError as e:
        ...     str(e)
        "Agent 'test-agent' not found"
        >>> try:
        ...     raise A2AAgentNotFoundError("No such agent")
        ... except A2AAgentError as e:
        ...     isinstance(e, A2AAgentError)  # Should inherit from A2AAgentError
        True
    """


class A2AAgentNameConflictError(A2AAgentError):
    """Raised when an A2A agent name conflicts with an existing one."""

    def __init__(self, name: str, is_active: bool = True, agent_id: Optional[str] = None, visibility: Optional[str] = "public"):
        """Initialize an A2AAgentNameConflictError exception.

        Args:
            name: The agent name that caused the conflict.
            is_active: Whether the conflicting agent is currently active.
            agent_id: The ID of the conflicting agent, if known.
            visibility: The visibility level of the conflicting agent (private, team, public).

        Examples:
            >>> error = A2AAgentNameConflictError("test-agent")
            >>> error.name
            'test-agent'
            >>> error.is_active
            True
            >>> error.agent_id is None
            True
            >>> "test-agent" in str(error)
            True
            >>>
            >>> # Test inactive agent conflict
            >>> error = A2AAgentNameConflictError("inactive-agent", is_active=False, agent_id="agent-123")
            >>> error.is_active
            False
            >>> error.agent_id
            'agent-123'
            >>> "inactive" in str(error)
            True
            >>> "agent-123" in str(error)
            True
        """
        self.name = name
        self.is_active = is_active
        self.agent_id = agent_id
        message = f"{visibility.capitalize()} A2A Agent already exists with name: {name}"
        if not is_active:
            message += f" (currently inactive, ID: {agent_id})"
        super().__init__(message)


class A2AAgentUpstreamError(A2AAgentError):
    """Raised when an upstream A2A agent returns an error (HTTP 4xx/5xx, gRPC failure).

    Route handlers should map this to HTTP 502 Bad Gateway to distinguish upstream
    failures from client-side request errors.

    Examples:
        >>> try:
        ...     raise A2AAgentUpstreamError("HTTP 500: Internal Server Error")
        ... except A2AAgentUpstreamError as e:
        ...     str(e)
        'HTTP 500: Internal Server Error'
        >>> isinstance(A2AAgentUpstreamError("x"), A2AAgentError)
        True
    """
