# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_team_search_query_sql.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Integration tests verifying that TeamManagementService.list_teams and get_teams_count
actually filter rows via SQL when search_query is set — not just mock the service layer.

These tests use a real in-memory SQLite database so the SQL WHERE clauses are exercised
end-to-end, catching any regression where search_description or search_query is dropped
from the query before the ORM executes it.
"""

from __future__ import annotations

# Third-Party
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as OrmSession

# First-Party
from mcpgateway.db import Base, EmailTeam
from mcpgateway.services.team_management_service import TeamManagementService


@pytest.fixture
def db_with_teams():
    """Real in-memory SQLite DB with three seeded teams for search tests."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with OrmSession(engine) as db:
        db.add_all(
            [
                EmailTeam(
                    id="id-eng",
                    name="Engineering",
                    slug="engineering",
                    description="Core platform engineering team",
                    created_by="admin@example.com",
                    is_personal=False,
                    is_active=True,
                ),
                EmailTeam(
                    id="id-ops",
                    name="Ops Team",
                    slug="ops-team",
                    description="Escalates to rocket-squad on call",
                    created_by="admin@example.com",
                    is_personal=False,
                    is_active=True,
                ),
                EmailTeam(
                    id="id-rocket",
                    name="Rocket Squad",
                    slug="rocket-squad",
                    description="First responder on-call rotation",
                    created_by="admin@example.com",
                    is_personal=False,
                    is_active=True,
                ),
            ]
        )
        db.commit()
        yield db


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_teams_sql_filters_by_name(db_with_teams):
    """list_teams SQL WHERE matches teams whose name contains the query."""
    svc = TeamManagementService(db_with_teams)
    teams, _ = await svc.list_teams(search_query="engineering")
    assert len(teams) == 1
    assert teams[0].id == "id-eng"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_teams_sql_filters_by_slug(db_with_teams):
    """list_teams SQL WHERE matches teams whose slug contains the query (case-insensitive).

    "ROCKET" matches id-rocket by name/slug AND id-ops by description
    ("Escalates to rocket-squad on call"). Both must appear.
    """
    svc = TeamManagementService(db_with_teams)
    teams, _ = await svc.list_teams(search_query="ROCKET")
    assert {t.id for t in teams} == {"id-rocket", "id-ops"}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_teams_sql_filters_by_description(db_with_teams):
    """list_teams SQL WHERE matches teams whose description contains the query."""
    svc = TeamManagementService(db_with_teams)
    # "rocket-squad" appears in Ops Team's description, not in its name or slug.
    teams, _ = await svc.list_teams(search_query="rocket-squad")
    ids = {t.id for t in teams}
    assert "id-ops" in ids
    assert "id-rocket" in ids  # also matches name/slug


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_teams_count_matches_list_teams_for_description_query(db_with_teams):
    """get_teams_count and list_teams must agree when search_query matches only via description.

    Regression for the count/list mismatch: previously get_teams_count did not pass
    search_description=True, so it under-counted description-only matches while list_teams
    returned them — causing paginated callers to see a total lower than actual results.
    """
    svc = TeamManagementService(db_with_teams)
    teams, _ = await svc.list_teams(search_query="rocket-squad")
    count = await svc.get_teams_count(search_query="rocket-squad")
    assert count == len(teams), f"list_teams returned {len(teams)} but get_teams_count returned {count}"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_teams_like_wildcard_percent_is_literal(db_with_teams):
    """Regression: search_query='%' must NOT match every team.

    Without _escape_like(), '%' is a SQL wildcard and returns all rows — a trivial
    data-enumeration vector for any caller who can use the search parameter.
    """
    svc = TeamManagementService(db_with_teams)
    teams, _ = await svc.list_teams(search_query="%")
    assert len(teams) == 0, f"'%' must not wildcard-match all teams, got {len(teams)}"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_teams_like_wildcard_underscore_is_literal(db_with_teams):
    """Regression: search_query='ops_team' must NOT match 'ops-team' via underscore wildcard.

    Without _escape_like(), '_' matches any single character, so 'ops_team' would match
    'ops-team' (the hyphen) — violating the literal-substring contract and causing
    admin/SQL results to diverge from the non-admin in-memory filter.
    """
    svc = TeamManagementService(db_with_teams)
    # The fixture has "ops-team" (slug) — an unescaped underscore would match it.
    teams, _ = await svc.list_teams(search_query="ops_team")
    assert len(teams) == 0, f"'ops_team' must not wildcard-match 'ops-team', got {len(teams)}"
