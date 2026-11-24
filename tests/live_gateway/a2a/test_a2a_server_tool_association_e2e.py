# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/a2a/test_a2a_server_tool_association_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box checks that an A2A agent on a virtual server exposes its derived tool (#7672).
"""

# Standard
import uuid

# Third-Party
import httpx
import pytest

# Local
from tests.helpers.auth import make_auth_headers, make_test_jwt
from tests.live_gateway.a2a.test_a2a_fetch_card_e2e import gateway  # noqa: F401  # pylint: disable=unused-import

pytestmark = pytest.mark.e2e


def _request(gateway, method, path, **kwargs):  # noqa: F811
    """Send one request to the gateway with an admin token."""
    base, key = gateway
    token = make_test_jwt("admin@example.com", is_admin=True, teams=None, secret=key, algorithm="HS256")
    with httpx.Client(base_url=base, timeout=30, trust_env=False) as client:
        return client.request(method, path, headers=make_auth_headers(token), **kwargs)


def _agent(gateway):  # noqa: F811
    """Register an agent and return its read body."""
    body = {"name": f"e2e-tool-{uuid.uuid4().hex[:8]}", "endpoint_url": "http://127.0.0.1:9/rpc", "agent_type": "generic", "protocol_version": "1.0", "capabilities": {}}
    created = _request(gateway, "POST", "/a2a", json={"agent": body, "visibility": "public"})
    assert created.status_code == 201, created.text
    return created.json()


def _server(gateway, **fields):  # noqa: F811
    """Create a virtual server and return its id."""
    created = _request(gateway, "POST", "/servers", json={"server": {"name": f"e2e-srv-{uuid.uuid4().hex[:8]}", **fields}, "visibility": "public"})
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _tool_names(gateway, server_id):  # noqa: F811
    """Return the names of the tools the server lists."""
    listed = _request(gateway, "GET", f"/servers/{server_id}/tools")
    assert listed.status_code == 200, listed.text
    return [tool["originalName"] for tool in listed.json()]


def test_agent_read_reports_the_derived_tool(gateway):  # noqa: F811
    """The agent read schema carries the id of the tool derived from the agent."""
    agent = _agent(gateway)

    assert agent["toolId"]
    assert _request(gateway, "GET", f"/a2a/{agent['id']}").json()["toolId"] == agent["toolId"]


def test_server_created_with_an_agent_lists_the_agent_tool(gateway):  # noqa: F811
    """A server created with an agent lists its tool, so MCP clients can call it."""
    agent = _agent(gateway)

    server_id = _server(gateway, associated_a2a_agents=[agent["id"]])

    assert f"a2a_{agent['slug']}" in _tool_names(gateway, server_id)
    assert agent["toolId"] in _request(gateway, "GET", f"/servers/{server_id}").json()["associatedToolIds"]


def test_agent_added_by_update_brings_its_tool_and_removal_takes_it_away(gateway):  # noqa: F811
    """Adding an agent adds its tool. Removing the agent removes it."""
    agent = _agent(gateway)
    server_id = _server(gateway)
    assert _tool_names(gateway, server_id) == []

    added = _request(gateway, "PUT", f"/servers/{server_id}", json={"associated_a2a_agents": [agent["id"]]})
    assert added.status_code == 200, added.text
    assert f"a2a_{agent['slug']}" in _tool_names(gateway, server_id)

    removed = _request(gateway, "PUT", f"/servers/{server_id}", json={"associated_a2a_agents": []})
    assert removed.status_code == 200, removed.text
    assert _tool_names(gateway, server_id) == []


def test_put_without_the_derived_tool_does_not_detach_it(gateway):  # noqa: F811
    """A PUT that replaces associated_tools without the derived tool leaves it attached."""
    agent = _agent(gateway)
    server_id = _server(gateway, associated_a2a_agents=[agent["id"]])

    replaced = _request(gateway, "PUT", f"/servers/{server_id}", json={"associated_tools": []})

    assert replaced.status_code == 200, replaced.text
    assert f"a2a_{agent['slug']}" in _tool_names(gateway, server_id)
