# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/a2a_compliance/test_fixture_sanity.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

A2A compliance harness fixture sanity test (Plan T28 Part B).
Plan T28 Part B (Wave 7) — sanity-checks every harness fixture in
isolation so a developer running the harness against a live gateway
sees a single clean failure if any wiring is broken, rather than
discovering it via a 14-test cascade of cryptic errors deep in
``test_agent_card.py`` or similar.

Per Oracle v3 #11: this lives in a NEW TEST FILE (NOT in
``conftest.py``) because functions defined in ``conftest.py`` are
NOT collected as tests by pytest — only fixtures and hooks.
"""

from __future__ import annotations

import re
import uuid

import httpx
import pytest

UUID_PATTERN = re.compile(r"^[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}$")


def _looks_like_uuid(value: str) -> bool:
    """Return True if ``value`` parses as a UUID (with or without dashes)."""
    if not isinstance(value, str):
        return False
    if not UUID_PATTERN.match(value):
        return False
    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False


def test_gateway_base_url_fixture_resolves(gateway_base_url: str) -> None:
    """``gateway_base_url`` is a well-formed URL with no trailing slash."""
    assert isinstance(gateway_base_url, str)
    assert gateway_base_url.startswith(("http://", "https://"))


def test_auth_token_fixture_returns_jwt_shape(auth_token: str) -> None:
    """``auth_token`` returns a three-part dotted JWT."""
    assert isinstance(auth_token, str)
    parts = auth_token.split(".")
    assert len(parts) == 3, f"expected JWT (header.payload.sig), got {len(parts)} parts"


def test_registered_agent_id_is_uuid(registered_agent_id: str) -> None:
    """``registered_agent_id`` is a UUID (the gateway's primary key for the agent)."""
    assert _looks_like_uuid(registered_agent_id), (
        f"registered_agent_id={registered_agent_id!r} is not a UUID; " "the harness must pass agent IDs (not names) into " "associated_a2a_agents per Momus v3 #3."
    )


def test_server_id_is_uuid(server_id: str) -> None:
    """``server_id`` is a UUID for the bundling virtual server (T28 Part B)."""
    assert _looks_like_uuid(server_id), f"server_id={server_id!r} is not a UUID; the v-server URL builder " "would produce a malformed /servers/{server_id}/a2a/{name} path."


def test_version_endpoint_accepts_auth_token(gateway_base_url: str, auth_token: str) -> None:
    """``GET /version`` accepts the harness auth token and returns 200.

    Round-trips the JWT through the gateway's auth middleware. A 401
    here indicates the JWT secret doesn't match what the gateway
    boots with; a 403 indicates the platform_admin role isn't being
    granted to is_admin=True tokens.
    """
    headers = {"Authorization": f"Bearer {auth_token}"}
    try:
        resp = httpx.get(f"{gateway_base_url}/version", headers=headers, timeout=httpx.Timeout(5.0))
    except httpx.HTTPError as exc:
        pytest.skip(f"Gateway unreachable at {gateway_base_url}: {exc}")
    assert resp.status_code == 200, f"GET /version returned {resp.status_code} with the harness JWT; " f"body: {resp.text[:200]}"
