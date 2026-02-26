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
from pydantic import BaseModel, Field, ValidationError

# First-Party
from mcpgateway.plugins.framework.hooks.policies import apply_policy, DefaultHookPolicy, HookPayloadPolicy
from mcpgateway.plugins.framework.models import PluginPayload


class SamplePayload(PluginPayload):
    """Test payload with writable and non-writable fields."""

    name: str
    args: dict = Field(default_factory=dict)
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

    def test_sentinel_skip_for_missing_attribute(self):
        """When a declared field is absent from the modified instance's __dict__
        (defensive guard), the field is skipped via the _SENTINEL check."""
        policy = HookPayloadPolicy(writable_fields=frozenset({"name", "secret"}))
        original = SamplePayload(name="old", secret="s")
        modified = SamplePayload(name="new", secret="changed")

        # Remove 'secret' from the modified instance's internal storage
        # to trigger the new_val is _SENTINEL branch
        del modified.__dict__["secret"]

        result = apply_policy(original, modified, policy)
        assert result is not None
        assert result.name == "new"  # type: ignore[union-attr]
        # secret should be unchanged (skipped because sentinel)
        assert result.secret == "s"  # type: ignore[union-attr]

    def test_basemodel_field_equal_skipped(self):
        """When both old and new values are BaseModel instances with identical
        content, apply_policy uses model_dump() comparison and skips the field."""

        class Inner(BaseModel):
            x: int = 1
            y: str = "hello"

        class PayloadWithModel(PluginPayload):
            name: str
            nested: Inner = Field(default_factory=Inner)

        policy = HookPayloadPolicy(writable_fields=frozenset({"name", "nested"}))
        original = PayloadWithModel(name="old", nested=Inner(x=1, y="hello"))
        modified = PayloadWithModel(name="new", nested=Inner(x=1, y="hello"))

        result = apply_policy(original, modified, policy)
        assert result is not None
        assert result.name == "new"  # type: ignore[union-attr]
        # nested is structurally identical so should not appear in updates
        assert result.nested.x == 1  # type: ignore[union-attr]

    def test_basemodel_field_changed_accepted(self):
        """When both old and new values are BaseModel but differ, the writable
        field change is accepted via model_dump() comparison."""

        class Inner(BaseModel):
            x: int = 1

        class PayloadWithModel(PluginPayload):
            name: str
            nested: Inner = Field(default_factory=Inner)

        policy = HookPayloadPolicy(writable_fields=frozenset({"nested"}))
        original = PayloadWithModel(name="old", nested=Inner(x=1))
        modified = PayloadWithModel(name="old", nested=Inner(x=99))

        result = apply_policy(original, modified, policy)
        assert result is not None
        assert result.nested.x == 99  # type: ignore[union-attr]


class TestPluginPayloadFrozen:
    """Tests for frozen PluginPayload base class."""

    def test_payload_is_immutable(self):
        payload = SamplePayload(name="test", args={}, secret="s")
        with pytest.raises(ValidationError, match="frozen"):
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
            "http_pre_request",
            "http_post_request",
            "http_auth_resolve_user",
            "http_auth_check_permission",
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

    def test_agent_pre_invoke_includes_agent_id(self):
        from mcpgateway.plugins.policy import HOOK_PAYLOAD_POLICIES

        policy = HOOK_PAYLOAD_POLICIES["agent_pre_invoke"]
        assert "agent_id" in policy.writable_fields, "agent_id must be writable for agent-routing plugins"


