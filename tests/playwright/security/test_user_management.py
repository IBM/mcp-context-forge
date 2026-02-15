# -*- coding: utf-8 -*-
# Copyright (c) 2025 ContextForge Contributors.
# SPDX-License-Identifier: Apache-2.0

"""User Management E2E Tests.

Tests the complete user lifecycle through the REST API and admin endpoints:
create, list, get, update, activate/deactivate, force password change, delete.
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
# User CRUD Lifecycle
# ---------------------------------------------------------------------------


class TestUserLifecycle:
    """Test user create/read/update/delete operations."""

    @pytest.fixture(scope="class")
    def lifecycle_email(self, admin_api: APIRequestContext):
        """Create a user for lifecycle tests, yield email, cleanup after class."""
        email = f"lifecycle-{uuid.uuid4().hex[:8]}@example.com"
        resp = admin_api.post(
            "/auth/email/admin/users",
            data={"email": email, "password": TEST_PASSWORD, "full_name": "Lifecycle User"},
        )
        assert resp.status in (200, 201), f"Failed to create lifecycle user: {resp.status}"
        yield email
        try:
            admin_api.delete(f"/auth/email/admin/users/{email}")
        except Exception:
            pass

    def test_create_user(self, admin_api: APIRequestContext):
        """Admin can create a new user via API."""
        email = f"create-{uuid.uuid4().hex[:8]}@example.com"
        resp = admin_api.post(
            "/auth/email/admin/users",
            data={"email": email, "password": TEST_PASSWORD, "full_name": "Create Test"},
        )
        assert resp.status in (200, 201)
        body = resp.json()
        assert body["email"] == email
        # Cleanup
        admin_api.delete(f"/auth/email/admin/users/{email}")

    def test_list_users_includes_created(self, admin_api: APIRequestContext, lifecycle_email: str):
        """Created user appears in the admin user list."""
        resp = admin_api.get("/auth/email/admin/users")
        assert resp.status == 200
        users = resp.json()
        emails = [u["email"] for u in users]
        assert lifecycle_email in emails

    def test_get_user_details(self, admin_api: APIRequestContext, lifecycle_email: str):
        """Get specific user details by email."""
        resp = admin_api.get(f"/auth/email/admin/users/{lifecycle_email}")
        assert resp.status == 200
        user = resp.json()
        assert user["email"] == lifecycle_email
        assert user["full_name"] == "Lifecycle User"

    def test_update_user(self, admin_api: APIRequestContext, lifecycle_email: str):
        """Update user's full name."""
        resp = admin_api.put(
            f"/auth/email/admin/users/{lifecycle_email}",
            data={"full_name": "Updated Lifecycle User"},
        )
        assert resp.status == 200
        updated = resp.json()
        assert updated["full_name"] == "Updated Lifecycle User"

    def test_delete_user(self, admin_api: APIRequestContext):
        """Admin can delete a user."""
        email = f"delete-{uuid.uuid4().hex[:8]}@example.com"
        admin_api.post(
            "/auth/email/admin/users",
            data={"email": email, "password": TEST_PASSWORD, "full_name": "Delete Me"},
        )
        resp = admin_api.delete(f"/auth/email/admin/users/{email}")
        assert resp.status in (200, 204)
        # Verify deleted
        get_resp = admin_api.get(f"/auth/email/admin/users/{email}")
        assert get_resp.status == 404


# ---------------------------------------------------------------------------
# User Activation / Deactivation
# ---------------------------------------------------------------------------


class TestUserActivation:
    """Test user activate/deactivate/force-password-change operations."""

    def test_deactivate_user(self, admin_api: APIRequestContext, temp_user: str):
        """Admin can deactivate a user."""
        resp = admin_api.put(
            f"/auth/email/admin/users/{temp_user}",
            data={"is_active": False},
        )
        assert resp.status == 200
        user = resp.json()
        assert user.get("is_active") is False

    def test_deactivated_user_cannot_login(self, admin_api: APIRequestContext, anon_api: APIRequestContext):
        """A deactivated user cannot log in."""
        # Create and deactivate a user
        email = f"deact-login-{uuid.uuid4().hex[:8]}@example.com"
        admin_api.post(
            "/auth/email/admin/users",
            data={"email": email, "password": TEST_PASSWORD, "full_name": "Deactivated"},
        )
        admin_api.put(f"/auth/email/admin/users/{email}", data={"is_active": False})

        # Try to login as deactivated user
        login_resp = anon_api.post(
            "/auth/email/login",
            data={"email": email, "password": TEST_PASSWORD},
        )
        assert login_resp.status in (401, 403), f"Deactivated user should be denied login, got {login_resp.status}"

        # Cleanup
        admin_api.delete(f"/auth/email/admin/users/{email}")

    def test_reactivate_user(self, admin_api: APIRequestContext, temp_user: str):
        """Admin can reactivate a deactivated user."""
        # Deactivate
        admin_api.put(f"/auth/email/admin/users/{temp_user}", data={"is_active": False})
        # Reactivate
        resp = admin_api.put(f"/auth/email/admin/users/{temp_user}", data={"is_active": True})
        assert resp.status == 200
        user = resp.json()
        assert user.get("is_active") is True

    def test_force_password_change(self, admin_api: APIRequestContext, temp_user: str):
        """Admin can force a user to change their password on next login."""
        resp = admin_api.put(
            f"/auth/email/admin/users/{temp_user}",
            data={"password_change_required": True},
        )
        assert resp.status == 200
        user = resp.json()
        assert user.get("password_change_required") is True


# ---------------------------------------------------------------------------
# Permission Denial
# ---------------------------------------------------------------------------


class TestUserManagementPermissions:
    """Test that non-admin users are denied user management operations."""

    def test_non_admin_denied_create_user(self, non_admin_api: APIRequestContext):
        """Non-admin user cannot create users."""
        resp = non_admin_api.post(
            "/auth/email/admin/users",
            data={"email": "should-fail@example.com", "password": TEST_PASSWORD, "full_name": "Fail"},
        )
        assert resp.status in (401, 403), f"Non-admin should be denied, got {resp.status}"

    def test_non_admin_denied_list_users(self, non_admin_api: APIRequestContext):
        """Non-admin user cannot list all users."""
        resp = non_admin_api.get("/auth/email/admin/users")
        assert resp.status in (401, 403), f"Non-admin should be denied, got {resp.status}"

    def test_unauthenticated_denied_user_management(self, anon_api: APIRequestContext):
        """Unauthenticated requests are denied user management."""
        resp = anon_api.get("/auth/email/admin/users")
        assert resp.status in (401, 403), f"Unauthenticated should be denied, got {resp.status}"
