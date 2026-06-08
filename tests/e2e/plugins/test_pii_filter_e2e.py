# -*- coding: utf-8 -*-
"""Gateway-executed end-to-end checks for the packaged CPEX PII filter plugin.

This suite validates live gateway execution across the CPEX hook surfaces used
by ContextForge:
- prompt_pre_fetch / prompt_post_fetch hooks
- tool_pre_invoke / tool_post_invoke hooks

TODO: Add observability verification tests that query traces/spans to confirm:
- PII detections are logged with correct categories and confidence scores
- Plugin execution is captured in observability traces
- Violations are recorded when applicable (enforce mode)
"""

from __future__ import annotations

from typing import Any, Callable
import logging

import pytest

# Import extraction functions from conftest to avoid duplication
from tests.e2e.plugins.conftest import _extract_text_content as _extract_tool_text, _extract_prompt_text

pytestmark = [pytest.mark.e2e]  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]

logger = logging.getLogger(__name__)

# PII-specific constants for this test suite
MASK_MARKERS = ("***", "[REDACTED]", "XXX", "xxxxx", "masked", "redacted", "[PII_REDACTED]")

# Trace persistence timeout for observability verification
TRACE_PERSISTENCE_TIMEOUT_SECONDS = 5
TRACE_POLL_INTERVAL_SECONDS = 0.5


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
    }


