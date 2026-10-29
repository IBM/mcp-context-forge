# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_a2a_card_resync.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for Agent Card re-sync, drift reporting and the apply/decline decision (#4734).
"""

# Standard
from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock

# Third-Party
from fastapi import HTTPException
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# First-Party
from mcpgateway import main
from mcpgateway.db import A2AAgent, A2AAgentCard, Base
from mcpgateway.schemas import A2ACardDriftDecision
from mcpgateway.services import a2a_service as a2a_service_module
from mcpgateway.services.a2a_card_drift import diff_cards
from mcpgateway.services.a2a_card_import import CardResponse
from mcpgateway.services.a2a_service import A2AAgentError, A2AAgentService

ENDPOINT = "https://agent.example.com/rpc"
CARD = {
    "name": "weather",
    "description": "Forecasts",
    "version": "1.0.0",
    "supportedInterfaces": [{"url": ENDPOINT, "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}],
    "capabilities": {"streaming": False, "pushNotifications": False, "extendedAgentCard": False},
    "defaultInputModes": ["text"],
    "defaultOutputModes": ["text"],
    "skills": [{"id": "forecast", "name": "Forecast", "description": "d", "tags": []}],
    "securitySchemes": {"bearerAuth": {"httpAuthSecurityScheme": {"scheme": "bearer"}}},
    "securityRequirements": [{"schemes": {"bearerAuth": {}}}],
}


def _changed(**updates):
    """Return a copy of the base card with top-level fields replaced."""
    card = deepcopy(CARD)
    card.update(updates)
    return card


class TestDiffCards:
    """Change classification."""

    def test_identical_cards_have_no_changes(self):
        """Equal cards produce an empty report."""
        report = diff_cards(CARD, deepcopy(CARD), ENDPOINT)
        assert report == {"changes": [], "behaviourAffecting": False, "unapplied": []}

    @pytest.mark.parametrize("updates", [{"description": "Better"}, {"skills": []}, {"iconUrl": "https://x/i.png"}, {"defaultOutputModes": ["text", "image/png"]}])
    def test_descriptive_changes_do_not_gate(self, updates):
        """Description, skills, icon and modes apply without confirmation."""
        report = diff_cards(CARD, _changed(**updates), ENDPOINT)
        assert report["changes"] and report["behaviourAffecting"] is False

    def test_streaming_change_is_gated(self):
        """A change to capabilities.streaming is behaviour-affecting."""
        report = diff_cards(CARD, _changed(capabilities={**CARD["capabilities"], "streaming": True}), ENDPOINT)
        assert report["behaviourAffecting"] is True
        assert [(c["path"], c["before"], c["after"]) for c in report["changes"]] == [("capabilities.streaming", False, True)]

    def test_interface_change_is_gated_and_endpoint_is_unapplied(self):
        """A new interface URL is gated and reported as a setting that apply never rewrites."""
        moved = [{"url": "https://new.example.com/rpc", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}]
        report = diff_cards(CARD, _changed(supportedInterfaces=moved), ENDPOINT)
        assert report["behaviourAffecting"] is True and report["unapplied"] == ["endpoint_url"]

    def test_protocol_version_change_is_gated(self):
        """A new protocolVersion lives in the interfaces, so it is gated."""
        upgraded = [{"url": ENDPOINT, "protocolBinding": "JSONRPC", "protocolVersion": "1.1"}]
        assert diff_cards(CARD, _changed(supportedInterfaces=upgraded), ENDPOINT)["behaviourAffecting"] is True

    def test_security_change_is_gated_and_auth_is_unapplied(self):
        """A new security scheme is gated and reported as auth that apply never rewrites."""
        report = diff_cards(CARD, _changed(securitySchemes={"k": {"apiKeySecurityScheme": {"location": "header", "name": "X-K"}}}, securityRequirements=[{"schemes": {"k": {}}}]), ENDPOINT)
        assert report["behaviourAffecting"] is True and report["unapplied"] == ["auth"]

    def test_added_and_removed_fields_are_labelled(self):
        """Added and removed fields carry only the side that exists."""
        report = diff_cards(CARD, {**{k: v for k, v in CARD.items() if k != "description"}, "documentationUrl": "https://docs"}, ENDPOINT)
        by_path = {c["path"]: c for c in report["changes"]}
        assert by_path["description"]["change"] == "removed" and "after" not in by_path["description"]
        assert by_path["documentationUrl"]["change"] == "added" and "before" not in by_path["documentationUrl"]

    def test_legacy_format_of_same_card_has_no_gated_drift(self):
        """A 0.3 card that says the same thing as the 1.0 card reports no interface or streaming drift."""
        legacy = {
            "name": "weather",
            "description": "Forecasts",
            "version": "1.0.0",
            "url": ENDPOINT,
            "protocolVersion": "1.0",
            "capabilities": {"streaming": False, "pushNotifications": False},
            "defaultInputModes": ["text"],
            "defaultOutputModes": ["text"],
            "skills": CARD["skills"],
        }
        paths = {c["path"] for c in diff_cards(CARD, legacy, ENDPOINT)["changes"] if c["behaviourAffecting"]}
        assert paths <= {"securitySchemes", "securityRequirements"}


@pytest.fixture
def db():
    """In-memory database with one agent and its applied version 1 card."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(
        A2AAgent(
            id="agent-1",
            name="weather-local",
            slug="weather-local",
            endpoint_url=ENDPOINT,
            agent_type="generic",
            protocol_version="1.0",
            capabilities={"streaming": False, "skills": CARD["skills"], "custom": "keep"},
            visibility="public",
        )
    )
    session.add(A2AAgentCard(a2a_agent_id="agent-1", version=1, card=CARD, detected_version="1.0", source_url=ENDPOINT + "/.well-known/agent-card.json", etag='"v1"', max_age=60))
    session.commit()
    yield session
    session.close()


