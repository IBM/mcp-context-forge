# -*- coding: utf-8 -*-
"""Gateway virtual-server A2A target — live v-server passthrough.

Location: ./tests/live_gateway/a2a_compliance/targets/gateway_virtual.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

Plan T29 (Wave 7) wired this target up to the v-server-scoped native
A2A passthrough ContextForge gained in Wave 4 (T16 path rewrite
middleware + the same T11 + T12 + T14 handlers). The
``ClientFactory.create_from_url`` call resolves the gateway's
synthesized agent card at
``/servers/{server_id}/a2a/{name}/.well-known/agent-card.json``,
which the T16 middleware rewrites onto the bare per-agent handlers
with ``request.scope["a2a_server_id"]`` populated. The synthesizer
enforces the three-level conjunctive v-server access (server
visibility AND agent visibility AND membership) per Amendment B.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, ClassVar

import httpx
from a2a.client.client import Client, ClientConfig
from a2a.client.client_factory import ClientFactory

from .base import A2AComplianceTarget, Transport


class A2AGatewayVirtualServerTarget(A2AComplianceTarget):
    """A2A via a ContextForge virtual server at ``/servers/{id}/a2a/{name}``."""

    name: ClassVar[str] = "gateway_virtual"
    supported_transports: ClassVar[frozenset[Transport]] = frozenset({"jsonrpc"})

    def __init__(self, base_url: str, auth_token: str, server_id: str, agent_name: str) -> None:
        self._base_url = base_url
        self._auth_token = auth_token
        self._server_id = server_id
        self._agent_name = agent_name

    @asynccontextmanager
    async def _open_client(self, transport: Transport, **client_kwargs: object) -> AsyncIterator[Client]:
        del transport, client_kwargs
        async with httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {self._auth_token}"},
        ) as httpx_client:
            config = ClientConfig(httpx_client=httpx_client)
            factory = ClientFactory(config=config)
            client = await factory.create_from_url(f"{self._base_url}/servers/{self._server_id}/a2a/{self._agent_name}")
            async with client as connected:
                yield connected
