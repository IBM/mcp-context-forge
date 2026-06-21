# -*- coding: utf-8 -*-
"""Tests for the A2A-association CRUD authorization wiring (Phase A T20 + Phase 2 hardening).

Location: ./tests/unit/mcpgateway/services/test_server_service_a2a_auth.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

Pins the contract between :func:`_authorize_a2a_associations` (in
:mod:`mcpgateway.services.server_service`) and the centralized policy
function
:func:`mcpgateway.services.a2a_access_policy.can_associate_a2a_agent_with_server`.

Three properties under test:

1. **System-context bypass** (now explicit): when ``caller_context.is_system``
   is ``True``, NO authorization check runs. ``CallerContext.system()`` is
   the only way to opt in; the old "both Nones means system" magic is
   gone. ``CallerContext.for_user(None, [])`` is NOT a system context —
   it represents an anonymous public-only caller and the policy check
   runs (and will correctly deny non-public access).

2. **Allow path**: when the caller can see BOTH the server AND each
   agent being added, the helper returns silently and the binding
   proceeds.

3. **Deny path**: when the caller cannot see EITHER the server OR any
   agent being added, the helper raises :class:`ServerError` with a
   GENERIC message (no leak about which side denied).

Metis M4 boundary tests are folded into the SystemContext class to
prove the old magic-two-Nones interpretation is fully gone.
"""

from __future__ import annotations

from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcpgateway.services.caller_context import CallerContext
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
    """Bypass fires ONLY for CallerContext.system(). Other shapes run the check."""

    @pytest.mark.asyncio
    async def test_bypass_fires_for_explicit_system_context(self) -> None:
        """``CallerContext.system()`` → no policy call (explicit opt-in bypass).

        Patches the policy function to detect any call — if invoked, the
        bypass contract is broken.
        """
        with patch("mcpgateway.services.a2a_access_policy.can_associate_a2a_agent_with_server", new_callable=AsyncMock) as policy_mock:
            await _authorize_a2a_associations(
                db=MagicMock(),
                db_server=_server(),
                agents=[_agent()],
                caller_context=CallerContext.system(),
            )
            policy_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_bypass_does_NOT_fire_for_anonymous_public_only_caller(self) -> None:
        """``CallerContext.for_user(None, [])`` is NOT a system context.

        Metis M4 boundary: a public-only token with no email is a real
        anonymous caller, not a system call. The policy check runs and
        will deny non-public access correctly. This is the test that
        proves the old "both Nones means system" interpretation is
        fully gone.
        """
        with patch("mcpgateway.services.a2a_access_policy.can_associate_a2a_agent_with_server", new_callable=AsyncMock, return_value=False) as policy_mock:
            with pytest.raises(ServerError):
                await _authorize_a2a_associations(
                    db=MagicMock(),
                    db_server=_server(),
                    agents=[_agent()],
                    caller_context=CallerContext.for_user(None, []),
                )
            policy_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_bypass_does_NOT_fire_for_admin_email_with_none_teams(self) -> None:
        """``CallerContext.for_user('admin@x', None)`` runs the check (admin context).

        Metis M4 boundary: a user_email with token_teams=None is the
        authenticated-admin shape (JWT had no teams claim). The policy
        function decides whether the admin bypass applies inside
        ``_check_agent_access``; the auth-helper does NOT short-circuit.
        """
        with patch("mcpgateway.services.a2a_access_policy.can_associate_a2a_agent_with_server", new_callable=AsyncMock, return_value=True) as policy_mock:
            await _authorize_a2a_associations(
                db=MagicMock(),
                db_server=_server(),
                agents=[_agent()],
                caller_context=CallerContext.for_user("admin@example.com", None),
            )
            policy_mock.assert_awaited_once()
            kwargs = policy_mock.await_args.kwargs
            assert kwargs["user_email"] == "admin@example.com"
            assert kwargs["token_teams"] is None


class TestAuthorizeA2AAssociationsAllowPath:
    """When the caller can see both, the helper returns without raising."""

    @pytest.mark.asyncio
    async def test_returns_silently_when_policy_grants(self) -> None:
        """``for_user`` context + policy True → helper returns silently."""
        with patch("mcpgateway.services.a2a_access_policy.can_associate_a2a_agent_with_server", new_callable=AsyncMock, return_value=True) as policy_mock:
            await _authorize_a2a_associations(
                db=MagicMock(),
                db_server=_server(),
                agents=[_agent()],
                caller_context=CallerContext.for_user("caller@example.com", ["t1"]),
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
                caller_context=CallerContext.for_user("caller@example.com", []),
            )
            assert policy_mock.await_count == 2


class TestAuthorizeA2AAssociationsDenyPath:
    """When the policy denies for any agent, the helper raises ServerError."""

    @pytest.mark.asyncio
    async def test_raises_server_error_on_single_agent_denial(self) -> None:
        """``for_user`` context + policy False → ServerError raised."""
        with patch("mcpgateway.services.a2a_access_policy.can_associate_a2a_agent_with_server", new_callable=AsyncMock, return_value=False):
            with pytest.raises(ServerError, match="Cannot associate A2A agent"):
                await _authorize_a2a_associations(
                    db=MagicMock(),
                    db_server=_server(),
                    agents=[_agent()],
                    caller_context=CallerContext.for_user("caller@example.com", []),
                )

    @pytest.mark.asyncio
    async def test_error_message_is_generic_no_agent_or_server_leak(self) -> None:
        """Side-channel guard: the error message contains NEITHER agent name NOR server name.

        Revealing which side denied would let a caller enumerate agents
        or servers they cannot see.
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
                    caller_context=CallerContext.for_user("caller@example.com", []),
                )
            msg = str(exc_info.value)
            assert "leak-me-agent-name" not in msg
            assert "leak-me-server-name" not in msg

    @pytest.mark.asyncio
    async def test_short_circuits_on_first_denial(self) -> None:
        """First denial in a list → no further policy calls.

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
                    caller_context=CallerContext.for_user("caller@example.com", []),
                )
            assert policy_mock.await_count == 1


class TestCallerContextFactories:
    """:class:`CallerContext` factory methods produce the documented shapes."""

    def test_system_factory_has_is_system_true(self) -> None:
        ctx = CallerContext.system()
        assert ctx.is_system is True
        assert ctx.user_email is None
        assert ctx.token_teams is None

    def test_for_user_factory_has_is_system_false(self) -> None:
        ctx = CallerContext.for_user("u@x.com", ["t1"])
        assert ctx.is_system is False
        assert ctx.user_email == "u@x.com"
        assert ctx.token_teams == ["t1"]

    def test_for_user_anonymous_is_NOT_system(self) -> None:
        """``CallerContext.for_user(None, [])`` (anonymous public-only) is NOT system.

        This is the test that locks in the Momus Block 2 hardening:
        anonymous callers are NOT automatically system callers; the
        explicit ``.system()`` factory is the only way to opt in.
        """
        ctx = CallerContext.for_user(None, [])
        assert ctx.is_system is False

    def test_caller_context_is_frozen(self) -> None:
        """Once constructed, ``CallerContext`` cannot be mutated."""
        ctx = CallerContext.for_user("u@x.com", ["t1"])
        with pytest.raises(Exception):  # FrozenInstanceError
            ctx.user_email = "evil@x.com"  # type: ignore[misc]