@pytest.fixture
def service(monkeypatch):
    """A service whose registry cache is a stub."""
    cache = MagicMock()
    cache.invalidate_agents = AsyncMock()
    monkeypatch.setattr(a2a_service_module, "_get_registry_cache", lambda: cache)
    return A2AAgentService()


def _remote(monkeypatch, response: CardResponse) -> AsyncMock:
    """Make the stored card's source return ``response``."""
    refetch = AsyncMock(return_value=response)
    monkeypatch.setattr(a2a_service_module, "refetch_card", refetch)
    return refetch


def _rows(db):
    """Return (version, status) of every stored card."""
    return [(r.version, r.status) for r in db.query(A2AAgentCard).order_by(A2AAgentCard.version)]


@pytest.mark.asyncio
class TestResync:
    """Re-fetching the stored card."""

    async def test_sends_stored_etag_and_reports_304_as_unchanged(self, db, service, monkeypatch):
        """A 304 changes nothing and the conditional request carries the stored ETag."""
        refetch = _remote(monkeypatch, CardResponse(304))
        result = await service.resync_agent_card(db, "agent-1")
        assert result.outcome == "unchanged" and result.drifted is False
        refetch.assert_awaited_once_with(ENDPOINT + "/.well-known/agent-card.json", '"v1"')
        assert _rows(db) == [(1, "applied")]

    async def test_identical_document_refreshes_validators_only(self, db, service, monkeypatch):
        """The same card with a new ETag adds no version."""
        _remote(monkeypatch, CardResponse(200, deepcopy(CARD), '"v2"', 120))
        result = await service.resync_agent_card(db, "agent-1")
        assert result.outcome == "unchanged"
        row = db.query(A2AAgentCard).one()
        assert (row.etag, row.max_age) == ('"v2"', 120)

    async def test_descriptive_change_applies_and_syncs_capabilities(self, db, service, monkeypatch):
        """A new skill list applies at once, keeps history, and leaves unrelated capabilities alone."""
        skills = [{"id": "new", "name": "New", "description": "d", "tags": []}]
        _remote(monkeypatch, CardResponse(200, _changed(skills=skills, description="Better"), '"v2"', 60))
        result = await service.resync_agent_card(db, "agent-1")

        assert (result.outcome, result.version, result.drifted) == ("applied", 2, False)
        assert _rows(db) == [(1, "applied"), (2, "applied")]
        agent = db.get(A2AAgent, "agent-1")
        assert agent.capabilities["skills"] == skills and agent.capabilities["custom"] == "keep"
        assert agent.name == "weather-local" and agent.endpoint_url == ENDPOINT

    async def test_behaviour_change_is_held_and_agent_keeps_serving(self, db, service, monkeypatch):
        """A streaming change becomes a pending drift; the agent and the current card do not change."""
        _remote(monkeypatch, CardResponse(200, _changed(capabilities={**CARD["capabilities"], "streaming": True}), '"v2"', 60))
        result = await service.resync_agent_card(db, "agent-1")

        assert (result.outcome, result.version, result.drifted) == ("drifted", 1, True)
        assert _rows(db) == [(1, "applied"), (2, "pending")]
        assert db.get(A2AAgent, "agent-1").capabilities["streaming"] is False
        stored = await _stored(service, db, monkeypatch)
        assert stored.version == 1 and stored.drifted is True and stored.drift.status == "pending" and stored.drift.version == 2
        assert stored.drift.report["behaviourAffecting"] is True

    async def test_same_drift_twice_adds_no_row(self, db, service, monkeypatch):
        """Re-syncing an unchanged remote card does not stack drift rows."""
        drifted = _changed(capabilities={**CARD["capabilities"], "streaming": True})
        _remote(monkeypatch, CardResponse(200, drifted, '"v2"', 60))
        await service.resync_agent_card(db, "agent-1")
        await service.resync_agent_card(db, "agent-1")
        assert _rows(db) == [(1, "applied"), (2, "pending")]

    async def test_newer_drift_replaces_older_drift(self, db, service, monkeypatch):
        """A second, different drift replaces the first open one."""
        _remote(monkeypatch, CardResponse(200, _changed(capabilities={**CARD["capabilities"], "streaming": True}), None, None))
        await service.resync_agent_card(db, "agent-1")
        _remote(monkeypatch, CardResponse(200, _changed(supportedInterfaces=[{"url": ENDPOINT, "protocolBinding": "JSONRPC", "protocolVersion": "1.1"}]), None, None))
        await service.resync_agent_card(db, "agent-1")
        assert _rows(db) == [(1, "applied"), (3, "pending")]

    async def test_remote_reverting_clears_drift(self, db, service, monkeypatch):
        """When the remote card matches the applied card again, the agent is no longer drifted."""
        _remote(monkeypatch, CardResponse(200, _changed(capabilities={**CARD["capabilities"], "streaming": True}), None, None))
        await service.resync_agent_card(db, "agent-1")
        _remote(monkeypatch, CardResponse(200, deepcopy(CARD), None, None))
        result = await service.resync_agent_card(db, "agent-1")
        assert result.drifted is False and _rows(db) == [(1, "applied")]

    @pytest.mark.parametrize("response", [CardResponse(None), CardResponse(500), CardResponse(404), CardResponse(200, None), CardResponse(200, ["not", "a", "card"])])
    async def test_failed_refetch_raises_and_changes_nothing(self, db, service, monkeypatch, response):
        """Any failed re-fetch raises one generic error and leaves the rows alone."""
        _remote(monkeypatch, response)
        with pytest.raises(A2AAgentError, match="could not be re-fetched"):
            await service.resync_agent_card(db, "agent-1")
        assert _rows(db) == [(1, "applied")]

    async def test_agent_without_stored_card_is_rejected(self, db, service, monkeypatch):
        """A hand-registered agent has nothing to re-sync."""
        db.query(A2AAgentCard).delete()
        db.commit()
        refetch = _remote(monkeypatch, CardResponse(304))
        with pytest.raises(A2AAgentError, match="no stored"):
            await service.resync_agent_card(db, "agent-1")
        refetch.assert_not_awaited()

    async def test_non_owner_is_denied_before_any_fetch(self, db, service, monkeypatch):
        """Only the owner can re-sync; a denied caller triggers no outbound request."""
        refetch = _remote(monkeypatch, CardResponse(304))
        monkeypatch.setattr("mcpgateway.services.permission_service.PermissionService.check_resource_ownership", AsyncMock(return_value=False))
        with pytest.raises(PermissionError):
            await service.resync_agent_card(db, "agent-1", user_email="other@example.com")
        refetch.assert_not_awaited()


