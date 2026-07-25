# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/plugins/vault/test_vault_plugin.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for Vault Plugin functionality.
"""

# Standard
import json

# Third-Party
import pytest

# First-Party
from cpex.framework import (
    GlobalContext,
    PluginConfig,
    PluginContext,
    PluginMode,
    ToolHookType,
    ToolPreInvokePayload,
)
from cpex.framework.extensions import Extensions, HttpExtension

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
            mode=PluginMode.SEQUENTIAL,
            priority=10,
            capabilities=["write_headers"],
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
        payload = ToolPreInvokePayload(name="test_tool", args={})
        ext = Extensions(http=HttpExtension(headers={"Content-Type": "application/json"}))

        result = await plugin.tool_pre_invoke(payload, plugin_context, ext)

        assert result.modified_extensions is None
        assert result.continue_processing

    @pytest.mark.asyncio
    async def test_vault_token_added_to_authorization_header(self, plugin_config, plugin_context):
        """Test that vault token is added as Bearer token."""
        plugin = Vault(plugin_config)

        # Create vault tokens
        vault_tokens = {"github.com": "ghp_test123456789"}

        # Create payload with vault header (lowercase per ASGI spec)
        payload = ToolPreInvokePayload(name="test_tool", args={})
        ext = Extensions(http=HttpExtension(headers={"content-type": "application/json", "x-vault-tokens": json.dumps(vault_tokens)}))

        result = await plugin.tool_pre_invoke(payload, plugin_context, ext)

        assert result.modified_extensions is not None
        assert result.modified_extensions.http is not None
        hdrs = result.modified_extensions.http.headers
        assert "authorization" in hdrs
        assert hdrs["authorization"] == "Bearer ghp_test123456789"
        assert "x-vault-tokens" not in hdrs

    @pytest.mark.asyncio
    async def test_pat_token_uses_custom_header(self, plugin_config, plugin_context):
        """Test that PAT token uses custom header from AUTH_HEADER tag."""
        plugin = Vault(plugin_config)

        # Create vault tokens with PAT type
        vault_tokens = {"github.com:USER:PAT:TOKEN": "ghp_pat_token123"}

        # Create payload with vault header (lowercase per ASGI spec)
        payload = ToolPreInvokePayload(name="test_tool", args={})
        ext = Extensions(http=HttpExtension(headers={"content-type": "application/json", "x-vault-tokens": json.dumps(vault_tokens)}))

        result = await plugin.tool_pre_invoke(payload, plugin_context, ext)

        assert result.modified_extensions is not None
        assert result.modified_extensions.http is not None
        hdrs = result.modified_extensions.http.headers
        assert "x-github-token" in hdrs
        assert hdrs["x-github-token"] == "ghp_pat_token123"
        assert "x-vault-tokens" not in hdrs

    @pytest.mark.asyncio
    async def test_invalid_json_in_vault_header(self, plugin_config, plugin_context):
        """Test that invalid JSON in vault header is handled gracefully and header is removed."""
        plugin = Vault(plugin_config)

        # Create payload with invalid JSON (lowercase per ASGI spec)
        payload = ToolPreInvokePayload(name="test_tool", args={})
        ext = Extensions(http=HttpExtension(headers={"content-type": "application/json", "x-vault-tokens": "invalid json"}))

        result = await plugin.tool_pre_invoke(payload, plugin_context, ext)

        # SECURITY: Vault header must be removed even on parse error
        assert result.modified_extensions is not None
        assert result.modified_extensions.http is not None
        hdrs = result.modified_extensions.http.headers
        assert "x-vault-tokens" not in hdrs
        assert result.continue_processing

    @pytest.mark.asyncio
    async def test_no_system_tag_strips_vault_header(self, plugin_config):
        """Test that missing system tag strips vault header and returns modified payload."""
        plugin = Vault(plugin_config)

        # Create context without system tag
        gateway_metadata = type("obj", (object,), {"tags": [{"id": "1", "label": "other:tag"}]})()

        global_context = GlobalContext(request_id="test-2", metadata={"gateway": gateway_metadata})

        context = PluginContext(global_context=global_context)

        vault_tokens = {"github.com": "token123"}

        payload = ToolPreInvokePayload(name="test_tool", args={})
        ext = Extensions(http=HttpExtension(headers={"x-vault-tokens": json.dumps(vault_tokens)}))

        result = await plugin.tool_pre_invoke(payload, context, ext)

        # SECURITY: Vault header must be removed even when system tag is missing
        assert result.modified_extensions is not None
        assert result.modified_extensions.http is not None
        hdrs = result.modified_extensions.http.headers
        assert "x-vault-tokens" not in hdrs
        assert result.continue_processing

    @pytest.mark.asyncio
    async def test_no_system_tag_no_vault_header_returns_empty(self, plugin_config):
        """Test that missing system tag without vault header returns empty result."""
        plugin = Vault(plugin_config)

        gateway_metadata = type("obj", (object,), {"tags": [{"id": "1", "label": "other:tag"}]})()
        global_context = GlobalContext(request_id="test-3", metadata={"gateway": gateway_metadata})
        context = PluginContext(global_context=global_context)

        payload = ToolPreInvokePayload(name="test_tool", args={})
        ext = Extensions(http=HttpExtension(headers={"Content-Type": "application/json"}))

        result = await plugin.tool_pre_invoke(payload, context, ext)

        assert result.modified_extensions is None
        assert result.continue_processing

    @pytest.mark.asyncio
    async def test_non_dict_json_vault_tokens_stripped(self, plugin_config, plugin_context):
        """Test that non-dict JSON in vault header (e.g. array) strips header without injecting auth."""
        plugin = Vault(plugin_config)

        # JSON array is valid JSON but not a dict — must not be treated as tokens (lowercase per ASGI spec)
        payload = ToolPreInvokePayload(name="test_tool", args={})
        ext = Extensions(http=HttpExtension(headers={"content-type": "application/json", "x-vault-tokens": '["not", "a", "dict"]'}))

        result = await plugin.tool_pre_invoke(payload, plugin_context, ext)

        # SECURITY: Vault header must be removed
        assert result.modified_extensions is not None
        assert result.modified_extensions.http is not None
        hdrs = result.modified_extensions.http.headers
        assert "x-vault-tokens" not in hdrs
        # No Authorization header should be injected
        assert "authorization" not in hdrs
        assert result.continue_processing

    @pytest.mark.asyncio
    async def test_complex_token_key_parsing(self, plugin_config, plugin_context):
        """Test that complex token keys are parsed correctly."""
        plugin = Vault(plugin_config)

        # Create vault tokens with complex key
        vault_tokens = {"github.com:USER:OAUTH2:ACCESS_TOKEN": "oauth_token_123"}

        payload = ToolPreInvokePayload(name="test_tool", args={})
        ext = Extensions(http=HttpExtension(headers={"x-vault-tokens": json.dumps(vault_tokens)}))

        result = await plugin.tool_pre_invoke(payload, plugin_context, ext)

        assert result.modified_extensions is not None
        assert result.modified_extensions.http is not None
        hdrs = result.modified_extensions.http.headers
        assert "authorization" in hdrs
        assert hdrs["authorization"] == "Bearer oauth_token_123"

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

        # Create payload with existing Authorization header (lowercase per ASGI spec)
        payload = ToolPreInvokePayload(name="test_tool", args={})
        ext = Extensions(
            http=HttpExtension(
                headers={
                    "content-type": "application/json",
                    "authorization": "Bearer old_default_token",
                    "x-vault-tokens": json.dumps(vault_tokens),
                }
            )
        )

        result = await plugin.tool_pre_invoke(payload, plugin_context, ext)

        # Verify the old token was replaced with the new one from vault
        assert result.modified_extensions is not None
        assert result.modified_extensions.http is not None
        hdrs = result.modified_extensions.http.headers
        assert "authorization" in hdrs
        assert hdrs["authorization"] == "Bearer ghp_new_token_from_vault"
        assert hdrs["authorization"] != "Bearer old_default_token"
        assert "x-vault-tokens" not in hdrs

    @pytest.mark.asyncio
    async def test_existing_custom_header_is_replaced_with_pat(self, plugin_config, plugin_context):
        """Test that existing custom header is replaced when PAT token is provided."""
        plugin = Vault(plugin_config)

        # Create vault tokens with PAT type
        vault_tokens = {"github.com:USER:PAT:TOKEN": "ghp_new_pat_token"}

        # Create payload with existing custom header (lowercase per ASGI spec)
        payload = ToolPreInvokePayload(name="test_tool", args={})
        ext = Extensions(
            http=HttpExtension(
                headers={
                    "content-type": "application/json",
                    "x-github-token": "old_github_token",
                    "x-vault-tokens": json.dumps(vault_tokens),
                }
            )
        )

        result = await plugin.tool_pre_invoke(payload, plugin_context, ext)

        # Verify the old custom header was replaced with the new PAT token
        assert result.modified_extensions is not None
        assert result.modified_extensions.http is not None
        hdrs = result.modified_extensions.http.headers
        assert "x-github-token" in hdrs
        assert hdrs["x-github-token"] == "ghp_new_pat_token"
        assert hdrs["x-github-token"] != "old_github_token"
        assert "x-vault-tokens" not in hdrs

    @pytest.mark.asyncio
    async def test_vault_header_removed_when_no_token_match(self, plugin_config, plugin_context):
        """Test that vault header is removed even when no token matches the system."""
        plugin = Vault(plugin_config)

        # Create vault tokens for a different system
        vault_tokens = {"gitlab.com": "glpat_different_system_token"}

        # Create payload with vault header but no matching system (lowercase per ASGI spec)
        payload = ToolPreInvokePayload(name="test_tool", args={})
        ext = Extensions(http=HttpExtension(headers={"content-type": "application/json", "x-vault-tokens": json.dumps(vault_tokens)}))

        result = await plugin.tool_pre_invoke(payload, plugin_context, ext)

        # SECURITY: Vault header must be removed even when no token match is found
        assert result.modified_extensions is not None
        assert result.modified_extensions.http is not None
        hdrs = result.modified_extensions.http.headers
        assert "x-vault-tokens" not in hdrs
        # No Authorization header should be added since there's no match
        assert "authorization" not in hdrs
        assert result.continue_processing

    @pytest.mark.asyncio
    async def test_case_insensitive_vault_header_detection(self, plugin_config, plugin_context):
        """Test that vault header is detected case-insensitively (RFC 7230)."""
        plugin = Vault(plugin_config)

        # Create vault tokens
        vault_tokens = {"github.com": "ghp_test_case_insensitive"}

        # Test with different case variations
        test_cases = [
            "X-Vault-Tokens",  # Original case
            "x-vault-tokens",  # All lowercase
            "X-VAULT-TOKENS",  # All uppercase
            "x-Vault-Tokens",  # Mixed case
        ]

        for header_name in test_cases:
            payload = ToolPreInvokePayload(name="test_tool", args={})
            ext = Extensions(http=HttpExtension(headers={"Content-Type": "application/json", header_name: json.dumps(vault_tokens)}))

            result = await plugin.tool_pre_invoke(payload, plugin_context, ext)

            # Should work regardless of case
            assert result.modified_extensions is not None, f"Failed for header case: {header_name}"
            assert result.modified_extensions.http is not None
            hdrs = result.modified_extensions.http.headers
            assert "authorization" in hdrs, f"Authorization not found for case: {header_name}"
            assert hdrs["authorization"] == "Bearer ghp_test_case_insensitive"
            # Vault header should be removed (check all possible cases)
            for key in hdrs.keys():
                assert key.lower() != "x-vault-tokens", f"Vault header not removed for case: {header_name}"

    @pytest.mark.asyncio
    async def test_copyonwritedict_root_attribute_access(self, plugin_config, plugin_context):
        """Test that plugin correctly processes headers via extensions.http.headers.

        This test validates header access through the extensions path (replacing the
        former CopyOnWriteDict.model_dump() / .root pattern on payload.headers).
        """
        plugin = Vault(plugin_config)

        # Create vault tokens
        vault_tokens = {"github.com": "ghp_root_access_test"}

        # Create payload with vault header
        payload = ToolPreInvokePayload(name="test_tool", args={})
        headers_in = {"Content-Type": "application/json", "X-Vault-Tokens": json.dumps(vault_tokens), "X-Custom-Header": "custom_value"}
        ext = Extensions(http=HttpExtension(headers=headers_in))

        # Verify extensions contain actual headers (the correct access pattern)
        assert len(ext.http.headers) == 3, "extensions.http.headers should contain all headers"
        assert "X-Vault-Tokens" in ext.http.headers
        assert "X-Custom-Header" in ext.http.headers
        assert "Content-Type" in ext.http.headers

        # Plugin should work correctly by using extensions.http.headers
        result = await plugin.tool_pre_invoke(payload, plugin_context, ext)

        # Verify plugin processed the headers correctly
        assert result.modified_extensions is not None
        assert result.modified_extensions.http is not None
        hdrs = result.modified_extensions.http.headers
        assert "authorization" in hdrs
        assert hdrs["authorization"] == "Bearer ghp_root_access_test"
        assert "x-vault-tokens" not in hdrs
        # Custom header should be preserved (normalized to lowercase)
        assert "x-custom-header" in hdrs
        assert hdrs["x-custom-header"] == "custom_value"

    @pytest.mark.asyncio
    async def test_case_insensitive_header_with_config_variations(self, plugin_context):
        """Test that vault header detection works with all case combinations of header and config.

        This validates that the plugin correctly handles:
        - Config specifies "X-Vault-Tokens" but request has "x-vault-tokens"
        - Config specifies "x-vault-tokens" but request has "X-Vault-Tokens"
        - Any other case combination
        """
        vault_tokens = {"github.com": "ghp_case_test"}

        # Test matrix: (config_header_name, request_header_name)
        test_cases = [
            ("X-Vault-Tokens", "X-Vault-Tokens"),  # Both standard case
            ("X-Vault-Tokens", "x-vault-tokens"),  # Config upper, request lower
            ("X-Vault-Tokens", "X-VAULT-TOKENS"),  # Config mixed, request upper
            ("x-vault-tokens", "X-Vault-Tokens"),  # Config lower, request mixed
            ("x-vault-tokens", "x-vault-tokens"),  # Both lower
            ("X-VAULT-TOKENS", "x-vault-tokens"),  # Config upper, request lower
            ("X-VAULT-TOKENS", "X-Vault-Tokens"),  # Config upper, request mixed
        ]

        for config_header, request_header in test_cases:
            # Create plugin config with specific header name case
            plugin_config = PluginConfig(
                name="TestVault",
                description="Test Vault Plugin",
                author="Test",
                kind="plugins.vault.vault_plugin.Vault",
                version="1.0",
                hooks=[ToolHookType.TOOL_PRE_INVOKE],
                tags=["test", "vault"],
                mode=PluginMode.SEQUENTIAL,
                priority=10,
                capabilities=["write_headers"],
                config={
                    "system_tag_prefix": "system",
                    "vault_header_name": config_header,  # Variable case
                    "vault_handling": "raw",
                    "system_handling": "tag",
                    "auth_header_tag_prefix": "AUTH_HEADER",
                },
            )

            plugin = Vault(plugin_config)

            # Create payload with specific request header case
            payload = ToolPreInvokePayload(name="test_tool", args={})
            ext = Extensions(http=HttpExtension(headers={"Content-Type": "application/json", request_header: json.dumps(vault_tokens)}))

            result = await plugin.tool_pre_invoke(payload, plugin_context, ext)

            # Should work regardless of case combination
            assert result.modified_extensions is not None, f"Failed for config='{config_header}', request='{request_header}'"
            assert result.modified_extensions.http is not None
            hdrs = result.modified_extensions.http.headers
            assert "authorization" in hdrs, f"Authorization not found for config='{config_header}', request='{request_header}'"
            assert hdrs["authorization"] == "Bearer ghp_case_test"

            # Vault header should be removed (check all possible cases)
            for key in hdrs.keys():
                assert key.lower() != config_header.lower(), f"Vault header not removed for config='{config_header}', request='{request_header}'"

    @pytest.mark.asyncio
    async def test_vault_header_lowercase_headers(self, plugin_config, plugin_context):
        """Test that vault header lookup is case-insensitive (production ASGI flow).

        Real production flow: ASGI middleware lowercases all headers, but config may use PascalCase.
        Config: vault_header_name: "X-Vault-Tokens" (PascalCase)
        Payload: {"x-vault-tokens": "..."} (lowercase, as from ASGI middleware)
        Expected: Token found and processed correctly
        """
        plugin = Vault(plugin_config)

        # Create vault tokens
        vault_tokens = {"github.com": "ghp_production_token_456"}

        # Create payload with LOWERCASE vault header (as ASGI middleware provides)
        payload = ToolPreInvokePayload(name="test_tool", args={})
        ext = Extensions(http=HttpExtension(headers={"content-type": "application/json", "x-vault-tokens": json.dumps(vault_tokens)}))

        result = await plugin.tool_pre_invoke(payload, plugin_context, ext)

        # Token should be found and processed despite case mismatch
        assert result.modified_extensions is not None
        assert result.modified_extensions.http is not None
        hdrs = result.modified_extensions.http.headers
        assert "authorization" in hdrs
        assert hdrs["authorization"] == "Bearer ghp_production_token_456"
        assert "x-vault-tokens" not in hdrs

    @pytest.mark.asyncio
    async def test_vault_header_lowercase_config(self, plugin_context):
        """Test that lowercase config works with lowercase headers (bidirectional normalization).

        Config: vault_header_name: "x-vault-tokens" (lowercase)
        Payload: {"x-vault-tokens": "..."} (lowercase)
        Expected: Token found and processed correctly
        """
        # Create plugin config with lowercase vault_header_name
        lowercase_config = PluginConfig(
            name="TestVault",
            description="Test Vault Plugin",
            author="Test",
            kind="plugins.vault.vault_plugin.Vault",
            version="1.0",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            tags=["test", "vault"],
            mode=PluginMode.SEQUENTIAL,
            priority=10,
            capabilities=["write_headers"],
            config={
                "system_tag_prefix": "system",
                "vault_header_name": "x-vault-tokens",  # lowercase config
                "vault_handling": "raw",
                "system_handling": "tag",
                "auth_header_tag_prefix": "AUTH_HEADER",
            },
        )

        plugin = Vault(lowercase_config)

        # Create vault tokens
        vault_tokens = {"github.com": "ghp_lowercase_config_token"}

        # Create payload with lowercase vault header
        payload = ToolPreInvokePayload(name="test_tool", args={})
        ext = Extensions(http=HttpExtension(headers={"x-vault-tokens": json.dumps(vault_tokens)}))

        result = await plugin.tool_pre_invoke(payload, plugin_context, ext)

        # Token should be found and processed
        assert result.modified_extensions is not None
        assert result.modified_extensions.http is not None
        hdrs = result.modified_extensions.http.headers
        assert "authorization" in hdrs
        assert hdrs["authorization"] == "Bearer ghp_lowercase_config_token"
        assert "x-vault-tokens" not in hdrs

    @pytest.mark.asyncio
    async def test_pat_token_custom_header_lowercase(self, plugin_config, plugin_context):
        """Test that PAT token writes custom headers in lowercase (AUTH_HEADER tag normalization).

        Gateway tag: AUTH_HEADER:X-GitHub-Token (PascalCase)
        Token type: PAT
        Expected: Header written as "x-github-token" (lowercase) for ASGI compliance
        """
        plugin = Vault(plugin_config)

        # Create vault tokens with PAT type
        vault_tokens = {"github.com:USER:PAT:TOKEN": "ghp_pat_lowercase_header"}

        # Create payload with lowercase headers (production ASGI flow)
        payload = ToolPreInvokePayload(name="test_tool", args={})
        ext = Extensions(http=HttpExtension(headers={"content-type": "application/json", "x-vault-tokens": json.dumps(vault_tokens)}))

        result = await plugin.tool_pre_invoke(payload, plugin_context, ext)

        # PAT token should be written with lowercase header name
        assert result.modified_extensions is not None
        assert result.modified_extensions.http is not None
        hdrs = result.modified_extensions.http.headers
        assert "x-github-token" in hdrs
        assert hdrs["x-github-token"] == "ghp_pat_lowercase_header"
        assert "x-vault-tokens" not in hdrs


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
