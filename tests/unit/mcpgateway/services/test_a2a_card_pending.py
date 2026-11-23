# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_a2a_card_pending.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for confirming or rejecting a changed Agent Card, the drifted flag,
the unverified marker, version reads and the scheduled re-sync (#7661).
"""

# Standard
import asyncio
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
from mcpgateway.schemas import A2ACardDecisionRequest, A2ACardRefreshRequest
from mcpgateway.services import a2a_service as a2a_service_module
from mcpgateway.services.a2a_card_import import changed_card_paths
from mcpgateway.services.a2a_service import A2AAgentError, A2AAgentNotFoundError, A2ACardConflictError, A2ACardNotFoundError, A2AAgentService
from mcpgateway.utils.services_auth import encode_auth
from tests.unit.mcpgateway.services.test_a2a_card_refresh import _found, _not_modified, _store, ENDPOINT, V1_CARD


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


STREAMING_CARD = {**V1_CARD, "capabilities": {"streaming": True, "extensions": []}}
MOVED_SAME_ORIGIN_CARD = {**V1_CARD, "version": "3.0.0", "supportedInterfaces": [{"url": "https://agent.example.com/rpc/v2", "protocolBinding": "JSONRPC", "protocolVersion": "1.1"}]}
MOVED_CARD = {
    **V1_CARD,
    "version": "3.0.0",
    "supportedInterfaces": [{"url": "https://moved.example.com/rpc", "protocolBinding": "JSONRPC", "protocolVersion": "1.1"}],
    "capabilities": {"streaming": True},
}


def _agent(db):
    db.expire_all()
    return db.get(A2AAgent, "agent-1")


def _rows(db):
    db.expire_all()
    return [(row.version, row.kind, row.status) for row in db.query(A2AAgentCard).order_by(A2AAgentCard.version)]


@pytest.mark.asyncio
class TestPendingVersion:
    """A changed card waits for a decision."""

    async def test_changed_card_is_pending_and_agent_is_untouched(self, db, service, fetch):
        _store(db)
        before = {column.name: getattr(_agent(db), column.name) for column in A2AAgent.__table__.columns}
        fetch.return_value = _found(STREAMING_CARD, etag='"v2"')
        result = await service.refresh_card(db, "agent-1", A2ACardRefreshRequest())
        assert (result.status, result.version, result.pending_version, result.changed_keys, result.drifted) == ("pending", 1, 2, ["capabilities"], False)
        assert _rows(db) == [(1, "public", "applied"), (2, "public", "pending")]
        assert (await service.get_stored_card(db, "agent-1")).version == 1
        assert {column.name: getattr(_agent(db), column.name) for column in A2AAgent.__table__.columns} == before

    async def test_same_remote_card_keeps_one_pending_version(self, db, service, fetch):
        _store(db)
        fetch.return_value = _found(STREAMING_CARD)
        await service.refresh_card(db, "agent-1", A2ACardRefreshRequest())
        result = await service.refresh_card(db, "agent-1", A2ACardRefreshRequest())
        assert (result.status, result.pending_version) == ("pending", 2)
        assert _rows(db) == [(1, "public", "applied"), (2, "public", "pending")]

    async def test_newer_change_supersedes_the_pending_version(self, db, service, fetch):
        _store(db)
        fetch.return_value = _found(STREAMING_CARD)
        await service.refresh_card(db, "agent-1", A2ACardRefreshRequest())
        fetch.return_value = _found({**STREAMING_CARD, "version": "9"})
        result = await service.refresh_card(db, "agent-1", A2ACardRefreshRequest())
        assert result.pending_version == 3
        assert _rows(db) == [(1, "public", "applied"), (2, "public", "superseded"), (3, "public", "pending")]

    async def test_remote_matching_the_current_card_drops_pending_and_clears_drift(self, db, service, fetch):
        _store(db)
        fetch.return_value = _found(STREAMING_CARD)
        await service.refresh_card(db, "agent-1", A2ACardRefreshRequest())
        await service.reject_pending_card(db, "agent-1", 2)
        assert _agent(db).drifted is True
        fetch.return_value = _found()
        result = await service.refresh_card(db, "agent-1", A2ACardRefreshRequest())
        assert (result.status, result.drifted) == ("unchanged", False)
        assert _agent(db).drifted is False

    async def test_304_drops_the_pending_version(self, db, service, fetch):
        _store(db)
        fetch.return_value = _found(STREAMING_CARD)
        await service.refresh_card(db, "agent-1", A2ACardRefreshRequest())
        fetch.return_value = _not_modified()
        await service.refresh_card(db, "agent-1", A2ACardRefreshRequest())
        assert _rows(db) == [(1, "public", "applied"), (2, "public", "superseded")]

    async def test_first_card_is_applied_at_once(self, db, service, fetch):
        result = await service.refresh_card(db, "agent-1", A2ACardRefreshRequest())
        assert (result.status, result.version, result.pending_version) == ("created", 1, None)
        assert _rows(db) == [(1, "public", "applied")]


@pytest.mark.asyncio
class TestDecisions:
    """Apply and reject."""

    async def _pending(self, db, service, fetch, document=STREAMING_CARD):
        _store(db)
        fetch.return_value = _found(document)
        await service.refresh_card(db, "agent-1", A2ACardRefreshRequest())

    async def test_reject_keeps_the_current_card_and_flags_the_agent(self, db, service, fetch):
        await self._pending(db, service, fetch)
        result = await service.reject_pending_card(db, "agent-1", 2)
        assert (result.status, result.drifted) == ("rejected", True)
        assert _rows(db) == [(1, "public", "applied"), (2, "public", "rejected")]
        assert (await service.get_stored_card(db, "agent-1")).version == 1
        assert _agent(db).endpoint_url == ENDPOINT

    async def test_rejected_card_is_not_offered_again(self, db, service, fetch):
        await self._pending(db, service, fetch)
        await service.reject_pending_card(db, "agent-1", 2)
        result = await service.refresh_card(db, "agent-1", A2ACardRefreshRequest())
        assert (result.status, result.drifted, result.pending_version) == ("unchanged", True, None)
        assert _rows(db) == [(1, "public", "applied"), (2, "public", "rejected")]

    async def test_change_after_reject_is_pending_and_agent_stays_drifted(self, db, service, fetch):
        await self._pending(db, service, fetch)
        await service.reject_pending_card(db, "agent-1", 2)
        fetch.return_value = _found({**STREAMING_CARD, "version": "9"})
        result = await service.refresh_card(db, "agent-1", A2ACardRefreshRequest())
        assert (result.status, result.pending_version, result.drifted) == ("pending", 3, True)

    async def test_apply_promotes_the_card_and_updates_call_fields(self, db, service, fetch, monkeypatch):
        monkeypatch.setattr("mcpgateway.services.a2a_service._get_registry_cache", lambda: MagicMock(invalidate_agents=AsyncMock()))
        await self._pending(db, service, fetch, MOVED_CARD)
        agent = _agent(db)
        version_before = agent.version
        result = await service.apply_pending_card(db, "agent-1", 2)
        agent = _agent(db)
        assert (result.status, result.drifted) == ("applied", False)
        assert result.applied_fields == ["capabilities", "endpoint_url", "protocol_version"]
        assert (agent.endpoint_url, agent.protocol_version, agent.capabilities["streaming"], agent.name) == ("https://moved.example.com/rpc", "1.1", True, "weather")
        assert agent.version == version_before + 1
        assert (await service.get_stored_card(db, "agent-1")).version == 2
        assert _rows(db) == [(1, "public", "applied"), (2, "public", "applied")]

    async def test_apply_clears_drift(self, db, service, fetch, monkeypatch):
        monkeypatch.setattr("mcpgateway.services.a2a_service._get_registry_cache", lambda: MagicMock(invalidate_agents=AsyncMock()))
        await self._pending(db, service, fetch)
        await service.reject_pending_card(db, "agent-1", 2)
        fetch.return_value = _found({**STREAMING_CARD, "version": "9"})
        await service.refresh_card(db, "agent-1", A2ACardRefreshRequest())
        await service.apply_pending_card(db, "agent-1", 3)
        assert _agent(db).drifted is False

    async def test_apply_keeps_credentials_and_auth_type(self, db, service, fetch, monkeypatch):
        monkeypatch.setattr("mcpgateway.services.a2a_service._get_registry_cache", lambda: MagicMock(invalidate_agents=AsyncMock()))
        agent = _agent(db)
        agent.auth_type, agent.auth_value = "bearer", encode_auth({"Authorization": "Bearer s"})
        db.commit()
        await self._pending(db, service, fetch, MOVED_SAME_ORIGIN_CARD)
        stored_auth = (_agent(db).auth_type, _agent(db).auth_value)
        result = await service.apply_pending_card(db, "agent-1", 2)
        assert "endpoint_url" in result.applied_fields
        assert (_agent(db).auth_type, _agent(db).auth_value) == stored_auth

    async def test_apply_refuses_another_origin_when_the_agent_has_credentials(self, db, service, fetch):
        agent = _agent(db)
        agent.auth_type, agent.auth_value = "bearer", encode_auth({"Authorization": "Bearer s"})
        db.commit()
        await self._pending(db, service, fetch, MOVED_CARD)
        with pytest.raises(A2AAgentError, match="another origin"):
            await service.apply_pending_card(db, "agent-1", 2)
        assert _agent(db).endpoint_url == ENDPOINT
        assert _rows(db) == [(1, "public", "applied"), (2, "public", "pending")]

    async def test_apply_refuses_an_endpoint_the_url_policy_rejects(self, db, service, fetch, monkeypatch):
        await self._pending(db, service, fetch, MOVED_CARD)
        monkeypatch.setattr("mcpgateway.services.a2a_service.SecurityValidator.validate_url", MagicMock(side_effect=ValueError("blocked")))
        with pytest.raises(A2AAgentError, match="not allowed"):
            await service.apply_pending_card(db, "agent-1", 2)
        assert _agent(db).endpoint_url == ENDPOINT

    async def test_apply_without_callable_interface_fails(self, db, service, fetch):
        await self._pending(db, service, fetch)
        row = db.query(A2AAgentCard).filter_by(version=2).one()
        row.card = {"name": "x", "version": "1"}
        db.commit()
        with pytest.raises(A2AAgentError, match="no callable interface"):
            await service.apply_pending_card(db, "agent-1", 2)

    async def test_apply_reports_skills_that_do_not_fit(self, db, service, fetch, monkeypatch):
        monkeypatch.setattr("mcpgateway.services.a2a_service._get_registry_cache", lambda: MagicMock(invalidate_agents=AsyncMock()))
        await self._pending(db, service, fetch, {**STREAMING_CARD, "skills": [{"id": "s", "name": "n", "description": "d", "tags": []}]})
        row = db.query(A2AAgentCard).filter_by(version=2).one()
        row.card = {**row.card, "skills": [{"bad": 1}]}
        db.commit()
        result = await service.apply_pending_card(db, "agent-1", 2)
        assert any("skills" in warning for warning in result.warnings)

    async def test_stale_version_is_a_conflict_and_missing_pending_is_not_found(self, db, service, fetch):
        _store(db)
        with pytest.raises(A2ACardNotFoundError):
            await service.reject_pending_card(db, "agent-1", 2)
        fetch.return_value = _found(STREAMING_CARD)
        await service.refresh_card(db, "agent-1", A2ACardRefreshRequest())
        with pytest.raises(A2ACardConflictError):
            await service.apply_pending_card(db, "agent-1", 5)
        assert _rows(db) == [(1, "public", "applied"), (2, "public", "pending")]

    async def test_apply_storage_failure_rolls_back(self, db, service, fetch, monkeypatch):
        await self._pending(db, service, fetch)
        monkeypatch.setattr(db, "commit", MagicMock(side_effect=RuntimeError("db down")))
        with pytest.raises(A2AAgentError, match="Failed to apply"):
            await service.apply_pending_card(db, "agent-1", 2)

    async def test_reject_storage_failure_rolls_back(self, db, service, fetch, monkeypatch):
        await self._pending(db, service, fetch)
        monkeypatch.setattr(db, "commit", MagicMock(side_effect=RuntimeError("db down")))
        with pytest.raises(A2AAgentError, match="Failed to reject"):
            await service.reject_pending_card(db, "agent-1", 2)


@pytest.mark.asyncio
class TestReads:
    """Pending beside current, and earlier versions."""

    async def test_pending_card_is_read_beside_the_current_card(self, db, service, fetch):
        _store(db, card=STREAMING_CARD)
        fetch.return_value = _found({**STREAMING_CARD, "capabilities": {"streaming": False, "extensions": []}})
        await service.refresh_card(db, "agent-1", A2ACardRefreshRequest())
        read = await service.get_pending_card(db, "agent-1")
        assert (read.current.version, read.pending.version, read.pending.status, read.changed_keys) == (1, 2, "pending", ["capabilities.streaming"])

    async def test_no_pending_card_reads_none(self, db, service):
        _store(db)
        assert await service.get_pending_card(db, "agent-1") is None

    async def test_earlier_version_is_readable_and_pending_is_not(self, db, service, fetch, monkeypatch):
        monkeypatch.setattr("mcpgateway.services.a2a_service._get_registry_cache", lambda: MagicMock(invalidate_agents=AsyncMock()))
        _store(db)
        fetch.return_value = _found(STREAMING_CARD)
        await service.refresh_card(db, "agent-1", A2ACardRefreshRequest())
        assert await service.get_stored_card(db, "agent-1", version=2) is None
        await service.apply_pending_card(db, "agent-1", 2)
        assert (await service.get_stored_card(db, "agent-1", version=1)).card == V1_CARD
        assert [(item.version, item.status) for item in await service.list_card_versions(db, "agent-1")] == [(2, "applied"), (1, "applied")]

    async def test_version_list_hides_pending_and_rejected(self, db, service, fetch):
        _store(db)
        fetch.return_value = _found(STREAMING_CARD)
        await service.refresh_card(db, "agent-1", A2ACardRefreshRequest())
        await service.reject_pending_card(db, "agent-1", 2)
        assert [item.version for item in await service.list_card_versions(db, "agent-1")] == [1]


class TestChangedPaths:
    def test_dotted_paths_split_behaviour_from_display(self):
        old = {"capabilities": {"streaming": False, "extensions": []}, "name": "a"}
        new = {"capabilities": {"streaming": True, "extensions": [{"uri": "x"}]}, "name": "a"}
        assert changed_card_paths(old, new) == ["capabilities.extensions", "capabilities.streaming"]

    def test_added_and_removed_keys_are_listed(self):
        assert changed_card_paths({"a": 1, "b": {"c": 1}}, {"a": 1, "b": {}, "d": 2}) == ["b.c", "d"]


@pytest.mark.asyncio
class TestUnverified:
    """A credential nothing has checked."""

    async def _with_credential(self, db):
        agent = _agent(db)
        agent.auth_type, agent.auth_value, agent.unverified = "bearer", encode_auth({"Authorization": "Bearer s"}), True
        db.commit()

    async def test_refresh_with_the_credential_clears_the_marker(self, db, service, fetch):
        await self._with_credential(db)
        _store(db)
        await service.refresh_card(db, "agent-1", A2ACardRefreshRequest())
        assert _agent(db).unverified is False

    async def test_request_headers_do_not_verify_the_stored_credential(self, db, service, fetch):
        await self._with_credential(db)
        _store(db)
        await service.refresh_card(db, "agent-1", A2ACardRefreshRequest(base_url="https://other.example.com/card.json", headers={"X-Key": "k"}))
        assert _agent(db).unverified is True

    async def test_cross_origin_source_does_not_verify(self, db, service, fetch):
        await self._with_credential(db)
        _store(db, source_url="https://other.example.com/card.json")
        fetch.return_value = _found(url="https://other.example.com/card.json")
        await service.refresh_card(db, "agent-1", A2ACardRefreshRequest())
        assert _agent(db).unverified is True


@pytest.mark.asyncio
class TestSync:
    """Scheduled re-sync."""

    @pytest.fixture
    def maker(self, db, monkeypatch):
        maker = sessionmaker(bind=db.get_bind())
        monkeypatch.setattr("mcpgateway.db.SessionLocal", maker)
        return maker

    async def test_sync_holds_a_changed_card_as_pending_and_never_applies_it(self, db, service, fetch, maker):
        _store(db)
        fetch.return_value = _found(MOVED_CARD)
        assert await service.sync_cards() == 1
        assert _rows(db) == [(1, "public", "applied"), (2, "public", "pending")]
        assert _agent(db).endpoint_url == ENDPOINT

    async def test_sync_skips_agents_without_a_stored_card_and_disabled_agents(self, db, service, fetch, maker):
        assert await service.sync_cards() == 0
        _store(db)
        _agent(db).enabled = False
        db.commit()
        assert await service.sync_cards() == 0
        fetch.assert_not_awaited()

    async def test_sync_survives_a_failure_and_respects_the_interval(self, db, service, fetch, maker, monkeypatch):
        _store(db)
        fetch.side_effect = RuntimeError("boom")
        assert await service.sync_cards() == 0
        monkeypatch.setattr(settings, "a2a_card_refresh_min_interval", 60)
        fetch.side_effect = None
        fetch.return_value = _found()
        assert await service.sync_cards() == 0
        service._card_refresh_attempts.clear()
        assert await service.sync_cards() == 1
        assert await service.sync_cards() == 0


@pytest.mark.asyncio
class TestRoutes:
    """Route mapping."""

    @pytest.fixture
    def route(self, monkeypatch):
        service = MagicMock()
        for name in ("apply_pending_card", "reject_pending_card", "get_pending_card", "list_card_versions", "get_stored_card"):
            setattr(service, name, AsyncMock())
        service.check_agent_manage_access = AsyncMock(return_value=True)
        monkeypatch.setattr(main, "a2a_service", service)
        monkeypatch.setattr(main, "get_scoped_resource_access_context", lambda request, user: ("u@example.com", None))
        monkeypatch.setattr(main, "_audit_a2a_card_decision", MagicMock())
        return service

    @staticmethod
    def _fn(name):
        fn = getattr(main, name)
        return getattr(fn, "__wrapped__", fn)

    async def _decide(self, name):
        return await self._fn(name)("agent-1", A2ACardDecisionRequest(version=2), MagicMock(), MagicMock(), {"email": "u@example.com"})

    @pytest.mark.parametrize("name,method", [("apply_a2a_agent_pending_card", "apply_pending_card"), ("reject_a2a_agent_pending_card", "reject_pending_card")])
    async def test_decision_is_audited_and_returned(self, route, name, method):
        getattr(route, method).return_value = MagicMock(status="applied", version=2)
        result = await self._decide(name)
        assert result is getattr(route, method).return_value
        assert getattr(route, method).await_args.args[1:3] == ("agent-1", 2)
        main._audit_a2a_card_decision.assert_called_once()

    @pytest.mark.parametrize("error,status", [(A2ACardNotFoundError("none"), 404), (A2AAgentNotFoundError("none"), 404), (A2ACardConflictError("stale"), 409), (A2AAgentError("bad"), 400)])
    async def test_decision_errors_map_to_status_codes_and_are_not_audited(self, route, error, status):
        route.apply_pending_card.side_effect = error
        with pytest.raises(HTTPException) as exc:
            await self._decide("apply_a2a_agent_pending_card")
        assert exc.value.status_code == status
        main._audit_a2a_card_decision.assert_not_called()

    async def test_non_owner_is_404_and_changes_nothing(self, route):
        route.check_agent_manage_access.return_value = False
        for name, method in (("apply_a2a_agent_pending_card", "apply_pending_card"), ("reject_a2a_agent_pending_card", "reject_pending_card")):
            with pytest.raises(HTTPException) as exc:
                await self._decide(name)
            assert exc.value.status_code == 404
            getattr(route, method).assert_not_awaited()

    async def test_service_unavailable_is_503(self, monkeypatch):
        monkeypatch.setattr(main, "a2a_service", None)
        with pytest.raises(HTTPException) as exc:
            await self._decide("apply_a2a_agent_pending_card")
        assert exc.value.status_code == 503

    async def test_pending_route_returns_404_when_nothing_is_pending(self, route):
        route.get_pending_card.return_value = None
        with pytest.raises(HTTPException) as exc:
            await self._fn("get_a2a_agent_pending_card")("agent-1", MagicMock(), MagicMock(), {"email": "u@example.com"})
        assert exc.value.status_code == 404

    async def test_pending_route_returns_the_pending_card(self, route):
        route.get_pending_card.return_value = MagicMock()
        assert await self._fn("get_a2a_agent_pending_card")("agent-1", MagicMock(), MagicMock(), {"email": "u@example.com"}) is route.get_pending_card.return_value

    async def test_pending_route_maps_unknown_agent_to_404_and_non_owner_to_404(self, route):
        route.get_pending_card.side_effect = A2AAgentNotFoundError("none")
        with pytest.raises(HTTPException) as exc:
            await self._fn("get_a2a_agent_pending_card")("agent-1", MagicMock(), MagicMock(), {"email": "u@example.com"})
        assert exc.value.status_code == 404
        route.check_agent_manage_access.return_value = False
        route.get_pending_card.side_effect = None
        route.get_pending_card.reset_mock()
        with pytest.raises(HTTPException) as exc:
            await self._fn("get_a2a_agent_pending_card")("agent-1", MagicMock(), MagicMock(), {"email": "u@example.com"})
        assert exc.value.status_code == 404
        route.get_pending_card.assert_not_awaited()

    async def test_versions_route(self, route):
        route.list_card_versions.return_value = []
        assert await self._fn("list_a2a_agent_card_versions")("agent-1", MagicMock(), MagicMock(), {"email": "u@example.com"}) == []
        route.list_card_versions.side_effect = A2AAgentNotFoundError("none")
        with pytest.raises(HTTPException) as exc:
            await self._fn("list_a2a_agent_card_versions")("agent-1", MagicMock(), MagicMock(), {"email": "u@example.com"})
        assert exc.value.status_code == 404

    async def test_versions_route_service_unavailable(self, monkeypatch):
        monkeypatch.setattr(main, "a2a_service", None)
        with pytest.raises(HTTPException) as exc:
            await self._fn("list_a2a_agent_card_versions")("agent-1", MagicMock(), MagicMock(), {"email": "u@example.com"})
        assert exc.value.status_code == 503

    async def test_pending_route_service_unavailable(self, monkeypatch):
        monkeypatch.setattr(main, "a2a_service", None)
        with pytest.raises(HTTPException) as exc:
            await self._fn("get_a2a_agent_pending_card")("agent-1", MagicMock(), MagicMock(), {"email": "u@example.com"})
        assert exc.value.status_code == 503

    async def test_stored_card_route_passes_the_version(self, route):
        route.get_stored_card.return_value = MagicMock()
        await self._fn("get_a2a_agent_stored_card")("agent-1", MagicMock(), 3, MagicMock(), {"email": "u@example.com"})
        assert route.get_stored_card.await_args.kwargs["version"] == 3

    async def test_audit_action_names(self, monkeypatch):
        audit = MagicMock()
        monkeypatch.setattr(main, "get_audit_trail_service", lambda: audit)
        monkeypatch.setattr(main, "get_request_identity", lambda request, user: ("u@example.com", False))
        request = MagicMock()
        request.client.host = "127.0.0.1"
        for status, action in (("applied", "apply_a2a_card"), ("rejected", "reject_a2a_card")):
            main._audit_a2a_card_decision(request, {}, "agent-1", MagicMock(status=status, version=2, applied_fields=[]))
            assert audit.log_action.call_args.kwargs["action"] == action
            assert "db" not in audit.log_action.call_args.kwargs


@pytest.mark.asyncio
class TestSyncLoop:
    """The scheduled loop runs on the primary worker only."""

    async def _run(self, monkeypatch, primary, sync):
        """Run the loop for two sleeps, then cancel it."""
        calls = []

        async def fake_sleep(_seconds):
            calls.append(1)
            if len(calls) > 2:
                raise asyncio.CancelledError

        monkeypatch.setattr(main.asyncio, "sleep", fake_sleep)
        monkeypatch.setattr(main, "is_primary_worker", lambda: primary)
        monkeypatch.setattr(main, "a2a_service", MagicMock(sync_cards=sync))
        with pytest.raises(asyncio.CancelledError):
            await main._run_a2a_card_sync_loop()

    async def test_primary_worker_syncs_on_every_tick(self, monkeypatch):
        sync = AsyncMock(return_value=1)
        await self._run(monkeypatch, True, sync)
        assert sync.await_count == 2

    async def test_other_workers_do_not_sync(self, monkeypatch):
        sync = AsyncMock()
        await self._run(monkeypatch, False, sync)
        sync.assert_not_awaited()

    async def test_a_failed_sync_does_not_stop_the_loop(self, monkeypatch):
        sync = AsyncMock(side_effect=RuntimeError("boom"))
        await self._run(monkeypatch, True, sync)
        assert sync.await_count == 2
