# -*- coding: utf-8 -*-
"""Well-known endpoint routing for A2A 0.3.0.

Location: ./tests/live_gateway/a2a_compliance/v0_3_0/test_well_known.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

The well-known card endpoint is the single discovery hook in A2A — an
agent that doesn't serve a card at the canonical path is invisible to
``ClientFactory.create_from_url``. These tests validate the endpoint
exists and returns parseable JSON with the v0.3.0 card shape.
"""

from __future__ import annotations

import httpx
import pytest

pytestmark = [pytest.mark.a2a, pytest.mark.a2a_v0_3_0, pytest.mark.a2a_well_known]


@pytest.mark.asyncio
async def test_canonical_well_known_route(echo_agent_base_url: str) -> None:
    """``GET /.well-known/agent-card.json`` MUST return 200 + JSON body."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(f"{echo_agent_base_url}/.well-known/agent-card.json")
    assert response.status_code == 200, response.text[:200]
    assert response.headers.get("content-type", "").startswith("application/json"), response.headers
    body = response.json()
    assert isinstance(body, dict), f"card body must be a JSON object: {body!r}"


@pytest.mark.asyncio
async def test_compat_well_known_alias(echo_agent_base_url: str) -> None:
    """``GET /.well-known/agent.json`` MUST return the same shape as the canonical path.

    The agent advertises both paths for back-compat with pre-0.3 A2A
    clients. The canonical and compat responses must be equivalent.
    """
    async with httpx.AsyncClient(timeout=5.0) as client:
        canonical = await client.get(f"{echo_agent_base_url}/.well-known/agent-card.json")
        compat = await client.get(f"{echo_agent_base_url}/.well-known/agent.json")
    assert canonical.status_code == 200, canonical.text[:200]
    assert compat.status_code == 200, compat.text[:200]
    assert canonical.json() == compat.json(), "well-known canonical and compat aliases must return identical bodies"


@pytest.mark.asyncio
async def test_extended_agent_card_route(echo_agent_base_url: str) -> None:
    """``GET /extendedAgentCard`` MUST return 200 + v0.3.0-shaped card.

    The extended card surfaces fields hidden from anonymous discovery.
    The echo agent has no auth, so the call succeeds unconditionally
    and returns at least the same required fields as the canonical
    card (``name``, ``version``, ``protocolVersion``, ``url`` for v0.3.0).
    """
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(f"{echo_agent_base_url}/extendedAgentCard")
    assert response.status_code == 200, response.text[:200]
    body = response.json()
    assert isinstance(body, dict), f"extended card body must be a JSON object: {body!r}"
    for required in ("name", "version", "protocolVersion", "url"):
        assert required in body, f"extended card missing field {required!r}: {body}"
