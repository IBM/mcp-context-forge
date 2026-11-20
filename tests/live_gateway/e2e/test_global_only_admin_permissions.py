# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/e2e/test_global_only_admin_permissions.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Live-gateway black-box tests for global-only administration permissions.

``admin.user_management``, ``admin.security_audit`` and ``admin.sso_providers:*`` administer
users, roles and identity providers across every team. A team-scoped grant of these permissions
must not satisfy any route. A global grant keeps working.

Every account, team, role and grant is created through the HTTP API of a private gateway
subprocess (see ``isolated_gateway``). No Docker stack is required.
"""

# Future
from __future__ import annotations

# Standard
from typing import Any
import uuid

# Third-Party
import httpx
import pytest

# Local
from tests.helpers.auth import make_auth_headers, make_test_jwt
from tests.live_gateway.e2e.test_candidate_credential_handshake import _GatewayFixture, isolated_gateway  # noqa: F401  pylint: disable=unused-import

pytestmark = pytest.mark.e2e

_PASSWORD = "E2eGlobalOnly!42"  # pragma: allowlist secret
_ADMIN_EMAIL = "admin@example.com"


def _api(client: httpx.Client, method: str, path: str, *, expected: tuple[int, ...] = (200, 201), **kwargs: Any) -> Any:
    """Send an API request, assert its status and return the JSON body."""
    response = client.request(method, path, **kwargs)
    assert response.status_code in expected, f"{method} {path} returned {response.status_code}: {response.text[:500]}"
    return response.json() if response.content else None


class _Actor:
    """A non-admin team member, the admin client and the ``platform_admin`` role ID."""

    def __init__(self, gateway: _GatewayFixture) -> None:
        """Create a shared team with one non-admin member."""
        self.admin, _token, self.base_url, self.key = gateway
        self.team_id = _api(self.admin, "POST", "/teams/", json={"name": f"global-only-{uuid.uuid4().hex[:8]}", "visibility": "private"})["id"]
        self.email = f"global-only-{uuid.uuid4().hex[:8]}@example.com"
        _api(
            self.admin,
            "POST",
            "/auth/email/admin/users",
            expected=(201,),
            json={"email": self.email, "password": _PASSWORD, "full_name": "actor", "is_admin": False, "is_active": True, "password_change_required": False},
        )
        _api(self.admin, "POST", f"/teams/{self.team_id}/members", json={"email": self.email, "role": "member"})
        roles = _api(self.admin, "GET", "/rbac/roles")
        self.platform_admin_role_id = next(role["id"] for role in roles if role["name"] == "platform_admin")

    def grant(self, permissions: list[str], *, scope: str) -> None:
        """Create a role holding ``permissions`` and grant it to the actor at ``scope``."""
        scope_id = self.team_id if scope == "team" else None
        role = _api(self.admin, "POST", "/rbac/roles", json={"name": f"global-only-role-{uuid.uuid4().hex[:8]}", "scope": scope, "permissions": permissions})
        _api(self.admin, "POST", f"/rbac/users/{self.email}/roles", json={"role_id": role["id"], "scope": scope, "scope_id": scope_id})

    def client(self) -> httpx.Client:
        """Return a client authenticated as the actor and narrowed to the actor's team."""
        token = make_test_jwt(self.email, teams=[self.team_id], secret=self.key, algorithm="HS256", include_email_claim=True)
        return httpx.Client(base_url=self.base_url, headers=make_auth_headers(token), timeout=30, trust_env=False)


def test_team_scoped_user_management_cannot_assign_global_role(isolated_gateway: _GatewayFixture) -> None:  # noqa: F811  pylint: disable=redefined-outer-name
    """A team-scoped ``admin.user_management`` grant cannot assign a global role."""
    actor = _Actor(isolated_gateway)
    actor.grant(["admin.user_management"], scope="team")
    with actor.client() as client:
        _api(client, "POST", f"/rbac/users/{actor.email}/roles", expected=(403,), json={"role_id": actor.platform_admin_role_id, "scope": "global"})
    assigned = _api(actor.admin, "GET", f"/rbac/users/{actor.email}/roles")
    assert all(role["role_id"] != actor.platform_admin_role_id for role in assigned)


def test_team_scoped_user_management_cannot_set_is_admin(isolated_gateway: _GatewayFixture) -> None:  # noqa: F811  pylint: disable=redefined-outer-name
    """A team-scoped ``admin.user_management`` grant cannot set ``is_admin`` on a user."""
    actor = _Actor(isolated_gateway)
    actor.grant(["admin.user_management"], scope="team")
    with actor.client() as client:
        _api(client, "PATCH", f"/auth/email/admin/users/{actor.email}", expected=(403,), json={"is_admin": True})
    assert _api(actor.admin, "GET", f"/auth/email/admin/users/{actor.email}")["is_admin"] is False


def test_team_scoped_security_audit_cannot_read_other_users_permissions(isolated_gateway: _GatewayFixture) -> None:  # noqa: F811  pylint: disable=redefined-outer-name
    """A team-scoped ``admin.security_audit`` grant cannot read another user's permissions."""
    actor = _Actor(isolated_gateway)
    actor.grant(["admin.security_audit"], scope="team")
    with actor.client() as client:
        _api(client, "GET", f"/rbac/permissions/user/{_ADMIN_EMAIL}", expected=(403,))


def test_global_user_management_grant_still_works(isolated_gateway: _GatewayFixture) -> None:  # noqa: F811  pylint: disable=redefined-outer-name
    """A global ``admin.user_management`` grant keeps access to user administration."""
    actor = _Actor(isolated_gateway)
    actor.grant(["admin.user_management"], scope="global")
    with actor.client() as client:
        _api(client, "GET", f"/rbac/users/{actor.email}/roles")


@pytest.mark.parametrize("isolated_gateway", [{"SSO_ENABLED": "true"}], indirect=True)
def test_team_scoped_sso_provider_grant_cannot_create_provider(isolated_gateway: _GatewayFixture) -> None:  # noqa: F811  pylint: disable=redefined-outer-name
    """A team-scoped ``admin.sso_providers:create`` grant cannot register an identity provider."""
    actor = _Actor(isolated_gateway)
    actor.grant(["admin.sso_providers:create"], scope="team")
    provider_id = f"globalonly{uuid.uuid4().hex[:8]}"
    provider = {
        "id": provider_id,
        "name": provider_id,
        "display_name": "Global only check",
        "provider_type": "oidc",
        "client_id": "client",
        "client_secret": "client-secret",  # pragma: allowlist secret
        "authorization_url": "https://idp.example.com/authorize",
        "token_url": "https://idp.example.com/token",
        "userinfo_url": "https://idp.example.com/userinfo",
        "issuer": "https://idp.example.com",
    }
    with actor.client() as client:
        _api(client, "POST", "/auth/sso/admin/providers", expected=(403,), json=provider)
    assert all(existing["id"] != provider_id for existing in _api(actor.admin, "GET", "/auth/sso/admin/providers"))
