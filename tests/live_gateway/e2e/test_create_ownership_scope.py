# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/e2e/test_create_ownership_scope.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Live-gateway black-box tests for team and owner assignment on the create routes.

The create routes for servers, resources, prompts and tools accept ``team_id``,
``owner_email`` and ``visibility`` both at the top level of the body and nested in the
payload. The tests prove that a caller creates only in a team its token is scoped to and
holds the create permission in, that the stored owner is always the caller, and that a
public-only token never assigns a team or a non-public visibility.

Every account, team, role, grant and token is created through the HTTP API of a private
gateway subprocess (see ``isolated_gateway``). Personal teams are off, so a user in two
teams receives a public-only API token. No Docker stack is required.
"""

# Future
from __future__ import annotations

# Standard
from typing import Any

# Third-Party
import httpx
import pytest

# Local
from tests.helpers.auth import make_auth_headers
from tests.live_gateway.e2e.test_candidate_credential_handshake import _GatewayFixture, isolated_gateway  # noqa: F401  pylint: disable=unused-import

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.parametrize("isolated_gateway", [{"AUTO_CREATE_PERSONAL_TEAMS": "false"}], ids=["no-personal-teams"], indirect=True),
]

_PASSWORD = "E2eCreateOwner!42"  # pragma: allowlist secret
_ALICE = "alice@example.com"
_OTHER = "other@example.com"
_CAROL = "carol@example.com"
_DAVE = "dave@example.com"

KINDS = ("servers", "resources", "prompts", "tools")
_PAYLOAD_KEY = {"servers": "server", "resources": "resource", "prompts": "prompt", "tools": "tool"}
_CREATE_PERMISSIONS = [f"{kind}.create" for kind in KINDS]
_READ_PERMISSIONS = [f"{kind}.read" for kind in KINDS]


def _setup(client: httpx.Client, method: str, path: str, step: str, *, expected: tuple[int, ...] = (200, 201), **kwargs: Any) -> Any:
    """Send a setup request and return its JSON body.

    Raises:
        RuntimeError: If the response status is not in ``expected``.
    """
    response = client.request(method, path, **kwargs)
    if response.status_code not in expected:
        raise RuntimeError(f"setup: {step} {response.status_code} {response.text[:300]}")
    return response.json() if response.content else None


def _minimal_body(kind: str, name: str) -> dict[str, Any]:
    """Return the smallest valid create payload for ``kind``."""
    if kind == "servers":
        return {"name": name}
    if kind == "resources":
        return {"uri": f"docs/{name}", "name": name, "content": "text"}
    if kind == "prompts":
        return {"name": name, "template": "Hello"}
    return {"name": name, "url": "https://example.com/api", "integration_type": "REST", "request_type": "GET"}


def _stored_value(row: dict[str, Any], snake: str, camel: str) -> Any:
    """Read a field that the API may serialize in snake or camel case."""
    return row.get(camel, row.get(snake))


class _Tenants:
    """Two teams, four users and their tokens on one gateway."""

    def __init__(self, gateway: _GatewayFixture) -> None:
        """Create the teams, users, roles, grants and tokens through the API."""
        self.admin, _token, self.base_url, _key = gateway
        self.team_a = _setup(self.admin, "POST", "/teams/", "team-a", json={"name": "team-a", "visibility": "private"})["id"]
        self.team_other = _setup(self.admin, "POST", "/teams/", "team-other", json={"name": "team-other", "visibility": "private"})["id"]

        memberships = {_ALICE: [self.team_a], _OTHER: [self.team_other], _CAROL: [self.team_a, self.team_other], _DAVE: [self.team_a]}
        for email, teams in memberships.items():
            _setup(
                self.admin,
                "POST",
                "/auth/email/admin/users",
                f"user {email}",
                expected=(201,),
                json={"email": email, "password": _PASSWORD, "full_name": email.split("@")[0], "is_admin": False, "is_active": True, "password_change_required": False},
            )
            for team_id in teams:
                _setup(self.admin, "POST", f"/teams/{team_id}/members", f"member {email}", json={"email": email, "role": "member"})

        creator = _setup(self.admin, "POST", "/rbac/roles", "role creator", json={"name": "creator", "scope": "team", "permissions": _CREATE_PERMISSIONS + _READ_PERMISSIONS})
        _setup(self.admin, "POST", f"/rbac/users/{_ALICE}/roles", "grant creator", json={"role_id": creator["id"], "scope": "team", "scope_id": self.team_a})
        global_creator = _setup(self.admin, "POST", "/rbac/roles", "role global-creator", json={"name": "global-creator", "scope": "global", "permissions": _CREATE_PERMISSIONS})
        for email in (_CAROL, _DAVE):
            _setup(self.admin, "POST", f"/rbac/users/{email}/roles", f"grant global-creator {email}", json={"role_id": global_creator["id"], "scope": "global", "scope_id": None})

        self.alice_session = self._login(_ALICE)
        self.alice_api = self._api_token(self.alice_session, "alice-team-a", team_id=self.team_a)["access_token"]
        self.other_session = self._login(_OTHER)
        self.dave_session = self._login(_DAVE)
        carol_token = self._api_token(self._login(_CAROL), "carol-no-team")
        if not carol_token.get("warnings"):
            raise RuntimeError("setup: carol public-only token has no warnings")
        self.carol_api = carol_token["access_token"]

    def _login(self, email: str) -> str:
        """Log in as ``email`` and return the session token."""
        with httpx.Client(base_url=self.base_url, timeout=30, trust_env=False) as anonymous:
            return _setup(anonymous, "POST", "/auth/email/login", f"login {email}", json={"email": email, "password": _PASSWORD})["access_token"]

    def _api_token(self, session: str, name: str, team_id: str | None = None) -> dict[str, Any]:
        """Create an API token with the caller's session and return the response body."""
        body: dict[str, Any] = {"name": name, "expires_in_days": 1}
        if team_id:
            body["team_id"] = team_id
        with self._client(session) as client:
            return _setup(client, "POST", "/tokens", f"token {name}", expected=(201,), json=body)

    def _client(self, token: str) -> httpx.Client:
        """Return a client authenticated with ``token``."""
        return httpx.Client(base_url=self.base_url, headers=make_auth_headers(token), timeout=30, trust_env=False)

    def create(self, token: str, kind: str, name: str, *, nested: dict[str, Any] | None = None, team_id: str | None = None) -> httpx.Response:
        """POST a create request for ``kind`` with optional nested fields and a top-level team."""
        body: dict[str, Any] = {_PAYLOAD_KEY[kind]: {**_minimal_body(kind, name), **(nested or {})}}
        if team_id:
            body["team_id"] = team_id
        with self._client(token) as client:
            return client.post(f"/v1/{kind}", json=body)

    def stored(self, kind: str, name: str) -> list[dict[str, Any]]:
        """Return every row of ``kind`` named ``name`` as the platform admin sees it."""
        rows = self.admin.get(f"/v1/{kind}", params={"include_inactive": "true", "limit": 0})
        rows.raise_for_status()
        return [row for row in rows.json() if row.get("name") == name]

    def assert_denied(self, response: httpx.Response, kind: str, name: str) -> None:
        """Assert a 403 and that no row named ``name`` exists."""
        assert response.status_code == 403, f"{kind}: expected 403, got {response.status_code}: {response.text[:300]}"
        assert not self.stored(kind, name), f"{kind}: a row was created despite the 403"

    def assert_created(self, response: httpx.Response, kind: str, name: str) -> dict[str, Any]:
        """Assert a successful create and return the single stored row."""
        assert response.status_code in (200, 201), f"{kind}: expected success, got {response.status_code}: {response.text[:300]}"
        rows = self.stored(kind, name)
        assert len(rows) == 1, f"{kind}: expected one stored row, found {len(rows)}"
        return rows[0]


