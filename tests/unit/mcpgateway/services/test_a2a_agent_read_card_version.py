# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_a2a_agent_read_card_version.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for reporting the stored Agent Card version on A2AAgentRead (#7605).
"""

# Standard

# Third-Party
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

# First-Party
from mcpgateway.db import A2AAgent, A2AAgentCard, Base
from mcpgateway.services.a2a_service import A2AAgentService

SOURCE_URL = "https://agent.example.com/.well-known/agent-card.json"
CARD = {"name": "weather", "version": "2.1.0"}


def _agent(agent_id: str, name: str) -> A2AAgent:
    """Build a minimally valid public A2A agent row."""
    return A2AAgent(
        id=agent_id,
        name=name,
        slug=name,
        endpoint_url="https://agent.example.com/rpc",
        agent_type="generic",
        protocol_version="1.0",
        capabilities={},
        config={},
        visibility="public",
    )


def _card(agent_id: str, version: int) -> A2AAgentCard:
    """Build a stored Agent Card row at ``version``."""
    return A2AAgentCard(
        a2a_agent_id=agent_id,
        version=version,
        kind="public",
        card=CARD,
        detected_version="1.0",
        source_url=SOURCE_URL,
    )


@pytest.fixture
def db():
    """In-memory database holding agent and card tables."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(_agent("agent-plain", "plain-agent"))
    session.add(_agent("agent-carded", "carded-agent"))
    session.add(_agent("agent-other", "other-agent"))
    session.add(_card("agent-carded", 1))
    session.add(_card("agent-carded", 3))
    session.add(_card("agent-other", 2))
    session.commit()
    yield session
    session.close()


@pytest.fixture
def service():
    """A fresh A2A service."""
    return A2AAgentService()


class TestConvertAgentCardVersion:
    """A2AAgentRead.card_version comes from the stored card history."""

    def test_card_version_is_null_when_no_card_is_stored(self, db, service):
        """An agent registered without a card reports card_version=null."""
        agent = db.get(A2AAgent, "agent-plain")
        read = service.convert_agent_to_read(agent, db=db)
        assert read.card_version is None

    def test_card_version_matches_highest_stored_version(self, db, service):
        """card_version is the highest version in a2a_agent_cards for that agent."""
        agent = db.get(A2AAgent, "agent-carded")
        read = service.convert_agent_to_read(agent, db=db)
        assert read.card_version == 3

    def test_prefetched_map_is_used_without_a_per_agent_query(self, db, service):
        """A pre-fetched map supplies card_version and skips a per-agent lookup."""
        agent = db.get(A2AAgent, "agent-carded")
        original_query = db.query
        queries = []

        def tracking_query(*args, **kwargs):
            queries.append(args)
            return original_query(*args, **kwargs)

        db.query = tracking_query  # type: ignore[method-assign]
        read = service.convert_agent_to_read(agent, db=db, card_version_map={"agent-carded": 3})
        assert read.card_version == 3
        assert queries == []

    def test_missing_map_key_is_null(self, db, service):
        """A batch map that omits an agent means that agent has no stored card."""
        agent = db.get(A2AAgent, "agent-plain")
        read = service.convert_agent_to_read(agent, db=db, card_version_map={"agent-carded": 3})
        assert read.card_version is None


class TestBatchCardVersions:
    """List requests resolve stored card versions in one query."""

    def test_batch_lookup_returns_highest_version_per_agent(self, db, service):
        """One grouped query returns the highest version for each requested agent."""
        result = service._batch_get_card_versions(db, ["agent-plain", "agent-carded", "agent-other"])  # pylint: disable=protected-access
        assert result == {"agent-carded": 3, "agent-other": 2}

    def test_batch_lookup_is_a_single_query(self, db, service):
        """Listing versions does not run a query per agent."""
        statements = []

        def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):  # pylint: disable=unused-argument
            statements.append(statement)

        event.listen(db.get_bind(), "before_cursor_execute", before_cursor_execute)
        service._batch_get_card_versions(db, ["agent-plain", "agent-carded", "agent-other"])  # pylint: disable=protected-access
        event.remove(db.get_bind(), "before_cursor_execute", before_cursor_execute)

        card_statements = [s for s in statements if "a2a_agent_cards" in s.lower()]
        assert len(card_statements) == 1
        assert "max(" in card_statements[0].lower() or "max (" in card_statements[0].lower()

    def test_empty_id_list_does_not_query(self, db, service):
        """No agents means no query and an empty map."""
        assert service._batch_get_card_versions(db, []) == {}  # pylint: disable=protected-access

    @pytest.mark.asyncio
    async def test_list_agents_for_user_passes_one_prefetched_map(self, db, service, monkeypatch):
        """The deprecated list path batches card versions once and passes the map."""
        # First-Party
        from mcpgateway.services.team_management_service import TeamManagementService

        async def no_teams(self, user_email):  # pylint: disable=unused-argument
            return []

        monkeypatch.setattr(TeamManagementService, "get_user_teams", no_teams)

        batch_calls = []
        real_batch = service._batch_get_card_versions

        def tracking_batch(session, agent_ids):
            batch_calls.append(list(agent_ids))
            return real_batch(session, agent_ids)

        monkeypatch.setattr(service, "_batch_get_card_versions", tracking_batch)

        maps = []
        real_convert = service.convert_agent_to_read

        def tracking_convert(*args, **kwargs):
            maps.append(kwargs.get("card_version_map"))
            return real_convert(*args, **kwargs)

        monkeypatch.setattr(service, "convert_agent_to_read", tracking_convert)

        result = await service.list_agents_for_user(db, "viewer@example.com")
        by_id = {agent.id: agent.card_version for agent in result}

        assert len(batch_calls) == 1
        assert set(batch_calls[0]) == {"agent-plain", "agent-carded", "agent-other"}
        assert maps and all(m == {"agent-carded": 3, "agent-other": 2} for m in maps)
        assert by_id["agent-plain"] is None
        assert by_id["agent-carded"] == 3
        assert by_id["agent-other"] == 2
