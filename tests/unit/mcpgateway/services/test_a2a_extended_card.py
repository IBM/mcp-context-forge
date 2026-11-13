# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_a2a_extended_card.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for fetching and storing the authenticated extended A2A Agent Card (#4734).
"""

# Standard
import copy
from unittest.mock import AsyncMock, MagicMock

# Third-Party
from fastapi import HTTPException
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

# First-Party
from mcpgateway import main
from mcpgateway.db import A2AAgent, A2AAgentCard, Base
from mcpgateway.services import a2a_card_import
from mcpgateway.services import a2a_service as a2a_service_module
from mcpgateway.services.a2a_card_import import _build_found_response, CardResponse, extended_card_additions, fetch_agent_card, fetch_extended_card
from mcpgateway.services.a2a_service import A2AAgentError, A2AAgentNotFoundError, A2AAgentService

SOURCE_URL = "https://agent.example.com/.well-known/agent-card.json"
PUBLIC_CARD = {
    "name": "weather",
    "capabilities": {"streaming": True, "extendedAgentCard": True},
    "supportedInterfaces": [{"url": "https://agent.example.com/rpc", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}],
    "skills": [{"id": "public", "name": "Public", "description": "d", "tags": []}],
}
EXTENDED_CARD = {**PUBLIC_CARD, "skills": PUBLIC_CARD["skills"] + [{"id": "secret", "name": "Secret", "description": "d", "tags": []}], "provider": {"organization": "Acme", "url": "https://acme.example"}}
HEADERS = {"Authorization": "Bearer t0k"}  # pragma: allowlist secret


def _rpc(result):
    """Wrap a card in a JSON-RPC success envelope."""
    return CardResponse(200, {"jsonrpc": "2.0", "id": "1", "result": result}, etag='"ext"', max_age=60)


def _patch_get_json(monkeypatch, responses):
    """Serve ``responses`` in order from ``_get_json`` and record the calls."""
    calls = []

    async def fake(url, headers, payload=None):
        calls.append((url, headers, payload))
        return responses[min(len(calls) - 1, len(responses) - 1)]

    monkeypatch.setattr(a2a_card_import, "_get_json", fake)
    return calls


@pytest.mark.asyncio
class TestFetchExtendedCard:
    """fetch_extended_card()."""

    async def test_found_uses_the_1_0_method(self, monkeypatch):
        """A 1.0 interface is asked with GetExtendedAgentCard and the card is normalized."""
        calls = _patch_get_json(monkeypatch, [_rpc(EXTENDED_CARD)])
        result = await fetch_extended_card(PUBLIC_CARD, SOURCE_URL, HEADERS)
        assert result.outcome == "found"
        assert calls[0][2]["method"] == "GetExtendedAgentCard"
        assert calls[0][1] == HEADERS
        assert (result.etag, result.max_age) == ('"ext"', 60)

    async def test_legacy_interface_uses_the_0_3_method(self, monkeypatch):
        """A 0.3 interface is asked with agent/getAuthenticatedExtendedCard."""
        legacy = copy.deepcopy(PUBLIC_CARD)
        legacy["supportedInterfaces"][0]["protocolVersion"] = "0.3.0"
        calls = _patch_get_json(monkeypatch, [_rpc(EXTENDED_CARD)])
        await fetch_extended_card(legacy, SOURCE_URL, HEADERS)
        assert calls[0][2]["method"] == "agent/getAuthenticatedExtendedCard"

    @pytest.mark.parametrize("status", [401, 403])
    async def test_rejected_key_is_reported(self, monkeypatch, status):
        """A 401 or 403 means the agent rejected the credential."""
        _patch_get_json(monkeypatch, [CardResponse(status)])
        assert (await fetch_extended_card(PUBLIC_CARD, SOURCE_URL, HEADERS)).outcome == "auth_rejected"

    @pytest.mark.parametrize("response", [CardResponse(None), CardResponse(500), CardResponse(200, {"result": {"not": "a card"}}), CardResponse(200, {"error": {"code": -32601}}), CardResponse(200, None)])
    async def test_unusable_answer_is_unavailable(self, monkeypatch, response):
        """Transport failure, a server error, a JSON-RPC error, or a non-card result is unavailable."""
        _patch_get_json(monkeypatch, [response])
        assert (await fetch_extended_card(PUBLIC_CARD, SOURCE_URL, HEADERS)).outcome == "unavailable"

    async def test_credentials_are_not_sent_to_another_origin(self, monkeypatch):
        """An interface on another origin than the card URL never receives the credential."""
        card = copy.deepcopy(PUBLIC_CARD)
        card["supportedInterfaces"][0]["url"] = "https://other.example.com/rpc"
        calls = _patch_get_json(monkeypatch, [_rpc(EXTENDED_CARD)])
        assert (await fetch_extended_card(card, SOURCE_URL, HEADERS)).outcome == "unavailable"
        assert not calls

    async def test_non_jsonrpc_binding_is_unavailable(self, monkeypatch):
        """Only the JSON-RPC binding is supported."""
        card = copy.deepcopy(PUBLIC_CARD)
        card["supportedInterfaces"][0]["protocolBinding"] = "GRPC"
        calls = _patch_get_json(monkeypatch, [_rpc(EXTENDED_CARD)])
        assert (await fetch_extended_card(card, SOURCE_URL, HEADERS)).outcome == "unavailable"
        assert not calls


@pytest.mark.asyncio
class TestFetchAgentCardExtended:
    """fetch_agent_card() with credentials and a card that declares an extended card."""

    async def test_extended_card_and_additions_are_returned(self, monkeypatch):
        """The response names what the extended card adds."""
        _patch_get_json(monkeypatch, [CardResponse(200, copy.deepcopy(PUBLIC_CARD)), _rpc(EXTENDED_CARD)])
        found = await fetch_agent_card("https://agent.example.com", None, HEADERS)
        assert found.extended_outcome == "found"
        assert found.extended_additions == ["provider", "skills"]
        assert found.extended_card["provider"]["organization"] == "Acme"

    async def test_no_headers_means_no_extended_attempt(self, monkeypatch):
        """Without credentials the extended card is not requested."""
        calls = _patch_get_json(monkeypatch, [CardResponse(200, copy.deepcopy(PUBLIC_CARD))])
        found = await fetch_agent_card("https://agent.example.com", None, None)
        assert found.extended_outcome is None
        assert len(calls) == 1

    async def test_undeclared_extended_card_is_not_requested(self, monkeypatch):
        """A card that does not declare capabilities.extendedAgentCard is not asked for one."""
        card = copy.deepcopy(PUBLIC_CARD)
        card["capabilities"]["extendedAgentCard"] = False
        calls = _patch_get_json(monkeypatch, [CardResponse(200, card)])
        found = await fetch_agent_card("https://agent.example.com", None, HEADERS)
        assert found.extended_outcome is None
        assert len(calls) == 1

    async def test_rejected_key_is_reported_on_a_found_card(self, monkeypatch):
        """The public card is still returned when the extended card rejects the key."""
        _patch_get_json(monkeypatch, [CardResponse(200, copy.deepcopy(PUBLIC_CARD)), CardResponse(401)])
        found = await fetch_agent_card("https://agent.example.com", None, HEADERS)
        assert (found.found, found.extended_outcome, found.extended_card) == (True, "auth_rejected", None)


def test_additions_compare_nested_objects_key_by_key():
    """A new nested key reports its dotted path and an unchanged one reports nothing."""
    assert extended_card_additions({"capabilities": {"streaming": True}}, {"capabilities": {"streaming": True, "extensions": []}}) == ["capabilities.extensions"]
    assert extended_card_additions(PUBLIC_CARD, PUBLIC_CARD) == []


@pytest.fixture
def db():
    """In-memory database holding the agent and card tables."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(A2AAgent(id="agent-1", name="weather-local", slug="weather-local", endpoint_url="https://agent.example.com/rpc", agent_type="generic", protocol_version="1.0", visibility="public"))
    session.commit()
    yield session
    session.close()


