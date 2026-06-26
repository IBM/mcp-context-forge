# -*- coding: utf-8 -*-
"""Live a2a_echo_agent fixtures.

Location: ./tests/live_gateway/a2a_compliance/fixtures/echo_agent.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

Probes the bundled ``a2a_echo_agent`` (compose ``testing`` profile,
default port 9100) at session scope and skips the entire suite cleanly
when it's unreachable. Same pattern as
``protocol_compliance/fixtures/gateway_live.py::gateway_base_url`` — a
single reachability check that converts "infra not up" into a readable
skip reason instead of a cascade of connection errors.

The echo agent is the A2A reference target; gateway federation arrives
in a later phase and gets its own fixtures.
"""

from __future__ import annotations

import os

import httpx
import pytest


def _base_url() -> str:
    """Echo agent URL — overridable for non-default compose port-forwards."""
    return os.getenv("A2A_ECHO_BASE_URL", "http://127.0.0.1:9100")


def _is_reachable(url: str, timeout: float = 3.0) -> bool:
    try:
        return httpx.get(f"{url}/health", timeout=timeout).status_code == 200
    except Exception:  # noqa: BLE001 — any failure means "not reachable"
        return False


@pytest.fixture(scope="module")
def echo_agent_base_url() -> str:
    """Return the live echo agent base URL or skip the module if unreachable.

    The agent is brought up by ``make testing-up`` (compose ``testing``
    profile) and binds ``0.0.0.0:9100`` by default. Override via
    ``A2A_ECHO_BASE_URL`` for non-default port-forwards or remote
    deployments.

    Scope is ``module`` (not ``session``) so the per-version override
    in ``v0_3_0/conftest.py`` takes effect cleanly per test module —
    a session-scoped override interacts poorly with pytest's
    first-seen caching and causes the wrong URL to leak between the
    v1.0.0 and v0.3.0 suites when both run in one process.
    """
    url = _base_url()
    if not _is_reachable(url):
        pytest.skip(f"a2a_echo_agent not reachable at {url}. Bring up the testing " "stack (`make testing-up`) or set A2A_ECHO_BASE_URL to a running " "agent before running A2A compliance tests.")
    return url


@pytest.fixture(scope="module")
def echo_agent_card_url(echo_agent_base_url: str) -> str:
    """URL of the agent card endpoint expected by ``ClientFactory.create_from_url``.

    A2A spec routes the canonical agent card at
    ``/.well-known/agent-card.json``. The echo agent also serves a
    compatibility alias at ``/.well-known/agent.json``; tests that
    specifically exercise the alias should construct that URL inline
    rather than reaching for this fixture.
    """
    return f"{echo_agent_base_url}/.well-known/agent-card.json"
