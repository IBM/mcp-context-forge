# -*- coding: utf-8 -*-
"""Unit tests for the A2A plugin-hook helper module.

Location: ./tests/unit/mcpgateway/services/test_a2a_hooks.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

Covers the extraction at ``mcpgateway/services/a2a_hooks.py`` introduced
post-Wave 7 to back the Amendment F (Phase C) deferral. Pins the
extracted live helpers behave identically to the inline boilerplate they
replaced in :meth:`A2AAgentService.invoke_agent`, and confirms the six
placeholder helpers are callable no-ops today so future Phase C wiring
can swap their bodies without touching call sites.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def fake_agent() -> SimpleNamespace:
    """Snapshot-shaped agent stand-in mirroring DbA2AAgent's public fields."""
    return SimpleNamespace(
        id="agent-uuid",
        name="echo-agent",
        team_id="team-1",
        visibility="public",
        enabled=True,
        tags=["echo"],
        oauth_config=None,
        passthrough_headers=None,
        auth_type=None,
    )


@pytest.fixture
def fake_agent_no_team() -> SimpleNamespace:
    """Agent with no team_id — covers the alternate context-id branch."""
    return SimpleNamespace(
        id="lonely-agent",
        name="lonely",
        team_id=None,
        visibility="public",
        enabled=True,
        tags=[],
        oauth_config=None,
        passthrough_headers=None,
        auth_type=None,
    )


@pytest.fixture
def plugin_manager_factory_recording() -> Tuple[AsyncMock, List[str]]:
    """Factory that records which context_id values were requested.

    Returns a (factory, calls) tuple — assertions can inspect calls.
    """
    calls: List[str] = []
    mock_pm = MagicMock()
    mock_pm.has_hooks_for = MagicMock(return_value=False)

    async def _factory(context_id: str) -> Optional[Any]:
        calls.append(context_id)
        return mock_pm

    return _factory, calls


@pytest.fixture
def plugin_manager_factory_none() -> AsyncMock:
    """Factory that always returns None (no plugin manager available)."""

    async def _factory(context_id: str) -> Optional[Any]:  # pylint: disable=unused-argument
        return None

    return _factory


class TestBuildA2AHookContext:
    """Pin :func:`build_a2a_hook_context` contract."""

    @pytest.mark.asyncio
    async def test_builds_context_with_team_uses_make_context_id(self, fake_agent, plugin_manager_factory_recording):
        """When agent has team_id, the plugin manager is requested by team:name context-id."""
        from mcpgateway.services.a2a_hooks import build_a2a_hook_context

        factory, calls = plugin_manager_factory_recording

        ctx = await build_a2a_hook_context(
            fake_agent,
            correlation_id="corr-1",
            user_email="dev@example.com",
            plugin_manager_factory=factory,
        )

        assert ctx.agent_id == "agent-uuid"
        assert ctx.agent_name == "echo-agent"
        assert ctx.agent_team_id == "team-1"
        assert ctx.correlation_id == "corr-1"
        assert ctx.user_email == "dev@example.com"
        assert ctx.plugin_manager is not None
        assert ctx.context_table == {}
        assert len(calls) == 1
        assert calls[0] != "agent-uuid", "team-scoped context-id should NOT be the raw agent id"

    @pytest.mark.asyncio
    async def test_builds_context_without_team_uses_agent_id(self, fake_agent_no_team, plugin_manager_factory_recording):
        """When agent has no team_id, the plugin manager is requested by raw agent_id."""
        from mcpgateway.services.a2a_hooks import build_a2a_hook_context

        factory, calls = plugin_manager_factory_recording

        ctx = await build_a2a_hook_context(
            fake_agent_no_team,
            correlation_id="corr-2",
            user_email=None,
            plugin_manager_factory=factory,
        )

        assert ctx.agent_team_id is None
        assert calls == ["lonely-agent"]

    @pytest.mark.asyncio
    async def test_returns_frozen_dataclass(self, fake_agent, plugin_manager_factory_none):
        """A2AHookContext is frozen — identifiers can't drift between pre/post."""
        from dataclasses import FrozenInstanceError

        from mcpgateway.services.a2a_hooks import build_a2a_hook_context

        ctx = await build_a2a_hook_context(
            fake_agent,
            correlation_id="corr-3",
            user_email=None,
            plugin_manager_factory=plugin_manager_factory_none,
        )

        with pytest.raises(FrozenInstanceError):
            ctx.agent_id = "different-id"  # type: ignore[misc]

    @pytest.mark.asyncio
    async def test_handles_none_plugin_manager(self, fake_agent, plugin_manager_factory_none):
        """When factory returns None, context is still built but metadata is skipped."""
        from mcpgateway.services.a2a_hooks import build_a2a_hook_context

        ctx = await build_a2a_hook_context(
            fake_agent,
            correlation_id="corr-4",
            user_email=None,
            plugin_manager_factory=plugin_manager_factory_none,
        )

        assert ctx.plugin_manager is None
        assert ctx.global_context is not None


