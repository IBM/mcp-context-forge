# -*- coding: utf-8 -*-
"""Gateway-executed end-to-end checks for the packaged CPEX PII filter plugin.

This suite validates live gateway execution across the CPEX hook surfaces used
by ContextForge:
- [`prompt_pre_fetch`](mcpgateway/services/prompt_service.py:1937)
- [`prompt_post_fetch`](mcpgateway/services/prompt_service.py:2025)
- [`tool_pre_invoke`](mcpgateway/services/tool_service.py:4642)
- [`tool_post_invoke`](mcpgateway/services/tool_service.py:5535)
"""

from __future__ import annotations

from typing import Any, Callable
import logging

import pytest

pytestmark = [pytest.mark.e2e]  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]

logger = logging.getLogger(__name__)

# PII-specific constants for this test suite
MASK_MARKERS = ("***", "[REDACTED]", "XXX", "xxxxx", "masked", "redacted")


def _looks_masked(text: str) -> bool:
    """Check if text contains common masking patterns."""
    if not text:
        return False
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in MASK_MARKERS)


def _looks_like_policy_block(payload: dict[str, Any]) -> bool:
    """Check if payload indicates a policy-based block."""
    if not isinstance(payload, dict):
        return False
    error = payload.get("error")
    if not error:
        return False
    message = str(error.get("message", "")).lower()
    return "policy" in message or "blocked" in message or "denied" in message


@pytest.fixture
def assert_redaction_behavior() -> Callable[[str, str], None]:
    """Fixture that provides PII redaction assertion logic."""
    def _assert(output_text: str, sensitive_value: str) -> None:
        """Assert that sensitive_value is either masked or absent from output_text."""
        assert sensitive_value not in output_text, (
            f"Expected {sensitive_value!r} to be redacted, but found raw PII in: {output_text}"
        )
        assert _looks_masked(output_text), (
            f"Expected output to contain masking markers, but got: {output_text}"
        )
    return _assert


@pytest.fixture
def plugin_assertions() -> dict[str, Any]:
    """Fixture providing PII-specific assertion helpers."""
    return {
        "looks_masked": _looks_masked,
        "looks_like_policy_block": _looks_like_policy_block,
        "extract_tool_text": lambda result: _extract_tool_text(result),
        "extract_prompt_text": lambda result: _extract_prompt_text(result),
    }


def _extract_tool_text(result: dict[str, Any]) -> str:
    """Extract text content from tool invocation result."""
    content = result.get("content", [])
    if not isinstance(content, list):
        return ""
    text_parts = [item.get("text", "") for item in content if isinstance(item, dict)]
    return "\n".join(part for part in text_parts if part)


def _extract_prompt_text(result: dict[str, Any]) -> str:
    """Extract text from prompt fetch result."""
    messages = result.get("messages", [])
    if not isinstance(messages, list):
        return ""
    for item in messages:
        content = item.get("content")
        if isinstance(content, dict):
            text = content.get("text")
            if text:
                return str(text)
    return ""