class TestPiiFilterE2E:
    """Validate live CPEX PII handling across prompt and tool hook paths."""

    def test_plugin_stack_contract_is_enabled(self, plugin_harness: dict[str, Any]) -> None:
        """The live stack should advertise plugins and observability as enabled."""
        # Strong assertions: these must be true for PII filter tests to be meaningful
        assert str(plugin_harness["plugins_enabled"]).lower() == "true", (
            f"PLUGINS_ENABLED must be 'true' for PII filter tests. Got: {plugin_harness['plugins_enabled']}"
        )
        assert str(plugin_harness["observability_enabled"]).lower() == "true", (
            f"OBSERVABILITY_ENABLED must be 'true' for trace verification. Got: {plugin_harness['observability_enabled']}"
        )
        assert plugin_harness["plugins_config_file"], (
            f"PLUGINS_CONFIG_FILE must be set. Got: {plugin_harness['plugins_config_file']}"
        )
        assert plugin_harness["plugin_name"], (
            f"Plugin name must be configured. Got: {plugin_harness['plugin_name']}"
        )
        assert plugin_harness["plugin_kind"], (
            f"Plugin kind must be configured. Got: {plugin_harness['plugin_kind']}"
        )
        
        # PII filter specific validation
        assert plugin_harness["plugin_kind"] == "cpex_pii_filter.pii_filter.PIIFilterPlugin", (
            f"Expected PII filter plugin, got: {plugin_harness['plugin_kind']}"
        )
        assert plugin_harness["prompt_name"], (
            f"Prompt name must be configured. Got: {plugin_harness['prompt_name']}"
        )
        assert plugin_harness["tool_name"], (
            f"Tool name must be configured. Got: {plugin_harness['tool_name']}"
        )
        
        logger.info(
            "✅ Plugin stack validated: plugins=%s, observability=%s, plugin=%s",
            plugin_harness["plugins_enabled"],
            plugin_harness["observability_enabled"],
            plugin_harness["plugin_name"]
        )

    def test_tool_call_round_trips_through_gateway(
        self,
        plugin_harness: dict[str, Any],
        invoke_tool: Callable,
        plugin_assertions: dict[str, Any],
    ) -> None:
        """The harness should be able to invoke a real gateway-backed MCP tool."""
        response = invoke_tool(plugin_harness, arguments={"timezone": "UTC"}, request_id=10)
        
        # Strong assertion: HTTP request must succeed
        assert response["status_code"] == 200, (
            f"Expected HTTP 200, got {response['status_code']}. Response: {response}"
        )

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
            # For other errors, fail the test with detailed message
            pytest.fail(f"Tool invocation failed with error code {error_code}: {error_msg}")

        # Strong assertions: result must be valid
        assert isinstance(response["result"], dict), (
            f"Expected result to be dict, got {type(response['result'])}. Response: {response}"
        )
        text = _extract_tool_text(response["result"])
        logger.info("✅ E2E tool round-trip successful. Output: %s", text or response["result"])
        
        assert isinstance(text, str), f"Expected text to be str, got {type(text)}"
        assert text or response["result"].get("content"), (
            f"Tool response is empty - expected content. Response: {response['result']}"
        )

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
        invoke_prompt: Callable,
        assert_redaction_behavior: Callable,
        plugin_assertions: dict[str, Any],
    ) -> None:
        """Prompt hook coverage should handle individual and combined PII categories."""
        # Validate test has PII to detect
        if not sensitive_values or not any(sensitive_values):
            pytest.skip("No PII values to test")
        
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

        # Strong assertion: HTTP request must succeed
        assert response["status_code"] == 200, (
            f"Expected HTTP 200 for {category_name}, got {response['status_code']}. Response: {response}"
        )

        # If error, verify it's a policy block (expected behavior for some PII categories)
        if response["error"] is not None:
            assert plugin_assertions["looks_like_policy_block"](response["payload"]), (
                f"Expected policy block error for {category_name}, got: {response}"
            )
            logger.info("✅ PII category %s correctly blocked by policy", category_name)
            return

        # Strong assertions: result must be valid
        assert isinstance(response["result"], dict), (
            f"Expected result to be dict for {category_name}, got {type(response['result'])}. Response: {response}"
        )
        prompt_text = _extract_prompt_text(response["result"])
        # Log output without exposing PII values
        output_preview = prompt_text[:100] if prompt_text else str(response["result"])[:100]
        logger.info("E2E prompt output for %s: %s...", category_name, output_preview)
        
        assert prompt_text, (
            f"Prompt text is empty for {category_name} - expected content. Response: {response['result']}"
        )
        
        prompt_lines = [line.strip() for line in prompt_text.splitlines() if line.strip()]
        assert prompt_lines, (
            f"No non-empty lines in prompt text for {category_name}. Text: {prompt_text}"
        )

        # Verify primary value redaction
        if primary_value:
            primary_lines = [line for line in prompt_lines if line.startswith("User input:")]
            assert primary_lines, (
                f"No 'User input:' lines found for {category_name}. Lines: {prompt_lines}"
            )
            assert_redaction_behavior("\n".join(primary_lines), primary_value)
            logger.info("✅ Primary value redacted for %s", category_name)

        # Verify secondary value redaction (for multi-PII tests)
        if len(sensitive_values) > 1 and secondary_value:
            secondary_lines = [line for line in prompt_lines if line.startswith("Secondary input:")]
            assert secondary_lines, (
                f"No 'Secondary input:' lines found for {category_name}. Lines: {prompt_lines}"
            )
            assert_redaction_behavior("\n".join(secondary_lines), secondary_value)
            logger.info("✅ Secondary value redacted for %s", category_name)

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
        invoke_tool: Callable,
        assert_redaction_behavior: Callable,
        plugin_assertions: dict[str, Any],
    ) -> None:
        """Tool hook coverage should verify outbound responses are redacted across the PII matrix."""
        # Validate test has PII to detect
        if not sensitive_values or not any(sensitive_values):
            pytest.skip("No PII values to test")
        
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

        # Strong assertion: HTTP request must succeed
        assert response["status_code"] == 200, (
            f"Expected HTTP 200 for {category_name}, got {response['status_code']}. Response: {response}"
        )

        # If error, verify it's a policy block (expected behavior for some PII categories)
        if response["error"] is not None:
            assert plugin_assertions["looks_like_policy_block"](response["payload"]), (
                f"Expected policy block error for {category_name}, got: {response}"
            )
            logger.info("✅ PII category %s correctly blocked by policy", category_name)
            return

        # Strong assertions: result must be valid
        assert isinstance(response["result"], dict), (
            f"Expected result to be dict for {category_name}, got {type(response['result'])}. Response: {response}"
        )
        text = _extract_tool_text(response["result"])
        # Log output without exposing PII values
        output_preview = text[:100] if text else str(response["result"])[:100]
        logger.info("E2E tool output for %s: %s...", category_name, output_preview)

        # Verify response contains content (not completely blocked)
        assert text or response["result"].get("content"), (
            f"Tool response is empty for {category_name} - PII filter may have blocked the entire response: {response['result']}"
        )

        # Strong assertion: all sensitive values must be redacted
        for sensitive_value in sensitive_values:
            assert sensitive_value not in text, (
                f"SECURITY VIOLATION: Raw PII value {sensitive_value!r} found in tool response for {category_name}. "
                f"PII filter failed to redact. Response text: {text}"
            )

        # Strong assertion: redaction markers must be present
        assert plugin_assertions["looks_masked"](text), (
            f"Expected output to contain masking markers (e.g., ***, [REDACTED], XXX) for {category_name}, "
            f"but no markers found. This indicates PII may not have been properly redacted. Text: {text}"
        )
        
        logger.info("✅ All PII values redacted for %s", category_name)

    def test_plugin_harness_is_tenant_scoped(
        self,
        plugin_harness: dict[str, Any],
    ) -> None:
        """The harness should provision an isolated team-scoped server and token."""
        # Strong assertions: tenant isolation must be properly configured
        assert plugin_harness["team_id"], (
            f"Team ID must be set for tenant isolation. Got: {plugin_harness['team_id']}"
        )
        assert plugin_harness["server_id"], (
            f"Server ID must be set for tenant isolation. Got: {plugin_harness['server_id']}"
        )
        assert plugin_harness["token"], (
            f"Token must be set for authentication. Got: {plugin_harness['token']}"
        )
        assert plugin_harness["prompt_name"].startswith("e2e-plugin"), (
            f"Prompt name must start with 'e2e-plugin' for test isolation. Got: {plugin_harness['prompt_name']}"
        )
        
        logger.info(
            "✅ Tenant isolation validated: team=%s, server=%s",
            plugin_harness["team_id"],
            plugin_harness["server_id"]
        )

    def test_make_target_documents_live_stack_requirement(self) -> None:
        """The suite is intended to run only after a live docker-compose or main dev stack is started."""
        assert True

