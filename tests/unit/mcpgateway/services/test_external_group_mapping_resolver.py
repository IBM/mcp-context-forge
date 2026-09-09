# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_external_group_mapping_resolver.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for resolve_external_groups_to_teams (issue #5976).

The resolver translates external IdP group IDs into ContextForge team IDs and
role names through the external_group_mappings table. Unmapped groups
contribute nothing: the resolver fails closed.
"""

# Standard
from datetime import datetime, timezone

# Third-Party
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.db import Base, EmailTeam, EmailUser, ExternalGroupMapping
from mcpgateway.utils.trusted_claims import resolve_external_groups_to_teams

ISSUER = "https://issuer.example.com"
TENANT = "tenant-1"


@pytest.fixture
def db():
    """In-memory SQLite session seeded with teams and mapping rows."""
    engine = sa.create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()

    user = EmailUser(
        email="owner@example.com",
        password_hash="hash",  # pragma: allowlist secret
        full_name="Owner",
        is_admin=False,
        is_active=True,
        email_verified_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(user)
    session.add(EmailTeam(id="team-a", name="Team A", slug="team-a", created_by=user.email, is_personal=False, visibility="private"))
    session.add(EmailTeam(id="team-b", name="Team B", slug="team-b", created_by=user.email, is_personal=False, visibility="private"))
    session.add(ExternalGroupMapping(issuer=ISSUER, tenant=TENANT, external_group_id="guid-1", cf_team_id="team-a", cf_role="developer"))
    session.add(ExternalGroupMapping(issuer=ISSUER, tenant=TENANT, external_group_id="guid-2", cf_team_id="team-b", cf_role=None))
    session.add(ExternalGroupMapping(issuer=ISSUER, tenant=None, external_group_id="guid-3", cf_team_id="team-b", cf_role="viewer"))
    session.commit()
    try:
        yield session
    finally:
        session.close()


class TestResolveExternalGroupsToTeams:
    """Mapped, unmapped, and mixed group resolution."""

    def test_mapped_groups_return_teams_and_roles(self, db):
        team_ids, role_names = resolve_external_groups_to_teams(ISSUER, TENANT, ["guid-1", "guid-2"], db)
        assert team_ids == ["team-a", "team-b"]
        assert role_names == ["developer"]

    def test_unmapped_groups_fail_closed(self, db):
        team_ids, role_names = resolve_external_groups_to_teams(ISSUER, TENANT, ["guid-unknown"], db)
        assert team_ids == []
        assert role_names == []

    def test_mixed_groups_only_mapped_contribute(self, db):
        team_ids, role_names = resolve_external_groups_to_teams(ISSUER, TENANT, ["guid-1", "guid-unknown"], db)
        assert team_ids == ["team-a"]
        assert role_names == ["developer"]

    def test_empty_groups_fail_closed(self, db):
        team_ids, role_names = resolve_external_groups_to_teams(ISSUER, TENANT, [], db)
        assert team_ids == []
        assert role_names == []

    def test_tenant_scoping_isolates_mappings(self, db):
        # A mapping recorded for tenant-1 must not leak into another tenant.
        team_ids, role_names = resolve_external_groups_to_teams(ISSUER, "other-tenant", ["guid-1"], db)
        assert team_ids == []
        assert role_names == []

    def test_null_tenant_matches_only_tenantless_rows(self, db):
        team_ids, role_names = resolve_external_groups_to_teams(ISSUER, None, ["guid-1", "guid-3"], db)
        assert team_ids == ["team-b"]
        assert role_names == ["viewer"]

    def test_issuer_scoping_isolates_mappings(self, db):
        team_ids, role_names = resolve_external_groups_to_teams("https://other-issuer.example.com", TENANT, ["guid-1"], db)
        assert team_ids == []
        assert role_names == []

    def test_null_role_contributes_team_only(self, db):
        team_ids, role_names = resolve_external_groups_to_teams(ISSUER, TENANT, ["guid-2"], db)
        assert team_ids == ["team-b"]
        assert role_names == []