class TestAgentMessageCoercion:
    """Tests for _coerce_messages field validator on agent payloads."""

    def test_pre_invoke_dict_messages_coerced(self):
        from mcpgateway.plugins.framework.hooks.agents import AgentPreInvokePayload
        from mcpgateway.plugins.framework.utils import StructuredData

        payload = AgentPreInvokePayload(
            agent_id="agent-1",
            messages=[{"role": "user", "content": {"type": "text", "text": "hello"}}],
        )
        assert isinstance(payload.messages[0], StructuredData)
        assert payload.messages[0].role == "user"
        assert payload.messages[0].content.text == "hello"

    def test_post_invoke_dict_messages_coerced(self):
        from mcpgateway.plugins.framework.hooks.agents import AgentPostInvokePayload
        from mcpgateway.plugins.framework.utils import StructuredData

        payload = AgentPostInvokePayload(
            agent_id="agent-1",
            messages=[{"role": "assistant", "content": {"type": "text", "text": "world"}}],
        )
        assert isinstance(payload.messages[0], StructuredData)
        assert payload.messages[0].content.text == "world"

    def test_real_message_objects_pass_through(self):
        from mcpgateway.common.models import Message, Role, TextContent
        from mcpgateway.plugins.framework.hooks.agents import AgentPreInvokePayload

        msg = Message(role=Role.USER, content=TextContent(type="text", text="hi"))
        payload = AgentPreInvokePayload(agent_id="agent-1", messages=[msg])
        assert payload.messages[0] is msg

    def test_empty_messages_list(self):
        from mcpgateway.plugins.framework.hooks.agents import AgentPreInvokePayload

        payload = AgentPreInvokePayload(agent_id="agent-1", messages=[])
        assert payload.messages == []


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
            [hook_ref],
            payload,
            global_ctx,
            hook_type="test_hook",
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
            executor = PluginExecutor(hook_policies={})

        payload = SamplePayload(name="old", secret="original")
        global_ctx = GlobalContext(request_id="1")

        result, _ = await executor.execute(
            [hook_ref],
            payload,
            global_ctx,
            hook_type="test_hook",
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
            [hook_ref],
            payload,
            global_ctx,
            hook_type="test_hook",
        )
        # apply_policy returns None because no writable fields changed — so modified_payload stays None
        assert result.modified_payload is None

    @pytest.mark.asyncio
    async def test_in_place_nested_mutation_caught_by_policy(self):
        """Plugins that mutate nested dicts in place should not bypass policy filtering."""
        from mcpgateway.plugins.framework.base import HookRef, Plugin, PluginRef
        from mcpgateway.plugins.framework.manager import PluginExecutor
        from mcpgateway.plugins.framework.models import GlobalContext, PluginConfig, PluginResult

        class InPlaceMutatingPlugin(Plugin):
            async def test_hook(self, payload, context):
                # Mutate the nested dict in place — bypasses frozen=True
                # because Pydantic's frozen only protects top-level assignment.
                payload.args["injected"] = "evil"
                # Also mutate 'secret' (non-writable) via in-place nested trick
                # and return the mutated payload as modified_payload.
                return PluginResult(
                    continue_processing=True,
                    modified_payload=payload.model_copy(update={"secret": "hacked", "args": {**payload.args, "injected": "evil"}}),
                )

        config = PluginConfig(name="mutator", kind="test.Plugin", version="1.0", hooks=["test_hook"])
        plugin = InPlaceMutatingPlugin(config)
        ref = PluginRef(plugin)
        hook_ref = HookRef("test_hook", ref)

        # Only 'name' is writable — 'args' and 'secret' should be rejected
        policies = {"test_hook": HookPayloadPolicy(writable_fields=frozenset({"name"}))}
        executor = PluginExecutor(hook_policies=policies)

        payload = SamplePayload(name="old", args={"key": "value"}, secret="original")
        global_ctx = GlobalContext(request_id="1")

        result, _ = await executor.execute(
            [hook_ref],
            payload,
            global_ctx,
            hook_type="test_hook",
        )
        # The snapshot preserves the original args, so the in-place
        # mutation and 'secret' change are both caught by the policy diff
        # and rejected.  No writable field ('name') was changed, so
        # modified_payload should be None.
        assert result.modified_payload is None

    @pytest.mark.asyncio
    async def test_enforce_early_return_uses_policy_filtered_payload(self):
        """When an ENFORCE plugin short-circuits after a prior plugin made
        policy-approved modifications, the early return must carry those
        filtered modifications via current_payload — not the raw result."""
        from mcpgateway.plugins.framework.base import HookRef, Plugin, PluginRef
        from mcpgateway.plugins.framework.manager import PluginExecutor
        from mcpgateway.plugins.framework.models import GlobalContext, PluginConfig, PluginMode, PluginResult

        class ModifyingPlugin(Plugin):
            async def test_hook(self, payload, context):
                modified = payload.model_copy(update={"name": "filtered", "secret": "hacked"})
                return PluginResult(continue_processing=True, modified_payload=modified)

        class BlockingPlugin(Plugin):
            async def test_hook(self, payload, context):
                return PluginResult(continue_processing=False)

        modify_config = PluginConfig(name="modifier", kind="test.Plugin", version="1.0", hooks=["test_hook"])
        modify_plugin = ModifyingPlugin(modify_config)
        modify_ref = PluginRef(modify_plugin)
        modify_hook = HookRef("test_hook", modify_ref)

        block_config = PluginConfig(name="blocker", kind="test.Plugin", version="1.0", hooks=["test_hook"], mode=PluginMode.ENFORCE)
        block_plugin = BlockingPlugin(block_config)
        block_ref = PluginRef(block_plugin)
        block_hook = HookRef("test_hook", block_ref)

        # Only 'name' is writable
        policies = {"test_hook": HookPayloadPolicy(writable_fields=frozenset({"name"}))}
        executor = PluginExecutor(hook_policies=policies)

        payload = SamplePayload(name="old", secret="original")
        global_ctx = GlobalContext(request_id="1")

        result, _ = await executor.execute(
            [modify_hook, block_hook],
            payload,
            global_ctx,
            hook_type="test_hook",
        )
        assert result.continue_processing is False
        # The first plugin's writable modification must survive via current_payload
        assert result.modified_payload is not None
        assert result.modified_payload.name == "filtered"  # writable — accepted
        assert result.modified_payload.secret == "original"  # non-writable — filtered
        assert result.violation is None

    @pytest.mark.asyncio
    async def test_enforce_early_return_carries_metadata(self):
        """The early-return path must carry accumulated metadata from earlier
        plugins, consistent with the normal return path."""
        from mcpgateway.plugins.framework.base import HookRef, Plugin, PluginRef
        from mcpgateway.plugins.framework.manager import PluginExecutor
        from mcpgateway.plugins.framework.models import GlobalContext, PluginConfig, PluginMode, PluginResult

        class MetadataPlugin(Plugin):
            async def test_hook(self, payload, context):
                return PluginResult(continue_processing=True, metadata={"source": "plugin_a"})

        class BlockingPlugin(Plugin):
            async def test_hook(self, payload, context):
                return PluginResult(continue_processing=False)

        meta_config = PluginConfig(name="meta", kind="test.Plugin", version="1.0", hooks=["test_hook"])
        meta_plugin = MetadataPlugin(meta_config)
        meta_ref = PluginRef(meta_plugin)
        meta_hook = HookRef("test_hook", meta_ref)

        block_config = PluginConfig(name="blocker", kind="test.Plugin", version="1.0", hooks=["test_hook"], mode=PluginMode.ENFORCE)
        block_plugin = BlockingPlugin(block_config)
        block_ref = PluginRef(block_plugin)
        block_hook = HookRef("test_hook", block_ref)

        policies = {"test_hook": HookPayloadPolicy(writable_fields=frozenset({"name"}))}
        executor = PluginExecutor(hook_policies=policies)

        payload = SamplePayload(name="old")
        global_ctx = GlobalContext(request_id="1")

        result, _ = await executor.execute(
            [meta_hook, block_hook],
            payload,
            global_ctx,
            hook_type="test_hook",
        )
        assert result.continue_processing is False
        assert result.metadata == {"source": "plugin_a"}

    @pytest.mark.asyncio
    async def test_enforce_early_return_deny_default_rejects_all(self):
        """When default=deny and an ENFORCE plugin short-circuits with modifications,
        all modifications must be rejected (modified_payload=None)."""
        from mcpgateway.plugins.framework.base import HookRef, Plugin, PluginRef
        from mcpgateway.plugins.framework.manager import PluginExecutor
        from mcpgateway.plugins.framework.models import GlobalContext, PluginConfig, PluginMode, PluginResult

        class BlockingPlugin(Plugin):
            async def test_hook(self, payload, context):
                modified = payload.model_copy(update={"name": "new"})
                return PluginResult(continue_processing=False, modified_payload=modified)

        config = PluginConfig(name="blocker", kind="test.Plugin", version="1.0", hooks=["test_hook"], mode=PluginMode.ENFORCE)
        plugin = BlockingPlugin(config)
        ref = PluginRef(plugin)
        hook_ref = HookRef("test_hook", ref)

        # No policies, default deny
        with patch("mcpgateway.plugins.framework.manager.settings") as mock_settings:
            mock_settings.default_hook_policy = "deny"
            executor = PluginExecutor(hook_policies={})

        payload = SamplePayload(name="old", secret="original")
        global_ctx = GlobalContext(request_id="1")

        result, _ = await executor.execute(
            [hook_ref],
            payload,
            global_ctx,
            hook_type="test_hook",
        )
        assert result.continue_processing is False
        assert result.modified_payload is None  # all modifications rejected


