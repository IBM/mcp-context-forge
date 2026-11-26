# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/a2a/test_a2a_server_tool_association_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box checks that an A2A agent on a virtual server exposes its derived tool (#7672).
"""

# Standard
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
import threading
import uuid

# Third-Party
import httpx
import pytest

# Local
from tests.helpers.auth import make_auth_headers, make_test_jwt
from tests.live_gateway.a2a.test_a2a_fetch_card_e2e import gateway  # noqa: F401  # pylint: disable=unused-import

pytestmark = pytest.mark.e2e


OTHER_ADMIN = "other-admin@example.com"


def _request(gateway, method, path, *, email="admin@example.com", teams=None, scopes=None, **kwargs):  # noqa: F811
    """Send one request to the gateway with an admin token."""
    base, key = gateway
    headers = {} if email is None else make_auth_headers(make_test_jwt(email, is_admin=True, teams=teams, scopes=scopes, secret=key, algorithm="HS256"))
    with httpx.Client(base_url=base, timeout=30, trust_env=False) as client:
        return client.request(method, path, headers=headers, **kwargs)


@pytest.fixture(scope="module")
def other_admin(gateway):  # noqa: F811
    """Create a second platform admin who owns none of the agents."""
    fixture_password = "A9!" + "-".join(secrets.token_urlsafe(1) for _ in range(16))
    created = _request(gateway, "POST", "/auth/email/admin/users", json={"email": OTHER_ADMIN, "password": fixture_password, "full_name": "Other Admin", "is_admin": True})
    assert created.status_code in (200, 201), created.text
    return OTHER_ADMIN


def _agent(gateway, visibility="public", endpoint_url="http://127.0.0.1:9/rpc"):  # noqa: F811
    """Register an agent and return its read body."""
    body = {"name": f"e2e-tool-{uuid.uuid4().hex[:8]}", "endpoint_url": endpoint_url, "agent_type": "generic", "protocol_version": "1.0", "capabilities": {}}
    created = _request(gateway, "POST", "/a2a", json={"agent": body, "visibility": visibility})
    assert created.status_code == 201, created.text
    return created.json()


def _server(gateway, *, email="admin@example.com", **fields):  # noqa: F811
    """Create a virtual server and return its id."""
    created = _request(gateway, "POST", "/servers", email=email, json={"server": {"name": f"e2e-srv-{uuid.uuid4().hex[:8]}", **fields}, "visibility": "public"})
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


def test_read_back_put_that_removes_the_agent_removes_its_tool(gateway):  # noqa: F811
    """A client that sends back the read tool list and removes the agent detaches the tool."""
    agent = _agent(gateway)
    server_id = _server(gateway, associated_a2a_agents=[agent["id"]])
    read = _request(gateway, "GET", f"/servers/{server_id}").json()

    removed = _request(gateway, "PUT", f"/servers/{server_id}", json={"associated_a2a_agents": [], "associated_tools": read["associatedToolIds"]})

    assert removed.status_code == 200, removed.text
    assert _tool_names(gateway, server_id) == []


def test_server_create_denies_another_users_private_agent(gateway, other_admin):  # noqa: F811
    """A caller cannot attach a private agent that another user owns."""
    agent = _agent(gateway, visibility="private")

    denied = _request(gateway, "POST", "/servers", email=OTHER_ADMIN, json={"server": {"name": f"e2e-srv-{uuid.uuid4().hex[:8]}", "associated_a2a_agents": [agent["id"]]}, "visibility": "public"})

    assert denied.status_code == 400, denied.text
    assert agent["id"] in denied.text


def test_server_update_denies_another_users_private_agent(gateway, other_admin):  # noqa: F811
    """The owner can attach a private agent by PUT. Another user cannot, and that server stays unchanged."""
    agent = _agent(gateway, visibility="private")
    server_id = _server(gateway)

    attached = _request(gateway, "PUT", f"/servers/{server_id}", json={"associated_a2a_agents": [agent["id"]]})
    assert attached.status_code == 200, attached.text

    other_server = _request(gateway, "POST", "/servers", email=OTHER_ADMIN, json={"server": {"name": f"e2e-srv-{uuid.uuid4().hex[:8]}"}, "visibility": "public"})
    assert other_server.status_code == 201, other_server.text
    other_id = other_server.json()["id"]

    denied = _request(gateway, "PUT", f"/servers/{other_id}", email=OTHER_ADMIN, json={"associated_a2a_agents": [agent["id"]]})

    assert denied.status_code == 400, denied.text
    assert _tool_names(gateway, other_id) == []


def test_missing_and_invisible_agents_return_the_same_error(gateway, other_admin):  # noqa: F811
    """The error does not reveal whether an agent ID exists."""
    private = _agent(gateway, visibility="private")
    unknown = uuid.uuid4().hex

    responses = [
        _request(gateway, "POST", "/servers", email=OTHER_ADMIN, json={"server": {"name": f"e2e-srv-{uuid.uuid4().hex[:8]}", "associated_a2a_agents": [agent_id]}, "visibility": "public"})
        for agent_id in (private["id"], unknown)
    ]

    assert [r.status_code for r in responses] == [400, 400]
    assert responses[0].text.replace(private["id"], "X") == responses[1].text.replace(unknown, "X")


@pytest.fixture
def invocation_stub():
    """Serve a fixed response to derived tool calls."""
    requests = []

    class AgentHandler(BaseHTTPRequestHandler):
        """Handle agent requests for this test."""

        def do_POST(self):  # noqa: N802
            """Record the request and send the test response."""
            requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            payload = b'{"response":"derived tool stub"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    with ThreadingHTTPServer(("127.0.0.1", 0), AgentHandler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}/rpc", requests
        finally:
            server.shutdown()
            thread.join()


@pytest.mark.parametrize("legacy_flag", [{}, {"allow_auto": False}, {"allow_auto": True}])
def test_tool_create_rejects_manual_a2a(gateway, legacy_flag):  # noqa: F811
    """Reject client requests to create gateway-managed tools."""
    response = _request(
        gateway, "POST", "/tools",
        json={"tool": {"name": "manual-a2a", "url": "https://example.com", "integration_type": "A2A", "request_type": "POST", **legacy_flag}},
    )

    assert response.status_code == 422, response.text
    assert "Cannot manually create A2A tools" in response.text


def test_private_agent_ids_are_scoped_to_the_owner(gateway, other_admin):  # noqa: F811
    """Keep a public server discoverable and filter its agent IDs."""
    agent = _agent(gateway, visibility="private")
    server_id = _server(gateway, associated_a2a_agents=[agent["id"]])
    path = f"/servers/{server_id}"

    owner_read = _request(gateway, "GET", path)
    other_read = _request(gateway, "GET", path, email=other_admin)
    assert owner_read.status_code == other_read.status_code == 200
    assert owner_read.json()["associatedA2aAgents"] == [agent["id"]]
    assert other_read.json()["associatedA2aAgents"] == []

    listed = _request(gateway, "GET", "/servers", email=other_admin, params={"page": 1, "per_page": 100})
    assert listed.status_code == 200, listed.text
    body = listed.json()
    servers = body if isinstance(body, list) else body["servers"]
    assert next(server for server in servers if server["id"] == server_id)["associatedA2aAgents"] == []


def test_server_edit_preserves_hidden_associations(gateway, other_admin):  # noqa: F811
    """Keep agent associations hidden from the user who edits the server."""
    agent = _agent(gateway)
    server_id = _server(gateway, email=other_admin, associated_a2a_agents=[agent["id"]])
    changed = _request(gateway, "PUT", f"/a2a/{agent['id']}", json={"visibility": "private"})
    assert changed.status_code == 200, changed.text
    server_path = f"/servers/{server_id}"

    read = _request(gateway, "GET", server_path, email=other_admin)
    assert read.status_code == 200, read.text
    assert read.json()["associatedA2aAgents"] == []
    saved = _request(gateway, "PUT", server_path, email=other_admin, json={"associated_a2a_agents": read.json()["associatedA2aAgents"]})
    assert saved.status_code == 200, saved.text
    assert saved.json()["associatedA2aAgents"] == []
    assert _request(gateway, "GET", server_path).json()["associatedA2aAgents"] == [agent["id"]]


def test_derived_tool_requires_execute_and_agent_visibility(gateway, other_admin, invocation_stub):  # noqa: F811
    """Invoke a legitimate private tool with tools.execute and protect it from other callers."""
    endpoint_url, requests = invocation_stub
    agent = _agent(gateway, visibility="private", endpoint_url=endpoint_url)
    assert agent["toolId"]
    tool = _request(gateway, "GET", f"/tools/{agent['toolId']}")
    assert tool.status_code == 200, tool.text
    params = {"name": tool.json()["name"], "arguments": {"query": "hello"}}
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params}
    execute = {"permissions": ["tools.execute"]}

    login_required = _request(gateway, "POST", "/rpc", email=None, json=body)
    wrong_scope = _request(gateway, "POST", "/rpc", scopes={"permissions": ["tools.read"]}, json=body)
    non_owner = _request(gateway, "POST", "/rpc", email=other_admin, scopes=execute, json=body)
    public_only = _request(gateway, "POST", "/rpc", teams=[], scopes=execute, json=body)
    assert login_required.status_code in (401, 403)
    for denied in (wrong_scope, non_owner, public_only):
        assert denied.status_code in (403, 404) or "error" in denied.json(), denied.text
    assert requests == []

    allowed = _request(gateway, "POST", "/rpc", scopes=execute, json=body)
    assert allowed.status_code == 200, allowed.text
    result = allowed.json()
    assert "result" in result, result
    assert "derived tool stub" in result["result"]["content"][0]["text"]
    assert len(requests) == 1
