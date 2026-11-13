"""Black-box deny paths for the team-visibility authorization gate.

A virtual-server row may carry ``visibility="team"`` only when the requester is
a platform admin or an active ``owner``-role member of the target team. This
suite runs the policy through the real HTTP surface against a live gateway.
"""

from typing import Any
import uuid

# Third-Party
import httpx
import pytest

# Local
from tests.helpers.auth import make_auth_headers
from tests.live_gateway.e2e.test_candidate_credential_handshake import _GatewayFixture, isolated_gateway  # noqa: F401  pylint: disable=unused-import

pytestmark = pytest.mark.e2e

_PASSWORD = "E2eTeamVis!42"  # pragma: allowlist secret
_PERMISSIONS = ["servers.create", "servers.read", "servers.update"]


def _api(client: httpx.Client, method: str, path: str, *, expected: tuple[int, ...] = (200, 201), **kwargs: Any) -> Any:
    """Send an API request, assert its status and return the JSON body."""
    response = client.request(method, path, **kwargs)
    assert response.status_code in expected, f"{method} {path} returned {response.status_code}: {response.text[:500]}"
    return response.json() if response.content else None


def _grant(admin: httpx.Client, email: str, permissions: list[str], *, team_id: str) -> None:
    """Create a team-scoped role holding ``permissions`` and grant it to ``email``."""
    role = _api(admin, "POST", "/rbac/roles", json={"name": f"vis-role-{uuid.uuid4().hex[:8]}", "scope": "team", "permissions": permissions})
    _api(admin, "POST", f"/rbac/users/{email}/roles", json={"role_id": role["id"], "scope": "team", "scope_id": team_id})


def _login(base_url: str, email: str) -> str:
    """Log in with email and password and return the session JWT."""
    with httpx.Client(base_url=base_url, timeout=30, trust_env=False) as anon:
        return _api(anon, "POST", "/auth/email/login", json={"email": email, "password": _PASSWORD})["access_token"]


def _mint_api_token(base_url: str, email: str, team_id: str, permissions: list[str]) -> httpx.Client:
    """Return a client that authenticates with a product-issued API token scoped to ``team_id``."""
    with httpx.Client(base_url=base_url, headers=make_auth_headers(_login(base_url, email)), timeout=30, trust_env=False) as session:
        created = _api(session, "POST", "/tokens", json={"name": f"vis-{uuid.uuid4().hex[:6]}", "team_id": team_id, "expires_in_days": 1, "scope": {"permissions": permissions}})
    return httpx.Client(base_url=base_url, headers=make_auth_headers(created["access_token"]), timeout=30, trust_env=False)


class _World:
    """Team A with an owner-role member and a member-role member, plus Team B.

    Both members hold the same RBAC create/update permissions in Team A and
    differ only in team role, so denials prove the owner-role gate and not a
    missing permission.
    """

    def __init__(self, gateway: _GatewayFixture) -> None:
        """Provision the tenants and users through the admin API."""
        self.admin, _token, self.base_url, self.signing_key = gateway
        suffix = uuid.uuid4().hex[:8]
        self.team_a = _api(self.admin, "POST", "/teams/", json={"name": f"vis-team-a-{suffix}", "visibility": "private"})["id"]
        self.team_b = _api(self.admin, "POST", "/teams/", json={"name": f"vis-team-b-{suffix}", "visibility": "private"})["id"]
        self.owner = f"vis-owner-{suffix}@example.com"
        self.member = f"vis-member-{suffix}@example.com"
        for email in (self.owner, self.member):
            _api(
                self.admin,
                "POST",
                "/auth/email/admin/users",
                expected=(201,),
                json={"email": email, "password": _PASSWORD, "full_name": email.split("@")[0], "is_admin": False, "is_active": True, "password_change_required": False},
            )
        _api(self.admin, "POST", f"/teams/{self.team_a}/members", json={"email": self.owner, "role": "owner"})
        _api(self.admin, "POST", f"/teams/{self.team_a}/members", json={"email": self.member, "role": "member"})
        _grant(self.admin, self.owner, _PERMISSIONS, team_id=self.team_a)
        _grant(self.admin, self.member, _PERMISSIONS, team_id=self.team_a)
        self.owner_client = _mint_api_token(self.base_url, self.owner, self.team_a, _PERMISSIONS)
        self.member_client = _mint_api_token(self.base_url, self.member, self.team_a, _PERMISSIONS)

    def close(self) -> None:
        """Close the token clients."""
        self.owner_client.close()
        self.member_client.close()

    def admin_view(self, server_id: str) -> dict[str, Any]:
        """Return the stored server as the platform admin sees it."""
        return _api(self.admin, "GET", f"/v1/servers/{server_id}")

    def owner_view(self, server_id: str) -> dict[str, Any]:
        """Return the stored server as its owner sees it.

        Private rows stay invisible to the platform admin (PR #4341), so the
        owner witnesses rows that remain ``visibility="private"``.
        """
        return _api(self.owner_client, "GET", f"/v1/servers/{server_id}")

    def member_view(self, server_id: str) -> dict[str, Any]:
        """Return the stored server as the member-role caller sees it.

        Token scoping shows a private row only to its own owner, so a row the
        member created is witnessed through the member's client.
        """
        return _api(self.member_client, "GET", f"/v1/servers/{server_id}")


@pytest.fixture
def world(isolated_gateway: _GatewayFixture) -> Any:  # noqa: F811  pylint: disable=redefined-outer-name
    """Provision the world and tear down its clients."""
    built = _World(isolated_gateway)
    yield built
    built.close()


