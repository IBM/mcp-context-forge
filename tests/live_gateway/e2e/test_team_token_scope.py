# -*- coding: utf-8 -*-
# Copyright contributors to the MCP-CONTEXT-FORGE project
# SPDX-License-Identifier: Apache-2.0
"""Location: ./tests/live_gateway/e2e/test_team_token_scope.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Exercise team management scope through a disposable live gateway.
"""

# Standard
import secrets
from typing import Any
import uuid

# Third-Party
import httpx
import jwt
import pytest

# Local
from tests.helpers.auth import make_auth_headers, make_test_jwt
from tests.live_gateway.e2e.test_candidate_credential_handshake import _GatewayFixture, isolated_gateway  # noqa: F401  pylint: disable=unused-import

pytestmark = pytest.mark.e2e


def _json(client: httpx.Client, method: str, path: str, **kwargs: Any) -> Any:
    """Return successful JSON without exposing credentials on failure."""
    response = client.request(method, path, **kwargs)
    assert response.status_code in (200, 201), f"{method} {path}: {response.status_code}"
    return response.json()


def _denied(response: httpx.Response, sensitive: tuple[str, ...]) -> None:
    """Check denial status and exclude sensitive fixture data."""
    assert response.status_code == 403
    for value in sensitive:
        assert value not in response.text


