# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/protocol_compliance/helpers/compliance.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Shared test helpers for the compliance harness.

Includes:
  - ``resolve_tool`` — translate bare tool names to whatever the current
    target advertises (handles gateway slug-prefixing).
  - ``current_target`` / ``xfail_on`` — read the parametrized target out of
    a fixture-aware request and conditionally mark ``xfail``. Used to track
    documented compliance gaps without letting them stall the suite.



The reference server registers tools by their bare name (``echo``, ``add``,
…). When the gateway federates an upstream, it prefixes each tool with the
gateway's slug (``compliance-reference-echo``, …). Tests that call tools by
name need to resolve the bare name to whatever the *current* target
actually advertises.

The gateway slug used by the harness is locked to ``GATEWAY_UPSTREAM_SLUG``
below — it must match the ``name`` field used in
``upstream_registration.registered_reference_upstream`` so the resolver can
reconstruct the federated form deterministically.
"""

from __future__ import annotations

from typing import Optional

import pytest
from fastmcp.client import Client

# Slug derived from upstream registration name "compliance_reference":
# ContextForge converts underscores to hyphens for the public slug.
GATEWAY_UPSTREAM_SLUG = "compliance-reference"


async def resolve_tool(client: Client, bare: str) -> Optional[str]:
    """Return the tool name as advertised by the connected client, or None.

    Matches in this order:
      1. Exact bare name (reference target).
      2. Exact ``<slug>-<bare-with-underscores-as-hyphens>`` (federated targets).

    Suffix matching was tried earlier but caused false positives — e.g.
    ``echo`` matched ``compliance-reference-roots-echo``. Exact compose-then-
    compare is unambiguous given a known slug.

    Returns ``None`` if no candidate tool is advertised — the caller can
    ``pytest.skip`` with a clear reason.
    """
    tools = await client.list_tools()
    names = {t.name for t in tools}
    if bare in names:
        return bare
    federated = f"{GATEWAY_UPSTREAM_SLUG}-{bare.replace('_', '-')}"
    if federated in names:
        return federated
    return None


def current_target(request: pytest.FixtureRequest) -> str:
    """Return the parametrize cell's target name (e.g. ``"gateway_proxy"``).

    Tests using the ``client`` or ``connect`` fixtures inherit a parametrize
    ID like ``"reference-stdio"`` or ``"gateway_proxy-http"``. This helper
    extracts the target portion so a test can branch on it (typically to
    call ``xfail_on``).

    Returns an empty string when no parametrize context is available.
    """
    callspec = getattr(request.node, "callspec", None)
    if callspec is None:
        return ""
    # The id format is "<target>-<transport>" (see conftest._CASES).
    return callspec.id.split("-")[0]


def xfail_on(request: pytest.FixtureRequest, *targets: str, reason: str) -> None:
    """Mark the current test ``xfail`` when running against any of ``targets``.

    Designed for documented compliance gaps: the harness keeps running the
    test against every target so an *unexpected pass* (gap fixed) gets
    flagged, but a known-failing target doesn't break the suite.

    Always pass a ``reason`` that points at the COMPLIANCE_GAPS.md entry
    (e.g. ``"GAP-004: server-initiated sampling not relayed (see #4205)"``).

    Implementation note: this dynamically adds a ``pytest.mark.xfail``
    marker via ``request.node.add_marker`` rather than calling
    ``pytest.xfail(...)`` imperatively. The imperative form raises
    immediately and makes XPASS (gap closure) undetectable because the
    test body never runs. The marker form lets the body run; if it
    passes when it shouldn't have, pytest records an XPASS that the
    conftest hook captures into the per-slice sidecar log.
    """
    if current_target(request) in targets:
        request.node.add_marker(pytest.mark.xfail(strict=False, reason=reason))