class TestFireA2APreInvokeHook:
    """Pin :func:`fire_a2a_pre_invoke_hook` contract — matches prior inline behavior."""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_plugin_manager(self):
        """No plugin manager → no-op + return None."""
        from mcpgateway.services.a2a_hooks import A2AHookContext, fire_a2a_pre_invoke_hook

        ctx = A2AHookContext(
            agent_id="a1",
            agent_name="a",
            agent_team_id=None,
            correlation_id="c",
            user_email=None,
            plugin_manager=None,
            global_context=MagicMock(),
        )

        result = await fire_a2a_pre_invoke_hook(ctx, parameters={"q": "hi"})
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_hooks_registered(self):
        """Plugin manager present but no PRE_INVOKE hooks → no-op + return None."""
        from mcpgateway.services.a2a_hooks import A2AHookContext, fire_a2a_pre_invoke_hook

        pm = MagicMock()
        pm.has_hooks_for = MagicMock(return_value=False)
        pm.invoke_hook = AsyncMock()

        ctx = A2AHookContext(
            agent_id="a1",
            agent_name="a",
            agent_team_id=None,
            correlation_id="c",
            user_email=None,
            plugin_manager=pm,
            global_context=MagicMock(),
        )

        result = await fire_a2a_pre_invoke_hook(ctx, parameters={"q": "hi"})
        assert result is None
        pm.invoke_hook.assert_not_called()

    @pytest.mark.asyncio
    async def test_fires_when_hooks_registered_and_updates_context_table(self):
        """When PRE_INVOKE has hooks, invoke_hook fires and context_table is updated."""
        from mcpgateway.services.a2a_hooks import A2AHookContext, fire_a2a_pre_invoke_hook

        pm = MagicMock()
        pm.has_hooks_for = MagicMock(return_value=True)
        pre_result = MagicMock()
        pre_result.modified_payload = None
        new_table = {"plugin_state": "set"}
        pm.invoke_hook = AsyncMock(return_value=(pre_result, new_table))

        ctx = A2AHookContext(
            agent_id="a1",
            agent_name="a",
            agent_team_id=None,
            correlation_id="c",
            user_email=None,
            plugin_manager=pm,
            global_context=MagicMock(),
        )

        result = await fire_a2a_pre_invoke_hook(ctx, parameters={"q": "hi"})

        assert result is pre_result
        pm.invoke_hook.assert_called_once()
        assert ctx.context_table == {"plugin_state": "set"}


