# -*- coding: utf-8 -*-
"""Tests for the centralized A2A access-decision policy module (Plan T16 Phase A).

Location: ./tests/unit/mcpgateway/services/test_a2a_access_policy.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

These tests pin the contract of
:mod:`mcpgateway.services.a2a_access_policy` so the policy module's
behaviour stays stable when the rules-engine migration arrives. The
contract has three parts per the plan amendment:

- :func:`can_view_a2a_agent_directly` — single-level: agent visibility
  primitive only.
- :func:`can_view_a2a_agent_in_server_context` — three-level
  conjunctive: server visibility AND membership AND agent visibility,
  evaluated cheapest-first to minimize timing side-channels.
- :func:`can_associate_a2a_agent_with_server` — CRUD authorization:
  server visibility AND agent visibility (no membership check — the
  call is what CREATES the membership).

The 3-check function's ordering matters for side-channels, so we
assert it explicitly via short-circuit tests.
"""

from __future__ import annotations

from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from mcpgateway.services.a2a_access_policy import (
    can_associate_a2a_agent_with_server,
    can_view_a2a_agent_directly,
    can_view_a2a_agent_in_server_context,
)
from mcpgateway.services.a2a_hooks import A2AAgentSnapshot


def _agent_snapshot(visibility: str = "public", team_id: Optional[str] = None, owner_email: Optional[str] = None) -> A2AAgentSnapshot:
    """Build an A2AAgentSnapshot with visibility-relevant attrs (Amendment G)."""
    return A2AAgentSnapshot(
        id="agt-1",
        name="echo",
        team_id=team_id,
        visibility=visibility,
        enabled=True,
        tags=[],
        owner_email=owner_email,
        oauth_config=None,
        oauth_enabled=False,
        passthrough_headers=None,
        auth_type=None,
    )


def _server(visibility: str = "public", team_id: Optional[str] = None, owner_email: Optional[str] = None) -> MagicMock:
    """Build a MagicMock DbServer with the visibility-relevant attrs."""
    server = MagicMock()
    server.id = "srv-1"
    server.visibility = visibility
    server.team_id = team_id
    server.owner_email = owner_email
    return server


def _service(agent_allowed: bool = True, member: bool = True) -> MagicMock:
    """Build a MagicMock A2AAgentService with controllable primitives.

    Returns an instance whose ``_check_agent_access`` and
    ``check_server_a2a_membership`` are AsyncMocks; tests inspect
    ``await_count`` to verify short-circuit ordering.
    """
    svc = MagicMock()
    svc._check_agent_access = AsyncMock(return_value=agent_allowed)
    svc.check_server_a2a_membership = AsyncMock(return_value=member)
    return svc


class TestCanViewAgentDirectly:
    """Single-level decision: only agent visibility matters."""

    @pytest.mark.asyncio
    async def test_returns_true_when_agent_visible(self) -> None:
        svc = _service(agent_allowed=True)
        result = await can_view_a2a_agent_directly(
            db=MagicMock(),
            agent_snapshot=_agent_snapshot(),
            user_email="u@x.com",
            token_teams=["t1"],
            a2a_service=svc,
        )
        assert result is True
        svc._check_agent_access.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_false_when_agent_hidden(self) -> None:
        svc = _service(agent_allowed=False)
        result = await can_view_a2a_agent_directly(
            db=MagicMock(),
            agent_snapshot=_agent_snapshot(visibility="team"),
            user_email="u@x.com",
            token_teams=[],  # public-only token
            a2a_service=svc,
        )
        assert result is False


