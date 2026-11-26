# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/a2a/test_a2a_extended_card_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box checks for the authenticated extended Agent Card (#4734) against an isolated gateway subprocess.

A loopback HTTP server plays the remote agent. It serves a public card that declares an extended card,
and answers the JSON-RPC extended-card request only when it receives the right bearer key. The server
records every request, so the tests can prove where the credential did and did not go.
"""

# Standard
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

# Third-Party
import httpx
import pytest

# Local
from tests.helpers.auth import make_auth_headers, make_test_jwt
from tests.live_gateway.a2a.test_a2a_fetch_card_e2e import _free_port, gateway  # noqa: F401  # pylint: disable=unused-import

pytestmark = pytest.mark.e2e

GOOD_KEY = "good-extended-key"  # pragma: allowlist secret
SECRET_SKILL = {"id": "secret", "name": "Secret", "description": "only for credentialed callers", "tags": []}
PUBLIC_SKILL = {"id": "public", "name": "Public", "description": "visible to all", "tags": []}


def _public_card(rpc_url):
    """Build a public card that declares an extended card at ``rpc_url``."""
    return {
        "name": "e2e-extended",
        "version": "1.0.0",
        "capabilities": {"streaming": False, "extendedAgentCard": True},
        "supportedInterfaces": [{"url": rpc_url, "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}],
        "skills": [PUBLIC_SKILL],
    }


class _Agent:
    """The fake remote agent and the requests it received."""

    def __init__(self):
        self.requests = []
        self.port = _free_port()
        self.origin = f"http://127.0.0.1:{self.port}"
        self.other_origin = f"http://localhost:{self.port}"
        agent = self

        class Handler(BaseHTTPRequestHandler):
            """Serve the public cards and the credential-gated extended card."""

            def _send(self, status, body):
                payload = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self):  # noqa: N802
                """Serve the public cards."""
                agent.requests.append(("GET", self.path, self.headers.get("Authorization")))
                if self.path == "/ext/.well-known/agent-card.json":
                    self._send(200, _public_card(f"{agent.origin}/ext/rpc"))
                elif self.path == "/other/.well-known/agent-card.json":
                    self._send(200, _public_card(f"{agent.other_origin}/other/rpc"))
                else:
                    self._send(404, {})

            def do_POST(self):  # noqa: N802
                """Answer the JSON-RPC extended-card request for the right key only."""
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                agent.requests.append(("POST", self.path, self.headers.get("Authorization")))
                if self.headers.get("Authorization") != f"Bearer {GOOD_KEY}":
                    self._send(401, {})
                    return
                extended = {**_public_card(f"{agent.origin}/ext/rpc"), "skills": [PUBLIC_SKILL, SECRET_SKILL], "provider": {"organization": "Acme", "url": "https://acme.example"}}
                self._send(200, {"jsonrpc": "2.0", "id": "1", "result": extended})

            def log_message(self, *args):
                """Silence request logging."""

        self.server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def posts(self, path=None):
        """Return the POST requests received, optionally for one path."""
        return [request for request in self.requests if request[0] == "POST" and (path is None or request[1] == path)]


@pytest.fixture
def agent():
    """Run the fake remote agent on loopback."""
    remote = _Agent()
    yield remote
    remote.server.shutdown()


def _request(gateway, method, path, *, scopes=None, email="admin@example.com", **kwargs):  # noqa: F811
    """Send one request to the gateway with an admin token, optionally scoped."""
    base, key = gateway
    token = make_test_jwt(email, is_admin=True, teams=None, secret=key, algorithm="HS256", scopes=scopes)
    with httpx.Client(base_url=base, timeout=30, trust_env=False) as client:
        return client.request(method, path, headers=make_auth_headers(token), **kwargs)


def _fetch(gateway, agent, path, headers=None):  # noqa: F811
    """POST /a2a/fetch-card for one of the fake agent's cards."""
    body = {"baseUrl": f"{agent.origin}{path}"}
    if headers is not None:
        body["headers"] = headers
    return _request(gateway, "POST", "/a2a/fetch-card", json=body)


def _register(gateway, agent, name, key):  # noqa: F811
    """Register an agent with a card URL and a bearer key."""
    agent_body = {
        "name": name,
        "endpoint_url": f"{agent.origin}/ext/rpc",
        "agent_type": "generic",
        "protocol_version": "1.0",
        "card_url": f"{agent.origin}/ext",
        "auth_type": "bearer",
        "auth_token": key,
    }
    return _request(gateway, "POST", "/a2a", json={"agent": agent_body, "visibility": "public"})


