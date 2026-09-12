# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/test_trust_mode_external_ingress_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box external-issuer ingress matrix (issues #5884/#5885, acceptance
row of #6272; ingress fix #5903).

Proves the authentication choke point (``get_current_user``) dispatches
external-issuer bearers to the trusted-OIDC-issuer (JWKS) verifier when
``JWT_TRUST_MODE=jwt-trust``:

    mapped_user_invokes_agent    -> 200  (external authn + group mapping + RBAC + team visibility)
    unmapped_user_invoke         -> 403  (authn ok, no role -> RBAC Layer-2 deny)
    wrong_audience_token         -> 401  (trust-root token, definitive failure, fail-closed)
    missing_revocation_claim     -> 401  (no jti -> unrevocable -> reject, fail-closed)
    nonexistent_agent_with_role  -> 404  (authn + RBAC ok, agent lookup terminates at 404)

Branch note (PR #6750): rows 1 and 5 were marked ``xfail(strict=False)``
because TokenScopingMiddleware validated claim-derived teams against local
``email_team_members`` and 403'd trust-only principals ("User is no longer
a member of the associated team") before RBAC/agent lookup. Task 10 (#5904,
PR #6751) landed the trusted-team exemption: both rows XPASS'd and the
markers were removed; the full matrix is green on this branch.

Gateway startup (operator-provided; run from the repo root). This exact
env was verified against a live run: the secret-strength validator rejects
the repo's conventional weak test secrets, so strong throwaway values are
required; SSO_ENABLED mounts the provider admin API; the SSRF allowances
permit the loopback stub-agent endpoint; SSL_CERT_FILE lets the gateway
trust the issuer's self-signed TLS cert for JWKS:

    mkdir -p /tmp/opencode
    # one-time: materialize the TLS cert the gateway must trust for JWKS
    uv run python -m tests.live_gateway.helpers.local_oidc_issuer ensure-material

    AUTH_REQUIRED=true \\
    MCPGATEWAY_A2A_ENABLED=true \\
    MCPGATEWAY_ADMIN_API_ENABLED=true \\
    SSO_ENABLED=true \\
    JWT_TRUST_MODE=jwt-trust \\
    SSO_API_TOKEN_AUTH_ENABLED=true \\
    DATABASE_URL=sqlite:////tmp/opencode/t9-e2e.db \\
    JWT_SECRET_KEY=t9-e2e-live-secret-3f9a1c7e5b24d68f0a2c4e6f8b1d3a5c7e9f0b2d \\  # pragma: allowlist secret
    AUTH_ENCRYPTION_SECRET=t9-e2e-encryption-secret-8f4a2c6e0b1d3a5c7e9f2b4d6a8c0e1f \\  # pragma: allowlist secret
    PLATFORM_ADMIN_PASSWORD='T9-e2e-AdminPass!x9Qw2Kp5' \\  # pragma: allowlist secret
    DEFAULT_USER_PASSWORD='T9-e2e-DefaultUser!x9Qw2Kp5' \\  # pragma: allowlist secret
    ADMIN_REQUIRE_PASSWORD_CHANGE_ON_BOOTSTRAP=false \\
    PASSWORD_CHANGE_ENFORCEMENT_ENABLED=false \\
    SSL_CERT_FILE=/tmp/cf-local-oidc-issuer/issuer-tls-cert.pem \\
    SSRF_ALLOW_LOCALHOST=true \\
    SSRF_ALLOW_PRIVATE_NETWORKS=true \\
    uv run uvicorn mcpgateway.main:app --host 127.0.0.1 --port 8013

Then (``JWT_SECRET_KEY`` must match the gateway so the seeded admin token verifies):

    MCP_CLI_BASE_URL=http://127.0.0.1:8013 JWT_TRUST_MODE=jwt-trust \\
    JWT_SECRET_KEY=t9-e2e-live-secret-3f9a1c7e5b24d68f0a2c4e6f8b1d3a5c7e9f0b2d \\
        uv run pytest tests/live_gateway/test_trust_mode_external_ingress_e2e.py -v

Seeding happens through the admin API with a gateway-signed platform-admin
JWT minted from the shared test secret (``JWT_SECRET_KEY`` above): an
SSOProvider row for the local issuer (``trusted_for_api_auth=True``,
``api_audience`` pinned), team ``agent-a-team``, A2A agent ``Agent-A``
(``visibility=team``, endpoint = the harness's stub agent), and the
external group mapping ``local-issuer-group-1 -> agent-a-team + developer``.

Token material is NEVER logged: assertion messages carry the status code
and a short body excerpt only (response bodies contain no secrets).
"""

# Future
from __future__ import annotations

# Standard
from datetime import datetime, timedelta, timezone
import os
import uuid

# Third-Party
import httpx
import pytest

# Local
from tests.helpers.auth import make_test_jwt
from .helpers.local_oidc_issuer import local_oidc_issuer  # noqa: F401  # fixture re-export
from .helpers.mcp_test_helpers import ADMIN_EMAIL, BASE_URL, JWT_SECRET, skip_no_gateway

pytestmark = [pytest.mark.e2e, skip_no_gateway]

# Expected gateway mode for this run; must match the stack configuration.
EXPECTED_TRUST_MODE = os.getenv("JWT_TRUST_MODE", "db")

skip_unless_trust_mode = pytest.mark.skipif(
    EXPECTED_TRUST_MODE != "jwt-trust",
    reason="requires the stack started with JWT_TRUST_MODE=jwt-trust",
)
pytestmark.append(skip_unless_trust_mode)

TEAM_NAME = "agent-a-team"
AGENT_NAME = "Agent-A"
PROVIDER_ID = "local-oidc-test"
API_AUDIENCE = "api://local-oidc-test-audience"
MAPPED_GROUP = "local-issuer-group-1"
UNMAPPED_GROUP = "local-issuer-group-unmapped"
NONEXISTENT_AGENT = "Agent-A-that-does-not-exist"

MATRIX = [
    # (scenario, expected status)
    # #6272 acceptance row. Previously xfail(strict=False): the TokenScopingMiddleware
    # membership check 403'd trust-only principals; Task 10 (#5904, PR #6751)
    # exempted resolver-derived trusted teams and this row went green (XPASS).
    ("mapped_user_invokes_agent", 200),
    ("unmapped_user_invoke", 403),  # authn ok, RBAC deny (deny without disclosure)
    ("wrong_audience_token", 401),  # trust-root token, definitive failure -> fail-closed
    ("missing_revocation_claim", 401),  # no jti -> unrevocable -> reject
    # Previously xfail(strict=False): blocked upstream of agent lookup by the same
    # membership check; Task 10 (#5904, PR #6751) closed it (XPASS at 404).
    ("nonexistent_agent_with_role", 404),  # authenticated + authorized -> agent lookup 404
]


def _admin_headers() -> dict[str, str]:
    """Gateway-signed platform-admin headers for seeding (shared test secret).

    token_use="session" gives DB-authoritative team resolution: the platform
    admin resolves to the admin bypass (token_teams=None), whereas a
    claim-less token would resolve token_teams=[] and the public-only
    semantics would suppress admin bypass on the admin APIs.
    """
    token = make_test_jwt(ADMIN_EMAIL, is_admin=True, secret=JWT_SECRET, token_use="session")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _base_claims(local_oidc_issuer, subject: str) -> dict:
    """Standard claim set for a local-issuer end-user token."""
    now = datetime.now(timezone.utc)
    return {
        "iss": local_oidc_issuer.issuer,
        "sub": subject,
        "aud": API_AUDIENCE,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=30)).timestamp()),
        "jti": uuid.uuid4().hex,
    }


def _mint_user_token(local_oidc_issuer, subject: str, *, groups: list[str]) -> str:
    """Mint a mapped/unmapped end-user token (RS256, local issuer key)."""
    claims = _base_claims(local_oidc_issuer, subject)
    claims["email"] = f"{subject}@example.com"
    claims["name"] = f"Live {subject}"
    claims["groups"] = groups
    return local_oidc_issuer.mint_token(claims)


def _invoke_agent(agent_name: str, token: str) -> httpx.Response:
    """POST the A2A invocation route with the given bearer token."""
    return httpx.post(
        f"{BASE_URL}/a2a/{agent_name}/invoke",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"parameters": {}, "interaction_type": "query"},
        timeout=20,
    )


def _seed_team(client: httpx.Client) -> str:
    """Create (or reuse) team ``agent-a-team``; return its team ID."""
    response = client.post(f"{BASE_URL}/teams/", json={"name": TEAM_NAME, "description": "T9 ingress matrix team"})
    if response.status_code not in (200, 201):
        # Re-run against a reused database: find the existing team by name.
        listing = client.get(f"{BASE_URL}/teams/", params={"include_inactive": "false"})
        assert listing.status_code == 200, f"team seed failed: {response.status_code} {response.text[:200]}; listing failed: {listing.status_code}"
        body = listing.json()
        teams = body.get("teams", body) if isinstance(body, dict) else body
        for team in teams:
            if isinstance(team, dict) and team.get("name") == TEAM_NAME:
                return team["id"]
        raise AssertionError(f"team seed failed: {response.status_code} {response.text[:200]}")
    return response.json()["id"]


def _seed_provider(client: httpx.Client, local_oidc_issuer) -> None:
    """Create the SSOProvider trust root for the local issuer (idempotent)."""
    # Delete-first keeps re-runs against a reused database deterministic.
    client.delete(f"{BASE_URL}/auth/sso/admin/providers/{PROVIDER_ID}")
    payload = {
        "id": PROVIDER_ID,
        "name": PROVIDER_ID,
        "display_name": "Local OIDC Test Issuer",
        "provider_type": "oidc",
        "client_id": "local-oidc-test-client",
        "client_secret": "local-oidc-test-secret",  # pragma: allowlist secret
        "authorization_url": f"{local_oidc_issuer.issuer}/authorize",
        "token_url": f"{local_oidc_issuer.issuer}/token",
        "userinfo_url": f"{local_oidc_issuer.issuer}/userinfo",
        "issuer": local_oidc_issuer.issuer,
        "trusted_for_api_auth": True,
        "api_audience": API_AUDIENCE,
    }
    response = client.post(f"{BASE_URL}/auth/sso/admin/providers", json=payload)
    assert response.status_code in (200, 201), f"provider seed failed: {response.status_code} {response.text[:200]}"


def _seed_agent(client: httpx.Client, team_id: str, local_oidc_issuer) -> None:
    """Register Agent-A (team-visible, endpoint = harness stub agent)."""
    payload = {
        "agent": {
            "name": AGENT_NAME,
            "description": "T9 ingress matrix stub agent",
            "endpoint_url": local_oidc_issuer.stub_agent_url,
            "agent_type": "generic",
        },
        "team_id": team_id,
        "visibility": "team",
    }
    response = client.post(f"{BASE_URL}/a2a/", json=payload)
    assert response.status_code in (200, 201, 409), f"agent seed failed: {response.status_code} {response.text[:200]}"


def _seed_mapping(client: httpx.Client, team_id: str, local_oidc_issuer) -> None:
    """Map external group -> team + developer role (idempotent on re-run)."""
    payload = {
        "issuer": local_oidc_issuer.issuer,
        "tenant": None,
        "external_group_id": MAPPED_GROUP,
        "cf_team_id": team_id,
        "cf_role": "developer",
    }
    response = client.post(f"{BASE_URL}/admin/external-group-mappings", json=payload)
    assert response.status_code in (200, 201, 409), f"mapping seed failed: {response.status_code} {response.text[:200]}"


@pytest.fixture(scope="module")
def seeded_gateway(local_oidc_issuer) -> dict[str, str]:
    """Seed the trust root, team, agent, and mapping; mint scenario tokens.

    Returns a scenario -> bearer-token mapping. Token material stays inside
    the fixture; tests only forward it in the Authorization header.
    """
    with httpx.Client(headers=_admin_headers(), timeout=20) as client:
        team_id = _seed_team(client)
        _seed_provider(client, local_oidc_issuer)
        _seed_agent(client, team_id, local_oidc_issuer)
        _seed_mapping(client, team_id, local_oidc_issuer)

    mapped_token = _mint_user_token(local_oidc_issuer, "oid-mapped-user-0001", groups=[MAPPED_GROUP])
    unmapped_token = _mint_user_token(local_oidc_issuer, "oid-unmapped-user-0001", groups=[UNMAPPED_GROUP])

    wrong_audience_claims = _base_claims(local_oidc_issuer, "oid-mapped-user-0001")
    wrong_audience_claims["aud"] = "api://not-the-gateway"
    wrong_audience_claims["groups"] = [MAPPED_GROUP]
    wrong_audience_token = local_oidc_issuer.mint_token(wrong_audience_claims)

    no_jti_claims = _base_claims(local_oidc_issuer, "oid-mapped-user-0001")
    del no_jti_claims["jti"]
    no_jti_claims["groups"] = [MAPPED_GROUP]
    missing_jti_token = local_oidc_issuer.mint_token(no_jti_claims)

    return {
        "mapped": mapped_token,
        "unmapped": unmapped_token,
        "wrong_audience": wrong_audience_token,
        "missing_jti": missing_jti_token,
    }


@pytest.mark.parametrize("scenario,expected", MATRIX)
def test_ingress_matrix(scenario, expected, local_oidc_issuer, seeded_gateway):
    """External-issuer ingress matrix against the live trust-mode gateway."""
    if scenario == "mapped_user_invokes_agent":
        response = _invoke_agent(AGENT_NAME, seeded_gateway["mapped"])
    elif scenario == "unmapped_user_invoke":
        response = _invoke_agent(AGENT_NAME, seeded_gateway["unmapped"])
    elif scenario == "wrong_audience_token":
        response = _invoke_agent(AGENT_NAME, seeded_gateway["wrong_audience"])
    elif scenario == "missing_revocation_claim":
        response = _invoke_agent(AGENT_NAME, seeded_gateway["missing_jti"])
    elif scenario == "nonexistent_agent_with_role":
        response = _invoke_agent(NONEXISTENT_AGENT, seeded_gateway["mapped"])
    else:  # pragma: no cover - parametrization guard
        raise AssertionError(f"unknown scenario {scenario}")

    assert response.status_code == expected, f"{scenario}: expected {expected}, got {response.status_code} {response.text[:200]}"
    if scenario == "unmapped_user_invoke":
        # The deny must come from RBAC (Layer 2), not from the token-scoping
        # membership check: the unmapped principal has NO mapped teams
        # (public-only), so "no longer a member" here would mean claim
        # extraction fabricated a team grant.
        assert "no longer a member" not in response.text, f"{scenario}: deny came from the wrong layer: {response.text[:200]}"
