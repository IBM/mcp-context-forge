# -*- coding: utf-8 -*-
"""Location: ./tests/protocol_compliance/targets/gateway_proxy.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Gateway-proxy target: live ContextForge serving /mcp backed by the reference server.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, ClassVar

from fastmcp.client import Client
from fastmcp.client.auth import BearerAuth
from fastmcp.client.transports import StreamableHttpTransport

from .base import ComplianceTarget, Transport


class GatewayProxyTarget(ComplianceTarget):
    name: ClassVar[str] = "gateway_proxy"
    supported_transports: ClassVar[frozenset[Transport]] = frozenset({"http"})

    def __init__(self, base_url: str, auth_token: str) -> None:
        self._base_url = base_url
        self._auth_token = auth_token

    @asynccontextmanager
    async def _open_client(self, transport: Transport, **client_kwargs: object) -> AsyncIterator[Client]:
        # Trailing slash matters — see the IPv6/path-rewrite notes in
        # tests/e2e/test_mcp_protocol_e2e.py::mcp_url.
        streamable = StreamableHttpTransport(
            url=f"{self._base_url}/mcp/",
            auth=BearerAuth(self._auth_token),
        )
        async with Client(streamable, **client_kwargs) as connected:
            yield connected
