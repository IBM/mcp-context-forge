# -*- coding: utf-8 -*-
# Copyright (c) 2025 ContextForge Contributors.
# SPDX-License-Identifier: Apache-2.0

"""RBAC Admin E2E Tests.

Tests role CRUD, user role assignment/revocation, and permission checks
through the /rbac REST API endpoints.
"""

# Future
from __future__ import annotations

# Standard
import logging
import uuid

# Third-Party
from playwright.sync_api import APIRequestContext
import pytest

# Local
from .conftest import TEST_PASSWORD

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Role CRUD Lifecycle
# ---------------------------------------------------------------------------


class TestRoleLifecycle:
    """Test custom role create/read/update/delete operations."""

    @pytest.fixture(scope="class")
    def custom_role(self, admin_api: APIRequestContext):
        """Create a custom role for lifecycle tests, cleanup after class."""
        role_data = {
            "name": f"test-role-{uuid.uuid4().hex[:8]}",
            "description": "E2E test custom role",
            "scope": "global",
            "permissions": ["tools.read", "resources.read"],
        }
        resp = admin_api.post("/rbac/roles", data=role_data)
        assert resp.status in (200, 201), f"Failed to create role: {resp.status} {resp.text()}"
        role = resp.json()
        yield role
        try:
            admin_api.delete(f"/rbac/roles/{role['id']}")
        except Exception:
            pass

    def test_create_custom_role(self, admin_api: APIRequestContext):
        """Admin can create a custom role."""
        role_data = {
            "name": f"create-role-{uuid.uuid4().hex[:8]}",
            "description": "Temporary role",
            "scope": "global",
            "permissions": ["tools.read"],
        }
        resp = admin_api.post("/rbac/roles", data=role_data)
        assert resp.status in (200, 201)
        role = resp.json()
        assert role["name"] == role_data["name"]
        assert "tools.read" in role["permissions"]
        # Cleanup
        admin_api.delete(f"/rbac/roles/{role['id']}")

    def test_list_roles_includes_builtin(self, admin_api: APIRequestContext):
        """Role list includes built-in system roles."""
        resp = admin_api.get("/rbac/roles")
        assert resp.status == 200
        roles = resp.json()
        role_names = [r["name"] for r in roles]
        assert "platform_admin" in role_names
        assert "viewer" in role_names

    def test_get_role_details(self, admin_api: APIRequestContext, custom_role: dict):
        """Get specific role details by ID."""
        resp = admin_api.get(f"/rbac/roles/{custom_role['id']}")
        assert resp.status == 200
        role = resp.json()
        assert role["id"] == custom_role["id"]
        assert role["name"] == custom_role["name"]

    def test_update_role_permissions(self, admin_api: APIRequestContext, custom_role: dict):
        """Admin can update a custom role's permissions."""
        resp = admin_api.put(
            f"/rbac/roles/{custom_role['id']}",
            data={"permissions": ["tools.read", "resources.read", "prompts.read"]},
        )
        assert resp.status == 200
        updated = resp.json()
        assert "prompts.read" in updated["permissions"]

    def test_delete_custom_role(self, admin_api: APIRequestContext):
        """Admin can delete a custom role."""
        resp = admin_api.post(
            "/rbac/roles",
            data={"name": f"del-role-{uuid.uuid4().hex[:8]}", "description": "Delete me", "scope": "global", "permissions": ["tools.read"]},
        )
        assert resp.status in (200, 201)
        role_id = resp.json()["id"]

        del_resp = admin_api.delete(f"/rbac/roles/{role_id}")
        assert del_resp.status == 200

    def test_system_role_delete_returns_400(self, admin_api: APIRequestContext):
        """Deleting a system role should return 400, not 500."""
        resp = admin_api.get("/rbac/roles")
        roles = resp.json()
        pa_role = next((r for r in roles if r["name"] == "platform_admin"), None)
        assert pa_role is not None, "platform_admin role not found"

        del_resp = admin_api.delete(f"/rbac/roles/{pa_role['id']}")
        assert del_resp.status == 400, f"System role delete should return 400, got {del_resp.status}"