class TestFireA2APostInvokeHook:
    """Pin :func:`fire_a2a_post_invoke_hook` non-blocking contract."""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_plugin_manager(self):
        from mcpgateway.services.a2a_hooks import A2AHookContext, fire_a2a_post_invoke_hook

        ctx = A2AHookContext(
            agent_id="a1",
            agent_name="a",
            agent_team_id=None,
            correlation_id="c",
            user_email=None,
            plugin_manager=None,
            global_context=MagicMock(),
        )

        result = await fire_a2a_post_invoke_hook(ctx, response={"ok": True}, success=True)
        assert result is None

    @pytest.mark.asyncio
    async def test_swallows_exceptions(self):
        """A misbehaving POST plugin must never propagate — invocation already succeeded."""
        from mcpgateway.services.a2a_hooks import A2AHookContext, fire_a2a_post_invoke_hook

        pm = MagicMock()
        pm.has_hooks_for = MagicMock(return_value=True)
        pm.invoke_hook = AsyncMock(side_effect=RuntimeError("plugin crashed"))

        ctx = A2AHookContext(
            agent_id="a1",
            agent_name="a",
            agent_team_id=None,
            correlation_id="c",
            user_email=None,
            plugin_manager=pm,
            global_context=MagicMock(),
        )

        # Must NOT raise — RuntimeError is swallowed and logged.
        result = await fire_a2a_post_invoke_hook(ctx, response={"ok": True}, success=True)
        assert result is None


class TestPlaceholderHooks:
    """Pin the six Amendment F placeholder helpers are callable no-ops today."""

    @pytest.mark.asyncio
    async def test_fire_a2a_card_pre_hook_no_op_when_pm_none(self):
        from mcpgateway.services.a2a_hooks import fire_a2a_card_pre_hook

        await fire_a2a_card_pre_hook(
            None,
            agent_name="echo",
            server_id=None,
            public_base_url="http://gateway",
            caller_email=None,
        )

    @pytest.mark.asyncio
    async def test_fire_a2a_card_pre_hook_logs_when_pm_set(self, caplog):
        import logging

        from mcpgateway.services.a2a_hooks import fire_a2a_card_pre_hook

        caplog.set_level(logging.DEBUG, logger="mcpgateway.services.a2a_hooks")
        await fire_a2a_card_pre_hook(
            MagicMock(),
            agent_name="echo",
            server_id="srv-1",
            public_base_url="http://gateway",
            caller_email="dev@example.com",
        )
        assert any("placeholder" in record.message and "echo" in record.message for record in caplog.records)

    @pytest.mark.asyncio
    async def test_fire_a2a_card_post_hook_no_op_when_pm_none(self):
        from mcpgateway.services.a2a_hooks import fire_a2a_card_post_hook

        await fire_a2a_card_post_hook(
            None,
            agent_name="echo",
            server_id=None,
            card_resolved=False,
        )

    @pytest.mark.asyncio
    async def test_fire_a2a_extended_card_hooks_no_op_when_pm_none(self):
        from mcpgateway.services.a2a_hooks import (
            A2AHookContext,
            fire_a2a_extended_card_post_hook,
            fire_a2a_extended_card_pre_hook,
        )

        ctx = A2AHookContext(
            agent_id="a1",
            agent_name="a",
            agent_team_id=None,
            correlation_id="c",
            user_email=None,
            plugin_manager=None,
            global_context=MagicMock(),
        )

        await fire_a2a_extended_card_pre_hook(ctx, server_id="srv-1")
        await fire_a2a_extended_card_post_hook(ctx, server_id="srv-1", capabilities_advertised=False)

    @pytest.mark.asyncio
    async def test_fire_a2a_streaming_dispatch_hooks_no_op_when_pm_none(self):
        from mcpgateway.services.a2a_hooks import (
            A2AHookContext,
            fire_a2a_streaming_dispatch_post_hook,
            fire_a2a_streaming_dispatch_pre_hook,
        )

        ctx = A2AHookContext(
            agent_id="a1",
            agent_name="a",
            agent_team_id=None,
            correlation_id="c",
            user_email=None,
            plugin_manager=None,
            global_context=MagicMock(),
        )

        await fire_a2a_streaming_dispatch_pre_hook(
            ctx,
            method="SendStreamingMessage",
            server_id=None,
            hop_count=0,
        )
        await fire_a2a_streaming_dispatch_post_hook(
            ctx,
            method="SendStreamingMessage",
            server_id=None,
            chunks_sent=0,
            completed_normally=True,
        )