class TestCanViewAgentInServerContext:
    """Three-level conjunctive decision: server AND membership AND agent."""

    @pytest.mark.asyncio
    async def test_returns_true_when_all_three_pass(self) -> None:
        svc = _service(agent_allowed=True, member=True)
        result = await can_view_a2a_agent_in_server_context(
            db=MagicMock(),
            agent_snapshot=_agent_snapshot(),
            server=_server(),  # public server
            user_email="u@x.com",
            token_teams=["t1"],
            a2a_service=svc,
        )
        assert result is True
        svc.check_server_a2a_membership.assert_awaited_once()
        svc._check_agent_access.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_server_invisible_short_circuits_membership_and_agent(self) -> None:
        """Server-visibility denial MUST short-circuit (no DB queries downstream).

        This is the cheap-first ordering invariant: a private server
        with a non-owner caller produces False without ever calling
        check_server_a2a_membership or _check_agent_access.
        """
        svc = _service()
        result = await can_view_a2a_agent_in_server_context(
            db=MagicMock(),
            agent_snapshot=_agent_snapshot(),
            server=_server(visibility="private", owner_email="other@x.com"),
            user_email="u@x.com",  # NOT owner
            token_teams=["t1"],
            a2a_service=svc,
        )
        assert result is False
        svc.check_server_a2a_membership.assert_not_awaited()
        svc._check_agent_access.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_membership_denial_short_circuits_agent_visibility(self) -> None:
        """Membership denial MUST short-circuit (no agent-visibility query).

        Mirrors the pre-Phase-A behaviour the existing
        ``test_membership_checked_before_visibility`` unit test relies on:
        when the agent is not in the server, the agent-visibility check
        is never invoked. Also a timing-side-channel guard — the expensive
        team-membership query is skipped on early denial.
        """
        svc = _service(member=False)
        result = await can_view_a2a_agent_in_server_context(
            db=MagicMock(),
            agent_snapshot=_agent_snapshot(),
            server=_server(),  # public server passes step 1
            user_email="u@x.com",
            token_teams=["t1"],
            a2a_service=svc,
        )
        assert result is False
        svc.check_server_a2a_membership.assert_awaited_once()
        svc._check_agent_access.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_agent_visibility_denial_returns_false_after_first_two_pass(self) -> None:
        """Agent-visibility denial returns False even when server + membership pass.

        Closes the gap the user direction explicitly forbids: server
        membership does NOT bypass agent visibility.
        """
        svc = _service(agent_allowed=False, member=True)
        result = await can_view_a2a_agent_in_server_context(
            db=MagicMock(),
            agent_snapshot=_agent_snapshot(visibility="team", team_id="other-team"),
            server=_server(),  # public server
            user_email="u@x.com",
            token_teams=["t1"],  # not in agent's team
            a2a_service=svc,
        )
        assert result is False
        svc.check_server_a2a_membership.assert_awaited_once()
        svc._check_agent_access.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_all_denials_collapse_to_false(self) -> None:
        """ALL denial paths return the same ``False`` (no leak about WHICH layer denied).

        This is the wire-level requirement that lets the route layer
        emit a single HTTP 404 for every denial reason per D14.
        """
        # Server-deny
        svc1 = _service()
        r1 = await can_view_a2a_agent_in_server_context(
            db=MagicMock(), agent_snapshot=_agent_snapshot(), server=_server(visibility="private", owner_email="o@x.com"), user_email="u@x.com", token_teams=["t1"], a2a_service=svc1
        )
        # Membership-deny
        svc2 = _service(member=False)
        r2 = await can_view_a2a_agent_in_server_context(db=MagicMock(), agent_snapshot=_agent_snapshot(), server=_server(), user_email="u@x.com", token_teams=["t1"], a2a_service=svc2)
        # Agent-deny
        svc3 = _service(agent_allowed=False)
        r3 = await can_view_a2a_agent_in_server_context(db=MagicMock(), agent_snapshot=_agent_snapshot(), server=_server(), user_email="u@x.com", token_teams=["t1"], a2a_service=svc3)
        assert r1 is False
        assert r2 is False
        assert r3 is False


class TestCanAssociateAgentWithServer:
    """CRUD authorization: server visibility AND agent visibility (no membership)."""

    @pytest.mark.asyncio
    async def test_returns_true_when_user_can_see_both(self) -> None:
        svc = _service(agent_allowed=True)
        result = await can_associate_a2a_agent_with_server(
            db=MagicMock(),
            agent_snapshot=_agent_snapshot(),
            server=_server(),
            user_email="u@x.com",
            token_teams=["t1"],
            a2a_service=svc,
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_server_hidden(self) -> None:
        """User who cannot see the server cannot mutate its membership."""
        svc = _service(agent_allowed=True)
        result = await can_associate_a2a_agent_with_server(
            db=MagicMock(),
            agent_snapshot=_agent_snapshot(),
            server=_server(visibility="private", owner_email="other@x.com"),
            user_email="u@x.com",
            token_teams=["t1"],
            a2a_service=svc,
        )
        assert result is False
        # Server-deny short-circuits the agent visibility check.
        svc._check_agent_access.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_returns_false_when_agent_hidden(self) -> None:
        """User who cannot see the agent cannot expose it through a server.

        Closes the gap where a server admin would otherwise be able to
        surface an agent they have no business surfacing.
        """
        svc = _service(agent_allowed=False)
        result = await can_associate_a2a_agent_with_server(
            db=MagicMock(),
            agent_snapshot=_agent_snapshot(visibility="team", team_id="other-team"),
            server=_server(),
            user_email="u@x.com",
            token_teams=["t1"],
            a2a_service=svc,
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_membership_NOT_consulted(self) -> None:
        """CRUD authorization does NOT call ``check_server_a2a_membership``.

        The CRUD call IS what creates the membership row; pre-checking
        membership would be a logic error.
        """
        svc = _service()
        await can_associate_a2a_agent_with_server(
            db=MagicMock(),
            agent_snapshot=_agent_snapshot(),
            server=_server(),
            user_email="u@x.com",
            token_teams=["t1"],
            a2a_service=svc,
        )
        svc.check_server_a2a_membership.assert_not_awaited()
