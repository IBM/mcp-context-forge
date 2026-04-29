# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/test_gateway_plugin_manager.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Madhumohan Jaishankar

Unit tests for GatewayTenantPluginManagerFactory and related helpers.

Tests cover:
    - make_context_id: correct format
    - get_config_from_db: unrecognised format returns None
    - get_config_from_db: unknown team / no bindings returns None
    - get_config_from_db: bindings translated to PluginConfigOverride list
    - get_config_from_db: unknown plugin_id is passed through to the framework
    - reload_plugin_context: no-op when plugins disabled or factory is None
    - reload_plugin_context: delegates to factory.reload_tenant when factory exists
"""

# Standard
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.db import Base
from mcpgateway.plugins import reload_plugin_context
from mcpgateway.plugins.gateway_plugin_manager import (
    CONTEXT_ID_SEPARATOR,
    GatewayTenantPluginManagerFactory,
    make_context_id,
)
from cpex.framework.models import PluginMode
from mcpgateway.schemas import (
    PluginBindingMode,
    PluginPolicyItem,
    TeamPolicies,
    ToolPluginBindingRequest,
)
from mcpgateway.services.tool_plugin_binding_service import ToolPluginBindingService


# ---------------------------------------------------------------------------
# Canonical full-field configs (must include all schema fields)
# ---------------------------------------------------------------------------

_OLG: dict = {
    "min_chars": 0, "max_chars": 2000, "min_tokens": 0, "max_tokens": None,
    "chars_per_token": 4, "limit_mode": "character", "strategy": "truncate",
    "ellipsis": "\u2026", "word_boundary": False, "max_text_length": 1_000_000,
    "max_structure_size": 10_000, "max_recursion_depth": 100,
}
_RL: dict = {
    "by_user": None, "by_tenant": None, "by_tool": None,
    "algorithm": "fixed_window", "backend": "memory",
    "redis_url": None, "redis_key_prefix": "rl", "redis_fallback": True,
}


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_session():
    """Shared in-memory SQLite session backed by all ORM models."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _make_factory(db_session_fixture):
    """Return a GatewayTenantPluginManagerFactory that skips YAML loading.

    We mock ``_base_config`` after construction so tests don't need a real
    plugins/config.yaml on disk.
    """
    # Patch ConfigLoader.load_config so __init__ succeeds without a real YAML file
    with patch("cpex.framework.manager.ConfigLoader.load_config", return_value=MagicMock(plugins=[])):
        factory = GatewayTenantPluginManagerFactory(
            yaml_path="/fake/config.yaml",
            db_factory=lambda: db_session_fixture,
        )
    return factory


# ---------------------------------------------------------------------------
# make_context_id
# ---------------------------------------------------------------------------


class TestMakeContextId:
    def test_format(self):
        assert make_context_id("team-abc", "echo_text") == "team-abc::echo_text"

    def test_separator_constant(self):
        assert CONTEXT_ID_SEPARATOR == "::"

    def test_wildcard_tool(self):
        assert make_context_id("t1", "*") == "t1::*"


# ---------------------------------------------------------------------------
# GatewayTenantPluginManagerFactory.get_config_from_db
# ---------------------------------------------------------------------------


