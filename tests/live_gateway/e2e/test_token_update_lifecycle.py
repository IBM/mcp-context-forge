# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/e2e/test_token_update_lifecycle.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Live-gateway black-box tests for the API token update lifecycle.

An API token's scope is signed into the issued bearer, and a bearer is rejected only once
its JTI is revoked. The tests prove that:

- deactivating a token through ``PUT /tokens/{id}`` stops the issued bearer immediately,
- a deactivated token cannot be reactivated,
- a token cannot be created in an inactive state,
- the scope of an issued token cannot be changed in place, and
- ``DELETE /tokens/{id}`` keeps revoking the bearer.

Every test runs with the auth cache enabled and disabled, so a stale cached decision cannot
hide a regression. Tokens are minted on a private gateway subprocess (see ``isolated_gateway``).
No Docker stack is required.
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

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.parametrize("isolated_gateway", [{}, {"AUTH_CACHE_ENABLED": "false"}], ids=["auth-cache-on", "auth-cache-off"], indirect=True),
]

_SCOPE = {"ip_restrictions": ["127.0.0.1/32"]}
_OTHER_SCOPE = {"ip_restrictions": ["192.0.2.10/32"]}


class _Token(NamedTuple):
    """An issued API token."""

    token_id: str
    bearer: str


class _Gateway(NamedTuple):
    """Gateway client (admin credentials) and address."""

    client: httpx.Client
    base_url: str


def _mint_token(gateway: _Gateway) -> _Token:
    """Create an API token and return its id and bearer value.

    Raises:
        RuntimeError: If the gateway rejects the token request.
    """
    response = gateway.client.post("/tokens", json={"name": f"lifecycle-{uuid.uuid4().hex[:8]}", "expires_in_days": 1, "scope": _SCOPE})
    if response.status_code not in (200, 201):
        raise RuntimeError(f"setup: create token {response.status_code} {response.text[:300]}")
    body = response.json()
    return _Token(body["token"]["id"], body["access_token"])


def _list_tools(gateway: _Gateway, bearer: str) -> int:
    """Return the status of ``GET /tools`` called with ``bearer``."""
    return httpx.get(f"{gateway.base_url}/tools", headers=make_auth_headers(bearer), timeout=20, trust_env=False).status_code


@pytest.fixture
def gateway(isolated_gateway: _GatewayFixture) -> _Gateway:  # noqa: F811  pylint: disable=redefined-outer-name
    """Expose the admin client and base URL of the private gateway."""
    client, _, base_url, _ = isolated_gateway
    return _Gateway(client, base_url)


@pytest.fixture
def token(gateway: _Gateway) -> _Token:  # pylint: disable=redefined-outer-name
    """Mint a token and prove its bearer is accepted before each test acts on it."""
    issued = _mint_token(gateway)
    assert _list_tools(gateway, issued.bearer) == 200
    return issued


def test_deactivate_stops_issued_bearer(gateway: _Gateway, token: _Token) -> None:  # pylint: disable=redefined-outer-name
    """Deactivating a token rejects its bearer on the next request."""
    response = gateway.client.put(f"/tokens/{token.token_id}", json={"is_active": False})

    assert response.status_code == 200
    assert response.json()["is_active"] is False
    assert _list_tools(gateway, token.bearer) == 401


def test_deactivated_token_cannot_be_reactivated(gateway: _Gateway, token: _Token) -> None:  # pylint: disable=redefined-outer-name
    """Reactivation is refused and the bearer stays rejected."""
    assert gateway.client.put(f"/tokens/{token.token_id}", json={"is_active": False}).status_code == 200

    response = gateway.client.put(f"/tokens/{token.token_id}", json={"is_active": True})

    assert response.status_code == 400
    assert "cannot be reactivated" in response.text
    assert _list_tools(gateway, token.bearer) == 401


def test_token_cannot_be_created_inactive(gateway: _Gateway) -> None:  # pylint: disable=redefined-outer-name
    """A token request with is_active=false is refused and no bearer is returned."""
    response = gateway.client.post("/tokens", json={"name": f"inactive-{uuid.uuid4().hex[:8]}", "expires_in_days": 1, "is_active": False})

    assert response.status_code == 400
    assert "inactive state" in response.text
    assert "access_token" not in response.text


def test_scope_change_is_refused(gateway: _Gateway, token: _Token) -> None:  # pylint: disable=redefined-outer-name
    """A different scope is refused and the issued bearer keeps its original scope."""
    response = gateway.client.put(f"/tokens/{token.token_id}", json={"scope": _OTHER_SCOPE})

    assert response.status_code == 400
    assert "cannot be changed" in response.text
    assert _list_tools(gateway, token.bearer) == 200


def test_resending_the_issued_scope_is_accepted(gateway: _Gateway, token: _Token) -> None:  # pylint: disable=redefined-outer-name
    """Echoing the issued scope back is accepted and changes nothing."""
    response = gateway.client.put(f"/tokens/{token.token_id}", json={"scope": _SCOPE, "description": "renamed"})

    assert response.status_code == 200
    assert _list_tools(gateway, token.bearer) == 200


def test_delete_still_stops_issued_bearer(gateway: _Gateway, token: _Token) -> None:  # pylint: disable=redefined-outer-name
    """Control: revoking through DELETE rejects the bearer."""
    assert gateway.client.delete(f"/tokens/{token.token_id}").status_code in (200, 204)

    assert _list_tools(gateway, token.bearer) == 401
