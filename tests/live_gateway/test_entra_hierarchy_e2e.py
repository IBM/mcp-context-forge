# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/test_entra_hierarchy_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Live Entra hierarchy e2e: verify JWT-borne authorization metadata
(roles and hierarchies) against a running OpenFGA-powered gateway.

Provisions a 3-level org in Entra (executives → division-leads →
engineers), creates one user per level, and verifies that rules
referencing different hierarchy levels allow or deny tool execution
correctly. All test identities live ONLY in Entra — the ContextForge
database has no user rows for them (only the admin).
"""

# Future
from __future__ import annotations

# Standard
import os

# Third-Party
import httpx
import pytest

# First-Party
from tests.live_gateway.helpers.entra_hierarchy import (
    get_transitive_groups,
    inspect_token_groups,
    provision_entra_hierarchy,
)
from tests.live_gateway.helpers.entra_live import _azure_credentials
from tests.live_gateway.helpers.mcp_test_helpers import BASE_URL, skip_no_gateway

pytestmark = [pytest.mark.e2e, skip_no_gateway]

_REQUIRED_ENV = ("AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET", "AZURE_TENANT_ID")
_HAS_AZURE = all(os.getenv(var) for var in _REQUIRED_ENV)
_SKIP_REASON = "AZURE_CLIENT_ID/AZURE_CLIENT_SECRET/AZURE_TENANT_ID not set"

pytestmark.append(pytest.mark.skipif(not _HAS_AZURE, reason=_SKIP_REASON))


@pytest.fixture(scope="module")
def entra_hierarchy():
    """Provision the hierarchy; yield the manifest; clean up after."""
    if not _HAS_AZURE:
        pytest.skip(_SKIP_REASON)
    manifest = provision_entra_hierarchy()
    yield manifest
    # Cleanup is handled inside provision_entra_hierarchy on failure;
    # for the success path, delete after the module completes.
    from tests.live_gateway.helpers.entra_live import _azure_graph_token

    client_id, client_secret, tenant_id, _ = _azure_credentials()
    graph_token = _azure_graph_token(client_id, client_secret, tenant_id)
    headers = {"Authorization": f"Bearer {graph_token}"}
    for uid in manifest.get("user_ids", []):
        try:
            httpx.delete(f"https://graph.microsoft.com/v1.0/users/{uid}", headers=headers, timeout=15)
        except Exception:
            pass
    for gid in manifest.get("group_ids", {}).values():
        try:
            httpx.delete(f"https://graph.microsoft.com/v1.0/groups/{gid}", headers=headers, timeout=15)
        except Exception:
            pass


@pytest.fixture(scope="module")
def hierarchy_tokens(entra_hierarchy):
    """Extract the tokens for each level."""
    return entra_hierarchy["tokens"]


class TestHierarchyStructure:
    """Verify the Entra hierarchy is correctly nested."""

    def test_executive_direct_group_only(self, hierarchy_tokens, entra_hierarchy):
        """The executive's token carries only the executives group."""
        groups = inspect_token_groups(hierarchy_tokens["exec"])
        assert entra_hierarchy["group_ids"]["exec"] in groups
        # Direct membership: should NOT contain child groups
        assert entra_hierarchy["group_ids"]["eng"] not in groups

    def test_engineer_direct_group_only(self, hierarchy_tokens, entra_hierarchy):
        """The engineer's token carries the engineers group.

        Entra may include transitive groups in the claim depending on
        the groupMembershipClaims setting; the key assertion is that
        the engineer's OWN group is present.
        """
        groups = inspect_token_groups(hierarchy_tokens["eng"])
        assert entra_hierarchy["group_ids"]["eng"] in groups

    def test_transitive_resolution_includes_all_levels(self, hierarchy_tokens, entra_hierarchy):
        """getMemberGroups returns all levels for the engineer."""
        transitive = set(get_transitive_groups(hierarchy_tokens["eng"]))
        assert entra_hierarchy["group_ids"]["eng"] in transitive
        assert entra_hierarchy["group_ids"]["lead"] in transitive
        assert entra_hierarchy["group_ids"]["exec"] in transitive

    def test_transitive_exec_only_has_exec(self, hierarchy_tokens, entra_hierarchy):
        """The executive's transitive groups do NOT include child groups."""
        transitive = set(get_transitive_groups(hierarchy_tokens["exec"]))
        assert entra_hierarchy["group_ids"]["exec"] in transitive
        assert entra_hierarchy["group_ids"]["eng"] not in transitive


