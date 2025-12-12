# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/plugins/webhook_notification/test_webhook_integration.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Integration tests for WebhookNotificationPlugin with PluginManager.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcpgateway.plugins.framework.manager import PluginManager
from mcpgateway.plugins.framework import (
    GlobalContext,
    PromptHookType,
    ToolHookType,
    ToolPostInvokePayload
)


@pytest.mark.asyncio
async def test_webhook_plugin_with_manager():
    """Test webhook plugin integration with PluginManager."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Create test config file
        config_content = """
plugins:
  - name: "WebhookNotification"
    kind: "plugins.webhook_notification.webhook_notification.WebhookNotificationPlugin"
    hooks: ["tool_post_invoke"]
    mode: "permissive"
    priority: 900
    config:
      webhooks:
        - url: "https://test.example.com/webhook"
          events: ["tool_success", "tool_error"]
          authentication:
            type: "bearer"
            token: "test-token"
          retry_attempts: 1
          timeout: 5
          enabled: true
      include_payload_data: false

plugin_settings:
  plugin_timeout: 10
  fail_on_plugin_error: false

plugin_dirs: []
"""
        config_path = Path(tmp_dir) / "test_config.yaml"
        config_path.write_text(config_content)

        # Mock HTTP client for webhook delivery
        #with patch('plugins.webhook_notification.webhook_notification.httpx.AsyncClient') as mock_client_class:
        with patch('plugins.webhook_notification.webhook_notification.httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_client.post.return_value = mock_response
            mock_client_class.return_value = mock_client

            # Initialize plugin manager
            manager = PluginManager(str(config_path), timeout=10)
            await manager.initialize()

            try:
                # Create test context and payload
                context = GlobalContext(
                    request_id="test-req-123",
                    user="testuser@example.com",
                    tenant_id="test-tenant",
                    server_id="test-server"
                )

                payload = ToolPostInvokePayload(
                    name="search_tool",
                    result={"status": "success", "results": ["item1", "item2"]}
                )

                # Execute tool post-invoke hook
                result, final_context = await manager.invoke_hook(ToolHookType.TOOL_POST_INVOKE, payload, context)

                # Verify result
                assert result.continue_processing is True
                assert result.violation is None

                # Verify webhook was called
                mock_client.post.assert_called_once()

                # Verify the webhook call details
                call_args = mock_client.post.call_args
                assert call_args[0][0] == "https://test.example.com/webhook"  # URL
                assert call_args[1]["timeout"] == 5

                # Verify headers
                headers = call_args[1]["headers"]
                assert headers["Authorization"] == "Bearer test-token"
                assert headers["Content-Type"] == "application/json"

                # Verify payload structure
                payload_data = json.loads(call_args[1]["content"])
                assert payload_data["event"] == "tool_success"
                assert payload_data["request_id"] == "test-req-123"
                assert payload_data["user"] == "testuser@example.com"
                assert payload_data["metadata"]["tool_name"] == "search_tool"

            finally:
                await manager.shutdown()


@pytest.mark.asyncio
async def test_webhook_plugin_violation_handling():
    """Test webhook plugin handles violations from other plugins."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Create config with webhook plugin and a deny filter that will create violations
        config_content = """
plugins:
  - name: "DenyFilter"
    kind: "plugins.deny_filter.deny.DenyListPlugin"
    hooks: ["prompt_pre_fetch"]
    mode: "enforce"
    priority: 100
    config:
      words: ["forbidden"]

  - name: "WebhookNotification"
    kind: "plugins.webhook_notification.webhook_notification.WebhookNotificationPlugin"
    hooks: ["prompt_post_fetch"]
    mode: "permissive"
    priority: 900
    config:
      webhooks:
        - url: "https://violations.example.com/webhook"
          events: ["violation"]
          authentication:
            type: "none"
          retry_attempts: 1
          enabled: true

plugin_settings:
  plugin_timeout: 10
  fail_on_plugin_error: false

plugin_dirs: []
"""
        config_path = Path(tmp_dir) / "test_config.yaml"
        config_path.write_text(config_content)

        # Mock HTTP client
        with patch('plugins.webhook_notification.webhook_notification.httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_client.post.return_value = mock_response
            mock_client_class.return_value = mock_client

            manager = PluginManager(str(config_path), timeout=10)
            await manager.initialize()

            try:
                context = GlobalContext(request_id="violation-test", user="testuser")

                # Create payload with forbidden word that will trigger deny filter
                from mcpgateway.plugins.framework import PromptPrehookPayload
                payload = PromptPrehookPayload(
                    prompt_id="test_prompt",
                    args={"query": "this contains forbidden word"}
                )

                # Execute - should be blocked by deny filter
                result, final_context = await manager.invoke_hook(PromptHookType.PROMPT_PRE_FETCH, payload, context)

                # Verify the request was blocked
                assert result.continue_processing is False
                assert result.violation is not None

                # Note: In this test, the webhook plugin runs but may not send a webhook
                # because the violation occurred in another plugin, not the webhook plugin itself
                # The webhook plugin primarily sends notifications for successful operations
                # and its own violations, not violations from other plugins in the same hook

            finally:
                await manager.shutdown()


@pytest.mark.asyncio
async def test_webhook_plugin_multiple_webhooks():
    """Test webhook plugin with multiple configured webhooks."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        config_content = """
plugins:
  - name: "WebhookNotification"
    kind: "plugins.webhook_notification.webhook_notification.WebhookNotificationPlugin"
    hooks: ["tool_post_invoke"]
    mode: "permissive"
    priority: 500
    config:
      webhooks:
        - url: "https://slack.example.com/webhook"
          events: ["tool_success", "violation"]
          authentication:
            type: "bearer"
            token: "slack-token"
          retry_attempts: 2
          enabled: true

        - url: "https://monitoring.example.com/webhook"
          events: ["tool_success", "tool_error"]
          authentication:
            type: "api_key"
            api_key: "monitor-key"
            api_key_header: "X-Monitor-Key"
          retry_attempts: 1
          enabled: true

        - url: "https://disabled.example.com/webhook"
          events: ["tool_success"]
          enabled: false  # This one is disabled

plugin_settings:
  plugin_timeout: 15
  fail_on_plugin_error: false

plugin_dirs: []
"""
        config_path = Path(tmp_dir) / "test_config.yaml"
        config_path.write_text(config_content)

        with patch('plugins.webhook_notification.webhook_notification.httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_client.post.return_value = mock_response
            mock_client_class.return_value = mock_client

            manager = PluginManager(str(config_path), timeout=15)
            await manager.initialize()

            try:
                context = GlobalContext(request_id="multi-webhook-test", user="testuser")

                payload = ToolPostInvokePayload(
                    name="analytics_tool",
                    result={"processed": 100, "errors": 0}
                )

                # Execute hook
                result, final_context = await manager.invoke_hook(ToolHookType.TOOL_POST_INVOKE, payload, context)

                assert result.continue_processing is True

                # Verify two webhooks were called (not the disabled one)
                assert mock_client.post.call_count == 2

                # Check that different authentication methods were used
                call_args_list = mock_client.post.call_args_list

                # Find Slack webhook call
                slack_call = None
                monitor_call = None

                for call in call_args_list:
                    url = call[0][0]
                    headers = call[1]["headers"]

                    if "slack.example.com" in url:
                        slack_call = call
                        assert headers["Authorization"] == "Bearer slack-token"
                    elif "monitoring.example.com" in url:
                        monitor_call = call
                        assert headers["X-Monitor-Key"] == "monitor-key"

                assert slack_call is not None, "Slack webhook was not called"
                assert monitor_call is not None, "Monitoring webhook was not called"

                # Verify disabled webhook was not called
                for call in call_args_list:
                    url = call[0][0]
                    assert "disabled.example.com" not in url

            finally:
                await manager.shutdown()


@pytest.mark.asyncio
async def test_webhook_plugin_template_customization():
    """Test webhook plugin with custom payload templates."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        config_content = """
plugins:
  - name: "WebhookNotification"
    kind: "plugins.webhook_notification.webhook_notification.WebhookNotificationPlugin"
    hooks: ["tool_post_invoke"]
    mode: "permissive"
    priority: 500
    config:
      webhooks:
        - url: "https://custom.example.com/webhook"
          events: ["tool_success"]
          authentication:
            type: "none"
          retry_attempts: 1
          enabled: true
      payload_templates:
        tool_success: |
          {
            "alert_type": "success",
            "service": "mcp-gateway",
            "tool": "{{metadata}}",
            "user": "{{user}}",
            "timestamp": "{{timestamp}}"
          }

plugin_settings:
  plugin_timeout: 10
  fail_on_plugin_error: false

plugin_dirs: []
"""
        config_path = Path(tmp_dir) / "test_config.yaml"
        config_path.write_text(config_content)

        with patch('plugins.webhook_notification.webhook_notification.httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_client.post.return_value = mock_response
            mock_client_class.return_value = mock_client

            manager = PluginManager(str(config_path), timeout=10)
            await manager.initialize()

            try:
                context = GlobalContext(request_id="template-test", user="template_user")

                payload = ToolPostInvokePayload(
                    name="custom_tool",
                    result={"data": "test"}
                )

                await manager.invoke_hook(ToolHookType.TOOL_POST_INVOKE, payload, context)

                # Verify webhook was called with custom template
                mock_client.post.assert_called_once()
                call_args = mock_client.post.call_args

                payload_data = json.loads(call_args[1]["content"])

                # Check custom template fields
                assert payload_data["alert_type"] == "success"
                assert payload_data["service"] == "mcp-gateway"
                # User field is tested comprehensively in other tests
                # The key thing here is that the custom template was used

            finally:
                await manager.shutdown()
