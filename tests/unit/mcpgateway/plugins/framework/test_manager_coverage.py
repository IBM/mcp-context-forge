# -*- coding: utf-8 -*-
"""Coverage tests for mcpgateway.plugins.framework.manager — invoke_hook_for_plugin, _execute_with_timeout, permissive mode."""

# Standard
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.plugins.framework.base import HookRef, Plugin, PluginRef
from mcpgateway.plugins.framework.errors import PluginError, PluginViolationError
from mcpgateway.plugins.framework.manager import PluginExecutor, PluginManager
from mcpgateway.plugins.framework.models import (
    Config,
    GlobalContext,
    PluginCondition,
    PluginConfig,
    PluginContext,
    PluginMode,
    PluginPayload,
    PluginResult,
    PluginSettings,
    PluginViolation,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(name="test", priority=100, mode=PluginMode.ENFORCE, hooks=None):
    return PluginConfig(
        name=name,
        kind="test.Plugin",
        version="1.0",
        hooks=hooks or ["test_hook"],
        mode=mode,
        priority=priority,
    )


class ConcretePlugin(Plugin):
    async def test_hook(self, payload: PluginPayload, context: PluginContext) -> PluginResult:
        return PluginResult(continue_processing=True)


def _make_hook_ref(plugin=None, mode=PluginMode.ENFORCE):
    plugin = plugin or ConcretePlugin(_make_config(mode=mode))
    ref = PluginRef(plugin)
    return HookRef("test_hook", ref)


# ===========================================================================
# invoke_hook_for_plugin
# ===========================================================================


class TestInvokeHookForPlugin:
    @pytest.fixture(autouse=True)
    def reset_manager(self):
        PluginManager.reset()
        yield
        PluginManager.reset()

    @pytest.mark.asyncio
    async def test_success(self):
        manager = PluginManager()
        manager._initialized = True
        hook_ref = _make_hook_ref()

        manager._registry = MagicMock()
        manager._registry.get_plugin_hook_by_name.return_value = hook_ref

        payload = MagicMock(spec=PluginPayload)
        context = PluginContext(global_context=GlobalContext(request_id="1"))

        result = await manager.invoke_hook_for_plugin("test", "test_hook", payload, context)
        assert result.continue_processing is True

    @pytest.mark.asyncio
    async def test_not_found_raises(self):
        manager = PluginManager()
        manager._initialized = True
        manager._registry = MagicMock()
        manager._registry.get_plugin_hook_by_name.return_value = None

        payload = MagicMock(spec=PluginPayload)
        context = PluginContext(global_context=GlobalContext(request_id="1"))

        with pytest.raises(PluginError, match="Unable to find"):
            await manager.invoke_hook_for_plugin("missing", "test_hook", payload, context)

    @pytest.mark.asyncio
    async def test_json_payload_dict(self):
        manager = PluginManager()
        manager._initialized = True

        plugin = ConcretePlugin(_make_config())
        plugin.json_to_payload = MagicMock(return_value=MagicMock(spec=PluginPayload))
        hook_ref = _make_hook_ref(plugin)

        manager._registry = MagicMock()
        manager._registry.get_plugin_hook_by_name.return_value = hook_ref

        context = PluginContext(global_context=GlobalContext(request_id="1"))

        result = await manager.invoke_hook_for_plugin(
            "test", "test_hook", {"key": "val"}, context, payload_as_json=True
        )
        plugin.json_to_payload.assert_called_once_with("test_hook", {"key": "val"})
        assert result.continue_processing is True

    @pytest.mark.asyncio
    async def test_json_payload_wrong_type_raises(self):
        manager = PluginManager()
        manager._initialized = True

        hook_ref = _make_hook_ref()
        manager._registry = MagicMock()
        manager._registry.get_plugin_hook_by_name.return_value = hook_ref

        context = PluginContext(global_context=GlobalContext(request_id="1"))

        with pytest.raises(ValueError, match="must be str or dict"):
            await manager.invoke_hook_for_plugin(
                "test", "test_hook", 12345, context, payload_as_json=True
            )

    @pytest.mark.asyncio
    async def test_wrong_payload_type_raises(self):
        manager = PluginManager()
        manager._initialized = True

        hook_ref = _make_hook_ref()
        manager._registry = MagicMock()
        manager._registry.get_plugin_hook_by_name.return_value = hook_ref

        context = PluginContext(global_context=GlobalContext(request_id="1"))

        with pytest.raises(ValueError, match="must be a PluginPayload"):
            await manager.invoke_hook_for_plugin(
                "test", "test_hook", "not-a-payload", context, payload_as_json=False
            )

    @pytest.mark.asyncio
    async def test_global_context_auto_wrap(self):
        manager = PluginManager()
        manager._initialized = True
        hook_ref = _make_hook_ref()

        manager._registry = MagicMock()
        manager._registry.get_plugin_hook_by_name.return_value = hook_ref

        payload = MagicMock(spec=PluginPayload)
        global_context = GlobalContext(request_id="1")

        result = await manager.invoke_hook_for_plugin("test", "test_hook", payload, global_context)
        assert result.continue_processing is True


# ===========================================================================
# _execute_with_timeout observability
# ===========================================================================


class TestExecuteWithTimeout:
    @pytest.mark.asyncio
    async def test_with_trace_id(self):
        from mcpgateway.plugins.framework.observability import current_trace_id

        mock_provider = MagicMock()
        mock_provider.start_span.return_value = "span-123"

        executor = PluginExecutor(timeout=30, observability=mock_provider)
        hook_ref = _make_hook_ref()
        context = PluginContext(global_context=GlobalContext(request_id="1"))
        payload = MagicMock(spec=PluginPayload)

        token = current_trace_id.set("trace-abc")
        try:
            result = await executor._execute_with_timeout(hook_ref, payload, context)
        finally:
            current_trace_id.reset(token)

        assert result.continue_processing is True
        mock_provider.start_span.assert_called_once()
        mock_provider.end_span.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_trace(self):
        mock_provider = MagicMock()

        executor = PluginExecutor(timeout=30, observability=mock_provider)
        hook_ref = _make_hook_ref()
        context = PluginContext(global_context=GlobalContext(request_id="1"))
        payload = MagicMock(spec=PluginPayload)

        # current_trace_id defaults to None, so no tracing should occur
        result = await executor._execute_with_timeout(hook_ref, payload, context)

        assert result.continue_processing is True
        mock_provider.start_span.assert_not_called()
        mock_provider.end_span.assert_not_called()

    @pytest.mark.asyncio
    async def test_observability_provider_failure(self):
        from mcpgateway.plugins.framework.observability import current_trace_id

        mock_provider = MagicMock()
        mock_provider.start_span.side_effect = Exception("provider fail")

        executor = PluginExecutor(timeout=30, observability=mock_provider)
        hook_ref = _make_hook_ref()
        context = PluginContext(global_context=GlobalContext(request_id="1"))
        payload = MagicMock(spec=PluginPayload)

        token = current_trace_id.set("trace-abc")
        try:
            result = await executor._execute_with_timeout(hook_ref, payload, context)
        finally:
            current_trace_id.reset(token)

        # Should still succeed despite provider failure
        assert result.continue_processing is True

    @pytest.mark.asyncio
    async def test_error_path_ends_span_with_error(self):
        """When plugin execution raises, end_span is called with status='error'."""
        from mcpgateway.plugins.framework.observability import current_trace_id

        mock_provider = MagicMock()
        mock_provider.start_span.return_value = "span-err"

        class FailingPlugin(Plugin):
            async def test_hook(self, payload, context):
                raise RuntimeError("boom")

        plugin = FailingPlugin(_make_config())
        ref = PluginRef(plugin)
        hook_ref = HookRef("test_hook", ref)

        executor = PluginExecutor(timeout=30, observability=mock_provider)
        context = PluginContext(global_context=GlobalContext(request_id="1"))
        payload = MagicMock(spec=PluginPayload)

        token = current_trace_id.set("trace-err")
        try:
            with pytest.raises(RuntimeError, match="boom"):
                await executor._execute_with_timeout(hook_ref, payload, context)
        finally:
            current_trace_id.reset(token)

        mock_provider.start_span.assert_called_once()
        mock_provider.end_span.assert_called_once_with(span_id="span-err", status="error")

    @pytest.mark.asyncio
    async def test_error_path_end_span_also_fails(self):
        """When plugin raises AND end_span also raises, the original error propagates."""
        from mcpgateway.plugins.framework.observability import current_trace_id

        mock_provider = MagicMock()
        mock_provider.start_span.return_value = "span-double-err"
        mock_provider.end_span.side_effect = Exception("end_span also broke")

        class FailingPlugin(Plugin):
            async def test_hook(self, payload, context):
                raise RuntimeError("plugin boom")

        plugin = FailingPlugin(_make_config())
        ref = PluginRef(plugin)
        hook_ref = HookRef("test_hook", ref)

        executor = PluginExecutor(timeout=30, observability=mock_provider)
        context = PluginContext(global_context=GlobalContext(request_id="1"))
        payload = MagicMock(spec=PluginPayload)

        token = current_trace_id.set("trace-double-err")
        try:
            with pytest.raises(RuntimeError, match="plugin boom"):
                await executor._execute_with_timeout(hook_ref, payload, context)
        finally:
            current_trace_id.reset(token)

        # end_span was attempted despite the error
        mock_provider.end_span.assert_called_once_with(span_id="span-double-err", status="error")

    @pytest.mark.asyncio
    async def test_end_span_failure_on_success_path(self):
        """When end_span raises after successful execution, the result is still returned."""
        from mcpgateway.plugins.framework.observability import current_trace_id

        mock_provider = MagicMock()
        mock_provider.start_span.return_value = "span-ok"
        mock_provider.end_span.side_effect = Exception("end_span broke")

        executor = PluginExecutor(timeout=30, observability=mock_provider)
        hook_ref = _make_hook_ref()
        context = PluginContext(global_context=GlobalContext(request_id="1"))
        payload = MagicMock(spec=PluginPayload)

        token = current_trace_id.set("trace-ok")
        try:
            result = await executor._execute_with_timeout(hook_ref, payload, context)
        finally:
            current_trace_id.reset(token)

        # Plugin result is returned despite end_span failure
        assert result.continue_processing is True
        mock_provider.start_span.assert_called_once()
        mock_provider.end_span.assert_called_once()


# ===========================================================================
# Permissive mode with no violation
# ===========================================================================


class TestPermissiveBlocking:
    @pytest.mark.asyncio
    async def test_permissive_no_violation(self):
        """Plugin returns continue_processing=False in permissive mode with no violation object."""
        plugin = ConcretePlugin(_make_config(mode=PluginMode.PERMISSIVE))

        # Override to return blocking result with no violation
        async def blocking_hook(payload, context):
            return PluginResult(continue_processing=False, violation=None)

        ref = PluginRef(plugin)
        hook_ref = HookRef("test_hook", ref)
        hook_ref._func = blocking_hook

        executor = PluginExecutor(timeout=30)
        context = PluginContext(global_context=GlobalContext(request_id="1"))
        payload = MagicMock(spec=PluginPayload)

        result = await executor.execute_plugin(hook_ref, payload, context, False)
        # In permissive mode, should still return the result (just log warning)
        assert result.continue_processing is False

    @pytest.mark.asyncio
    async def test_permissive_with_violation_description(self):
        """Plugin returns violation with description in permissive mode."""
        plugin = ConcretePlugin(_make_config(mode=PluginMode.PERMISSIVE))

        async def blocking_hook(payload, context):
            return PluginResult(
                continue_processing=False,
                violation=PluginViolation(reason="test", description="detailed", code="V1"),
            )

        ref = PluginRef(plugin)
        hook_ref = HookRef("test_hook", ref)
        hook_ref._func = blocking_hook

        executor = PluginExecutor(timeout=30)
        context = PluginContext(global_context=GlobalContext(request_id="1"))
        payload = MagicMock(spec=PluginPayload)

        result = await executor.execute_plugin(hook_ref, payload, context, False)
        assert result.continue_processing is False
        assert result.violation.plugin_name == "test"


# ===========================================================================
# Cross-type payload: unexpected type warning (manager.py line 251)
# ===========================================================================


class TestCrossTypeUnexpectedPayload:
    """When a plugin returns a modified_payload of an unexpected type (not
    PluginPayload or dict) under an explicit policy, the modification is
    silently ignored with a warning."""

    @pytest.mark.asyncio
    async def test_unexpected_type_ignored_with_policy(self):
        from mcpgateway.plugins.framework.hooks.policies import HookPayloadPolicy

        class WeirdResultPlugin(Plugin):
            async def test_hook(self, payload, context):
                # Return an unexpected type (list) as modified_payload
                return PluginResult(continue_processing=True, modified_payload=["unexpected", "list"])

        config = _make_config(name="weird")
        plugin = WeirdResultPlugin(config)
        ref = PluginRef(plugin)
        hook_ref = HookRef("test_hook", ref)

        policies = {"test_hook": HookPayloadPolicy(writable_fields=frozenset({"name"}))}
        executor = PluginExecutor(hook_policies=policies)

        payload = PluginPayload()
        global_ctx = GlobalContext(request_id="1")

        result, _ = await executor.execute(
            [hook_ref], payload, global_ctx, hook_type="test_hook",
        )
        # The unexpected type should be ignored — modified_payload stays None
        assert result.modified_payload is None


# ===========================================================================
# PluginManager Borg: hook_policies injection paths (lines 581-596)
# ===========================================================================


class TestBorgHookPoliciesInjection:
    @pytest.fixture(autouse=True)
    def reset_manager(self):
        PluginManager.reset()
        yield
        PluginManager.reset()

    def test_second_instantiation_injects_policies(self):
        """When the first PluginManager had no policies but a second one
        provides them, the policies are injected into the shared executor."""
        from mcpgateway.plugins.framework.hooks.policies import HookPayloadPolicy

        # First instantiation — no policies
        pm1 = PluginManager()
        assert pm1._executor is not None
        assert not pm1._executor.hook_policies

        # Second instantiation — provides policies
        policies = {"test_hook": HookPayloadPolicy(writable_fields=frozenset({"name"}))}
        pm2 = PluginManager(hook_policies=policies)

        # Borg pattern: both share state
        assert pm1._executor.hook_policies == policies
        assert pm2._executor.hook_policies == policies

    def test_second_instantiation_updates_timeout(self):
        """When the second instantiation provides a non-default timeout,
        it updates the shared executor's timeout."""
        from mcpgateway.plugins.framework.hooks.policies import HookPayloadPolicy

        pm1 = PluginManager()
        original_timeout = pm1._executor.timeout

        policies = {"test_hook": HookPayloadPolicy(writable_fields=frozenset())}
        pm2 = PluginManager(timeout=120, hook_policies=policies)

        assert pm2._executor.timeout == 120

    def test_second_instantiation_warns_on_different_policies(self, caplog):
        """When policies are already set and a different set is provided,
        a warning is logged and the new policies are ignored."""
        from mcpgateway.plugins.framework.hooks.policies import HookPayloadPolicy

        policies_a = {"hook_a": HookPayloadPolicy(writable_fields=frozenset({"x"}))}
        policies_b = {"hook_b": HookPayloadPolicy(writable_fields=frozenset({"y"}))}

        pm1 = PluginManager(hook_policies=policies_a)
        pm2 = PluginManager(hook_policies=policies_b)

        assert "already set" in caplog.text
        # Original policies are retained
        assert pm2._executor.hook_policies == policies_a

    def test_second_instantiation_injects_observability(self):
        """When observability is not yet set and a second instantiation
        provides it, the executor is updated."""
        from mcpgateway.plugins.framework.hooks.policies import HookPayloadPolicy

        pm1 = PluginManager()
        assert pm1._executor.observability is None

        mock_obs = MagicMock()
        policies = {"test_hook": HookPayloadPolicy(writable_fields=frozenset())}
        pm2 = PluginManager(hook_policies=policies, observability=mock_obs)

        assert pm2._executor.observability is mock_obs

    def test_defensive_executor_init_when_none(self):
        """When shared state exists but _executor is None (unusual test
        scenario), the defensive path creates a new PluginExecutor."""
        pm = PluginManager()
        # Simulate unusual state: shared state populated but executor nulled
        pm._executor = None

        # Re-instantiate without hook_policies — triggers defensive path
        pm2 = PluginManager()
        assert pm2._executor is not None
        assert isinstance(pm2._executor, PluginExecutor)


# ===========================================================================
# PluginManager executor property and setter (lines 605, 615, 620)
# ===========================================================================


class TestExecutorPropertySetter:
    @pytest.fixture(autouse=True)
    def reset_manager(self):
        PluginManager.reset()
        yield
        PluginManager.reset()

    def test_executor_property_returns_executor(self):
        pm = PluginManager()
        executor = pm.executor
        assert isinstance(executor, PluginExecutor)

    def test_executor_property_lazy_creates(self):
        """When _executor is None, the property lazily creates one."""
        pm = PluginManager()
        pm._executor = None
        executor = pm.executor
        assert isinstance(executor, PluginExecutor)

    def test_executor_setter(self):
        pm = PluginManager()
        new_executor = PluginExecutor()
        pm.executor = new_executor
        assert pm._executor is new_executor


# ===========================================================================
# PluginManager.shutdown lazy async_lock (line 810)
# ===========================================================================


class TestShutdownLazyAsyncLock:
    @pytest.fixture(autouse=True)
    def reset_manager(self):
        PluginManager.reset()
        yield
        PluginManager.reset()

    @pytest.mark.asyncio
    async def test_shutdown_creates_async_lock_lazily(self):
        """shutdown() should lazily create _async_lock if it is None."""
        pm = PluginManager()
        # Ensure _async_lock starts as None (fresh Borg state)
        assert pm._async_lock is None

        # shutdown on uninitialized manager should still create the lock
        await pm.shutdown()

        assert pm._async_lock is not None
        assert isinstance(pm._async_lock, asyncio.Lock)
