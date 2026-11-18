# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/e2e/test_forwarded_ip_trust.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Live-gateway black-box tests for ``FORWARDED_ALLOW_IPS``.

The gateway honors ``X-Forwarded-For`` only from peers listed in ``FORWARDED_ALLOW_IPS``.
Each test mints an API token restricted to one address through ``POST /tokens`` on a
private gateway subprocess (see ``isolated_gateway``) and calls ``GET /tools`` from
``127.0.0.1`` with a forwarded address. When loopback is not a trusted proxy, the header
must not change the address that the token IP restriction checks. No Docker stack is
required.
"""

# Future
from __future__ import annotations

# Standard
import uuid

# Third-Party
import httpx
import pytest

# Local
from tests.helpers.auth import make_auth_headers
from tests.live_gateway.e2e.test_candidate_credential_handshake import _GatewayFixture, isolated_gateway  # noqa: F401  pylint: disable=unused-import

pytestmark = [pytest.mark.e2e]

FORWARDED_IP = "198.51.100.7"
LOOPBACK_UNTRUSTED = {"FORWARDED_ALLOW_IPS": "192.0.2.1"}
LOOPBACK_TRUSTED = {"FORWARDED_ALLOW_IPS": "127.0.0.1,::1"}


def _list_tools_with_restricted_token(gateway: _GatewayFixture, cidr: str) -> int:
    """Mint a token restricted to ``cidr`` and return the ``GET /tools`` status with a forwarded address.

    Raises:
        RuntimeError: If the gateway rejects the token request.
    """
    client, _, base_url, _ = gateway
    response = client.post("/tokens", json={"name": f"fwd-{uuid.uuid4().hex[:8]}", "expires_in_days": 1, "scope": {"ip_restrictions": [cidr]}})
    if response.status_code not in (200, 201):
        raise RuntimeError(f"setup: create token {response.status_code} {response.text[:300]}")
    headers = make_auth_headers(response.json()["access_token"], extra_headers={"X-Forwarded-For": FORWARDED_IP})
    return httpx.get(f"{base_url}/tools", headers=headers, timeout=20, trust_env=False).status_code


@pytest.mark.parametrize("isolated_gateway", [LOOPBACK_UNTRUSTED], indirect=True)
def test_untrusted_peer_cannot_spoof_allowed_ip(isolated_gateway: _GatewayFixture) -> None:  # noqa: F811  pylint: disable=redefined-outer-name
    """A forwarded address from an untrusted peer does not satisfy the token IP restriction."""
    assert _list_tools_with_restricted_token(isolated_gateway, f"{FORWARDED_IP}/32") == 403


@pytest.mark.parametrize("isolated_gateway", [LOOPBACK_UNTRUSTED], indirect=True)
def test_untrusted_peer_matched_on_socket_ip(isolated_gateway: _GatewayFixture) -> None:  # noqa: F811  pylint: disable=redefined-outer-name
    """The token IP restriction checks the socket address of an untrusted peer."""
    assert _list_tools_with_restricted_token(isolated_gateway, "127.0.0.1/32") == 200


@pytest.mark.parametrize("isolated_gateway", [LOOPBACK_TRUSTED], indirect=True)
def test_trusted_loopback_proxy_forwards_client_ip(isolated_gateway: _GatewayFixture) -> None:  # noqa: F811  pylint: disable=redefined-outer-name
    """A loopback proxy listed in ``FORWARDED_ALLOW_IPS`` forwards the client address."""
    assert _list_tools_with_restricted_token(isolated_gateway, f"{FORWARDED_IP}/32") == 200
