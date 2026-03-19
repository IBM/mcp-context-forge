# -*- coding: utf-8 -*-
# Copyright (c) 2025 ContextForge Contributors.
# SPDX-License-Identifier: Apache-2.0

"""Cross-Team Isolation Tests for RBAC System.

Verifies that team-scoped roles are isolated to their assigned team,
and that personal team roles are excluded from check_any_team aggregation.
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
from mcpgateway.db import Base, EmailTeam, EmailUser, Role, UserRole
from mcpgateway.services.permission_service import PermissionService

TEAM_PERMISSIONS = [
    "tools.read",
    "tools.create",
    "tools.execute",
    "resources.read",
    "servers.read",
    "gateways.read",
]


@pytest.fixture(scope="module")
def isolation_db():
    """Create in-memory SQLite DB with two teams and users for isolation tests."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    # Create admin user (FK target)
    admin = EmailUser(email="admin@test.local", password_hash="$argon2id$v=19$m=65536,t=3,p=1$test", full_name="Admin", is_admin=False, is_active=True)
    db.add(admin)
    db.flush()

    # Create two teams
    team_a_id = str(uuid.uuid4())
    team_b_id = str(uuid.uuid4())
    personal_team_id = str(uuid.uuid4())

    team_a = EmailTeam(id=team_a_id, name="Team A", slug="team-a", created_by="admin@test.local", is_personal=False)
    team_b = EmailTeam(id=team_b_id, name="Team B", slug="team-b", created_by="admin@test.local", is_personal=False)
    personal_team = EmailTeam(id=personal_team_id, name="Personal Team", slug="personal-team", created_by="admin@test.local", is_personal=True)
    db.add_all([team_a, team_b, personal_team])
    db.flush()

    # Create developer role (team-scoped)
    dev_role = Role(id=str(uuid.uuid4()), name="developer", description="Developer", scope="team", permissions=TEAM_PERMISSIONS, created_by="admin@test.local", is_system_role=True, is_active=True)
    db.add(dev_role)

    # Create team_admin role (for personal team test)
    ta_role = Role(
        id=str(uuid.uuid4()),
        name="team_admin",
        description="Team Admin",
        scope="team",
        permissions=TEAM_PERMISSIONS + ["teams.read", "teams.update", "teams.delete", "teams.manage_members", "servers.create", "tools.create"],
        created_by="admin@test.local",
        is_system_role=True,
        is_active=True,
    )
    db.add(ta_role)

    # Create viewer role (team-scoped)
    viewer_role = Role(
        id=str(uuid.uuid4()),
        name="viewer",
        description="Viewer",
        scope="team",
        permissions=["tools.read", "resources.read", "servers.read", "gateways.read", "admin.dashboard"],
        created_by="admin@test.local",
        is_system_role=True,
        is_active=True,
    )
    db.add(viewer_role)

    # Create global role for global-scope test
    global_role = Role(
        id=str(uuid.uuid4()),
        name="global_dev",
        description="Global Dev",
        scope="global",
        permissions=["tools.read", "tools.create"],
        created_by="admin@test.local",
        is_system_role=False,
        is_active=True,
    )
    db.add(global_role)
    db.flush()

    # Create test users
    # User with developer role on Team A only
    user_a = EmailUser(email="dev-a@test.local", password_hash="$argon2id$v=19$m=65536,t=3,p=1$test", full_name="Dev A", is_admin=False, is_active=True)
    db.add(user_a)
    db.flush()
    ur_a = UserRole(user_email="dev-a@test.local", role_id=dev_role.id, scope="team", scope_id=team_a_id, granted_by="admin@test.local", is_active=True)
    db.add(ur_a)

    # User with viewer role on Team A and personal team_admin
    user_viewer = EmailUser(email="viewer@test.local", password_hash="$argon2id$v=19$m=65536,t=3,p=1$test", full_name="Viewer", is_admin=False, is_active=True)
    db.add(user_viewer)
    db.flush()
    ur_viewer = UserRole(user_email="viewer@test.local", role_id=viewer_role.id, scope="team", scope_id=team_a_id, granted_by="admin@test.local", is_active=True)
    db.add(ur_viewer)
    # Personal team admin role (should be excluded from check_any_team)
    ur_personal = UserRole(user_email="viewer@test.local", role_id=ta_role.id, scope="team", scope_id=personal_team_id, granted_by="admin@test.local", is_active=True)
    db.add(ur_personal)

    # User with global role
    user_global = EmailUser(email="global@test.local", password_hash="$argon2id$v=19$m=65536,t=3,p=1$test", full_name="Global", is_admin=False, is_active=True)
    db.add(user_global)
    db.flush()
    ur_global = UserRole(user_email="global@test.local", role_id=global_role.id, scope="global", scope_id=None, granted_by="admin@test.local", is_active=True)
    db.add(ur_global)

    # User with no roles
    user_norole = EmailUser(email="norole@test.local", password_hash="$argon2id$v=19$m=65536,t=3,p=1$test", full_name="NoRole", is_admin=False, is_active=True)
    db.add(user_norole)

    db.commit()

    yield db, team_a_id, team_b_id, personal_team_id
    db.close()
    engine.dispose()


