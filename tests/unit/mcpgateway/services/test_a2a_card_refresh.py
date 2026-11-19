# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_a2a_card_refresh.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for re-fetching the Agent Card of a registered agent (#7540).
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
from mcpgateway.config import settings
from mcpgateway.db import A2AAgent, A2AAgentCard, Base
from mcpgateway.schemas import A2ACardRefreshRequest
from mcpgateway.services import a2a_service as a2a_service_module
from mcpgateway.services.a2a_card_import import _build_found_response
from mcpgateway.services.a2a_service import A2AAgentError, A2ACardRefreshThrottledError, A2AAgentService
from mcpgateway.utils.services_auth import encode_auth

SOURCE_URL = "https://agent.example.com/.well-known/agent-card.json"
ENDPOINT = "https://agent.example.com/rpc"
V1_CARD = {
    "name": "weather",
    "version": "2.1.0",
    "supportedInterfaces": [{"url": ENDPOINT, "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}],
}


def _found(document=None, url=SOURCE_URL, etag='"v1"'):
    found = _build_found_response(url, copy.deepcopy(document or V1_CARD), etag=etag, max_age=60)
    assert found is not None
    return found


def _not_modified(etag='"v1"'):
    fetched = _found().model_copy(update={"found": False, "outcome": "not_modified", "card": None, "raw_card": None, "etag": etag})
    return fetched


@pytest.fixture
def db():
    """In-memory database holding one agent without a stored card."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(A2AAgent(id="agent-1", name="weather", slug="weather", endpoint_url=ENDPOINT, agent_type="generic", protocol_version="1.0", visibility="public"))
    session.commit()
    yield session
    session.close()


@pytest.fixture
def service(monkeypatch):
    """A fresh service with visibility and ownership checks passed."""
    svc = A2AAgentService()
    monkeypatch.setattr(svc, "get_agent", AsyncMock())
    monkeypatch.setattr(settings, "a2a_card_refresh_min_interval", 0)
    return svc


@pytest.fixture
def fetch(monkeypatch):
    """Replace the outbound fetch."""
    mock = AsyncMock(return_value=_found())
    monkeypatch.setattr(a2a_service_module, "fetch_agent_card", mock)
    return mock


def _agent_snapshot(db):
    agent = db.get(A2AAgent, "agent-1")
    return {column.name: getattr(agent, column.name) for column in A2AAgent.__table__.columns}


def _store(db, **overrides):
    values = dict(a2a_agent_id="agent-1", version=1, card=V1_CARD, detected_version="1.0", source_url=SOURCE_URL, etag='"v1"', max_age=60)
    values.update(overrides)
    db.add(A2AAgentCard(**values))
    db.commit()


@pytest.mark.asyncio
class TestRefreshCard:
    """Service behavior."""

    async def test_agent_without_card_gets_first_version_from_endpoint(self, db, service, fetch):
        """An agent with no stored card derives its URL from endpoint_url."""
        before = _agent_snapshot(db)
        result = await service.refresh_card(db, "agent-1", A2ACardRefreshRequest())
        assert (result.status, result.version) == ("created", 1)
        assert fetch.await_args.args[0] == ENDPOINT
        assert _agent_snapshot(db) == before

    async def test_unchanged_card_adds_no_version_and_records_check(self, db, service, fetch):
        """Same document: no new row, checked_at set."""
        _store(db)
        result = await service.refresh_card(db, "agent-1", A2ACardRefreshRequest())
        assert (result.status, result.version, result.changed_keys) == ("unchanged", 1, [])
        assert db.query(A2AAgentCard).count() == 1
        assert db.query(A2AAgentCard).one().checked_at is not None

    async def test_304_records_check_and_sends_stored_etag(self, db, service, fetch):
        """The stored ETag goes out as If-None-Match; a 304 is an unchanged check."""
        _store(db)
        fetch.return_value = _not_modified()
        result = await service.refresh_card(db, "agent-1", A2ACardRefreshRequest())
        assert result.status == "unchanged"
        assert fetch.await_args.args[0] == SOURCE_URL
        assert fetch.await_args.args[3] == '"v1"'
        assert db.query(A2AAgentCard).one().checked_at is not None

    async def test_changed_card_becomes_next_version_and_lists_keys(self, db, service, fetch):
        """A changed card is stored as version 2 and the changed top-level keys are listed."""
        _store(db)
        fetch.return_value = _found({**V1_CARD, "version": "2.2.0", "extra": 1}, etag='"v2"')
        result = await service.refresh_card(db, "agent-1", A2ACardRefreshRequest())
        assert (result.status, result.version, result.changed_keys) == ("updated", 2, ["extra", "version"])
        assert (await service.get_stored_card(db, "agent-1")).etag == '"v2"'
        assert db.query(A2AAgentCard).count() == 2

    @pytest.mark.parametrize("outcome", ["unreachable", "auth_required", "no_card"])
    async def test_failed_fetch_leaves_card_unchanged(self, db, service, fetch, outcome):
        """A failed request writes nothing, including a source_url the SSRF policy refuses (unreachable)."""
        _store(db)
        fetch.return_value = _found().model_copy(update={"found": False, "outcome": outcome, "card": None})
        with pytest.raises(A2AAgentError):
            await service.refresh_card(db, "agent-1", A2ACardRefreshRequest())
        row = db.query(A2AAgentCard).one()
        assert (row.version, row.card, row.checked_at) == (1, V1_CARD, None)

    async def test_stored_source_falls_back_to_endpoint_on_no_card(self, db, service, fetch):
        """A stored source that no longer serves a card falls through to the derived URLs."""
        _store(db)
        fetch.side_effect = [_found().model_copy(update={"found": False, "outcome": "no_card"}), _found()]
        await service.refresh_card(db, "agent-1", A2ACardRefreshRequest())
        assert [call.args[0] for call in fetch.await_args_list] == [SOURCE_URL, ENDPOINT]

    async def test_caller_base_url_and_headers_apply_to_this_request_only(self, db, service, fetch):
        """Caller URL wins, carries caller headers, sends no ETag, and stores no headers."""
        _store(db)
        request = A2ACardRefreshRequest(base_url="https://other.example.com/card.json", headers={"X-Key": "k"})
        await service.refresh_card(db, "agent-1", request)
        args = fetch.await_args.args
        assert (args[0], args[2]) == ("https://other.example.com/card.json", {"X-Key": "k"})
        assert len(args) == 3

    async def test_credential_sent_only_to_endpoint_origin(self, db, service, fetch):
        """The agent credential reaches a same-origin source_url and never a cross-origin one."""
        agent = db.get(A2AAgent, "agent-1")
        agent.auth_type, agent.auth_value = "bearer", encode_auth({"Authorization": "Bearer s"})
        db.commit()
        _store(db)
        await service.refresh_card(db, "agent-1", A2ACardRefreshRequest())
        assert fetch.await_args.args[2] == {"Authorization": "Bearer s"}

        db.query(A2AAgentCard).delete()
        _store(db, source_url="https://evil.example.com/card.json")
        await service.refresh_card(db, "agent-1", A2ACardRefreshRequest())
        assert fetch.await_args.args[2] is None

    async def test_rate_limit(self, db, service, fetch, monkeypatch):
        """A second attempt inside the interval is refused before any outbound request."""
        monkeypatch.setattr(settings, "a2a_card_refresh_min_interval", 60)
        await service.refresh_card(db, "agent-1", A2ACardRefreshRequest())
        with pytest.raises(A2ACardRefreshThrottledError) as exc:
            await service.refresh_card(db, "agent-1", A2ACardRefreshRequest())
        assert exc.value.retry_after > 0
        assert fetch.await_count == 1

    async def test_non_owner_is_denied(self, db, service, fetch, monkeypatch):
        """Ownership is enforced like agent update."""
        from mcpgateway.services import permission_service

        monkeypatch.setattr(permission_service.PermissionService, "check_resource_ownership", AsyncMock(return_value=False))
        with pytest.raises(PermissionError):
            await service.refresh_card(db, "agent-1", A2ACardRefreshRequest(), user_email="other@example.com")
        fetch.assert_not_awaited()


def test_headers_require_base_url():
    """Caller headers without a caller URL are rejected."""
    with pytest.raises(ValueError):
        A2ACardRefreshRequest(headers={"X-Key": "k"})


def test_unsafe_headers_are_rejected():
    """The fetch-card header rules apply."""
    with pytest.raises(ValueError):
        A2ACardRefreshRequest(base_url="https://a.example.com", headers={"Host": "evil"})


@pytest.mark.asyncio
class TestRefreshRoute:
    """Route behavior."""

    @pytest.fixture
    def route(self, monkeypatch):
        service = MagicMock()
        service.refresh_card = AsyncMock()
        monkeypatch.setattr(main, "a2a_service", service)
        monkeypatch.setattr(main, "get_scoped_resource_access_context", lambda request, user: ("u@example.com", None))
        monkeypatch.setattr(main, "check_permission_inline", AsyncMock(return_value=True))
        return service

    async def _call(self, payload=None):
        fn = main.refresh_a2a_agent_card
        fn = getattr(fn, "__wrapped__", fn)
        return await fn("agent-1", MagicMock(), payload, MagicMock(), {"email": "u@example.com"})

    async def test_base_url_requires_create(self, route, monkeypatch):
        """Supplying base_url without a2a.create is 403 and nothing is fetched."""
        monkeypatch.setattr(main, "check_permission_inline", AsyncMock(return_value=False))
        with pytest.raises(HTTPException) as exc:
            await self._call(A2ACardRefreshRequest(base_url="https://a.example.com"))
        assert exc.value.status_code == 403
        route.refresh_card.assert_not_awaited()

    async def test_no_base_url_needs_no_create(self, route, monkeypatch):
        """A refresh without a URL does not consult a2a.create."""
        check = AsyncMock(return_value=False)
        monkeypatch.setattr(main, "check_permission_inline", check)
        await self._call(None)
        check.assert_not_awaited()

    async def test_throttle_is_429_with_retry_after(self, route):
        route.refresh_card.side_effect = A2ACardRefreshThrottledError(12)
        with pytest.raises(HTTPException) as exc:
            await self._call(None)
        assert (exc.value.status_code, exc.value.headers["Retry-After"]) == (429, "12")

    async def test_fetch_failure_is_400(self, route):
        route.refresh_card.side_effect = A2AAgentError("nope")
        with pytest.raises(HTTPException) as exc:
            await self._call(None)
        assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_fetch_sends_if_none_match_and_maps_304(monkeypatch):
    """The fetcher sends the stored ETag and reports a 304 as not_modified."""
    # First-Party
    from mcpgateway.services import a2a_card_import
    from mcpgateway.services.a2a_card_import import CardResponse

    seen = {}

    async def fake_get_json(url, headers, if_none_match=None):
        seen["etag"] = if_none_match
        return CardResponse(304, etag='"v1"')

    monkeypatch.setattr(a2a_card_import, "_get_json", fake_get_json)
    result = await a2a_card_import.fetch_agent_card(SOURCE_URL, None, None, '"v1"')
    assert (seen["etag"], result.outcome, result.found) == ('"v1"', "not_modified", False)
