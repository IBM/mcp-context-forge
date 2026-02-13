# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/framework/test_policies.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

Tests for hook payload policies.
"""

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

        assert violations == [], f"Framework still imports from gateway internals:\n" + "\n".join(violations)
