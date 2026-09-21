# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/helpers/trust_mode_seed.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Shared seeding helpers for live trust-mode gateway tests.

Every function targets the running gateway at ``BASE_URL`` through the
admin API with a gateway-signed platform-admin JWT. Seeding is
idempotent: re-runs against a reused database reuse existing rows.
"""

# Future
from __future__ import annotations

# Standard
from typing import Optional

# Third-Party
import httpx

# Local
from tests.helpers.auth import make_test_jwt

from .mcp_test_helpers import ADMIN_EMAIL, BASE_URL, JWT_SECRET


def admin_headers() -> dict[str, str]:
    """Gateway-signed platform-admin headers for seeding (shared test secret).

    token_use="session" gives DB-authoritative team resolution: the platform
    admin resolves to the admin bypass (token_teams=None), whereas a
    claim-less token would resolve token_teams=[] and the public-only
    semantics would suppress admin bypass on the admin APIs.
    """
    token = make_test_jwt(ADMIN_EMAIL, is_admin=True, secret=JWT_SECRET, token_use="session")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def seed_team(client: httpx.Client, name: str, description: str) -> str:
    """Create (or reuse) team ``name``; return its team ID."""
    response = client.post(f"{BASE_URL}/teams/", json={"name": name, "description": description})
    if response.status_code not in (200, 201):
        listing = client.get(f"{BASE_URL}/teams/", params={"include_inactive": "false"})
        assert listing.status_code == 200, f"team seed failed: {response.status_code} {response.text[:200]}; listing failed: {listing.status_code}"
        body = listing.json()
        teams = body.get("teams", body) if isinstance(body, dict) else body
        for team in teams:
            if isinstance(team, dict) and team.get("name") == name:
                return team["id"]
        raise AssertionError(f"team seed failed: {response.status_code} {response.text[:200]}")
    return response.json()["id"]


def seed_provider(
    client: httpx.Client,
    provider_id: str,
    issuer: str,
    audience: str,
    *,
    token_url: Optional[str] = None,
    jwks_uri: Optional[str] = None,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> None:
    """Create the SSOProvider trust root for ``issuer`` (idempotent)."""
    client.delete(f"{BASE_URL}/auth/sso/admin/providers/{provider_id}")
    payload = {
        "id": provider_id,
        "name": provider_id,
        "display_name": provider_id,
        "provider_type": "oidc",
        "client_id": client_id or "local-oidc-test-client",
        "client_secret": client_secret or "local-oidc-test-secret",  # pragma: allowlist secret
        "authorization_url": f"{issuer}/authorize",
        "token_url": token_url or f"{issuer}/token",
        "jwks_uri": jwks_uri,
        "userinfo_url": f"{issuer}/userinfo",
        "issuer": issuer,
        "trusted_for_api_auth": True,
        "api_audience": audience,
    }
    response = client.post(f"{BASE_URL}/auth/sso/admin/providers", json=payload)
    assert response.status_code in (200, 201), f"provider seed failed: {response.status_code} {response.text[:200]}"


def seed_agent(client: httpx.Client, name: str, team_id: str, endpoint_url: str, description: str) -> None:
    """Register a team-visible A2A agent (idempotent)."""
    payload = {
        "agent": {
            "name": name,
            "description": description,
            "endpoint_url": endpoint_url,
            "agent_type": "generic",
        },
        "team_id": team_id,
        "visibility": "team",
    }
    response = client.post(f"{BASE_URL}/a2a/", json=payload)
    assert response.status_code in (200, 201, 409), f"agent seed failed: {response.status_code} {response.text[:200]}"


def seed_mapping(client: httpx.Client, issuer: str, tenant: Optional[str], external_group_id: str, cf_team_id: str, cf_role: str) -> str:
    """Map external group -> team + role; return the mapping ID (idempotent)."""
    payload = {
        "issuer": issuer,
        "tenant": tenant,
        "external_group_id": external_group_id,
        "cf_team_id": cf_team_id,
        "cf_role": cf_role,
    }
    response = client.post(f"{BASE_URL}/admin/external-group-mappings", json=payload)
    if response.status_code in (200, 201):
        return response.json()["id"]
    if response.status_code == 409:
        listing = client.get(f"{BASE_URL}/admin/external-group-mappings")
        assert listing.status_code == 200, f"mapping listing failed: {listing.status_code} {listing.text[:200]}"
        for row in listing.json():
            if row.get("issuer") == issuer and row.get("external_group_id") == external_group_id and row.get("tenant") == tenant:
                return row["id"]
    raise AssertionError(f"mapping seed failed: {response.status_code} {response.text[:200]}")


def update_mapping(client: httpx.Client, mapping_id: str, *, cf_team_id: Optional[str] = None, cf_role: Optional[str] = None) -> httpx.Response:
    """PUT a partial mapping update (team repoint and/or role change)."""
    payload: dict[str, str] = {}
    if cf_team_id is not None:
        payload["cf_team_id"] = cf_team_id
    if cf_role is not None:
        payload["cf_role"] = cf_role
    return client.put(f"{BASE_URL}/admin/external-group-mappings/{mapping_id}", json=payload)
