# -*- coding: utf-8 -*-
"""Tests for rule-based plugin routing system.

Tests various routing scenarios including:
- Name-based routing
- Tag-based routing
- Priority ordering
- reverse_order_on_post
- when clause filtering
- Config merging (deep merge and override)
- Hooks and mode overrides
- Infrastructure filters
- Specificity ordering
"""

import sys
from pathlib import Path

import pytest

# Add fixtures to path
fixtures_path = Path(__file__).parent.parent / "fixtures" / "plugins"
sys.path.insert(0, str(fixtures_path))

from mcpgateway.plugins.framework.hooks.tools import ToolHookType
from mcpgateway.plugins.framework.hooks.prompts import PromptHookType
from mcpgateway.plugins.framework.hooks.resources import ResourceHookType
from mcpgateway.plugins.framework.hooks.http import (
    HttpHookType,
    HttpPreRequestPayload,
    HttpPostRequestPayload,
    HttpHeaderPayload,
    HttpAuthResolveUserPayload,
    HttpAuthCheckPermissionPayload,
)
from mcpgateway.plugins.framework.manager import PluginManager
from mcpgateway.plugins.framework.models import GlobalContext

# Import test plugins
from tracker_plugin import TrackerPlugin
from configurable_plugin import ConfigurablePlugin


@pytest.fixture
def config_dir():
    """Return path to routing config fixtures."""
    return Path(__file__).parent.parent / "fixtures" / "configs" / "routing"


@pytest.fixture
def reset_plugins():
    """Reset plugin tracking before each test."""
    TrackerPlugin.reset()
    ConfigurablePlugin.reset()
    yield
    TrackerPlugin.reset()
    ConfigurablePlugin.reset()


class TestNameBasedRouting:
    """Test exact name-based routing."""

    @pytest.mark.asyncio
    async def test_exact_name_match(self, config_dir, reset_plugins):
        """Test that exact name matching routes to correct plugin."""
        config_path = config_dir / "01_name_based_routing.yaml"
        manager = PluginManager(config_path)
        await manager.initialize()

        # Create tool with name that matches tracker_a rule
        global_context = GlobalContext(
            request_id="test-1",
            entity_type="tool",
            entity_name="create_customer",
            entity_id="tool-1"
        )

        # Create dummy payload
        from mcpgateway.plugins.framework.hooks.tools import ToolPreInvokePayload
        payload = ToolPreInvokePayload(tool_id="tool-1", name="create_customer", args={})

        # Invoke pre hook
        result, _ = await manager.invoke_hook(
            ToolHookType.TOOL_PRE_INVOKE,
            payload=payload,
            global_context=global_context
        )

        # Verify only tracker_a was called
        assert len(TrackerPlugin.invocations) == 1
        assert TrackerPlugin.invocations[0]["plugin"] == "tracker_a"
        assert TrackerPlugin.invocations[0]["hook"] == "tool_pre_invoke"

        await manager.shutdown()

    @pytest.mark.asyncio
    async def test_name_list_match(self, config_dir, reset_plugins):
        """Test that name list matching routes to correct plugin."""
        config_path = config_dir / "01_name_based_routing.yaml"
        manager = PluginManager(config_path)
        await manager.initialize()

        # Test both names in the list
        for tool_name in ["delete_customer", "update_customer"]:
            TrackerPlugin.reset()

            global_context = GlobalContext(
                request_id=f"test-{tool_name}",
                entity_type="tool",
                entity_name=tool_name,
                entity_id=f"tool-{tool_name}"
            )

            from mcpgateway.plugins.framework.hooks.tools import ToolPreInvokePayload
            payload = ToolPreInvokePayload(tool_id=f"tool-{tool_name}", name=tool_name, args={})

            await manager.invoke_hook(
                ToolHookType.TOOL_PRE_INVOKE,
                payload=payload,
                global_context=global_context
            )

            # Verify only tracker_b was called
            assert len(TrackerPlugin.invocations) == 1
            assert TrackerPlugin.invocations[0]["plugin"] == "tracker_b"

        await manager.shutdown()


