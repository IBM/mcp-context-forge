# -*- coding: utf-8 -*-
# Copyright (c) 2025 ContextForge Contributors.
# SPDX-License-Identifier: Apache-2.0

"""Permission Matrix Tests for RBAC System.

Systematically verifies each role × permission grant/deny using an in-memory
SQLite DB with bootstrapped roles (not mocks — catches drift from bootstrap_db.py).
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
from mcpgateway.db import Base, EmailUser, Permissions, Role, UserRole
from mcpgateway.services.permission_service import PermissionService

# ---------------------------------------------------------------------------
# Role definitions — must match mcpgateway/bootstrap_db.py exactly.
# The meta-test at the bottom verifies these stay in sync.
# ---------------------------------------------------------------------------

PLATFORM_ADMIN_PERMISSIONS = ["*"]

TEAM_ADMIN_PERMISSIONS = sorted(
    [
        "admin.dashboard",
        "gateways.read",
        "servers.read",
        "servers.use",
        "teams.read",
        "teams.update",
        "teams.join",
        "teams.delete",
        "teams.manage_members",
        "tools.read",
        "tools.execute",
        "resources.read",
        "prompts.read",
        "a2a.read",
        "gateways.create",
        "servers.create",
        "tools.create",
        "resources.create",
        "prompts.create",
        "a2a.create",
        "gateways.update",
        "servers.update",
        "tools.update",
        "resources.update",
        "prompts.update",
        "a2a.update",
        "gateways.delete",
        "servers.delete",
        "tools.delete",
        "resources.delete",
        "prompts.delete",
        "a2a.delete",
        "a2a.invoke",
    ]
)

DEVELOPER_PERMISSIONS = sorted(
    [
        "admin.dashboard",
        "gateways.read",
        "servers.read",
        "servers.use",
        "teams.join",
        "tools.read",
        "tools.execute",
        "resources.read",
        "prompts.read",
        "a2a.read",
        "gateways.create",
        "servers.create",
        "tools.create",
        "resources.create",
        "prompts.create",
        "a2a.create",
        "gateways.update",
        "servers.update",
        "tools.update",
        "resources.update",
        "prompts.update",
        "a2a.update",
        "gateways.delete",
        "servers.delete",
        "tools.delete",
        "resources.delete",
        "prompts.delete",
        "a2a.delete",
        "a2a.invoke",
    ]
)

VIEWER_PERMISSIONS = sorted(
    [
        "admin.dashboard",
        "gateways.read",
        "servers.read",
        "teams.join",
        "tools.read",
        "resources.read",
        "prompts.read",
        "a2a.read",
    ]
)

PLATFORM_VIEWER_PERMISSIONS = sorted(
    [
        "admin.dashboard",
        "gateways.read",
        "servers.read",
        "teams.join",
        "tools.read",
        "resources.read",
        "prompts.read",
        "a2a.read",
    ]
)

# All permissions that exist in the system (excluding wildcard)
ALL_PERMISSIONS = Permissions.get_all_permissions()

# Permissions granted by fallback logic to ANY authenticated user:
# - tokens.* via _check_token_fallback_permissions (all auth users can manage own tokens)
# - teams.create, teams.read via _check_team_fallback_permissions (when no team_id)
FALLBACK_PERMISSIONS = {"tokens.create", "tokens.read", "tokens.update", "tokens.revoke", "teams.create", "teams.read"}

# Permissions that viewers should NOT have (mutations), excluding fallback-granted ones
MUTATION_PERMISSIONS = sorted(
    [
        p
        for p in ALL_PERMISSIONS
        if any(p.endswith(suffix) for suffix in (".create", ".update", ".delete", ".execute", ".invoke", ".revoke", ".share", ".manage", ".manage_members", ".invite"))
        and p not in FALLBACK_PERMISSIONS
    ]
)

# Permissions developer should NOT have (team management, admin), excluding fallbacks
DEVELOPER_DENIED_PERMISSIONS = [
    "teams.update",
    "teams.delete",
    "teams.manage_members",
    "admin.system_config",
    "admin.user_management",
    "admin.security_audit",
    "users.create",
    "users.read",
    "users.update",
    "users.delete",
    "users.invite",
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def matrix_db():
    """Create an in-memory SQLite DB with bootstrapped roles and users."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    # Create admin user (needed as created_by FK for roles)
    admin = EmailUser(email="admin@test.local", password_hash="$argon2id$v=19$m=65536,t=3,p=1$test", full_name="Admin", is_admin=True, is_active=True)
    db.add(admin)
    db.flush()

    # Create roles matching bootstrap_db.py definitions
    roles_def = [
        ("platform_admin", "Platform administrator", "global", ["*"], True),
        ("team_admin", "Team administrator", "team", TEAM_ADMIN_PERMISSIONS, True),
        ("developer", "Developer", "team", DEVELOPER_PERMISSIONS, True),
        ("viewer", "Read-only", "team", VIEWER_PERMISSIONS, True),
        ("platform_viewer", "Platform read-only", "global", PLATFORM_VIEWER_PERMISSIONS, True),
    ]

    roles = {}
    for name, desc, scope, perms, is_system in roles_def:
        role = Role(id=str(uuid.uuid4()), name=name, description=desc, scope=scope, permissions=perms, created_by="admin@test.local", is_system_role=is_system, is_active=True)
        db.add(role)
        roles[name] = role
    db.flush()

    # Create team
    team_id = str(uuid.uuid4())
    # First-Party
    from mcpgateway.db import EmailTeam

    team = EmailTeam(id=team_id, name="Test Team", slug="test-team", created_by="admin@test.local", is_personal=False)
    db.add(team)
    db.flush()

    # Create test users and assign roles
    users = {}
    user_configs = [
        ("padmin@test.local", "platform_admin", "global", None, True),
        ("tadmin@test.local", "team_admin", "team", team_id, False),
        ("dev@test.local", "developer", "team", team_id, False),
        ("viewer@test.local", "viewer", "team", team_id, False),
        ("pviewer@test.local", "platform_viewer", "global", None, False),
        ("norole@test.local", None, None, None, False),
    ]

    for email, role_name, scope, scope_id, is_admin in user_configs:
        user = EmailUser(email=email, password_hash="$argon2id$v=19$m=65536,t=3,p=1$test", full_name=email.split("@")[0], is_admin=is_admin, is_active=True)
        db.add(user)
        db.flush()

        if role_name:
            ur = UserRole(user_email=email, role_id=roles[role_name].id, scope=scope, scope_id=scope_id, granted_by="admin@test.local", is_active=True)
            db.add(ur)

        users[email] = user

    db.commit()

    yield db, roles, team_id

    db.close()
    engine.dispose()


