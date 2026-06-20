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
_REFERENCE_GAP_006_TESTS_BY_VERSION: dict[str, frozenset[str]] = {
    "v1_0_0": frozenset(
        {
            "test_send_message_returns_at_least_one_response",
            "test_send_message_echoes_input_text",
            "test_list_tasks_returns_response",
            "test_send_message_response_populates_message_or_task",
            "test_echo_response_carries_text_part",
        }
    ),
    "v0_3_0": frozenset({"test_list_tasks_returns_response"}),
}
_REFERENCE_GAP_006_REASON = (
    "A2A-GAP-006: echo agent response payloads include non-protobuf fields the " "SDK parser rejects with ParseError. See " "tests/live_gateway/a2a_compliance/COMPLIANCE_GAPS.md."
)


def _version_segment_from_path(item: pytest.Item) -> str | None:
    """Return ``v1_0_0`` / ``v0_3_0`` based on the test's filesystem location.

    The ``a2a_compliance`` package organizes test bodies under per-version
    subpackages (``v1_0_0/``, ``v0_3_0/``); the path segment is the only
    stable signal at collection time for distinguishing which version's
    fixture-override conftest a given test inherits. Returns ``None`` for
    tests collected outside any versioned subdir (none today, but defended
    against future flat-layout additions at the harness root).
    """
    path_str = str(item.path)
    if "/v1_0_0/" in path_str or "\\v1_0_0\\" in path_str:
        return "v1_0_0"
    if "/v0_3_0/" in path_str or "\\v0_3_0\\" in path_str:
        return "v0_3_0"
    return None


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Blanket-xfail known-broken matrix cells.

    Two gap-driven exclusions live here:

    * **A2A-GAP-001 (column-wide)** — every ``gateway_proxy`` and
      ``gateway_virtual`` cell. The gateway has no native A2A JSON-RPC
      endpoint, so the placeholder targets raise
      ``NotImplementedError`` inside ``_open_client``. Marking xfail at
      collection time (before fixture setup runs) means the fixture's
      exception lands inside an xfail-wrapped test and pytest reports
      ``XFAIL`` instead of ``ERROR``.
    * **A2A-GAP-006 (per-test, ``reference`` target, per-version)** —
      the v1.0.0 transport rejects all five SDK-Client tests in
      ``_REFERENCE_GAP_006_TESTS_BY_VERSION['v1_0_0']`` because the
      echo agent's ``SendMessageResponse`` JSON includes an
      ``artifacts`` field at the response root that's absent from the
      SDK's protobuf schema. The HTTP round-trip succeeds; the SDK's
      protobuf parser rejects the response with ``ParseError``.

      The v0.3.0 ``CompatJsonRpcTransport`` has a different response
      shape and tolerates four of the five; only
      ``test_list_tasks_returns_response`` still fails under v0.3.0,
      so ``_REFERENCE_GAP_006_TESTS_BY_VERSION['v0_3_0']`` is a single
      entry. The test's version is read from the filesystem path
      (``v1_0_0/`` vs ``v0_3_0/``) via ``_version_segment_from_path``.

    Rather than requiring every future test author to remember to call
    ``xfail_on`` for these column-wide / cell-wide gaps, this hook
    applies the markers once per cell. When a gap closes, delete the
    arm for it and the next matrix run surfaces ``XPASS`` on each
    newly-passing cell — the cue to move that gap's entry to "Closed
    gaps" in COMPLIANCE_GAPS.md.

    Per-test ``xfail_on`` calls (the helper in
    ``helpers/compliance.py``) remain the right tool for narrower
    gaps that don't have a stable column-wide or test-set pattern.
    """
    del config  # unused; pytest-canonical signature
    for item in items:
        callspec = getattr(item, "callspec", None)
        if callspec is None:
            continue
        target_name = callspec.id.split("-")[0]
        if target_name in _GATEWAY_TARGET_NAMES:
            item.add_marker(pytest.mark.xfail(strict=False, reason=_GATEWAY_XFAIL_REASON))
        elif target_name == "reference":
            version = _version_segment_from_path(item)
            if version is not None and item.originalname in _REFERENCE_GAP_006_TESTS_BY_VERSION[version]:
                item.add_marker(pytest.mark.xfail(strict=False, reason=_REFERENCE_GAP_006_REASON))


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
