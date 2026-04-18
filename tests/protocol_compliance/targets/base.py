"""ComplianceTarget abstraction.

A target is a runnable MCP endpoint plus the logic to construct a FastMCP
`Client` bound to it over a given transport. Each target declares which
transports it supports; the parametrized `client` fixture then enumerates
every `(target, transport)` pair the harness should exercise.
"""

from __future__ import annotations

import abc
from contextlib import AbstractAsyncContextManager
from typing import Literal

from fastmcp.client import Client

Transport = Literal["stdio", "sse", "http"]


class ComplianceTarget(abc.ABC):
    """A connectable MCP endpoint under test."""

    name: str
    supported_transports: frozenset[Transport]

    @abc.abstractmethod
    def client(self, transport: Transport, **client_kwargs: object) -> AbstractAsyncContextManager[Client]:
        """Return an async context manager yielding a connected Client.

        Implementations are responsible for spinning up any required server
        process or in-process wiring, running the initialize handshake, and
        tearing everything down on context exit.

        ``client_kwargs`` are forwarded to the FastMCP ``Client`` constructor
        so tests can wire sampling/elicitation/log/progress/roots handlers.
        """
