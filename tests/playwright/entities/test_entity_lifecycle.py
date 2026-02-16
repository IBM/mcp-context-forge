# -*- coding: utf-8 -*-
# Copyright (c) 2025 ContextForge Contributors.
# SPDX-License-Identifier: Apache-2.0

"""Entity Lifecycle E2E Tests (REST API).

Tests full CRUD lifecycle + activate/deactivate for tools, resources, prompts,
and servers via the REST API. Complements the existing browser-based entity tests.
"""

# Future
from __future__ import annotations

# Standard
import logging
import os
import uuid

# Third-Party
from playwright.sync_api import APIRequestContext, Playwright
import pytest

# First-Party
from mcpgateway.utils.create_jwt_token import _create_jwt_token

logger = logging.getLogger(__name__)

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8080")


def _make_jwt(email: str, is_admin: bool = False, teams=None) -> str:
    return _create_jwt_token(
        {"sub": email},
        user_data={"email": email, "is_admin": is_admin, "auth_provider": "local"},
        teams=teams,
    )


@pytest.fixture(scope="module")
def admin_api(playwright: Playwright):
    """Admin-authenticated API context."""
    token = _make_jwt("admin@example.com", is_admin=True)
    ctx = playwright.request.new_context(
        base_url=BASE_URL,
        extra_http_headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    yield ctx
    ctx.dispose()


@pytest.fixture(scope="module")
def viewer_api(playwright: Playwright):
    """Viewer (non-admin, no RBAC roles) API context for permission checks."""
    email = f"viewer-entity-{uuid.uuid4().hex[:8]}@example.com"
    token = _make_jwt(email, is_admin=False)
    ctx = playwright.request.new_context(
        base_url=BASE_URL,
        extra_http_headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    yield ctx
    ctx.dispose()


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class TestToolLifecycle:
    """Full CRUD + activate/deactivate lifecycle for tools via REST API."""

    def test_create_tool(self, admin_api: APIRequestContext):
        """Admin can create a REST tool."""
        name = f"lifecycle-tool-{uuid.uuid4().hex[:8]}"
        resp = admin_api.post(
            "/tools/",
            data={
                "tool": {
                    "name": name,
                    "url": "https://httpbin.org/post",
                    "description": "Lifecycle test tool",
                    "integration_type": "REST",
                    "request_type": "POST",
                },
                "team_id": None,
            },
        )
        assert resp.status in (200, 201), f"Create tool failed: {resp.status} {resp.text()}"
        tool = resp.json()
        assert tool["name"] == name

        # Cleanup
        admin_api.delete(f"/tools/{tool['id']}")

    def test_list_tools(self, admin_api: APIRequestContext):
        """Admin can list tools."""
        resp = admin_api.get("/tools/")
        assert resp.status == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_get_tool(self, admin_api: APIRequestContext):
        """Admin can get a specific tool."""
        name = f"get-tool-{uuid.uuid4().hex[:8]}"
        create_resp = admin_api.post(
            "/tools/",
            data={
                "tool": {
                    "name": name,
                    "url": "https://httpbin.org/post",
                    "description": "Get test",
                    "integration_type": "REST",
                    "request_type": "POST",
                },
                "team_id": None,
            },
        )
        assert create_resp.status in (200, 201), f"Create tool failed: {create_resp.status} {create_resp.text()}"
        tool = create_resp.json()

        resp = admin_api.get(f"/tools/{tool['id']}")
        assert resp.status == 200
        fetched = resp.json()
        assert fetched["name"] == name

        admin_api.delete(f"/tools/{tool['id']}")

    def test_update_tool(self, admin_api: APIRequestContext):
        """Admin can update a tool's description."""
        name = f"update-tool-{uuid.uuid4().hex[:8]}"
        create_resp = admin_api.post(
            "/tools/",
            data={
                "tool": {
                    "name": name,
                    "url": "https://httpbin.org/post",
                    "description": "Original",
                    "integration_type": "REST",
                    "request_type": "POST",
                },
                "team_id": None,
            },
        )
        assert create_resp.status in (200, 201), f"Create tool failed: {create_resp.status} {create_resp.text()}"
        tool = create_resp.json()

        resp = admin_api.put(f"/tools/{tool['id']}", data={"description": "Updated description"})
        assert resp.status == 200
        updated = resp.json()
        assert updated["description"] == "Updated description"

        admin_api.delete(f"/tools/{tool['id']}")

    def test_deactivate_tool(self, admin_api: APIRequestContext):
        """Admin can deactivate a tool via state endpoint."""
        name = f"deact-tool-{uuid.uuid4().hex[:8]}"
        create_resp = admin_api.post(
            "/tools/",
            data={
                "tool": {
                    "name": name,
                    "url": "https://httpbin.org/post",
                    "description": "Deactivate test",
                    "integration_type": "REST",
                    "request_type": "POST",
                },
                "team_id": None,
            },
        )
        assert create_resp.status in (200, 201), f"Create tool failed: {create_resp.status} {create_resp.text()}"
        tool = create_resp.json()

        resp = admin_api.post(f"/tools/{tool['id']}/state?activate=false")
        assert resp.status == 200

        # Verify inactive (should not appear in default list)
        list_resp = admin_api.get("/tools/")
        tool_ids = [t["id"] for t in list_resp.json()]
        assert tool["id"] not in tool_ids

        admin_api.delete(f"/tools/{tool['id']}")

    def test_reactivate_tool(self, admin_api: APIRequestContext):
        """Admin can reactivate a deactivated tool."""
        name = f"react-tool-{uuid.uuid4().hex[:8]}"
        create_resp = admin_api.post(
            "/tools/",
            data={
                "tool": {
                    "name": name,
                    "url": "https://httpbin.org/post",
                    "description": "Reactivate test",
                    "integration_type": "REST",
                    "request_type": "POST",
                },
                "team_id": None,
            },
        )
        assert create_resp.status in (200, 201), f"Create tool failed: {create_resp.status} {create_resp.text()}"
        tool = create_resp.json()

        # Deactivate then reactivate
        admin_api.post(f"/tools/{tool['id']}/state?activate=false")
        resp = admin_api.post(f"/tools/{tool['id']}/state?activate=true")
        assert resp.status == 200

        # Verify active again
        list_resp = admin_api.get("/tools/")
        tool_ids = [t["id"] for t in list_resp.json()]
        assert tool["id"] in tool_ids

        admin_api.delete(f"/tools/{tool['id']}")

    def test_delete_tool(self, admin_api: APIRequestContext):
        """Admin can delete a tool."""
        name = f"del-tool-{uuid.uuid4().hex[:8]}"
        create_resp = admin_api.post(
            "/tools/",
            data={
                "tool": {
                    "name": name,
                    "url": "https://httpbin.org/post",
                    "description": "Delete test",
                    "integration_type": "REST",
                    "request_type": "POST",
                },
                "team_id": None,
            },
        )
        assert create_resp.status in (200, 201), f"Create tool failed: {create_resp.status} {create_resp.text()}"
        tool = create_resp.json()

        resp = admin_api.delete(f"/tools/{tool['id']}")
        assert resp.status == 200

        # Verify deleted
        get_resp = admin_api.get(f"/tools/{tool['id']}")
        assert get_resp.status == 404


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


class TestResourceLifecycle:
    """Full CRUD + activate/deactivate lifecycle for resources."""

    def test_create_resource(self, admin_api: APIRequestContext):
        """Admin can create a resource."""
        name = f"lifecycle-res-{uuid.uuid4().hex[:8]}"
        resp = admin_api.post(
            "/resources/",
            data={
                "resource": {
                    "uri": f"file:///test/{name}.txt",
                    "name": name,
                    "description": "Lifecycle test resource",
                    "mimeType": "text/plain",
                    "content": "test content",
                },
                "team_id": None,
            },
        )
        assert resp.status in (200, 201), f"Create resource failed: {resp.status} {resp.text()}"
        resource = resp.json()
        assert resource["name"] == name

        admin_api.delete(f"/resources/{resource['id']}")

    def test_list_resources(self, admin_api: APIRequestContext):
        """Admin can list resources."""
        resp = admin_api.get("/resources/")
        assert resp.status == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_get_resource_info(self, admin_api: APIRequestContext):
        """Admin can get resource info."""
        name = f"get-res-{uuid.uuid4().hex[:8]}"
        create_resp = admin_api.post(
            "/resources/",
            data={
                "resource": {
                    "uri": f"file:///test/{name}.txt",
                    "name": name,
                    "description": "Get test",
                    "mimeType": "text/plain",
                    "content": "test content",
                },
                "team_id": None,
            },
        )
        assert create_resp.status in (200, 201), f"Create resource failed: {create_resp.status} {create_resp.text()}"
        resource = create_resp.json()

        resp = admin_api.get(f"/resources/{resource['id']}/info")
        assert resp.status == 200
        fetched = resp.json()
        assert fetched["name"] == name

        admin_api.delete(f"/resources/{resource['id']}")

    def test_update_resource(self, admin_api: APIRequestContext):
        """Admin can update a resource."""
        name = f"update-res-{uuid.uuid4().hex[:8]}"
        create_resp = admin_api.post(
            "/resources/",
            data={
                "resource": {
                    "uri": f"file:///test/{name}.txt",
                    "name": name,
                    "description": "Original",
                    "mimeType": "text/plain",
                    "content": "test content",
                },
                "team_id": None,
            },
        )
        assert create_resp.status in (200, 201), f"Create resource failed: {create_resp.status} {create_resp.text()}"
        resource = create_resp.json()

        resp = admin_api.put(f"/resources/{resource['id']}", data={"description": "Updated resource"})
        assert resp.status == 200
        updated = resp.json()
        assert updated["description"] == "Updated resource"

        admin_api.delete(f"/resources/{resource['id']}")

    def test_deactivate_resource(self, admin_api: APIRequestContext):
        """Admin can deactivate a resource."""
        name = f"deact-res-{uuid.uuid4().hex[:8]}"
        create_resp = admin_api.post(
            "/resources/",
            data={
                "resource": {
                    "uri": f"file:///test/{name}.txt",
                    "name": name,
                    "description": "Deactivate test",
                    "mimeType": "text/plain",
                    "content": "test content",
                },
                "team_id": None,
            },
        )
        assert create_resp.status in (200, 201), f"Create resource failed: {create_resp.status} {create_resp.text()}"
        resource = create_resp.json()

        resp = admin_api.post(f"/resources/{resource['id']}/state?activate=false")
        assert resp.status == 200

        # Verify inactive
        list_resp = admin_api.get("/resources/")
        res_ids = [r["id"] for r in list_resp.json()]
        assert resource["id"] not in res_ids

        admin_api.delete(f"/resources/{resource['id']}")

    def test_reactivate_resource(self, admin_api: APIRequestContext):
        """Admin can reactivate a resource."""
        name = f"react-res-{uuid.uuid4().hex[:8]}"
        create_resp = admin_api.post(
            "/resources/",
            data={
                "resource": {
                    "uri": f"file:///test/{name}.txt",
                    "name": name,
                    "description": "Reactivate test",
                    "mimeType": "text/plain",
                    "content": "test content",
                },
                "team_id": None,
            },
        )
        assert create_resp.status in (200, 201), f"Create resource failed: {create_resp.status} {create_resp.text()}"
        resource = create_resp.json()

        admin_api.post(f"/resources/{resource['id']}/state?activate=false")
        resp = admin_api.post(f"/resources/{resource['id']}/state?activate=true")
        assert resp.status == 200

        list_resp = admin_api.get("/resources/")
        res_ids = [r["id"] for r in list_resp.json()]
        assert resource["id"] in res_ids

        admin_api.delete(f"/resources/{resource['id']}")

    def test_delete_resource(self, admin_api: APIRequestContext):
        """Admin can delete a resource."""
        name = f"del-res-{uuid.uuid4().hex[:8]}"
        create_resp = admin_api.post(
            "/resources/",
            data={
                "resource": {
                    "uri": f"file:///test/{name}.txt",
                    "name": name,
                    "description": "Delete test",
                    "mimeType": "text/plain",
                    "content": "test content",
                },
                "team_id": None,
            },
        )
        assert create_resp.status in (200, 201), f"Create resource failed: {create_resp.status} {create_resp.text()}"
        resource = create_resp.json()

        resp = admin_api.delete(f"/resources/{resource['id']}")
        assert resp.status == 200

        get_resp = admin_api.get(f"/resources/{resource['id']}/info")
        assert get_resp.status == 404


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


class TestPromptLifecycle:
    """Full CRUD + activate/deactivate lifecycle for prompts."""

    def test_create_prompt(self, admin_api: APIRequestContext):
        """Admin can create a prompt."""
        name = f"lifecycle-prompt-{uuid.uuid4().hex[:8]}"
        resp = admin_api.post(
            "/prompts/",
            data={
                "prompt": {
                    "name": name,
                    "description": "Lifecycle test prompt",
                    "template": "Tell me about {{topic}}",
                    "arguments": [{"name": "topic", "description": "The topic", "required": True}],
                },
                "team_id": None,
            },
        )
        assert resp.status in (200, 201), f"Create prompt failed: {resp.status} {resp.text()}"
        prompt = resp.json()
        assert prompt["name"] == name

        admin_api.delete(f"/prompts/{prompt['id']}")

    def test_list_prompts(self, admin_api: APIRequestContext):
        """Admin can list prompts."""
        resp = admin_api.get("/prompts/")
        assert resp.status == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_get_prompt(self, admin_api: APIRequestContext):
        """Admin can get a prompt (returns rendered MCP messages)."""
        name = f"get-prompt-{uuid.uuid4().hex[:8]}"
        create_resp = admin_api.post(
            "/prompts/",
            data={
                "prompt": {
                    "name": name,
                    "description": "Get test",
                    "template": "Test prompt template",
                    "arguments": [],
                },
                "team_id": None,
            },
        )
        assert create_resp.status in (200, 201), f"Create prompt failed: {create_resp.status} {create_resp.text()}"
        prompt = create_resp.json()

        # GET /prompts/{id} returns rendered MCP messages, not raw metadata
        resp = admin_api.get(f"/prompts/{prompt['id']}")
        assert resp.status == 200
        fetched = resp.json()
        assert "messages" in fetched or "description" in fetched

        admin_api.delete(f"/prompts/{prompt['id']}")

    def test_update_prompt(self, admin_api: APIRequestContext):
        """Admin can update a prompt."""
        name = f"update-prompt-{uuid.uuid4().hex[:8]}"
        create_resp = admin_api.post(
            "/prompts/",
            data={
                "prompt": {
                    "name": name,
                    "description": "Original",
                    "template": "Test prompt template",
                    "arguments": [],
                },
                "team_id": None,
            },
        )
        assert create_resp.status in (200, 201), f"Create prompt failed: {create_resp.status} {create_resp.text()}"
        prompt = create_resp.json()

        resp = admin_api.put(f"/prompts/{prompt['id']}", data={"description": "Updated prompt"})
        assert resp.status == 200
        updated = resp.json()
        assert updated["description"] == "Updated prompt"

        admin_api.delete(f"/prompts/{prompt['id']}")

    def test_deactivate_prompt(self, admin_api: APIRequestContext):
        """Admin can deactivate a prompt."""
        name = f"deact-prompt-{uuid.uuid4().hex[:8]}"
        create_resp = admin_api.post(
            "/prompts/",
            data={
                "prompt": {
                    "name": name,
                    "description": "Deactivate test",
                    "template": "Test prompt template",
                    "arguments": [],
                },
                "team_id": None,
            },
        )
        assert create_resp.status in (200, 201), f"Create prompt failed: {create_resp.status} {create_resp.text()}"
        prompt = create_resp.json()

        resp = admin_api.post(f"/prompts/{prompt['id']}/state?activate=false")
        assert resp.status == 200

        list_resp = admin_api.get("/prompts/")
        prompt_ids = [p["id"] for p in list_resp.json()]
        assert prompt["id"] not in prompt_ids

        admin_api.delete(f"/prompts/{prompt['id']}")

    def test_reactivate_prompt(self, admin_api: APIRequestContext):
        """Admin can reactivate a prompt."""
        name = f"react-prompt-{uuid.uuid4().hex[:8]}"
        create_resp = admin_api.post(
            "/prompts/",
            data={
                "prompt": {
                    "name": name,
                    "description": "Reactivate test",
                    "template": "Test prompt template",
                    "arguments": [],
                },
                "team_id": None,
            },
        )
        assert create_resp.status in (200, 201), f"Create prompt failed: {create_resp.status} {create_resp.text()}"
        prompt = create_resp.json()

        admin_api.post(f"/prompts/{prompt['id']}/state?activate=false")
        resp = admin_api.post(f"/prompts/{prompt['id']}/state?activate=true")
        assert resp.status == 200

        list_resp = admin_api.get("/prompts/")
        prompt_ids = [p["id"] for p in list_resp.json()]
        assert prompt["id"] in prompt_ids

        admin_api.delete(f"/prompts/{prompt['id']}")

    def test_delete_prompt(self, admin_api: APIRequestContext):
        """Admin can delete a prompt."""
        name = f"del-prompt-{uuid.uuid4().hex[:8]}"
        create_resp = admin_api.post(
            "/prompts/",
            data={
                "prompt": {
                    "name": name,
                    "description": "Delete test",
                    "template": "Test prompt template",
                    "arguments": [],
                },
                "team_id": None,
            },
        )
        assert create_resp.status in (200, 201), f"Create prompt failed: {create_resp.status} {create_resp.text()}"
        prompt = create_resp.json()

        resp = admin_api.delete(f"/prompts/{prompt['id']}")
        assert resp.status == 200

        get_resp = admin_api.get(f"/prompts/{prompt['id']}")
        assert get_resp.status == 404


# ---------------------------------------------------------------------------
# Servers
# ---------------------------------------------------------------------------


class TestServerLifecycle:
    """Full CRUD + activate/deactivate lifecycle for virtual servers."""

    def test_create_server(self, admin_api: APIRequestContext):
        """Admin can create a virtual server."""
        name = f"lifecycle-srv-{uuid.uuid4().hex[:8]}"
        resp = admin_api.post(
            "/servers/",
            data={
                "server": {
                    "name": name,
                    "description": "Lifecycle test server",
                    "icon": "https://example.com/icon.png",
                },
                "team_id": None,
            },
        )
        assert resp.status in (200, 201), f"Create server failed: {resp.status} {resp.text()}"
        server = resp.json()
        assert server["name"] == name

        admin_api.delete(f"/servers/{server['id']}")

    def test_list_servers(self, admin_api: APIRequestContext):
        """Admin can list servers."""
        resp = admin_api.get("/servers/")
        assert resp.status == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_get_server(self, admin_api: APIRequestContext):
        """Admin can get a specific server."""
        name = f"get-srv-{uuid.uuid4().hex[:8]}"
        create_resp = admin_api.post(
            "/servers/",
            data={
                "server": {
                    "name": name,
                    "description": "Get test",
                    "icon": "https://example.com/icon.png",
                },
                "team_id": None,
            },
        )
        assert create_resp.status in (200, 201), f"Create server failed: {create_resp.status} {create_resp.text()}"
        server = create_resp.json()

        resp = admin_api.get(f"/servers/{server['id']}")
        assert resp.status == 200
        fetched = resp.json()
        assert fetched["name"] == name

        admin_api.delete(f"/servers/{server['id']}")

    def test_update_server(self, admin_api: APIRequestContext):
        """Admin can update a server."""
        name = f"update-srv-{uuid.uuid4().hex[:8]}"
        create_resp = admin_api.post(
            "/servers/",
            data={
                "server": {
                    "name": name,
                    "description": "Original",
                    "icon": "https://example.com/icon.png",
                },
                "team_id": None,
            },
        )
        assert create_resp.status in (200, 201), f"Create server failed: {create_resp.status} {create_resp.text()}"
        server = create_resp.json()

        resp = admin_api.put(f"/servers/{server['id']}", data={"description": "Updated server"})
        assert resp.status == 200
        updated = resp.json()
        assert updated["description"] == "Updated server"

        admin_api.delete(f"/servers/{server['id']}")

    def test_deactivate_server(self, admin_api: APIRequestContext):
        """Admin can deactivate a server."""
        name = f"deact-srv-{uuid.uuid4().hex[:8]}"
        create_resp = admin_api.post(
            "/servers/",
            data={
                "server": {
                    "name": name,
                    "description": "Deactivate test",
                    "icon": "https://example.com/icon.png",
                },
                "team_id": None,
            },
        )
        assert create_resp.status in (200, 201), f"Create server failed: {create_resp.status} {create_resp.text()}"
        server = create_resp.json()

        resp = admin_api.post(f"/servers/{server['id']}/state?activate=false")
        assert resp.status == 200

        list_resp = admin_api.get("/servers/")
        srv_ids = [s["id"] for s in list_resp.json()]
        assert server["id"] not in srv_ids

        admin_api.delete(f"/servers/{server['id']}")

    def test_reactivate_server(self, admin_api: APIRequestContext):
        """Admin can reactivate a server."""
        name = f"react-srv-{uuid.uuid4().hex[:8]}"
        create_resp = admin_api.post(
            "/servers/",
            data={
                "server": {
                    "name": name,
                    "description": "Reactivate test",
                    "icon": "https://example.com/icon.png",
                },
                "team_id": None,
            },
        )
        assert create_resp.status in (200, 201), f"Create server failed: {create_resp.status} {create_resp.text()}"
        server = create_resp.json()

        admin_api.post(f"/servers/{server['id']}/state?activate=false")
        resp = admin_api.post(f"/servers/{server['id']}/state?activate=true")
        assert resp.status == 200

        list_resp = admin_api.get("/servers/")
        srv_ids = [s["id"] for s in list_resp.json()]
        assert server["id"] in srv_ids

        admin_api.delete(f"/servers/{server['id']}")

    def test_delete_server(self, admin_api: APIRequestContext):
        """Admin can delete a server."""
        name = f"del-srv-{uuid.uuid4().hex[:8]}"
        create_resp = admin_api.post(
            "/servers/",
            data={
                "server": {
                    "name": name,
                    "description": "Delete test",
                    "icon": "https://example.com/icon.png",
                },
                "team_id": None,
            },
        )
        assert create_resp.status in (200, 201), f"Create server failed: {create_resp.status} {create_resp.text()}"
        server = create_resp.json()

        resp = admin_api.delete(f"/servers/{server['id']}")
        assert resp.status == 200

        get_resp = admin_api.get(f"/servers/{server['id']}")
        assert get_resp.status == 404


# ---------------------------------------------------------------------------
# RBAC Permission Checks (cross-entity)
# ---------------------------------------------------------------------------


class TestEntityRBACPermissions:
    """Verify that unprivileged users are denied entity mutations."""

    @pytest.mark.parametrize(
        "entity,body",
        [
            ("tools", {"tool": {"name": "deny-tool", "url": "https://httpbin.org/post", "integration_type": "REST", "request_type": "POST"}, "team_id": None}),
            ("resources", {"resource": {"uri": "file:///deny.txt", "name": "deny-res", "mimeType": "text/plain", "content": "denied"}, "team_id": None}),
            ("prompts", {"prompt": {"name": "deny-prompt", "description": "denied", "template": "denied", "arguments": []}, "team_id": None}),
            ("servers", {"server": {"name": "deny-srv", "icon": "https://example.com/icon.png"}, "team_id": None}),
        ],
    )
    def test_unprivileged_user_cannot_create(self, viewer_api: APIRequestContext, entity: str, body: dict):
        """User without create permission is denied."""
        resp = viewer_api.post(f"/{entity}/", data=body)
        assert resp.status in (401, 403), f"Unprivileged create on {entity} should be denied, got {resp.status}"