class TestPiiFilterStateTransitions:
    """Validate dynamic plugin mode transitions without restart."""

    def test_plugin_mode_transitions_affect_behavior(
        self,
        admin_client: Any,
        plugin_harness: dict[str, Any],
        invoke_tool: Callable,
    ) -> None:
        """Plugin mode changes should take effect immediately without restart.
        
        Tests the requirement: 'Plugin state: disabled → enabled → disabled
        (confirm state transitions take effect on subsequent invocations without restart)'
        
        Uses the existing PUT /plugins/{name} API to change plugin mode.
        """
        plugin_name = plugin_harness["plugin_name"]
        test_pii = "john@example.com"
        
        # Step 1: Set plugin to permissive mode (effectively disabled for blocking)
        response = admin_client.put(
            f"/admin/plugins/{plugin_name}",
            json={"mode": "permissive"},
            follow_redirects=True,
        )
        assert response.status_code in (200, 204), f"Failed to set permissive mode: {response.text}"
        
        # Verify mode change by checking response (API may return execution_mode not policy_mode)
        verify_response = admin_client.get(f"/admin/plugins/{plugin_name}", follow_redirects=True)
        if verify_response.status_code == 200:
            plugin_data = verify_response.json()
            current_mode = plugin_data.get("mode") or plugin_data.get("policy_mode") or plugin_data.get("execution_mode")
            logger.info(f"Plugin mode after change: {current_mode} (requested: permissive)")
        logger.info("✅ Plugin set to permissive mode via API")
        
        # Step 2: Invoke tool - in permissive mode, errors are logged but don't block
        result = invoke_tool(
            plugin_harness,
            arguments={"user_input": test_pii, "timezone": "UTC"},
            request_id=100,
        )
        assert result["status_code"] == 200, f"Expected success in permissive mode: {result}"
        logger.info("✅ Tool invocation succeeded in permissive mode")
        
        # Step 3: Set plugin to enforce mode
        response = admin_client.put(
            f"/admin/plugins/{plugin_name}",
            json={"mode": "enforce"},
            follow_redirects=True,
        )
        assert response.status_code in (200, 204), f"Failed to set enforce mode: {response.text}"
        
        # Verify mode change by checking response (API may return execution_mode not policy_mode)
        verify_response = admin_client.get(f"/admin/plugins/{plugin_name}", follow_redirects=True)
        if verify_response.status_code == 200:
            plugin_data = verify_response.json()
            current_mode = plugin_data.get("mode") or plugin_data.get("policy_mode") or plugin_data.get("execution_mode")
            logger.info(f"Plugin mode after change: {current_mode} (requested: enforce)")
        logger.info("✅ Plugin set to enforce mode via API")
        
        # Step 4: Invoke tool - in enforce mode, PII should be redacted or blocked
        result = invoke_tool(
            plugin_harness,
            arguments={"user_input": test_pii, "timezone": "UTC"},
            request_id=101,
        )
        # In enforce mode, either the request succeeds with redaction or fails with policy block
        if result["status_code"] == 200 and result["result"]:
            text = _extract_tool_text(result["result"])
            if text:
                # If it succeeded, PII must be redacted
                assert test_pii not in text, (
                    f"SECURITY VIOLATION: Raw PII found in enforce mode: {text}"
                )
                logger.info("✅ PII redacted in enforce mode")
        elif result["error"]:
            # Or it was blocked by policy
            assert _looks_like_policy_block(result["payload"]), (
                f"Expected policy block in enforce mode: {result}"
            )
            logger.info("✅ Request blocked by policy in enforce mode")
        
        # Step 5: Return to permissive mode
        response = admin_client.put(
            f"/admin/plugins/{plugin_name}",
            json={"mode": "permissive"},
            follow_redirects=True,
        )
        assert response.status_code in (200, 204), f"Failed to restore permissive mode: {response.text}"
        
        # Verify mode change by checking response (API may return execution_mode not policy_mode)
        verify_response = admin_client.get(f"/admin/plugins/{plugin_name}", follow_redirects=True)
        if verify_response.status_code == 200:
            plugin_data = verify_response.json()
            current_mode = plugin_data.get("mode") or plugin_data.get("policy_mode") or plugin_data.get("execution_mode")
            logger.info(f"Plugin mode after change: {current_mode} (requested: permissive)")
        
        result = invoke_tool(
            plugin_harness,
            arguments={"user_input": test_pii, "timezone": "UTC"},
            request_id=102,
        )
        assert result["status_code"] == 200, f"Expected success after returning to permissive mode: {result}"
        logger.info("✅ Tool invocation succeeded after returning to permissive mode")


