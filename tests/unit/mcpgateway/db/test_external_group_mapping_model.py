# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/db/test_external_group_mapping_model.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for the ExternalGroupMapping ORM model (issue #5976).

The model mirrors the external_group_mappings migration schema: one external
group maps to exactly one CF team and, optionally, one role. cf_team_id is a
foreign key to email_teams.id. cf_role is a plain String with no foreign key:
roles.name has only a partial unique index, so role existence is validated at
the application level.
"""

# Standard
from datetime import datetime, timezone

# Third-Party
import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.db import Base, EmailTeam, EmailUser, ExternalGroupMapping


def _make_session():
    """Return a session on an in-memory SQLite DB with FK enforcement on."""
    engine = sa.create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _seed_user(db, email: str = "owner@example.com") -> EmailUser:
    """Insert the owner user; return it."""
    user = EmailUser(
        email=email,
        password_hash="hash",  # pragma: allowlist secret
        full_name="Owner",
        is_admin=False,
        is_active=True,
        email_verified_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(user)
    db.commit()
    return user


def _seed_team(db, team_id: str, created_by: str = "owner@example.com") -> EmailTeam:
    """Insert one team; return it."""
    team = EmailTeam(id=team_id, name=f"Team {team_id}", slug=f"team-{team_id}", created_by=created_by, is_personal=False, visibility="private")
    db.add(team)
    db.commit()
    return team


def _seed_user_and_team(db, team_id: str = "team-a") -> EmailTeam:
    """Insert the owner user and one team; return the team."""
    _seed_user(db)
    return _seed_team(db, team_id)


def _mapping(**overrides) -> ExternalGroupMapping:
    """Build a mapping row with sane defaults; override any field by name."""
    values = {
        "issuer": "https://issuer.example.com",
        "tenant": "tenant-1",
        "external_group_id": "guid-1",
        "cf_team_id": "team-a",
        "cf_role": "developer",
    }
    values.update(overrides)
    return ExternalGroupMapping(**values)


class TestExternalGroupMappingModel:
    """Schema shape and constraint behavior of ExternalGroupMapping."""

    def test_tablename(self):
        assert ExternalGroupMapping.__tablename__ == "external_group_mappings"

    def test_instantiation_fields(self):
        mapping = _mapping()
        assert mapping.issuer == "https://issuer.example.com"
        assert mapping.tenant == "tenant-1"
        assert mapping.external_group_id == "guid-1"
        assert mapping.cf_team_id == "team-a"
        assert mapping.cf_role == "developer"

    def test_nullable_fields(self):
        mapping = _mapping(tenant=None, cf_role=None)
        assert mapping.tenant is None
        assert mapping.cf_role is None

    def test_server_defaults_on_insert(self):
        db = _make_session()
        try:
            _seed_user_and_team(db)
            mapping = _mapping()
            db.add(mapping)
            db.commit()
            assert mapping.id is not None
            assert mapping.validation_status == "valid"
            assert mapping.created_at is not None
            assert mapping.updated_at is not None
            assert mapping.last_validated_at is None
        finally:
            db.close()

    def test_unique_constraint_issuer_tenant_group(self):
        db = _make_session()
        try:
            _seed_user(db)
            _seed_team(db, "team-a")
            _seed_team(db, "team-b")
            db.add(_mapping(cf_team_id="team-a"))
            db.commit()
            db.add(_mapping(cf_team_id="team-b"))
            with pytest.raises(IntegrityError):
                db.commit()
        finally:
            db.close()

    def test_cf_team_id_fk_target(self):
        fks = ExternalGroupMapping.__table__.c.cf_team_id.foreign_keys
        assert {fk.target_fullname for fk in fks} == {"email_teams.id"}

    def test_cf_team_id_fk_enforced(self):
        db = _make_session()
        try:
            db.add(_mapping(cf_team_id="missing-team"))
            with pytest.raises(IntegrityError):
                db.commit()
        finally:
            db.close()

    def test_cf_role_has_no_fk(self):
        # roles.name has only a partial unique index, so cf_role must stay a
        # plain String. Existence is validated at the application level.
        assert not ExternalGroupMapping.__table__.c.cf_role.foreign_keys
