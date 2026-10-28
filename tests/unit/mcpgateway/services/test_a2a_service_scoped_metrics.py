# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_a2a_service_scoped_metrics.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Visibility scoping of A2AAgentService.aggregate_metrics against a real database.
"""

# Standard
from datetime import datetime, timezone

# Third-Party
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.db import A2AAgent, A2AAgentMetric, Base
from mcpgateway.services.a2a_service import A2AAgentService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _agent(db, name, visibility, team_id=None, owner="owner@x.com", enabled=True, ok=0, bad=0):
    agent = A2AAgent(id=name, name=name, slug=name, endpoint_url=f"http://{name}.example.com", visibility=visibility, team_id=team_id, owner_email=owner, enabled=enabled)
    db.add(agent)
    db.flush()
    now = datetime.now(timezone.utc)
    for _ in range(ok):
        db.add(A2AAgentMetric(a2a_agent_id=name, timestamp=now, response_time=1.0, is_success=True))
    for _ in range(bad):
        db.add(A2AAgentMetric(a2a_agent_id=name, timestamp=now, response_time=3.0, is_success=False))
    db.commit()


@pytest.fixture
def seeded(db):
    _agent(db, "pub", "public", ok=2)
    _agent(db, "team-a", "team", team_id="team-a", ok=1, bad=1)
    _agent(db, "team-b", "team", team_id="team-b", ok=10)
    _agent(db, "mine", "private", owner="me@x.com", ok=1)
    _agent(db, "theirs", "private", owner="other@x.com", ok=20)
    _agent(db, "off", "public", enabled=False, ok=3)
    return db


@pytest.mark.asyncio
async def test_public_only_counts_only_public_agents(seeded):
    result = await A2AAgentService().aggregate_metrics(seeded, user_email="me@x.com", token_teams=[])
    assert (result.total_agents, result.active_agents) == (2, 1)
    assert result.total_interactions == 5


@pytest.mark.asyncio
async def test_team_scope_excludes_other_teams_and_other_users_private(seeded):
    result = await A2AAgentService().aggregate_metrics(seeded, user_email="me@x.com", token_teams=["team-a"])
    assert result.total_agents == 4  # pub, off, team-a, mine
    assert result.total_interactions == 8  # 2 + 3 + 2 + 1
    assert result.failed_interactions == 1


@pytest.mark.asyncio
async def test_wrong_team_sees_no_team_agents(seeded):
    result = await A2AAgentService().aggregate_metrics(seeded, user_email="stranger@x.com", token_teams=["team-z"])
    assert result.total_agents == 2
    assert result.total_interactions == 5


@pytest.mark.asyncio
async def test_no_visible_agents_returns_zeros(db):
    result = await A2AAgentService().aggregate_metrics(db, user_email="me@x.com", token_teams=[])
    assert (result.total_agents, result.active_agents, result.total_interactions, result.success_rate) == (0, 0, 0, 0.0)


@pytest.mark.asyncio
async def test_admin_context_sees_all_team_agents_but_not_others_private(seeded, monkeypatch):
    monkeypatch.setattr("mcpgateway.services.a2a_service.is_user_admin", lambda _db, _email: True)
    result = await A2AAgentService().aggregate_metrics(seeded, user_email="me@x.com", token_teams=None)
    assert result.total_agents == 5  # everything except "theirs"
    assert result.total_interactions == 2 + 2 + 10 + 1 + 3