class TestTagBasedRouting:
    """Test tag-based routing."""

    @pytest.mark.asyncio
    async def test_single_tag_match(self, config_dir, reset_plugins):
        """Test routing based on single tag."""
        config_path = config_dir / "02_tag_based_routing.yaml"
        manager = PluginManager(config_path)
        await manager.initialize()

        global_context = GlobalContext(
            request_id="test-pii",
            entity_type="tool",
            entity_name="get_ssn",
            entity_id="tool-1",
            tags=["pii"]
        )

        from mcpgateway.plugins.framework.hooks.tools import ToolPreInvokePayload
        payload = ToolPreInvokePayload(tool_id="tool-1", name="get_ssn", args={}, tags=["pii"])

        await manager.invoke_hook(
            ToolHookType.TOOL_PRE_INVOKE,
            payload=payload,
            global_context=global_context
        )

        # Verify pii_tracker was called
        assert len(TrackerPlugin.invocations) == 1
        assert TrackerPlugin.invocations[0]["plugin"] == "pii_tracker"

        await manager.shutdown()

    @pytest.mark.asyncio
    async def test_multiple_tag_match(self, config_dir, reset_plugins):
        """Test routing when tool has multiple tags."""
        config_path = config_dir / "02_tag_based_routing.yaml"
        manager = PluginManager(config_path)
        await manager.initialize()

        # Tool with both 'pii' and 'customer' tags should match both rules
        global_context = GlobalContext(
            request_id="test-multi",
            entity_type="tool",
            entity_name="get_customer_data",
            entity_id="tool-2",
            tags=["pii", "customer"]
        )

        from mcpgateway.plugins.framework.hooks.tools import ToolPreInvokePayload
        payload = ToolPreInvokePayload(
            tool_id="tool-2",
            name="get_customer_data",
            args={},
            tags=["pii", "customer"]
        )

        await manager.invoke_hook(
            ToolHookType.TOOL_PRE_INVOKE,
            payload=payload,
            global_context=global_context
        )

        # Both trackers should be called
        assert len(TrackerPlugin.invocations) == 2
        plugins_called = {inv["plugin"] for inv in TrackerPlugin.invocations}
        assert plugins_called == {"pii_tracker", "customer_tracker"}

        await manager.shutdown()


class TestPriorityOrdering:
    """Test priority-based plugin ordering."""

    @pytest.mark.asyncio
    async def test_priority_order(self, config_dir, reset_plugins):
        """Test plugins execute in priority order (lower number = higher priority)."""
        config_path = config_dir / "03_priority_ordering.yaml"
        manager = PluginManager(config_path)
        await manager.initialize()

        global_context = GlobalContext(
            request_id="test-priority",
            entity_type="tool",
            entity_name="ordered_tool",
            entity_id="tool-1"
        )

        from mcpgateway.plugins.framework.hooks.tools import ToolPreInvokePayload
        payload = ToolPreInvokePayload(tool_id="tool-1", name="ordered_tool", args={})

        await manager.invoke_hook(
            ToolHookType.TOOL_PRE_INVOKE,
            payload=payload,
            global_context=global_context
        )

        # Verify execution order: high (10), medium (20), low (30)
        assert len(TrackerPlugin.invocations) == 3
        assert TrackerPlugin.invocations[0]["plugin"] == "tracker_high"
        assert TrackerPlugin.invocations[1]["plugin"] == "tracker_medium"
        assert TrackerPlugin.invocations[2]["plugin"] == "tracker_low"

        await manager.shutdown()


class TestReverseOrderOnPost:
    """Test reverse_order_on_post for symmetric wrapping."""

    @pytest.mark.asyncio
    async def test_reverse_order_post_hook(self, config_dir, reset_plugins):
        """Test POST hooks reverse order for symmetric wrapping."""
        config_path = config_dir / "04_reverse_order_on_post.yaml"
        manager = PluginManager(config_path)
        await manager.initialize()

        global_context = GlobalContext(
            request_id="test-wrap",
            entity_type="tool",
            entity_name="wrapped_tool",
            entity_id="tool-1"
        )

        from mcpgateway.plugins.framework.hooks.tools import ToolPreInvokePayload, ToolPostInvokePayload
        pre_payload = ToolPreInvokePayload(tool_id="tool-1", name="wrapped_tool", args={})
        post_payload = ToolPostInvokePayload(tool_id="tool-1", name="wrapped_tool", args={}, result={})

        # Invoke PRE hook
        await manager.invoke_hook(
            ToolHookType.TOOL_PRE_INVOKE,
            payload=pre_payload,
            global_context=global_context
        )

        # PRE order: outer (10), middle (20), inner (30)
        pre_invocations = [inv for inv in TrackerPlugin.invocations if inv["hook"] == "tool_pre_invoke"]
        assert len(pre_invocations) == 3
        assert pre_invocations[0]["plugin"] == "tracker_outer"
        assert pre_invocations[1]["plugin"] == "tracker_middle"
        assert pre_invocations[2]["plugin"] == "tracker_inner"

        # Invoke POST hook
        await manager.invoke_hook(
            ToolHookType.TOOL_POST_INVOKE,
            payload=post_payload,
            global_context=global_context
        )

        # POST order: inner (30), middle (20), outer (10) - REVERSED!
        post_invocations = [inv for inv in TrackerPlugin.invocations if inv["hook"] == "tool_post_invoke"]
        assert len(post_invocations) == 3
        assert post_invocations[0]["plugin"] == "tracker_inner"
        assert post_invocations[1]["plugin"] == "tracker_middle"
        assert post_invocations[2]["plugin"] == "tracker_outer"

        await manager.shutdown()