async def _stored(service, db, monkeypatch):
    """Read the stored card with visibility checks stubbed out."""
    monkeypatch.setattr(service, "get_agent", AsyncMock())
    return await service.get_stored_card(db, "agent-1")


@pytest.mark.asyncio
class TestDecision:
    """Apply or decline a drifted card."""

    @staticmethod
    async def _drift(db, service, monkeypatch, **updates):
        """Create an open drift by re-syncing a changed remote card."""
        interfaces = [{"url": "https://moved.example.com/rpc", "protocolBinding": "JSONRPC", "protocolVersion": "1.1"}]
        card = _changed(supportedInterfaces=interfaces, capabilities={**CARD["capabilities"], "streaming": True}, **updates)
        _remote(monkeypatch, CardResponse(200, card, '"v2"', 60))
        await service.resync_agent_card(db, "agent-1")
        return card

    async def test_apply_syncs_card_owned_fields_but_not_endpoint_or_auth(self, db, service, monkeypatch):
        """Applying copies protocol version and capabilities and never rewrites endpoint_url."""
        await self._drift(db, service, monkeypatch)
        result = await service.decide_card_drift(db, "agent-1", "apply")

        assert (result.outcome, result.version, result.drifted) == ("applied", 2, False)
        assert _rows(db) == [(1, "applied"), (2, "applied")]
        agent = db.get(A2AAgent, "agent-1")
        assert agent.protocol_version == "1.1" and agent.capabilities["streaming"] is True and agent.capabilities["custom"] == "keep"
        assert agent.endpoint_url == ENDPOINT
        assert result.report["unapplied"] == ["endpoint_url"]

    async def test_decline_keeps_agent_usable_and_marked_drifted(self, db, service, monkeypatch):
        """Declining keeps the current card, leaves the agent unchanged, and keeps it drifted."""
        await self._drift(db, service, monkeypatch)
        result = await service.decide_card_drift(db, "agent-1", "decline")

        assert (result.outcome, result.version, result.drifted) == ("drifted", 1, True)
        assert _rows(db) == [(1, "applied"), (2, "declined")]
        assert db.get(A2AAgent, "agent-1").protocol_version == "1.0"
        stored = await _stored(service, db, monkeypatch)
        assert stored.drifted is True and stored.drift.status == "declined"

    async def test_declined_drift_is_not_re_proposed_for_same_card(self, db, service, monkeypatch):
        """Re-syncing the same remote card after a decline keeps the decline."""
        card = await self._drift(db, service, monkeypatch)
        await service.decide_card_drift(db, "agent-1", "decline")
        _remote(monkeypatch, CardResponse(200, card, '"v2"', 60))
        result = await service.resync_agent_card(db, "agent-1")
        assert result.drifted is True and _rows(db) == [(1, "applied"), (2, "declined")]

    async def test_decision_without_drift_is_rejected(self, db, service):
        """Deciding when nothing awaits a decision fails."""
        with pytest.raises(A2AAgentError, match="awaiting a decision"):
            await service.decide_card_drift(db, "agent-1", "apply")

    async def test_non_owner_cannot_decide(self, db, service, monkeypatch):
        """Only the owner can apply or decline."""
        await self._drift(db, service, monkeypatch)
        monkeypatch.setattr("mcpgateway.services.permission_service.PermissionService.check_resource_ownership", AsyncMock(return_value=False))
        with pytest.raises(PermissionError):
            await service.decide_card_drift(db, "agent-1", "apply", user_email="other@example.com")
        assert _rows(db) == [(1, "applied"), (2, "pending")]