@pytest.fixture
def service():
    """A2A service instance."""
    return A2AAgentService()


def _fetched(**overrides):
    """Build a found response with an extended card from the real fetch builder."""
    found = _build_found_response(SOURCE_URL, copy.deepcopy(PUBLIC_CARD), etag='"pub"', max_age=300)
    update = {"extended_outcome": "found", "extended_card": copy.deepcopy(EXTENDED_CARD), "extended_etag": '"ext"', "extended_max_age": 60}
    update.update(overrides)
    return found.model_copy(update=update)


@pytest.mark.asyncio
class TestExtendedCardStorage:
    """Registration stores and rejects on the extended card."""

    async def test_extended_card_is_stored_as_its_own_row(self, db, service):
        """A found extended card becomes a second row of kind extended."""
        service._store_agent_card(db, db.get(A2AAgent, "agent-1"), _fetched())  # pylint: disable=protected-access
        rows = db.execute(select(A2AAgentCard).order_by(A2AAgentCard.version)).scalars().all()
        assert [(row.kind, row.version, row.etag) for row in rows] == [("public", 1, '"pub"'), ("extended", 2, '"ext"')]
        assert rows[1].card["provider"]["organization"] == "Acme"

    async def test_no_extended_row_without_an_extended_card(self, db, service):
        """A registration without an extended card stores the public row only."""
        service._store_agent_card(db, db.get(A2AAgent, "agent-1"), _fetched(extended_outcome=None, extended_card=None))  # pylint: disable=protected-access
        assert [row.kind for row in db.execute(select(A2AAgentCard)).scalars()] == ["public"]

    async def test_kinds_read_back_separately(self, db, service, monkeypatch):
        """Each kind returns its own current card."""
        monkeypatch.setattr(service, "get_agent", AsyncMock())
        service._store_agent_card(db, db.get(A2AAgent, "agent-1"), _fetched())  # pylint: disable=protected-access
        assert (await service.get_stored_card(db, "agent-1")).kind == "public"
        extended = await service.get_stored_card(db, "agent-1", kind="extended")
        assert (extended.kind, extended.card["provider"]["organization"]) == ("extended", "Acme")

    async def test_rejected_extended_key_fails_registration(self, service, monkeypatch):
        """A key the agent rejects for the extended card stops the registration."""
        monkeypatch.setattr(a2a_service_module, "fetch_agent_card", AsyncMock(return_value=_fetched(extended_outcome="auth_rejected", extended_card=None)))
        auth_value = a2a_service_module.encode_auth({"Authorization": "Bearer t0k"})  # pragma: allowlist secret
        with pytest.raises(A2AAgentError, match="rejected the credentials"):
            await service._fetch_registration_card("https://agent.example.com", "bearer", auth_value, "https://agent.example.com/rpc")  # pylint: disable=protected-access


