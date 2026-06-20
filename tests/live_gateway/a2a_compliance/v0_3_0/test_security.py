# -*- coding: utf-8 -*-
"""Security scheme advertisement for A2A 0.3.0.

Location: ./tests/live_gateway/a2a_compliance/v0_3_0/test_security.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

A2A 0.3.0 carries authentication discovery on the card via
``securitySchemes`` (map) and ``security`` (list of requirement
references). v1.0.0 renamed the latter to ``securityRequirements``.

Per the protobuf JSON convention, default-valued fields (empty map,
empty list) MAY be omitted on the wire — absence is semantically
equivalent to "no auth required". This suite validates *shape when
present* rather than mandating explicit emission (the earlier strict
assertions were the basis of A2A-GAP-003, since reclassified as a
test-side spec misreading).
"""

from __future__ import annotations

import httpx
import pytest

pytestmark = [pytest.mark.a2a, pytest.mark.a2a_v0_3_0, pytest.mark.a2a_security]


@pytest.mark.asyncio
async def test_security_schemes_well_typed_when_present(echo_agent_card_url: str) -> None:
    """If the card emits ``securitySchemes``, it MUST be a JSON object (map).

    Empty map means "no auth schemes advertised" — valid. Omission
    means the same per protobuf JSON default-drop. The bug we guard
    against is the field being present with a non-map shape.
    """
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(echo_agent_card_url)
    card = response.json()
    if "securitySchemes" in card:
        schemes = card["securitySchemes"]
        assert isinstance(schemes, dict), f"securitySchemes must be a JSON object when present: {schemes!r}"


@pytest.mark.asyncio
async def test_security_well_typed_when_present(echo_agent_card_url: str) -> None:
    """If the card emits ``security`` (v0.3.0 requirement list), it MUST be a JSON array.

    v0.3.0 uses ``security`` (singular). v1.0.0 renamed it to
    ``securityRequirements``. The protobuf JSON contract is "list of
    SecurityRequirement objects, or absent for no requirements".
    """
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(echo_agent_card_url)
    card = response.json()
    if "security" in card:
        security = card["security"]
        assert isinstance(security, list), f"security must be a JSON array when present: {security!r}"
        for entry in security:
            assert isinstance(entry, dict), f"each security entry must be a JSON object: {entry!r}"
