# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/e2e/test_server_association_visibility_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box checks that a virtual server can attach only visible tools, resources and prompts (#7684).

Every account, team, role and API token is created through the HTTP API of a private
gateway subprocess (see ``isolated_gateway``). No Docker stack is required.
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
from tests.helpers.auth import make_auth_headers
from tests.live_gateway.e2e.test_candidate_credential_handshake import _GatewayFixture, isolated_gateway  # noqa: F401  pylint: disable=unused-import
from tests.live_gateway.e2e.test_server_create_nested_team_override import _World, _api, _grant, _login, _mint_api_token, world  # noqa: F401,F811  pylint: disable=unused-import

pytestmark = pytest.mark.e2e

_PERMISSIONS = [f"{kind}.{action}" for kind in ("servers", "tools", "resources", "prompts") for action in ("create", "read", "update")]


@pytest.fixture
def tenants(world: _World):  # noqa: F811
    """Give Bob update permission and mint Alice a public-only token."""
    _grant(world.admin, world.bob, _PERMISSIONS, team_id=world.team_b)
    world.bob_client.close()
    world.bob_client = _mint_api_token(world.base_url, world.bob, world.team_b, _PERMISSIONS)
    role = _api(world.admin, "POST", "/rbac/roles", json={"name": f"global-assoc-{uuid.uuid4().hex[:8]}", "scope": "global", "permissions": _PERMISSIONS})
    _api(world.admin, "POST", f"/rbac/users/{world.alice}/roles", json={"role_id": role["id"], "scope": "global", "scope_id": None})
    with httpx.Client(base_url=world.base_url, headers=make_auth_headers(_login(world.base_url, world.alice)), timeout=30, trust_env=False) as session:
        created = _api(session, "POST", "/tokens", expected=(201,), json={"name": f"public-only-{uuid.uuid4().hex[:6]}", "expires_in_days": 1, "scope": {"permissions": _PERMISSIONS}})
    world.alice_public_only = httpx.Client(base_url=world.base_url, headers=make_auth_headers(created["access_token"]), timeout=30, trust_env=False)
    try:
        yield world
    finally:
        world.alice_public_only.close()


def _ids_key(kind: str) -> str:
    """Return the ServerRead JSON field that lists associated IDs."""
    return {"tools": "associatedToolIds", "resources": "associatedResources", "prompts": "associatedPrompts"}[kind]


def _create_item(client: httpx.Client, kind: str, *, visibility: str, team_id: str, name: str | None = None) -> str:
    """Create a tool, resource or prompt and return its ID."""
    suffix = uuid.uuid4().hex[:8]
    label = name or f"{kind}-{visibility}-{suffix}"
    scope = {"team_id": team_id, "visibility": visibility}
    if kind == "tools":
        inner: dict[str, Any] = {
            "name": label,
            "url": "https://example.com/api",
            "integration_type": "REST",
            "request_type": "GET",
            "input_schema": {"type": "object", "properties": {}},
            **scope,
        }
        body: dict[str, Any] = {"tool": inner, **scope}
        path = "/tools"
    elif kind == "resources":
        body = {"resource": {"name": label, "uri": f"file:///{label}.txt", "content": "x", **scope}, **scope}
        path = "/resources"
    else:
        body = {"prompt": {"name": label, "template": "hello", "arguments": [], **scope}, **scope}
        path = "/prompts"
    created = _api(client, "POST", path, expected=(200, 201), json=body)
    assert created.get("visibility") == visibility, created
    return created["id"]


def _assoc_field(kind: str) -> str:
    """Return the server payload field for an association type."""
    return {"tools": "associated_tools", "resources": "associated_resources", "prompts": "associated_prompts"}[kind]


def _create_server(client: httpx.Client, *, team_id: str, visibility: str = "team", **associations: Any) -> dict[str, Any]:
    """Create a virtual server and return the response body."""
    name = f"srv-{uuid.uuid4().hex[:8]}"
    payload: dict[str, Any] = {"server": {"name": name, **associations}, "team_id": team_id, "visibility": visibility}
    return _api(client, "POST", "/servers", expected=(200, 201), json=payload)