class TestCrossTypePolicyHandling:
    """Tests for cross-type payload results (e.g. HTTP hooks)."""

    @pytest.mark.asyncio
    async def test_cross_type_result_accepted_when_policy_exists(self):
        """When modified_payload is a different PluginPayload subtype from the
        input, the policy's presence authorises the hook and the result is accepted."""
        from mcpgateway.plugins.framework.base import HookRef, Plugin, PluginRef
        from mcpgateway.plugins.framework.manager import PluginExecutor
        from mcpgateway.plugins.framework.models import GlobalContext, PluginConfig, PluginPayload, PluginResult

        class DifferentResult(PluginPayload):
            granted: bool = True
            reason: str = "ok"

        class CrossTypePlugin(Plugin):
            async def test_hook(self, payload, context):
                return PluginResult(continue_processing=True, modified_payload=DifferentResult())

        config = PluginConfig(name="cross", kind="test.Plugin", version="1.0", hooks=["test_hook"])
        plugin = CrossTypePlugin(config)
        ref = PluginRef(plugin)
        hook_ref = HookRef("test_hook", ref)

        policies = {"test_hook": HookPayloadPolicy(writable_fields=frozenset({"granted", "reason"}))}
        executor = PluginExecutor(hook_policies=policies)

        payload = SamplePayload(name="old")
        global_ctx = GlobalContext(request_id="1")

        result, _ = await executor.execute([hook_ref], payload, global_ctx, hook_type="test_hook")
        assert result.modified_payload is not None
        assert result.modified_payload.granted is True

    @pytest.mark.asyncio
    async def test_cross_type_dict_result_accepted_when_policy_exists(self):
        """dict results (e.g. http_auth_resolve_user) are accepted when a policy exists."""
        from mcpgateway.plugins.framework.base import HookRef, Plugin, PluginRef
        from mcpgateway.plugins.framework.manager import PluginExecutor
        from mcpgateway.plugins.framework.models import GlobalContext, PluginConfig, PluginResult

        class DictResultPlugin(Plugin):
            async def test_hook(self, payload, context):
                return PluginResult(continue_processing=True, modified_payload={"email": "user@example.com"})

        config = PluginConfig(name="auth", kind="test.Plugin", version="1.0", hooks=["test_hook"])
        plugin = DictResultPlugin(config)
        ref = PluginRef(plugin)
        hook_ref = HookRef("test_hook", ref)

        policies = {"test_hook": HookPayloadPolicy(writable_fields=frozenset())}
        executor = PluginExecutor(hook_policies=policies)

        payload = SamplePayload(name="old")
        global_ctx = GlobalContext(request_id="1")

        result, _ = await executor.execute([hook_ref], payload, global_ctx, hook_type="test_hook")
        assert result.modified_payload == {"email": "user@example.com"}

    @pytest.mark.asyncio
    async def test_deny_default_snapshots_payload_for_in_place_isolation(self):
        """When default=deny, in-place nested mutations must not persist on the live payload."""
        from mcpgateway.plugins.framework.base import HookRef, Plugin, PluginRef
        from mcpgateway.plugins.framework.manager import PluginExecutor
        from mcpgateway.plugins.framework.models import GlobalContext, PluginConfig, PluginResult

        class InPlaceMutator(Plugin):
            async def no_policy_hook(self, payload, context):
                payload.args["injected"] = "evil"
                return PluginResult(continue_processing=True, modified_payload=None)

        config = PluginConfig(name="mutator", kind="test.Plugin", version="1.0", hooks=["no_policy_hook"])
        plugin = InPlaceMutator(config)
        ref = PluginRef(plugin)
        hook_ref = HookRef("no_policy_hook", ref)

        # No policy for this hook, default=deny
        with patch("mcpgateway.plugins.framework.manager.settings") as mock_settings:
            mock_settings.default_hook_policy = "deny"
            executor = PluginExecutor(hook_policies={})

        payload = SamplePayload(name="old", args={"key": "value"})
        global_ctx = GlobalContext(request_id="1")

        result, _ = await executor.execute([hook_ref], payload, global_ctx, hook_type="no_policy_hook")
        # The plugin mutated args in-place, but the deep-copy snapshot means
        # the original payload passed to the next plugin (or returned) is clean
        assert result.modified_payload is None, "deny-default should reject all modifications"
        assert payload.args == {"key": "value"}, "Original payload must not be mutated"


