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
    - get_config_from_db: unknown plugin_id is skipped (forward-compat guard)
    - get_config_from_db: all bindings have unknown plugin_ids → returns None
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
from mcpgateway.plugins.framework import reload_plugin_context
from mcpgateway.plugins.gateway_plugin_manager import (
    CONTEXT_ID_SEPARATOR,
    GatewayTenantPluginManagerFactory,
    make_context_id,
)
from mcpgateway.plugins.framework.models import PluginMode
from mcpgateway.schemas import (
    PluginBindingMode,
    PluginId,
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
    with patch("mcpgateway.plugins.framework.manager.ConfigLoader.load_config", return_value=MagicMock(plugins=[])):
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
                            plugin_id=PluginId.OUTPUT_LENGTH_GUARD,
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
        assert o.mode == PluginMode.ENFORCE
        assert o.priority == 42
        assert o.config == {**_OLG, "max_chars": 500}

    @pytest.mark.asyncio
    async def test_unknown_plugin_id_is_skipped(self, db_session):
        """A binding with an unknown plugin_id is silently skipped (forward-compat)."""
        from mcpgateway.db import ToolPluginBinding, utc_now
        import uuid

        # Insert a row with a plugin_id not present in PLUGIN_ID_TO_NAME
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
        # The unknown plugin is skipped and no known plugins remain → None
        assert result is None

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
                            plugin_id=PluginId.RATE_LIMITER,
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
            patch("mcpgateway.plugins.framework._PLUGINS_ENABLED", False),
            patch("mcpgateway.plugins.framework._plugin_manager_factory", None),
        ):
            # Should not raise
            await reload_plugin_context("team-a::my_tool")

    @pytest.mark.asyncio
    async def test_noop_when_factory_is_none(self):
        """reload_plugin_context is a no-op when the factory is not initialised."""
        with (
            patch("mcpgateway.plugins.framework._PLUGINS_ENABLED", True),
            patch("mcpgateway.plugins.framework._plugin_manager_factory", None),
        ):
            await reload_plugin_context("team-a::my_tool")

    @pytest.mark.asyncio
    async def test_delegates_to_factory_reload_tenant(self):
        """reload_plugin_context calls factory.reload_tenant with the context_id."""
        mock_factory = MagicMock()
        mock_factory.reload_tenant = AsyncMock()

        with (
            patch("mcpgateway.plugins.framework._PLUGINS_ENABLED", True),
            patch("mcpgateway.plugins.framework._plugin_manager_factory", mock_factory),
        ):
            await reload_plugin_context("team-a::echo_text")

        mock_factory.reload_tenant.assert_awaited_once_with("team-a::echo_text")