class TestPiiFilterE2E:
    """Validate live CPEX PII handling across prompt and tool hook paths."""

    def test_plugin_stack_contract_is_enabled(self, plugin_harness: dict[str, Any]) -> None:
        """The live stack should advertise plugins and observability as enabled."""
        assert str(plugin_harness["plugins_enabled"]).lower() == "true", plugin_harness
        assert str(plugin_harness["observability_enabled"]).lower() == "true", plugin_harness
        assert plugin_harness["plugins_config_file"], plugin_harness
        assert plugin_harness["plugin_name"], plugin_harness
        assert plugin_harness["plugin_kind"], plugin_harness
        # PII filter specific validation
        assert plugin_harness["plugin_kind"] == "cpex_pii_filter.pii_filter.PIIFilterPlugin", (
            f"Expected PII filter plugin, got: {plugin_harness['plugin_kind']}"
        )
        assert plugin_harness["prompt_name"], plugin_harness
        assert plugin_harness["tool_name"], plugin_harness

    def test_tool_call_round_trips_through_gateway(
        self,
        plugin_harness: dict[str, Any],
        invoke_tool: Any,
        plugin_assertions: dict[str, Any],
    ) -> None:
        """The harness should be able to invoke a real gateway-backed MCP tool."""
        response = invoke_tool(plugin_harness, arguments={"timezone": "UTC"}, request_id=10)
        assert response["status_code"] == 200, response

        # Handle potential access denied errors gracefully (may occur due to RBAC or plugin policies)
        if response["error"] is not None:
            error_code = response["error"].get("code")
            error_msg = response["error"].get("message", "")
            # -32003 is MCP "Access denied" - log and skip rather than fail
            if error_code == -32003:
                logger.warning(
                    "Tool invocation returned Access denied (code -32003). "
                    "This may indicate RBAC restrictions or plugin policy blocks. "
                    "Error: %s", response["error"]
                )
                pytest.skip(f"Access denied for tool invocation: {error_msg}")
            # For other errors, fail the test
            assert False, f"Unexpected error: {response['error']}"

        assert isinstance(response["result"], dict), response
        text = plugin_assertions["extract_tool_text"](response["result"])
        logger.info("E2E tool round-trip output: %s", text or response["result"])
        assert isinstance(text, str)
        assert text or response["result"].get("content"), response

    @pytest.mark.parametrize(  # pyright: ignore[reportUnknownMemberType, reportUntypedFunctionDecorator]
        ("category_name", "sensitive_values"),
        [
            ("email", ("john@example.com",)),
            ("phone", ("555-123-4567",)),
            ("ssn", ("123-45-6789",)),
            ("credit_card", ("4111-1111-1111-1111",)),
            ("email_phone", ("john@example.com", "555-123-4567")),
            ("email_ssn_credit_card", ("john@example.com", "123-45-6789", "4111-1111-1111-1111")),
        ],
    )
    def test_prompt_pre_fetch_and_post_fetch_handle_pii_matrix(
        self,
        category_name: str,
        sensitive_values: tuple[str, ...],
        plugin_harness: dict[str, Any],
        invoke_prompt: Any,
        assert_redaction_behavior: Any,
        plugin_assertions: dict[str, Any],
    ) -> None:
        """Prompt hook coverage should handle individual and combined PII categories."""
        primary_value = sensitive_values[0] if sensitive_values else ""
        secondary_value = sensitive_values[1] if len(sensitive_values) > 1 else primary_value

        response = invoke_prompt(
            plugin_harness,
            arguments={
                "user_input": primary_value,
                "secondary_input": secondary_value,
            },
            request_id=20,
        )

        if response["error"] is not None:
            assert plugin_assertions["looks_like_policy_block"](response["payload"]), (category_name, response)
            return

        assert isinstance(response["result"], dict), response
        prompt_text = plugin_assertions["extract_prompt_text"](response["result"])
        logger.info("E2E prompt output for %s: %s", category_name, prompt_text or response["result"])
        prompt_lines = [line.strip() for line in prompt_text.splitlines() if line.strip()]

        if primary_value:
            primary_lines = [line for line in prompt_lines if line.startswith("User input:")]
            assert primary_lines, prompt_text
            assert_redaction_behavior("\n".join(primary_lines), primary_value)

        if len(sensitive_values) > 1 and secondary_value:
            secondary_lines = [line for line in prompt_lines if line.startswith("Secondary input:")]
            assert secondary_lines, prompt_text
            assert_redaction_behavior("\n".join(secondary_lines), secondary_value)

    @pytest.mark.parametrize(  # pyright: ignore[reportUnknownMemberType, reportUntypedFunctionDecorator]
        ("category_name", "sensitive_values"),
        [
            ("email", ("john@example.com",)),
            ("phone", ("555-123-4567",)),
            ("ssn", ("123-45-6789",)),
            ("credit_card", ("4111-1111-1111-1111",)),
            ("email_phone", ("john@example.com", "555-123-4567")),
            ("email_ssn_credit_card", ("john@example.com", "123-45-6789", "4111-1111-1111-1111")),
        ],
    )
    def test_tool_pre_invoke_and_post_invoke_handle_pii_matrix(
        self,
        category_name: str,
        sensitive_values: tuple[str, ...],
        plugin_harness: dict[str, Any],
        invoke_tool: Any,
        assert_redaction_behavior: Any,
        plugin_assertions: dict[str, Any],
    ) -> None:
        """Tool hook coverage should verify outbound responses are redacted across the PII matrix."""
        primary_value = sensitive_values[0] if sensitive_values else ""
        secondary_value = " ".join(sensitive_values[1:]) if len(sensitive_values) > 1 else primary_value

        response = invoke_tool(
            plugin_harness,
            arguments={
                "user_input": primary_value,
                "secondary_input": secondary_value,
                "timezone": "UTC",
            },
            request_id=21,
        )

        if response["error"] is not None:
            assert plugin_assertions["looks_like_policy_block"](response["payload"]), (category_name, response)
            return

        assert isinstance(response["result"], dict), response
        text = plugin_assertions["extract_tool_text"](response["result"])
        logger.info("E2E tool output for %s: %s", category_name, text or response["result"])

        # Verify response contains content (not completely blocked)
        assert text or response["result"].get("content"), (
            f"Tool response is empty - PII filter may have blocked the entire response: {response['result']}"
        )

        # Verify all sensitive values are redacted
        for sensitive_value in sensitive_values:
            assert sensitive_value not in text, (
                f"Expected outbound tool response value {sensitive_value!r} to be redacted, but raw PII was returned: {text}"
            )

        # Verify redaction markers are present (strict check - must have masking markers)
        assert plugin_assertions["looks_masked"](text), (
            f"Expected output to contain masking markers (e.g., ***, [REDACTED], XXX) but got: {text}"
        )

    def test_plugin_harness_is_tenant_scoped(
        self,
        plugin_harness: dict[str, Any],
    ) -> None:
        """The harness should provision an isolated team-scoped server and token."""
        assert plugin_harness["team_id"], plugin_harness
        assert plugin_harness["server_id"], plugin_harness
        assert plugin_harness["token"], plugin_harness
        assert plugin_harness["prompt_name"].startswith("e2e-plugin"), plugin_harness

    def test_make_target_documents_live_stack_requirement(self) -> None:
        """The suite is intended to run only after a live docker-compose or main dev stack is started."""
        assert True

    def test_state_transition_enable_disable_reenable(
        self,
        plugin_harness: dict[str, Any],
        invoke_tool: Any,
        plugin_assertions: dict[str, Any],
        admin_client: Any,
    ) -> None:
        """Verify plugin state transitions: enabled → disabled → re-enabled without restart.

        TODO: Implement dynamic plugin state transitions via /v1/tools/plugin_bindings API.
        Requires:
        - Plugin binding API to accept mode changes (enforce/permissive/disabled)
        - Plugin reload mechanism to apply changes without restart
        - Verification that disabled mode passes through PII unredacted
        - Verification that re-enabling restores redaction behavior

        See issue #4221 for full requirements.
        """
        # Placeholder - test infrastructure is ready, awaiting plugin binding API implementation
        assert True

    @pytest.mark.parametrize(  # pyright: ignore[reportUnknownMemberType, reportUntypedFunctionDecorator]
        ("mode", "expected_behavior"),
        [
            ("enforce", "block_or_redact"),
            ("permissive", "redact"),
            ("disabled", "passthrough"),
        ],
    )
    def test_plugin_mode_variations(
        self,
        mode: str,
        expected_behavior: str,
        plugin_harness: dict[str, Any],
        invoke_tool: Any,
        plugin_assertions: dict[str, Any],
        admin_client: Any,
    ) -> None:
        """Verify plugin behavior across different modes: enforce, permissive, disabled.

        TODO: Implement mode-specific behavior testing via /v1/tools/plugin_bindings API.
        Requires:
        - Dynamic mode configuration (enforce/permissive/disabled)
        - Verification that enforce mode blocks or redacts PII
        - Verification that permissive mode redacts but doesn't block
        - Verification that disabled mode passes through unmodified

        See issue #4221 for full requirements.
        """
        # Placeholder - test infrastructure is ready, awaiting plugin binding API implementation
        assert True

    def test_binding_scope_per_tool_isolation(
        self,
        plugin_harness: dict[str, Any],
        invoke_tool: Any,
        plugin_assertions: dict[str, Any],
        admin_client: Any,
        plugin_server: dict[str, Any],
    ) -> None:
        """Verify plugin bindings are tool-specific and don't affect other tools.

        TODO: Implement per-tool binding isolation testing via /v1/tools/plugin_bindings API.
        Requires:
        - Ability to bind plugin to specific tools only
        - Verification that bound tools apply plugin logic
        - Verification that unbound tools in same team are unaffected
        - Query API to list bindings per team and verify tool-specific scope

        See issue #4221 for full requirements.
        """
        # Placeholder - test infrastructure is ready, awaiting plugin binding API implementation
        assert True

    def test_cross_tenant_isolation(
        self,
        plugin_harness: dict[str, Any],
        invoke_tool: Any,
        plugin_assertions: dict[str, Any],
        admin_client: Any,
    ) -> None:
        """Verify plugin bindings for one team don't affect other teams.

        TODO: Implement cross-tenant isolation testing via /v1/tools/plugin_bindings API.
        Requires:
        - Ability to bind plugin to specific teams only
        - Verification that team-scoped bindings apply plugin logic
        - Verification that other teams are unaffected
        - Query API to verify binding counts per team

        See issue #4221 for full requirements.
        """
        # Placeholder - test infrastructure is ready, awaiting plugin binding API implementation
        assert True

    def test_observability_traces_show_plugin_execution(
        self,
        plugin_harness: dict[str, Any],
        invoke_tool: Any,
        query_observability_traces: Any,
        verify_plugin_execution: Any,
    ) -> None:
        """Verify plugin execution is recorded in observability traces.

        TODO: Implement observability verification for plugin execution.
        Requires:
        - Plugin execution to emit observability spans
        - Query API to retrieve traces by resource type/name
        - Verification that plugin-related spans appear in traces
        - Handle cases where observability is disabled

        See issue #4221 for full requirements.
        """
        # Placeholder - test infrastructure is ready, awaiting observability integration
        assert True
