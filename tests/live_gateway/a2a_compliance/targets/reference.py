# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/a2a_compliance/targets/reference.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Reference A2A agent target.
Direct connection to the bundled ``a2a_echo_agent``: no gateway in
front, no federation hop. The ``ClientFactory.create_from_url`` call
resolves the well-known agent card, picks the JSON-RPC transport per
the card's advertised interfaces (the echo agent advertises JSON-RPC
only), and returns a connected ``a2a.client.Client``.

Construction uses a freshly-created ``httpx.AsyncClient`` per target
``client()`` invocation so concurrent tests don't share connection
pools — matters once parametrize-by-version doubles up the test count.

Phase 1 supports the ``jsonrpc`` transport literal only. To exercise
the SDK's gRPC transport against a future echo-agent build that
advertises gRPC, add ``"grpc"`` to the ``Transport`` literal and
extend ``supported_transports`` here; ``ClientFactory`` will pick the
right transport from the agent card automatically.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, ClassVar

import httpx
from a2a.client.client import Client, ClientConfig
from a2a.client.client_factory import ClientFactory

from .base import A2AComplianceTarget, Transport


class A2AReferenceTarget(A2AComplianceTarget):
    """JSON-RPC client against the live a2a_echo_agent.

    Constructed with the agent's **base URL** (resolved by the
    ``echo_agent_base_url`` fixture). The SDK's
    ``ClientFactory.create_from_url`` appends ``/.well-known/agent-card.json``
    itself; passing the already-appended card URL produces the
    pathological doubled path
    ``…/.well-known/agent-card.json/.well-known/agent-card.json``.

    Each ``client()`` call gets its own ``httpx.AsyncClient`` for
    clean teardown.
    """

    name: ClassVar[str] = "reference"
    supported_transports: ClassVar[frozenset[Transport]] = frozenset({"jsonrpc"})

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url

    @asynccontextmanager
    async def _open_client(self, transport: Transport, **client_kwargs: object) -> AsyncIterator[Client]:
        async with httpx.AsyncClient() as httpx_client:
            config = ClientConfig(httpx_client=httpx_client)
            factory = ClientFactory(config=config)
            client = await factory.create_from_url(self._base_url)
            async with client as connected:
                yield connected
