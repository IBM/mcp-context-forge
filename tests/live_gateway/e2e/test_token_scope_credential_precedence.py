# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/e2e/test_token_scope_credential_precedence.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Live-gateway black-box tests for token scope enforcement with mixed credentials.

A request can carry a bearer token in the ``Authorization`` header and a token in the
``jwt_token`` cookie. The tests prove that token IP restrictions apply to the bearer
credential even when cookies are present, and that an unrestricted bearer credential is
not narrowed by a restricted cookie.

Both API tokens are minted through ``POST /tokens`` on a private gateway subprocess (see
``isolated_gateway``). The gateway sees every request from ``127.0.0.1``. No Docker stack
is required.
"""

# Future
from __future__ import annotations

# Standard
from typing import NamedTuple
import uuid

# Third-Party
import httpx
import pytest

# Local
from tests.helpers.auth import make_auth_headers
from tests.live_gateway.e2e.test_candidate_credential_handshake import _GatewayFixture, isolated_gateway  # noqa: F401  pylint: disable=unused-import

pytestmark = [pytest.mark.e2e]


class _Credentials(NamedTuple):
    """Gateway address and the tokens used by the tests."""

    base_url: str
    admin: str
    blocked: str
    allowed: str


def _mint_token(client: httpx.Client, cidr: str) -> str:
    """Create an API token restricted to ``cidr`` and return its value.

    Raises:
        RuntimeError: If the gateway rejects the token request.
    """
    response = client.post("/tokens", json={"name": f"ipr-{uuid.uuid4().hex[:8]}", "expires_in_days": 1, "scope": {"ip_restrictions": [cidr]}})
    if response.status_code not in (200, 201):
        raise RuntimeError(f"setup: create token {response.status_code} {response.text[:300]}")
    return response.json()["access_token"]


@pytest.fixture
def credentials(isolated_gateway: _GatewayFixture) -> _Credentials:  # noqa: F811  pylint: disable=redefined-outer-name
    """Mint one token whose IP restriction excludes the caller and one that includes it."""
    client, admin_token, base_url, _ = isolated_gateway
    return _Credentials(base_url, admin_token, _mint_token(client, "192.0.2.10/32"), _mint_token(client, "127.0.0.1/32"))


def _list_tools(creds: _Credentials, bearer: str, cookie: str | None = None) -> int:
    """Return the status of ``GET /tools`` with ``bearer`` and an optional ``jwt_token`` cookie."""
    headers = make_auth_headers(bearer, extra_headers={"Cookie": f"jwt_token={cookie}"} if cookie is not None else None)
    return httpx.get(f"{creds.base_url}/tools", headers=headers, timeout=20, trust_env=False).status_code


def test_blocked_bearer_alone_denied(credentials: _Credentials) -> None:  # pylint: disable=redefined-outer-name
    """A bearer token restricted to another network is denied."""
    assert _list_tools(credentials, credentials.blocked) == 403


def test_blocked_bearer_with_invalid_cookie_denied(credentials: _Credentials) -> None:  # pylint: disable=redefined-outer-name
    """An invalid cookie does not lift the bearer token IP restriction."""
    assert _list_tools(credentials, credentials.blocked, cookie="invalid") == 403


def test_blocked_bearer_with_admin_cookie_denied(credentials: _Credentials) -> None:  # pylint: disable=redefined-outer-name
    """An unrestricted cookie does not lift the bearer token IP restriction."""
    assert _list_tools(credentials, credentials.blocked, cookie=credentials.admin) == 403


def test_allowed_bearer_with_invalid_cookie_ok(credentials: _Credentials) -> None:  # pylint: disable=redefined-outer-name
    """A bearer token whose restriction matches the caller succeeds with an invalid cookie."""
    assert _list_tools(credentials, credentials.allowed, cookie="invalid") == 200


def test_admin_bearer_with_blocked_cookie_ok(credentials: _Credentials) -> None:  # pylint: disable=redefined-outer-name
    """A restricted cookie does not narrow an unrestricted bearer token."""
    assert _list_tools(credentials, credentials.admin, cookie=credentials.blocked) == 200
