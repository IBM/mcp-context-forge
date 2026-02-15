# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/framework/test_policies.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

Tests for hook payload policies.
"""

# Standard
from unittest.mock import patch

# Third-Party
import pytest
from pydantic import BaseModel

# First-Party
from mcpgateway.plugins.framework.hooks.policies import apply_policy, DefaultHookPolicy, HookPayloadPolicy
from mcpgateway.plugins.framework.models import PluginPayload


class SamplePayload(PluginPayload):
    """Test payload with writable and non-writable fields."""

    name: str
    args: dict = {}
    secret: str = "original"


class TestHookPayloadPolicy:
    """Tests for HookPayloadPolicy dataclass."""

    def test_policy_is_frozen(self):
        policy = HookPayloadPolicy(writable_fields=frozenset({"name"}))
        with pytest.raises(AttributeError):
            policy.writable_fields = frozenset({"other"})  # type: ignore[misc]

    def test_writable_fields_membership(self):
        policy = HookPayloadPolicy(writable_fields=frozenset({"name", "args"}))
        assert "name" in policy.writable_fields
        assert "args" in policy.writable_fields
        assert "secret" not in policy.writable_fields


class TestDefaultHookPolicy:
    """Tests for DefaultHookPolicy enum."""

    def test_allow_value(self):
        assert DefaultHookPolicy.ALLOW.value == "allow"

    def test_deny_value(self):
        assert DefaultHookPolicy.DENY.value == "deny"

    def test_from_string(self):
        assert DefaultHookPolicy("allow") == DefaultHookPolicy.ALLOW
        assert DefaultHookPolicy("deny") == DefaultHookPolicy.DENY


class TestApplyPolicy:
    """Tests for apply_policy function."""

    def test_allows_writable_field_change(self):
        policy = HookPayloadPolicy(writable_fields=frozenset({"name", "args"}))
        original = SamplePayload(name="old", args={"key": "val"}, secret="s")
        modified = SamplePayload(name="new", args={"key": "val"}, secret="s")

        result = apply_policy(original, modified, policy)
        assert result is not None
        assert result.name == "new"  # type: ignore[union-attr]

    def test_filters_non_writable_field(self):
        policy = HookPayloadPolicy(writable_fields=frozenset({"name"}))
        original = SamplePayload(name="old", secret="original")
        modified = SamplePayload(name="new", secret="hacked")

        result = apply_policy(original, modified, policy)
        assert result is not None
        assert result.name == "new"  # type: ignore[union-attr]
        assert result.secret == "original"  # type: ignore[union-attr]

    def test_returns_none_when_no_effective_changes(self):
        policy = HookPayloadPolicy(writable_fields=frozenset({"name"}))
        original = SamplePayload(name="same", secret="s")
        modified = SamplePayload(name="same", secret="hacked")

        result = apply_policy(original, modified, policy)
        assert result is None

    def test_returns_none_for_identical_payloads(self):
        policy = HookPayloadPolicy(writable_fields=frozenset({"name", "args", "secret"}))
        original = SamplePayload(name="same", args={}, secret="s")
        modified = SamplePayload(name="same", args={}, secret="s")

        result = apply_policy(original, modified, policy)
        assert result is None

    def test_multiple_writable_fields_changed(self):
        policy = HookPayloadPolicy(writable_fields=frozenset({"name", "args"}))
        original = SamplePayload(name="old", args={"a": "1"}, secret="s")
        modified = SamplePayload(name="new", args={"b": "2"}, secret="hacked")

        result = apply_policy(original, modified, policy)
        assert result is not None
        assert result.name == "new"  # type: ignore[union-attr]
        assert result.args == {"b": "2"}  # type: ignore[union-attr]
        assert result.secret == "s"  # type: ignore[union-attr]

    def test_empty_writable_fields_rejects_all(self):
        policy = HookPayloadPolicy(writable_fields=frozenset())
        original = SamplePayload(name="old", secret="s")
        modified = SamplePayload(name="new", secret="hacked")

        result = apply_policy(original, modified, policy)
        assert result is None


class TestPluginPayloadFrozen:
    """Tests for frozen PluginPayload base class."""

    def test_payload_is_immutable(self):
        payload = SamplePayload(name="test", args={}, secret="s")
        with pytest.raises(Exception):  # ValidationError for frozen model
            payload.name = "changed"  # type: ignore[misc]

    def test_payload_model_copy(self):
        payload = SamplePayload(name="test", args={}, secret="s")
        copied = payload.model_copy(update={"name": "updated"})
        assert copied.name == "updated"
        assert payload.name == "test"  # original unchanged


class TestConcreteGatewayPolicies:
    """Tests for the gateway-side HOOK_PAYLOAD_POLICIES."""

    def test_all_hook_types_have_policies(self):
        from mcpgateway.plugins.policy import HOOK_PAYLOAD_POLICIES

        expected_hooks = {
            "tool_pre_invoke",
            "tool_post_invoke",
            "prompt_pre_fetch",
            "prompt_post_fetch",
            "resource_pre_fetch",
            "resource_post_fetch",
            "agent_pre_invoke",
            "agent_post_invoke",
        }
        assert set(HOOK_PAYLOAD_POLICIES.keys()) == expected_hooks

    def test_tool_pre_invoke_writable_fields(self):
        from mcpgateway.plugins.policy import HOOK_PAYLOAD_POLICIES

        policy = HOOK_PAYLOAD_POLICIES["tool_pre_invoke"]
        assert "name" in policy.writable_fields
        assert "args" in policy.writable_fields
        assert "headers" in policy.writable_fields

    def test_tool_post_invoke_writable_fields(self):
        from mcpgateway.plugins.policy import HOOK_PAYLOAD_POLICIES

        policy = HOOK_PAYLOAD_POLICIES["tool_post_invoke"]
        assert policy.writable_fields == frozenset({"result"})


class TestProtocolConformance:
    """Verify gateway concrete types satisfy framework protocols."""

    def test_message_satisfies_message_like(self):
        from mcpgateway.common.models import Message, Role, TextContent
        from mcpgateway.plugins.framework.protocols import MessageLike

        msg = Message(role=Role.USER, content=TextContent(type="text", text="hello"))
        assert isinstance(msg, MessageLike)

    def test_prompt_result_satisfies_prompt_result_like(self):
        from mcpgateway.common.models import Message, PromptResult, Role, TextContent
        from mcpgateway.plugins.framework.protocols import PromptResultLike

        result = PromptResult(
            messages=[Message(role=Role.USER, content=TextContent(type="text", text="hi"))],
            description="test",
        )
        assert isinstance(result, PromptResultLike)

    def test_simple_namespace_satisfies_message_like(self):
        from types import SimpleNamespace

        from mcpgateway.plugins.framework.protocols import MessageLike

        msg = SimpleNamespace(role="user", content="hello")
        assert isinstance(msg, MessageLike)


class TestPromptPosthookCoercion:
    """Tests for PromptPosthookPayload._coerce_result field validator."""

    def test_dict_result_coerced_to_structured_data(self):
        from mcpgateway.plugins.framework.hooks.prompts import PromptPosthookPayload
        from mcpgateway.plugins.framework.utils import StructuredData

        payload = PromptPosthookPayload(
            prompt_id="test",
            result={"messages": [{"role": "user", "content": {"type": "text", "text": "hi"}}]},
        )
        assert isinstance(payload.result, StructuredData)
        assert payload.result.messages[0].content.text == "hi"

    def test_non_dict_result_passthrough(self):
        from types import SimpleNamespace

        from mcpgateway.plugins.framework.hooks.prompts import PromptPosthookPayload

        ns = SimpleNamespace(messages=[], description=None)
        payload = PromptPosthookPayload(prompt_id="test", result=ns)
        assert payload.result is ns

    def test_pydantic_model_result_passthrough(self):
        from mcpgateway.plugins.framework.hooks.prompts import PromptPosthookPayload

        class FakeResult(BaseModel):
            messages: list = []
            description: str = "test"

        fake = FakeResult()
        payload = PromptPosthookPayload(prompt_id="test", result=fake)
        assert payload.result is fake


class TestExecutorPolicyEnforcement:
    """Tests for policy enforcement in PluginExecutor.execute()."""

    @pytest.mark.asyncio
    async def test_explicit_policy_filters_writable_fields(self):
        from mcpgateway.plugins.framework.base import HookRef, Plugin, PluginRef
        from mcpgateway.plugins.framework.manager import PluginExecutor
        from mcpgateway.plugins.framework.models import GlobalContext, PluginConfig, PluginResult

        class ModifyingPlugin(Plugin):
            async def test_hook(self, payload, context):
                modified = payload.model_copy(update={"name": "new", "secret": "hacked"})
                return PluginResult(continue_processing=True, modified_payload=modified)

        config = PluginConfig(name="modifier", kind="test.Plugin", version="1.0", hooks=["test_hook"])
        plugin = ModifyingPlugin(config)
        ref = PluginRef(plugin)
        hook_ref = HookRef("test_hook", ref)

        policies = {"test_hook": HookPayloadPolicy(writable_fields=frozenset({"name"}))}
        executor = PluginExecutor(hook_policies=policies)

        payload = SamplePayload(name="old", secret="original")
        global_ctx = GlobalContext(request_id="1")

        result, _ = await executor.execute(
            [hook_ref], payload, global_ctx, hook_type="test_hook",
        )
        assert result.modified_payload is not None
        assert result.modified_payload.name == "new"
        assert result.modified_payload.secret == "original"  # filtered by policy

    @pytest.mark.asyncio
    async def test_default_deny_rejects_modifications(self):
        from mcpgateway.plugins.framework.base import HookRef, Plugin, PluginRef
        from mcpgateway.plugins.framework.manager import PluginExecutor
        from mcpgateway.plugins.framework.models import GlobalContext, PluginConfig, PluginResult

        class ModifyingPlugin(Plugin):
            async def test_hook(self, payload, context):
                modified = payload.model_copy(update={"name": "new"})
                return PluginResult(continue_processing=True, modified_payload=modified)

        config = PluginConfig(name="modifier", kind="test.Plugin", version="1.0", hooks=["test_hook"])
        plugin = ModifyingPlugin(config)
        ref = PluginRef(plugin)
        hook_ref = HookRef("test_hook", ref)

        # No policies passed — default deny should reject all
        with patch("mcpgateway.plugins.framework.manager.settings") as mock_settings:
            mock_settings.default_hook_policy = "deny"
            mock_settings.max_payload_size_bytes = 1048576
            executor = PluginExecutor(hook_policies={})

        payload = SamplePayload(name="old", secret="original")
        global_ctx = GlobalContext(request_id="1")

        result, _ = await executor.execute(
            [hook_ref], payload, global_ctx, hook_type="test_hook",
        )
        # With deny policy, modifications should be rejected — modified_payload is None
        assert result.modified_payload is None

    @pytest.mark.asyncio
    async def test_explicit_policy_no_effective_change(self):
        from mcpgateway.plugins.framework.base import HookRef, Plugin, PluginRef
        from mcpgateway.plugins.framework.manager import PluginExecutor
        from mcpgateway.plugins.framework.models import GlobalContext, PluginConfig, PluginResult

        class ModifyingPlugin(Plugin):
            async def test_hook(self, payload, context):
                # Only modify 'secret' which is NOT writable
                modified = payload.model_copy(update={"secret": "hacked"})
                return PluginResult(continue_processing=True, modified_payload=modified)

        config = PluginConfig(name="modifier", kind="test.Plugin", version="1.0", hooks=["test_hook"])
        plugin = ModifyingPlugin(config)
        ref = PluginRef(plugin)
        hook_ref = HookRef("test_hook", ref)

        policies = {"test_hook": HookPayloadPolicy(writable_fields=frozenset({"name"}))}
        executor = PluginExecutor(hook_policies=policies)

        payload = SamplePayload(name="old", secret="original")
        global_ctx = GlobalContext(request_id="1")

        result, _ = await executor.execute(
            [hook_ref], payload, global_ctx, hook_type="test_hook",
        )
        # apply_policy returns None because no writable fields changed — so modified_payload stays None
        assert result.modified_payload is None


class TestFrameworkImportIsolation:
    """Verify the plugin framework has no remaining imports from mcpgateway.common or mcpgateway.utils."""

    def test_no_common_or_utils_imports_in_framework(self):
        import ast
        from pathlib import Path

        framework_dir = Path(__file__).resolve().parents[5] / "mcpgateway" / "plugins" / "framework"
        violations = []

        for py_file in framework_dir.rglob("*.py"):
            source = py_file.read_text()
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    if node.module.startswith(("mcpgateway.common", "mcpgateway.utils")):
                        violations.append(f"{py_file.relative_to(framework_dir)}:{node.lineno} -> {node.module}")

        assert violations == [], "Framework still imports from gateway internals:\n" + "\n".join(violations)
