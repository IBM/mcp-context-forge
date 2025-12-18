# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/plugins/vault/test_vault_plugin.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Adrian Popa

Unit tests for Vault Plugin functionality.
"""

# Standard
import json

# Third-Party
import pytest

# First-Party
from mcpgateway.plugins.framework import (
    GlobalContext,
    HttpHeaderPayload,
    PluginConfig,
    PluginContext,
    PluginMode,
    ToolHookType,
    ToolPreInvokePayload,
)

# Import the Vault plugin
from plugins.vault.vault_plugin import Vault


class TestVaultPluginFunctionality:
    """Unit tests for Vault plugin functionality."""

    @pytest.fixture
    def plugin_config(self) -> PluginConfig:
        """Create a test plugin configuration."""
        return PluginConfig(
            name="TestVault",
            description="Test Vault Plugin",
            author="Test",
            kind="plugins.vault.vault_plugin.Vault",
            version="1.0",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            tags=["test", "vault"],
            mode=PluginMode.ENFORCE,
            priority=10,
            config={
                "system_tag_prefix": "system",
                "vault_header_name": "X-Vault-Tokens",
                "vault_handling": "raw",
                "system_handling": "tag",
                "auth_header_tag_prefix": "AUTH_HEADER",
            },
        )

    @pytest.fixture
    def plugin_context(self) -> PluginContext:
        """Create a test plugin context with gateway metadata."""
        gateway_metadata = type("obj", (object,), {"tags": [{"id": "1", "label": "system:github.com"}, {"id": "2", "label": "AUTH_HEADER:X-GitHub-Token"}]})()

        global_context = GlobalContext(request_id="test-1", metadata={"gateway": gateway_metadata})

        return PluginContext(global_context=global_context)

    @pytest.mark.asyncio
    async def test_no_vault_header_returns_empty_result(self, plugin_config, plugin_context):
        """Test that missing vault header returns empty result."""
        plugin = Vault(plugin_config)

        # Create payload without vault header
        payload = ToolPreInvokePayload(name="test_tool", arguments={}, headers=HttpHeaderPayload(root={"Content-Type": "application/json"}))

        result = await plugin.tool_pre_invoke(payload, plugin_context)

        assert result.modified_payload is None
        assert result.continue_processing

    @pytest.mark.asyncio
    async def test_vault_token_added_to_authorization_header(self, plugin_config, plugin_context):
        """Test that vault token is added as Bearer token."""
        plugin = Vault(plugin_config)

        # Create vault tokens
        vault_tokens = {"github.com": "ghp_test123456789"}

        # Create payload with vault header
        payload = ToolPreInvokePayload(name="test_tool", arguments={}, headers=HttpHeaderPayload(root={"Content-Type": "application/json", "X-Vault-Tokens": json.dumps(vault_tokens)}))

        result = await plugin.tool_pre_invoke(payload, plugin_context)

        assert result.modified_payload is not None
        assert "Authorization" in result.modified_payload.headers.root
        assert result.modified_payload.headers.root["Authorization"] == "Bearer ghp_test123456789"
        assert "X-Vault-Tokens" not in result.modified_payload.headers.root

    @pytest.mark.asyncio
    async def test_pat_token_uses_custom_header(self, plugin_config, plugin_context):
        """Test that PAT token uses custom header from AUTH_HEADER tag."""
        plugin = Vault(plugin_config)

        # Create vault tokens with PAT type
        vault_tokens = {"github.com:USER:PAT:TOKEN": "ghp_pat_token123"}

        # Create payload with vault header
        payload = ToolPreInvokePayload(name="test_tool", arguments={}, headers=HttpHeaderPayload(root={"Content-Type": "application/json", "X-Vault-Tokens": json.dumps(vault_tokens)}))

        result = await plugin.tool_pre_invoke(payload, plugin_context)

        assert result.modified_payload is not None
        assert "X-GitHub-Token" in result.modified_payload.headers.root
        assert result.modified_payload.headers.root["X-GitHub-Token"] == "ghp_pat_token123"
        assert "X-Vault-Tokens" not in result.modified_payload.headers.root

    @pytest.mark.asyncio
    async def test_invalid_json_in_vault_header(self, plugin_config, plugin_context):
        """Test that invalid JSON in vault header is handled gracefully."""
        plugin = Vault(plugin_config)

        # Create payload with invalid JSON
        payload = ToolPreInvokePayload(name="test_tool", arguments={}, headers=HttpHeaderPayload(root={"Content-Type": "application/json", "X-Vault-Tokens": "invalid json"}))

        result = await plugin.tool_pre_invoke(payload, plugin_context)

        assert result.modified_payload is None
        assert result.continue_processing

    @pytest.mark.asyncio
    async def test_no_system_tag_returns_empty_result(self, plugin_config):
        """Test that missing system tag returns empty result."""
        plugin = Vault(plugin_config)

        # Create context without system tag
        gateway_metadata = type("obj", (object,), {"tags": [{"id": "1", "label": "other:tag"}]})()

        global_context = GlobalContext(request_id="test-2", metadata={"gateway": gateway_metadata})

        context = PluginContext(global_context=global_context)

        vault_tokens = {"github.com": "token123"}

        payload = ToolPreInvokePayload(name="test_tool", arguments={}, headers=HttpHeaderPayload(root={"X-Vault-Tokens": json.dumps(vault_tokens)}))

        result = await plugin.tool_pre_invoke(payload, context)

        assert result.modified_payload is None

    @pytest.mark.asyncio
    async def test_complex_token_key_parsing(self, plugin_config, plugin_context):
        """Test that complex token keys are parsed correctly."""
        plugin = Vault(plugin_config)

        # Create vault tokens with complex key
        vault_tokens = {"github.com:USER:OAUTH2:ACCESS_TOKEN": "oauth_token_123"}

        payload = ToolPreInvokePayload(name="test_tool", arguments={}, headers=HttpHeaderPayload(root={"X-Vault-Tokens": json.dumps(vault_tokens)}))

        result = await plugin.tool_pre_invoke(payload, plugin_context)

        assert result.modified_payload is not None
        assert "Authorization" in result.modified_payload.headers.root
        assert result.modified_payload.headers.root["Authorization"] == "Bearer oauth_token_123"

    def test_parse_vault_token_key(self, plugin_config):
        """Test the _parse_vault_token_key method."""
        plugin = Vault(plugin_config)

        # Test simple key
        system, scope, token_type, token_name = plugin._parse_vault_token_key("github.com")
        assert system == "github.com"
        assert scope is None
        assert token_type is None
        assert token_name is None

        # Test complex key
        system, scope, token_type, token_name = plugin._parse_vault_token_key("github.com:USER:PAT:TOKEN")
        assert system == "github.com"
        assert scope == "USER"
        assert token_type == "PAT"
        assert token_name == "TOKEN"

    @pytest.mark.asyncio
    async def test_existing_bearer_token_is_replaced(self, plugin_config, plugin_context):
        """Test that existing Authorization header is replaced with vault token."""
        plugin = Vault(plugin_config)

        # Create vault tokens
        vault_tokens = {"github.com": "ghp_new_token_from_vault"}

        # Create payload with existing Authorization header
        payload = ToolPreInvokePayload(
            name="test_tool",
            arguments={},
            headers=HttpHeaderPayload(root={"Content-Type": "application/json", "Authorization": "Bearer old_default_token", "X-Vault-Tokens": json.dumps(vault_tokens)}),
        )

        result = await plugin.tool_pre_invoke(payload, plugin_context)

        # Verify the old token was replaced with the new one from vault
        assert result.modified_payload is not None
        assert "Authorization" in result.modified_payload.headers.root
        assert result.modified_payload.headers.root["Authorization"] == "Bearer ghp_new_token_from_vault"
        assert result.modified_payload.headers.root["Authorization"] != "Bearer old_default_token"
        assert "X-Vault-Tokens" not in result.modified_payload.headers.root

    @pytest.mark.asyncio
    async def test_existing_custom_header_is_replaced_with_pat(self, plugin_config, plugin_context):
        """Test that existing custom header is replaced when PAT token is provided."""
        plugin = Vault(plugin_config)

        # Create vault tokens with PAT type
        vault_tokens = {"github.com:USER:PAT:TOKEN": "ghp_new_pat_token"}

        # Create payload with existing custom header
        payload = ToolPreInvokePayload(
            name="test_tool", arguments={}, headers=HttpHeaderPayload(root={"Content-Type": "application/json", "X-GitHub-Token": "old_github_token", "X-Vault-Tokens": json.dumps(vault_tokens)})
        )

        result = await plugin.tool_pre_invoke(payload, plugin_context)

        # Verify the old custom header was replaced with the new PAT token
        assert result.modified_payload is not None
        assert "X-GitHub-Token" in result.modified_payload.headers.root
        assert result.modified_payload.headers.root["X-GitHub-Token"] == "ghp_new_pat_token"
        assert result.modified_payload.headers.root["X-GitHub-Token"] != "old_github_token"
        assert "X-Vault-Tokens" not in result.modified_payload.headers.root


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