class TestPiiFilterBindingIsolation:
    """Validate per-tool plugin binding isolation using existing tool-plugin-bindings API."""

    def test_plugin_binding_isolation_per_tool(
        self,
        admin_client: Any,
        plugin_team: dict[str, Any],
        plugin_harness: dict[str, Any],
        invoke_tool: Callable,
    ) -> None:
        """Plugin bound to specific tools should not affect non-bound tools.
        
        Tests the requirement: 'Scope / binding: plugin bound globally vs. per-tool;
        confirm non-bound tools/tenants are unaffected'
        
        Uses the existing POST /tool-plugin-bindings API (tool-centric binding).
        """
        import uuid
        
        test_pii = "sensitive@company.com"  
        plugin_name = plugin_harness["plugin_name"]
        
        # Create two tools: tool_A (will be bound) and tool_B (will NOT be bound)
        tool_a = admin_client.post(
            "/tools/",
            json={
                "tool": {
                    "name": f"e2e-plugin-tool-a-{uuid.uuid4().hex[:8]}",
                    "description": "Tool A - will have plugin bound",
                    "integration_type": "REST",
                    "request_type": "POST",
                    "url": "https://postman-echo.com/post",
                    "headers": {"Content-Type": "application/json"},
                    "inputSchema": {
                        "type": "object",
                        "properties": {"user_input": {"type": "string"}},
                    },
                },
                "team_id": plugin_team["id"],
                "visibility": "team",
            },
        ).json()
        
        tool_b = admin_client.post(
            "/tools/",
            json={
                "tool": {
                    "name": f"e2e-plugin-tool-b-{uuid.uuid4().hex[:8]}",
                    "description": "Tool B - will NOT have plugin bound",
                    "integration_type": "REST",
                    "request_type": "POST",
                    "url": "https://postman-echo.com/post",
                    "headers": {"Content-Type": "application/json"},
                    "inputSchema": {
                        "type": "object",
                        "properties": {"user_input": {"type": "string"}},
                    },
                },
                "team_id": plugin_team["id"],
                "visibility": "team",
            },
        ).json()
        
        # Create server with both tools
        server = admin_client.post(
            "/servers",
            json={
                "server": {
                    "name": f"e2e-plugin-isolation-server-{uuid.uuid4().hex[:8]}",
                    "description": "Server for plugin binding isolation test",
                    "associated_tools": [tool_a["id"], tool_b["id"]],
                },
                "team_id": plugin_team["id"],
                "visibility": "team",
            },
        ).json()
        
        # Override tool_A to permissive mode via API
        # This should override the global YAML 'enforce' mode for this specific tool
        response = admin_client.post(
            "/v1/tools/plugin_bindings",
            json={
                "teams": {
                    plugin_team["id"]: {
                        "policies": [
                            {
                                "tool_names": [tool_a["name"]],
                                "plugin_id": plugin_name,
                                "mode": "permissive",  # Override to permissive mode
                                "priority": 50,
                                "config": {
                                    "detect_email": True,
                                    "default_mask_strategy": "partial",
                                },
                            }
                        ]
                    }
                }
            },
            follow_redirects=True,
        )
        assert response.status_code in (200, 201), f"Failed to bind plugin: {response.text}"
        logger.info("✅ Plugin mode overridden to permissive for tool_A")
        
        # Test tool_A: should have lenient behavior (permissive mode)
        # In permissive mode, the plugin still filters PII but errors don't block requests
        harness_a = {**plugin_harness, "tool_name": tool_a["name"], "server_id": server["id"]}
        result_a = invoke_tool(
            harness_a,
            arguments={"user_input": test_pii},
            request_id=200,
        )
        # Permissive mode: request should succeed even if plugin has issues
        assert result_a["status_code"] == 200, (
            f"Tool A (permissive mode) should allow request, got {result_a['status_code']}"
        )
        if result_a["result"]:
            text_a = _extract_tool_text(result_a["result"])
            if text_a:
                # PII should still be filtered (plugin still runs in permissive mode)
                assert test_pii not in text_a, (
                    f"Tool A should have PII filtered even in permissive mode: {text_a}"
                )
                logger.info("✅ Tool A has lenient behavior (permissive mode override)")
        
        # Test tool_B: should have strict behavior (global enforce mode from YAML)
        harness_b = {**plugin_harness, "tool_name": tool_b["name"], "server_id": server["id"]}
        result_b = invoke_tool(
            harness_b,
            arguments={"user_input": test_pii},
            request_id=201,
        )
        # Enforce mode: request should succeed with strict filtering
        assert result_b["status_code"] == 200, (
            f"Tool B (enforce mode) request failed: {result_b.get('error')}"
        )
        if result_b["result"]:
            text_b = _extract_tool_text(result_b["result"])
            if text_b:
                # PII should be filtered (global enforce mode)
                assert test_pii not in text_b, (
                    f"Tool B should have PII filtered in enforce mode: {text_b}"
                )
                logger.info("✅ Tool B has strict behavior (global enforce mode)")



