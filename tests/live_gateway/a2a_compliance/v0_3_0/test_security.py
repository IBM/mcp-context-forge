# -*- coding: utf-8 -*-
"""Security scheme advertisement for A2A 0.3.0.

Location: ./tests/live_gateway/a2a_compliance/v0_3_0/test_security.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

The A2A spec carries authentication discovery on the agent card itself:
``securitySchemes`` and ``securityRequirements`` define what auth a
caller must satisfy before invoking the agent. Even agents with no
auth requirements MUST emit these fields (typically empty lists/maps)
so clients can confirm "no auth" rather than guessing.
"""

from __future__ import annotations

import httpx
import pytest

pytestmark = [pytest.mark.a2a, pytest.mark.a2a_v0_3_0, pytest.mark.a2a_security]


@pytest.mark.xfail(
    reason="A2A-GAP-003: echo agent card omits securitySchemes (protobuf JSON default-drop)",
    strict=False,
)
@pytest.mark.asyncio
async def test_security_schemes_field_present(echo_agent_card_url: str) -> None:
    """The agent card MUST include a ``securitySchemes`` field, even if empty.

    Missing ``securitySchemes`` is ambiguous: clients can't distinguish
    "no auth needed" from "we forgot to advertise it". The protobuf
    schema makes the field always-present, but JSON serialization can
    drop empty maps unless emit-defaults is on — this test guards
    against that drift.
    """
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(echo_agent_card_url)
    card = response.json()
    assert "securitySchemes" in card, f"card MUST emit securitySchemes (even if empty): {card.keys()}"


@pytest.mark.xfail(
    reason="A2A-GAP-003: echo agent card omits securityRequirements (protobuf JSON default-drop)",
    strict=False,
)
@pytest.mark.asyncio
async def test_security_requirements_field_present(echo_agent_card_url: str) -> None:
    """The agent card MUST include a ``securityRequirements`` field, even if empty.

    Same rationale as ``securitySchemes`` — without explicit emission,
    clients can't tell "anonymous-allowed" from "spec-violating card".
    The echo agent has no auth, so the field will be empty.
    """
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(echo_agent_card_url)
    card = response.json()
    assert "securityRequirements" in card, f"card MUST emit securityRequirements (even if empty): {card.keys()}"
