# -*- coding: utf-8 -*-
"""A2A protocol-compliance harness fixtures.

Location: ./tests/live_gateway/a2a_compliance/conftest.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

The ``client`` fixture is parametrized over every ``(target, transport)``
pair declared below, so every test body runs across the full matrix
automatically:

    reference-jsonrpc       — direct to the live a2a_echo_agent
    gateway_proxy-jsonrpc   — via ContextForge proxy (placeholder)
    gateway_virtual-jsonrpc — via ContextForge virtual server (placeholder)

The two gateway cells are blanket-xfailed at collection time
(``pytest_collection_modifyitems`` below) under **A2A-GAP-001** — see
``COMPLIANCE_GAPS.md`` — because ContextForge does not yet expose a
native A2A JSON-RPC endpoint. Their placeholder targets raise
``NotImplementedError`` inside ``_open_client``; with the xfail marker
already attached at collection time, pytest reports each cell as
``XFAIL`` rather than ``ERROR``. When the gap closes, delete the
collection hook below and the next matrix run will surface ``XPASS``
on each newly-passing cell.
"""

from __future__ import annotations

from typing import AsyncIterator

import pytest
import pytest_asyncio
from a2a.client.client import Client

from .fixtures.echo_agent import (  # noqa: F401 — re-exported for pytest fixture discovery
    echo_agent_base_url,
    echo_agent_card_url,
)
from .targets.base import Transport
from .targets.gateway_proxy import A2AGatewayProxyTarget
from .targets.gateway_virtual import A2AGatewayVirtualServerTarget
from .targets.reference import A2AReferenceTarget

_CASES: list[tuple[str, Transport]] = [
    ("reference", "jsonrpc"),
    ("gateway_proxy", "jsonrpc"),
    ("gateway_virtual", "jsonrpc"),
]

_GATEWAY_TARGET_NAMES = frozenset({"gateway_proxy", "gateway_virtual"})
_GATEWAY_XFAIL_REASON = "A2A-GAP-001: ContextForge lacks native A2A passthrough at a public " "JSON-RPC + well-known-card route. See " "tests/live_gateway/a2a_compliance/COMPLIANCE_GAPS.md."


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Blanket-xfail every gateway-target matrix cell (A2A-GAP-001).

    The entire ``gateway_proxy`` and ``gateway_virtual`` columns are
    known broken via A2A-GAP-001 — the gateway has no native A2A
    JSON-RPC endpoint, so the placeholder targets raise
    ``NotImplementedError`` inside ``_open_client``. Marking xfail at
    collection time (before fixture setup runs) means the fixture's
    exception lands inside an xfail-wrapped test and pytest reports
    ``XFAIL`` instead of ``ERROR``.

    Rather than requiring every future test author to remember to call
    ``xfail_on`` for this column-wide gap, this hook applies the
    marker once per cell. When A2A-GAP-001 closes, delete this hook
    entirely and the next matrix run surfaces ``XPASS`` on each
    newly-passing gateway cell — the cue to move the gap entry to
    "Closed gaps" in COMPLIANCE_GAPS.md.

    Per-test ``xfail_on`` calls (the helper in
    ``helpers/compliance.py``) remain the right tool for narrower
    gaps that don't have a stable column-wide pattern.
    """
    del config  # unused; pytest-canonical signature
    for item in items:
        callspec = getattr(item, "callspec", None)
        if callspec is None:
            continue
        target_name = callspec.id.split("-")[0]
        if target_name in _GATEWAY_TARGET_NAMES:
            item.add_marker(pytest.mark.xfail(strict=False, reason=_GATEWAY_XFAIL_REASON))


def _build_target(target_name: str, request: pytest.FixtureRequest):
    """Construct an A2AComplianceTarget for ``target_name``.

    Reference target pulls the resolved card URL from the
    ``echo_agent_card_url`` fixture (which transitively probes the
    agent's ``/health`` and skips the session if it's unreachable).
    Gateway placeholders are constructed unconditionally — their
    ``_open_client`` raises at fixture-setup time, captured by the
    collection-modify hook above.
    """
    if target_name == "reference":
        base_url = request.getfixturevalue("echo_agent_base_url")
        return A2AReferenceTarget(base_url=base_url)
    if target_name == "gateway_proxy":
        return A2AGatewayProxyTarget(
            base_url="http://placeholder",
            auth_token="placeholder",
            agent_name="a2a-echo-agent",
        )
    if target_name == "gateway_virtual":
        return A2AGatewayVirtualServerTarget(
            base_url="http://placeholder",
            auth_token="placeholder",
            server_id="placeholder",
            agent_name="a2a-echo-agent",
        )
    raise AssertionError(f"unknown target: {target_name!r}")


@pytest_asyncio.fixture(params=_CASES, ids=[f"{t}-{x}" for t, x in _CASES])
async def client(request: pytest.FixtureRequest) -> AsyncIterator[Client]:
    """Yield a connected ``a2a.client.Client`` for the parametrized cell.

    Reference target opens a fresh ``httpx.AsyncClient`` + ``ClientFactory``
    per invocation; the SDK auto-routes via JSON-RPC per the echo
    agent's advertised card interfaces.

    Gateway targets raise ``NotImplementedError`` inside
    ``_open_client`` (see ``targets/gateway_proxy.py`` /
    ``gateway_virtual.py``). The collection hook above attaches an
    ``xfail`` marker to every gateway cell so the exception is
    captured as ``XFAIL``.
    """
    target_name, transport = request.param
    target = _build_target(target_name, request)
    async with target.client(transport) as connected:
        yield connected