@pytest.mark.asyncio
class TestRoutes:
    """Deny paths for the re-sync routes."""

    @pytest.mark.parametrize("route", ["resync", "decide"])
    async def test_denied_without_a2a_update(self, monkeypatch, route):
        """A caller lacking a2a.update gets 403 and the service is not reached."""
        permission_service = MagicMock()
        permission_service.check_permission = AsyncMock(return_value=False)
        monkeypatch.setattr("mcpgateway.middleware.rbac.PermissionService", lambda db: permission_service)
        monkeypatch.setattr("mcpgateway.plugins.get_plugin_manager", AsyncMock(return_value=None))
        service = MagicMock()
        service.resync_agent_card = AsyncMock()
        service.decide_card_drift = AsyncMock()
        monkeypatch.setattr(main, "a2a_service", service)
        user = {"email": "u@example.com", "db": MagicMock()}

        with pytest.raises(HTTPException) as exc_info:
            if route == "resync":
                await main.resync_a2a_agent_card("agent-1", db=MagicMock(), user=user)
            else:
                await main.decide_a2a_agent_card_drift("agent-1", A2ACardDriftDecision(decision="apply"), db=MagicMock(), user=user)

        assert exc_info.value.status_code == 403
        service.resync_agent_card.assert_not_awaited()
        service.decide_card_drift.assert_not_awaited()


def test_decision_must_be_apply_or_decline():
    """Any other decision value fails validation."""
    with pytest.raises(ValueError):
        A2ACardDriftDecision(decision="maybe")
