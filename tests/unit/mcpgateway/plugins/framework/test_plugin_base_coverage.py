# -*- coding: utf-8 -*-
"""Coverage tests for mcpgateway.plugins.framework.base — PluginRef and HookRef."""

# Standard
from unittest.mock import MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.plugins.framework.base import HookRef, Plugin, PluginRef
from mcpgateway.plugins.framework.decorator import hook
from mcpgateway.plugins.framework.errors import PluginError
from mcpgateway.plugins.framework.models import PluginCondition, PluginConfig, PluginContext, PluginMode, PluginPayload, PluginResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(**overrides) -> PluginConfig:
    defaults = dict(
        name="test_plugin",
        description="test",
        author="tester",
        kind="test.Plugin",
        version="1.0.0",
        hooks=["tool_pre_invoke"],
        tags=["tag1", "tag2"],
        mode=PluginMode.ENFORCE,
        priority=42,
        conditions=[PluginCondition(server_ids={"s1"})],
    )
    defaults.update(overrides)
    return PluginConfig(**defaults)


class ConcretePlugin(Plugin):
    """A concrete plugin with a convention-based hook method."""

    async def tool_pre_invoke(self, payload: PluginPayload, context: PluginContext) -> PluginResult:
        return PluginResult(continue_processing=True)


class DecoratedPlugin(Plugin):
    """Plugin that uses the @hook decorator for registration."""

    @hook("tool_pre_invoke")
    async def my_custom_method(self, payload: PluginPayload, context: PluginContext) -> PluginResult:
        return PluginResult(continue_processing=True)


class SyncPlugin(Plugin):
    """Plugin with a synchronous hook method (invalid)."""

    def tool_pre_invoke(self, payload: PluginPayload, context: PluginContext) -> PluginResult:
        return PluginResult(continue_processing=True)


class BadSigPlugin(Plugin):
    """Plugin with wrong parameter count (invalid)."""

    async def tool_pre_invoke(self, payload: PluginPayload) -> PluginResult:
        return PluginResult(continue_processing=True)


class NoHookPlugin(Plugin):
    """Plugin with no method matching the hook."""

    pass


# ===========================================================================
# PluginRef tests
# ===========================================================================


class TestPluginRef:
    def test_uuid_is_32_hex(self):
        ref = PluginRef(ConcretePlugin(_make_config()))
        assert len(ref.uuid) == 32
        assert all(c in "0123456789abcdef" for c in ref.uuid)

    def test_uuid_unique(self):
        plugin = ConcretePlugin(_make_config())
        ref1 = PluginRef(plugin)
        ref2 = PluginRef(plugin)
        assert ref1.uuid != ref2.uuid

    def test_priority(self):
        ref = PluginRef(ConcretePlugin(_make_config(priority=7)))
        assert ref.priority == 7

    def test_name(self):
        ref = PluginRef(ConcretePlugin(_make_config(name="my_plugin")))
        assert ref.name == "my_plugin"

    def test_hooks(self):
        ref = PluginRef(ConcretePlugin(_make_config(hooks=["hook_a", "hook_b"])))
        assert ref.hooks == ["hook_a", "hook_b"]

    def test_tags(self):
        ref = PluginRef(ConcretePlugin(_make_config(tags=["t1", "t2"])))
        assert ref.tags == ["t1", "t2"]

    def test_conditions(self):
        cond = PluginCondition(tools={"calc"})
        ref = PluginRef(ConcretePlugin(_make_config(conditions=[cond])))
        assert ref.conditions == [cond]

    def test_conditions_none(self):
        ref = PluginRef(ConcretePlugin(_make_config(conditions=[])))
        assert ref.conditions == []

    def test_mode(self):
        ref = PluginRef(ConcretePlugin(_make_config(mode=PluginMode.PERMISSIVE)))
        assert ref.mode == PluginMode.PERMISSIVE

    def test_plugin_property(self):
        plugin = ConcretePlugin(_make_config())
        ref = PluginRef(plugin)
        assert ref.plugin is plugin


# ===========================================================================
# HookRef tests
# ===========================================================================


class TestHookRef:
    def test_convention_based_discovery(self):
        plugin = ConcretePlugin(_make_config())
        ref = PluginRef(plugin)
        hook_ref = HookRef("tool_pre_invoke", ref)
        assert hook_ref.hook is not None
        assert hook_ref.name == "tool_pre_invoke"
        assert hook_ref.plugin_ref is ref

    def test_decorator_based_discovery(self):
        plugin = DecoratedPlugin(_make_config())
        ref = PluginRef(plugin)
        hook_ref = HookRef("tool_pre_invoke", ref)
        assert hook_ref.hook is not None
        assert hook_ref.name == "tool_pre_invoke"

    def test_missing_method_raises(self):
        plugin = NoHookPlugin(_make_config())
        ref = PluginRef(plugin)
        with pytest.raises(PluginError, match="has no hook"):
            HookRef("tool_pre_invoke", ref)

    def test_wrong_param_count_raises(self):
        plugin = BadSigPlugin(_make_config())
        ref = PluginRef(plugin)
        with pytest.raises(PluginError, match="invalid signature"):
            HookRef("tool_pre_invoke", ref)

    def test_sync_method_raises(self):
        plugin = SyncPlugin(_make_config())
        ref = PluginRef(plugin)
        with pytest.raises(PluginError, match="must be async"):
            HookRef("tool_pre_invoke", ref)

    def test_properties(self):
        plugin = ConcretePlugin(_make_config())
        ref = PluginRef(plugin)
        hook_ref = HookRef("tool_pre_invoke", ref)
        assert hook_ref.name == "tool_pre_invoke"
        assert hook_ref.plugin_ref is ref
        assert callable(hook_ref.hook)