class TestWhenClauseFiltering:
    """Test runtime filtering with when clauses."""

    @pytest.mark.asyncio
    async def test_when_clause_true(self, config_dir, reset_plugins):
        """Test plugin executes when when clause evaluates to True."""
        config_path = config_dir / "05_when_clause_filtering.yaml"
        manager = PluginManager(config_path)
        await manager.initialize()

        global_context = GlobalContext(
            request_id="test-when-true",
            entity_type="tool",
            entity_name="conditional_tool",
            entity_id="tool-1"
        )

        from mcpgateway.plugins.framework.hooks.tools import ToolPreInvokePayload
        # args.size > 1000 should be True
        payload = ToolPreInvokePayload(tool_id="tool-1", name="conditional_tool", args={"size": 2000})

        await manager.invoke_hook(
            ToolHookType.TOOL_PRE_INVOKE,
            payload=payload,
            global_context=global_context
        )

        # Plugin should be called
        assert len(TrackerPlugin.invocations) == 1
        assert TrackerPlugin.invocations[0]["plugin"] == "size_checker"

        await manager.shutdown()

    @pytest.mark.asyncio
    async def test_when_clause_false(self, config_dir, reset_plugins):
        """Test plugin skipped when when clause evaluates to False."""
        config_path = config_dir / "05_when_clause_filtering.yaml"
        manager = PluginManager(config_path)
        await manager.initialize()

        global_context = GlobalContext(
            request_id="test-when-false",
            entity_type="tool",
            entity_name="conditional_tool",
            entity_id="tool-1"
        )

        from mcpgateway.plugins.framework.hooks.tools import ToolPreInvokePayload
        # args.size > 1000 should be False
        payload = ToolPreInvokePayload(tool_id="tool-1", name="conditional_tool", args={"size": 500})

        await manager.invoke_hook(
            ToolHookType.TOOL_PRE_INVOKE,
            payload=payload,
            global_context=global_context
        )

        # Plugin should NOT be called
        assert len(TrackerPlugin.invocations) == 0

        await manager.shutdown()

    @pytest.mark.asyncio
    async def test_when_clause_user_filter(self, config_dir, reset_plugins):
        """Test when clause filtering on user."""
        config_path = config_dir / "05_when_clause_filtering.yaml"
        manager = PluginManager(config_path)
        await manager.initialize()

        # Test with admin user (should match)
        global_context = GlobalContext(
            request_id="test-admin",
            entity_type="tool",
            entity_name="admin_tool",
            entity_id="tool-1",
            user="admin"
        )

        from mcpgateway.plugins.framework.hooks.tools import ToolPreInvokePayload
        payload = ToolPreInvokePayload(tool_id="tool-1", name="admin_tool", args={})

        await manager.invoke_hook(
            ToolHookType.TOOL_PRE_INVOKE,
            payload=payload,
            global_context=global_context
        )

        assert len(TrackerPlugin.invocations) == 1
        assert TrackerPlugin.invocations[0]["plugin"] == "admin_checker"

        # Test with non-admin user (should NOT match)
        TrackerPlugin.reset()
        global_context.user = "regular_user"

        await manager.invoke_hook(
            ToolHookType.TOOL_PRE_INVOKE,
            payload=payload,
            global_context=global_context
        )

        assert len(TrackerPlugin.invocations) == 0

        await manager.shutdown()


