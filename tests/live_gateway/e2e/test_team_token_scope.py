# -*- coding: utf-8 -*-
# Copyright contributors to the MCP-CONTEXT-FORGE project
# SPDX-License-Identifier: Apache-2.0
"""Location: ./tests/live_gateway/e2e/test_team_token_scope.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Exercise team management scope through a disposable live gateway.
"""

# Standard
from collections.abc import Iterator
import hashlib
import json
from typing import Any
import uuid

# Third-Party
import httpx
import jwt
import pytest

# Local
from tests.helpers.auth import make_auth_headers, make_test_jwt, make_test_password
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
    if any(value in response.text for value in sensitive):
        raise AssertionError("Denied response contains fixture data")


def _state_digest(value: Any) -> str:
    """Compare persisted state without printing invitation material on failure."""
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


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
                    "password": make_test_password(),
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
            invitation_state = _state_digest(_json(owner_client, "GET", f"/teams/{b}/invitations", headers=make_auth_headers(tokens[1])))
            narrowed_session = make_test_jwt(owner, teams=[a], token_use="session", secret=signing_key, algorithm="HS256")
            scoped_admin = make_test_jwt("admin@example.com", is_admin=True, teams=[a], secret=signing_key, algorithm="HS256")
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
                for credential in (tokens[0], public, narrowed_session, scoped_admin):
                    responses = [owner_client.delete(f"{prefix}/invitations/{identifier}", headers=make_auth_headers(credential)) for identifier in (invitation_id, uuid.uuid4().hex)]
                    assert [response.status_code for response in responses] == [404, 404]
                    assert responses[0].content == responses[1].content
                    assert all(value not in response.text for response in responses for value in sensitive)
            _denied(owner_client.get(f"/teams/{b}", headers=make_auth_headers(narrowed_session)), sensitive)
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
            assert _state_digest(remaining) == invitation_state
            assert owner_client.delete(f"/teams/invitations/{invitation_id}", headers=make_auth_headers(tokens[1])).status_code == 200
            assert _json(owner_client, "GET", f"/teams/{b}/invitations", headers=make_auth_headers(tokens[1])) == []
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
    role_id = None
    try:
        _json(
            admin,
            "POST",
            "/auth/email/admin/users",
            json={
                "email": owner,
                "password": make_test_password(),
                "full_name": "Proxy Scope",
                "is_admin": False,
                "is_active": True,
                "password_change_required": False,
            },
        )
        role_id = _json(admin, "POST", "/rbac/roles", json={"name": f"proxy-inviter-{suffix}", "scope": "global", "permissions": ["teams.manage_members"]})["id"]
        _json(admin, "POST", f"/rbac/users/{owner}/roles", json={"role_id": role_id, "scope": "global"})
        for label in ("a", "b"):
            team_ids.append(_json(admin, "POST", "/teams/", json={"name": f"proxy-{label}-{suffix}", "visibility": "private"})["id"])
        a, b = team_ids
        _json(admin, "POST", f"/teams/{a}/members", json={"email": owner, "role": "owner"})
        invitations = [_json(admin, "POST", f"/teams/{team_id}/invitations", json={"email": f"proxy-invite-{team_id}@example.com", "role": "member"}) for team_id in (a, b)]
        claim_cases: list[dict[str, Any]] = [{"teams": []}, {"teams": [b]}, {"teams": None, "is_admin": True}]
        for claims in claim_cases:
            conflicting = make_test_jwt("admin@example.com", secret=signing_key, algorithm="HS256", **claims)
            headers = make_auth_headers(conflicting, extra_headers={"X-Authenticated-User": owner, "Cookie": f"jwt_token={conflicting}"})
            with httpx.Client(base_url=base_url, headers=headers, trust_env=False, timeout=20) as client:
                assert client.get(f"/teams/{a}").status_code == 200
                ui_status = 403 if claims["teams"] == [] else 200
                assert client.get(f"/v1/admin/teams/{a}/edit").status_code == ui_status
                _denied(client.get(f"/v1/admin/teams/{b}/edit"), (owner,))
                if ui_status == 200:
                    ids = _json(client, "GET", "/v1/admin/teams/ids")
                    assert a in ids["team_ids"] and b not in ids["team_ids"]
                _denied(client.get(f"/teams/{b}"), (owner,))
                responses = [client.delete(f"/teams/invitations/{identifier}") for identifier in (invitations[1]["id"], uuid.uuid4().hex)]
                assert [response.status_code for response in responses] == [404, 404]
                assert responses[0].content == responses[1].content
                assert all(invitations[1]["token"] not in response.text for response in responses)
                _denied(client.get(f"/teams/{b}", headers={"X-Authenticated-User": f"unknown-{suffix}@example.com"}), (owner,))
        assert [item["id"] for item in _json(admin, "GET", f"/teams/{b}/invitations")] == [invitations[1]["id"]]
        with httpx.Client(base_url=base_url, headers={"X-Authenticated-User": owner}, trust_env=False, timeout=20) as proxy_client:
            assert proxy_client.get(f"/v1/admin/teams/{a}/edit").status_code == 200
            assert proxy_client.get(f"/v1/admin/teams/{a}/members/partial").status_code == 200
            _denied(proxy_client.get(f"/v1/admin/teams/{b}/edit"), (owner,))
            ids = _json(proxy_client, "GET", "/v1/admin/teams/ids")
            assert a in ids["team_ids"] and b not in ids["team_ids"]
            assert proxy_client.delete(f"/teams/invitations/{invitations[0]['id']}").status_code == 200
        conflicting = make_test_jwt(owner, teams=[a], secret=signing_key, algorithm="HS256")
        assert admin.get(f"/teams/{b}", headers=make_auth_headers(conflicting)).status_code == 200
        assert admin.delete(f"/teams/invitations/{invitations[1]['id']}", headers=make_auth_headers(conflicting)).status_code == 200
    finally:
        for team_id in reversed(team_ids):
            admin.delete(f"/teams/{team_id}")
        if role_id is not None:
            admin.delete(f"/rbac/roles/{role_id}")
        admin.delete(f"/auth/email/admin/users/{owner}")