@pytest.mark.parametrize(
    "isolated_gateway",
    [
        {"MCPGATEWAY_UI_ENABLED": "true", "AUTH_CACHE_ENABLED": "false"},
        {"MCPGATEWAY_UI_ENABLED": "true", "AUTH_CACHE_ENABLED": "false", "APP_ROOT_PATH": "/gateway"},
    ],
    indirect=True,
)
def test_team_scope_live(isolated_gateway: _GatewayFixture) -> None:  # noqa: F811  pylint: disable=redefined-outer-name
    """Cross-team tokens cannot read private data or persist member changes."""
    admin, _, base_url, signing_key = isolated_gateway
    suffix = uuid.uuid4().hex[:10]
    owner = f"scope-owner-{suffix}@example.com"
    outsider = f"scope-outsider-{suffix}@example.com"
    invitee = f"scope-invitee-{suffix}@example.com"
    team_ids = []
    role_ids = []
    try:
        for email in (owner, outsider):
            _json(
                admin,
                "POST",
                "/auth/email/admin/users",
                json={
                    "email": email,
                    "password": secrets.token_urlsafe(24) + "Aa1!",
                    "full_name": "Scope Regression",
                    "is_admin": False,
                    "is_active": True,
                    "password_change_required": False,
                },
            )
        for label in ("a", "b"):
            team = _json(admin, "POST", "/teams/", json={"name": f"scope-{label}-{suffix}", "visibility": "private"})
            team_ids.append(team["id"])
            _json(admin, "POST", f"/teams/{team['id']}/members", json={"email": owner, "role": "owner"})
        a, b = team_ids
        roles = _json(admin, "GET", "/rbac/roles")
        viewer = next(role["id"] for role in roles if role["name"] == "platform_viewer")
        assignments = _json(admin, "GET", f"/rbac/users/{owner}/roles")
        if not any(item["role_id"] == viewer for item in assignments):
            _json(admin, "POST", f"/rbac/users/{owner}/roles", json={"role_id": viewer, "scope": "global"})
        role = _json(
            admin,
            "POST",
            "/rbac/roles",
            json={
                "name": f"scope-manager-{suffix}",
                "scope": "global",
                "permissions": ["teams.manage_members", "teams.update", "teams.delete", "teams.join"],
            },
        )
        role_ids.append(role["id"])
        _json(admin, "POST", f"/rbac/users/{owner}/roles", json={"role_id": role["id"], "scope": "global"})
        session = make_test_jwt(owner, teams=[a, b], token_use="session", secret=signing_key, algorithm="HS256", include_email_claim=True)
        public = make_test_jwt(owner, teams=[], secret=signing_key, algorithm="HS256", include_email_claim=True)
        assert jwt.decode(public, signing_key, algorithms=["HS256"], options={"verify_aud": False})["teams"] == []
        with httpx.Client(base_url=base_url, headers=make_auth_headers(session), trust_env=False, timeout=20) as owner_client:
            tokens = []
            for team_id in (a, b):
                token = _json(owner_client, "POST", "/tokens", json={"name": f"scope-{team_id}-{suffix}", "team_id": team_id, "expires_in_days": 1})
                tokens.append(token["access_token"])
            invitation = _json(owner_client, "POST", f"/teams/{b}/invitations", json={"email": invitee, "role": "member"})
            invitation_id = invitation["id"]
            sensitive = (owner, invitee, invitation["token"])
            for prefix in ("/teams", "/v1/teams"):
                for credential in (tokens[0], public):
                    headers = make_auth_headers(credential)
                    for endpoint in (f"{prefix}/{b}", f"{prefix}/{b}/members", f"{prefix}/{b}/invitations"):
                        _denied(owner_client.get(endpoint, headers=headers), sensitive)
                    _denied(owner_client.post(f"{prefix}/{b}/members", headers=headers, json={"email": outsider, "role": "owner"}), sensitive)
                for endpoint in (f"{prefix}/{b}", f"{prefix}/{b}/members", f"{prefix}/{b}/invitations"):
                    assert owner_client.get(endpoint, headers=make_auth_headers(tokens[1])).status_code == 200
                collection = _json(owner_client, "GET", f"{prefix}/", headers=make_auth_headers(tokens[0]))
                assert [team["id"] for team in collection["teams"]] == [a]
                assert _json(owner_client, "GET", f"{prefix}/", headers=make_auth_headers(public))["teams"] == []
            narrowed_session = make_test_jwt(owner, teams=[a], token_use="session", secret=signing_key, algorithm="HS256")
            _denied(owner_client.get(f"/teams/{b}", headers=make_auth_headers(narrowed_session)), sensitive)
            scoped_admin = make_test_jwt("admin@example.com", is_admin=True, teams=[a], secret=signing_key, algorithm="HS256")
            _denied(owner_client.get(f"/teams/{b}", headers=make_auth_headers(scoped_admin)), sensitive)
            nonmember = make_test_jwt(outsider, teams=[b], secret=signing_key, algorithm="HS256", include_email_claim=True)
            _denied(owner_client.get(f"/teams/{b}", headers=make_auth_headers(nonmember)), sensitive)
            headers = make_auth_headers(tokens[0])
            operations: list[tuple[str, str, dict[str, Any]]] = [
                ("PUT", f"/teams/{b}", {"json": {"name": "Unauthorized change"}}),
                ("DELETE", f"/teams/{b}", {}),
                ("PUT", f"/teams/{b}/members/{owner}", {"json": {"role": "member"}}),
                ("DELETE", f"/teams/{b}/members/{owner}", {}),
                ("POST", f"/teams/{b}/invitations", {"json": {"email": outsider, "role": "owner"}}),
                ("DELETE", f"/teams/invitations/{invitation_id}", {}),
                ("DELETE", f"/teams/{b}/leave", {}),
                ("GET", f"/teams/{b}/join-requests", {}),
                ("POST", f"/teams/{b}/join-requests/missing/approve", {}),
                ("DELETE", f"/teams/{b}/join-requests/missing", {}),
                ("GET", f"/admin/teams/{b}/members", {}),
                ("POST", f"/admin/teams/{b}/add-member", {"data": {"user_email": outsider, "role": "owner"}}),
            ]
            for method, path, kwargs in operations:
                _denied(owner_client.request(method, path, headers=headers, **kwargs), sensitive)
            assert owner_client.get(f"/admin/teams/{b}/members", headers=make_auth_headers(tokens[1])).status_code == 200
            for credential in (
                make_test_jwt(owner, teams=[b], token_use="session", secret=signing_key, algorithm="HS256"),
                make_test_jwt(owner, token_use="session", secret=signing_key, algorithm="HS256"),
            ):
                assert owner_client.get(f"/teams/{b}", headers=make_auth_headers(credential)).status_code == 200
            explicit = _json(
                owner_client,
                "POST",
                "/tokens",
                json={
                    "name": f"explicit-{suffix}",
                    "expires_in_days": 1,
                    "team_id": b,
                    "scope": {"permissions": ["teams.read"]},
                },
            )
            _denied(owner_client.get(f"/teams/{b}", headers=make_auth_headers(explicit["access_token"])), sensitive)
            assert httpx.get(f"{base_url}/teams/{b}", trust_env=False).status_code == 401
            members = _json(admin, "GET", f"/teams/{b}/members")
            assert outsider not in {member["user_email"] for member in members}
            assert next(member["role"] for member in members if member["user_email"] == owner) == "owner"
            remaining = _json(owner_client, "GET", f"/teams/{b}/invitations", headers=make_auth_headers(tokens[1]))
            assert [item["id"] for item in remaining] == [invitation_id]
            assert _json(admin, "GET", f"/teams/{b}")["name"] == f"scope-b-{suffix}"
            added = _json(owner_client, "POST", f"/teams/{b}/members", headers=make_auth_headers(tokens[1]), json={"email": outsider, "role": "member"})
            assert added["role"] == "member"
            _denied(owner_client.get(f"/teams/{b}/invitations", headers=make_auth_headers(nonmember)), sensitive)
            changed = owner_client.post(f"/admin/teams/{b}/add-member", headers=make_auth_headers(tokens[1]), data={"user_email": outsider, "role": "owner"})
            assert changed.status_code == 200
            members = _json(admin, "GET", f"/teams/{b}/members")
            assert next(member["role"] for member in members if member["user_email"] == outsider) == "owner"
    finally:
        for team_id in reversed(team_ids):
            admin.delete(f"/teams/{team_id}")
        for role_id in role_ids:
            admin.delete(f"/rbac/roles/{role_id}")
        for email in (outsider, owner):
            admin.delete(f"/auth/email/admin/users/{email}")