class TestBorgPolicyBackfill:
    """Tests for PluginManager Borg pattern policy injection."""

    def test_get_plugin_manager_injects_policies(self, monkeypatch, tmp_path):
        """Verify get_plugin_manager() always injects hook policies."""
        import mcpgateway.plugins.framework as fw
        from mcpgateway.plugins.framework.settings import settings as plugin_settings

        config_file = tmp_path / "plugins.yaml"
        config_file.write_text("plugin_settings:\n  plugin_timeout: 30\nplugin_dirs: []\nplugins: []\n")

        monkeypatch.setenv("PLUGINS_ENABLED", "true")
        monkeypatch.setenv("PLUGINS_CONFIG_FILE", str(config_file))

        # Reset singleton state
        fw.PluginManager.reset()
        fw._plugin_manager = None
        plugin_settings.cache_clear()

        pm = fw.get_plugin_manager()
        assert pm is not None
        assert pm._executor.hook_policies, "get_plugin_manager() should inject hook policies"

        # Verify known policy keys are present
        assert "tool_pre_invoke" in pm._executor.hook_policies
        assert "prompt_post_fetch" in pm._executor.hook_policies

    def test_service_via_get_plugin_manager_has_policies(self, monkeypatch, tmp_path):
        """Verify that services using get_plugin_manager() get policies regardless of creation order."""
        import mcpgateway.plugins.framework as fw
        from mcpgateway.plugins.framework.settings import settings as plugin_settings

        config_file = tmp_path / "plugins.yaml"
        config_file.write_text("plugin_settings:\n  plugin_timeout: 30\nplugin_dirs: []\nplugins: []\n")

        monkeypatch.setenv("PLUGINS_ENABLED", "true")
        monkeypatch.setenv("PLUGINS_CONFIG_FILE", str(config_file))

        # Reset state
        fw.PluginManager.reset()
        fw._plugin_manager = None
        plugin_settings.cache_clear()

        # Simulate service creating manager via get_plugin_manager
        pm1 = fw.get_plugin_manager()

        # Simulate another access (e.g. from another service)
        pm2 = fw.get_plugin_manager()

        # Both should share the same executor with policies
        assert pm1 is pm2
        assert pm1._executor.hook_policies

    @pytest.mark.asyncio
    async def test_policy_enforcement_through_manager(self, monkeypatch, tmp_path):
        """Integration test: policies enforced through PluginManager.execute flow."""
        from mcpgateway.plugins.framework.base import HookRef, Plugin, PluginRef
        from mcpgateway.plugins.framework.hooks.policies import HookPayloadPolicy
        from mcpgateway.plugins.framework.manager import PluginExecutor
        from mcpgateway.plugins.framework.models import GlobalContext, PluginConfig, PluginResult

        class InjectPlugin(Plugin):
            async def tool_pre_invoke(self, payload, context):
                modified = payload.model_copy(update={"name": "injected", "args": {"injected": "true"}, "secret": "hacked"})
                return PluginResult(continue_processing=True, modified_payload=modified)

        # Set up executor with tool_pre_invoke policy
        policies = {
            "tool_pre_invoke": HookPayloadPolicy(writable_fields=frozenset({"name", "args"})),
        }
        executor = PluginExecutor(hook_policies=policies)

        config = PluginConfig(name="injector", kind="test.Plugin", version="1.0", hooks=["tool_pre_invoke"])
        plugin = InjectPlugin(config)
        ref = PluginRef(plugin)
        hook_ref = HookRef("tool_pre_invoke", ref)

        payload = SamplePayload(name="original", args={}, secret="safe")
        global_ctx = GlobalContext(request_id="test-1")

        result, _ = await executor.execute(
            [hook_ref],
            payload,
            global_ctx,
            hook_type="tool_pre_invoke",
        )

        assert result.modified_payload is not None
        assert result.modified_payload.name == "injected"
        assert result.modified_payload.args == {"injected": "true"}
        assert result.modified_payload.secret == "safe"  # Policy filtered this out


