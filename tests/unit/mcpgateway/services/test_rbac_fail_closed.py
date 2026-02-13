# -*- coding: utf-8 -*-
# Copyright (c) 2025 ContextForge Contributors.
# SPDX-License-Identifier: Apache-2.0

"""Fail-Closed Tests for RBAC System.

Verifies that permission checks default to DENY on errors, exceptions,
expired roles, deactivated roles, and corrupted state.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
from datetime import timedelta
from unittest.mock import patch
import uuid

# Third-Party
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.db import Base, EmailUser, Role, UserRole, utc_now
from mcpgateway.services.permission_service import PermissionService


@pytest.fixture
def fail_db():
    """Create in-memory SQLite DB for fail-closed tests."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    # Create admin user (FK target)
    admin = EmailUser(email="admin@test.local", password_hash="$argon2id$v=19$m=65536,t=3,p=1$test", full_name="Admin", is_admin=False, is_active=True)
    db.add(admin)
    db.flush()

    # Create a role with tools.read
    role = Role(
        id=str(uuid.uuid4()), name="dev_role", description="Dev", scope="global", permissions=["tools.read", "tools.create"], created_by="admin@test.local", is_system_role=False, is_active=True
    )
    db.add(role)
    db.flush()

    # Active assignment
    ur = UserRole(user_email="admin@test.local", role_id=role.id, scope="global", scope_id=None, granted_by="admin@test.local", is_active=True)
    db.add(ur)
    db.commit()

    yield db, role
    db.close()
    engine.dispose()


def _check(db, email, permission, **kwargs):
    svc = PermissionService(db, audit_enabled=False)
    svc.clear_cache()
    return asyncio.run(svc.check_permission(user_email=email, permission=permission, allow_admin_bypass=False, **kwargs))


class TestFailClosedBehavior:
    """Permission checks must default to deny on any error."""

    def test_db_exception_returns_deny(self, fail_db):
        """Database exception during permission check → deny."""
        db, role = fail_db
        svc = PermissionService(db, audit_enabled=False)
        svc.clear_cache()
        with patch.object(svc, "_get_user_roles", side_effect=Exception("DB connection lost")):
            result = asyncio.run(svc.check_permission(user_email="admin@test.local", permission="tools.read", allow_admin_bypass=False))
        assert result is False

    def test_admin_check_exception_returns_deny(self, fail_db):
        """Exception during admin check → deny (not bypass)."""
        db, role = fail_db
        svc = PermissionService(db, audit_enabled=False)
        svc.clear_cache()
        with patch.object(svc, "_is_user_admin", side_effect=Exception("Admin check failed")):
            result = asyncio.run(svc.check_permission(user_email="admin@test.local", permission="tools.read", allow_admin_bypass=True))
        assert result is False

    def test_nonexistent_user_returns_deny(self, fail_db):
        """Permission check for non-existent user → deny."""
        db, role = fail_db
        result = _check(db, "nobody@test.local", "tools.read")
        assert result is False

    def test_empty_permission_string_returns_deny(self, fail_db):
        """Empty permission string → deny."""
        db, role = fail_db
        result = _check(db, "admin@test.local", "")
        assert result is False

    def test_expired_role_excluded(self):
        """Role assignment with expires_at in the past → excluded from permissions."""
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        db = Session()

        user = EmailUser(email="expired@test.local", password_hash="$argon2id$v=19$m=65536,t=3,p=1$test", full_name="Expired", is_admin=False, is_active=True)
        db.add(user)
        db.flush()

        role = Role(id=str(uuid.uuid4()), name="temp", description="Temp", scope="global", permissions=["tools.read"], created_by="expired@test.local", is_system_role=False, is_active=True)
        db.add(role)
        db.flush()

        # Expired assignment (1 hour ago)
        ur = UserRole(user_email="expired@test.local", role_id=role.id, scope="global", granted_by="expired@test.local", is_active=True, expires_at=utc_now() - timedelta(hours=1))
        db.add(ur)
        db.commit()

        result = _check(db, "expired@test.local", "tools.read")
        assert result is False

        db.close()
        engine.dispose()

    def test_deactivated_role_excluded(self):
        """Role with is_active=False → excluded from permissions."""
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        db = Session()

        user = EmailUser(email="deact@test.local", password_hash="$argon2id$v=19$m=65536,t=3,p=1$test", full_name="Deact", is_admin=False, is_active=True)
        db.add(user)
        db.flush()

        role = Role(
            id=str(uuid.uuid4()), name="inactive_role", description="Inactive", scope="global", permissions=["tools.read"], created_by="deact@test.local", is_system_role=False, is_active=False
        )
        db.add(role)
        db.flush()

        ur = UserRole(user_email="deact@test.local", role_id=role.id, scope="global", granted_by="deact@test.local", is_active=True)
        db.add(ur)
        db.commit()

        result = _check(db, "deact@test.local", "tools.read")
        assert result is False

        db.close()
        engine.dispose()

    def test_deactivated_user_role_excluded(self):
        """UserRole with is_active=False → excluded from permissions."""
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        db = Session()

        user = EmailUser(email="inactive_ur@test.local", password_hash="$argon2id$v=19$m=65536,t=3,p=1$test", full_name="InactiveUR", is_admin=False, is_active=True)
        db.add(user)
        db.flush()

        role = Role(id=str(uuid.uuid4()), name="good_role", description="Good", scope="global", permissions=["tools.read"], created_by="inactive_ur@test.local", is_system_role=False, is_active=True)
        db.add(role)
        db.flush()

        # Deactivated assignment
        ur = UserRole(user_email="inactive_ur@test.local", role_id=role.id, scope="global", granted_by="inactive_ur@test.local", is_active=False)
        db.add(ur)
        db.commit()

        result = _check(db, "inactive_ur@test.local", "tools.read")
        assert result is False

        db.close()
        engine.dispose()

    def test_role_query_exception_returns_empty_permissions(self, fail_db):
        """Exception during role query → empty permissions set."""
        db, role = fail_db
        svc = PermissionService(db, audit_enabled=False)
        svc.clear_cache()
        with patch.object(svc, "_get_user_roles", side_effect=Exception("Query failed")):
            result = asyncio.run(svc.check_permission(user_email="admin@test.local", permission="tools.read", allow_admin_bypass=False))
        # The outer try/except in check_permission catches the exception and returns False
        assert result is False

    def test_corrupted_cache_doesnt_leak(self, fail_db):
        """Corrupted cache entry should not leak permissions from another user."""
        db, role = fail_db
        svc = PermissionService(db, audit_enabled=False)
        svc.clear_cache()

        # Manually inject a corrupted cache entry for a different user
        svc._permission_cache["hacker@test.local:global"] = {"admin.system_config"}
        svc._cache_timestamps["hacker@test.local:global"] = utc_now()

        # The user "admin@test.local" should NOT see "admin.system_config"
        result = asyncio.run(svc.check_permission(user_email="admin@test.local", permission="admin.system_config", allow_admin_bypass=False))
        assert result is False

    def test_valid_active_role_still_works(self, fail_db):
        """Sanity check: valid active role with permission → granted."""
        db, role = fail_db
        result = _check(db, "admin@test.local", "tools.read")
        assert result is True