class TestConfigMerging:
    """Test config merging with deep merge and override."""

    @pytest.mark.asyncio
    async def test_deep_merge(self, config_dir, reset_plugins):
        """Test deep merge combines base and rule configs."""
        config_path = config_dir / "06_config_merging.yaml"
        manager = PluginManager(config_path)
        await manager.initialize()

        global_context = GlobalContext(
            request_id="test-merge",
            entity_type="tool",
            entity_name="merge_tool",
            entity_id="tool-1"
        )

        from mcpgateway.plugins.framework.hooks.tools import ToolPreInvokePayload
        payload = ToolPreInvokePayload(tool_id="tool-1", name="merge_tool", args={})

        await manager.invoke_hook(
            ToolHookType.TOOL_PRE_INVOKE,
            payload=payload,
            global_context=global_context
        )

        # Verify merged config
        assert len(ConfigurablePlugin.invocations) == 1
        inv = ConfigurablePlugin.invocations[0]

        # Base values preserved
        assert inv["action"] == "log"  # From base config

        # Rule values override
        assert inv["threshold"] == 500  # Overridden by rule
        assert inv["message"] == "merged_message"  # Overridden by rule

        # Nested deep merge
        assert inv["nested"]["level1"]["level2"] == "merged_value"  # Overridden by rule
        assert inv["nested"]["level1"]["keep_this"] is True  # Preserved from base

        await manager.shutdown()

    @pytest.mark.asyncio
    async def test_override_flag(self, config_dir, reset_plugins):
        """Test override flag replaces entire config."""
        config_path = config_dir / "06_config_merging.yaml"
        manager = PluginManager(config_path)
        await manager.initialize()

        global_context = GlobalContext(
            request_id="test-override",
            entity_type="tool",
            entity_name="override_tool",
            entity_id="tool-1"
        )

        from mcpgateway.plugins.framework.hooks.tools import ToolPreInvokePayload
        payload = ToolPreInvokePayload(tool_id="tool-1", name="override_tool", args={})

        await manager.invoke_hook(
            ToolHookType.TOOL_PRE_INVOKE,
            payload=payload,
            global_context=global_context
        )

        # Verify overridden config
        assert len(ConfigurablePlugin.invocations) == 1
        inv = ConfigurablePlugin.invocations[0]

        # All values from rule config only
        assert inv["action"] == "modify"
        assert inv["threshold"] == 1000
        assert inv["message"] == "override_message"

        # Base nested config NOT present
        assert "level1" not in inv["nested"]

        await manager.shutdown()

    @pytest.mark.asyncio
    async def test_multiple_instances(self, config_dir, reset_plugins):
        """Test same plugin can be instantiated multiple times with different configs."""
        config_path = config_dir / "06_config_merging.yaml"
        manager = PluginManager(config_path)
        await manager.initialize()

        global_context = GlobalContext(
            request_id="test-multi",
            entity_type="tool",
            entity_name="multi_instance_tool",
            entity_id="tool-1"
        )

        from mcpgateway.plugins.framework.hooks.tools import ToolPreInvokePayload
        payload = ToolPreInvokePayload(tool_id="tool-1", name="multi_instance_tool", args={})

        await manager.invoke_hook(
            ToolHookType.TOOL_PRE_INVOKE,
            payload=payload,
            global_context=global_context
        )

        # Two instances should be called
        assert len(ConfigurablePlugin.invocations) == 2

        # First instance (priority 10)
        assert ConfigurablePlugin.invocations[0]["message"] == "instance_1"
        assert ConfigurablePlugin.invocations[0]["threshold"] == 100  # Base value

        # Second instance (priority 20)
        assert ConfigurablePlugin.invocations[1]["message"] == "instance_2"
        assert ConfigurablePlugin.invocations[1]["threshold"] == 200  # Merged value

        await manager.shutdown()


