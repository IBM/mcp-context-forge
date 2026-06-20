# -*- coding: utf-8 -*-
"""Protocol version advertisement for A2A 1.0.0.

Location: ./tests/live_gateway/a2a_compliance/v1_0_0/test_version_negotiation.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

Version negotiation in A2A is card-driven: ``ClientFactory`` reads
``supportedInterfaces[*].protocolVersion`` and routes via
``CompatJsonRpcTransport`` if the version is in the legacy 0.3.x range.
These tests pin the version the echo agent advertises so the suite
fails fast if the agent (or its config) drifts off the expected
target version.
"""

from __future__ import annotations

import os

import httpx
import pytest

pytestmark = [pytest.mark.a2a, pytest.mark.a2a_v1_0_0, pytest.mark.a2a_versioning]


def _expected_version() -> str:
    """Version we expect the echo agent to advertise in this suite.

    Sourced from ``A2A_ECHO_PROTOCOL_VERSION`` so a compose run with
    ``A2A_ECHO_PROTOCOL_VERSION=0.3.0`` (the Phase 2 overlay) skips
    cleanly instead of failing the v1.0.0 expectation. The echo
    agent's default is ``1.0.0``.
    """
    return os.getenv("A2A_ECHO_PROTOCOL_VERSION", "1.0.0")


@pytest.mark.xfail(
    reason="A2A-GAP-002: echo agent puts protocolVersion at top level, not in supportedInterfaces entries",
    strict=False,
)
@pytest.mark.asyncio
async def test_card_advertises_expected_protocol_version(echo_agent_card_url: str) -> None:
    """Every advertised interface MUST declare ``protocolVersion == expected``.

    Skips when ``A2A_ECHO_PROTOCOL_VERSION`` is set to a non-1.0.0
    string so the Phase-2 0.3.0 overlay doesn't trip this test.
    """
    expected = _expected_version()
    if not expected.startswith("1."):
        pytest.skip(f"A2A_ECHO_PROTOCOL_VERSION={expected!r} — not a 1.x suite run")
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(echo_agent_card_url)
    card = response.json()
    versions = {iface.get("protocolVersion") for iface in card.get("supportedInterfaces", [])}
    assert versions == {expected}, f"agent advertises {versions} on its interfaces; expected exactly {{'{expected}'}}"


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