@pytest.mark.parametrize(
    "isolated_gateway",
    [
        {
            "MCP_CLIENT_AUTH_ENABLED": "false",
            "TRUST_PROXY_AUTH": "true",
            "TRUST_PROXY_AUTH_DANGEROUSLY": "true",
            "PROXY_USER_HEADER": "X-Authenticated-User",
            "AUTH_CACHE_ENABLED": "false",
        }
    ],
    indirect=True,
)
def test_proxy_team_scope_live(isolated_gateway: _GatewayFixture) -> None:  # noqa: F811  pylint: disable=redefined-outer-name
    """Verified proxy identity keeps local membership despite conflicting signed JWTs."""
    admin, _, base_url, signing_key = isolated_gateway
    admin.headers["X-Authenticated-User"] = "admin@example.com"
    suffix = uuid.uuid4().hex[:10]
    owner = f"proxy-owner-{suffix}@example.com"
    team_ids = []
    try:
        _json(
            admin,
            "POST",
            "/auth/email/admin/users",
            json={
                "email": owner,
                "password": secrets.token_urlsafe(24) + "Aa1!",
                "full_name": "Proxy Scope",
                "is_admin": False,
                "is_active": True,
                "password_change_required": False,
            },
        )
        for label in ("a", "b"):
            team_ids.append(_json(admin, "POST", "/teams/", json={"name": f"proxy-{label}-{suffix}", "visibility": "private"})["id"])
        a, b = team_ids
        _json(admin, "POST", f"/teams/{a}/members", json={"email": owner, "role": "owner"})
        claim_cases: list[dict[str, Any]] = [{"teams": []}, {"teams": [b]}, {"teams": None, "is_admin": True}]
        for claims in claim_cases:
            conflicting = make_test_jwt("admin@example.com", secret=signing_key, algorithm="HS256", **claims)
            headers = make_auth_headers(conflicting, extra_headers={"X-Authenticated-User": owner, "Cookie": f"jwt_token={conflicting}"})
            with httpx.Client(base_url=base_url, headers=headers, trust_env=False, timeout=20) as client:
                assert client.get(f"/teams/{a}").status_code == 200
                _denied(client.get(f"/teams/{b}"), (owner,))
                _denied(client.get(f"/teams/{b}", headers={"X-Authenticated-User": f"unknown-{suffix}@example.com"}), (owner,))
        conflicting = make_test_jwt(owner, teams=[a], secret=signing_key, algorithm="HS256")
        assert admin.get(f"/teams/{b}", headers=make_auth_headers(conflicting)).status_code == 200
    finally:
        for team_id in reversed(team_ids):
            admin.delete(f"/teams/{team_id}")
        admin.delete(f"/auth/email/admin/users/{owner}")