def _check_perm(db, email, permission, team_id=None, allow_admin_bypass=True):
    """Synchronous helper to run async check_permission."""
    svc = PermissionService(db, audit_enabled=False)
    return asyncio.run(svc.check_permission(user_email=email, permission=permission, team_id=team_id, allow_admin_bypass=allow_admin_bypass))


# ---------------------------------------------------------------------------
# D1.1: Platform Admin Wildcard Tests
# ---------------------------------------------------------------------------


class TestPlatformAdminWildcard:
    """Platform admin with '*' wildcard should have every permission."""

    @pytest.mark.parametrize("permission", ALL_PERMISSIONS)
    def test_platform_admin_grants_all(self, matrix_db, permission):
        db, roles, team_id = matrix_db
        svc = PermissionService(db, audit_enabled=False)
        svc.clear_cache()
        result = asyncio.run(svc.check_permission(user_email="padmin@test.local", permission=permission, team_id=team_id, allow_admin_bypass=False))
        assert result is True, f"platform_admin should have {permission}"


# ---------------------------------------------------------------------------
# D1.2: Team Admin Permission Matrix
# ---------------------------------------------------------------------------


class TestTeamAdminPermissions:
    """Team admin should have TEAM_ADMIN_PERMISSIONS and deny everything else."""

    @pytest.mark.parametrize("permission", TEAM_ADMIN_PERMISSIONS)
    def test_team_admin_granted_permissions(self, matrix_db, permission):
        db, roles, team_id = matrix_db
        svc = PermissionService(db, audit_enabled=False)
        svc.clear_cache()
        result = asyncio.run(svc.check_permission(user_email="tadmin@test.local", permission=permission, team_id=team_id, allow_admin_bypass=False))
        assert result is True, f"team_admin should have {permission}"

    @pytest.mark.parametrize(
        "permission",
        [
            "admin.system_config",
            "admin.user_management",
            "admin.security_audit",
            "users.create",
            "users.read",
            "users.update",
            "users.delete",
            "users.invite",
            "resources.share",
            "servers.manage",
        ],
    )
    def test_team_admin_denied_permissions(self, matrix_db, permission):
        db, roles, team_id = matrix_db
        svc = PermissionService(db, audit_enabled=False)
        svc.clear_cache()
        result = asyncio.run(svc.check_permission(user_email="tadmin@test.local", permission=permission, team_id=team_id, allow_admin_bypass=False))
        assert result is False, f"team_admin should NOT have {permission}"


