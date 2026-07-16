# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/plugins/conftest.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Shared fixtures for the live-gateway cpex plugin E2E suites.

Provides an authenticated admin HTTP client and a provisioned virtual server
backed by the ``fast-time-server`` federation gateway. The gateway under test
is started out-of-band by the plugin-integration.yml workflow with a
single-plugin enforce config; these fixtures only set up the request path the
tests exercise.
"""

from __future__ import annotations

# Standard
from contextlib import suppress
from typing import Generator

# Third-Party
import httpx
import pytest

# First-Party
from tests.live_gateway.helpers.mcp_test_helpers import BASE_URL
from tests.live_gateway.plugins import _helpers


@pytest.fixture(scope="session")
def admin_token() -> str:
    """Session-scoped admin JWT for the live-gateway test stack.

    Returns:
        A signed admin JWT.
    """
    return _helpers.make_admin_jwt()


@pytest.fixture(scope="session")
def admin_client(admin_token: str) -> Generator[httpx.Client, None, None]:
    """Session-scoped authenticated admin HTTP client.

    Args:
        admin_token: Admin bearer token.

    Yields:
        An ``httpx.Client`` bound to the gateway base URL.
    """
    # The live-gateway suites only talk to a local plain-HTTP stack; verify is
    # disabled to avoid TLS env leakage from other tests in the session.
    with httpx.Client(base_url=BASE_URL, headers=_helpers.api_headers(admin_token), timeout=30.0, verify=False) as client:
        yield client


@pytest.fixture(scope="session")
def fast_time_server(admin_client: httpx.Client, admin_token: str) -> Generator[dict[str, str], None, None]:
    """Provision a virtual server exposing the fast-time ``echo`` tool.

    Creates a throwaway team, registers the fast-time-server federation gateway
    scoped to it (so the federated tools carry a ``team_id``), waits for its
    tools to sync, creates a virtual server over them, and tears everything down
    on exit. The ``echo`` tool round-trips arbitrary text, which lets the plugin
    suites drive the gateway's plugin hooks with controlled payloads. The team
    scoping is required by the tool-plugin-bindings enforcement path and is
    inert for the static-config path.

    Args:
        admin_client: Authenticated admin HTTP client.
        admin_token: Admin bearer token (for MCP calls).

    Yields:
        Mapping with ``server_id``, ``echo_tool`` (gateway-prefixed name),
        ``flaky_tool`` (gateway-prefixed name), ``token`` and ``team_id``.
    """
    suffix = _helpers.unique_suffix()
    team_id = _helpers.create_team(admin_client, name=f"plugin_e2e_team_{suffix}")
    gateway_name = f"fast_time_e2e_{suffix}"
    gateway_id = _helpers.register_fast_time_gateway(admin_client, name=gateway_name, team_id=team_id, visibility="team")

    tools = _helpers.wait_for_gateway_tools(admin_client, gateway_id)
    echo_tool = _helpers.find_echo_tool(tools)
    flaky_tool = _helpers.find_flaky_tool(tools)
    server_id = _helpers.create_virtual_server(
        admin_client,
        name=f"fast_time_e2e_server_{suffix}",
        tool_ids=[t["id"] for t in tools],
    )

    try:
        yield {"server_id": server_id, "echo_tool": echo_tool["name"], "flaky_tool": flaky_tool["name"], "token": admin_token, "team_id": team_id}
    finally:
        with suppress(Exception):
            admin_client.delete(f"/servers/{server_id}")
        with suppress(Exception):
            admin_client.delete(f"/gateways/{gateway_id}")
        with suppress(Exception):
            _helpers.delete_team(admin_client, team_id=team_id)
