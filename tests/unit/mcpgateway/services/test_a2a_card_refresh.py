# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_a2a_card_refresh.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for re-fetching the Agent Card of a registered agent (#7540).
"""

# Standard
import copy
import time
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
from mcpgateway.services.a2a_card_import import _build_found_response, ExtendedCardResult
from mcpgateway.services.a2a_service import _origin_of, A2AAgentError, A2AAgentNotFoundError, A2ACardRefreshThrottledError, A2AAgentService
from mcpgateway.utils.services_auth import encode_auth

SOURCE_URL = "https://agent.example.com/.well-known/agent-card.json"
ENDPOINT = "https://agent.example.com/rpc"
ORIGIN = "https://agent.example.com"
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
        assert fetch.await_args.args[0] == ORIGIN
        assert _agent_snapshot(db) == before

    async def test_derived_url_uses_the_origin_not_the_endpoint_path(self, db, service, fetch):
        """The well-known path hangs off the origin, never off the stored endpoint path."""
        db.get(A2AAgent, "agent-1").endpoint_url = "https://agent.example.com:8443/rpc/v1"
        db.commit()
        await service.refresh_card(db, "agent-1", A2ACardRefreshRequest())
        assert fetch.await_args.args[0] == "https://agent.example.com:8443"

    async def test_unchanged_card_adds_no_version_and_records_check(self, db, service, fetch):
        """Same document: no new row, checked_at set."""
        _store(db)
        result = await service.refresh_card(db, "agent-1", A2ACardRefreshRequest())
        assert (result.status, result.version, result.changed_keys) == ("unchanged", 1, [])
        assert db.query(A2AAgentCard).count() == 1
        assert db.query(A2AAgentCard).one().checked_at is not None

    async def test_extended_row_is_not_taken_for_the_current_public_card(self, db, service, fetch):
        """A newer extended row never becomes the comparison base or the source URL of the public card."""
        _store(db)
        _store(db, version=2, kind="extended", card={**V1_CARD, "secret": 1}, source_url="https://other.example.com/x")
        result = await service.refresh_card(db, "agent-1", A2ACardRefreshRequest())
        assert (result.status, result.version, result.source_url) == ("unchanged", 1, SOURCE_URL)
        assert fetch.await_args.args[0] == SOURCE_URL

    async def test_changed_public_card_takes_the_next_shared_version(self, db, service, fetch):
        """The shared counter skips the extended row."""
        _store(db)
        _store(db, version=2, kind="extended", card={**V1_CARD, "secret": 1})
        fetch.return_value = _found({**V1_CARD, "version": "2.2.0"}, etag='"v2"')
        result = await service.refresh_card(db, "agent-1", A2ACardRefreshRequest())
        assert (result.status, result.version) == ("updated", 3)

    async def test_refresh_stores_and_updates_the_extended_card(self, db, service, fetch):
        """A found extended card is stored once and left alone when unchanged."""
        _store(db)
        extended = {**V1_CARD, "skills": [{"id": "s", "name": "s", "description": "d", "tags": []}]}
        found = _found()
        found.extended_outcome, found.extended_card, found.extended_etag = "found", extended, '"e1"'
        fetch.return_value = found
        await service.refresh_card(db, "agent-1", A2ACardRefreshRequest())
        rows = db.query(A2AAgentCard).filter_by(kind="extended").all()
        assert [(row.version, row.card) for row in rows] == [(2, extended)]
        await service.refresh_card(db, "agent-1", A2ACardRefreshRequest())
        assert db.query(A2AAgentCard).filter_by(kind="extended").count() == 1
        found.extended_card = {**extended, "extra": 1}
        await service.refresh_card(db, "agent-1", A2ACardRefreshRequest())
        assert sorted(row.version for row in db.query(A2AAgentCard).filter_by(kind="extended")) == [2, 3]

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
        assert [call.args[0] for call in fetch.await_args_list] == [SOURCE_URL, ORIGIN]

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

    async def test_endpoint_without_an_origin_finds_no_card(self, db, service, fetch):
        """An endpoint that does not parse gives no card and sends no request."""
        db.get(A2AAgent, "agent-1").endpoint_url = "not a url"
        db.commit()
        with pytest.raises(A2AAgentError, match="No A2A Agent Card"):
            await service.refresh_card(db, "agent-1", A2ACardRefreshRequest())
        fetch.assert_not_awaited()

    async def test_storage_failure_leaves_the_card_unchanged(self, db, service, fetch, monkeypatch):
        """A failed write rolls back, raises, and keeps the stored card."""
        _store(db)
        found = _found({**V1_CARD, "version": "9.9.9"}, etag='"v9"')

        async def fail_after_fetch(*args, **kwargs):
            monkeypatch.setattr(db, "flush", MagicMock(side_effect=RuntimeError("disk full")))
            return found

        fetch.side_effect = fail_after_fetch
        with pytest.raises(A2AAgentError, match="Failed to store"):
            await service.refresh_card(db, "agent-1", A2ACardRefreshRequest())
        monkeypatch.undo()
        assert [(row.version, row.card["version"]) for row in db.query(A2AAgentCard)] == [(1, "2.1.0")]

    async def test_old_attempts_are_pruned_when_the_table_grows(self, db, service, fetch, monkeypatch):
        """The attempt table drops entries older than the interval once it passes 10000 agents."""
        monkeypatch.setattr(settings, "a2a_card_refresh_min_interval", 60)
        long_ago = time.monotonic() - 1000
        service._card_refresh_attempts = {f"old-{index}": long_ago for index in range(10001)}  # pylint: disable=protected-access
        await service.refresh_card(db, "agent-1", A2ACardRefreshRequest())
        assert list(service._card_refresh_attempts) == ["agent-1"]  # pylint: disable=protected-access

    async def test_credentials_are_withheld_for_an_unparsable_url(self, db, service):
        """A URL that does not parse never receives the agent credential."""
        agent = db.get(A2AAgent, "agent-1")
        agent.auth_type, agent.auth_value = "bearer", encode_auth({"Authorization": "Bearer s"})
        assert service._card_credentials(agent, "not a url") is None  # pylint: disable=protected-access

    async def test_stale_result_is_rejected_when_the_stored_card_changed(self, db, service, fetch):
        """A card stored by another refresh during the fetch is not overwritten or given a stale 304."""
        _store(db)

        async def concurrent_store(*args, **kwargs):
            _store(db, version=2, card={**V1_CARD, "version": "3.0.0"})
            return _not_modified()

        fetch.side_effect = concurrent_store
        with pytest.raises(A2AAgentError, match="changed during the refresh"):
            await service.refresh_card(db, "agent-1", A2ACardRefreshRequest())
        assert [row.version for row in db.query(A2AAgentCard)] == [1, 2]

    async def test_version_conflict_is_reported_as_a_retry(self, db, service, fetch, monkeypatch):
        """A uniqueness conflict from a concurrent writer is rejected, not a storage failure."""
        from sqlalchemy.exc import IntegrityError

        _store(db)
        found = _found({**V1_CARD, "version": "9.9.9"})

        async def conflict_after_fetch(*args, **kwargs):
            monkeypatch.setattr(db, "flush", MagicMock(side_effect=IntegrityError("insert", {}, Exception("unique"))))
            return found

        fetch.side_effect = conflict_after_fetch
        with pytest.raises(A2AAgentError, match="changed during the refresh"):
            await service.refresh_card(db, "agent-1", A2ACardRefreshRequest())

    async def test_true_and_one_are_different_values(self, db, service, fetch):
        """A field that changes from true to 1 stores a new version and is listed."""
        _store(db, card={**V1_CARD, "flag": True})
        fetch.return_value = _found({**V1_CARD, "flag": 1})
        result = await service.refresh_card(db, "agent-1", A2ACardRefreshRequest())
        assert (result.status, result.changed_keys) == ("updated", ["flag"])

    async def test_added_null_field_is_listed(self, db, service, fetch):
        """A key that appears with a null value is a change."""
        fetch.return_value = _found({**V1_CARD, "extra": None})
        _store(db)
        result = await service.refresh_card(db, "agent-1", A2ACardRefreshRequest())
        assert (result.status, result.changed_keys) == ("updated", ["extra"])

    async def test_identical_200_from_another_url_updates_source_and_validators(self, db, service, fetch):
        """An identical card from a new URL moves source_url with its ETag and max-age."""
        _store(db)
        fetch.return_value = _found(V1_CARD, url="https://agent.example.com/other.json", etag='"x9"')
        result = await service.refresh_card(db, "agent-1", A2ACardRefreshRequest())
        row = db.query(A2AAgentCard).one()
        assert (result.status, row.source_url, row.etag) == ("unchanged", "https://agent.example.com/other.json", '"x9"')

    async def test_304_stores_the_extended_card(self, db, service, fetch, monkeypatch):
        """An unchanged public card still refreshes the extended card with the agent credential."""
        agent = db.get(A2AAgent, "agent-1")
        agent.auth_type, agent.auth_value = "bearer", encode_auth({"Authorization": "Bearer s"})
        db.commit()
        _store(db)
        fetch.return_value = _not_modified()
        extended = {**V1_CARD, "skills": []}
        result_card = ExtendedCardResult("found", extended, extended, '"e1"', 30)
        stored_fetch = AsyncMock(return_value=result_card)
        monkeypatch.setattr(a2a_service_module, "fetch_stored_extended_card", stored_fetch)
        await service.refresh_card(db, "agent-1", A2ACardRefreshRequest())
        assert stored_fetch.await_args.args[2] == {"Authorization": "Bearer s"}
        assert [(row.version, row.kind) for row in db.query(A2AAgentCard).order_by(A2AAgentCard.version)] == [(1, "public"), (2, "extended")]


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
        service.check_agent_manage_access = AsyncMock(return_value=True)
        monkeypatch.setattr(main, "check_permission_inline", AsyncMock(return_value=True))
        monkeypatch.setattr(main, "_audit_a2a_card_refresh", MagicMock())
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

    async def test_service_unavailable_is_503(self, monkeypatch):
        """Without a service the route answers 503."""
        monkeypatch.setattr(main, "a2a_service", None)
        with pytest.raises(HTTPException) as exc:
            await self._call()
        assert exc.value.status_code == 503

    async def test_non_owner_is_404_and_nothing_is_fetched(self, route):
        """A caller who cannot manage the agent gets 404, as on the task routes."""
        route.check_agent_manage_access.return_value = False
        with pytest.raises(HTTPException) as exc:
            await self._call()
        assert exc.value.status_code == 404
        route.refresh_card.assert_not_awaited()

    async def test_create_check_carries_the_agent_team(self, route, monkeypatch):
        """The additive a2a.create check resolves the team context like require_permission."""
        check = AsyncMock(return_value=True)
        monkeypatch.setattr(main, "check_permission_inline", check)
        monkeypatch.setattr(main, "_resolve_team_and_check_mode", AsyncMock(return_value=("team-1", False)))
        await self._call(A2ACardRefreshRequest(base_url="https://a.example.com"))
        assert (check.await_args.args[1], check.await_args.kwargs["team_id"], check.await_args.kwargs["check_any_team"]) == ("a2a.create", "team-1", False)

    async def test_success_is_audited_and_failure_is_not(self, route):
        """Only a stored or checked refresh writes an audit entry."""
        await self._call()
        main._audit_a2a_card_refresh.assert_called_once()
        main._audit_a2a_card_refresh.reset_mock()
        route.refresh_card.side_effect = A2AAgentError("nope")
        with pytest.raises(HTTPException):
            await self._call()
        main._audit_a2a_card_refresh.assert_not_called()

    async def test_unknown_agent_is_404(self, route):
        """An agent the caller cannot see is 404."""
        route.refresh_card.side_effect = A2AAgentNotFoundError("nope")
        with pytest.raises(HTTPException) as exc:
            await self._call()
        assert exc.value.status_code == 404

    async def test_success_returns_the_service_result(self, route):
        """The route returns what the service returns."""
        result = MagicMock(status="unchanged")
        route.refresh_card.return_value = result
        assert await self._call() is result

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


@pytest.mark.parametrize(
    ("url", "origin"),
    [
        (None, None),
        ("", None),
        ("not a url", None),
        ("https://agent.example.com/rpc/v1?x=1", "https://agent.example.com"),
        ("https://agent.example.com:443/rpc", "https://agent.example.com"),
        ("http://agent.example.com:80/rpc", "http://agent.example.com"),
        ("http://127.0.0.1:9100/rpc", "http://127.0.0.1:9100"),
    ],
)
def test_origin_of(url, origin):
    """The origin keeps scheme, host, and a non-default port, and drops the rest."""
    assert _origin_of(url) == origin


@pytest.mark.asyncio
async def test_not_modified_response_is_read_without_a_body(monkeypatch):
    """A real 304 answer carries the ETag and max-age and no document."""
    # First-Party
    from mcpgateway.services import a2a_card_import
    from mcpgateway.services.a2a_card_import import CardResponse

    class _Resp:
        status_code = 304
        headers = {"etag": '"e"', "cache-control": "public, max-age=60"}

    class _Stream:
        async def __aenter__(self):
            return _Resp()

        async def __aexit__(self, *exc):
            return False

    class _Client:
        def stream(self, *args, **kwargs):
            return _Stream()

    target = MagicMock()
    target.pin.return_value = "https://1.2.3.4/card.json"
    target.validated_url = "https://a.example.com/card.json"
    target.extensions = {}
    result = await a2a_card_import._read_body(_Client(), "https://a.example.com/card.json", target, {})  # pylint: disable=protected-access
    assert result == CardResponse(304, etag='"e"', max_age=60)