def _create_private(world: _World, client: httpx.Client, name: str) -> str:
    """Create a private server in Team A and return its id."""
    body = {"server": {"name": name}, "team_id": world.team_a, "visibility": "private"}
    return _api(client, "POST", "/v1/servers", expected=(201,), json=body)["id"]


def test_owner_can_set_team_visibility(world: _World) -> None:
    """An active owner-role member can switch their own row to team visibility."""
    name = f"vis-owner-ok-{uuid.uuid4().hex[:6]}"
    server_id = _create_private(world, world.owner_client, name)
    _api(world.owner_client, "PUT", f"/v1/servers/{server_id}", json={"visibility": "team", "team_id": world.team_a, "name": name})
    stored = world.admin_view(server_id)
    assert stored["visibility"] == "team"
    assert stored["teamId"] == world.team_a


def test_member_without_owner_role_cannot_set_team_visibility(world: _World) -> None:
    """A member-role caller gets 403 and the row keeps its stored visibility."""
    name = f"vis-member-deny-{uuid.uuid4().hex[:6]}"
    server_id = _create_private(world, world.member_client, name)
    response = world.member_client.put(f"/v1/servers/{server_id}", json={"visibility": "team", "team_id": world.team_a, "name": name})
    assert response.status_code == 403, response.text[:500]
    assert "membership in team not sufficient" in response.text
    stored = world.member_view(server_id)
    assert stored["visibility"] == "private"
    assert stored["teamId"] == world.team_a


def test_member_can_save_unchanged_team_visibility(world: _World) -> None:
    """A member-not-owner saves a team-visibility row unchanged and keeps the team."""
    name = f"vis-member-keep-{uuid.uuid4().hex[:6]}"
    server_id = _create_private(world, world.member_client, name)
    _api(world.admin, "PUT", f"/v1/servers/{server_id}", json={"visibility": "team", "team_id": world.team_a, "name": name})
    renamed = f"{name}-v2"
    _api(world.member_client, "PUT", f"/v1/servers/{server_id}", json={"visibility": "team", "name": renamed})
    stored = world.member_view(server_id)
    assert stored["visibility"] == "team"
    assert stored["teamId"] == world.team_a
    assert stored["name"] == renamed


def test_owner_cannot_set_team_visibility_for_foreign_team(world: _World) -> None:
    """An owner-role member of Team A cannot point team visibility at Team B."""
    name = f"vis-foreign-deny-{uuid.uuid4().hex[:6]}"
    server_id = _create_private(world, world.owner_client, name)
    response = world.owner_client.put(f"/v1/servers/{server_id}", json={"visibility": "team", "team_id": world.team_b, "name": name})
    assert response.status_code == 403, response.text[:500]
    stored = world.owner_view(server_id)
    assert stored["visibility"] == "private"
    assert stored["teamId"] == world.team_a


def test_admin_bypass_sets_team_visibility(world: _World) -> None:
    """A platform admin can set team visibility without a membership row."""
    name = f"vis-admin-ok-{uuid.uuid4().hex[:6]}"
    server_id = _create_private(world, world.owner_client, name)
    _api(world.admin, "PUT", f"/v1/servers/{server_id}", json={"visibility": "team", "team_id": world.team_a, "name": name})
    stored = world.admin_view(server_id)
    assert stored["visibility"] == "team"
    assert stored["teamId"] == world.team_a


def test_unauthenticated_update_is_rejected(world: _World) -> None:
    """An unauthenticated PUT gets 401 and the row keeps its stored visibility."""
    name = f"vis-anon-deny-{uuid.uuid4().hex[:6]}"
    server_id = _create_private(world, world.owner_client, name)
    with httpx.Client(base_url=world.base_url, timeout=30, trust_env=False) as anon:
        response = anon.put(f"/v1/servers/{server_id}", json={"visibility": "team", "team_id": world.team_a, "name": name})
    assert response.status_code == 401, response.text[:500]
    stored = world.owner_view(server_id)
    assert stored["visibility"] == "private"


def test_create_team_visibility_requires_owner_role(world: _World) -> None:
    """The create gate admits owner-role members and rejects member-role callers."""
    denied_name = f"vis-create-deny-{uuid.uuid4().hex[:6]}"
    response = world.member_client.post("/v1/servers", json={"server": {"name": denied_name}, "team_id": world.team_a, "visibility": "team"})
    assert response.status_code == 403, response.text[:500]
    names = [s["name"] for s in _api(world.admin, "GET", "/v1/servers", params={"include_inactive": True, "limit": 0})]
    assert denied_name not in names

    allowed_name = f"vis-create-ok-{uuid.uuid4().hex[:6]}"
    created = _api(world.owner_client, "POST", "/v1/servers", expected=(201,), json={"server": {"name": allowed_name}, "team_id": world.team_a, "visibility": "team"})
    stored = world.admin_view(created["id"])
    assert stored["visibility"] == "team"
    assert stored["teamId"] == world.team_a


def test_create_team_visibility_without_team_id_is_rejected(world: _World) -> None:
    """A team-visible create with no resolvable team_id fails validation with 400."""
    name = f"vis-create-noteam-{uuid.uuid4().hex[:6]}"
    response = world.admin.post("/v1/servers", json={"server": {"name": name}, "visibility": "team"})
    assert response.status_code == 400, response.text[:500]
    assert "Cannot set visibility to 'team' without a team_id" in response.text
    names = [s["name"] for s in _api(world.admin, "GET", "/v1/servers", params={"include_inactive": True, "limit": 0})]
    assert name not in names
