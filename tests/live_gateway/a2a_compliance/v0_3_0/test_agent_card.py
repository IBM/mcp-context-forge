# -*- coding: utf-8 -*-
"""Agent card structural compliance for A2A 0.3.0.

Location: ./tests/live_gateway/a2a_compliance/v0_3_0/test_agent_card.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

Phase 1 scope: raw-httpx against the reference target. The card-shape
contract is wire-level, so we drive it without the SDK abstraction.
When gateway native A2A passthrough lands (A2A-GAP-001) these checks
should be re-parametrized over the full target matrix via an
``agent_card_url`` resolver per target.
"""

from __future__ import annotations

import httpx
import pytest

pytestmark = [pytest.mark.a2a, pytest.mark.a2a_v0_3_0, pytest.mark.a2a_agent_card]


@pytest.mark.xfail(
    reason="A2A-GAP-002: echo agent card omits supportedInterfaces; advertises top-level protocolVersion",
    strict=False,
)
@pytest.mark.asyncio
async def test_agent_card_required_fields(echo_agent_card_url: str) -> None:
    """The agent card MUST advertise ``name``, ``version``, and ``supportedInterfaces``.

    The A2A 0.3.0 protobuf schema serializes these as camelCase
    (protobuf JSON convention); the echo agent honors that convention,
    so we assert on the camelCase wire form.
    """
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(echo_agent_card_url)
    assert response.status_code == 200, response.text[:200]
    card = response.json()
    for required in ("name", "version", "supportedInterfaces"):
        assert required in card, f"agent card missing required field {required!r}: {card}"


@pytest.mark.xfail(
    reason="A2A-GAP-002: echo agent card omits supportedInterfaces; advertises top-level protocolVersion",
    strict=False,
)
@pytest.mark.asyncio
async def test_supported_interfaces_non_empty(echo_agent_card_url: str) -> None:
    """``supportedInterfaces`` MUST be a non-empty list.

    A card with zero interfaces is unusable — a client cannot pick a
    transport. The echo agent advertises at least JSON-RPC.
    """
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(echo_agent_card_url)
    card = response.json()
    interfaces = card.get("supportedInterfaces", [])
    assert isinstance(interfaces, list), f"supportedInterfaces must be a list: {interfaces!r}"
    assert len(interfaces) >= 1, f"supportedInterfaces must be non-empty: {interfaces}"


@pytest.mark.asyncio
async def test_each_interface_has_protocol_version(echo_agent_card_url: str) -> None:
    """Every entry in ``supportedInterfaces`` MUST declare ``protocolVersion``.

    Without ``protocolVersion`` the SDK's ``ClientFactory`` can't decide
    between current and ``CompatJsonRpcTransport`` for legacy 0.3.x.
    """
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(echo_agent_card_url)
    card = response.json()
    for interface in card.get("supportedInterfaces", []):
        assert "protocolVersion" in interface, f"interface missing protocolVersion: {interface}"
        assert interface["protocolVersion"], f"protocolVersion must be non-empty: {interface}"
