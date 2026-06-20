# -*- coding: utf-8 -*-
"""Gateway-proxy A2A target (placeholder).

Location: ./tests/live_gateway/a2a_compliance/targets/gateway_proxy.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

Phase 1 placeholder. ContextForge does not currently expose a native
A2A JSON-RPC + well-known-card surface that an
``a2a.client.ClientFactory.create_from_url`` call can connect to — the
public ``/a2a/*`` paths are admin CRUD plus a custom REST invocation
endpoint, not the protocol-level transport. See **A2A-GAP-001** in
``COMPLIANCE_GAPS.md`` for the contract this target will satisfy once
native passthrough lands.

Until then, ``_open_client`` raises ``NotImplementedError``. Tests
that exercise the matrix mark themselves ``xfail`` on this target via:

    from ..helpers.compliance import xfail_on
    xfail_on(request, "gateway_proxy", reason="A2A-GAP-001: ...")

so the cell reports ``XFAIL`` rather than ``ERROR`` and a future fix
surfaces as ``XPASS`` — the cue to drop the ``xfail_on`` and close the
gap entry.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, ClassVar

from a2a.client.client import Client

from .base import A2AComplianceTarget, Transport


class A2AGatewayProxyTarget(A2AComplianceTarget):
    """A2A via ContextForge gateway-as-proxy. Phase-1 placeholder."""

    name: ClassVar[str] = "gateway_proxy"
    supported_transports: ClassVar[frozenset[Transport]] = frozenset({"jsonrpc"})

    def __init__(self, base_url: str, auth_token: str, agent_name: str) -> None:
        self._base_url = base_url
        self._auth_token = auth_token
        self._agent_name = agent_name

    @asynccontextmanager
    async def _open_client(self, transport: Transport, **client_kwargs: object) -> AsyncIterator[Client]:
        raise NotImplementedError(
            "A2A-GAP-001: ContextForge lacks native A2A passthrough at a " "public JSON-RPC + well-known-card route. See " "tests/live_gateway/a2a_compliance/COMPLIANCE_GAPS.md."
        )
        yield  # pragma: no cover - unreachable, present only so the function is an async generator