# ===========================================================================
# _validate_type_hints tests (called directly since it's commented out in __init__)
# ===========================================================================


class TestValidateTypeHints:
    def _make_hook_ref(self, plugin_cls):
        plugin = plugin_cls(_make_config())
        ref = PluginRef(plugin)
        return HookRef("tool_pre_invoke", ref)

    def test_no_registry_types_skips(self):
        hook_ref = self._make_hook_ref(ConcretePlugin)
        import inspect
        func = hook_ref.hook
        params = list(inspect.signature(func).parameters.values())
        registry = MagicMock()
        registry.get_payload_type.return_value = None
        registry.get_result_type.return_value = None
        with patch("mcpgateway.plugins.framework.hooks.registry.get_hook_registry", return_value=registry):
            hook_ref._validate_type_hints("tool_pre_invoke", func, params, "test_plugin")

    def test_get_type_hints_exception(self):
        hook_ref = self._make_hook_ref(ConcretePlugin)
        import inspect
        func = hook_ref.hook
        params = list(inspect.signature(func).parameters.values())
        registry = MagicMock()
        registry.get_payload_type.return_value = PluginPayload
        registry.get_result_type.return_value = PluginResult
        with patch("mcpgateway.plugins.framework.hooks.registry.get_hook_registry", return_value=registry), \
             patch("typing.get_type_hints", side_effect=Exception("fail")):
            hook_ref._validate_type_hints("tool_pre_invoke", func, params, "test_plugin")

    def test_missing_payload_hint_raises(self):
        hook_ref = self._make_hook_ref(ConcretePlugin)
        import inspect
        func = hook_ref.hook
        params = list(inspect.signature(func).parameters.values())
        registry = MagicMock()
        registry.get_payload_type.return_value = PluginPayload
        registry.get_result_type.return_value = PluginResult
        with patch("mcpgateway.plugins.framework.hooks.registry.get_hook_registry", return_value=registry), \
             patch("typing.get_type_hints", return_value={"return": PluginResult}):
            with pytest.raises(PluginError, match="missing type hint"):
                hook_ref._validate_type_hints("tool_pre_invoke", func, params, "test_plugin")

    def test_wrong_payload_type_raises(self):
        hook_ref = self._make_hook_ref(ConcretePlugin)
        import inspect
        func = hook_ref.hook
        params = list(inspect.signature(func).parameters.values())
        param_name = params[0].name
        registry = MagicMock()
        registry.get_payload_type.return_value = PluginPayload
        registry.get_result_type.return_value = PluginResult
        with patch("mcpgateway.plugins.framework.hooks.registry.get_hook_registry", return_value=registry), \
             patch("typing.get_type_hints", return_value={param_name: str, "return": PluginResult}):
            with pytest.raises(PluginError, match="incorrect type hint"):
                hook_ref._validate_type_hints("tool_pre_invoke", func, params, "test_plugin")

    def test_missing_return_hint_raises(self):
        hook_ref = self._make_hook_ref(ConcretePlugin)
        import inspect
        func = hook_ref.hook
        params = list(inspect.signature(func).parameters.values())
        param_name = params[0].name
        registry = MagicMock()
        registry.get_payload_type.return_value = PluginPayload
        registry.get_result_type.return_value = PluginResult
        with patch("mcpgateway.plugins.framework.hooks.registry.get_hook_registry", return_value=registry), \
             patch("typing.get_type_hints", return_value={param_name: PluginPayload}):
            with pytest.raises(PluginError, match="missing return type hint"):
                hook_ref._validate_type_hints("tool_pre_invoke", func, params, "test_plugin")

    def test_wrong_return_type_raises(self):
        hook_ref = self._make_hook_ref(ConcretePlugin)
        import inspect
        func = hook_ref.hook
        params = list(inspect.signature(func).parameters.values())
        param_name = params[0].name
        registry = MagicMock()
        registry.get_payload_type.return_value = PluginPayload
        registry.get_result_type.return_value = PluginResult
        with patch("mcpgateway.plugins.framework.hooks.registry.get_hook_registry", return_value=registry), \
             patch("typing.get_type_hints", return_value={param_name: PluginPayload, "return": str}):
            with pytest.raises(PluginError, match="incorrect return type hint"):
                hook_ref._validate_type_hints("tool_pre_invoke", func, params, "test_plugin")