# ---------------------------------------------------------------------------
# Role Assignment
# ---------------------------------------------------------------------------


class TestRoleAssignment:
    """Test assigning and revoking roles from users."""

    @pytest.fixture(scope="class")
    def assignment_user(self, admin_api: APIRequestContext):
        """Create a user for role assignment tests."""
        email = f"assign-{uuid.uuid4().hex[:8]}@example.com"
        resp = admin_api.post(
            "/auth/email/admin/users",
            data={"email": email, "password": TEST_PASSWORD, "full_name": "Assignment User"},
        )
        assert resp.status in (200, 201)
        yield email
        try:
            admin_api.delete(f"/auth/email/admin/users/{email}")
        except Exception:
            pass

    @pytest.fixture(scope="class")
    def assignment_role(self, admin_api: APIRequestContext):
        """Create a role for assignment tests."""
        resp = admin_api.post(
            "/rbac/roles",
            data={"name": f"assign-role-{uuid.uuid4().hex[:8]}", "description": "For assignment", "scope": "global", "permissions": ["tools.read"]},
        )
        assert resp.status in (200, 201)
        role = resp.json()
        yield role
        try:
            admin_api.delete(f"/rbac/roles/{role['id']}")
        except Exception:
            pass

    def test_assign_role_to_user(self, admin_api: APIRequestContext, assignment_user: str, assignment_role: dict):
        """Admin can assign a role to a user."""
        resp = admin_api.post(
            f"/rbac/users/{assignment_user}/roles",
            data={"role_id": assignment_role["id"], "scope": "global"},
        )
        assert resp.status in (200, 201), f"Failed to assign role: {resp.status} {resp.text()}"

    def test_list_user_roles(self, admin_api: APIRequestContext, assignment_user: str, assignment_role: dict):
        """Admin can list a user's assigned roles."""
        # Ensure assignment exists
        admin_api.post(
            f"/rbac/users/{assignment_user}/roles",
            data={"role_id": assignment_role["id"], "scope": "global"},
        )
        resp = admin_api.get(f"/rbac/users/{assignment_user}/roles")
        assert resp.status == 200
        roles = resp.json()
        role_ids = [r.get("role_id") or r.get("id") for r in roles]
        assert assignment_role["id"] in role_ids

    def test_revoke_user_role(self, admin_api: APIRequestContext, assignment_user: str, assignment_role: dict):
        """Admin can revoke a role from a user."""
        # Ensure assignment exists
        admin_api.post(
            f"/rbac/users/{assignment_user}/roles",
            data={"role_id": assignment_role["id"], "scope": "global"},
        )
        resp = admin_api.delete(f"/rbac/users/{assignment_user}/roles/{assignment_role['id']}?scope=global")
        assert resp.status in (200, 204), f"Failed to revoke role: {resp.status} {resp.text()}"


# ---------------------------------------------------------------------------
# Permission Checks
# ---------------------------------------------------------------------------


class TestPermissionChecks:
    """Test permission query and denial endpoints."""

    def test_get_available_permissions(self, admin_api: APIRequestContext):
        """List all available system permissions."""
        resp = admin_api.get("/rbac/permissions/available")
        assert resp.status == 200
        data = resp.json()
        # Response format: {"all_permissions": [...], "permissions_by_resource": {...}, "total_count": N}
        perms = data.get("all_permissions", data if isinstance(data, list) else [])
        assert len(perms) > 0, "Expected at least one permission"
        assert any("tools" in str(p) for p in perms)

    def test_non_admin_denied_role_create(self, non_admin_api: APIRequestContext):
        """Non-admin user cannot create roles."""
        resp = non_admin_api.post(
            "/rbac/roles",
            data={"name": "should-fail", "description": "Fail", "scope": "global", "permissions": ["tools.read"]},
        )
        assert resp.status in (401, 403), f"Non-admin should be denied role creation, got {resp.status}"