@pytest.fixture
def tenants(isolated_gateway: _GatewayFixture) -> _Tenants:  # noqa: F811  pylint: disable=redefined-outer-name
    """Build the tenant layout on a fresh gateway."""
    return _Tenants(isolated_gateway)


def test_api_token_nested_foreign_team_is_denied(tenants: _Tenants) -> None:  # pylint: disable=redefined-outer-name
    """A team-scoped API token cannot place a record in another team through the nested field."""
    for kind in KINDS:
        name = f"{kind}-api-nested-other"
        tenants.assert_denied(tenants.create(tenants.alice_api, kind, name, nested={"team_id": tenants.team_other}), kind, name)


def test_session_token_top_level_own_nested_foreign_is_denied(tenants: _Tenants) -> None:  # pylint: disable=redefined-outer-name
    """A nested team that differs from the top-level team is refused."""
    for kind in KINDS:
        name = f"{kind}-session-split-team"
        response = tenants.create(tenants.alice_session, kind, name, team_id=tenants.team_a, nested={"team_id": tenants.team_other})
        tenants.assert_denied(response, kind, name)


def test_global_role_session_foreign_team_is_denied(tenants: _Tenants) -> None:  # pylint: disable=redefined-outer-name
    """A global create role does not allow creating in a team the caller is not a member of."""
    for kind in KINDS:
        nested_name = f"{kind}-global-nested-other"
        tenants.assert_denied(tenants.create(tenants.dave_session, kind, nested_name, nested={"team_id": tenants.team_other}), kind, nested_name)
        top_name = f"{kind}-global-top-other"
        tenants.assert_denied(tenants.create(tenants.dave_session, kind, top_name, team_id=tenants.team_other), kind, top_name)


