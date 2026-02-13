# -*- coding: utf-8 -*-
# Copyright (c) 2025 ContextForge Contributors.
# SPDX-License-Identifier: MIT

"""Admin Bypass Tests for RBAC System.

Verifies allow_admin_bypass=True (default) vs allow_admin_bypass=False
(admin UI, RBAC CRUD) behavior using the require_permission decorator.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
import uuid

# Third-Party
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.db import Base, EmailUser, Role, UserRole
from mcpgateway.services.permission_service import PermissionService


@pytest.fixture(scope="module")
def bypass_db():
    """Create in-memory SQLite DB with admin and non-admin users + roles."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    # Create admin user (also serves as FK target for created_by)
    admin = EmailUser(email="admin@test.local", password_hash="$argon2id$v=19$m=65536,t=3,p=1$test", full_name="Admin", is_admin=True, is_active=True)
    db.add(admin)

    # Non-admin user with specific permissions
    nonadmin = EmailUser(email="user@test.local", password_hash="$argon2id$v=19$m=65536,t=3,p=1$test", full_name="User", is_admin=False, is_active=True)
    db.add(nonadmin)

    # Non-admin with NO roles
    norole = EmailUser(email="norole@test.local", password_hash="$argon2id$v=19$m=65536,t=3,p=1$test", full_name="NoRole", is_admin=False, is_active=True)
    db.add(norole)
    db.flush()

    # Create a role with tools.read permission (global scope)
    role = Role(
        id=str(uuid.uuid4()), name="limited", description="Limited", scope="global", permissions=["tools.read", "admin.dashboard"], created_by="admin@test.local", is_system_role=False, is_active=True
    )
    db.add(role)
    db.flush()

    # Assign role to nonadmin user
    ur = UserRole(user_email="user@test.local", role_id=role.id, scope="global", scope_id=None, granted_by="admin@test.local", is_active=True)
    db.add(ur)

    # Create platform_admin role for admin user so bypass=False still works for admin
    pa_role = Role(id=str(uuid.uuid4()), name="platform_admin", description="All", scope="global", permissions=["*"], created_by="admin@test.local", is_system_role=True, is_active=True)
    db.add(pa_role)
    db.flush()

    pa_ur = UserRole(user_email="admin@test.local", role_id=pa_role.id, scope="global", scope_id=None, granted_by="admin@test.local", is_active=True)
    db.add(pa_ur)

    db.commit()
    yield db
    db.close()
    engine.dispose()


def _check(db, email, permission, allow_admin_bypass=True):
    svc = PermissionService(db, audit_enabled=False)
    svc.clear_cache()
    return asyncio.run(svc.check_permission(user_email=email, permission=permission, allow_admin_bypass=allow_admin_bypass))


# ---------------------------------------------------------------------------
# D3.1: Admin Bypass Matrix
# ---------------------------------------------------------------------------


class TestAdminBypassMatrix:
    """Test allow_admin_bypass=True vs False for admin and non-admin users."""

    def test_bypass_true_admin_granted(self, bypass_db):
        """bypass=True + admin → granted (admin bypass)."""
        assert _check(bypass_db, "admin@test.local", "tools.create", allow_admin_bypass=True) is True

    def test_bypass_true_nonadmin_with_perm_granted(self, bypass_db):
        """bypass=True + non-admin + has permission → granted."""
        assert _check(bypass_db, "user@test.local", "tools.read", allow_admin_bypass=True) is True

    def test_bypass_true_nonadmin_without_perm_denied(self, bypass_db):
        """bypass=True + non-admin + no permission → denied."""
        assert _check(bypass_db, "user@test.local", "admin.system_config", allow_admin_bypass=True) is False

    def test_bypass_false_admin_with_perm_granted(self, bypass_db):
        """bypass=False + admin + has permission (via platform_admin wildcard) → granted."""
        assert _check(bypass_db, "admin@test.local", "tools.read", allow_admin_bypass=False) is True

    def test_bypass_false_admin_still_granted_via_wildcard(self, bypass_db):
        """bypass=False + admin + wildcard '*' → granted (checked via role, not bypass)."""
        assert _check(bypass_db, "admin@test.local", "admin.system_config", allow_admin_bypass=False) is True

    def test_bypass_false_nonadmin_with_perm_granted(self, bypass_db):
        """bypass=False + non-admin + has permission → granted."""
        assert _check(bypass_db, "user@test.local", "tools.read", allow_admin_bypass=False) is True

    def test_bypass_false_nonadmin_without_perm_denied(self, bypass_db):
        """bypass=False + non-admin + no permission → denied."""
        assert _check(bypass_db, "user@test.local", "admin.system_config", allow_admin_bypass=False) is False


# ---------------------------------------------------------------------------
# D3.2: Admin without platform_admin role + bypass=False
# ---------------------------------------------------------------------------


class TestAdminWithoutPlatformAdminRole:
    """Admin user without platform_admin role assignment should be denied when bypass=False."""

    @pytest.fixture
    def admin_no_role_db(self):
        """DB with admin user who has NO role assignments."""
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        db = Session()

        admin = EmailUser(email="bare-admin@test.local", password_hash="$argon2id$v=19$m=65536,t=3,p=1$test", full_name="Bare Admin", is_admin=True, is_active=True)
        db.add(admin)
        db.commit()
        yield db
        db.close()
        engine.dispose()

    def test_admin_no_role_bypass_true_granted(self, admin_no_role_db):
        """bypass=True + admin (no roles) → granted via admin bypass."""
        assert _check(admin_no_role_db, "bare-admin@test.local", "tools.create", allow_admin_bypass=True) is True

    def test_admin_no_role_bypass_false_denied(self, admin_no_role_db):
        """bypass=False + admin (no roles) → DENIED (key test! No role grants the permission)."""
        assert _check(admin_no_role_db, "bare-admin@test.local", "tools.create", allow_admin_bypass=False) is False


# ---------------------------------------------------------------------------
# D3.3: Decorator-level bypass enforcement verification
# ---------------------------------------------------------------------------


class TestAdminUIBypassEnforcement:
    """Verify admin UI endpoints actually use allow_admin_bypass=False."""

    def test_admin_ui_endpoints_use_bypass_false(self):
        """Spot-check that admin.py decorators set allow_admin_bypass=False."""
        # Standard
        import inspect

        # First-Party
        import mcpgateway.admin as admin_mod

        source = inspect.getsource(admin_mod)
        # Count occurrences of bypass=False in admin.py
        bypass_false_count = source.count("allow_admin_bypass=False")
        # admin.py should have many endpoints with bypass=False
        assert bypass_false_count > 20, f"Expected >20 admin UI endpoints with bypass=False, found {bypass_false_count}"

    def test_rbac_crud_endpoints_use_bypass_false_or_require_admin(self):
        """Verify RBAC router uses require_admin_permission or admin.user_management."""
        # Standard
        import inspect

        # First-Party
        import mcpgateway.routers.rbac as rbac_router

        source = inspect.getsource(rbac_router)
        # RBAC router should use require_admin_permission or admin.user_management
        assert "require_admin_permission" in source or "admin.user_management" in source