class TestFrameworkImportIsolation:
    """Verify the plugin framework has no remaining imports from mcpgateway.common or mcpgateway.utils."""

    def test_no_common_or_utils_imports_in_framework(self):
        import ast
        from pathlib import Path

        # Walk up to repo root (where pyproject.toml lives) instead of hardcoding parent depth.
        _here = Path(__file__).resolve().parent
        repo_root = _here
        while not (repo_root / "pyproject.toml").exists() and repo_root != repo_root.parent:
            repo_root = repo_root.parent
        framework_dir = repo_root / "mcpgateway" / "plugins" / "framework"
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


class TestMultiPluginDictChain:
    """Tests for multi-plugin chains where an earlier plugin returns a dict payload."""

    @pytest.mark.asyncio
    async def test_dict_payload_deep_copied_for_next_plugin(self):
        """When plugin 1 returns a dict, the next plugin receives a deep-copied
        dict without crashing on model_copy (which dicts don't have)."""
        from mcpgateway.plugins.framework.base import HookRef, Plugin, PluginRef
        from mcpgateway.plugins.framework.manager import PluginExecutor
        from mcpgateway.plugins.framework.models import GlobalContext, PluginConfig, PluginResult

        class AuthPlugin(Plugin):
            async def auth_hook(self, payload, context):
                return PluginResult(continue_processing=True, modified_payload={"email": "user@test.com", "role": "admin"})

        class AuditPlugin(Plugin):
            async def auth_hook(self, payload, context):
                # Second plugin just passes through
                return PluginResult(continue_processing=True)

        auth_config = PluginConfig(name="auth", kind="test.Plugin", version="1.0", hooks=["auth_hook"])
        audit_config = PluginConfig(name="audit", kind="test.Plugin", version="1.0", hooks=["auth_hook"])

        auth_plugin = AuthPlugin(auth_config)
        audit_plugin = AuditPlugin(audit_config)

        hook_refs = [
            HookRef("auth_hook", PluginRef(auth_plugin)),
            HookRef("auth_hook", PluginRef(audit_plugin)),
        ]

        policies = {"auth_hook": HookPayloadPolicy(writable_fields=frozenset())}
        executor = PluginExecutor(hook_policies=policies)

        payload = SamplePayload(name="original")
        global_ctx = GlobalContext(request_id="multi-1")

        result, _ = await executor.execute(hook_refs, payload, global_ctx, hook_type="auth_hook")
        assert result.continue_processing is True
        assert result.modified_payload == {"email": "user@test.com", "role": "admin"}

    @pytest.mark.asyncio
    async def test_dict_to_dict_accepted_without_apply_policy(self):
        """When effective_payload is a dict and plugin also returns a dict,
        the result is accepted directly (not routed through apply_policy)."""
        from mcpgateway.plugins.framework.base import HookRef, Plugin, PluginRef
        from mcpgateway.plugins.framework.manager import PluginExecutor
        from mcpgateway.plugins.framework.models import GlobalContext, PluginConfig, PluginResult

        class FirstAuth(Plugin):
            async def auth_hook(self, payload, context):
                return PluginResult(continue_processing=True, modified_payload={"email": "first@test.com"})

        class SecondAuth(Plugin):
            async def auth_hook(self, payload, context):
                return PluginResult(continue_processing=True, modified_payload={"email": "second@test.com", "enriched": True})

        first_config = PluginConfig(name="first", kind="test.Plugin", version="1.0", hooks=["auth_hook"])
        second_config = PluginConfig(name="second", kind="test.Plugin", version="1.0", hooks=["auth_hook"])

        hook_refs = [
            HookRef("auth_hook", PluginRef(FirstAuth(first_config))),
            HookRef("auth_hook", PluginRef(SecondAuth(second_config))),
        ]

        policies = {"auth_hook": HookPayloadPolicy(writable_fields=frozenset())}
        executor = PluginExecutor(hook_policies=policies)

        payload = SamplePayload(name="original")
        global_ctx = GlobalContext(request_id="multi-2")

        result, _ = await executor.execute(hook_refs, payload, global_ctx, hook_type="auth_hook")
        assert result.continue_processing is True
        assert result.modified_payload == {"email": "second@test.com", "enriched": True}

    @pytest.mark.asyncio
    async def test_empty_dict_payload_not_dropped_by_truthiness(self):
        """An empty dict returned by a plugin must not be replaced by the
        original payload due to falsy truthiness evaluation."""
        from mcpgateway.plugins.framework.base import HookRef, Plugin, PluginRef
        from mcpgateway.plugins.framework.manager import PluginExecutor
        from mcpgateway.plugins.framework.models import GlobalContext, PluginConfig, PluginResult

        class EmptyDictPlugin(Plugin):
            async def auth_hook(self, payload, context):
                return PluginResult(continue_processing=True, modified_payload={})

        class PassthroughPlugin(Plugin):
            """Runs after EmptyDictPlugin; receives the empty dict if chaining works."""

            async def auth_hook(self, payload, context):
                return PluginResult(continue_processing=True)

        hook_refs = [
            HookRef("auth_hook", PluginRef(EmptyDictPlugin(PluginConfig(name="empty", kind="test.Plugin", version="1.0", hooks=["auth_hook"])))),
            HookRef("auth_hook", PluginRef(PassthroughPlugin(PluginConfig(name="pass", kind="test.Plugin", version="1.0", hooks=["auth_hook"])))),
        ]

        policies = {"auth_hook": HookPayloadPolicy(writable_fields=frozenset())}
        executor = PluginExecutor(hook_policies=policies)

        payload = SamplePayload(name="original")
        global_ctx = GlobalContext(request_id="multi-3")

        result, _ = await executor.execute(hook_refs, payload, global_ctx, hook_type="auth_hook")
        assert result.modified_payload == {}, "Empty dict should be preserved, not replaced by original payload"
