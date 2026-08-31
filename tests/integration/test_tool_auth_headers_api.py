# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_tool_auth_headers_api.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

End-to-end coverage for the ``auth_headers`` array on the JSON tool API (issue #5201).

Unlike the schema-level unit tests, these drive the real ``POST /tools`` / ``PUT /tools/{id}``
routes through ToolService and assert what actually lands in the database, so the originally
reported bug (headers silently dropped, ``auth_value`` stored as ``NULL``) stays closed.
"""

# Standard
from unittest.mock import AsyncMock, patch

# Third-Party
from fastapi.testclient import TestClient
import pytest

# First-Party
import mcpgateway.db as db_mod
from mcpgateway.db import Tool as DbTool
from mcpgateway.middleware.rbac import get_current_user_with_permissions
from mcpgateway.utils.services_auth import decode_auth

REPRO_HEADERS = [
    {"key": "X-API-Key", "value": "secret"},
    {"key": "X-Tenant", "value": "acme"},
]


@pytest.fixture
def client(app_with_temp_db):
    """TestClient with authentication and RBAC bypassed."""

    def _current_user(_request=None, _credentials=None, _jwt_token=None):
        return {"email": "test_user@example.com", "full_name": "Test User", "is_admin": True, "ip_address": "127.0.0.1", "user_agent": "test"}

    app_with_temp_db.dependency_overrides[get_current_user_with_permissions] = _current_user
    with patch("mcpgateway.middleware.rbac.PermissionService.check_permission", new=AsyncMock(return_value=True)):
        yield TestClient(app_with_temp_db)
    app_with_temp_db.dependency_overrides.pop(get_current_user_with_permissions, None)


def _stored_auth(tool_name: str):
    """Read the persisted auth_type/auth_value for a tool straight from the database.

    Args:
        tool_name: Name of the tool to look up.

    Returns:
        tuple: The stored ``(auth_type, auth_value)`` pair.
    """
    # Resolved lazily: the app_with_temp_db fixture swaps db_mod.SessionLocal for the temp DB.
    with db_mod.SessionLocal() as session:
        tool = session.query(DbTool).filter(DbTool.original_name == tool_name).one()
        return tool.auth_type, tool.auth_value


def _create_payload(name: str, **tool_fields):
    """Build a POST /tools request body.

    Args:
        name: Tool name.
        **tool_fields: Extra fields merged into the nested tool object.

    Returns:
        dict: The request body.
    """
    tool = {"name": name, "url": "https://api.example.com/endpoint", "request_type": "POST", "integration_type": "REST"}
    tool.update(tool_fields)
    return {"tool": tool, "team_id": None, "visibility": "private"}


def test_post_tools_persists_auth_headers_array(client):
    """POST /tools stores every entry of the auth_headers array (issue #5201 repro)."""
    response = client.post("/tools/", json=_create_payload("repro_tool", auth_type="authheaders", auth_headers=REPRO_HEADERS))
    assert response.status_code == 200, response.text

    auth_type, auth_value = _stored_auth("repro_tool")
    assert auth_type == "authheaders"
    assert auth_value is not None, "auth_value was stored as NULL - headers were dropped"
    assert decode_auth(auth_value) == {"X-API-Key": "secret", "X-Tenant": "acme"}


def test_put_tools_persists_auth_headers_array(client):
    """PUT /tools/{id} replaces stored headers with the full auth_headers array."""
    created = client.post("/tools/", json=_create_payload("update_tool", auth_type="authheaders", auth_headers=[{"key": "X-Old", "value": "old"}]))
    assert created.status_code == 200, created.text
    tool_id = created.json()["id"]

    response = client.put(f"/tools/{tool_id}", json={"auth_type": "authheaders", "auth_headers": REPRO_HEADERS})
    assert response.status_code == 200, response.text

    _, auth_value = _stored_auth("update_tool")
    assert decode_auth(auth_value) == {"X-API-Key": "secret", "X-Tenant": "acme"}


def test_post_tools_malformed_header_key_returns_422(client):
    """A malformed header key is a client error, not an unhandled 500."""
    response = client.post("/tools/", json=_create_payload("bad_key_tool", auth_type="authheaders", auth_headers=[{"key": "Bad@Key!", "value": "x"}]))
    assert response.status_code == 422, response.text


def test_post_tools_non_string_header_key_returns_422(client):
    """A non-string header key is a client error, not an unhandled 500.

    ToolCreate assembles auth in a ``mode="before"`` validator, so this value reaches the
    encoder uncoerced; it previously raised AttributeError/TypeError and surfaced as a 500.
    """
    response = client.post("/tools/", json=_create_payload("bad_key_type_tool", auth_type="authheaders", auth_headers=[{"key": 123, "value": "x"}]))
    assert response.status_code == 422, response.text


def test_post_tools_excessive_headers_returns_422(client):
    """More than 100 header entries is rejected through the real route, not persisted."""
    headers = [{"key": f"X-Header-{i}", "value": f"v{i}"} for i in range(101)]
    response = client.post("/tools/", json=_create_payload("too_many_headers_tool", auth_type="authheaders", auth_headers=headers))
    assert response.status_code == 422, response.text


def test_post_tools_persists_legacy_single_header_pair(client):
    """The legacy auth_header_key/auth_header_value pair still persists through POST /tools."""
    response = client.post(
        "/tools/",
        json=_create_payload("legacy_tool", auth_type="authheaders", auth_header_key="X-API-Key", auth_header_value="legacy-secret"),
    )
    assert response.status_code == 200, response.text

    _, auth_value = _stored_auth("legacy_tool")
    assert decode_auth(auth_value) == {"X-API-Key": "legacy-secret"}  # pragma: allowlist secret


def test_put_tools_empty_array_preserves_stored_headers(client):
    """PUT /tools/{id} with an empty auth_headers array leaves existing credentials intact.

    The schema resolves an empty array to ``auth_value=None``, but ToolService.update_tool only
    writes auth_value when it is non-null, so a partial update never wipes stored secrets. This
    pins that behavior: an empty array is not an "unset headers" instruction, and clearing
    credentials is not supported through this path.
    """
    created = client.post("/tools/", json=_create_payload("clear_tool", auth_type="authheaders", auth_headers=REPRO_HEADERS))
    assert created.status_code == 200, created.text
    tool_id = created.json()["id"]

    response = client.put(f"/tools/{tool_id}", json={"auth_type": "authheaders", "auth_headers": []})
    assert response.status_code == 200, response.text

    _, auth_value = _stored_auth("clear_tool")
    assert decode_auth(auth_value) == {"X-API-Key": "secret", "X-Tenant": "acme"}
