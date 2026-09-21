# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/test_trust_mode_entra_inline_groups_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Runbook (from the repo root):

    # 1. Start the Entra trust-mode testing stack (assumes .env exists
    #    with the strong secrets from make init-secrets-patch-env):
    make docker-nuke && make testing-up-entra

    # 2. Token sourcing, first match wins:
    #    a) Export AZURE_CLIENT_ID + AZURE_CLIENT_SECRET + AZURE_TENANT_ID.
    #       The harness provisions a throwaway user and group, acquires a
    #       v2 token through ROPC, and deletes both objects after the session.
    #    b) Or set ENTRA_LIVE_TOKEN_FILE to a pre-acquired non-overage
    #       end-user token saved in an untracked file.

    # 3. Run (JWT_SECRET_KEY must match the running gateway container's value;
    #    TESTS_DNS_PASSTHROUGH_HOSTS is required because tests/conftest.py
    #    blackholes external DNS by default):
    TESTS_DNS_PASSTHROUGH_HOSTS="login.microsoftonline.com,graph.microsoft.com" \
    JWT_TRUST_MODE=jwt-trust \
    JWT_SECRET_KEY="$(docker compose exec -T gateway printenv JWT_SECRET_KEY)" \
        uv run pytest tests/live_gateway/test_trust_mode_entra_inline_groups_e2e.py -v

