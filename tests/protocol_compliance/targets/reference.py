"""Reference MCP server target.

Phase 2 supports stdio only, via FastMCP's in-process `Client(mcp)` wiring
(no subprocess). SSE and Streamable HTTP arrive in Phase 4 together with
the gateway lifecycle plumbing they share.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastmcp.client import Client

from .base import ComplianceTarget, Transport


class ReferenceTarget(ComplianceTarget):
    name = "reference"
    supported_transports = frozenset({"stdio"})

    @asynccontextmanager
    async def client(self, transport: Transport, **client_kwargs: object) -> AsyncIterator[Client]:
        if transport != "stdio":
            raise NotImplementedError(f"ReferenceTarget transport '{transport}' is scheduled for Phase 4.")
        from compliance_reference_server.server import mcp

        async with Client(mcp, **client_kwargs) as connected:
            yield connected
