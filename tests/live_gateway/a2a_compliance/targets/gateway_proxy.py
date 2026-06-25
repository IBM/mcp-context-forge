# -*- coding: utf-8 -*-
"""Gateway-proxy A2A target — live ContextForge passthrough.

Location: ./tests/live_gateway/a2a_compliance/targets/gateway_proxy.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

Plan T29 (Wave 7) wired this target up to the native A2A passthrough
ContextForge gained in Wave 3 (T11 + T12 + T14). The
``ClientFactory.create_from_url`` call resolves the gateway's
synthesized agent card at
``/a2a/{name}/.well-known/agent-card.json`` and picks the JSON-RPC
transport per the card's advertised interfaces (per-interface
``protocolVersion`` and a JSONRPC ``protocolBinding`` — D7 + D8).

Mirrors the canonical shape in ``targets/reference.py`` so the same
test bodies run identically across the matrix; the only behavioral
difference is that this target's HTTP traffic terminates at the
gateway (which then forwards to the registered agent) instead of
the agent itself. The ``Authorization: Bearer <token>`` header is
required because the gateway's ``/a2a/*`` routes are guarded by
``HttpAuthMiddleware`` + per-method RBAC (T12 step 6).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, ClassVar

import httpx
from a2a.client.client import Client, ClientConfig
from a2a.client.client_factory import ClientFactory

from .base import A2AComplianceTarget, Transport


class A2AGatewayProxyTarget(A2AComplianceTarget):
    """A2A via ContextForge native passthrough at ``/a2a/{name}``."""

    name: ClassVar[str] = "gateway_proxy"
    supported_transports: ClassVar[frozenset[Transport]] = frozenset({"jsonrpc"})

    def __init__(self, base_url: str, auth_token: str, agent_name: str) -> None:
        self._base_url = base_url
        self._auth_token = auth_token
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
            client = await factory.create_from_url(f"{self._base_url}/a2a/{self._agent_name}")
            async with client as connected:
                yield connected