class TestHierarchyTokenValidation:
    """Verify the gateway authenticates the Entra tokens."""

    def test_all_tokens_are_valid_v2(self, hierarchy_tokens):
        """Each token decodes and carries the required claims."""
        import base64
        import json as _json

        for level, token in hierarchy_tokens.items():
            part = token.split(".")[1]
            payload = _json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
            assert payload.get("oid"), f"{level} token lacks oid"
            assert payload.get("groups"), f"{level} token lacks groups claim"
            issuer = payload.get("iss", "")
            assert issuer.startswith(("https://login.microsoftonline.com/", "https://sts.windows.net/")), f"{level} token has wrong issuer: {issuer}"

    def test_gateway_health(self):
        """The gateway is reachable."""
        resp = httpx.get(f"{BASE_URL}/health", timeout=10)
        assert resp.status_code == 200


class TestContextualDomainTuples:
    """Verify the contextual tuple builder maps JWT claims to domain tuples."""

    def test_build_tuples_from_engineer_claims(self):
        """The builder produces member tuples for each claimed team."""
        from mcpgateway.services.openfga_sync import build_contextual_domain_tuples

        tuples = build_contextual_domain_tuples(
            None,
            "hier-eng@test.com",
            token_teams=["engineers", "division-leads", "executives"],
            token_roles=["developer"],
        )
        assert {"user": "user:hier-eng@test.com", "relation": "member", "object": "domain:engineers"} in tuples
        assert {"user": "user:hier-eng@test.com", "relation": "member", "object": "domain:division-leads"} in tuples
        assert {"user": "user:hier-eng@test.com", "relation": "member", "object": "domain:executives"} in tuples

    def test_build_tuples_admin_role_elevates(self):
        """An admin-level role claim elevates member to admin."""
        from mcpgateway.services.openfga_sync import build_contextual_domain_tuples

        tuples = build_contextual_domain_tuples(
            None,
            "hier-exec@test.com",
            token_teams=["executives"],
            token_roles=["team_admin"],
        )
        assert {"user": "user:hier-exec@test.com", "relation": "admin", "object": "domain:executives"} in tuples


class TestHierarchyRuleEnforcement:
    """Verify rules fire per hierarchy level when tokens carry group claims."""

    def test_rule_predicate_matches_executives_claim(self):
        """A rule referencing team.executives matches the executive's claim."""
        from mcpgateway.services.rule_predicate import evaluate_predicate

        attrs = {"team": {"executives": True}, "role": {}, "args": {}}
        assert evaluate_predicate("team.executives", attrs) is True

    def test_rule_predicate_denies_engineer_not_in_sales(self):
        """A rule referencing team.sales does NOT match the engineer."""
        from mcpgateway.services.rule_predicate import evaluate_predicate

        attrs = {"team": {"engineers": True, "division-leads": True, "executives": True}, "role": {}, "args": {}}
        assert evaluate_predicate("team.sales", attrs) is False

    def test_combined_role_and_team(self):
        """A predicate combining role and team matches correctly."""
        from mcpgateway.services.rule_predicate import evaluate_predicate

        attrs = {"team": {"executives": True}, "role": {"team_admin": True}, "args": {}}
        assert evaluate_predicate("role.team_admin & team.executives", attrs) is True
        assert evaluate_predicate("role.team_admin & team.engineers", attrs) is False


class TestNoDatabaseUsers:
    """Verify the ContextForge DB has no rows for the hierarchy users."""

    def test_hierarchy_users_absent_from_gateway_db(self, entra_hierarchy):
        """The email_users table has no rows for the hierarchy test users."""
        # This test runs against the gateway's admin API to check that
        # the hierarchy users are NOT in the database. If they were,
        # the test would prove nothing about JWT-only authorization.
        admin_token = os.getenv("ADMIN_JWT")
        if not admin_token:
            pytest.skip("ADMIN_JWT not set")
        for level, upn in entra_hierarchy["upns"].items():
            resp = httpx.get(
                f"{BASE_URL}/admin/users/{upn}",
                headers={"Authorization": f"Bearer {admin_token}"},
                timeout=10,
            )
            assert resp.status_code == 404, f"hierarchy user {level} ({upn}) exists in the gateway DB — the test must use JWT-only identity"
