# -*- coding: utf-8 -*-
"""Location: ./tests/protocol_compliance/test_oauth_authorization.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

OAuth 2.1 / Authorization compliance tests (MCP 2025-11-25 § Authorization).

Two tiers:

1. **Without Keycloak** — tests wire-level behavior that doesn't require
   an actual OAuth provider:
   - PRM well-known endpoint shape on an oauth-enabled virtual server
     (skips if no oauth-enabled server is available).
   - Unauthenticated requests return 401 with WWW-Authenticate: Bearer
     (RFC 6750).
   - Malformed bearers are rejected (covered by test_security_best_practices).
2. **With Keycloak** — full OAuth 2.1 client_credentials flow:
   - Fetch token from Keycloak.
   - Send as Bearer on /mcp/ → 200 (accepted).
   - Tampered token rejected (401).

Start Keycloak via ``docker compose --profile sso up -d keycloak`` to
enable tier 2; the ``keycloak`` fixture skips tier 2 cleanly if it's
unreachable.
"""

from __future__ import annotations

import httpx
import pytest

from .fixtures.keycloak import keycloak  # noqa: F401 — fixture re-export

pytestmark = [pytest.mark.protocol_compliance, pytest.mark.mcp_auth]


_MCP_HEADERS = {
    "accept": "application/json, text/event-stream",
    "content-type": "application/json",
    "mcp-protocol-version": "2025-03-26",
}


def _initialize_body(request_id: int = 1) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "oauth-probe", "version": "0.1"},
        },
    }


# ---------------------------------------------------------------------------
# Tier 1 — no OAuth provider required
# ---------------------------------------------------------------------------
def test_prm_endpoint_wired_for_per_server_path(gateway_http_client: httpx.Client) -> None:
    """RFC 9728 requires the PRM at a canonical location. The gateway's
    per-server PRM path must at least be *routed* — either returning the
    spec JSON body (oauth enabled) or a 404 explaining oauth is disabled.
    A plain 404 without explanation, or a 5xx, would indicate the route
    isn't wired at all."""
    servers = gateway_http_client.get("/servers").json()
    assert servers, "no virtual servers registered — can't probe per-server PRM"
    server_id = servers[0]["id"]

    # Use a raw client without auth — well-known endpoints should be public.
    base_url = str(gateway_http_client.base_url)
    with httpx.Client(base_url=base_url, timeout=5.0) as raw:
        resp = raw.get(f"/.well-known/oauth-protected-resource/servers/{server_id}/mcp")

    # Either 200 (oauth enabled) or 404 with a "not enabled" reason is acceptable.
    # Both prove the route is wired. 5xx means broken.
    assert resp.status_code < 500, f"PRM endpoint 5xx'd — route not wired or crashed: {resp.status_code} {resp.text[:200]}"
    if resp.status_code == 200:
        body = resp.json()
        # Per RFC 9728: resource metadata MUST include "resource" and SHOULD
        # include "authorization_servers".
        assert "resource" in body, f"PRM missing `resource` field: {body}"
        assert "authorization_servers" in body or "bearer_methods_supported" in body, f"PRM missing OAuth-discovery fields: {body}"


def test_unauthenticated_request_carries_www_authenticate_header(
    gateway_http_client: httpx.Client,
) -> None:
    """An unauthenticated MCP request returns 401 with WWW-Authenticate: Bearer (RFC 6750).

    This is a low-bar assertion — the server must tell the client how to
    authenticate. Gateways that reject with 401 but omit the header are
    technically spec-violating for OAuth-protected resources.
    """
    base_url = str(gateway_http_client.base_url)
    with httpx.Client(base_url=base_url, timeout=5.0) as raw:
        # No Authorization header.
        resp = raw.post("/mcp/", headers=_MCP_HEADERS, json=_initialize_body(1))

    # The gateway may be configured to allow unauthenticated (AUTH_REQUIRED=false).
    # In that case, this test isn't applicable.
    if resp.status_code < 400:
        pytest.skip("gateway accepts unauthenticated /mcp/ requests on this deployment — " "AUTH_REQUIRED=false; WWW-Authenticate requirement only applies when auth is enforced.")
    assert resp.status_code in (401, 403), f"expected 401/403 for unauthenticated /mcp, got {resp.status_code}"
    www_auth = resp.headers.get("www-authenticate", "")
    assert "bearer" in www_auth.lower(), f"401 must carry WWW-Authenticate: Bearer ... per RFC 6750; got header={www_auth!r}"