@pytest.mark.asyncio
class TestExtendedCardRoute:
    """GET /a2a/{agent_id}/stored-card/extended."""

    def _grant(self, monkeypatch, allowed):
        """Install a permission service that answers ``allowed``."""
        permission_service = MagicMock()
        permission_service.check_permission = AsyncMock(return_value=allowed)
        monkeypatch.setattr("mcpgateway.middleware.rbac.PermissionService", lambda db: permission_service)
        monkeypatch.setattr("mcpgateway.plugins.get_plugin_manager", AsyncMock(return_value=None))
        service = MagicMock()
        service.get_stored_card = AsyncMock()
        monkeypatch.setattr(main, "a2a_service", service)
        return service

    async def _call(self):
        """Call the route as an authenticated caller."""
        return await main.get_a2a_agent_stored_extended_card("agent-1", MagicMock(), db=MagicMock(), user={"email": "u@example.com", "db": MagicMock()})

    async def test_denied_without_a2a_update(self, monkeypatch):
        """A caller without a2a.update gets 403 and the service is not reached."""
        service = self._grant(monkeypatch, False)
        with pytest.raises(HTTPException) as exc_info:
            await self._call()
        assert exc_info.value.status_code == 403
        service.get_stored_card.assert_not_awaited()

    async def test_returns_the_extended_card(self, monkeypatch):
        """A permitted caller receives the extended kind."""
        service = self._grant(monkeypatch, True)
        service.get_stored_card.return_value = "card"
        assert await self._call() == "card"
        assert service.get_stored_card.await_args.kwargs["kind"] == "extended"

    async def test_invisible_agent_is_404(self, monkeypatch):
        """An agent the caller cannot see gives 404."""
        service = self._grant(monkeypatch, True)
        service.get_stored_card.side_effect = A2AAgentNotFoundError("nope")
        with pytest.raises(HTTPException) as exc_info:
            await self._call()
        assert exc_info.value.status_code == 404

    async def test_agent_without_extended_card_is_404(self, monkeypatch):
        """A visible agent with no extended card gives 404."""
        service = self._grant(monkeypatch, True)
        service.get_stored_card.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            await self._call()
        assert exc_info.value.status_code == 404


def test_token_scoping_maps_the_extended_route_to_update():
    """The extended card route needs a2a.update, ahead of the generic a2a GET rule."""
    # First-Party
    from mcpgateway.middleware.token_scoping import _PERMISSION_PATTERNS  # pylint: disable=import-outside-toplevel

    match = next(permission for method, pattern, permission in _PERMISSION_PATTERNS if method == "GET" and pattern.match("/a2a/agent-1/stored-card/extended"))
    assert match == "a2a.update"