class TestHooksOverride:
    """Test hooks override."""

    @pytest.mark.asyncio
    async def test_hooks_restriction(self, config_dir, reset_plugins):
        """Test restricting plugin to specific hooks."""
        config_path = config_dir / "07_hooks_and_mode_override.yaml"
        manager = PluginManager(config_path)
        await manager.initialize()

        # Test pre-only tool
        global_context = GlobalContext(
            request_id="test-pre-only",
            entity_type="tool",
            entity_name="pre_only_tool",
            entity_id="tool-1"
        )

        from mcpgateway.plugins.framework.hooks.tools import ToolPreInvokePayload, ToolPostInvokePayload
        pre_payload = ToolPreInvokePayload(tool_id="tool-1", name="pre_only_tool", args={})
        post_payload = ToolPostInvokePayload(tool_id="tool-1", name="pre_only_tool", args={}, result={})

        # Pre-invoke should work
        await manager.invoke_hook(
            ToolHookType.TOOL_PRE_INVOKE,
            payload=pre_payload,
            global_context=global_context
        )
        assert len(TrackerPlugin.invocations) == 1
        assert TrackerPlugin.invocations[0]["hook"] == "tool_pre_invoke"

        # Post-invoke should NOT work (hooks restricted to pre only)
        await manager.invoke_hook(
            ToolHookType.TOOL_POST_INVOKE,
            payload=post_payload,
            global_context=global_context
        )
        # Still only 1 invocation (no post-invoke)
        assert len(TrackerPlugin.invocations) == 1

        await manager.shutdown()

    @pytest.mark.asyncio
    async def test_cross_entity_hooks(self, config_dir, reset_plugins):
        """Test using same plugin on different entity types with different hooks."""
        config_path = config_dir / "07_hooks_and_mode_override.yaml"
        manager = PluginManager(config_path)
        await manager.initialize()

        # Test prompt entity
        global_context = GlobalContext(
            request_id="test-prompt",
            entity_type="prompt",
            entity_name="prompt_entity",
            entity_id="prompt-1"
        )

        from mcpgateway.plugins.framework.hooks.prompts import PromptPrehookPayload
        payload = PromptPrehookPayload(prompt_id="prompt-1", args={})

        await manager.invoke_hook(
            PromptHookType.PROMPT_PRE_FETCH,
            payload=payload,
            global_context=global_context
        )

        assert len(TrackerPlugin.invocations) == 1
        assert TrackerPlugin.invocations[0]["hook"] == "prompt_pre_fetch"

        # Test resource entity
        TrackerPlugin.reset()
        global_context = GlobalContext(
            request_id="test-resource",
            entity_type="resource",
            entity_name="resource_entity",
            entity_id="resource-1"
        )

        from mcpgateway.plugins.framework.hooks.resources import ResourcePreFetchPayload
        payload = ResourcePreFetchPayload(resource_id="resource-1", uri="file://test")

        await manager.invoke_hook(
            ResourceHookType.RESOURCE_PRE_FETCH,
            payload=payload,
            global_context=global_context
        )

        assert len(TrackerPlugin.invocations) == 1
        assert TrackerPlugin.invocations[0]["hook"] == "resource_pre_fetch"

        await manager.shutdown()


class TestInfrastructureFilters:
    """Test infrastructure filtering (server_name, server_id, gateway_id)."""

    @pytest.mark.asyncio
    async def test_server_name_filter(self, config_dir, reset_plugins):
        """Test filtering by server name."""
        config_path = config_dir / "08_infrastructure_filters.yaml"
        manager = PluginManager(config_path)
        await manager.initialize()

        # Matching server name
        global_context = GlobalContext(
            request_id="test-server",
            entity_type="tool",
            entity_name="test_tool",
            entity_id="tool-1",
            server_name="api-server"
        )

        from mcpgateway.plugins.framework.hooks.tools import ToolPreInvokePayload
        payload = ToolPreInvokePayload(tool_id="tool-1", name="test_tool", args={})

        await manager.invoke_hook(
            ToolHookType.TOOL_PRE_INVOKE,
            payload=payload,
            global_context=global_context
        )

        assert len(TrackerPlugin.invocations) == 1
        assert TrackerPlugin.invocations[0]["plugin"] == "api_server_tracker"

        # Non-matching server name
        TrackerPlugin.reset()
        global_context.server_name = "other-server"

        await manager.invoke_hook(
            ToolHookType.TOOL_PRE_INVOKE,
            payload=payload,
            global_context=global_context
        )

        # Should not match
        assert len(TrackerPlugin.invocations) == 0

        await manager.shutdown()

    @pytest.mark.asyncio
    async def test_combined_filters(self, config_dir, reset_plugins):
        """Test combining multiple infrastructure filters."""
        config_path = config_dir / "08_infrastructure_filters.yaml"
        manager = PluginManager(config_path)
        await manager.initialize()

        # All filters match
        global_context = GlobalContext(
            request_id="test-combined",
            entity_type="tool",
            entity_name="critical_tool",
            entity_id="tool-1",
            server_name="api-server",
            gateway_id="gateway-123"
        )

        from mcpgateway.plugins.framework.hooks.tools import ToolPreInvokePayload
        payload = ToolPreInvokePayload(name="critical_tool", args={})

        await manager.invoke_hook(
            ToolHookType.TOOL_PRE_INVOKE,
            payload=payload,
            global_context=global_context
        )

        # Both plugins should be called
        assert len(TrackerPlugin.invocations) == 2
        plugins_called = {inv["plugin"] for inv in TrackerPlugin.invocations}
        assert plugins_called == {"prod_tracker", "api_server_tracker"}

        await manager.shutdown()