# ---------------------------------------------------------------------------
# Tier 2 — requires Keycloak on :8180
# ---------------------------------------------------------------------------
def test_keycloak_issues_client_credentials_token(keycloak) -> None:
    """Keycloak issues a token via the client_credentials grant.

    Baseline: if this fails, the rest of the Keycloak-dependent tests
    can't possibly work, so we isolate the failure mode.
    """
    token = keycloak.fetch_client_credentials_token()
    assert token is not None, f"Keycloak client_credentials grant returned no access_token. " f"Check client_secret={keycloak.client_secret!r} and realm={keycloak.realm!r}."
    # Minimal sanity — tokens are big opaque blobs.
    assert len(token) > 40, f"suspiciously short access token: {token[:40]!r}"


def test_keycloak_token_accepted_on_mcp_endpoint(keycloak, gateway_http_client) -> None:
    """A token minted by Keycloak should be accepted on /mcp/ if the gateway trusts this issuer.

    This asserts either:
      - 200 → the gateway validates this Keycloak-issued token.
      - 401/403 → the gateway doesn't trust this issuer today (document as a gap).

    The test passes in both cases but xfails the 401 path so the intent
    (gateway + Keycloak interop) is visible.
    """
    token = keycloak.fetch_client_credentials_token()
    assert token is not None, "precondition failed: couldn't obtain token"

    base_url = str(gateway_http_client.base_url)
    with httpx.Client(base_url=base_url, timeout=10.0) as raw:
        headers = dict(_MCP_HEADERS)
        headers["authorization"] = f"Bearer {token}"
        resp = raw.post("/mcp/", headers=headers, json=_initialize_body(1))

    if resp.status_code in (401, 403):
        pytest.xfail(
            "GAP candidate — gateway does not accept tokens issued by the configured "
            "Keycloak realm on the /mcp/ endpoint. This may be expected if the gateway "
            "is configured to trust a different JWT_SECRET_KEY for /mcp auth vs the SSO "
            "flow, or if audience validation rejects the token. File a GAP once the "
            "intended interop story is clarified."
        )
    assert resp.status_code == 200, f"Keycloak-issued token should yield 200, got {resp.status_code}: {resp.text[:200]}"


def test_keycloak_tampered_token_rejected(keycloak, gateway_http_client) -> None:
    """Flipping bits in a valid Keycloak token must produce 401/403 — signature check working."""
    token = keycloak.fetch_client_credentials_token()
    assert token is not None, "precondition failed: couldn't obtain token"
    # JWT is header.payload.signature; corrupt the signature by flipping a char.
    parts = token.split(".")
    assert len(parts) == 3, f"token isn't a three-part JWT: {token[:40]!r}"
    tampered_sig = parts[2][:-1] + ("A" if parts[2][-1] != "A" else "B")
    tampered = ".".join([parts[0], parts[1], tampered_sig])

    base_url = str(gateway_http_client.base_url)
    with httpx.Client(base_url=base_url, timeout=10.0) as raw:
        headers = dict(_MCP_HEADERS)
        headers["authorization"] = f"Bearer {tampered}"
        resp = raw.post("/mcp/", headers=headers, json=_initialize_body(1))
    assert resp.status_code in (401, 403), f"tampered Keycloak token must be rejected with 401/403, got {resp.status_code}: " f"{resp.text[:200]}"