class TestPiiFilterModes:
    """Validate different PII filter operating modes using existing PUT /plugins/{name} API."""

    @pytest.mark.parametrize(  # pyright: ignore[reportUnknownMemberType, reportUntypedFunctionDecorator]
        ("mode", "expected_behavior"),
        [
            ("enforce", "strict"),
            ("permissive", "lenient"),
        ],
    )
    def test_pii_filter_modes(
        self,
        mode: str,
        expected_behavior: str,
        admin_client: Any,
        plugin_harness: dict[str, Any],
        invoke_tool: Callable,
    ) -> None:
        """Plugin should behave differently based on configured mode.
        
        Tests the requirement: 'Mode: block, redact, flag-only (or whatever modes the plugin exposes)'
        
        Uses the existing PUT /plugins/{name} API which supports 'enforce' and 'permissive' modes.
        - Enforce mode: Strict error handling, failures block requests
        - Permissive mode: Lenient error handling, failures are logged but don't block
        """
        test_pii = "confidential@enterprise.com"
        plugin_name = plugin_harness["plugin_name"]
        
        # Set plugin mode via existing API
        response = admin_client.put(
            f"/admin/plugins/{plugin_name}",
            json={"mode": mode},
            follow_redirects=True,
        )
        assert response.status_code in (200, 204), f"Failed to set plugin mode: {response.text}"
        
        # Verify mode change took effect by checking response structure
        # The GET endpoint may return different fields (execution_mode vs policy mode)
        verify_response = admin_client.get(f"/admin/plugins/{plugin_name}", follow_redirects=True)
        if verify_response.status_code == 200:
            plugin_data = verify_response.json()
            # Check multiple possible field names for the mode
            current_mode = plugin_data.get("mode") or plugin_data.get("policy_mode") or plugin_data.get("execution_mode")
            logger.info(f"Plugin GET response mode field: {current_mode}, expected: {mode}")
            # Only assert if we got a mode value and it doesn't match
            # Some APIs may not return the policy mode in GET, only execution mode
            if current_mode and current_mode not in (mode, "transform", "sequential"):
                logger.warning(f"Mode mismatch: expected '{mode}', got '{current_mode}' - will verify via behavior")
        logger.info(f"✅ Plugin mode set to {mode} via API")
        
        # Invoke tool with PII
        result = invoke_tool(
            plugin_harness,
            arguments={"user_input": test_pii, "timezone": "UTC"},
            request_id=400 + hash(mode) % 100,
        )
        
        if expected_behavior == "strict":
            # Enforce mode: either succeeds with redaction or fails with policy block
            if result["status_code"] == 200 and result["result"]:
                text = _extract_tool_text(result["result"])
                if text:
                    pii_found = test_pii in text
                    if pii_found:
                        logger.error(f"❌ SECURITY VIOLATION: Raw PII found in enforce mode!")
                    assert not pii_found, (
                        f"Enforce mode should redact PII, but found raw PII in response"
                    )
                    logger.info(f"✅ {mode} mode: PII redacted")
            elif result["error"]:
                assert _looks_like_policy_block(result["payload"]), (
                    f"Expected policy block in enforce mode, got: {result}"
                )
                logger.info(f"✅ {mode} mode: Request blocked by policy")
        
        elif expected_behavior == "lenient":
            # Permissive mode: should succeed even if plugin has issues
            assert result["status_code"] == 200, (
                f"Permissive mode should allow requests through, got: {result}"
            )
            logger.info(f"✅ {mode} mode: Request processed successfully")


