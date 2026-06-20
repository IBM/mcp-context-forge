# -*- coding: utf-8 -*-
"""Shared test helpers for the A2A compliance harness.

Location: ./tests/live_gateway/a2a_compliance/helpers/compliance.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

Provides:
  * ``current_target`` / ``xfail_on`` — read the parametrized target out
    of a fixture-aware request and conditionally mark ``xfail``. Used to
    track documented compliance gaps without letting them stall the
    suite.

Mirrors ``tests/live_gateway/protocol_compliance/helpers/compliance.py``
in shape so that gap-tracking discipline is identical across protocols.
The MCP harness's ``resolve_tool`` helper has no A2A analogue today —
A2A operates on agents/tasks/messages rather than the tool federation
surface — so it's intentionally omitted. If gateway federation grows
its own agent-name slug-prefix scheme later, add a sibling
``resolve_agent`` here.
"""

from __future__ import annotations

import pytest


def current_target(request: pytest.FixtureRequest) -> str:
    """Return the parametrize cell's target name (e.g. ``"gateway_proxy"``).

    Tests using the harness's ``client`` fixture inherit a parametrize
    ID like ``"reference-jsonrpc"`` or ``"gateway_proxy-jsonrpc"``. This
    helper extracts the target portion so a test can branch on it
    (typically to call ``xfail_on``).

    Returns an empty string when no parametrize context is available
    (e.g. tests that drive raw httpx without going through the client
    fixture).
    """
    callspec = getattr(request.node, "callspec", None)
    if callspec is None:
        return ""
    return callspec.id.split("-")[0]


def xfail_on(request: pytest.FixtureRequest, *targets: str, reason: str) -> None:
    """Mark the current test ``xfail`` when running against any of ``targets``.

    Designed for documented compliance gaps: the harness keeps running
    the test against every target so an *unexpected pass* (gap fixed)
    gets flagged, but a known-failing target doesn't break the suite.

    Always pass a ``reason`` that points at the COMPLIANCE_GAPS.md
    entry (e.g. ``"A2A-GAP-001: gateway lacks native A2A passthrough"``).

    Implementation note: this dynamically adds a ``pytest.mark.xfail``
    marker via ``request.node.add_marker`` rather than calling
    ``pytest.xfail(...)`` imperatively. The imperative form raises
    immediately and makes XPASS (gap closure) undetectable because the
    test body never runs. The marker form lets the body run; if it
    passes when it shouldn't have, pytest records an XPASS that future
    matrix runs can pick up.
    """
    if current_target(request) in targets:
        request.node.add_marker(pytest.mark.xfail(strict=False, reason=reason))