def _check(db, email, permission, team_id=None, check_any_team=False):
    svc = PermissionService(db, audit_enabled=False)
    svc.clear_cache()
    return asyncio.run(svc.check_permission(user_email=email, permission=permission, team_id=team_id, allow_admin_bypass=False, check_any_team=check_any_team))


# ---------------------------------------------------------------------------
# D5.1: Cross-Team Isolation
# ---------------------------------------------------------------------------


class TestCrossTeamIsolation:
    """Team A role should NOT grant access to Team B resources."""

    @pytest.mark.parametrize("permission", TEAM_PERMISSIONS)
    def test_team_a_role_allowed_on_team_a(self, isolation_db, permission):
        db, team_a_id, team_b_id, _ = isolation_db
        result = _check(db, "dev-a@test.local", permission, team_id=team_a_id)
        assert result is True, f"developer on Team A should have {permission} on Team A"

    @pytest.mark.parametrize("permission", TEAM_PERMISSIONS)
    def test_team_a_role_denied_on_team_b(self, isolation_db, permission):
        db, team_a_id, team_b_id, _ = isolation_db
        result = _check(db, "dev-a@test.local", permission, team_id=team_b_id)
        assert result is False, f"developer on Team A should NOT have {permission} on Team B"

    def test_global_role_allowed_on_any_team(self, isolation_db):
        """Global role should grant access regardless of team context."""
        db, team_a_id, team_b_id, _ = isolation_db
        assert _check(db, "global@test.local", "tools.read", team_id=team_a_id) is True
        assert _check(db, "global@test.local", "tools.read", team_id=team_b_id) is True
        assert _check(db, "global@test.local", "tools.read") is True

    def test_no_roles_denied(self, isolation_db):
        """User with no roles should be denied."""
        db, team_a_id, team_b_id, _ = isolation_db
        assert _check(db, "norole@test.local", "tools.read", team_id=team_a_id) is False
        assert _check(db, "norole@test.local", "tools.create", team_id=team_b_id) is False


# ---------------------------------------------------------------------------
# D5.2: Personal Team Exclusion (#2900 regression)
# ---------------------------------------------------------------------------


class TestPersonalTeamExclusion:
    """Personal team admin role should be excluded from check_any_team aggregation."""

    def test_personal_team_admin_excluded_from_any_team_check(self, isolation_db):
        """Viewer with personal team_admin should NOT get tools.create via check_any_team.

        Regression test for #2900: personal team roles should be excluded from
        check_any_team aggregation to prevent privilege escalation.
        """
        db, team_a_id, team_b_id, personal_team_id = isolation_db
        # With check_any_team=True, personal team roles should be excluded
        result = _check(db, "viewer@test.local", "tools.create", check_any_team=True)
        assert result is False, "Viewer should NOT get tools.create via personal team_admin role in check_any_team"

    def test_viewer_with_personal_team_cannot_create(self, isolation_db):
        """Viewer should not get mutation permissions even with personal team_admin."""
        db, team_a_id, team_b_id, personal_team_id = isolation_db
        # Directly on team A — viewer role only has read permissions
        result = _check(db, "viewer@test.local", "tools.create", team_id=team_a_id)
        assert result is False, "Viewer should NOT have tools.create on Team A"

    def test_personal_team_admin_works_on_personal_team(self, isolation_db):
        """Personal team_admin role should still work when checking the personal team directly."""
        db, team_a_id, team_b_id, personal_team_id = isolation_db
        result = _check(db, "viewer@test.local", "tools.create", team_id=personal_team_id)
        assert result is True, "Personal team_admin should have tools.create on personal team"

    def test_viewer_read_works_with_check_any_team(self, isolation_db):
        """Viewer's read permissions should still work with check_any_team."""
        db, team_a_id, team_b_id, personal_team_id = isolation_db
        result = _check(db, "viewer@test.local", "tools.read", check_any_team=True)
        assert result is True, "Viewer should have tools.read via check_any_team"