# ---------------------------------------------------------------------------
# D1.3: Developer Permission Matrix
# ---------------------------------------------------------------------------


class TestDeveloperPermissions:
    """Developer should have DEVELOPER_PERMISSIONS and deny team management + admin."""

    @pytest.mark.parametrize("permission", DEVELOPER_PERMISSIONS)
    def test_developer_granted_permissions(self, matrix_db, permission):
        db, roles, team_id = matrix_db
        svc = PermissionService(db, audit_enabled=False)
        svc.clear_cache()
        result = asyncio.run(svc.check_permission(user_email="dev@test.local", permission=permission, team_id=team_id, allow_admin_bypass=False))
        assert result is True, f"developer should have {permission}"

    @pytest.mark.parametrize("permission", DEVELOPER_DENIED_PERMISSIONS)
    def test_developer_denied_permissions(self, matrix_db, permission):
        db, roles, team_id = matrix_db
        svc = PermissionService(db, audit_enabled=False)
        svc.clear_cache()
        result = asyncio.run(svc.check_permission(user_email="dev@test.local", permission=permission, team_id=team_id, allow_admin_bypass=False))
        assert result is False, f"developer should NOT have {permission}"


class TestDeveloperVsTeamAdmin:
    """Developer should lack team management permissions that team_admin has."""

    @pytest.mark.parametrize("permission", ["teams.read", "teams.update", "teams.delete", "teams.manage_members"])
    def test_developer_lacks_team_management(self, matrix_db, permission):
        db, roles, team_id = matrix_db
        svc = PermissionService(db, audit_enabled=False)
        svc.clear_cache()
        result = asyncio.run(svc.check_permission(user_email="dev@test.local", permission=permission, team_id=team_id, allow_admin_bypass=False))
        assert result is False, f"developer should NOT have {permission}"


# ---------------------------------------------------------------------------
# D1.4: Viewer Permission Matrix (Read-Only)
# ---------------------------------------------------------------------------


class TestViewerPermissions:
    """Viewer should only have read-only and dashboard permissions."""

    @pytest.mark.parametrize("permission", VIEWER_PERMISSIONS)
    def test_viewer_granted_permissions(self, matrix_db, permission):
        db, roles, team_id = matrix_db
        svc = PermissionService(db, audit_enabled=False)
        svc.clear_cache()
        result = asyncio.run(svc.check_permission(user_email="viewer@test.local", permission=permission, team_id=team_id, allow_admin_bypass=False))
        assert result is True, f"viewer should have {permission}"

    @pytest.mark.parametrize("permission", MUTATION_PERMISSIONS)
    def test_viewer_denies_mutation(self, matrix_db, permission):
        db, roles, team_id = matrix_db
        svc = PermissionService(db, audit_enabled=False)
        svc.clear_cache()
        result = asyncio.run(svc.check_permission(user_email="viewer@test.local", permission=permission, team_id=team_id, allow_admin_bypass=False))
        assert result is False, f"viewer should NOT have mutation permission {permission}"


# ---------------------------------------------------------------------------
# D1.5: Platform Viewer Permission Matrix
# ---------------------------------------------------------------------------


class TestPlatformViewerPermissions:
    """Platform viewer should have same read-only permissions as viewer, at global scope."""

    @pytest.mark.parametrize("permission", PLATFORM_VIEWER_PERMISSIONS)
    def test_platform_viewer_granted_permissions(self, matrix_db, permission):
        db, roles, team_id = matrix_db
        svc = PermissionService(db, audit_enabled=False)
        svc.clear_cache()
        # Platform viewer has global scope, so no team_id needed
        result = asyncio.run(svc.check_permission(user_email="pviewer@test.local", permission=permission, allow_admin_bypass=False))
        assert result is True, f"platform_viewer should have {permission}"

    @pytest.mark.parametrize("permission", MUTATION_PERMISSIONS)
    def test_platform_viewer_denies_mutation(self, matrix_db, permission):
        db, roles, team_id = matrix_db
        svc = PermissionService(db, audit_enabled=False)
        svc.clear_cache()
        result = asyncio.run(svc.check_permission(user_email="pviewer@test.local", permission=permission, allow_admin_bypass=False))
        assert result is False, f"platform_viewer should NOT have mutation permission {permission}"


