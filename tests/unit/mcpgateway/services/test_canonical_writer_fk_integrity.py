# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_canonical_writer_fk_integrity.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

FK-integrity contract for the canonical writers (#5893, F7).

``UserRole.user_email`` and ``EmailTeamMember.user_email`` hold foreign keys
to ``email_users.email``. When an SSO-provisioned user's canonical
``EmailUser.user_id`` diverges from their e-mail, the writer sites must keep
the FK columns e-mail-valued (always FK-valid) and store the canonical ID in
the additive ``user_id`` columns. These tests run on SQLite with
``PRAGMA foreign_keys=ON`` so a violation cannot slip through the way it does
on the stack's default non-enforcing test database.
"""

# Standard
import uuid
from contextlib import contextmanager
from unittest.mock import patch

# Third-Party
import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.auth import resolve_session_teams
from mcpgateway.db import Base, EmailTeam, EmailTeamMember, EmailUser, Role, UserRole
from mcpgateway.services.role_service import RoleService
from mcpgateway.services.team_management_service import TeamManagementService

DIVERGED_EMAIL = "alice@example.com"
DIVERGED_USER_ID = "entra-sub-123"


@pytest.fixture
def fk_db():
    """In-memory SQLite session with FK enforcement enabled."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _seed_diverged_user(db):
    """Insert a user whose canonical user_id diverges from their e-mail."""
    db.add(EmailUser(email=DIVERGED_EMAIL, user_id=DIVERGED_USER_ID, password_hash=None, is_active=True))
    db.commit()


@contextmanager
def _pinned_session(db):
    """Yield the fixture session where auth.py would open a fresh one."""
    yield db


def _seed_team_with_member(db, *, email, user_id):
    """Insert a non-personal team and an active membership row for the user."""
    suffix = uuid.uuid4().hex[:8]
    team = EmailTeam(name=f"Team {suffix}", slug=f"team-{suffix}", created_by=email, is_personal=False, visibility="private", is_active=True)
    db.add(team)
    db.commit()
    db.refresh(team)
    db.add(EmailTeamMember(team_id=team.id, user_email=email, user_id=user_id, role="member", invited_by=email, is_active=True))
    db.commit()
    return team


def test_fk_fixture_enforces_foreign_keys(fk_db):
    """Guard: the fixture must actually reject an FK-violating UserRole row.

    Without enforcement the dual-write assertions below could pass vacuously
    against a schema that never checks the FK.
    """
    _seed_diverged_user(fk_db)
    fk_db.add(Role(id=str(uuid.uuid4()), name=f"guard-role-{uuid.uuid4().hex[:8]}", scope="global", permissions=[], created_by=DIVERGED_EMAIL, is_system_role=False, is_active=True))
    fk_db.commit()
    role = fk_db.query(Role).one()
    fk_db.add(UserRole(user_email="ghost@example.com", role_id=role.id, scope="global", granted_by=DIVERGED_EMAIL))
    with pytest.raises(IntegrityError):
        fk_db.flush()
    fk_db.rollback()


@pytest.mark.asyncio
async def test_role_writer_keeps_fk_valid_and_stores_canonical_id(fk_db):
    """assign_role_to_user: user_email stays the FK-valid e-mail; user_id holds the canonical ID."""
    _seed_diverged_user(fk_db)
    role = Role(id=str(uuid.uuid4()), name=f"developer-{uuid.uuid4().hex[:8]}", scope="global", permissions=["tools.read"], created_by=DIVERGED_EMAIL, is_system_role=False, is_active=True)
    fk_db.add(role)
    fk_db.commit()

    svc = RoleService(db=fk_db)
    await svc.assign_role_to_user(user_email=DIVERGED_EMAIL, role_id=role.id, scope="global", scope_id=None, granted_by=DIVERGED_EMAIL)

    row = fk_db.execute(select(UserRole)).scalar_one()
    assert row.user_email == DIVERGED_EMAIL  # FK-valid (F7 contract)
    assert row.user_id == DIVERGED_USER_ID  # canonical preserved (#5884 intent)


@pytest.mark.asyncio
async def test_membership_writer_keeps_fk_valid_and_stores_canonical_id(fk_db):
    """add_member_to_team: user_email stays the FK-valid e-mail; user_id holds the canonical ID."""
    _seed_diverged_user(fk_db)
    suffix = uuid.uuid4().hex[:8]
    team = EmailTeam(name=f"Team {suffix}", slug=f"team-{suffix}", created_by=DIVERGED_EMAIL, is_personal=False, visibility="private", is_active=True)
    fk_db.add(team)
    fk_db.commit()
    fk_db.refresh(team)

    svc = TeamManagementService(fk_db)
    await svc.add_member_to_team(team_id=team.id, user_email=DIVERGED_EMAIL, role="member", invited_by=DIVERGED_EMAIL)

    row = fk_db.execute(select(EmailTeamMember)).scalar_one()
    assert row.user_email == DIVERGED_EMAIL  # FK-valid (F7 contract)
    assert row.user_id == DIVERGED_USER_ID  # canonical preserved (#5884 intent)


@pytest.mark.asyncio
async def test_session_teams_resolve_for_diverged_user(fk_db):
    """resolve_session_teams matches a dual-written membership row via either identity key."""
    _seed_diverged_user(fk_db)
    team = _seed_team_with_member(fk_db, email=DIVERGED_EMAIL, user_id=DIVERGED_USER_ID)

    payload = {"sub": DIVERGED_USER_ID, "token_use": "session"}
    with patch("mcpgateway.auth.fresh_db_session", lambda: _pinned_session(fk_db)):
        teams = await resolve_session_teams(payload, DIVERGED_EMAIL, {"is_admin": False})

    assert teams == [team.id]


@pytest.mark.asyncio
async def test_session_teams_resolve_for_legacy_user(fk_db):
    """Legacy user (user_id == e-mail in both columns) resolves unchanged."""
    legacy_email = "legacy@example.com"
    fk_db.add(EmailUser(email=legacy_email, user_id=legacy_email, password_hash=None, is_active=True))
    fk_db.commit()
    team = _seed_team_with_member(fk_db, email=legacy_email, user_id=legacy_email)

    payload = {"sub": legacy_email, "token_use": "session"}
    with patch("mcpgateway.auth.fresh_db_session", lambda: _pinned_session(fk_db)):
        teams = await resolve_session_teams(payload, legacy_email, {"is_admin": False})

    assert teams == [team.id]


@pytest.mark.asyncio
async def test_session_teams_admin_bypass_unchanged(fk_db):
    """Admin bypass (is_admin resolved from DB) still returns None."""
    admin_email = "admin@example.com"
    fk_db.add(EmailUser(email=admin_email, user_id=admin_email, password_hash=None, is_active=True, is_admin=True))
    fk_db.commit()

    payload = {"sub": admin_email, "token_use": "session"}
    with patch("mcpgateway.auth.fresh_db_session", lambda: _pinned_session(fk_db)):
        teams = await resolve_session_teams(payload, admin_email, {})  # no is_admin key -> DB lookup

    assert teams is None