The gateway is the compose testing gateway behind nginx :8080
(MCP_CLI_BASE_URL default). JWKS verification hits the real Entra
issuer over public CAs. The downstream stub A2A agent runs in this
pytest process and is reached by the gateway container through
host.docker.internal.
"""

# Future
from __future__ import annotations

# Standard
import os
import time
import uuid

# Third-Party
import httpx
import pytest

# Local
from .helpers.entra_live import entra_inline_token, inspect_token  # noqa: F401  # fixture re-export
from .helpers.local_oidc_issuer import local_oidc_issuer  # noqa: F401  # fixture re-export
from .helpers.mcp_test_helpers import BASE_URL, skip_no_gateway
from .helpers.trust_mode_seed import admin_headers, seed_agent, seed_mapping, seed_provider, seed_team, update_mapping

AGENT_NAME = "Entra-Live-Agent"
PROVIDER_ID = "entra-live-trust-root"
NO_AGENT_TEAM_NAME = "Entra Live No-Agent Team"

pytestmark = [pytest.mark.e2e, skip_no_gateway]
pytestmark.append(pytest.mark.skipif(os.getenv("JWT_TRUST_MODE", "db") != "jwt-trust", reason="requires the stack started with JWT_TRUST_MODE=jwt-trust (make testing-up-entra)"))


def _invoke(agent_name: str, token: str, message_text: str) -> httpx.Response:
    """POST the A2A invocation route with the given bearer token and message."""
    return httpx.post(
        f"{BASE_URL}/a2a/{agent_name}/invoke",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={
            "parameters": {
                "message": {
                    "messageId": f"msg-{uuid.uuid4().hex[:8]}",
                    "role": "user",
                    "parts": [{"text": message_text}],
                }
            },
            "interaction_type": "query",
        },
        timeout=30,
    )


@pytest.fixture(scope="module")
def entra_seeded(entra_inline_token, local_oidc_issuer):  # noqa: F811  # params are the re-exported fixtures
    """Seed trust root, team, stub-backed agent, and mapping from the REAL token.

    Returns a dict with the token, seeding values, mapping id, and the
    stub-agent invocation log. Teardown deletes the mapping so later runs
    and other suites never inherit a stale team/role for this group.
    """
    token, info = entra_inline_token
    with httpx.Client(headers=admin_headers(), timeout=30) as client:
        team_id = seed_team(client, "Entra Live Agent Team", "Live Entra inline-groups e2e")
        no_agent_team_id = seed_team(client, NO_AGENT_TEAM_NAME, "Mapped team without agent access")
        # Entra v1 issuers (sts.windows.net) publish a cross-origin JWKS by
        # design; the provider-level jwks_uri override points verification
        # at the same-origin tenant keys instead.
        v1_jwks = info["issuer"].rstrip("/") + "/discovery/keys" if "sts.windows.net" in info["issuer"] else None
        seed_provider(client, PROVIDER_ID, info["issuer"], info["audience"], jwks_uri=v1_jwks)
        seed_agent(client, AGENT_NAME, team_id, local_oidc_issuer.stub_agent_url_for_gateway, "Live Entra stub-backed agent")
        mapping_id = seed_mapping(client, info["issuer"], info["tenant_id"], info["groups"][0], team_id, "developer")
    yield {
        "token": token,
        "info": info,
        "team_id": team_id,
        "no_agent_team_id": no_agent_team_id,
        "mapping_id": mapping_id,
        "stub_invocations": local_oidc_issuer.stub_agent_invocations,
    }
    with httpx.Client(headers=admin_headers(), timeout=30) as client:
        client.delete(f"{BASE_URL}/admin/external-group-mappings/{mapping_id}")


def test_uc1_mapped_developer_invokes_agent(entra_seeded):
    """UC1: mapped group + developer -> 200 and the message reaches the agent."""
    before = len(entra_seeded["stub_invocations"])
    message = "Hello from live Entra inline-groups e2e"
    response = _invoke(AGENT_NAME, entra_seeded["token"], message)
    assert response.status_code == 200, f"UC1 expected 200, got {response.status_code}: {response.text[:200]}"
    artifacts = response.json()["result"]["artifacts"]
    echoed = artifacts[0]["parts"][0]["text"] if artifacts and artifacts[0].get("parts") else ""
    assert message in echoed, f"UC1 echo round-trip failed: {echoed[:200]}"
    assert len(entra_seeded["stub_invocations"]) == before + 1, "UC1: downstream stub agent was not called exactly once"


def test_uc2_repointed_team_hides_agent_with_404(entra_seeded):
    """UC2: same token, mapping moved to a team without the agent -> 404, agent never called."""
    with httpx.Client(headers=admin_headers(), timeout=30) as client:
        update = update_mapping(client, entra_seeded["mapping_id"], cf_team_id=entra_seeded["no_agent_team_id"])
        assert update.status_code == 200, f"mapping repoint failed: {update.status_code} {update.text[:200]}"
        body = update.json()
        assert body["cf_team_id"] == entra_seeded["no_agent_team_id"], "mapping PUT did not persist the new team"
        assert body["cf_role"] == "developer", "mapping PUT must retain the role absent from the payload"
    before = len(entra_seeded["stub_invocations"])
    denied_text = "This live request must not reach the stub agent"
    response = _invoke(AGENT_NAME, entra_seeded["token"], denied_text)
    assert response.status_code == 404, f"UC2 expected 404, got {response.status_code}: {response.text[:200]}"
    assert "not found" in response.text.lower(), f"UC2 body must be the agent-not-found detail: {response.text[:200]}"
    assert len(entra_seeded["stub_invocations"]) == before, "UC2 LEAK: denied message reached the downstream agent"


def test_uc3_viewer_sees_but_cannot_invoke(entra_seeded):
    """UC3: mapping repointed to viewer -> list 200, read 200, invoke 403, agent never called."""
    headers = {"Authorization": f"Bearer {entra_seeded['token']}", "Content-Type": "application/json"}
    with httpx.Client(headers=admin_headers(), timeout=30) as client:
        update = update_mapping(client, entra_seeded["mapping_id"], cf_team_id=entra_seeded["team_id"], cf_role="viewer")
        assert update.status_code == 200, f"mapping role change failed: {update.status_code} {update.text[:200]}"
        body = update.json()
        assert body["cf_team_id"] == entra_seeded["team_id"] and body["cf_role"] == "viewer", "mapping PUT did not persist team+viewer"
    listing = httpx.get(f"{BASE_URL}/a2a/", headers=headers, timeout=30)
    assert listing.status_code == 200, f"UC3 list expected 200, got {listing.status_code}"
    agents = listing.json() if isinstance(listing.json(), list) else listing.json().get("agents", [])
    agent_row = next((row for row in agents if row.get("name") == AGENT_NAME), None)
    assert agent_row is not None, "UC3: viewer cannot see the team-visible agent in the list"
    read = httpx.get(f"{BASE_URL}/a2a/{agent_row['id']}", headers=headers, timeout=30)
    assert read.status_code == 200, f"UC3 read expected 200, got {read.status_code}"
    before = len(entra_seeded["stub_invocations"])
    denied_text = "This live viewer request must not reach the stub agent"
    response = _invoke(AGENT_NAME, entra_seeded["token"], denied_text)
    assert response.status_code == 403, f"UC3 expected 403, got {response.status_code}: {response.text[:200]}"
    assert "access denied" in response.text.lower(), f"UC3 body must be the RBAC deny detail: {response.text[:200]}"
    assert len(entra_seeded["stub_invocations"]) == before, "UC3 LEAK: viewer message reached the downstream agent"


@pytest.fixture(scope="module")
def entra_overage_token():
    """Yield (token, info) from a REAL overage-marked Entra token; skip when absent."""
    path = os.getenv("ENTRA_OVERAGE_TOKEN_FILE")
    if not path or not os.path.isfile(path):
        pytest.skip(
            "UC4 needs a real overage token: set ENTRA_OVERAGE_TOKEN_FILE to a v2 token "
            "for a user in more than 200 groups (group-overage marker present)"
        )
    with open(path, encoding="utf-8") as handle:
        token = handle.read().strip()
    info = inspect_token(token)
    if not info["has_overage_marker"]:
        pytest.skip("UC4 token has no overage marker; need a member of >200 groups")
    if not isinstance(info["exp"], int) or info["exp"] <= int(time.time()):
        pytest.skip("UC4 token is expired; re-acquire before running")
    yield token, info


def test_uc4_overage_resolved_via_graph_allows_invoke(entra_overage_token, local_oidc_issuer):  # noqa: F811  # params are the re-exported fixtures
    """UC4: overage marker + graph_lookup policy -> real Graph resolves groups -> 200.

    The gateway (started via make testing-up-entra) performs the app-only
    Graph resolution itself: the provider record below carries real
    Graph-capable client credentials, and the group mapped to the agent
    team is the overage user's group resolved BY GRAPH (not present
    inline).
    """
    if os.getenv("JWT_TRUST_OVERAGE_POLICY", "fail_closed") != "graph_lookup":
        pytest.skip("UC4 requires the gateway started with JWT_TRUST_OVERAGE_POLICY=graph_lookup (make testing-up-entra)")
    graph_client_id = os.getenv("ENTRA_GRAPH_CLIENT_ID") or os.getenv("AZURE_CLIENT_ID") or os.getenv("ENTRA_CLIENT_ID")
    graph_client_secret = os.getenv("ENTRA_GRAPH_CLIENT_SECRET") or os.getenv("AZURE_CLIENT_SECRET") or os.getenv("ENTRA_CLIENT_SECRET")
    if not (graph_client_id and graph_client_secret):
        pytest.skip(
            "UC4 needs Graph-capable app credentials (admin-consented GroupMember.Read.All): "
            "set ENTRA_GRAPH_CLIENT_ID + ENTRA_GRAPH_CLIENT_SECRET (or AZURE_CLIENT_ID + AZURE_CLIENT_SECRET)"
        )
    token, info = entra_overage_token
    # ENTRA_OVERAGE_MAPPED_GROUP: when the overage token carries NO inline groups,
    # this env var must name a group the overage user belongs to; Graph resolves the
    # membership and the mapping turns it into the agent team + developer role.
    overage_group = info["groups"][0] if info["groups"] else os.getenv("ENTRA_OVERAGE_MAPPED_GROUP")
    if not overage_group:
        pytest.skip("UC4 token has no inline groups; set ENTRA_OVERAGE_MAPPED_GROUP to a group the overage user belongs to")
    with httpx.Client(headers=admin_headers(), timeout=30) as client:
        team_id = seed_team(client, "Entra Live Overage Team", "Live Entra overage graph_lookup e2e")
        seed_provider(
            client,
            PROVIDER_ID,
            info["issuer"],
            info["audience"],
            token_url=f"https://login.microsoftonline.com/{info['tenant_id']}/oauth2/v2.0/token",
            client_id=graph_client_id,
            client_secret=graph_client_secret,
        )
        seed_agent(client, "Entra-Live-Overage-Agent", team_id, local_oidc_issuer.stub_agent_url_for_gateway, "Live Entra overage agent")
        mapping_id = seed_mapping(client, info["issuer"], info["tenant_id"], overage_group, team_id, "developer")
    try:
        message = "Hello from live Entra overage graph_lookup e2e"
        response = _invoke("Entra-Live-Overage-Agent", token, message)
        assert response.status_code == 200, f"UC4 expected 200, got {response.status_code}: {response.text[:200]}"
        artifacts = response.json()["result"]["artifacts"]
        echoed = artifacts[0]["parts"][0]["text"] if artifacts and artifacts[0].get("parts") else ""
        assert message in echoed, f"UC4 echo round-trip failed: {echoed[:200]}"
    finally:
        with httpx.Client(headers=admin_headers(), timeout=30) as client:
            client.delete(f"{BASE_URL}/admin/external-group-mappings/{mapping_id}")