@pytest.fixture
def ui_scope(isolated_gateway: _GatewayFixture) -> Iterator[dict[str, Any]]:  # noqa: F811  pylint: disable=redefined-outer-name
    """Provision private teams and real API tokens for the expanded UI boundary."""
    from contextlib import suppress

    admin, _, base_url, signing_key = isolated_gateway
    suffix = uuid.uuid4().hex[:10]
    users = {name: f"ui-{name}-{suffix}@example.com" for name in ("owner", "member", "target", "approve", "reject", "cancel")}
    teams: list[str] = []
    roles: list[str] = []
    tokens: list[str] = []
    with httpx.Client(base_url=base_url, trust_env=False, timeout=30, follow_redirects=False) as client:

        def request(credential: str | None, method: str, path: str, **kwargs: Any) -> httpx.Response:
            headers = make_auth_headers(credential) if credential else {}
            headers.update(kwargs.pop("headers", {}))
            return client.request(method, path, headers=headers, **kwargs)

        def json_request(credential: str, method: str, path: str, **kwargs: Any) -> Any:
            response = request(credential, method, path, **kwargs)
            assert response.status_code in (200, 201), f"{method} {path}: {response.status_code}"
            return response.json()

        def signed(name: str, **claims: Any) -> str:
            return make_test_jwt(users.get(name, name), secret=signing_key, algorithm="HS256", include_email_claim=True, **claims)

        def create_team(label: str) -> str:
            team = _json(admin, "POST", "/teams/", json={"name": f"ui-{label}-{suffix}", "description": f"private-{label}-{suffix}", "visibility": "private"})
            teams.append(team["id"])
            return str(team["id"])

        def add(team_id: str, name: str, role: str) -> Any:
            return _json(admin, "POST", f"/teams/{team_id}/members", json={"email": users[name], "role": role})

        def mint(name: str, team_id: str, scope: dict[str, Any] | None = None) -> str:
            credential = isolated_gateway[1] if name == "admin" else signed(name, token_use="session")
            payload: dict[str, Any] = {"name": f"ui-token-{uuid.uuid4().hex[:10]}", "team_id": team_id, "expires_in_days": 1}
            if scope is not None:
                payload["scope"] = scope
            result = json_request(credential, "POST", "/tokens", json=payload)
            tokens.append(result["token"]["id"])
            return str(result["access_token"])

        try:
            for email in users.values():
                _json(
                    admin,
                    "POST",
                    "/auth/email/admin/users",
                    json={
                        "email": email,
                        "password": make_test_password(),
                        "full_name": "UI Scope Fixture",
                        "is_admin": False,
                        "is_active": True,
                        "password_change_required": False,
                    },
                )
            manager = _json(
                admin,
                "POST",
                "/rbac/roles",
                json={
                    "name": f"ui-manager-{suffix}",
                    "scope": "global",
                    "permissions": ["teams.read", "teams.update", "teams.delete", "teams.manage_members", "teams.join"],
                },
            )["id"]
            roles.append(manager)
            for name in ("owner", "member"):
                _json(admin, "POST", f"/rbac/users/{users[name]}/roles", json={"role_id": manager, "scope": "global"})
            a, b = create_team("a"), create_team("b")
            add(a, "owner", "owner")
            add(b, "owner", "owner")
            add(b, "member", "member")
            add(b, "target", "member")
            add(a, "cancel", "member")
            ta, tb, tm, tc = mint("owner", a), mint("owner", b), mint("member", b), mint("cancel", a)
            _json(admin, "PUT", f"/teams/{b}", json={"visibility": "public"})
            pending = {
                name: json_request(signed(name, token_use="session"), "POST", f"/teams/{b}/join", json={"message": f"private-request-{name}-{suffix}"})["id"]
                for name in ("approve", "reject", "cancel")
            }
            _json(admin, "PUT", f"/teams/{b}", json={"visibility": "private"})
            invitation = json_request(tb, "POST", f"/teams/{b}/invitations", json={"email": f"ui-invitee-{suffix}@example.com", "role": "member"})
            yield {
                "admin": admin,
                "request": request,
                "json": json_request,
                "signed": signed,
                "mint": mint,
                "create_team": create_team,
                "add": add,
                "users": users,
                "a": a,
                "b": b,
                "ta": ta,
                "tb": tb,
                "tm": tm,
                "tc": tc,
                "pending": pending,
                "sensitive": (*users.values(), invitation["email"], invitation["token"], f"private-b-{suffix}"),
            }
        finally:
            for token_id in tokens:
                with suppress(Exception):
                    admin.delete(f"/tokens/admin/{token_id}")
            for team_id in reversed(teams):
                with suppress(Exception):
                    admin.delete(f"/teams/{team_id}")
            for role_id in roles:
                with suppress(Exception):
                    admin.delete(f"/rbac/roles/{role_id}")


