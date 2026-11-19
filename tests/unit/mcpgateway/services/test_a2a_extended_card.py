# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_a2a_extended_card.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for fetching and storing the authenticated extended A2A Agent Card (#4734).
"""

# Standard
import asyncio
import copy
from unittest.mock import AsyncMock, MagicMock

# Third-Party
from fastapi import HTTPException
import orjson
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

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
EXTENDED_CARD = {
    **PUBLIC_CARD,
    "skills": PUBLIC_CARD["skills"] + [{"id": "secret", "name": "Secret", "description": "d", "tags": []}],
    "provider": {"organization": "Acme", "url": "https://acme.example"},
}
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
        assert calls[0][0] == "https://agent.example.com/rpc"
        assert calls[0][2] == {"jsonrpc": "2.0", "id": "1", "method": "GetExtendedAgentCard", "params": {}}
        assert calls[0][1] == HEADERS
        assert (result.etag, result.max_age) == ('"ext"', 60)

    async def test_legacy_interface_uses_the_0_3_method(self, monkeypatch):
        """A 0.3 interface is asked with agent/getAuthenticatedExtendedCard."""
        legacy = copy.deepcopy(PUBLIC_CARD)
        legacy["supportedInterfaces"][0]["protocolVersion"] = "0.3.0"
        calls = _patch_get_json(monkeypatch, [_rpc(EXTENDED_CARD)])
        await fetch_extended_card(legacy, SOURCE_URL, HEADERS)
        assert calls[0][0] == "https://agent.example.com/rpc"
        assert calls[0][2] == {"jsonrpc": "2.0", "id": "1", "method": "agent/getAuthenticatedExtendedCard", "params": {}}

    @pytest.mark.parametrize("status", [401, 403])
    async def test_rejected_key_is_reported(self, monkeypatch, status):
        """A 401 or 403 means the agent rejected the credential."""
        _patch_get_json(monkeypatch, [CardResponse(status)])
        assert (await fetch_extended_card(PUBLIC_CARD, SOURCE_URL, HEADERS)).outcome == "auth_rejected"

    @pytest.mark.parametrize(
        "response", [CardResponse(None), CardResponse(500), CardResponse(200, {"result": {"not": "a card"}}), CardResponse(200, {"error": {"code": -32601}}), CardResponse(200, None)]
    )
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

    @pytest.mark.parametrize("interface_url", ["http://agent.example.com/rpc", "https://agent.example.com:8443/rpc", "https://other.example.com/rpc", "http://[bad/rpc"])
    async def test_interface_on_another_origin_or_malformed_is_unavailable(self, monkeypatch, interface_url):
        """A scheme downgrade, another port, another host, or an unparsable URL never receives the credential."""
        card = copy.deepcopy(PUBLIC_CARD)
        card["supportedInterfaces"][0]["url"] = interface_url
        calls = _patch_get_json(monkeypatch, [_rpc(EXTENDED_CARD)])
        result = await fetch_extended_card(card, SOURCE_URL, HEADERS)
        assert result.outcome == "unavailable"
        assert not calls

    async def test_unparsable_source_url_is_unavailable(self, monkeypatch):
        """A source URL that does not parse gives unavailable, not an exception."""
        calls = _patch_get_json(monkeypatch, [_rpc(EXTENDED_CARD)])
        assert (await fetch_extended_card(PUBLIC_CARD, "not a url", HEADERS)).outcome == "unavailable"
        assert not calls

    @pytest.mark.parametrize("interfaces", [[], [{"protocolBinding": "JSONRPC"}], ["not-an-object"]])
    async def test_card_without_usable_interface_is_unavailable(self, monkeypatch, interfaces):
        """A card with no interface that has a URL gives unavailable and sends no request."""
        card = {**copy.deepcopy(PUBLIC_CARD), "supportedInterfaces": interfaces}
        calls = _patch_get_json(monkeypatch, [_rpc(EXTENDED_CARD)])
        assert (await fetch_extended_card(card, SOURCE_URL, HEADERS)).outcome == "unavailable"
        assert not calls

    async def test_normalization_failure_is_unavailable(self, monkeypatch):
        """An answer that looks like a card but fails normalization gives unavailable."""
        _patch_get_json(monkeypatch, [_rpc(EXTENDED_CARD)])
        monkeypatch.setattr(a2a_card_import, "normalize_card", MagicMock(side_effect=ValueError("bad")))
        assert (await fetch_extended_card(PUBLIC_CARD, SOURCE_URL, HEADERS)).outcome == "unavailable"

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
        assert (found.extended_etag, found.extended_max_age, found.extended_raw_card) == ('"ext"', 60, None)

    async def test_response_serializes_extended_fields_in_camel_case(self, monkeypatch):
        """The documented camelCase names are the names on the wire."""
        _patch_get_json(monkeypatch, [CardResponse(200, copy.deepcopy(PUBLIC_CARD)), _rpc(EXTENDED_CARD)])
        found = await fetch_agent_card("https://agent.example.com", None, HEADERS)
        body = found.model_dump(by_alias=True)
        assert body["extendedOutcome"] == "found"
        assert body["extendedEtag"] == '"ext"'
        assert body["extendedMaxAge"] == 60
        assert body["extendedAdditions"] == ["provider", "skills"]
        assert body["extendedCard"]["provider"]["organization"] == "Acme"
        assert "extendedRawCard" in body
        assert not {"extended_outcome", "extended_etag"} & set(body)

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
        service.check_agent_manage_access = AsyncMock(return_value=True)
        monkeypatch.setattr(main, "a2a_service", service)
        self.audit = MagicMock()
        monkeypatch.setattr(main, "get_audit_trail_service", lambda: self.audit)
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

    async def test_route_passes_the_caller_identity_and_token_scope(self, monkeypatch):
        """The owner check and the read both use the caller email and token teams, never an admin bypass."""
        service = self._grant(monkeypatch, True)
        service.get_stored_card.return_value = "card"
        monkeypatch.setattr(main, "get_scoped_resource_access_context", lambda request, user: ("u@example.com", ["t1"]))
        await self._call()
        assert service.check_agent_manage_access.await_args.args[1:] == ("agent-1", "u@example.com", ["t1"])
        kwargs = service.get_stored_card.await_args.kwargs
        assert (kwargs["user_email"], kwargs["token_teams"]) == ("u@example.com", ["t1"])

    async def test_route_serializes_the_stored_card_through_its_response_model(self, monkeypatch):
        """A real stored card passes the response model and carries its kind on the wire."""
        # Third-Party
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        # First-Party
        from mcpgateway.schemas import A2AStoredCardRead

        service = self._grant(monkeypatch, True)
        service.get_stored_card.return_value = A2AStoredCardRead(
            kind="extended", version=2, card=EXTENDED_CARD, detected_version="1.0", source_url=SOURCE_URL, etag='"ext"', max_age=60, fetched_at="2026-11-19T00:00:00Z"
        )
        app = FastAPI()
        app.include_router(main.a2a_router)
        app.dependency_overrides[main.require_a2a_enabled] = lambda: None
        session = MagicMock()
        app.dependency_overrides[main.get_db] = lambda: session
        app.dependency_overrides[main.get_current_user_with_permissions] = lambda: {"email": "u@example.com", "db": MagicMock()}
        response = TestClient(app).get("/a2a/agent-1/stored-card/extended")
        assert response.status_code == 200, response.text
        body = response.json()
        assert (body["kind"], body["version"], body["etag"]) == ("extended", 2, '"ext"')
        assert body["card"]["provider"]["organization"] == "Acme"

    async def test_successful_read_is_audited_without_the_request_session(self, monkeypatch):
        """A read of the extended card records who read it. The audit write uses its own session."""
        service = self._grant(monkeypatch, True)
        service.get_stored_card.return_value = "card"
        await self._call()
        self.audit.log_action.assert_called_once()
        kwargs = self.audit.log_action.call_args.kwargs
        assert (kwargs["action"], kwargs["resource_type"], kwargs["resource_id"]) == ("read_a2a_extended_card", "a2a_agent", "agent-1")
        assert "db" not in kwargs

    async def test_denied_read_is_not_audited(self, monkeypatch):
        """A caller who does not own the agent leaves no read entry."""
        service = self._grant(monkeypatch, True)
        service.check_agent_manage_access.return_value = False
        with pytest.raises(HTTPException):
            await self._call()
        self.audit.log_action.assert_not_called()

    async def test_non_owner_is_404(self, monkeypatch):
        """A caller with a2a.update who does not own the agent gets 404 and no card."""
        service = self._grant(monkeypatch, True)
        service.check_agent_manage_access.return_value = False
        with pytest.raises(HTTPException) as exc_info:
            await self._call()
        assert exc_info.value.status_code == 404
        service.get_stored_card.assert_not_awaited()

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


@pytest.mark.asyncio
class TestExtendedRequestDeadline:
    """The extended request has its own deadline (M2)."""

    async def test_slow_extended_request_keeps_the_public_card(self, monkeypatch):
        """A public card that used most of the budget still returns, with the extended card unavailable."""
        monkeypatch.setattr(a2a_card_import.settings, "federation_timeout", 0.2)

        async def slow(url, headers, payload=None):
            await asyncio.sleep(0.15)
            return CardResponse(200, copy.deepcopy(PUBLIC_CARD)) if payload is None else CardResponse(None)

        monkeypatch.setattr(a2a_card_import, "_get_json", slow)
        result = await fetch_agent_card("https://agent.example.com", None, HEADERS)
        assert (result.found, result.outcome, result.extended_outcome) == (True, "found", "unavailable")


LEGACY_EXTENDED = {
    "name": "weather",
    "url": "https://agent.example.com/rpc",
    "version": "1.0.0",
    "protocolVersion": "0.3.0",
    "capabilities": {"streaming": True},
    "skills": [{"id": "secret", "name": "Secret", "description": "d", "tags": []}],
}


def _legacy_public_card():
    """A public card whose interface speaks 0.3, so the legacy method is used."""
    card = copy.deepcopy(PUBLIC_CARD)
    card["supportedInterfaces"][0]["protocolVersion"] = "0.3.0"
    return card


@pytest.mark.asyncio
class TestLegacyExtendedCard:
    """A 0.3 extended document keeps its raw form beside the normalized card (T6)."""

    async def test_legacy_extended_card_keeps_raw_and_normalized(self, monkeypatch):
        """The response carries the document as fetched and the 1.0 card, and names what the card adds."""
        calls = _patch_get_json(monkeypatch, [CardResponse(200, _legacy_public_card()), _rpc(copy.deepcopy(LEGACY_EXTENDED))])
        found = await fetch_agent_card("https://agent.example.com", None, HEADERS)
        assert calls[1][2]["method"] == "agent/getAuthenticatedExtendedCard"
        assert found.extended_outcome == "found"
        assert found.extended_raw_card == LEGACY_EXTENDED
        assert found.extended_card["supportedInterfaces"][0]["protocolBinding"] == "JSONRPC"
        assert "skills" in found.extended_additions

    async def test_stored_legacy_extended_row_holds_the_raw_document(self, db, service):
        """The stored row is the document as fetched, not the normalized card."""
        found = _build_found_response(SOURCE_URL, _legacy_public_card(), etag='"pub"', max_age=300)
        normalized, _ = a2a_card_import.normalize_card(copy.deepcopy(LEGACY_EXTENDED))
        found = found.model_copy(update={"extended_outcome": "found", "extended_card": normalized, "extended_raw_card": copy.deepcopy(LEGACY_EXTENDED), "extended_etag": '"ext"'})
        service._store_agent_card(db, db.get(A2AAgent, "agent-1"), found)  # pylint: disable=protected-access
        row = db.execute(select(A2AAgentCard).where(A2AAgentCard.kind == "extended")).scalar_one()
        assert row.card == LEGACY_EXTENDED


@pytest.mark.asyncio
class TestRegistrationWithExtendedCard:
    """register_agent with a real database session (T7)."""

    @pytest.fixture
    def reg_db(self):
        """An empty in-memory database."""
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        session = sessionmaker(bind=engine)()
        yield session
        session.close()

    def _register(self, service, db, monkeypatch, fetched=None, error=None):
        """Run register_agent with the card fetch replaced."""
        monkeypatch.setattr(service, "_fetch_registration_card", AsyncMock(return_value=fetched, side_effect=error))
        monkeypatch.setattr(service, "convert_agent_to_read", MagicMock(return_value=MagicMock()))
        data = a2a_service_module.A2AAgentCreate(name="reg", endpoint_url="https://agent.example.com/rpc", card_url="https://agent.example.com")
        return service.register_agent(db, data)

    async def test_rejected_extended_key_creates_no_agent(self, service, reg_db, monkeypatch):
        """A rejected key raises and leaves no agent and no card row."""
        with pytest.raises(A2AAgentError):
            await self._register(service, reg_db, monkeypatch, error=A2AAgentError("rejected"))
        assert reg_db.query(A2AAgent).count() == 0
        assert reg_db.query(A2AAgentCard).count() == 0

    async def test_unavailable_extended_card_stores_the_public_row_only(self, service, reg_db, monkeypatch):
        """An unavailable extended card still registers the agent with the public card."""
        await self._register(service, reg_db, monkeypatch, fetched=_fetched(extended_outcome="unavailable", extended_card=None))
        assert [row.kind for row in reg_db.query(A2AAgentCard)] == ["public"]
        assert reg_db.query(A2AAgent).count() == 1

    async def test_found_extended_card_stores_two_rows(self, service, reg_db, monkeypatch):
        """A found extended card is stored beside the public card."""
        await self._register(service, reg_db, monkeypatch, fetched=_fetched())
        assert [(row.kind, row.version) for row in reg_db.query(A2AAgentCard).order_by(A2AAgentCard.version)] == [("public", 1), ("extended", 2)]


@pytest.mark.asyncio
class TestVersionSequenceAndKinds:
    """One version counter per agent, and kind isolation on read (T8)."""

    async def test_second_store_increments_versions_per_agent(self, db, service):
        """Two stores give public 1 and 3, extended 2 and 4. The counter is shared."""
        agent = db.get(A2AAgent, "agent-1")
        service._store_agent_card(db, agent, _fetched())  # pylint: disable=protected-access
        service._store_agent_card(db, agent, _fetched(extended_etag='"ext2"'))  # pylint: disable=protected-access
        rows = db.execute(select(A2AAgentCard).order_by(A2AAgentCard.version)).scalars().all()
        assert [(row.kind, row.version) for row in rows] == [("public", 1), ("extended", 2), ("public", 3), ("extended", 4)]

    async def test_current_card_of_each_kind_is_the_highest_version_of_that_kind(self, db, service, monkeypatch):
        """After repeated stores the default kind never returns the extended row, and each kind returns its latest."""
        monkeypatch.setattr(service, "get_agent", AsyncMock())
        agent = db.get(A2AAgent, "agent-1")
        service._store_agent_card(db, agent, _fetched())  # pylint: disable=protected-access
        service._store_agent_card(db, agent, _fetched(etag='"pub2"', extended_etag='"ext2"'))  # pylint: disable=protected-access
        public = await service.get_stored_card(db, "agent-1")
        extended = await service.get_stored_card(db, "agent-1", kind="extended")
        assert (public.kind, public.version, public.etag) == ("public", 3, '"pub2"')
        assert (extended.kind, extended.version, extended.etag) == ("extended", 4, '"ext2"')

    async def test_agent_with_only_an_extended_row_has_no_public_card(self, db, service, monkeypatch):
        """The default read never falls back to the extended row."""
        monkeypatch.setattr(service, "get_agent", AsyncMock())
        db.add(A2AAgentCard(a2a_agent_id="agent-1", version=1, kind="extended", card=EXTENDED_CARD, detected_version="1.0", source_url=SOURCE_URL))
        db.commit()
        assert await service.get_stored_card(db, "agent-1") is None
        assert (await service.get_stored_card(db, "agent-1", kind="extended")).version == 1

    async def test_unknown_kind_returns_none(self, db, service, monkeypatch):
        """A kind that no row has returns None."""
        monkeypatch.setattr(service, "get_agent", AsyncMock())
        service._store_agent_card(db, db.get(A2AAgent, "agent-1"), _fetched())  # pylint: disable=protected-access
        assert await service.get_stored_card(db, "agent-1", kind="bogus") is None


@pytest.mark.asyncio
class TestVisibilityWithTheRealService:
    """The real visibility rules decide who can read a stored card (T3)."""

    @pytest.fixture
    def agents(self, db, service):
        """Agents with private, team, and public visibility, each with stored cards."""
        db.add(
            A2AAgent(id="priv", name="priv", slug="priv", endpoint_url="https://p.example.com/rpc", agent_type="generic", protocol_version="1.0", visibility="private", owner_email="owner@example.com")
        )
        db.add(
            A2AAgent(
                id="team",
                name="team",
                slug="team",
                endpoint_url="https://t.example.com/rpc",
                agent_type="generic",
                protocol_version="1.0",
                visibility="team",
                team_id="t1",
                owner_email="owner@example.com",
            )
        )
        db.commit()
        for agent_id in ("priv", "team"):
            service._store_agent_card(db, db.get(A2AAgent, agent_id), _fetched())  # pylint: disable=protected-access
        return db

    @pytest.mark.parametrize(
        ("agent_id", "user_email", "token_teams", "visible"),
        [
            ("priv", "owner@example.com", ["personal"], True),
            ("priv", "owner@example.com", [], False),
            ("priv", "other@example.com", [], False),
            ("team", "other@example.com", ["t1"], True),
            ("team", "other@example.com", ["other-team"], False),
            ("team", "other@example.com", [], False),
        ],
    )
    async def test_stored_card_follows_agent_visibility(self, agents, service, agent_id, user_email, token_teams, visible):
        """A caller outside the visibility scope gets not found. A caller inside gets the card."""
        read = service.get_stored_card(agents, agent_id, user_email=user_email, token_teams=token_teams, kind="extended")
        if visible:
            assert (await read).kind == "extended"
        else:
            with pytest.raises(A2AAgentNotFoundError):
                await read


@pytest.mark.asyncio
class TestRegistrationToStoredCards:
    """Registration through the real fetch and storage, read back by kind, with only the HTTP transport stubbed (T9)."""

    @pytest.fixture
    def transport(self, monkeypatch):
        """Stub the isolated HTTP client so ``_get_json`` and ``_read_body`` run for real."""
        target = MagicMock()
        target.apply_headers.side_effect = lambda h: dict(h)
        target.pin.side_effect = lambda url: url
        target.validated_url = "https://agent.example.com"
        target.extensions = {}
        monkeypatch.setattr(a2a_card_import, "resolve_pinned_target", AsyncMock(return_value=target))
        sent = []

        class _Resp:
            def __init__(self, status, body):
                self.status_code, self._body, self.headers = status, body, {"etag": '"t"'}

            async def aiter_raw(self):
                yield self._body

        class _Stream:
            def __init__(self, resp):
                self._resp = resp

            async def __aenter__(self):
                return self._resp

            async def __aexit__(self, *exc):
                return False

        class _Client:
            def stream(self, method, url, headers=None, content=None, **kwargs):
                sent.append((method, headers.get("Authorization")))
                if method == "GET":
                    return _Stream(_Resp(200, orjson.dumps(PUBLIC_CARD)))
                body = {"jsonrpc": "2.0", "id": "1", "result": EXTENDED_CARD}
                return _Stream(_Resp(200, orjson.dumps(body)))

        class _Ctx:
            async def __aenter__(self):
                return _Client()

            async def __aexit__(self, *exc):
                return False

        monkeypatch.setattr(a2a_card_import, "get_isolated_http_client", lambda **kwargs: _Ctx())
        return sent

    async def test_register_then_read_both_cards_through_the_route(self, service, transport, monkeypatch):
        """Fetch, register, store, and read both kinds through the route, with the credential on the extended request."""
        # Third-Party
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()
        monkeypatch.setattr(service, "convert_agent_to_read", MagicMock(return_value=MagicMock()))
        data = a2a_service_module.A2AAgentCreate(
            name="t9",
            endpoint_url="https://agent.example.com/rpc",
            card_url="https://agent.example.com",
            auth_type="bearer",
            auth_token="t0k",  # pragma: allowlist secret
        )
        await service.register_agent(db, data)
        agent_id = db.query(A2AAgent).one().id
        assert ("POST", "Bearer t0k") in transport  # pragma: allowlist secret

        permission_service = MagicMock()
        permission_service.check_permission = AsyncMock(return_value=True)
        monkeypatch.setattr("mcpgateway.middleware.rbac.PermissionService", lambda session: permission_service)
        monkeypatch.setattr("mcpgateway.plugins.get_plugin_manager", AsyncMock(return_value=None))
        monkeypatch.setattr(service, "check_agent_manage_access", AsyncMock(return_value=True))
        monkeypatch.setattr(main, "a2a_service", service)
        monkeypatch.setattr(main, "get_audit_trail_service", lambda: MagicMock())
        app = FastAPI()
        app.include_router(main.a2a_router)
        app.dependency_overrides[main.require_a2a_enabled] = lambda: None
        app.dependency_overrides[main.get_db] = lambda: db
        app.dependency_overrides[main.get_current_user_with_permissions] = lambda: {"email": "u@example.com", "db": MagicMock()}
        client = TestClient(app)

        public = client.get(f"/a2a/{agent_id}/stored-card")
        extended = client.get(f"/a2a/{agent_id}/stored-card/extended")

        assert (public.status_code, public.json()["kind"]) == (200, "public")
        assert "secret" not in {skill["id"] for skill in public.json()["card"]["skills"]}
        assert (extended.status_code, extended.json()["kind"]) == (200, "extended")
        assert "secret" in {skill["id"] for skill in extended.json()["card"]["skills"]}
        db.close()
