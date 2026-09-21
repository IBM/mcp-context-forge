# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp/test_catalog_oauth_registration.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box regression for catalog OAuth registration (#5967).

Exercises the externally observable v1 catalog API against a running gateway:
submitted ``oauth_credentials`` persisting as a real ``oauth_config`` on the created
gateway (rather than being silently dropped), the "OAuth2.1 & API Key" catalog entry
registering without a live connection test when no ``api_key`` is supplied, and the
resulting ``requires_oauth_config`` catalog state staying accurate for both.
"""

# Future
from __future__ import annotations

# Standard
from typing import Iterator

# Third-Party
import httpx
import pytest

# First-Party
from tests.helpers.auth import make_test_jwt
from tests.live_gateway.helpers.mcp_test_helpers import BASE_URL, JWT_SECRET, skip_no_gateway

pytestmark = [pytest.mark.e2e, skip_no_gateway]

_ADMIN_EMAIL = "admin@example.com"


def _admin_token() -> str:
    return make_test_jwt(_ADMIN_EMAIL, is_admin=True, teams=None, secret=JWT_SECRET)


def _headers() -> dict:
    return {"Authorization": f"Bearer {_admin_token()}"}


def _register(catalog_id: str, body: dict) -> httpx.Response:
    return httpx.post(f"{BASE_URL}/v1/catalog/{catalog_id}/register", headers=_headers(), json=body, timeout=15.0)


def _delete_gateway(server_id: str) -> None:
    httpx.delete(f"{BASE_URL}/v1/gateways/{server_id}", headers=_headers(), timeout=10.0)


@pytest.fixture
def registered_github() -> Iterator[dict]:
    """Register the catalog's OAuth-only ``github`` entry with no ``api_key``.

    Skips (rather than fails) when the catalog feature or the ``github`` catalog
    entry is unavailable, since both are external configuration this suite doesn't
    control.
    """
    response = _register(
        "github",
        {"oauth_credentials": {"issuer": "https://github.com", "scopes": ["repo", "read:user"]}},
    )
    if response.status_code == 404:
        pytest.skip(f"catalog 'github' entry unavailable: {response.text}")
    assert response.status_code == 200, response.text
    payload = response.json()
    try:
        yield payload
    finally:
        server_id = payload.get("server_id")
        if server_id:
            _delete_gateway(server_id)


@pytest.fixture
def registered_stripe() -> Iterator[dict]:
    """Register the catalog's mixed "OAuth2.1 & API Key" ``stripe`` entry with no ``api_key``."""
    response = _register("stripe", {})
    if response.status_code == 404:
        pytest.skip(f"catalog 'stripe' entry unavailable: {response.text}")
    assert response.status_code == 200, response.text
    payload = response.json()
    try:
        yield payload
    finally:
        server_id = payload.get("server_id")
        if server_id:
            _delete_gateway(server_id)


def test_oauth_credentials_persist_as_oauth_config(registered_github: dict) -> None:
    """Submitted ``oauth_credentials`` (issuer/scopes) must persist on the created gateway's
    ``oauth_config`` in the same call that registers it, disabled pending authorization."""
    assert registered_github["success"] is True
    assert registered_github["oauth_required"] is True
    server_id = registered_github["server_id"]

    gateway_response = httpx.get(f"{BASE_URL}/v1/gateways/{server_id}", headers=_headers(), timeout=10.0)
    assert gateway_response.status_code == 200, gateway_response.text
    gateway = gateway_response.json()

    assert gateway["enabled"] is False
    assert gateway["authType"] == "oauth"
    oauth_config = gateway.get("oauthConfig") or {}
    assert oauth_config.get("issuer") == "https://github.com"
    assert oauth_config.get("scopes") == ["repo", "read:user"]
    assert "client_secret" not in oauth_config


def test_mixed_oauth_and_api_key_registers_without_connection_test(registered_stripe: dict) -> None:
    """A catalog entry with auth_type "OAuth2.1 & API Key" and no submitted ``api_key`` must
    take the skip-initialization path (no live connection test with zero credentials) rather
    than failing registration outright."""
    assert registered_stripe["success"] is True
    assert registered_stripe["oauth_required"] is True


def test_requires_oauth_config_reflects_pending_authorization(registered_github: dict) -> None:
    """The catalog listing must keep flagging a disabled OAuth gateway as requiring
    authorization even though oauth_config is already persisted for it - a configured
    but not-yet-authorized gateway must never look indistinguishable from a working one."""
    list_response = httpx.get(f"{BASE_URL}/v1/catalog", headers=_headers(), params={"search": "github", "show_available_only": "false"}, timeout=10.0)
    assert list_response.status_code == 200, list_response.text
    servers = list_response.json()["servers"]
    matches = [s for s in servers if s["id"] == "github"]
    assert matches, f"catalog listing did not return the 'github' entry: {servers}"
    github_entry = matches[0]

    assert github_entry["is_registered"] is True
    assert github_entry["gateway_id"] == registered_github["server_id"]
    assert github_entry["requires_oauth_config"] is True
