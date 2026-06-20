# -*- coding: utf-8 -*-
"""Protocol version advertisement for A2A 0.3.0.

Location: ./tests/live_gateway/a2a_compliance/v0_3_0/test_version_negotiation.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

The 0.3.0 suite pins the expected ``protocolVersion`` to ``0.3.0``
(no env-var override — the suite identity *is* the version). Version
negotiation in A2A is card-driven: ``ClientFactory`` reads
``supportedInterfaces[*].protocolVersion`` and routes via
``CompatJsonRpcTransport`` for the 0.3.x line. These tests confirm the
echo agent's v0.3.0 container actually advertises that version on the
wire.
"""

from __future__ import annotations

import httpx
import pytest

pytestmark = [pytest.mark.a2a, pytest.mark.a2a_v0_3_0, pytest.mark.a2a_versioning]

_EXPECTED_VERSION = "0.3.0"


@pytest.mark.xfail(
    reason="A2A-GAP-002: echo agent puts protocolVersion at top level, not in supportedInterfaces entries",
    strict=False,
)
@pytest.mark.asyncio
async def test_card_advertises_expected_protocol_version(echo_agent_card_url: str) -> None:
    """Every advertised interface MUST declare ``protocolVersion == 0.3.0``.

    Mirrors the v1.0.0 test under the same A2A-GAP-002 (echo agent
    serves a flat top-level ``protocolVersion`` instead of populating
    ``supportedInterfaces[*].protocolVersion``). When that closes,
    both suites' versions of this test XPASS in lockstep.
    """
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(echo_agent_card_url)
    card = response.json()
    versions = {iface.get("protocolVersion") for iface in card.get("supportedInterfaces", [])}
    assert versions == {_EXPECTED_VERSION}, f"agent advertises {versions} on its interfaces; expected exactly {{'{_EXPECTED_VERSION}'}}"


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
    for interface in card.get("supportedInterfaces", []):
        version = interface.get("protocolVersion")
        assert isinstance(version, str) and version, f"protocolVersion must be a non-empty string: {interface}"
        parts = version.split(".")
        assert len(parts) >= 2, f"protocolVersion {version!r} must have at least major.minor"
        assert all(p.isdigit() for p in parts), f"protocolVersion {version!r} must be all-numeric segments"