def test_fetch_card_with_the_right_key_returns_the_extended_card(gateway, agent):  # noqa: F811
    """The right key finds the extended card and lists what it adds, in camelCase."""
    response = _fetch(gateway, agent, "/ext", {"Authorization": f"Bearer {GOOD_KEY}"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["extendedOutcome"] == "found"
    assert body["extendedAdditions"] == ["provider", "skills"]
    assert {skill["id"] for skill in body["extendedCard"]["skills"]} == {"public", "secret"}
    assert "extended_outcome" not in body


def test_fetch_card_with_a_wrong_key_reports_auth_rejected(gateway, agent):  # noqa: F811
    """A key that the agent refuses reports auth_rejected and still returns the public card."""
    response = _fetch(gateway, agent, "/ext", {"Authorization": "Bearer wrong"})

    body = response.json()
    assert (response.status_code, body["outcome"], body["extendedOutcome"]) == (200, "found", "auth_rejected")
    assert body["extendedCard"] is None


def test_fetch_card_without_credentials_makes_no_extended_request(gateway, agent):  # noqa: F811
    """Without headers, the gateway never sends the JSON-RPC request."""
    response = _fetch(gateway, agent, "/ext")

    assert response.status_code == 200 and response.json()["extendedOutcome"] is None
    assert not agent.posts()


def test_credentials_are_not_sent_to_an_interface_on_another_origin(gateway, agent):  # noqa: F811
    """A card that points its interface at another host gets no credential, and the outcome is unavailable."""
    response = _fetch(gateway, agent, "/other", {"Authorization": f"Bearer {GOOD_KEY}"})

    assert response.json()["extendedOutcome"] == "unavailable"
    assert not agent.posts("/other/rpc")


def test_registration_stores_both_cards_and_keeps_the_extended_card_off_the_public_route(gateway, agent):  # noqa: F811
    """Registration stores two rows. The public route never returns the extended content."""
    created = _register(gateway, agent, "e2e-extended-ok", GOOD_KEY)
    assert created.status_code == 201, created.text
    agent_id = created.json()["id"]

    public = _request(gateway, "GET", f"/a2a/{agent_id}/stored-card")
    extended = _request(gateway, "GET", f"/a2a/{agent_id}/stored-card/extended")

    assert public.status_code == 200 and public.json()["kind"] == "public"
    assert "secret" not in {skill["id"] for skill in public.json()["card"]["skills"]}
    assert extended.status_code == 200 and extended.json()["kind"] == "extended"
    assert "secret" in {skill["id"] for skill in extended.json()["card"]["skills"]}


def test_registration_with_a_rejected_key_fails_and_creates_no_agent(gateway, agent):  # noqa: F811
    """A key that the agent refuses fails the registration with 400 and leaves no agent behind."""
    response = _register(gateway, agent, "e2e-extended-rejected", "wrong")

    assert response.status_code == 400, response.text
    names = {item["name"] for item in _request(gateway, "GET", "/a2a").json()}
    assert "e2e-extended-rejected" not in names


@pytest.mark.parametrize(("permission", "status"), [("a2a.read", 403), ("a2a.update", 200)])
def test_extended_route_needs_a2a_update_in_the_token_scope(gateway, agent, permission, status):  # noqa: F811
    """A token scoped to a2a.read is refused. A token scoped to a2a.update is allowed."""
    created = _register(gateway, agent, f"e2e-extended-scope-{permission}", GOOD_KEY)
    agent_id = created.json()["id"]

    response = _request(gateway, "GET", f"/a2a/{agent_id}/stored-card/extended", scopes={"permissions": [permission]})

    assert response.status_code == status, response.text


def test_stored_card_route_still_works_for_a_read_scoped_token(gateway, agent):  # noqa: F811
    """The public stored card keeps the a2a.read mapping."""
    agent_id = _register(gateway, agent, "e2e-extended-read", GOOD_KEY).json()["id"]

    response = _request(gateway, "GET", f"/a2a/{agent_id}/stored-card", scopes={"permissions": ["a2a.read"]})

    assert response.status_code == 200 and response.json()["kind"] == "public"


def test_extended_route_without_a_token_returns_401(gateway, agent):  # noqa: F811
    """An unauthenticated call is rejected."""
    base, _ = gateway
    with httpx.Client(base_url=base, timeout=15, trust_env=False) as client:
        assert client.get("/a2a/any/stored-card/extended").status_code == 401
