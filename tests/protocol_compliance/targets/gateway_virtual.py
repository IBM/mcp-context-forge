"""Gateway virtual-server target: /servers/{id}/mcp on a live gateway."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastmcp.client import Client
from fastmcp.client.auth import BearerAuth
from fastmcp.client.transports import StreamableHttpTransport

from .base import ComplianceTarget, Transport


class GatewayVirtualServerTarget(ComplianceTarget):
    name = "gateway_virtual"
    supported_transports = frozenset({"http"})

    def __init__(self, base_url: str, auth_token: str, server_id: str) -> None:
        self._base_url = base_url
        self._auth_token = auth_token
        self._server_id = server_id

    @asynccontextmanager
    async def client(self, transport: Transport, **client_kwargs: object) -> AsyncIterator[Client]:
        if transport != "http":
            raise NotImplementedError(f"GatewayVirtualServerTarget transport '{transport}' not yet supported.")
        streamable = StreamableHttpTransport(
            url=f"{self._base_url}/servers/{self._server_id}/mcp/",
            auth=BearerAuth(self._auth_token),
        )
        async with Client(streamable, **client_kwargs) as connected:
            yield connected
