# -*- coding: utf-8 -*-
"""Tests for native A2A passthrough helpers in :mod:`mcpgateway.services.a2a_service`.

Location: ./tests/unit/mcpgateway/services/test_a2a_service_native.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

Covers the helpers added by plan T3:

- :py:meth:`A2AAgentService.check_server_a2a_membership` — pure query
  against ``server_a2a_association``.
- :py:meth:`A2AAgentService.resolve_agent_for_dispatch` — name lookup
  with optional v-server membership + Layer-1 visibility enforcement.

Visibility semantics (plan D11 / Oracle v2 #3): a visibility miss surfaces
as :py:class:`A2AAgentNotFoundError`, NOT a separate permission error.
That keeps the wire shape uniform for callers and prevents existence-leak
side channels.

Membership semantics (plan F1 + D14): a foreign-agent miss at
``/servers/{X}/a2a/{foreign}`` raises :py:class:`AgentNotInServerError`
which the route layer translates to HTTP 404, behaviorally indistinguishable
from a name-not-found from the caller's perspective.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.services.a2a_service import (
    A2AAgentNotFoundError,
    A2AAgentService,
    AgentNotInServerError,
)


@pytest.fixture
def service() -> A2AAgentService:
    """Return a fresh :py:class:`A2AAgentService` instance."""
    return A2AAgentService()


def _mock_agent(agent_id: str = "agt-1", name: str = "echo", visibility: str = "public") -> MagicMock:
    """Build a MagicMock DbA2AAgent stub for resolve tests.

    Args:
        agent_id: ID to set on the stub.
        name: Name to set on the stub.
        visibility: Visibility to set on the stub.

    Returns:
        MagicMock: agent stub with the named attributes.
    """
    agent = MagicMock()
    agent.id = agent_id
    agent.name = name
    agent.visibility = visibility
    agent.team_id = None
    agent.owner_email = None
    return agent


class TestCheckServerA2AMembership:
    """Plan T3: ``check_server_a2a_membership`` returns True/False from row presence."""

    @pytest.mark.asyncio
    async def test_returns_true_when_row_exists(self, service: A2AAgentService) -> None:
        """A non-zero count means the agent is in the server."""
        db = MagicMock()
        db.execute.return_value.scalar.return_value = 1
        result = await service.check_server_a2a_membership(db, "srv-1", "agt-1")
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_row_missing(self, service: A2AAgentService) -> None:
        """A zero count means the agent is NOT in the server."""
        db = MagicMock()
        db.execute.return_value.scalar.return_value = 0
        result = await service.check_server_a2a_membership(db, "srv-1", "agt-2")
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_scalar_returns_none(self, service: A2AAgentService) -> None:
        """A None count (defensive — should not happen on COUNT, but guards the codepath)."""
        db = MagicMock()
        db.execute.return_value.scalar.return_value = None
        result = await service.check_server_a2a_membership(db, "srv-1", "agt-1")
        assert result is False


class TestResolveAgentForDispatch:
    """Plan T3: 6 scenarios per the acceptance criteria."""

    @pytest.mark.asyncio
    async def test_missing_agent_raises_not_found(self, service: A2AAgentService) -> None:
        """Name not in DB → :py:class:`A2AAgentNotFoundError`."""
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = None
        with pytest.raises(A2AAgentNotFoundError) as exc_info:
            await service.resolve_agent_for_dispatch(db, "missing")
        assert "missing" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_bare_lookup_admin_bypass(self, service: A2AAgentService) -> None:
        """No server_id + admin bypass (both user_email + token_teams None) → returns agent."""
        agent = _mock_agent(visibility="public")
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = agent
        result = await service.resolve_agent_for_dispatch(db, "echo", user_email=None, token_teams=None)
        assert result is agent

    @pytest.mark.asyncio
    async def test_valid_membership_with_server_id(self, service: A2AAgentService) -> None:
        """server_id provided + agent IS in server + visible → returns agent."""
        agent = _mock_agent(visibility="public")
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = agent
        with patch.object(service, "check_server_a2a_membership", new=AsyncMock(return_value=True)):
            result = await service.resolve_agent_for_dispatch(db, "echo", server_id="srv-1", user_email=None, token_teams=None)
            assert result is agent

    @pytest.mark.asyncio
    async def test_invalid_membership_raises(self, service: A2AAgentService) -> None:
        """server_id provided + agent NOT in server → :py:class:`AgentNotInServerError`."""
        agent = _mock_agent()
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = agent
        with patch.object(service, "check_server_a2a_membership", new=AsyncMock(return_value=False)):
            with pytest.raises(AgentNotInServerError) as exc_info:
                await service.resolve_agent_for_dispatch(db, "echo", server_id="srv-X", user_email=None, token_teams=None)
            assert exc_info.value.agent_name == "echo"
            assert exc_info.value.server_id == "srv-X"

    @pytest.mark.asyncio
    async def test_visibility_deny_raises_not_found(self, service: A2AAgentService) -> None:
        """Visibility deny surfaces as :py:class:`A2AAgentNotFoundError`, NOT permission error.

        Per plan D11 / Oracle v2 #3: same wire outcome as name-not-found.
        """
        agent = _mock_agent(visibility="team")
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = agent
        with patch.object(service, "_check_agent_access", new=AsyncMock(return_value=False)):
            with pytest.raises(A2AAgentNotFoundError):
                await service.resolve_agent_for_dispatch(db, "echo", user_email="user@example.com", token_teams=[])

    @pytest.mark.asyncio
    async def test_membership_checked_before_visibility(self, service: A2AAgentService) -> None:
        """Membership miss raises :py:class:`AgentNotInServerError` BEFORE visibility check.

        Important so we don't leak agent existence at
        ``/servers/{X}/a2a/foreign-agent`` — a foreign agent who is otherwise
        visible to the caller should still 404 at the v-server-scoped path.
        """
        agent = _mock_agent(visibility="public")
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = agent
        visibility_check = AsyncMock(return_value=True)
        with patch.object(service, "check_server_a2a_membership", new=AsyncMock(return_value=False)), patch.object(service, "_check_agent_access", new=visibility_check):
            with pytest.raises(AgentNotInServerError):
                await service.resolve_agent_for_dispatch(
                    db,
                    "echo",
                    server_id="srv-X",
                    user_email="user@example.com",
                    token_teams=["t1"],
                )
            # Visibility check must NOT fire when membership fails (would
            # be an existence-leak — caller could infer the agent exists
            # somewhere via timing or side effects).
            visibility_check.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_server_id_skips_membership_check(self, service: A2AAgentService) -> None:
        """When ``server_id`` is None, membership check is bypassed entirely."""
        agent = _mock_agent(visibility="public")
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = agent
        membership_check = AsyncMock(return_value=False)
        with patch.object(service, "check_server_a2a_membership", new=membership_check):
            result = await service.resolve_agent_for_dispatch(db, "echo", server_id=None, user_email=None, token_teams=None)
            assert result is agent
            membership_check.assert_not_called()