@pytest.mark.parametrize("kind", ("tools", "resources", "prompts"))
def test_item_from_another_team_is_rejected(tenants: _World, kind: str) -> None:
    """Bob cannot attach Alice's team-visible item to a new or existing server."""
    item_id = _create_item(tenants.alice_client, kind, visibility="team", team_id=tenants.team_a)
    field = _assoc_field(kind)

    denied = tenants.bob_client.post("/servers", json={"server": {"name": f"denied-{uuid.uuid4().hex[:8]}", field: [item_id]}, "team_id": tenants.team_b, "visibility": "team"})
    assert denied.status_code == 400, denied.text
    assert "do not exist" in denied.text

    bobs_server = _create_server(tenants.bob_client, team_id=tenants.team_b)
    denied_put = tenants.bob_client.put(f"/servers/{bobs_server['id']}", json={field: [item_id]})
    assert denied_put.status_code == 400, denied_put.text
    assert "do not exist" in denied_put.text
    listed = _api(tenants.admin, "GET", f"/servers/{bobs_server['id']}")
    stored_ids = listed.get(_ids_key(kind))
    assert item_id not in (stored_ids or [])


@pytest.mark.parametrize("kind", ("tools", "resources", "prompts"))
def test_private_item_of_another_user_is_rejected(tenants: _World, kind: str) -> None:
    """Bob cannot attach Alice's private item."""
    item_id = _create_item(tenants.alice_client, kind, visibility="private", team_id=tenants.team_a)
    field = _assoc_field(kind)

    denied = tenants.bob_client.post("/servers", json={"server": {"name": f"denied-{uuid.uuid4().hex[:8]}", field: [item_id]}, "team_id": tenants.team_b, "visibility": "team"})
    assert denied.status_code == 400, denied.text
    assert "do not exist" in denied.text


@pytest.mark.parametrize("kind", ("tools", "resources", "prompts"))
def test_unknown_and_invisible_ids_return_the_same_error(tenants: _World, kind: str) -> None:
    """A missing ID and an invisible ID produce the same not-found error."""
    hidden_id = _create_item(tenants.alice_client, kind, visibility="private", team_id=tenants.team_a)
    unknown_id = uuid.uuid4().hex
    field = _assoc_field(kind)

    missing = tenants.bob_client.post("/servers", json={"server": {"name": f"missing-{uuid.uuid4().hex[:8]}", field: [unknown_id]}, "team_id": tenants.team_b, "visibility": "team"})
    invisible = tenants.bob_client.post("/servers", json={"server": {"name": f"hidden-{uuid.uuid4().hex[:8]}", field: [hidden_id]}, "team_id": tenants.team_b, "visibility": "team"})
    assert missing.status_code == 400, missing.text
    assert invisible.status_code == 400, invisible.text
    missing_ids = missing.json().get("detail") or missing.json().get("message") or missing.text
    invisible_ids = invisible.json().get("detail") or invisible.json().get("message") or invisible.text
    assert "do not exist" in str(missing_ids)

    def _mask(message: str, item_id: str) -> str:
        """Ignore hyphenated vs hex typography when comparing not-found errors."""
        masked = message
        variants = {item_id, item_id.replace("-", "")}
        try:
            variants.add(str(uuid.UUID(item_id)))
            variants.add(uuid.UUID(item_id).hex)
        except ValueError:
            pass
        for form in variants:
            masked = masked.replace(form, "ID")
        return masked

    assert _mask(str(missing_ids), unknown_id) == _mask(str(invisible_ids), hidden_id)


@pytest.mark.parametrize("kind", ("tools", "resources", "prompts"))
def test_public_only_token_cannot_attach_a_team_item(tenants: _World, kind: str) -> None:
    """A public-only token cannot attach a team-visible item, even the owner's."""
    item_id = _create_item(tenants.alice_client, kind, visibility="team", team_id=tenants.team_a)
    field = _assoc_field(kind)
    denied = tenants.alice_public_only.post("/servers", json={"server": {"name": f"public-only-{uuid.uuid4().hex[:8]}", field: [item_id]}, "visibility": "public"})
    assert denied.status_code == 400, denied.text
    assert "do not exist" in denied.text


@pytest.mark.parametrize("kind", ("tools", "resources", "prompts"))
def test_owner_can_attach_and_resubmit_an_existing_association(tenants: _World, kind: str) -> None:
    """The owner can attach their team item, and a later PUT that repeats the ID stays allowed."""
    item_id = _create_item(tenants.alice_client, kind, visibility="team", team_id=tenants.team_a)
    field = _assoc_field(kind)

    created = _create_server(tenants.alice_client, team_id=tenants.team_a, **{field: [item_id]})
    ids_key = _ids_key(kind)
    assert item_id in created[ids_key]

    updated = _api(tenants.alice_client, "PUT", f"/servers/{created['id']}", json={field: created[ids_key]})
    assert item_id in updated[ids_key]
