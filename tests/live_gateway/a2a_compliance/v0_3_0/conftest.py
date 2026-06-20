# -*- coding: utf-8 -*-
"""A2A 0.3.0 compliance harness fixture overrides.

Location: ./tests/live_gateway/a2a_compliance/v0_3_0/conftest.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

Overrides the parent conftest's ``echo_agent_base_url`` session
fixture to point at the v0.3.0 echo agent (port 9101). All other
parent-conftest behavior — the ``(target, transport)`` matrix, the
gateway-column blanket xfail (A2A-GAP-001), the reference
SendMessageResponse-parse xfail allowlist (A2A-GAP-006) — applies
unchanged because the parent fixtures and hooks are inherited.

``echo_agent_card_url`` flows transitively: the parent definition
takes ``echo_agent_base_url`` as an argument, so overriding the URL
fixture here re-derives the card URL automatically.
"""

from __future__ import annotations

import os

import httpx
import pytest


def _v0_3_0_base_url() -> str:
    """v0.3.0 echo agent URL — overridable for non-default port-forwards."""
    return os.getenv("A2A_ECHO_V0_3_0_BASE_URL", "http://127.0.0.1:9101")


def _is_reachable(url: str, timeout: float = 3.0) -> bool:
    try:
        return httpx.get(f"{url}/health", timeout=timeout).status_code == 200
    except Exception:  # noqa: BLE001 — any failure means "not reachable"
        return False


@pytest.fixture(scope="session")
def echo_agent_base_url() -> str:
    """Override: point at the v0.3.0 echo agent on port 9101.

    The agent is brought up by ``make testing-up`` (compose
    ``testing`` profile, service ``a2a_echo_agent_v0_3_0``) and binds
    ``0.0.0.0:9100`` inside the container with a ``9101:9100``
    host-port mapping. Override via ``A2A_ECHO_V0_3_0_BASE_URL`` for
    non-default deployments.
    """
    url = _v0_3_0_base_url()
    if not _is_reachable(url):
        pytest.skip(f"v0.3.0 a2a_echo_agent not reachable at {url}. Bring up the " "testing stack (`make testing-up`) or set A2A_ECHO_V0_3_0_BASE_URL " "before running A2A 0.3.0 compliance tests.")
    return url
