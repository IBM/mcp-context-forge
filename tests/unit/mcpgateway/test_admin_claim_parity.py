# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_admin_claim_parity.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Parity tests for the mapped admin claim in JWT-trust mode (issue #5902).

The mapped admin claim (``jwt_claim_admin``) feeds BOTH admin tracks as one
atomic mapping: ``VirtualPrincipal.is_admin`` and the ``"platform_admin"``
entry in the effective-roles set. No intermediate state exists where one
track says admin and the other denies. ``PermissionService.check_permission``
honors the claims-derived admin without a DB user row. The public-only
``token_teams=[]`` suppression still applies: an admin-claim token with empty
teams gets no bypass.

Parity is measured permission-for-permission across a sample matrix drawn
from the built-in role definitions in ``bootstrap_db.py`` (extracted from
source, never copied): an admin-claim trust token must produce the same
allow/deny verdicts as a DB platform_admin, and a non-admin
``roles=["developer"]`` + ``teams=["t1"]`` trust token must produce exactly
the developer permission set resolved via the server-side roles table.
"""

# Standard
import ast
import inspect
import logging
from datetime import datetime, timezone
from typing import List

# Third-Party
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
import mcpgateway.bootstrap_db as bootstrap_db
from mcpgateway.config import settings
from mcpgateway.db import Base, EmailTeam, EmailUser, Permissions, Role, UserRole
from mcpgateway.services.permission_service import PermissionService
from mcpgateway.utils.trusted_claims import extract_trusted_principal

ISSUER = "https://login.example.com/tenant-1/v2.0"
CALLER_ID = "oid-admin-claim-parity"
ADMIN_EMAIL = "platform.admin@example.com"
DEVELOPER_EMAIL = "dev@example.com"


def _builtin_role_defs() -> List[dict]:
    """Extract the literal ``default_roles`` list from ``bootstrap_db``.

    The test matrix must track the shipped built-in roles. Parsing the
    assignment from source keeps the fixture faithful without copying the
    permission lists.
    """
    tree = ast.parse(inspect.getsource(bootstrap_db.bootstrap_default_roles))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "default_roles" for target in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("default_roles assignment not found in bootstrap_default_roles")


def _mapped_claims(*, teams=None, roles=None, is_admin=None) -> dict:
    """Build a claim dict under the configured ``jwt_claim_*`` names."""
    claims = {}
    if teams is not None:
        claims[settings.jwt_claim_teams] = teams
    if roles is not None:
        claims[settings.jwt_claim_roles] = roles
    if is_admin is not None:
        claims[settings.jwt_claim_admin] = is_admin
    return claims


def _base_payload(**overrides) -> dict:
    """Minimal trust-eligible payload: mapped user_id claim plus jti."""
    payload = {
        settings.jwt_claim_user_id: CALLER_ID,
        "iss": ISSUER,
        "jti": "parity-jti-1",
        "exp": 9999999999,
    }
    payload.update(overrides)
    return payload


def _permission_matrix(db) -> List[str]:
    """Sampled permission matrix drawn from the seeded built-in roles.

    The matrix is the union of every built-in role's effective permissions
    (wildcard excluded) plus admin-level probes that no built-in role grants.
    The negative probes make deny parity observable.
    """
    matrix = set()
    for role in db.query(Role).filter(Role.is_active.is_(True)).all():
        matrix.update(role.get_effective_permissions())
    matrix.discard(Permissions.ALL_PERMISSIONS)
    matrix.update({Permissions.ADMIN_SYSTEM_CONFIG, Permissions.ADMIN_USER_MANAGEMENT, Permissions.ADMIN_SECURITY_AUDIT})
    return sorted(matrix)


def _role_permissions(db, name: str) -> set:
    """Resolve one role name to its permission set via the roles table."""
    role = db.query(Role).filter(Role.name == name, Role.is_active.is_(True)).one()
    return set(role.get_effective_permissions())


@pytest.fixture
def db():
    """In-memory SQLite session seeded with the built-in roles and DB principals.

    Roles: the exact ``default_roles`` set from ``bootstrap_db.py``.
    Principals: a DB platform_admin (``is_admin`` flag plus the global
    platform_admin role assignment) and a DB developer (team-scoped
    developer role on team ``t1``). The trust-mode caller has no DB rows.
    """
    engine = sa.create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()

    now = datetime.now(timezone.utc)
    session.add(
        EmailUser(
            email=ADMIN_EMAIL,
            password_hash="hash",  # pragma: allowlist secret
            full_name="Platform Admin",
            is_admin=True,
            is_active=True,
            email_verified_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    session.add(
        EmailUser(
            email=DEVELOPER_EMAIL,
            password_hash="hash",  # pragma: allowlist secret
            full_name="Developer",
            is_admin=False,
            is_active=True,
            email_verified_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    session.add(EmailTeam(id="t1", name="Team One", slug="team-one", created_by=ADMIN_EMAIL, is_personal=False, visibility="private"))
    session.flush()

    roles = {}
    for role_def in _builtin_role_defs():
        role = Role(
            name=role_def["name"],
            description=role_def["description"],
            scope=role_def["scope"],
            permissions=list(role_def["permissions"]),
            created_by=ADMIN_EMAIL,
            is_system_role=True,
            is_active=True,
        )
        session.add(role)
        roles[(role_def["name"], role_def["scope"])] = role
    session.flush()

    # DB platform_admin: both DB tracks (is_admin flag + global role).
    session.add(UserRole(user_email=ADMIN_EMAIL, role_id=roles[("platform_admin", "global")].id, scope="global", scope_id=None, granted_by=ADMIN_EMAIL))
    # DB developer: team-scoped developer role on team t1.
    session.add(UserRole(user_email=DEVELOPER_EMAIL, role_id=roles[("developer", "team")].id, scope="team", scope_id="t1", granted_by=ADMIN_EMAIL))
    session.commit()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def service(db):
    """PermissionService over the seeded session, auditing off."""
    return PermissionService(db, audit_enabled=False)


class TestAdminClaimParity:
    """Admin-claim trust token vs DB platform_admin, permission-for-permission."""

    @pytest.mark.asyncio
    async def test_admin_claim_populates_both_tracks_atomically(self, db):
        """The mapped admin claim sets is_admin AND the platform_admin role."""
        payload = _base_payload(**_mapped_claims(is_admin=True))
        principal = extract_trusted_principal(payload, settings, db)
        assert principal.is_admin is True
        assert "platform_admin" in principal.roles

    @pytest.mark.asyncio
    async def test_admin_claim_parity_with_db_platform_admin(self, db, service):
        """Same allow/deny verdicts across the sample matrix.

        The trust caller has no DB user row, so every granted verdict on the
        trust side proves the claims-derived admin is honored directly.
        """
        payload = _base_payload(**_mapped_claims(is_admin=True))
        principal = extract_trusted_principal(payload, settings, db)
        assert db.query(EmailUser).filter(EmailUser.email == principal.user_id).first() is None

        matrix = _permission_matrix(db)
        assert matrix  # the matrix must not be empty
        for permission in matrix:
            db_verdict = await service.check_permission(user_email=ADMIN_EMAIL, permission=permission)
            trust_verdict = await service.check_permission(
                user_email=principal.user_id,
                permission=permission,
                token_is_admin=principal.is_admin,
                token_roles=principal.roles,
            )
            assert trust_verdict == db_verdict, f"verdict mismatch on {permission}"


class TestNonAdminClaimParity:
    """Non-admin trust token: roles=["developer"] + teams=["t1"]."""

    @pytest.mark.asyncio
    async def test_developer_claim_yields_exactly_developer_permissions(self, db, service):
        """The trust token resolves exactly the developer permission set."""
        payload = _base_payload(**_mapped_claims(teams=["t1"], roles=["developer"]))
        principal = extract_trusted_principal(payload, settings, db)
        assert principal.is_admin is False
        assert principal.roles == ["developer"]

        developer_permissions = _role_permissions(db, "developer")
        trust_permissions = await service.get_user_permissions(principal.user_id, team_id="t1", token_teams=["t1"], token_roles=principal.roles)
        assert trust_permissions == developer_permissions
        assert trust_permissions  # non-admin trust tokens are not left with empty permissions
        assert Permissions.ALL_PERMISSIONS not in trust_permissions

    @pytest.mark.asyncio
    async def test_developer_claim_parity_with_db_developer(self, db, service):
        """Same allow/deny verdicts as a DB-backed developer on team t1."""
        payload = _base_payload(**_mapped_claims(teams=["t1"], roles=["developer"]))
        principal = extract_trusted_principal(payload, settings, db)

        for permission in _permission_matrix(db):
            db_verdict = await service.check_permission(user_email=DEVELOPER_EMAIL, permission=permission, team_id="t1", token_teams=["t1"])
            trust_verdict = await service.check_permission(
                user_email=principal.user_id,
                permission=permission,
                team_id="t1",
                token_teams=["t1"],
                token_is_admin=principal.is_admin,
                token_roles=principal.roles,
            )
            assert trust_verdict == db_verdict, f"verdict mismatch on {permission}"

    @pytest.mark.asyncio
    async def test_developer_claim_gets_no_admin_bypass(self, db, service):
        """A non-admin trust token gets NO bypass for admin-only permissions."""
        payload = _base_payload(**_mapped_claims(teams=["t1"], roles=["developer"]))
        principal = extract_trusted_principal(payload, settings, db)
        granted = await service.check_permission(
            user_email=principal.user_id,
            permission=Permissions.ADMIN_USER_MANAGEMENT,
            team_id="t1",
            token_teams=["t1"],
            token_is_admin=principal.is_admin,
            token_roles=principal.roles,
        )
        assert granted is False


class TestAdminClaimDeny:
    """Deny paths: false/absent admin claim, public-only suppression, unknown roles."""

    @pytest.mark.asyncio
    async def test_is_admin_false_claim_denies_admin_attempt(self, db, service):
        """is_admin=false claim + admin attempt -> denied (403 verdict)."""
        payload = _base_payload(**_mapped_claims(is_admin=False))
        principal = extract_trusted_principal(payload, settings, db)
        assert principal.is_admin is False
        assert "platform_admin" not in principal.roles
        granted = await service.check_permission(
            user_email=principal.user_id,
            permission=Permissions.ADMIN_USER_MANAGEMENT,
            token_is_admin=principal.is_admin,
            token_roles=principal.roles,
        )
        assert granted is False

    @pytest.mark.asyncio
    async def test_is_admin_absent_denies_admin_attempt(self, db, service):
        """Absent admin claim + admin attempt -> denied (403 verdict)."""
        payload = _base_payload()
        principal = extract_trusted_principal(payload, settings, db)
        assert principal.is_admin is False
        assert "platform_admin" not in principal.roles
        granted = await service.check_permission(
            user_email=principal.user_id,
            permission=Permissions.ADMIN_USER_MANAGEMENT,
            token_is_admin=principal.is_admin,
            token_roles=principal.roles,
        )
        assert granted is False

    @pytest.mark.asyncio
    async def test_public_only_teams_suppress_claims_admin_bypass(self, db, service):
        """token_teams=[] + admin claim -> no bypass, no claims role permissions."""
        payload = _base_payload(**_mapped_claims(teams=[], is_admin=True))
        principal = extract_trusted_principal(payload, settings, db)
        assert principal.is_admin is True
        assert principal.teams == []

        granted = await service.check_permission(
            user_email=principal.user_id,
            permission=Permissions.ADMIN_USER_MANAGEMENT,
            token_teams=principal.teams,
            token_is_admin=principal.is_admin,
            token_roles=principal.roles,
        )
        assert granted is False

        permissions = await service.get_user_permissions(principal.user_id, token_teams=principal.teams, token_roles=principal.roles)
        assert Permissions.ALL_PERMISSIONS not in permissions
        assert Permissions.ADMIN_USER_MANAGEMENT not in permissions

    @pytest.mark.asyncio
    async def test_unknown_role_ignored_with_warning(self, db, service, caplog):
        """Unknown role name: WARNING log, no permissions granted from it."""
        payload = _base_payload(**_mapped_claims(teams=["t1"], roles=["developer", "ghost-role"]))
        with caplog.at_level(logging.WARNING, logger="mcpgateway.utils.trusted_claims"):
            principal = extract_trusted_principal(payload, settings, db)
        assert principal.roles == ["developer"]
        assert any("ghost-role" in record.message for record in caplog.records)

        permissions = await service.get_user_permissions(principal.user_id, team_id="t1", token_teams=["t1"], token_roles=principal.roles)
        assert permissions == _role_permissions(db, "developer")