class TestGetConfigFromDb:
    @pytest.mark.asyncio
    async def test_unrecognised_context_id_returns_none(self, db_session):
        """context_id without '::' separator returns None (graceful fallback)."""
        factory = _make_factory(db_session)
        result = await factory.get_config_from_db("just-a-server-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_no_bindings_returns_none(self, db_session):
        """Returns None when no DB rows exist for the given team+tool."""
        factory = _make_factory(db_session)
        result = await factory.get_config_from_db(make_context_id("no-such-team", "any_tool"))
        assert result is None

    @pytest.mark.asyncio
    async def test_bindings_translated_to_overrides(self, db_session):
        """DB bindings are converted to PluginConfigOverride objects correctly."""
        # Seed one binding
        svc = ToolPluginBindingService()
        req = ToolPluginBindingRequest(
            teams={
                "team-a": TeamPolicies(
                    policies=[
                        PluginPolicyItem(
                            tool_names=["my_tool"],
                            plugin_id="OutputLengthGuardPlugin",
                            mode=PluginBindingMode.ENFORCE,

                            priority=42,
                            config={**_OLG, "max_chars": 500},
                        )
                    ]
                )
            }
        )
        svc.upsert_bindings(db_session, req, caller_email="admin@example.com")

        factory = _make_factory(db_session)
        overrides = await factory.get_config_from_db(make_context_id("team-a", "my_tool"))

        assert overrides is not None
        assert len(overrides) == 1
        o = overrides[0]
        assert o.name == "OutputLengthGuardPlugin"
        assert o.mode == PluginMode.SEQUENTIAL
        assert o.priority == 42
        assert o.config == {**_OLG, "max_chars": 500}

    @pytest.mark.asyncio
    async def test_unknown_plugin_id_passed_through(self, db_session):
        """A binding with an unrecognised plugin_id is passed to the framework as-is.

        CF no longer skips unknown plugin names — the framework decides what to
        do with them.  This allows new plugins added to cpex to be used without
        a CF code change.
        """
        from mcpgateway.db import ToolPluginBinding, utc_now
        import uuid

        # Insert a row with a plugin_id not in the registry (simulates a future plugin)
        row = ToolPluginBinding(
            id=uuid.uuid4().hex,
            team_id="team-x",
            tool_name="t",
            plugin_id="FUTURE_PLUGIN_NOT_YET_KNOWN",
            mode="enforce",
            priority=1,
            config={},
            created_at=utc_now(),
            created_by="admin@example.com",
            updated_at=utc_now(),
            updated_by="admin@example.com",
        )
        db_session.add(row)
        db_session.flush()

        factory = _make_factory(db_session)
        result = await factory.get_config_from_db(make_context_id("team-x", "t"))
        # Unknown plugin is passed through — framework will ignore it if unrecognised
        assert result is not None
        assert len(result) == 1
        assert result[0].name == "FUTURE_PLUGIN_NOT_YET_KNOWN"

    @pytest.mark.asyncio
    async def test_on_error_from_binding_propagated(self, db_session):
        """When a binding has an on_error value, it propagates to the override."""
        from mcpgateway.db import ToolPluginBinding, utc_now
        import uuid

        row = ToolPluginBinding(
            id=uuid.uuid4().hex,
            team_id="team-e",
            tool_name="t",
            plugin_id="OutputLengthGuardPlugin",
            mode="enforce",
            priority=10,
            config={},
            on_error="ignore",
            created_at=utc_now(),
            created_by="admin@example.com",
            updated_at=utc_now(),
            updated_by="admin@example.com",
        )
        db_session.add(row)
        db_session.flush()

        factory = _make_factory(db_session)
        overrides = await factory.get_config_from_db(make_context_id("team-e", "t"))

        assert overrides is not None
        assert len(overrides) == 1
        o = overrides[0]
        assert o.name == "OutputLengthGuardPlugin"
        assert o.on_error is not None
        assert o.on_error.value == "ignore"

    @pytest.mark.asyncio
    async def test_on_error_none_when_not_set(self, db_session):
        """When a binding has no on_error, the override uses the mode-implied value."""
        svc = ToolPluginBindingService()
        req = ToolPluginBindingRequest(
            teams={
                "team-f": TeamPolicies(
                    policies=[
                        PluginPolicyItem(
                            tool_names=["my_tool"],
                            plugin_id="OutputLengthGuardPlugin",
                            mode=PluginBindingMode.ENFORCE,
                            priority=42,
                            config={**_OLG, "max_chars": 500},
                        )
                    ]
                )
            }
        )
        svc.upsert_bindings(db_session, req, caller_email="admin@example.com")

        factory = _make_factory(db_session)
        overrides = await factory.get_config_from_db(make_context_id("team-f", "my_tool"))

        assert overrides is not None
        assert len(overrides) == 1
        assert overrides[0].on_error is None

    @pytest.mark.asyncio
    async def test_invalid_on_error_ignored(self, db_session):
        """An invalid on_error value is ignored (not propagated)."""
        from mcpgateway.db import ToolPluginBinding, utc_now
        import uuid

        row = ToolPluginBinding(
            id=uuid.uuid4().hex,
            team_id="team-g",
            tool_name="t",
            plugin_id="OutputLengthGuardPlugin",
            mode="enforce",
            priority=10,
            config={},
            on_error="bogus_value",
            created_at=utc_now(),
            created_by="admin@example.com",
            updated_at=utc_now(),
            updated_by="admin@example.com",
        )
        db_session.add(row)
        db_session.flush()

        factory = _make_factory(db_session)
        overrides = await factory.get_config_from_db(make_context_id("team-g", "t"))

        assert overrides is not None
        assert len(overrides) == 1
        assert overrides[0].on_error is None

    @pytest.mark.asyncio
    async def test_wildcard_binding_returned(self, db_session):
        """A wildcard '*' binding for the team is returned even for exact-tool queries."""
        svc = ToolPluginBindingService()
        req = ToolPluginBindingRequest(
            teams={
                "team-w": TeamPolicies(
                    policies=[
                        PluginPolicyItem(
                            tool_names=["*"],
                            plugin_id="RateLimiterPlugin",
                            mode=PluginBindingMode.PERMISSIVE,

                            priority=5,
                            config={**_RL, "by_user": "60/m", "by_tenant": "600/m"},
                        )
                    ]
                )
            }
        )
        svc.upsert_bindings(db_session, req, caller_email="admin@example.com")

        factory = _make_factory(db_session)
        overrides = await factory.get_config_from_db(make_context_id("team-w", "any_specific_tool"))

        assert overrides is not None
        assert len(overrides) == 1
        assert overrides[0].name == "RateLimiterPlugin"


# ---------------------------------------------------------------------------
# reload_plugin_context
# ---------------------------------------------------------------------------


class TestReloadPluginContext:
    @pytest.mark.asyncio
    async def test_noop_when_plugins_disabled(self):
        """reload_plugin_context is a no-op when plugins are disabled."""
        with (
            patch("mcpgateway.plugins._PLUGINS_ENABLED", False),
            patch("mcpgateway.plugins._plugin_manager_factory", None),
        ):
            # Should not raise
            await reload_plugin_context("team-a::my_tool")

    @pytest.mark.asyncio
    async def test_noop_when_factory_is_none(self):
        """reload_plugin_context is a no-op when the factory is not initialised."""
        with (
            patch("mcpgateway.plugins._PLUGINS_ENABLED", True),
            patch("mcpgateway.plugins._plugin_manager_factory", None),
        ):
            await reload_plugin_context("team-a::my_tool")

    @pytest.mark.asyncio
    async def test_delegates_to_factory_reload_tenant(self):
        """reload_plugin_context calls factory.reload_tenant with the context_id."""
        mock_factory = MagicMock()
        mock_factory.reload_tenant = AsyncMock()

        with (
            patch("mcpgateway.plugins._PLUGINS_ENABLED", True),
            patch("mcpgateway.plugins._plugin_manager_factory", mock_factory),
        ):
            await reload_plugin_context("team-a::echo_text")

        mock_factory.reload_tenant.assert_awaited_once_with("team-a::echo_text")


# ---------------------------------------------------------------------------
# TenantPluginManagerFactory._merge_tenant_config with on_error
# ---------------------------------------------------------------------------


class TestMergeTenantConfigOnError:
    """Verify that _merge_tenant_config propagates on_error from overrides."""

    def _make_factory_with_base_config(self):
        from mcpgateway.plugins.gateway_plugin_manager import TenantPluginManagerFactory

        factory = TenantPluginManagerFactory.__new__(TenantPluginManagerFactory)
        factory._base_config = MagicMock()

        plugin = MagicMock()
        plugin.name = "TestPlugin"
        plugin.config = {"key": "base_value"}
        plugin.mode = PluginMode.SEQUENTIAL
        plugin.priority = 50

        captured_updates = []
        plugin.model_copy = MagicMock(side_effect=lambda update: (captured_updates.append(update), MagicMock(**update, name="TestPlugin"))[-1])
        factory._base_config.plugins = [plugin]
        factory._base_config.model_copy = MagicMock(side_effect=lambda update, deep: MagicMock(plugins=update["plugins"]))
        return factory, plugin, captured_updates

    def test_on_error_applied_when_present(self):
        from cpex.framework import OnError
        from mcpgateway.plugins.gateway_plugin_manager import PluginConfigOverride

        factory, _plugin, captured = self._make_factory_with_base_config()
        overrides = [PluginConfigOverride(name="TestPlugin", on_error=OnError.IGNORE)]

        factory._merge_tenant_config(overrides)
        assert len(captured) == 1
        assert captured[0].get("on_error") == OnError.IGNORE

    def test_on_error_not_applied_when_none(self):
        from mcpgateway.plugins.gateway_plugin_manager import PluginConfigOverride

        factory, _plugin, captured = self._make_factory_with_base_config()
        overrides = [PluginConfigOverride(name="TestPlugin")]

        factory._merge_tenant_config(overrides)
        assert len(captured) == 1
        assert "on_error" not in captured[0]
