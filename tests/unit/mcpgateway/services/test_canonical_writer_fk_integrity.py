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

# Third-Party
import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
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