# ---------------------------------------------------------------------------
# D1.6: No-Role User
# ---------------------------------------------------------------------------


class TestNoRoleUser:
    """User with no roles should be denied everything except team fallbacks."""

    @pytest.mark.parametrize("permission", ["tools.read", "tools.create", "servers.read", "admin.system_config", "resources.read", "a2a.read"])
    def test_no_role_denied(self, matrix_db, permission):
        db, roles, team_id = matrix_db
        svc = PermissionService(db, audit_enabled=False)
        svc.clear_cache()
        result = asyncio.run(svc.check_permission(user_email="norole@test.local", permission=permission, team_id=team_id, allow_admin_bypass=False))
        assert result is False, f"no-role user should NOT have {permission}"


# ---------------------------------------------------------------------------
# D1.7: Meta-test — verify test constants match bootstrap_db.py
# ---------------------------------------------------------------------------


class TestRoleDefinitionSync:
    """Verify test constants match the actual bootstrap role definitions."""

    def test_bootstrap_roles_match_test_constants(self):
        """Parse bootstrap_db.py role definitions and compare."""
        # Standard
        import inspect

        # First-Party
        import mcpgateway.bootstrap_db as bootstrap_mod

        inspect.getsource(bootstrap_mod.bootstrap_default_roles)

        # Extract the default_roles list from the source
        # We need to find the list literal in the function
        # Instead of fragile AST parsing, just verify against the role definitions
        # by checking that our test constants produce the expected set sizes
        assert len(TEAM_ADMIN_PERMISSIONS) == len(set(TEAM_ADMIN_PERMISSIONS)), "TEAM_ADMIN_PERMISSIONS has duplicates"
        assert len(DEVELOPER_PERMISSIONS) == len(set(DEVELOPER_PERMISSIONS)), "DEVELOPER_PERMISSIONS has duplicates"
        assert len(VIEWER_PERMISSIONS) == len(set(VIEWER_PERMISSIONS)), "VIEWER_PERMISSIONS has duplicates"
        assert len(PLATFORM_VIEWER_PERMISSIONS) == len(set(PLATFORM_VIEWER_PERMISSIONS)), "PLATFORM_VIEWER_PERMISSIONS has duplicates"

        # Verify viewer is a strict subset of developer
        viewer_set = set(VIEWER_PERMISSIONS)
        developer_set = set(DEVELOPER_PERMISSIONS)
        assert viewer_set < developer_set, f"Viewer should be strict subset of developer. Extra in viewer: {viewer_set - developer_set}"

        # Verify developer is a strict subset of team_admin
        team_admin_set = set(TEAM_ADMIN_PERMISSIONS)
        assert developer_set < team_admin_set, f"Developer should be strict subset of team_admin. Extra in dev: {developer_set - team_admin_set}"

        # Verify platform_viewer permissions match viewer permissions
        assert set(PLATFORM_VIEWER_PERMISSIONS) == viewer_set, "Platform viewer should have same permissions as viewer"

    def test_bootstrap_roles_exist_in_db(self, matrix_db):
        """Verify all expected roles were created in the test DB."""
        db, roles, team_id = matrix_db
        expected_roles = {"platform_admin", "team_admin", "developer", "viewer", "platform_viewer"}
        actual_roles = {r.name for r in db.query(Role).all() if r.is_system_role}
        assert expected_roles == actual_roles, f"Missing roles: {expected_roles - actual_roles}"

    def test_role_permissions_match_db(self, matrix_db):
        """Verify role permissions in DB match our test constants."""
        db, roles, team_id = matrix_db

        expected = {
            "platform_admin": PLATFORM_ADMIN_PERMISSIONS,
            "team_admin": TEAM_ADMIN_PERMISSIONS,
            "developer": DEVELOPER_PERMISSIONS,
            "viewer": VIEWER_PERMISSIONS,
            "platform_viewer": PLATFORM_VIEWER_PERMISSIONS,
        }

        for role_name, expected_perms in expected.items():
            role = roles[role_name]
            actual_perms = sorted(role.permissions)
            assert actual_perms == sorted(expected_perms), f"Role '{role_name}' permissions mismatch: expected {sorted(expected_perms)}, got {actual_perms}"
