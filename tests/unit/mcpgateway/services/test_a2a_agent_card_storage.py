# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_a2a_agent_card_storage.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for storing and reading an A2A Agent Card as fetched (#4734).
"""

# Standard
import copy
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
from mcpgateway.services.a2a_card_import import _build_found_response
from mcpgateway.services.a2a_service import A2AAgentError, A2AAgentNotFoundError, A2AAgentService

SOURCE_URL = "https://agent.example.com/.well-known/agent-card.json"
V1_CARD = {
    "name": "weather",
    "version": "2.1.0",
    "supportedInterfaces": [{"url": "https://agent.example.com/rpc", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}],
    "futureField": {"kept": True},
}
LEGACY_CARD = {
    "name": "legacy",
    "url": "https://old.example.com/a2a",
    "version": "1.2.0",
    "protocolVersion": "0.3.0",
    "capabilities": {"streaming": True},
    "skills": [],
    "futureField": {"kept": True},
}
RAW_CARD = V1_CARD


def _fetched(document=None, **overrides) -> A2AFetchCardResponse:
    """Build the fetch result the fetcher produces for ``document``, as ``fetch_agent_card`` does."""
    found = _build_found_response(SOURCE_URL, copy.deepcopy(document or V1_CARD), etag=overrides.pop("etag", '"v1"'), max_age=overrides.pop("max_age", 300))
    assert found is not None
    return found.model_copy(update=overrides)


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

    def test_a1_0_card_is_stored_as_fetched_not_null(self, db, service):
        """A card already in the 1.0 shape has no separate raw copy, so the card itself is stored."""
        fetched = _fetched()
        assert fetched.raw_card is None
        agent = db.get(A2AAgent, "agent-1")
        service._store_agent_card(db, agent, fetched)  # pylint: disable=protected-access

        row = db.query(A2AAgentCard).one()
        assert row.card == V1_CARD
        assert row.detected_version == "1.0"

    def test_legacy_card_stores_the_document_not_the_normalized_card(self, db, service):
        """A 0.3 card keeps its original fields, not the 1.0 normalization."""
        fetched = _fetched(LEGACY_CARD)
        assert fetched.raw_card is not None and fetched.card != fetched.raw_card
        agent = db.get(A2AAgent, "agent-1")
        service._store_agent_card(db, agent, fetched)  # pylint: disable=protected-access

        row = db.query(A2AAgentCard).one()
        assert row.card == LEGACY_CARD
        assert row.detected_version == "0.3"

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
        assert (await service._fetch_registration_card("https://agent.example.com")).card["name"] == "weather"  # pylint: disable=protected-access

    async def test_missing_card_fails_before_any_write(self, service, monkeypatch):
        """A card URL with no card fails registration with a generic error."""
        monkeypatch.setattr(a2a_service_module, "fetch_agent_card", AsyncMock(return_value=A2AFetchCardResponse(found=False, outcome="no_card", reason="x")))
        with pytest.raises(A2AAgentError, match="No A2A Agent Card"):
            await service.register_agent(MagicMock(), A2AAgentCreate(name="a", endpoint_url="https://agent.example.com/rpc", card_url="https://nowhere.example.com"))

    @pytest.mark.parametrize(
        "outcome, message",
        [("auth_required", "requires credentials"), ("unreachable", "could not be reached"), ("no_card", "No A2A Agent Card")],
    )
    async def test_failure_outcome_names_its_error(self, service, monkeypatch, outcome, message):
        """Each fetch outcome gives the caller a specific registration error."""
        monkeypatch.setattr(a2a_service_module, "fetch_agent_card", AsyncMock(return_value=A2AFetchCardResponse(found=False, outcome=outcome, reason="x")))
        with pytest.raises(A2AAgentError, match=message):
            await service._fetch_registration_card("https://agent.example.com")  # pylint: disable=protected-access

    async def test_registration_credentials_reach_the_card_fetch(self, service, monkeypatch):
        """A bearer credential is sent to the card URL so a keyed card can be read."""
        fetch = AsyncMock(return_value=_fetched())
        monkeypatch.setattr(a2a_service_module, "fetch_agent_card", fetch)
        auth_value = a2a_service_module.encode_auth({"Authorization": "Bearer t0k"})  # pragma: allowlist secret
        await service._fetch_registration_card("https://agent.example.com", "bearer", auth_value, "https://agent.example.com/rpc")  # pylint: disable=protected-access
        assert fetch.await_args.args[2] == {"Authorization": "Bearer t0k"}

    async def test_credentials_are_withheld_from_another_origin(self, service, monkeypatch):
        """A card URL on a different origin than the endpoint never receives the credential."""
        fetch = AsyncMock(return_value=_fetched())
        monkeypatch.setattr(a2a_service_module, "fetch_agent_card", fetch)
        auth_value = a2a_service_module.encode_auth({"Authorization": "Bearer t0k"})  # pragma: allowlist secret
        await service._fetch_registration_card("https://cards.evil.example", "bearer", auth_value, "https://agent.example.com/rpc")  # pylint: disable=protected-access
        assert fetch.await_args.args[2] is None

    async def test_no_credentials_sends_no_headers(self, service, monkeypatch):
        """A registration without auth fetches the card without headers."""
        fetch = AsyncMock(return_value=_fetched())
        monkeypatch.setattr(a2a_service_module, "fetch_agent_card", fetch)
        await service._fetch_registration_card("https://agent.example.com")  # pylint: disable=protected-access
        assert fetch.await_args.args[2] is None

    async def test_unsafe_credential_header_is_rejected(self, service, monkeypatch):
        """A Host override in the stored header set never reaches the fetch."""
        fetch = AsyncMock()
        monkeypatch.setattr(a2a_service_module, "fetch_agent_card", fetch)
        auth_value = a2a_service_module.encode_auth({"Host": "evil.example"})
        with pytest.raises(ValueError):
            await service._fetch_registration_card("https://agent.example.com", "authheaders", auth_value, "https://agent.example.com/rpc")  # pylint: disable=protected-access
        fetch.assert_not_awaited()


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

    async def test_stored_1_0_card_reads_back(self, db, service, monkeypatch):
        """A card stored from a 1.0 fetch validates on read, so the route cannot fail with 500."""
        monkeypatch.setattr(service, "get_agent", AsyncMock())
        service._store_agent_card(db, db.get(A2AAgent, "agent-1"), _fetched())  # pylint: disable=protected-access
        card = await service.get_stored_card(db, "agent-1")
        assert card.card == V1_CARD

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

    @pytest.fixture
    def permitted(self, monkeypatch):
        """Grant a2a.read and install a service double."""
        permission_service = MagicMock()
        permission_service.check_permission = AsyncMock(return_value=True)
        monkeypatch.setattr("mcpgateway.middleware.rbac.PermissionService", lambda db: permission_service)
        monkeypatch.setattr("mcpgateway.plugins.get_plugin_manager", AsyncMock(return_value=None))
        service = MagicMock()
        service.get_stored_card = AsyncMock()
        monkeypatch.setattr(main, "a2a_service", service)
        return service

    async def _call(self):
        """Call the route as an authenticated caller."""
        return await main.get_a2a_agent_stored_card("agent-1", MagicMock(), db=MagicMock(), user={"email": "u@example.com", "db": MagicMock()})

    async def test_returns_stored_card(self, permitted):
        """A permitted caller receives the stored card."""
        permitted.get_stored_card.return_value = "card"
        assert await self._call() == "card"

    async def test_invisible_agent_is_404(self, permitted):
        """An agent the caller cannot see gives 404."""
        permitted.get_stored_card.side_effect = A2AAgentNotFoundError("nope")
        with pytest.raises(HTTPException) as exc_info:
            await self._call()
        assert exc_info.value.status_code == 404

    async def test_agent_without_card_is_404(self, permitted):
        """A visible agent with no stored card gives 404."""
        permitted.get_stored_card.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            await self._call()
        assert exc_info.value.status_code == 404

    async def test_missing_service_is_503(self, permitted, monkeypatch):
        """A disabled service gives 503."""
        monkeypatch.setattr(main, "a2a_service", None)
        with pytest.raises(HTTPException) as exc_info:
            await self._call()
        assert exc_info.value.status_code == 503


@pytest.mark.asyncio
@pytest.mark.parametrize("document, detected", [(V1_CARD, "1.0"), (LEGACY_CARD, "0.3")], ids=["1.0", "0.3"])
async def test_registration_stores_the_card_in_the_database(service, monkeypatch, document, detected):
    """register_agent writes the fetched card as a row, for both card shapes."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    monkeypatch.setattr(service, "_fetch_registration_card", AsyncMock(return_value=_fetched(document)))
    monkeypatch.setattr(service, "convert_agent_to_read", MagicMock(return_value=MagicMock()))

    await service.register_agent(db, A2AAgentCreate(name="a", endpoint_url="https://agent.example.com/rpc", card_url="https://agent.example.com"))

    row = db.query(A2AAgentCard).one()
    assert row.card == document
    assert (row.version, row.detected_version, row.etag, row.max_age) == (1, detected, '"v1"', 300)
    assert row.a2a_agent_id == db.query(A2AAgent).one().id
    db.close()
