# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/e2e/test_export_selective_collision.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Live-gateway black-box tests for identifier collisions on POST /v1/export/selective.

Two tenants each own a private prompt with the same name and a private resource with the same URI.
The reader holds ``admin.export``. The tests prove that a selective export by the shared name or URI
returns only the reader's records, and that selecting the other tenant's record by ID returns nothing.

Every account, team, role, grant, prompt and resource is created through the HTTP API of a private
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
from tests.helpers.auth import make_auth_headers, make_test_jwt
from tests.live_gateway.e2e.test_candidate_credential_handshake import _GatewayFixture, isolated_gateway  # noqa: F401  pylint: disable=unused-import

pytestmark = pytest.mark.e2e

_PASSWORD = "E2eExportCollision!42"  # pragma: allowlist secret
_SHARED_PROMPT_NAME = "shared-collision-prompt"
_SHARED_RESOURCE_URI = "test://shared-collision/resource"
_RESOURCE_PERMISSIONS = ["prompts.create", "prompts.read", "resources.create", "resources.read"]


def _api(client: httpx.Client, method: str, path: str, *, expected: tuple[int, ...] = (200, 201), **kwargs: Any) -> Any:
    """Send an API request, assert its status and return the JSON body."""
    response = client.request(method, path, **kwargs)
    assert response.status_code in expected, f"{method} {path} returned {response.status_code}: {response.text[:500]}"
    return response.json() if response.content else None


def _create_tenant(admin: httpx.Client, label: str) -> tuple[str, str]:
    """Create a team with one non-admin member holding prompt and resource rights; return team ID and email."""
    team = _api(admin, "POST", "/teams/", json={"name": f"export-{label}-{uuid.uuid4().hex[:8]}", "visibility": "private"})
    email = f"export-{label}-{uuid.uuid4().hex[:8]}@example.com"
    _api(
        admin,
        "POST",
        "/auth/email/admin/users",
        expected=(201,),
        json={"email": email, "password": _PASSWORD, "full_name": label, "is_admin": False, "is_active": True, "password_change_required": False},
    )
    _api(admin, "POST", f"/teams/{team['id']}/members", json={"email": email, "role": "member"})
    _grant(admin, email, _RESOURCE_PERMISSIONS, scope="team", scope_id=team["id"])
    return team["id"], email


def _grant(admin: httpx.Client, email: str, permissions: list[str], *, scope: str, scope_id: str | None = None) -> None:
    """Create a role holding ``permissions`` and grant it to ``email``."""
    role = _api(admin, "POST", "/rbac/roles", json={"name": f"export-role-{uuid.uuid4().hex[:8]}", "scope": scope, "permissions": permissions})
    _api(admin, "POST", f"/rbac/users/{email}/roles", json={"role_id": role["id"], "scope": scope, "scope_id": scope_id})


def _client_for(base_url: str, signing_key: str, email: str, team_id: str) -> httpx.Client:
    """Return a client authenticated as ``email`` and narrowed to ``team_id``."""
    token = make_test_jwt(email, teams=[team_id], secret=signing_key, algorithm="HS256", include_email_claim=True)
    return httpx.Client(base_url=base_url, headers=make_auth_headers(token), timeout=30, trust_env=False)


def _create_records(client: httpx.Client, team_id: str, marker: str) -> tuple[str, str]:
    """Create a private prompt and resource that use the shared identifiers; return their IDs."""
    prompt = _api(
        client,
        "POST",
        "/v1/prompts",
        json={"prompt": {"name": _SHARED_PROMPT_NAME, "description": marker, "template": f"template {marker}", "arguments": []}, "team_id": team_id, "visibility": "private"},
    )
    resource = _api(
        client,
        "POST",
        "/v1/resources",
        json={
            "resource": {"uri": _SHARED_RESOURCE_URI, "name": "shared-collision-resource", "description": marker, "mimeType": "text/plain", "content": marker},
            "team_id": team_id,
            "visibility": "private",
        },
    )
    return prompt["id"], resource["id"]


class _Tenants:
    """A reader holding ``admin.export`` and a victim, each with a colliding private prompt and resource."""

    def __init__(self, gateway: _GatewayFixture) -> None:
        """Create both tenants and their colliding records."""
        self.admin, _token, self.base_url, self.key = gateway
        self.reader_team, self.reader = _create_tenant(self.admin, "reader")
        self.victim_team, self.victim = _create_tenant(self.admin, "victim")
        _grant(self.admin, self.reader, ["admin.export"], scope="global")
        with _client_for(self.base_url, self.key, self.reader, self.reader_team) as reader_client:
            self.reader_prompt_id, self.reader_resource_id = _create_records(reader_client, self.reader_team, "READER_MARKER")
        with _client_for(self.base_url, self.key, self.victim, self.victim_team) as victim_client:
            self.victim_prompt_id, self.victim_resource_id = _create_records(victim_client, self.victim_team, "VICTIM_MARKER")

    def export_as_reader(self, entity_selections: dict[str, list[str]]) -> httpx.Response:
        """POST a selective export as the reader."""
        with _client_for(self.base_url, self.key, self.reader, self.reader_team) as reader_client:
            return reader_client.post("/v1/export/selective", json=entity_selections)


def test_selective_export_by_shared_name_and_uri_returns_only_reader_records(isolated_gateway: _GatewayFixture) -> None:  # noqa: F811  pylint: disable=redefined-outer-name
    """Selecting a shared prompt name and resource URI exports the reader's records and none of the victim's."""
    tenants = _Tenants(isolated_gateway)

    response = tenants.export_as_reader({"prompts": [_SHARED_PROMPT_NAME], "resources": [_SHARED_RESOURCE_URI]})

    assert response.status_code == 200, response.text
    entities = response.json()["entities"]
    assert [prompt["template"] for prompt in entities["prompts"]] == ["template READER_MARKER"]
    assert [resource["description"] for resource in entities["resources"]] == ["READER_MARKER"]
    assert "VICTIM_MARKER" not in response.text


def test_selective_export_by_other_tenants_id_returns_nothing(isolated_gateway: _GatewayFixture) -> None:  # noqa: F811  pylint: disable=redefined-outer-name
    """Negative control: selecting the victim's prompt by ID exports no prompt."""
    tenants = _Tenants(isolated_gateway)

    response = tenants.export_as_reader({"prompts": [tenants.victim_prompt_id]})

    assert response.status_code == 200, response.text
    assert not response.json()["entities"].get("prompts")
    assert "VICTIM_MARKER" not in response.text


def test_selective_export_by_own_id_still_returns_the_record(isolated_gateway: _GatewayFixture) -> None:  # noqa: F811  pylint: disable=redefined-outer-name
    """The fix blocks other tenants' records only: the reader still exports its own prompt by ID."""
    tenants = _Tenants(isolated_gateway)

    response = tenants.export_as_reader({"prompts": [tenants.reader_prompt_id]})

    assert response.status_code == 200, response.text
    assert [prompt["template"] for prompt in response.json()["entities"]["prompts"]] == ["template READER_MARKER"]
