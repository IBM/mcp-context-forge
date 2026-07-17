# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/a2a_compliance/v0_3_0/test_agent_card.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Agent card structural compliance for A2A 0.3.0.
The A2A 0.3.0 ``AgentCard`` schema is fundamentally different from
1.0.0 — transport advertisement lives at the top level
(``protocol_version``, ``url``, ``preferred_transport``,
``additional_interfaces``) rather than in a ``supported_interfaces``
array. These tests assert on the v0.3.0 shape; the v1.0.0 sibling
under ``../v1_0_0/`` asserts the 1.0.0 shape on the same agent process
(the echo agent emits a 0.3.0-shaped card regardless of advertised
version — see A2A-GAP-002 for the 1.0.0 case).
"""

from __future__ import annotations

import httpx
import pytest

pytestmark = [pytest.mark.a2a, pytest.mark.a2a_v0_3_0, pytest.mark.a2a_agent_card]


@pytest.mark.asyncio
async def test_agent_card_required_fields(echo_agent_card_url: str) -> None:
    """The v0.3.0 agent card MUST advertise ``name``, ``version``, ``protocolVersion``, ``url``.

    Per the v0.3.0 ``AgentCard`` protobuf schema captured during
    Phase-0 introspection (``a2a.compat.v0_3.types.AgentCard``), these
    four fields are the minimum a discovery client needs to bootstrap
    a JSON-RPC session.
    """
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(echo_agent_card_url)
    assert response.status_code == 200, response.text[:200]
    card = response.json()
    for required in ("name", "version", "protocolVersion", "url"):
        assert required in card, f"agent card missing required field {required!r}: {card}"


@pytest.mark.asyncio
async def test_top_level_protocol_version_and_url_non_empty(echo_agent_card_url: str) -> None:
    """``protocolVersion`` and ``url`` MUST be non-empty strings.

    Empty values parse as protobuf defaults but leave clients with no
    actionable transport target.
    """
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(echo_agent_card_url)
    card = response.json()
    protocol_version = card.get("protocolVersion")
    url = card.get("url")
    assert isinstance(protocol_version, str) and protocol_version, f"protocolVersion must be a non-empty string: {protocol_version!r}"
    assert isinstance(url, str) and url, f"url must be a non-empty string: {url!r}"


@pytest.mark.asyncio
async def test_optional_transport_fields_well_typed(echo_agent_card_url: str) -> None:
    """If ``additionalInterfaces`` or ``preferredTransport`` are present, their shapes MUST match the schema.

    Both fields are optional in v0.3.0; protobuf JSON conventions
    legitimately omit defaults. This test validates shape *when*
    emitted.
    """
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(echo_agent_card_url)
    card = response.json()
    if "additionalInterfaces" in card:
        interfaces = card["additionalInterfaces"]
        assert isinstance(interfaces, list), f"additionalInterfaces must be a list when present: {interfaces!r}"
        for interface in interfaces:
            assert isinstance(interface, dict), f"each additionalInterfaces entry must be an object: {interface!r}"
    if "preferredTransport" in card:
        preferred = card["preferredTransport"]
        assert isinstance(preferred, str), f"preferredTransport must be a string when present: {preferred!r}"
