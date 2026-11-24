# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/e2e/test_elicitation_session_ownership.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Live-gateway black-box test for session ownership on ``/rpc`` ``elicitation/create``.

An owner opens an SSE session and initializes it with the elicitation capability.
A second non-admin user must not deliver an elicitation request to that session,
either by naming it or by omitting ``session_id``. The owner can still target its
own session, and a non-positive ``timeout`` is rejected.

Every account, role and grant is created through the HTTP API of a private gateway
subprocess (see ``isolated_gateway``). No Docker stack is required.
"""

# Future
from __future__ import annotations

# Standard
from typing import Any
from urllib.parse import parse_qs, urlparse

# Third-Party
import httpx
import pytest

# Local
from tests.helpers.auth import make_auth_headers
from tests.live_gateway.e2e.test_candidate_credential_handshake import _GatewayFixture, isolated_gateway  # noqa: F401  pylint: disable=unused-import

pytestmark = [pytest.mark.e2e]

_PASSWORD = "E2eElicitPassw!42"  # pragma: allowlist secret
_OWNER = "owner@example.com"
_INTRUDER = "intruder@example.com"
_SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}}


def _setup(client: httpx.Client, method: str, path: str, step: str, *, expected: tuple[int, ...] = (200, 201), **kwargs: Any) -> Any:
    """Send a setup request and return its JSON body.

    Raises:
        RuntimeError: If the response status is not in ``expected``.
    """
    response = client.request(method, path, **kwargs)
    if response.status_code not in expected:
        raise RuntimeError(f"setup: {step} {response.status_code} {response.text[:300]}")
    return response.json() if response.content else None


def _client(base_url: str, token: str) -> httpx.Client:
    """Return a client authenticated with ``token``."""
    return httpx.Client(base_url=base_url, headers=make_auth_headers(token), timeout=30, trust_env=False)


def _create_users(admin: httpx.Client, base_url: str) -> dict[str, str]:
    """Create the owner and intruder, grant ``servers.use``, and return their session tokens."""
    role = _setup(admin, "POST", "/rbac/roles", "role sse-user", json={"name": "sse-user", "scope": "global", "permissions": ["servers.use"]})
    tokens = {}
    for email in (_OWNER, _INTRUDER):
        _setup(
            admin,
            "POST",
            "/auth/email/admin/users",
            f"user {email}",
            expected=(201,),
            json={"email": email, "password": _PASSWORD, "full_name": email.split("@")[0], "is_admin": False, "is_active": True, "password_change_required": False},
        )
        _setup(admin, "POST", f"/rbac/users/{email}/roles", f"grant {email}", json={"role_id": role["id"], "scope": "global", "scope_id": None})
        with httpx.Client(base_url=base_url, timeout=30, trust_env=False) as anonymous:
            tokens[email] = _setup(anonymous, "POST", "/auth/email/login", f"login {email}", json={"email": email, "password": _PASSWORD})["access_token"]
    return tokens


def _rpc(client: httpx.Client, request_id: str, method: str, params: dict[str, Any]) -> dict[str, Any]:
    """POST one JSON-RPC call to ``/rpc`` and return the decoded body."""
    response = client.post("/rpc", json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
    return response.json()


def _open_session_id(stream: httpx.Response) -> str:
    """Read the SSE ``endpoint`` event and return its ``session_id``.

    Raises:
        AssertionError: If the stream ends before an endpoint event arrives.
    """
    for line in stream.iter_lines():
        if line.startswith("data:") and "session_id=" in line:
            return parse_qs(urlparse(line[len("data:") :].strip()).query)["session_id"][0]
    raise AssertionError("SSE stream closed before the endpoint event")


def test_elicitation_create_is_limited_to_owned_sessions(isolated_gateway: _GatewayFixture) -> None:  # noqa: F811  pylint: disable=redefined-outer-name
    """A non-admin user cannot deliver an elicitation request to another user's session."""
    admin, _token, base_url, _key = isolated_gateway
    tokens = _create_users(admin, base_url)

    with _client(base_url, tokens[_OWNER]) as owner, _client(base_url, tokens[_INTRUDER]) as intruder, _client(base_url, tokens[_OWNER]) as owner_sse:
        with owner_sse.stream("GET", "/sse") as stream:
            assert stream.status_code == 200, stream.read()[:300]
            owner_session = _open_session_id(stream)

            initialized = _rpc(
                owner,
                "init",
                "initialize",
                {"protocolVersion": "2025-06-18", "capabilities": {"elicitation": {"form": {}}}, "clientInfo": {"name": "e2e", "version": "1"}, "session_id": owner_session},
            )
            assert "error" not in initialized, initialized

            named = _rpc(intruder, "named", "elicitation/create", {"message": "probe", "requestedSchema": _SCHEMA, "session_id": owner_session, "timeout": 2})
            assert named.get("error", {}).get("code") == -32003, named

            implicit = _rpc(intruder, "implicit", "elicitation/create", {"message": "probe", "requestedSchema": _SCHEMA, "timeout": 2})
            assert implicit.get("error", {}).get("code") == -32000, implicit
            assert implicit["error"]["message"] == "No elicitation-capable clients available", implicit

            bad_timeout = _rpc(intruder, "timeout", "elicitation/create", {"message": "probe", "requestedSchema": _SCHEMA, "timeout": -1})
            assert bad_timeout.get("error", {}).get("code") == -32602, bad_timeout

            # Positive control: the owner reaches its own capable session (no client answers, so it times out).
            own = _rpc(owner, "own", "elicitation/create", {"message": "probe", "requestedSchema": _SCHEMA, "session_id": owner_session, "timeout": 1})
            assert "timed out" in own.get("error", {}).get("message", ""), own
