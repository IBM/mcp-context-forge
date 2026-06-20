# -*- coding: utf-8 -*-
"""Gateway virtual-server A2A target (placeholder).

Location: ./tests/live_gateway/a2a_compliance/targets/gateway_virtual.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

Phase 1 placeholder. Same A2A-GAP-001 blocker as ``gateway_proxy.py``;
once ContextForge exposes a per-virtual-server native A2A endpoint
(e.g. ``/servers/{id}/a2a/{agent_name}/`` with the well-known card),
this target gets a real ``_open_client`` body. Until then,
``NotImplementedError`` propagates and tests xfail the cell.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, ClassVar

from a2a.client.client import Client

from .base import A2AComplianceTarget, Transport


class A2AGatewayVirtualServerTarget(A2AComplianceTarget):
    """A2A via a ContextForge virtual server. Phase-1 placeholder."""

    name: ClassVar[str] = "gateway_virtual"
    supported_transports: ClassVar[frozenset[Transport]] = frozenset({"jsonrpc"})

    def __init__(self, base_url: str, auth_token: str, server_id: str, agent_name: str) -> None:
        self._base_url = base_url
        self._auth_token = auth_token
        self._server_id = server_id
        self._agent_name = agent_name

    @asynccontextmanager
    async def _open_client(self, transport: Transport, **client_kwargs: object) -> AsyncIterator[Client]:
        raise NotImplementedError("A2A-GAP-001: ContextForge lacks native A2A passthrough on the " "virtual-server path. See " "tests/live_gateway/a2a_compliance/COMPLIANCE_GAPS.md.")
        yield  # pragma: no cover - unreachable, present only so the function is an async generator