@pytest.mark.parametrize(
    "isolated_gateway",
    [
        {"MCPGATEWAY_UI_ENABLED": "true", "AUTH_CACHE_ENABLED": "false"},
        {"MCPGATEWAY_UI_ENABLED": "true", "AUTH_CACHE_ENABLED": "false", "APP_ROOT_PATH": "/gateway"},
    ],
    indirect=True,
)
def test_expanded_admin_team_authorization_live(ui_scope: dict[str, Any]) -> None:
    """All audited UI gaps reject foreign scope and preserve permitted controls."""
    import re

    u = ui_scope
    admin, request, data, signed = u["admin"], u["request"], u["json"], u["signed"]
    a, b, ta, tb, tm = u["a"], u["b"], u["ta"], u["tb"], u["tm"]
    users, pending, sensitive = u["users"], u["pending"], u["sensitive"]

    def snapshot() -> str:
        responses = [_json(admin, "GET", f"/teams/{b}{tail}") for tail in ("", "/members", "/invitations", "/join-requests")]
        return _state_digest(responses)

    before = snapshot()
    invitation_id = _json(admin, "GET", f"/teams/{b}/invitations")[0]["id"]
    for prefix in ("/teams", "/v1/teams"):
        for credential, status in ((None, 401), (signed("target", token_use="session"), 403)):
            response = request(credential, "DELETE", f"{prefix}/invitations/{invitation_id}")
            assert response.status_code == status
            assert all(value not in response.text for value in sensitive)
    for prefix in ("/admin", "/v1/admin"):
        operations = [
            ("GET", f"{prefix}/teams/{b}/members/add", {}),
            ("GET", f"{prefix}/teams/{b}/edit", {}),
            ("POST", f"{prefix}/teams/{b}/update", {"data": {"name": "Unauthorized", "visibility": "public"}}),
            ("DELETE", f"{prefix}/teams/{b}", {}),
            ("POST", f"{prefix}/teams/{b}/update-member-role", {"data": {"user_email": users["target"], "role": "owner"}}),
            ("POST", f"{prefix}/teams/{b}/remove-member", {"data": {"user_email": users["target"]}}),
            ("POST", f"{prefix}/teams/{b}/leave", {}),
            ("GET", f"{prefix}/teams/{b}/join-requests", {}),
            ("POST", f"{prefix}/teams/{b}/join-requests/{pending['approve']}/approve", {}),
            ("POST", f"{prefix}/teams/{b}/join-requests/{pending['reject']}/reject", {}),
            ("GET", f"{prefix}/teams/{b}/members/partial", {}),
            ("GET", f"{prefix}/teams/{b}/non-members/partial", {"params": {"search": "ui-cancel"}}),
        ]
        for method, path, kwargs in operations:
            _denied(request(ta, method, path, headers={"HX-Request": "true"}, **kwargs), sensitive)
            assert request(None, method, path, **kwargs).status_code == 401
            _denied(request(signed("owner", teams=[]), method, path, **kwargs), sensitive)
        for tail in ("members/add", "edit", "members/partial", "non-members/partial", "join-requests"):
            assert request(tb, "GET", f"{prefix}/teams/{b}/{tail}").status_code == 200
        for token in (ta, u["mint"]("admin", a)):
            result = data(token, "GET", f"{prefix}/teams/ids")
            assert result == {"team_ids": [a], "count": 1}
            result = data(token, "GET", f"{prefix}/teams/ids", params={"q": "no-such-team"})
            assert result == {"team_ids": [], "count": 0}
        scoped_admin = u["mint"]("admin", a)
        _denied(request(scoped_admin, "GET", f"{prefix}/users/partial", params={"render": "selector", "team_id": b}), sensitive)
        for params in ({"render": "selector"}, {"render": "selector", "team_id": a}):
            assert request(scoped_admin, "GET", f"{prefix}/users/partial", params=params).status_code == 200
        allowed_admin = u["mint"]("admin", b)
        selector = request(allowed_admin, "GET", f"{prefix}/users/partial", params={"render": "selector", "team_id": b, "per_page": 50})
        assert selector.status_code == 200
        assert re.search(r'data-user-email="' + re.escape(users["owner"]) + r'"\s+data-is-member="true"', selector.text)
        for action in ("approve", "reject"):
            response = request(ta, "POST", f"{prefix}/teams/{a}/join-requests/{pending[action]}/{action}")
            assert response.status_code == 404
        for tail in ("edit", "update", ""):
            method = "GET" if tail == "edit" else "POST" if tail else "DELETE"
            kwargs = {"data": {"name": "Non-owner", "visibility": "private"}} if tail == "update" else {}
            _denied(request(tm, method, f"{prefix}/teams/{b}" + (f"/{tail}" if tail else ""), **kwargs), sensitive)
    assert snapshot() == before
    explicit = u["mint"]("owner", a, {"permissions": ["teams.update"]})
    _denied(request(explicit, "GET", f"/v1/admin/teams/{b}/edit"), sensitive)
    _denied(request(signed("owner", token_use="session", teams=[a]), "GET", f"/v1/admin/teams/{b}/edit"), sensitive)
    assert request(signed("owner", token_use="session"), "GET", f"/v1/admin/teams/{b}/edit").status_code == 200
    _denied(request(signed("target", token_use="session"), "GET", f"/v1/admin/teams/{b}/edit"), sensitive)
    for path in (f"/v1/admin/teams/{a}/join-request/{pending['cancel']}", f"/v1/admin/teams/{'f' * 32}/join-request/{pending['cancel']}"):
        assert request(u["tc"], "DELETE", path).status_code == 404
    assert request(ta, "DELETE", f"/v1/admin/teams/{b}/join-request/{pending['cancel']}").status_code == 404
    assert snapshot() == before
    assert request(u["tc"], "DELETE", f"/v1/admin/teams/{b}/join-request/{pending['cancel']}").status_code == 200
    assert pending["cancel"] not in {r["id"] for r in _json(admin, "GET", f"/teams/{b}/join-requests")}

    # Permitted controls follow the unchanged-state assertions.
    b_name = _json(admin, "GET", f"/teams/{b}")["name"]
    assert request(tb, "POST", f"/v1/admin/teams/{b}/update", data={"name": b_name, "description": "Owner update", "visibility": "private"}, headers={"HX-Request": "true"}).status_code == 200
    assert _json(admin, "GET", f"/teams/{b}")["description"] == "Owner update"
    assert request(tb, "POST", f"/v1/admin/teams/{b}/update-member-role", data={"user_email": users["target"], "role": "owner"}).status_code == 200
    assert next(m["role"] for m in _json(admin, "GET", f"/teams/{b}/members") if m["user_email"] == users["target"]) == "owner"
    assert request(tb, "POST", f"/v1/admin/teams/{b}/remove-member", data={"user_email": users["target"]}).status_code == 200
    assert users["target"] not in {m["user_email"] for m in _json(admin, "GET", f"/teams/{b}/members")}
    for action in ("approve", "reject"):
        assert request(tb, "POST", f"/v1/admin/teams/{b}/join-requests/{pending[action]}/{action}").status_code == 200
    assert users["approve"] in {m["user_email"] for m in _json(admin, "GET", f"/teams/{b}/members")}
    assert _json(admin, "GET", f"/teams/{b}/join-requests") == []
    assert request(tb, "POST", f"/v1/admin/teams/{b}/leave").status_code == 200
    assert users["owner"] not in {m["user_email"] for m in _json(admin, "GET", f"/teams/{b}/members")}
    c = u["create_team"]("delete-control")
    u["add"](c, "owner", "owner")
    token_c = u["mint"]("owner", c)
    assert request(token_c, "DELETE", f"/v1/admin/teams/{c}").status_code == 200
    assert admin.get(f"/teams/{c}").status_code == 404