def test_viewer_session_cannot_create_in_team(tenants: _Tenants) -> None:  # pylint: disable=redefined-outer-name
    """A team member without a create permission cannot create in its own team."""
    for kind in KINDS:
        name = f"{kind}-viewer-own-team"
        tenants.assert_denied(tenants.create(tenants.other_session, kind, name, nested={"team_id": tenants.team_other}), kind, name)


def test_nested_owner_email_is_ignored(tenants: _Tenants) -> None:  # pylint: disable=redefined-outer-name
    """The stored owner is the caller, never the nested ``owner_email``."""
    for kind in KINDS:
        name = f"{kind}-nested-owner"
        row = tenants.assert_created(tenants.create(tenants.alice_api, kind, name, nested={"owner_email": _OTHER}), kind, name)
        assert _stored_value(row, "owner_email", "ownerEmail") == _ALICE, f"{kind}: owner_email is {_stored_value(row, 'owner_email', 'ownerEmail')}"
        assert _stored_value(row, "team_id", "teamId") == tenants.team_a, f"{kind}: team_id is {_stored_value(row, 'team_id', 'teamId')}"


def test_session_token_nested_own_team_is_kept(tenants: _Tenants) -> None:  # pylint: disable=redefined-outer-name
    """A nested team the caller may create in is honoured when no top-level team is sent."""
    for kind in KINDS:
        name = f"{kind}-session-nested-own"
        row = tenants.assert_created(tenants.create(tenants.alice_session, kind, name, nested={"team_id": tenants.team_a}), kind, name)
        assert _stored_value(row, "team_id", "teamId") == tenants.team_a, f"{kind}: team_id is {_stored_value(row, 'team_id', 'teamId')}"


def test_public_only_token_nested_team_visibility_is_denied(tenants: _Tenants) -> None:  # pylint: disable=redefined-outer-name
    """A public-only token cannot create a team-visible record through the nested fields."""
    for kind in KINDS:
        name = f"{kind}-public-only-team"
        response = tenants.create(tenants.carol_api, kind, name, nested={"team_id": tenants.team_other, "visibility": "team"})
        tenants.assert_denied(response, kind, name)


def test_public_only_token_cannot_assign_team(tenants: _Tenants) -> None:  # pylint: disable=redefined-outer-name
    """A public-only token creates a public record with no team, whatever the nested team says."""
    for kind in KINDS:
        name = f"{kind}-public-only-public"
        row = tenants.assert_created(tenants.create(tenants.carol_api, kind, name, nested={"team_id": tenants.team_other, "visibility": "public"}), kind, name)
        assert _stored_value(row, "team_id", "teamId") is None, f"{kind}: team_id is {_stored_value(row, 'team_id', 'teamId')}"
        assert _stored_value(row, "owner_email", "ownerEmail") == _CAROL, f"{kind}: owner_email is {_stored_value(row, 'owner_email', 'ownerEmail')}"