class TestSpecificityOrdering:
    """Test rule specificity ordering."""

    @pytest.mark.asyncio
    async def test_multiple_rules_merge(self, config_dir, reset_plugins):
        """Test plugins from multiple matching rules are merged."""
        config_path = config_dir / "09_specificity_ordering.yaml"
        manager = PluginManager(config_path)
        await manager.initialize()

        # Tool that matches all three rules
        global_context = GlobalContext(
            request_id="test-specificity",
            entity_type="tool",
            entity_name="create_customer",
            entity_id="tool-1",
            tags=["customer"]
        )

        from mcpgateway.plugins.framework.hooks.tools import ToolPreInvokePayload
        payload = ToolPreInvokePayload(tool_id="tool-1", name="create_customer", args={}, tags=["customer"])

        await manager.invoke_hook(
            ToolHookType.TOOL_PRE_INVOKE,
            payload=payload,
            global_context=global_context
        )

        # All three plugins should be called
        assert len(TrackerPlugin.invocations) == 3

        # Order should be by plugin priority: specific (10), tag (20), general (30)
        assert TrackerPlugin.invocations[0]["plugin"] == "specific_tracker"
        assert TrackerPlugin.invocations[1]["plugin"] == "tag_tracker"
        assert TrackerPlugin.invocations[2]["plugin"] == "general_tracker"

        await manager.shutdown()


class TestImplicitPriority:
    """Test implicit priority through order."""

    @pytest.mark.asyncio
    async def test_implicit_plugin_order(self, config_dir, reset_plugins):
        """Test plugins without explicit priority execute in order listed."""
        config_path = config_dir / "10_implicit_priority.yaml"
        manager = PluginManager(config_path)
        await manager.initialize()

        global_context = GlobalContext(
            request_id="test-implicit",
            entity_type="tool",
            entity_name="implicit_order_tool",
            entity_id="tool-1"
        )

        from mcpgateway.plugins.framework.hooks.tools import ToolPreInvokePayload
        payload = ToolPreInvokePayload(tool_id="tool-1", name="implicit_order_tool", args={})

        await manager.invoke_hook(
            ToolHookType.TOOL_PRE_INVOKE,
            payload=payload,
            global_context=global_context
        )

        # Verify execution order matches definition order (no explicit priority)
        assert len(TrackerPlugin.invocations) == 3
        assert TrackerPlugin.invocations[0]["plugin"] == "tracker_first"
        assert TrackerPlugin.invocations[1]["plugin"] == "tracker_second"
        assert TrackerPlugin.invocations[2]["plugin"] == "tracker_third"

        await manager.shutdown()

    @pytest.mark.asyncio
    async def test_mixed_explicit_implicit_priority(self, config_dir, reset_plugins):
        """Test mixing explicit and implicit priorities."""
        config_path = config_dir / "10_implicit_priority.yaml"
        manager = PluginManager(config_path)
        await manager.initialize()

        global_context = GlobalContext(
            request_id="test-mixed",
            entity_type="tool",
            entity_name="mixed_priority_tool",
            entity_id="tool-1"
        )

        from mcpgateway.plugins.framework.hooks.tools import ToolPreInvokePayload
        payload = ToolPreInvokePayload(tool_id="tool-1", name="mixed_priority_tool", args={})

        await manager.invoke_hook(
            ToolHookType.TOOL_PRE_INVOKE,
            payload=payload,
            global_context=global_context
        )

        # When mixing explicit and implicit priority, all are sorted by priority value
        # tracker_second gets priority 1 (implicit, based on list position)
        # tracker_third has priority 50 (explicit)
        # tracker_first has priority 100 (explicit)
        # Expected order: tracker_second (1), tracker_third (50), tracker_first (100)
        assert len(TrackerPlugin.invocations) == 3
        assert TrackerPlugin.invocations[0]["plugin"] == "tracker_second"
        assert TrackerPlugin.invocations[1]["plugin"] == "tracker_third"
        assert TrackerPlugin.invocations[2]["plugin"] == "tracker_first"

        await manager.shutdown()

    @pytest.mark.asyncio
    async def test_multiple_rules_implicit_priority(self, config_dir, reset_plugins):
        """Test multiple rules matching same entity with implicit priority."""
        config_path = config_dir / "10_implicit_priority.yaml"
        manager = PluginManager(config_path)
        await manager.initialize()

        global_context = GlobalContext(
            request_id="test-multi-rules",
            entity_type="tool",
            entity_name="multi_rule_tool",
            entity_id="tool-1"
        )

        from mcpgateway.plugins.framework.hooks.tools import ToolPreInvokePayload
        payload = ToolPreInvokePayload(tool_id="tool-1", name="multi_rule_tool", args={})

        await manager.invoke_hook(
            ToolHookType.TOOL_PRE_INVOKE,
            payload=payload,
            global_context=global_context
        )

        # All three rules match - plugins should execute in rule order
        assert len(TrackerPlugin.invocations) == 3
        assert TrackerPlugin.invocations[0]["plugin"] == "tracker_first"
        assert TrackerPlugin.invocations[1]["plugin"] == "tracker_second"
        assert TrackerPlugin.invocations[2]["plugin"] == "tracker_third"

        await manager.shutdown()


