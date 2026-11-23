# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/a2a/test_a2a_card_pending_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box checks for confirming or rejecting a changed Agent Card (#7661) against an isolated
gateway subprocess. A loopback server plays the remote agent. Its card changes between calls.
"""

# Standard
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import uuid

# Third-Party
import httpx
import pytest

# Local
from tests.helpers.auth import make_auth_headers, make_test_jwt
from tests.live_gateway.a2a.test_a2a_fetch_card_e2e import _free_port, gateway  # noqa: F401  # pylint: disable=unused-import

pytestmark = pytest.mark.e2e


class _Remote:
    """A remote agent whose card the test can change."""

    def __init__(self):
        self.port = _free_port()
        self.origin = f"http://127.0.0.1:{self.port}"
        self.card = self.make_card()
        self.gets = 0
        remote = self

        class Handler(BaseHTTPRequestHandler):
            """Serve the current card at the well-known path."""

            def do_GET(self):  # noqa: N802
                """Count the request and answer with the current card."""
                remote.gets += 1
                found = self.path == "/.well-known/agent-card.json"
                payload = json.dumps(remote.card if found else {}).encode()
                self.send_response(200 if found else 404)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                """Silence request logging."""

        self.server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def make_card(self, **changes):
        """Build a card, with ``changes`` replacing top-level keys."""
        card = {
            "name": "e2e-pending",
            "version": "1.0.0",
            "capabilities": {"streaming": False, "extensions": []},
            "supportedInterfaces": [{"url": f"{self.origin}/rpc", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}],
        }
        card.update(changes)
        return card


@pytest.fixture
def remote():
    """Run the changing remote agent on loopback."""
    server = _Remote()
    yield server
    server.server.shutdown()


def _request(gateway, method, path, *, scopes=None, **kwargs):  # noqa: F811
    """Send one request to the gateway with an admin token, optionally scoped."""
    base, key = gateway
    token = make_test_jwt("admin@example.com", is_admin=True, teams=None, secret=key, algorithm="HS256", scopes=scopes)
    with httpx.Client(base_url=base, timeout=30, trust_env=False) as client:
        return client.request(method, path, headers=make_auth_headers(token), **kwargs)


def _register(gateway, remote, auth=False):  # noqa: F811
    """Register an agent with its card and return its id."""
    body = {
        "name": f"e2e-pending-{uuid.uuid4().hex[:8]}",
        "endpoint_url": f"{remote.origin}/rpc",
        "agent_type": "generic",
        "protocol_version": "1.0",
        "capabilities": {"streaming": False},
        "card_url": remote.origin,
    }
    if auth:
        body.update(auth_type="bearer", auth_token="s3cr3t-key")  # pragma: allowlist secret
    created = _request(gateway, "POST", "/a2a", json={"agent": body, "visibility": "public"})
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _pending_agent(gateway, remote, **changes):  # noqa: F811
    """Register an agent, change the remote card, refresh, and return the id and refresh body."""
    agent_id = _register(gateway, remote)
    remote.card = remote.make_card(**changes)
    refreshed = _request(gateway, "POST", f"/a2a/{agent_id}/card")
    assert refreshed.status_code == 200, refreshed.text
    return agent_id, refreshed.json()


STREAMING = {"capabilities": {"streaming": True, "extensions": []}}


def test_changed_card_is_pending_and_the_agent_keeps_its_current_card(gateway, remote):  # noqa: F811
    """A changed card is held back. The agent and its current card stay as they were."""
    agent_id, body = _pending_agent(gateway, remote, **STREAMING)

    assert (body["status"], body["version"], body["pendingVersion"], body["changedKeys"]) == ("pending", 1, 2, ["capabilities.streaming"])
    assert _request(gateway, "GET", f"/a2a/{agent_id}/stored-card").json()["version"] == 1
    agent = _request(gateway, "GET", f"/a2a/{agent_id}").json()
    assert agent["drifted"] is False and agent["capabilities"]["streaming"] is False


def test_pending_card_is_read_beside_the_current_card(gateway, remote):  # noqa: F811
    """The pending route returns both cards and the dotted paths that differ."""
    agent_id, _ = _pending_agent(gateway, remote, **STREAMING)

    body = _request(gateway, "GET", f"/a2a/{agent_id}/stored-card/pending").json()

    assert (body["current"]["version"], body["pending"]["version"], body["pending"]["status"], body["changedKeys"]) == (1, 2, "pending", ["capabilities.streaming"])
    assert body["current"]["card"]["capabilities"]["streaming"] is False and body["pending"]["card"]["capabilities"]["streaming"] is True


def test_apply_makes_the_card_current_and_updates_the_agent(gateway, remote):  # noqa: F811
    """Apply promotes the pending card and changes the fields the gateway calls the agent with."""
    agent_id, _ = _pending_agent(gateway, remote, supportedInterfaces=[{"url": f"{remote.origin}/rpc/v2", "protocolBinding": "JSONRPC", "protocolVersion": "1.1"}], **STREAMING)

    applied = _request(gateway, "POST", f"/a2a/{agent_id}/card/apply", json={"version": 2})

    assert applied.status_code == 200, applied.text
    assert applied.json()["status"] == "applied" and applied.json()["appliedFields"] == ["capabilities", "endpoint_url", "protocol_version"]
    agent = _request(gateway, "GET", f"/a2a/{agent_id}").json()
    assert (agent["endpointUrl"], agent["protocolVersion"], agent["capabilities"]["streaming"], agent["drifted"]) == (f"{remote.origin}/rpc/v2", "1.1", True, False)
    assert _request(gateway, "GET", f"/a2a/{agent_id}/stored-card").json()["version"] == 2
    assert _request(gateway, "GET", f"/a2a/{agent_id}/stored-card?version=1").json()["card"]["capabilities"]["streaming"] is False
    assert [item["version"] for item in _request(gateway, "GET", f"/a2a/{agent_id}/stored-card/versions").json()] == [2, 1]
    assert _request(gateway, "GET", f"/a2a/{agent_id}/stored-card/pending").status_code == 404


def test_reject_keeps_the_current_card_and_marks_the_agent_drifted(gateway, remote):  # noqa: F811
    """Reject leaves the agent on its current card, flags it as drifted, and keeps it usable."""
    agent_id, _ = _pending_agent(gateway, remote, **STREAMING)

    rejected = _request(gateway, "POST", f"/a2a/{agent_id}/card/reject", json={"version": 2})

    assert rejected.status_code == 200, rejected.text
    assert (rejected.json()["status"], rejected.json()["drifted"]) == ("rejected", True)
    agent = _request(gateway, "GET", f"/a2a/{agent_id}").json()
    assert (agent["drifted"], agent["enabled"], agent["capabilities"]["streaming"]) == (True, True, False)
    assert _request(gateway, "GET", f"/a2a/{agent_id}/stored-card").json()["version"] == 1
    assert _request(gateway, "GET", f"/a2a/{agent_id}/stored-card/pending").status_code == 404


def test_stale_version_is_409_and_no_pending_card_is_404(gateway, remote):  # noqa: F811
    """A decision on a version other than the pending one changes nothing."""
    agent_id, _ = _pending_agent(gateway, remote, **STREAMING)

    assert _request(gateway, "POST", f"/a2a/{agent_id}/card/apply", json={"version": 9}).status_code == 409
    assert _request(gateway, "GET", f"/a2a/{agent_id}/stored-card/pending").json()["pending"]["version"] == 2
    assert _request(gateway, "POST", f"/a2a/{agent_id}/card/reject", json={"version": 2}).status_code == 200
    assert _request(gateway, "POST", f"/a2a/{agent_id}/card/reject", json={"version": 2}).status_code == 404


@pytest.mark.parametrize("permission", ["a2a.read", "a2a.create", "a2a.invoke"])
def test_decisions_and_the_pending_read_need_a2a_update(gateway, remote, permission):  # noqa: F811
    """A token without a2a.update cannot read, apply or reject the pending card, and nothing changes."""
    agent_id, _ = _pending_agent(gateway, remote, **STREAMING)
    scopes = {"permissions": [permission]}

    assert _request(gateway, "GET", f"/a2a/{agent_id}/stored-card/pending", scopes=scopes).status_code == 403
    assert _request(gateway, "POST", f"/a2a/{agent_id}/card/apply", scopes=scopes, json={"version": 2}).status_code == 403
    assert _request(gateway, "POST", f"/a2a/{agent_id}/card/reject", scopes=scopes, json={"version": 2}).status_code == 403
    assert _request(gateway, "GET", f"/a2a/{agent_id}/stored-card").json()["version"] == 1
    assert _request(gateway, "GET", f"/a2a/{agent_id}").json()["drifted"] is False


def test_no_card_route_returns_stored_credentials(gateway, remote):  # noqa: F811
    """Neither the agent read nor any card route exposes the stored credential."""
    agent_id = _register(gateway, remote, auth=True)
    remote.card = remote.make_card(**STREAMING)
    assert _request(gateway, "POST", f"/a2a/{agent_id}/card").status_code == 200

    texts = [_request(gateway, "GET", path).text for path in (f"/a2a/{agent_id}", f"/a2a/{agent_id}/stored-card", f"/a2a/{agent_id}/stored-card/pending", f"/a2a/{agent_id}/stored-card/versions")]
    texts.append(_request(gateway, "POST", f"/a2a/{agent_id}/card/apply", json={"version": 2}).text)

    assert all("s3cr3t-key" not in text for text in texts)  # pragma: allowlist secret


def test_agent_with_a_credential_is_unverified_until_a_refresh_sends_it(gateway, remote):  # noqa: F811
    """A saved credential is unverified. A refresh that sends it clears the marker."""
    agent_id = _register(gateway, remote, auth=True)
    assert _request(gateway, "GET", f"/a2a/{agent_id}").json()["unverified"] is True

    assert _request(gateway, "POST", f"/a2a/{agent_id}/card").status_code == 200

    assert _request(gateway, "GET", f"/a2a/{agent_id}").json()["unverified"] is False


def test_agent_without_a_credential_is_not_unverified(gateway, remote):  # noqa: F811
    """No credential, nothing to verify."""
    agent_id = _register(gateway, remote)
    assert _request(gateway, "GET", f"/a2a/{agent_id}").json()["unverified"] is False
