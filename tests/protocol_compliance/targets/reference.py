# -*- coding: utf-8 -*-
"""Location: ./tests/protocol_compliance/targets/reference.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Reference MCP server target.

Currently supports stdio only, via FastMCP's in-process ``Client(mcp)``
wiring (no subprocess). SSE / Streamable HTTP can be added by extending
``supported_transports`` and expanding ``_open_client``; the base class's
transport-validation wrapper will then route appropriately.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, ClassVar

from fastmcp.client import Client

from .base import ComplianceTarget, Transport


class ReferenceTarget(ComplianceTarget):
    name: ClassVar[str] = "reference"
    supported_transports: ClassVar[frozenset[Transport]] = frozenset({"stdio"})

    @asynccontextmanager
    async def _open_client(self, transport: Transport, **client_kwargs: object) -> AsyncIterator[Client]:
        from compliance_reference_server.server import mcp

        async with Client(mcp, **client_kwargs) as connected:
            yield connected
