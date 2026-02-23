# -*- coding: utf-8 -*-
"""Unit tests for IAM Pre-Tool Plugin."""

# Standard
from datetime import datetime, timedelta, timezone

# Third-Party
import pytest

# First-Party
from mcpgateway.plugins.framework import (
    GlobalContext,
    HttpHeaderPayload,
    HttpPreRequestPayload,
    PluginConfig,
    PluginContext,
)
from plugins.iam_pre_tool import IamPreToolPlugin


class TestIamPreToolPlugin:
    """Test suite for IAM pre-tool plugin."""

    def test_plugin_initialization(self):
        """Test plugin initializes with default config."""
        config = PluginConfig(
            id="test-iam",
            kind="iam_pre_tool",
            name="Test IAM Pre-Tool",
            enabled=True,
            order=0,
            config={}
        )
        plugin = IamPreToolPlugin(config)
        
        assert plugin._cfg.enabled is True
        assert plugin._cfg.token_cache_ttl_seconds == 3600
        assert plugin._cfg.inject_bearer_token is True

    def test_plugin_initialization_custom_config(self):
        """Test plugin initializes with custom config."""
        custom_config = {
            "enabled": False,
            "token_cache_ttl_seconds": 7200,
            "oauth2_client_credentials_enabled": True,
        }
        config = PluginConfig(
            id="test-iam",
            kind="iam_pre_tool",
            name="Test IAM Pre-Tool",
            enabled=True,
            order=0,
            config=custom_config
        )
        plugin = IamPreToolPlugin(config)
        
        assert plugin._cfg.enabled is False
        assert plugin._cfg.token_cache_ttl_seconds == 7200
        assert plugin._cfg.oauth2_client_credentials_enabled is True

    @pytest.mark.asyncio
    async def test_http_pre_request_disabled(self):
        """Test plugin passes through when disabled."""
        config = PluginConfig(
            id="test-iam",
            kind="iam_pre_tool",
            name="Test IAM Pre-Tool",
            enabled=True,
            order=0,
            config={"enabled": False}
        )
        plugin = IamPreToolPlugin(config)
        
        headers = HttpHeaderPayload({"content-type": "application/json"})
        payload = HttpPreRequestPayload(
            path="/api/tool",
            method="POST",
            headers=headers
        )
        global_ctx = GlobalContext(request_id="test-req-1")
        context = PluginContext(global_context=global_ctx, state={})
        
        result = await plugin.http_pre_request(payload, context)
        
        assert result.modified_payload == headers
        assert "authorization" not in result.modified_payload

    @pytest.mark.asyncio
    async def test_http_pre_request_no_server_id(self):
        """Test plugin skips injection when no server_id in context."""
        config = PluginConfig(
            id="test-iam",
            kind="iam_pre_tool",
            name="Test IAM Pre-Tool",
            enabled=True,
            order=0,
            config={}
        )
        plugin = IamPreToolPlugin(config)
        
        headers = HttpHeaderPayload({"content-type": "application/json"})
        payload = HttpPreRequestPayload(
            path="/api/tool",
            method="POST",
            headers=headers
        )
        global_ctx = GlobalContext(request_id="test-req-2")
        context = PluginContext(global_context=global_ctx, state={})
        
        result = await plugin.http_pre_request(payload, context)
        
        assert "authorization" not in result.modified_payload

    @pytest.mark.asyncio
    async def test_http_pre_request_no_credentials_configured(self):
        """Test plugin skips injection when no credentials for server."""
        config = PluginConfig(
            id="test-iam",
            kind="iam_pre_tool",
            name="Test IAM Pre-Tool",
            enabled=True,
            order=0,
            config={}
        )
        plugin = IamPreToolPlugin(config)
        
        headers = HttpHeaderPayload({"content-type": "application/json"})
        payload = HttpPreRequestPayload(
            path="/api/tool",
            method="POST",
            headers=headers
        )
        global_ctx = GlobalContext(request_id="test-req-3")
        context = PluginContext(global_context=global_ctx, state={"server_id": "server-1"})
        
        result = await plugin.http_pre_request(payload, context)
        
        assert "authorization" not in result.modified_payload

    @pytest.mark.asyncio
    async def test_token_cache_entry_expiration(self):
        """Test token cache entry expiration logic."""
        from plugins.iam_pre_tool.iam_pre_tool import TokenCacheEntry
        
        # Not expired
        future = datetime.now(timezone.utc) + timedelta(seconds=120)
        entry = TokenCacheEntry(
            access_token="test-token",
            expires_at=future,
        )
        assert not entry.is_expired()
        
        # Expired
        past = datetime.now(timezone.utc) - timedelta(seconds=1)
        entry = TokenCacheEntry(
            access_token="test-token",
            expires_at=past,
        )
        assert entry.is_expired()
        
        # About to expire (within 60s buffer)
        soon = datetime.now(timezone.utc) + timedelta(seconds=30)
        entry = TokenCacheEntry(
            access_token="test-token",
            expires_at=soon,
        )
        assert entry.is_expired()
