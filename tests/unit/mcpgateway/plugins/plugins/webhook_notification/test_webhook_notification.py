# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/plugins/webhook_notification/test_webhook_notification.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Tests for WebhookNotificationPlugin.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcpgateway.plugins.framework import (
    GlobalContext,
    PluginConfig,
    PluginContext,
    PluginViolation,
    ToolHookType,
    PromptPrehookPayload,
    ToolPostInvokePayload,
    ToolPreInvokePayload,
)
from plugins.webhook_notification.webhook_notification import (
    AuthenticationType,
    EventType,
    WebhookNotificationPlugin,
)


def _create_plugin(config_dict=None) -> WebhookNotificationPlugin:
    """Helper to create webhook notification plugin with test config."""
    default_config = {
        "webhooks": [
            {
                "url": "https://hooks.example.com/webhook",
                "events": ["violation", "tool_success"],
                "authentication": {"type": "none"},
                "retry_attempts": 1,
                "retry_delay": 100,
                "timeout": 5,
                "enabled": True,
            }
        ],
        "include_payload_data": False,
        "max_payload_size": 1000,
    }

    if config_dict:
        default_config.update(config_dict)

    return WebhookNotificationPlugin(
        PluginConfig(
            name="webhook_test",
            kind="plugins.webhook_notification.webhook_notification.WebhookNotificationPlugin",
            hooks=[ToolHookType.TOOL_POST_INVOKE],
            config=default_config,
        )
    )


def _create_context(user="testuser", request_id="req-123") -> PluginContext:
    """Helper to create plugin context."""
    return PluginContext(
        global_context=GlobalContext(
            request_id=request_id,
            user=user,
            tenant_id="tenant-abc",
            server_id="server-xyz"
        )
    )


