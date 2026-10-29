# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_a2a_agent_card_storage.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for storing and reading an A2A Agent Card as fetched (#4734).
"""

# Standard
from unittest.mock import AsyncMock, MagicMock

# Third-Party
from fastapi import HTTPException
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# First-Party
from mcpgateway import main
from mcpgateway.db import A2AAgent, A2AAgentCard, Base
from mcpgateway.schemas import A2AAgentCreate, A2AFetchCardResponse
from mcpgateway.services import a2a_service as a2a_service_module
from mcpgateway.services.a2a_service import A2AAgentError, A2AAgentNotFoundError, A2AAgentService

RAW_CARD = {"name": "weather", "supportedInterfaces": [{"url": "https://agent.example.com/rpc", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}], "futureField": {"kept": True}}


def _fetched(**overrides) -> A2AFetchCardResponse:
    """Build a successful fetch result."""
    values = dict(found=True, source_url="https://agent.example.com/.well-known/agent-card.json", detected_version="1.0", card=RAW_CARD, raw_card=RAW_CARD, etag='"v1"', max_age=300)
    values.update(overrides)
    return A2AFetchCardResponse(**values)


@pytest.fixture
def db():
    """In-memory database holding only the agent and card tables."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    agent = A2AAgent(id="agent-1", name="weather-local", slug="weather-local", endpoint_url="https://agent.example.com/rpc", agent_type="generic", protocol_version="1.0", visibility="public")
    session.add(agent)
    session.commit()
    yield session
    session.close()


@pytest.fixture
def service():
    """A fresh A2A service."""
    return A2AAgentService()


class TestStoreCard:
    """Persisting the card as fetched."""

    def test_stores_document_unchanged_beside_local_name(self, db, service):
        """The stored card keeps unmodelled fields; the local name is unaffected."""
        agent = db.get(A2AAgent, "agent-1")
        service._store_agent_card(db, agent, _fetched())  # pylint: disable=protected-access

        row = db.query(A2AAgentCard).one()
        assert row.card == RAW_CARD and row.card["futureField"] == {"kept": True}
        assert (row.version, row.detected_version, row.etag, row.max_age) == (1, "1.0", '"v1"', 300)
        assert row.source_url.endswith("agent-card.json")
        assert agent.name == "weather-local" and row.card["name"] == "weather"

    def test_next_store_adds_a_version_and_keeps_history(self, db, service):
        """A second store appends version 2 and keeps version 1."""
        agent = db.get(A2AAgent, "agent-1")
        service._store_agent_card(db, agent, _fetched())  # pylint: disable=protected-access
        service._store_agent_card(db, agent, _fetched(etag='"v2"'))  # pylint: disable=protected-access
        assert [(r.version, r.etag) for r in db.query(A2AAgentCard).order_by(A2AAgentCard.version)] == [(1, '"v1"'), (2, '"v2"')]

    def test_storage_failure_keeps_agent(self, db, service, monkeypatch):
        """A failed card write is logged and the agent row stays."""
        agent = db.get(A2AAgent, "agent-1")
        monkeypatch.setattr(db, "commit", MagicMock(side_effect=RuntimeError("disk full")))
        service._store_agent_card(db, agent, _fetched())  # pylint: disable=protected-access
        assert db.query(A2AAgentCard).count() == 0
        assert db.get(A2AAgent, "agent-1") is not None

    def test_deleting_agent_deletes_cards(self, db, service):
        """Cards cascade with their agent."""
        agent = db.get(A2AAgent, "agent-1")
        service._store_agent_card(db, agent, _fetched())  # pylint: disable=protected-access
        db.delete(agent)
        db.commit()
        assert db.query(A2AAgentCard).count() == 0


@pytest.mark.asyncio
class TestRegistrationFetch:
    """Server-side card fetch at registration."""

    async def test_no_card_url_skips_fetch(self, service, monkeypatch):
        """Registration without a card URL never fetches."""
        fetch = AsyncMock()
        monkeypatch.setattr(a2a_service_module, "fetch_agent_card", fetch)
        assert await service._fetch_registration_card(None) is None  # pylint: disable=protected-access
        fetch.assert_not_awaited()

    async def test_found_card_is_returned(self, service, monkeypatch):
        """A found card is passed on for storage."""
        monkeypatch.setattr(a2a_service_module, "fetch_agent_card", AsyncMock(return_value=_fetched()))
        assert (await service._fetch_registration_card("https://agent.example.com")).raw_card == RAW_CARD  # pylint: disable=protected-access

    async def test_missing_card_fails_before_any_write(self, service, monkeypatch):
        """A card URL with no card fails registration with a generic error."""
        monkeypatch.setattr(a2a_service_module, "fetch_agent_card", AsyncMock(return_value=A2AFetchCardResponse(found=False, reason="x")))
        with pytest.raises(A2AAgentError, match="No A2A Agent Card"):
            await service.register_agent(MagicMock(), A2AAgentCreate(name="a", endpoint_url="https://agent.example.com/rpc", card_url="https://nowhere.example.com"))


def test_client_cannot_supply_card_document():
    """The create schema has a card URL but no field for a card document."""
    assert "card_url" in A2AAgentCreate.model_fields
    assert not {"card", "agent_card", "raw_card"} & set(A2AAgentCreate.model_fields)


@pytest.mark.asyncio
class TestReadStoredCard:
    """Reading the current stored card."""

    async def test_returns_highest_version(self, db, service, monkeypatch):
        """The newest stored version is the current card."""
        monkeypatch.setattr(service, "get_agent", AsyncMock())
        agent = db.get(A2AAgent, "agent-1")
        service._store_agent_card(db, agent, _fetched())  # pylint: disable=protected-access
        service._store_agent_card(db, agent, _fetched(etag='"v2"'))  # pylint: disable=protected-access
        card = await service.get_stored_card(db, "agent-1")
        assert (card.version, card.etag, card.card) == (2, '"v2"', RAW_CARD)

    async def test_agent_without_card_returns_none(self, db, service, monkeypatch):
        """A hand-registered agent has no stored card."""
        monkeypatch.setattr(service, "get_agent", AsyncMock())
        assert await service.get_stored_card(db, "agent-1") is None

    async def test_invisible_agent_is_not_found(self, db, service, monkeypatch):
        """Visibility is enforced through get_agent before any card is read."""
        monkeypatch.setattr(service, "get_agent", AsyncMock(side_effect=A2AAgentNotFoundError("nope")))
        with pytest.raises(A2AAgentNotFoundError):
            await service.get_stored_card(db, "agent-1", user_email="other@example.com", token_teams=[])


@pytest.mark.asyncio
class TestStoredCardRoute:
    """GET /a2a/{agent_id}/stored-card."""

    async def test_denied_without_a2a_read(self, monkeypatch):
        """A caller lacking a2a.read gets 403 and the service is not reached."""
        permission_service = MagicMock()
        permission_service.check_permission = AsyncMock(return_value=False)
        monkeypatch.setattr("mcpgateway.middleware.rbac.PermissionService", lambda db: permission_service)
        monkeypatch.setattr("mcpgateway.plugins.get_plugin_manager", AsyncMock(return_value=None))
        service = MagicMock()
        service.get_stored_card = AsyncMock()
        monkeypatch.setattr(main, "a2a_service", service)
        with pytest.raises(HTTPException) as exc_info:
            await main.get_a2a_agent_stored_card("agent-1", MagicMock(), db=MagicMock(), user={"email": "u@example.com", "db": MagicMock()})
        assert exc_info.value.status_code == 403
        service.get_stored_card.assert_not_awaited()