class TestHttpHooks:
    """Test HTTP-level hook filtering."""

    @pytest.mark.asyncio
    async def test_http_pre_request_hook_filter(self, config_dir, reset_plugins):
        """Test that hooks filter works for http_pre_request."""
        config_path = config_dir / "11_http_hooks.yaml"
        manager = PluginManager(config_path)
        await manager.initialize()

        # Create HTTP pre-request context (no entity context)
        global_context = GlobalContext(
            request_id="test-http-pre"
        )

        # Create HTTP pre-request payload
        headers = HttpHeaderPayload({"Authorization": "Bearer token123"})
        payload = HttpPreRequestPayload(
            path="/tools/list",
            method="GET",
            client_host="127.0.0.1",
            client_port=12345,
            headers=headers
        )

        # Invoke http_pre_request hook
        result, _ = await manager.invoke_hook(
            HttpHookType.HTTP_PRE_REQUEST,
            payload=payload,
            global_context=global_context
        )

        # Should have all 3 plugins with http_pre_request hook
        # (rate_limiter is included even for GET because 'when' filtering happens at runtime)
        assert len(TrackerPlugin.invocations) == 3
        assert TrackerPlugin.invocations[0]["plugin"] == "global_auth"
        assert TrackerPlugin.invocations[0]["hook"] == "http_pre_request"
        assert TrackerPlugin.invocations[1]["plugin"] == "request_logger"
        assert TrackerPlugin.invocations[1]["hook"] == "http_pre_request"
        assert TrackerPlugin.invocations[2]["plugin"] == "rate_limiter"
        assert TrackerPlugin.invocations[2]["hook"] == "http_pre_request"

        await manager.shutdown()

    @pytest.mark.asyncio
    async def test_http_post_request_hook_filter(self, config_dir, reset_plugins):
        """Test that hooks filter works for http_post_request."""
        config_path = config_dir / "11_http_hooks.yaml"
        manager = PluginManager(config_path)
        await manager.initialize()

        # Create HTTP post-request context
        global_context = GlobalContext(
            request_id="test-http-post"
        )

        # Create HTTP post-request payload
        headers = HttpHeaderPayload({"Authorization": "Bearer token123"})
        response_headers = HttpHeaderPayload({"Content-Type": "application/json"})
        payload = HttpPostRequestPayload(
            path="/tools/list",
            method="GET",
            client_host="127.0.0.1",
            client_port=12345,
            headers=headers,
            response_headers=response_headers,
            status_code=200
        )

        # Invoke http_post_request hook
        result, _ = await manager.invoke_hook(
            HttpHookType.HTTP_POST_REQUEST,
            payload=payload,
            global_context=global_context
        )

        # Should have request_logger and post_processor (only post-request hooks)
        assert len(TrackerPlugin.invocations) == 2
        assert TrackerPlugin.invocations[0]["plugin"] == "request_logger"
        assert TrackerPlugin.invocations[0]["hook"] == "http_post_request"
        assert TrackerPlugin.invocations[1]["plugin"] == "post_processor"
        assert TrackerPlugin.invocations[1]["hook"] == "http_post_request"

        await manager.shutdown()

    @pytest.mark.asyncio
    async def test_http_with_when_clause(self, config_dir, reset_plugins):
        """Test HTTP hooks with when clause filtering (POST method)."""
        config_path = config_dir / "11_http_hooks.yaml"
        manager = PluginManager(config_path)
        await manager.initialize()

        # Create HTTP pre-request context with POST method
        global_context = GlobalContext(
            request_id="test-http-post-method"
        )

        # Create HTTP pre-request payload with POST method
        headers = HttpHeaderPayload({"Authorization": "Bearer token123"})
        payload = HttpPreRequestPayload(
            path="/tools/invoke",
            method="POST",
            client_host="127.0.0.1",
            client_port=12345,
            headers=headers
        )

        # Invoke http_pre_request hook
        result, _ = await manager.invoke_hook(
            HttpHookType.HTTP_PRE_REQUEST,
            payload=payload,
            global_context=global_context
        )

        # Should have global_auth, request_logger, AND rate_limiter (POST method)
        assert len(TrackerPlugin.invocations) == 3
        assert TrackerPlugin.invocations[0]["plugin"] == "global_auth"
        assert TrackerPlugin.invocations[1]["plugin"] == "request_logger"
        assert TrackerPlugin.invocations[2]["plugin"] == "rate_limiter"
        # All should be http_pre_request
        assert all(inv["hook"] == "http_pre_request" for inv in TrackerPlugin.invocations)

        await manager.shutdown()

    @pytest.mark.asyncio
    async def test_http_auth_resolve_user_hook(self, config_dir, reset_plugins):
        """Test that hooks filter works for http_auth_resolve_user."""
        config_path = config_dir / "11_http_hooks.yaml"
        manager = PluginManager(config_path)
        await manager.initialize()

        # Create HTTP auth resolve user context
        global_context = GlobalContext(
            request_id="test-auth-resolve"
        )

        # Create HTTP auth resolve user payload
        headers = HttpHeaderPayload({"Authorization": "Bearer token123", "X-Client-Cert": "cert-data"})
        payload = HttpAuthResolveUserPayload(
            credentials={"scheme": "bearer", "credentials": "token123"},
            headers=headers,
            client_host="127.0.0.1",
            client_port=12345
        )

        # Invoke http_auth_resolve_user hook
        result, _ = await manager.invoke_hook(
            HttpHookType.HTTP_AUTH_RESOLVE_USER,
            payload=payload,
            global_context=global_context
        )

        # Should have ldap_auth and mtls_auth (both http_auth_resolve_user hooks)
        assert len(TrackerPlugin.invocations) == 2
        assert TrackerPlugin.invocations[0]["plugin"] == "ldap_auth"
        assert TrackerPlugin.invocations[0]["hook"] == "http_auth_resolve_user"
        assert TrackerPlugin.invocations[1]["plugin"] == "mtls_auth"
        assert TrackerPlugin.invocations[1]["hook"] == "http_auth_resolve_user"

        await manager.shutdown()

    @pytest.mark.asyncio
    async def test_http_auth_check_permission_hook(self, config_dir, reset_plugins):
        """Test that hooks filter works for http_auth_check_permission."""
        config_path = config_dir / "11_http_hooks.yaml"
        manager = PluginManager(config_path)
        await manager.initialize()

        # Create HTTP auth check permission context
        global_context = GlobalContext(
            request_id="test-auth-permission"
        )

        # Create HTTP auth check permission payload with admin permission
        payload = HttpAuthCheckPermissionPayload(
            user_email="admin@example.com",
            permission="admin.servers.write",
            resource_type="server",
            is_admin=True,
            auth_method="jwt",
            client_host="127.0.0.1"
        )

        # Invoke http_auth_check_permission hook
        result, _ = await manager.invoke_hook(
            HttpHookType.HTTP_AUTH_CHECK_PERMISSION,
            payload=payload,
            global_context=global_context
        )

        # Should have admin_permission_checker (matches 'when' clause for admin permissions)
        assert len(TrackerPlugin.invocations) == 1
        assert TrackerPlugin.invocations[0]["plugin"] == "admin_permission_checker"
        assert TrackerPlugin.invocations[0]["hook"] == "http_auth_check_permission"

        await manager.shutdown()
