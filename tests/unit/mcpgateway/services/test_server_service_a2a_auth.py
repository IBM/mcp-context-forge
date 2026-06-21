# -*- coding: utf-8 -*-
"""Tests for the A2A-association CRUD authorization wiring (Phase A T20).

Location: ./tests/unit/mcpgateway/services/test_server_service_a2a_auth.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

Pins the contract between :func:`_authorize_a2a_associations` (in
:mod:`mcpgateway.services.server_service`) and the centralized policy
function
:func:`mcpgateway.services.a2a_access_policy.can_associate_a2a_agent_with_server`.

Three properties under test:

1. **System-context bypass**: when both ``caller_user_email`` and
   ``caller_token_teams`` are ``None``, NO authorization check runs.
   This is the backward-compatibility escape hatch that lets bootstrap
   / seed / opt-out tests keep working without threading caller
   context.
2. **Allow path**: when the caller can see BOTH the server AND each
   agent being added, the helper returns silently and the binding
   proceeds.
3. **Deny path**: when the caller cannot see EITHER the server OR any
   agent being added, the helper raises :class:`ServerError` with a
   GENERIC message (no leak about which side denied).

These properties together satisfy the user-clarified CRUD rule: "only
users with proper access to a virtual server should be allowed to add
an agent to the server" (extended to also require seeing the agent).
"""

from __future__ import annotations

from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcpgateway.services.server_service import _authorize_a2a_associations, ServerError


def _agent() -> MagicMock:
    agent = MagicMock()
    agent.id = "agt-1"
    agent.name = "echo"
    agent.visibility = "public"
    agent.team_id = None
    agent.owner_email = None
    return agent


def _server() -> MagicMock:
    server = MagicMock()
    server.id = "srv-1"
    server.name = "test-server"
    server.visibility = "public"
    server.team_id = None
    server.owner_email = None
    return server


class TestAuthorizeA2AAssociationsSystemContext:
    """System-context bypass: skip auth when both caller params are None."""

    @pytest.mark.asyncio
    async def test_skips_when_both_caller_params_none(self) -> None:
        """No DB / policy call when caller context is omitted entirely.

        Patches the policy function to detect any call — if invoked, the
        backward-compat contract is broken.
        """
        with patch("mcpgateway.services.a2a_access_policy.can_associate_a2a_agent_with_server", new_callable=AsyncMock) as policy_mock:
            await _authorize_a2a_associations(
                db=MagicMock(),
                db_server=_server(),
                agents=[_agent()],
                caller_user_email=None,
                caller_token_teams=None,
            )
            policy_mock.assert_not_called()


class TestAuthorizeA2AAssociationsAllowPath:
    """When the caller can see both, the helper returns without raising."""

    @pytest.mark.asyncio
    async def test_returns_silently_when_policy_grants(self) -> None:
        """Caller context provided + policy returns True → helper returns None.

        Patches the policy function to always grant. Helper must NOT
        raise. Asserts the policy was called once per agent with the
        expected kwargs.
        """
        with patch("mcpgateway.services.a2a_access_policy.can_associate_a2a_agent_with_server", new_callable=AsyncMock, return_value=True) as policy_mock:
            await _authorize_a2a_associations(
                db=MagicMock(),
                db_server=_server(),
                agents=[_agent()],
                caller_user_email="caller@example.com",
                caller_token_teams=["t1"],
            )
            policy_mock.assert_awaited_once()
            kwargs = policy_mock.await_args.kwargs
            assert kwargs["user_email"] == "caller@example.com"
            assert kwargs["token_teams"] == ["t1"]

    @pytest.mark.asyncio
    async def test_calls_policy_once_per_agent(self) -> None:
        """Two agents → two policy calls."""
        agents = [_agent(), _agent()]
        with patch("mcpgateway.services.a2a_access_policy.can_associate_a2a_agent_with_server", new_callable=AsyncMock, return_value=True) as policy_mock:
            await _authorize_a2a_associations(
                db=MagicMock(),
                db_server=_server(),
                agents=agents,
                caller_user_email="caller@example.com",
                caller_token_teams=[],
            )
            assert policy_mock.await_count == 2


class TestAuthorizeA2AAssociationsDenyPath:
    """When the policy denies for any agent, the helper raises ServerError."""

    @pytest.mark.asyncio
    async def test_raises_server_error_on_single_agent_denial(self) -> None:
        """Single agent + policy returns False → ServerError."""
        with patch("mcpgateway.services.a2a_access_policy.can_associate_a2a_agent_with_server", new_callable=AsyncMock, return_value=False):
            with pytest.raises(ServerError, match="Cannot associate A2A agent"):
                await _authorize_a2a_associations(
                    db=MagicMock(),
                    db_server=_server(),
                    agents=[_agent()],
                    caller_user_email="caller@example.com",
                    caller_token_teams=[],
                )

    @pytest.mark.asyncio
    async def test_error_message_is_generic_no_agent_or_server_leak(self) -> None:
        """The error message MUST NOT include the agent ID or name.

        Side-channel guard: revealing which side denied would let a
        caller enumerate agents or servers they cannot see.
        """
        agent = _agent()
        agent.name = "leak-me-agent-name"
        server = _server()
        server.name = "leak-me-server-name"
        with patch("mcpgateway.services.a2a_access_policy.can_associate_a2a_agent_with_server", new_callable=AsyncMock, return_value=False):
            with pytest.raises(ServerError) as exc_info:
                await _authorize_a2a_associations(
                    db=MagicMock(),
                    db_server=server,
                    agents=[agent],
                    caller_user_email="caller@example.com",
                    caller_token_teams=[],
                )
            msg = str(exc_info.value)
            assert "leak-me-agent-name" not in msg
            assert "leak-me-server-name" not in msg

    @pytest.mark.asyncio
    async def test_short_circuits_on_first_denial(self) -> None:
        """Denial on first agent in a list → no further policy calls.

        Performance + side-channel: deny early so the caller's
        observable latency reflects only the first failure, not the
        sum of all attempted agents.
        """
        agents = [_agent(), _agent(), _agent()]
        with patch("mcpgateway.services.a2a_access_policy.can_associate_a2a_agent_with_server", new_callable=AsyncMock, return_value=False) as policy_mock:
            with pytest.raises(ServerError):
                await _authorize_a2a_associations(
                    db=MagicMock(),
                    db_server=_server(),
                    agents=agents,
                    caller_user_email="caller@example.com",
                    caller_token_teams=[],
                )
            # First call denied; remaining two MUST NOT have been awaited.
            assert policy_mock.await_count == 1