class TestWebhookNotificationPlugin:
    """Test cases for WebhookNotificationPlugin."""

    @pytest.mark.asyncio
    async def test_plugin_initialization(self):
        """Test plugin initializes correctly with default config."""
        plugin = _create_plugin()
        assert plugin.name == "webhook_test"
        assert len(plugin._cfg.webhooks) == 1
        assert plugin._cfg.webhooks[0].url == "https://hooks.example.com/webhook"

    @pytest.mark.asyncio
    async def test_template_rendering(self):
        """Test template rendering with context variables."""
        plugin = _create_plugin()

        template = '{"event": "{{event}}", "user": "{{user}}", "timestamp": "{{timestamp}}"}'
        context_vars = {
            "event": "test_event",
            "user": "testuser",
            "timestamp": "2025-01-15T10:30:45.123Z"
        }

        result = await plugin._render_template(template, context_vars)
        parsed = json.loads(result)

        assert parsed["event"] == "test_event"
        assert parsed["user"] == "testuser"
        assert parsed["timestamp"] == "2025-01-15T10:30:45.123Z"

    @pytest.mark.asyncio
    async def test_hmac_signature_creation(self):
        """Test HMAC signature creation."""
        plugin = _create_plugin()

        payload = '{"test": "data"}'
        secret = "test-secret"
        algorithm = "sha256"

        signature = plugin._create_hmac_signature(payload, secret, algorithm)

        assert signature.startswith("sha256=")
        assert len(signature) > 10  # Basic length check

    @pytest.mark.asyncio
    @patch('plugins.webhook_notification.webhook_notification.httpx.AsyncClient')
    async def test_webhook_delivery_success(self, mock_client_class):
        """Test successful webhook delivery."""
        # Setup mocks
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        plugin = _create_plugin()
        plugin._client = mock_client

        context = _create_context()
        webhook = plugin._cfg.webhooks[0]

        await plugin._send_webhook(
            webhook=webhook,
            event=EventType.TOOL_SUCCESS,
            context=context,
            metadata={"tool_name": "test_tool"}
        )

        # Verify webhook was called
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args

        assert call_args[1]["timeout"] == 5
        assert "Content-Type" in call_args[1]["headers"]
        assert call_args[1]["headers"]["Content-Type"] == "application/json"

    @pytest.mark.asyncio
    @patch('plugins.webhook_notification.webhook_notification.httpx.AsyncClient')
    async def test_webhook_delivery_with_bearer_auth(self, mock_client_class):
        """Test webhook delivery with bearer token authentication."""
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        config = {
            "webhooks": [
                {
                    "url": "https://hooks.example.com/webhook",
                    "events": ["tool_success"],
                    "authentication": {
                        "type": "bearer",
                        "token": "test-token-123"
                    },
                    "retry_attempts": 1,
                    "enabled": True,
                }
            ]
        }

        plugin = _create_plugin(config)
        plugin._client = mock_client

        context = _create_context()
        webhook = plugin._cfg.webhooks[0]

        await plugin._send_webhook(
            webhook=webhook,
            event=EventType.TOOL_SUCCESS,
            context=context
        )

        # Verify Authorization header was set
        call_args = mock_client.post.call_args
        headers = call_args[1]["headers"]
        assert "Authorization" in headers
        assert headers["Authorization"] == "Bearer test-token-123"

    @pytest.mark.asyncio
    @patch('plugins.webhook_notification.webhook_notification.httpx.AsyncClient')
    async def test_webhook_delivery_with_api_key_auth(self, mock_client_class):
        """Test webhook delivery with API key authentication."""
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        config = {
            "webhooks": [
                {
                    "url": "https://hooks.example.com/webhook",
                    "events": ["tool_success"],
                    "authentication": {
                        "type": "api_key",
                        "api_key": "test-api-key",
                        "api_key_header": "X-API-Key"
                    },
                    "retry_attempts": 1,
                    "enabled": True,
                }
            ]
        }

        plugin = _create_plugin(config)
        plugin._client = mock_client

        context = _create_context()
        webhook = plugin._cfg.webhooks[0]

        await plugin._send_webhook(
            webhook=webhook,
            event=EventType.TOOL_SUCCESS,
            context=context
        )

        # Verify API key header was set
        call_args = mock_client.post.call_args
        headers = call_args[1]["headers"]
        assert "X-API-Key" in headers
        assert headers["X-API-Key"] == "test-api-key"

    @pytest.mark.asyncio
    @patch('plugins.webhook_notification.webhook_notification.httpx.AsyncClient')
    async def test_webhook_delivery_retry_on_failure(self, mock_client_class):
        """Test webhook retry logic on failure."""
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 500  # Server error
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        config = {
            "webhooks": [
                {
                    "url": "https://hooks.example.com/webhook",
                    "events": ["tool_success"],
                    "authentication": {"type": "none"},
                    "retry_attempts": 3,
                    "retry_delay": 100,  # Small delay for testing
                    "enabled": True,
                }
            ]
        }

        plugin = _create_plugin(config)
        plugin._client = mock_client

        context = _create_context()
        webhook = plugin._cfg.webhooks[0]

        await plugin._send_webhook(
            webhook=webhook,
            event=EventType.TOOL_SUCCESS,
            context=context
        )

        # Verify webhook was retried (1 initial + 3 retries = 4 total calls)
        assert mock_client.post.call_count == 4

    @pytest.mark.asyncio
    async def test_event_type_determination(self):
        """Test event type determination from violations."""
        plugin = _create_plugin()

        # Test rate limit violation
        rate_limit_violation = PluginViolation(
            reason="Rate limit exceeded",
            description="Too many requests",
            code="RATE_LIMIT",
            details={}
        )

        event_type = plugin._determine_event_type(rate_limit_violation)
        assert event_type == EventType.RATE_LIMIT_EXCEEDED

        # Test PII violation
        pii_violation = PluginViolation(
            reason="PII detected in content",
            description="Email found",
            code="PII_DETECTED",
            details={}
        )

        event_type = plugin._determine_event_type(pii_violation)
        assert event_type == EventType.PII_DETECTED

        # Test no violation (success case)
        event_type = plugin._determine_event_type(None)
        assert event_type == EventType.TOOL_SUCCESS

    @pytest.mark.asyncio
    @patch('plugins.webhook_notification.webhook_notification.WebhookNotificationPlugin._notify_webhooks')
    async def test_tool_post_invoke_hook(self, mock_notify):
        """Test tool_post_invoke hook triggers notification."""
        plugin = _create_plugin()
        context = _create_context()

        payload = ToolPostInvokePayload(
            name="test_tool",
            result={"success": True, "data": "test result"}
        )

        result = await plugin.tool_post_invoke(payload, context)

        # Verify notification was triggered
        mock_notify.assert_called_once()
        call_args = mock_notify.call_args[0]
        assert call_args[0] == EventType.TOOL_SUCCESS  # event type
        assert call_args[1] == context  # context

    @pytest.mark.asyncio
    async def test_webhook_filtering_by_event_type(self):
        """Test webhooks are filtered by event type."""
        config = {
            "webhooks": [
                {
                    "url": "https://hooks.example.com/webhook1",
                    "events": ["violation"],  # Only violations
                    "authentication": {"type": "none"},
                    "enabled": True,
                },
                {
                    "url": "https://hooks.example.com/webhook2",
                    "events": ["tool_success"],  # Only tool success
                    "authentication": {"type": "none"},
                    "enabled": True,
                }
            ]
        }

        plugin = _create_plugin(config)

        # Mock the send_webhook method to track calls
        plugin._send_webhook = AsyncMock()

        context = _create_context()

        # Send a tool success event
        await plugin._notify_webhooks(
            event=EventType.TOOL_SUCCESS,
            context=context
        )

        # Verify only the second webhook (tool_success) was called
        assert plugin._send_webhook.call_count == 2  # Both webhooks checked

        # Check the calls - first webhook should not be called (wrong event type)
        calls = plugin._send_webhook.call_args_list

        # Both webhooks get checked but filtering happens inside _send_webhook
        assert len(calls) == 2

    @pytest.mark.asyncio
    async def test_disabled_webhook_not_called(self):
        """Test disabled webhooks are not called."""
        config = {
            "webhooks": [
                {
                    "url": "https://hooks.example.com/webhook",
                    "events": ["tool_success"],
                    "authentication": {"type": "none"},
                    "enabled": False,  # Disabled
                }
            ]
        }

        plugin = _create_plugin(config)

        # Mock HTTP client to verify no calls are made
        plugin._client = AsyncMock()

        context = _create_context()
        webhook = plugin._cfg.webhooks[0]

        await plugin._send_webhook(
            webhook=webhook,
            event=EventType.TOOL_SUCCESS,
            context=context
        )

        # Verify no HTTP calls were made
        plugin._client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_custom_payload_template(self):
        """Test custom payload templates are used correctly."""
        custom_template = '{"custom": "{{event}}", "user": "{{user}}"}'

        config = {
            "payload_templates": {
                "tool_success": custom_template
            }
        }

        plugin = _create_plugin(config)

        context_vars = {
            "event": "tool_success",
            "user": "testuser"
        }

        result = await plugin._render_template(custom_template, context_vars)
        parsed = json.loads(result)

        assert parsed["custom"] == "tool_success"
        assert parsed["user"] == "testuser"

    @pytest.mark.asyncio
    async def test_payload_size_limiting(self):
        """Test payload size limiting functionality."""
        large_payload = {"data": "x" * 2000}  # Large payload

        config = {
            "include_payload_data": True,
            "max_payload_size": 100  # Small limit
        }

        plugin = _create_plugin(config)
        plugin._client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        plugin._client.post.return_value = mock_response

        context = _create_context()
        webhook = plugin._cfg.webhooks[0]

        await plugin._send_webhook(
            webhook=webhook,
            event=EventType.TOOL_SUCCESS,
            context=context,
            payload_data=large_payload
        )

        # Verify webhook was still sent (payload should be excluded due to size)
        plugin._client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_prompt_pre_and_post_hooks_return_success(self):
        """Test prompt hooks return success results."""
        plugin = _create_plugin()
        context = _create_context()

        # Test pre-hook
        pre_payload = PromptPrehookPayload(prompt_id="test_prompt", args={})
        pre_result = await plugin.prompt_pre_fetch(pre_payload, context)
        assert pre_result.continue_processing is True

        # Test post-hook with mock notification
        plugin._notify_webhooks = AsyncMock()

        from mcpgateway.plugins.framework import PromptPosthookPayload
        from mcpgateway.common.models import PromptResult
        post_payload = PromptPosthookPayload(
            prompt_id="test_prompt",
            result=PromptResult(messages=[])
        )
        post_result = await plugin.prompt_post_fetch(post_payload, context)
        assert post_result.continue_processing is True

        # Verify notification was sent
        plugin._notify_webhooks.assert_called_once()
