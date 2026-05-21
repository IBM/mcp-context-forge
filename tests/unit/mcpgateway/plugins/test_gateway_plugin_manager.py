# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/test_gateway_plugin_manager.py
Copyright 2026
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
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.db import Base
from mcpgateway.plugins import reload_plugin_context, set_global_observability
from mcpgateway.plugins.gateway_plugin_manager import (
    CONTEXT_ID_SEPARATOR,
    GatewayTenantPluginManagerFactory,
    PluginConfigOverride,
    TenantPluginManagerFactory,
    _CachedManager,
    make_context_id,
)
from mcpgateway.plugins.utils import apply_attribute_mapping
from cpex.framework import OnError
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
    "min_chars": 0,
    "max_chars": 2000,
    "min_tokens": 0,
    "max_tokens": None,
    "chars_per_token": 4,
    "limit_mode": "character",
    "strategy": "truncate",
    "ellipsis": "\u2026",
    "word_boundary": False,
    "max_text_length": 1_000_000,
    "max_structure_size": 10_000,
    "max_recursion_depth": 100,
}
_RL: dict = {
    "by_user": None,
    "by_tenant": None,
    "by_tool": None,
    "algorithm": "fixed_window",
    "backend": "memory",
    "redis_url": None,
    "redis_key_prefix": "rl",
    "redis_fallback": True,
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
    async def test_invalid_on_error_rejected_by_db_constraint(self, db_session):
        """An invalid on_error value is rejected by the DB CHECK constraint."""
        from mcpgateway.db import ToolPluginBinding, utc_now
        from sqlalchemy.exc import IntegrityError
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
        with pytest.raises(IntegrityError):
            db_session.flush()
        db_session.rollback()

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

    def test_none_override_returns_base_config(self):
        factory, _plugin, _captured = self._make_factory_with_base_config()
        result = factory._merge_tenant_config(None)
        assert result is factory._base_config

    def test_unmatched_plugin_passed_through(self):
        factory, plugin, captured = self._make_factory_with_base_config()
        overrides = [PluginConfigOverride(name="NonExistentPlugin")]
        result = factory._merge_tenant_config(overrides)
        assert len(captured) == 0
        assert plugin in result.plugins


# ---------------------------------------------------------------------------
# Observability property
# ---------------------------------------------------------------------------


class TestObservabilityProperty:
    def test_getter_returns_initial_value(self):
        factory = _make_factory.__wrapped__(None) if hasattr(_make_factory, "__wrapped__") else None
        with patch("cpex.framework.manager.ConfigLoader.load_config", return_value=MagicMock(plugins=[])):
            factory = GatewayTenantPluginManagerFactory(yaml_path="/fake.yaml")
        assert factory.observability is None

    def test_setter_updates_value(self):
        with patch("cpex.framework.manager.ConfigLoader.load_config", return_value=MagicMock(plugins=[])):
            factory = GatewayTenantPluginManagerFactory(yaml_path="/fake.yaml")
        mock_obs = MagicMock()
        factory.observability = mock_obs
        assert factory.observability is mock_obs


# ---------------------------------------------------------------------------
# _build_manager
# ---------------------------------------------------------------------------


class TestBuildManager:
    @pytest.fixture
    def factory(self):
        with patch("cpex.framework.manager.ConfigLoader.load_config", return_value=MagicMock(plugins=[])):
            f = TenantPluginManagerFactory(yaml_path="/fake.yaml", cache_ttl=60)
        return f

    @pytest.mark.asyncio
    async def test_build_manager_happy_path(self, factory):
        mock_manager = AsyncMock()
        mock_manager.initialize = AsyncMock()
        mock_manager.shutdown = AsyncMock()

        with (
            patch.object(factory, "get_config_from_db", new_callable=AsyncMock, return_value=None),
            patch.object(factory, "_apply_redis_mode_overrides", new_callable=AsyncMock, side_effect=lambda c: c),
            patch("mcpgateway.plugins.gateway_plugin_manager.TenantPluginManager", return_value=mock_manager),
        ):
            result = await factory._build_manager("team::tool")

        assert result is mock_manager
        mock_manager.initialize.assert_awaited_once()
        assert "team::tool" in factory._managers

    @pytest.mark.asyncio
    async def test_build_manager_shuts_down_old_manager(self, factory):
        old_manager = AsyncMock()
        old_manager.shutdown = AsyncMock()
        factory._managers["team::tool"] = _CachedManager(manager=old_manager, created_at=0)

        new_manager = AsyncMock()
        new_manager.initialize = AsyncMock()

        with (
            patch.object(factory, "get_config_from_db", new_callable=AsyncMock, return_value=None),
            patch.object(factory, "_apply_redis_mode_overrides", new_callable=AsyncMock, side_effect=lambda c: c),
            patch("mcpgateway.plugins.gateway_plugin_manager.TenantPluginManager", return_value=new_manager),
        ):
            result = await factory._build_manager("team::tool")

        assert result is new_manager
        old_manager.shutdown.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_build_manager_old_shutdown_failure_logged(self, factory):
        old_manager = AsyncMock()
        old_manager.shutdown = AsyncMock(side_effect=RuntimeError("boom"))
        factory._managers["team::tool"] = _CachedManager(manager=old_manager, created_at=0)

        new_manager = AsyncMock()
        new_manager.initialize = AsyncMock()

        with (
            patch.object(factory, "get_config_from_db", new_callable=AsyncMock, return_value=None),
            patch.object(factory, "_apply_redis_mode_overrides", new_callable=AsyncMock, side_effect=lambda c: c),
            patch("mcpgateway.plugins.gateway_plugin_manager.TenantPluginManager", return_value=new_manager),
        ):
            result = await factory._build_manager("team::tool")

        assert result is new_manager

    @pytest.mark.asyncio
    async def test_build_manager_exception_shuts_down_initialized_manager(self, factory):
        failing_manager = AsyncMock()
        failing_manager.initialize = AsyncMock(side_effect=RuntimeError("init failed"))
        failing_manager.shutdown = AsyncMock()

        with (
            patch.object(factory, "get_config_from_db", new_callable=AsyncMock, return_value=None),
            patch.object(factory, "_apply_redis_mode_overrides", new_callable=AsyncMock, side_effect=RuntimeError("redis boom")),
            patch("mcpgateway.plugins.gateway_plugin_manager.TenantPluginManager", return_value=failing_manager),
        ):
            with pytest.raises(RuntimeError, match="redis boom"):
                await factory._build_manager("team::tool")

    @pytest.mark.asyncio
    async def test_build_manager_exception_shutdown_failure_logged(self, factory):
        mock_manager = AsyncMock()
        mock_manager.initialize = AsyncMock()
        mock_manager.shutdown = AsyncMock(side_effect=RuntimeError("shutdown boom"))

        async def failing_redis_overrides(config):
            raise RuntimeError("redis error after init")

        with (
            patch.object(factory, "get_config_from_db", new_callable=AsyncMock, return_value=None),
            patch.object(factory, "_apply_redis_mode_overrides", new_callable=AsyncMock, side_effect=RuntimeError("redis fail")),
            patch("mcpgateway.plugins.gateway_plugin_manager.TenantPluginManager", return_value=mock_manager),
        ):
            with pytest.raises(RuntimeError, match="redis fail"):
                await factory._build_manager("team::tool")

    @pytest.mark.asyncio
    async def test_build_manager_cancelled_error_shuts_down(self, factory):
        mock_manager = AsyncMock()
        mock_manager.initialize = AsyncMock()
        mock_manager.shutdown = AsyncMock()

        call_count = 0

        async def cancel_on_redis(config):
            nonlocal call_count
            call_count += 1
            raise asyncio.CancelledError()

        with (
            patch.object(factory, "get_config_from_db", new_callable=AsyncMock, return_value=None),
            patch.object(factory, "_apply_redis_mode_overrides", side_effect=cancel_on_redis),
            patch("mcpgateway.plugins.gateway_plugin_manager.TenantPluginManager", return_value=mock_manager),
        ):
            with pytest.raises(asyncio.CancelledError):
                await factory._build_manager("team::tool")

    @pytest.mark.asyncio
    async def test_build_manager_cancelled_shutdown_failure_logged(self, factory):
        mock_manager = AsyncMock()
        mock_manager.initialize = AsyncMock()
        mock_manager.shutdown = AsyncMock(side_effect=RuntimeError("shutdown fail"))

        async def cancel_on_redis(config):
            raise asyncio.CancelledError()

        with (
            patch.object(factory, "get_config_from_db", new_callable=AsyncMock, return_value=None),
            patch.object(factory, "_apply_redis_mode_overrides", side_effect=cancel_on_redis),
            patch("mcpgateway.plugins.gateway_plugin_manager.TenantPluginManager", return_value=mock_manager),
        ):
            with pytest.raises(asyncio.CancelledError):
                await factory._build_manager("team::tool")


# ---------------------------------------------------------------------------
# get_manager
# ---------------------------------------------------------------------------


class TestGetManager:
    @pytest.fixture
    def factory(self):
        with patch("cpex.framework.manager.ConfigLoader.load_config", return_value=MagicMock(plugins=[])):
            f = TenantPluginManagerFactory(yaml_path="/fake.yaml", cache_ttl=60)
        return f

    @pytest.mark.asyncio
    async def test_get_manager_returns_cached(self, factory):
        mock_manager = AsyncMock()
        import time

        factory._managers["ctx"] = _CachedManager(manager=mock_manager, created_at=time.monotonic())
        result = await factory.get_manager("ctx")
        assert result is mock_manager

    @pytest.mark.asyncio
    async def test_get_manager_rebuilds_expired(self, factory):
        old_manager = AsyncMock()
        factory._managers["ctx"] = _CachedManager(manager=old_manager, created_at=0)

        new_manager = AsyncMock()
        new_manager.initialize = AsyncMock()

        with (
            patch.object(factory, "get_config_from_db", new_callable=AsyncMock, return_value=None),
            patch.object(factory, "_apply_redis_mode_overrides", new_callable=AsyncMock, side_effect=lambda c: c),
            patch("mcpgateway.plugins.gateway_plugin_manager.TenantPluginManager", return_value=new_manager),
        ):
            result = await factory.get_manager("ctx")
        assert result is new_manager

    @pytest.mark.asyncio
    async def test_get_manager_race_returns_cached_entry(self, factory):
        mock_manager = AsyncMock()
        cached_manager = AsyncMock()

        async def build_and_inject(context_id):
            import time
            factory._managers[context_id] = _CachedManager(manager=cached_manager, created_at=time.monotonic())
            return mock_manager

        with patch.object(factory, "_build_manager", side_effect=build_and_inject):
            result = await factory.get_manager("race_ctx")

        assert result is cached_manager


# ---------------------------------------------------------------------------
# reload_tenant
# ---------------------------------------------------------------------------


class TestReloadTenant:
    @pytest.fixture
    def factory(self):
        with patch("cpex.framework.manager.ConfigLoader.load_config", return_value=MagicMock(plugins=[])):
            f = TenantPluginManagerFactory(yaml_path="/fake.yaml", cache_ttl=60)
        return f

    @pytest.mark.asyncio
    async def test_reload_evicts_and_rebuilds(self, factory):
        old_manager = AsyncMock()
        old_manager.shutdown = AsyncMock()
        factory._managers["ctx"] = _CachedManager(manager=old_manager, created_at=0)

        new_manager = AsyncMock()
        new_manager.initialize = AsyncMock()

        with (
            patch.object(factory, "get_config_from_db", new_callable=AsyncMock, return_value=None),
            patch.object(factory, "_apply_redis_mode_overrides", new_callable=AsyncMock, side_effect=lambda c: c),
            patch("mcpgateway.plugins.gateway_plugin_manager.TenantPluginManager", return_value=new_manager),
        ):
            result = await factory.reload_tenant("ctx")

        assert result is new_manager
        old_manager.shutdown.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reload_cancels_inflight(self, factory):
        never_done = asyncio.get_event_loop().create_future()
        factory._inflight["ctx"] = asyncio.ensure_future(never_done)

        new_manager = AsyncMock()
        new_manager.initialize = AsyncMock()

        with (
            patch.object(factory, "get_config_from_db", new_callable=AsyncMock, return_value=None),
            patch.object(factory, "_apply_redis_mode_overrides", new_callable=AsyncMock, side_effect=lambda c: c),
            patch("mcpgateway.plugins.gateway_plugin_manager.TenantPluginManager", return_value=new_manager),
        ):
            result = await factory.reload_tenant("ctx")

        assert result is new_manager
        assert never_done.cancelled()

    @pytest.mark.asyncio
    async def test_reload_old_shutdown_failure_logged(self, factory):
        old_manager = AsyncMock()
        old_manager.shutdown = AsyncMock(side_effect=RuntimeError("shutdown boom"))
        factory._managers["ctx"] = _CachedManager(manager=old_manager, created_at=0)

        new_manager = AsyncMock()
        new_manager.initialize = AsyncMock()

        with (
            patch.object(factory, "get_config_from_db", new_callable=AsyncMock, return_value=None),
            patch.object(factory, "_apply_redis_mode_overrides", new_callable=AsyncMock, side_effect=lambda c: c),
            patch("mcpgateway.plugins.gateway_plugin_manager.TenantPluginManager", return_value=new_manager),
        ):
            result = await factory.reload_tenant("ctx")

        assert result is new_manager


# ---------------------------------------------------------------------------
# shutdown
# ---------------------------------------------------------------------------


class TestShutdown:
    @pytest.fixture
    def factory(self):
        with patch("cpex.framework.manager.ConfigLoader.load_config", return_value=MagicMock(plugins=[])):
            f = TenantPluginManagerFactory(yaml_path="/fake.yaml", cache_ttl=60)
        return f

    @pytest.mark.asyncio
    async def test_shutdown_clears_managers(self, factory):
        m1 = AsyncMock()
        m1.shutdown = AsyncMock()
        m2 = AsyncMock()
        m2.shutdown = AsyncMock()
        factory._managers["a"] = _CachedManager(manager=m1, created_at=0)
        factory._managers["b"] = _CachedManager(manager=m2, created_at=0)

        await factory.shutdown()

        assert len(factory._managers) == 0
        m1.shutdown.assert_awaited_once()
        m2.shutdown.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_shutdown_cancels_inflight(self, factory):
        future = asyncio.get_event_loop().create_future()
        factory._inflight["ctx"] = asyncio.ensure_future(future)

        await factory.shutdown()

        assert len(factory._inflight) == 0
        assert future.cancelled()

    @pytest.mark.asyncio
    async def test_shutdown_manager_failure_logged(self, factory):
        m = AsyncMock()
        m.shutdown = AsyncMock(side_effect=RuntimeError("shutdown fail"))
        factory._managers["a"] = _CachedManager(manager=m, created_at=0)

        await factory.shutdown()
        assert len(factory._managers) == 0


# ---------------------------------------------------------------------------
# _apply_redis_mode_overrides
# ---------------------------------------------------------------------------


class TestApplyRedisModeOverrides:
    @pytest.fixture
    def factory(self):
        with patch("cpex.framework.manager.ConfigLoader.load_config", return_value=MagicMock(plugins=[])):
            f = TenantPluginManagerFactory(yaml_path="/fake.yaml")
        return f

    def _make_config_with_plugin(self, name="TestPlugin"):
        plugin = MagicMock()
        plugin.name = name
        plugin.model_copy = MagicMock(side_effect=lambda update: MagicMock(**{**{"name": name}, **update}))
        config = MagicMock()
        config.plugins = [plugin]
        config.model_copy = MagicMock(side_effect=lambda update, deep: MagicMock(plugins=update["plugins"]))
        return config, plugin

    @pytest.mark.asyncio
    async def test_empty_plugins_returns_config(self, factory):
        config = MagicMock()
        config.plugins = []
        result = await factory._apply_redis_mode_overrides(config)
        assert result is config

    @pytest.mark.asyncio
    async def test_redis_valid_gateway_mode(self, factory):
        config, plugin = self._make_config_with_plugin()
        mock_client = AsyncMock()
        mock_client.mget = AsyncMock(return_value=[b"enforce"])

        with patch("mcpgateway.plugins.gateway_plugin_manager._redis", new_callable=AsyncMock, return_value=mock_client):
            result = await factory._apply_redis_mode_overrides(config)

        assert result.plugins[0].mode == PluginMode.SEQUENTIAL

    @pytest.mark.asyncio
    async def test_redis_invalid_mode_skipped(self, factory):
        config, plugin = self._make_config_with_plugin()
        mock_client = AsyncMock()
        mock_client.mget = AsyncMock(return_value=[b"totally_invalid_mode"])

        with patch("mcpgateway.plugins.gateway_plugin_manager._redis", new_callable=AsyncMock, return_value=mock_client):
            result = await factory._apply_redis_mode_overrides(config)

        assert result is config

    @pytest.mark.asyncio
    async def test_redis_plugin_mode_enum_value(self, factory):
        config, plugin = self._make_config_with_plugin()
        mock_client = AsyncMock()
        mock_client.mget = AsyncMock(return_value=[PluginMode.TRANSFORM.value.encode()])

        with patch("mcpgateway.plugins.gateway_plugin_manager._redis", new_callable=AsyncMock, return_value=mock_client):
            result = await factory._apply_redis_mode_overrides(config)

        assert result.plugins[0].mode == PluginMode.TRANSFORM

    @pytest.mark.asyncio
    async def test_redis_client_error_skipped(self, factory):
        config, plugin = self._make_config_with_plugin()

        with patch("mcpgateway.plugins.gateway_plugin_manager._redis", new_callable=AsyncMock, side_effect=RuntimeError("no redis")):
            result = await factory._apply_redis_mode_overrides(config)

        assert result is config

    @pytest.mark.asyncio
    async def test_redis_mget_failure_fallback(self, factory):
        config, plugin = self._make_config_with_plugin()
        mock_client = AsyncMock()
        mock_client.mget = AsyncMock(side_effect=RuntimeError("mget failed"))

        with patch("mcpgateway.plugins.gateway_plugin_manager._redis", new_callable=AsyncMock, return_value=mock_client):
            result = await factory._apply_redis_mode_overrides(config)

        assert result is config

    @pytest.mark.asyncio
    async def test_enforce_ignore_error_sets_on_error(self, factory):
        config, plugin = self._make_config_with_plugin()
        mock_client = AsyncMock()
        mock_client.mget = AsyncMock(return_value=[b"enforce_ignore_error"])

        with patch("mcpgateway.plugins.gateway_plugin_manager._redis", new_callable=AsyncMock, return_value=mock_client):
            result = await factory._apply_redis_mode_overrides(config)

        assert result.plugins[0].mode == PluginMode.SEQUENTIAL
        assert result.plugins[0].on_error == OnError.IGNORE

    @pytest.mark.asyncio
    async def test_validation_error_skipped(self, factory):
        from pydantic import ValidationError

        config, plugin = self._make_config_with_plugin()
        plugin.model_copy = MagicMock(side_effect=ValidationError.from_exception_data("test", []))
        mock_client = AsyncMock()
        mock_client.mget = AsyncMock(return_value=[b"enforce"])

        with patch("mcpgateway.plugins.gateway_plugin_manager._redis", new_callable=AsyncMock, return_value=mock_client):
            result = await factory._apply_redis_mode_overrides(config)

        assert result is config


# ---------------------------------------------------------------------------
# get_config_from_db: DB error propagates
# ---------------------------------------------------------------------------


class TestGetConfigFromDbErrors:
    @pytest.mark.asyncio
    async def test_db_error_propagates(self):
        def failing_db_factory():
            raise RuntimeError("DB connection failed")

        with patch("cpex.framework.manager.ConfigLoader.load_config", return_value=MagicMock(plugins=[])):
            factory = TenantPluginManagerFactory(yaml_path="/fake.yaml", db_factory=failing_db_factory)

        with pytest.raises(RuntimeError, match="DB connection failed"):
            await factory.get_config_from_db("team::tool")

    @pytest.mark.asyncio
    async def test_no_db_factory_returns_none(self):
        with patch("cpex.framework.manager.ConfigLoader.load_config", return_value=MagicMock(plugins=[])):
            factory = TenantPluginManagerFactory(yaml_path="/fake.yaml", db_factory=None)
        result = await factory.get_config_from_db("team::tool")
        assert result is None


# ---------------------------------------------------------------------------
# set_global_observability (plugins/__init__.py lines 305-307)
# ---------------------------------------------------------------------------


class TestSetGlobalObservability:
    def test_propagates_to_active_factory(self):
        mock_factory = MagicMock()
        mock_obs = MagicMock()

        with patch("mcpgateway.plugins._plugin_manager_factory", mock_factory):
            set_global_observability(mock_obs)

        assert mock_factory.observability == mock_obs

    def test_noop_when_no_factory(self):
        mock_obs = MagicMock()
        with patch("mcpgateway.plugins._plugin_manager_factory", None):
            set_global_observability(mock_obs)


# ---------------------------------------------------------------------------
# apply_attribute_mapping (plugins/utils.py line 33)
# ---------------------------------------------------------------------------


class TestApplyAttributeMapping:
    def test_empty_mapping_returns_original(self):
        attrs = {"tool.name": "weather", "tool.version": "1.0"}
        result = apply_attribute_mapping(attrs, {})
        assert result == attrs

    def test_mapping_renames_keys(self):
        attrs = {"tool.name": "weather", "tool.version": "1.0"}
        mapping = {"tool.name": "controls.artifact.name"}
        result = apply_attribute_mapping(attrs, mapping)
        assert result == {"controls.artifact.name": "weather", "tool.version": "1.0"}

    def test_empty_mapping_returns_copy(self):
        attrs = {"tool.name": "weather"}
        result = apply_attribute_mapping(attrs, {})
        assert result == attrs
        assert result is not attrs


# ---------------------------------------------------------------------------
# _CachedManager.is_expired contract
# ---------------------------------------------------------------------------


class TestCachedManagerExpiry:
    def test_ttl_zero_never_expires(self):
        entry = _CachedManager(manager=MagicMock(), created_at=0.0)
        assert entry.is_expired(0) is False

    def test_ttl_positive_expires_after_deadline(self):
        entry = _CachedManager(manager=MagicMock(), created_at=0.0)
        with patch("time.monotonic", return_value=31.0):
            assert entry.is_expired(30) is True

    def test_ttl_positive_not_expired_before_deadline(self):
        import time as _time

        now = _time.monotonic()
        entry = _CachedManager(manager=MagicMock(), created_at=now)
        assert entry.is_expired(9999) is False


# ---------------------------------------------------------------------------
# _BINDING_MODE_TO_PLUGIN_MODE: enforce_ignore_error DB binding path
# ---------------------------------------------------------------------------


class TestEnforceIgnoreErrorDbBinding:
    @pytest.mark.asyncio
    async def test_enforce_ignore_error_from_db_binding(self, db_session):
        """DB bindings with mode='enforce_ignore_error' map to SEQUENTIAL + OnError.IGNORE."""
        from mcpgateway.db import ToolPluginBinding, utc_now
        import uuid

        binding = ToolPluginBinding(
            id=str(uuid.uuid4()),
            team_id="team-x",
            tool_name="my_tool",
            plugin_id="SomePlugin",
            mode="enforce_ignore_error",
            priority=10,
            config={},
            binding_reference_id=None,
            on_error=None,
            created_at=utc_now(),
            created_by="test@test.com",
            updated_at=utc_now(),
            updated_by="test@test.com",
        )
        db_session.add(binding)
        db_session.commit()

        factory = _make_factory(db_session)
        overrides = await factory.get_config_from_db(make_context_id("team-x", "my_tool"))

        assert overrides is not None
        assert len(overrides) == 1
        assert overrides[0].mode == PluginMode.SEQUENTIAL
        assert overrides[0].on_error == OnError.IGNORE


# ---------------------------------------------------------------------------
# invalidate_team prefix collision safety
# ---------------------------------------------------------------------------


class TestInvalidateTeamPrefixSafety:
    @pytest.mark.asyncio
    async def test_team_id_prefix_does_not_collide(self):
        """team_id 't' must NOT match context_id 't2::tool'."""
        with patch("cpex.framework.manager.ConfigLoader.load_config", return_value=MagicMock(plugins=[])):
            factory = TenantPluginManagerFactory(yaml_path="/fake.yaml")

        mock_mgr = MagicMock()
        factory._managers = {
            "t::tool_a": _CachedManager(manager=mock_mgr, created_at=0.0),
            "t2::tool_b": _CachedManager(manager=mock_mgr, created_at=0.0),
            "t::tool_c": _CachedManager(manager=mock_mgr, created_at=0.0),
        }
        factory.reload_tenant = AsyncMock()

        await factory.invalidate_team("t")

        reloaded = [call.args[0] for call in factory.reload_tenant.call_args_list]
        assert "t::tool_a" in reloaded
        assert "t::tool_c" in reloaded
        assert "t2::tool_b" not in reloaded
