# -*- coding: utf-8 -*-
"""Protocol version advertisement for A2A 0.3.0.

Location: ./tests/live_gateway/a2a_compliance/v0_3_0/test_version_negotiation.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

The 0.3.0 suite pins the expected ``protocolVersion`` to ``0.3.0``.
Version negotiation in v0.3.0 reads the top-level ``protocolVersion``
field (unlike v1.0.0 which uses ``supportedInterfaces[*].protocolVersion``).
The SDK's ``ClientFactory`` routes via ``CompatJsonRpcTransport`` for
any version in the 0.3.x range.
"""

from __future__ import annotations

import httpx
import pytest

pytestmark = [pytest.mark.a2a, pytest.mark.a2a_v0_3_0, pytest.mark.a2a_versioning]

_EXPECTED_VERSION = "0.3.0"


@pytest.mark.asyncio
async def test_card_advertises_expected_protocol_version(echo_agent_card_url: str) -> None:
    """The card's top-level ``protocolVersion`` MUST equal ``0.3.0``.

    v0.3.0 puts protocolVersion at the card root (not inside a
    supportedInterfaces array, which is a v1.0.0-only construct).
    """
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(echo_agent_card_url)
    card = response.json()
    advertised = card.get("protocolVersion")
    assert advertised == _EXPECTED_VERSION, f"card.protocolVersion={advertised!r}; expected {_EXPECTED_VERSION!r}"


@pytest.mark.asyncio
async def test_protocol_version_is_semver_shape(echo_agent_card_url: str) -> None:
    """``protocolVersion`` MUST be a non-empty string in semver-ish shape.

    A2A doesn't formally require strict semver, but the SDK's
    ``is_legacy_version`` check parses ``major.minor.patch``. A
    non-string or empty value breaks transport selection.
    """
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(echo_agent_card_url)
    card = response.json()
    version = card.get("protocolVersion")
    assert isinstance(version, str) and version, f"protocolVersion must be a non-empty string: {version!r}"
    parts = version.split(".")
    assert len(parts) >= 2, f"protocolVersion {version!r} must have at least major.minor"
    assert all(p.isdigit() for p in parts), f"protocolVersion {version!r} must be all-numeric segments"
