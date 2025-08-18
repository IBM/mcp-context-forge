# -*- coding: utf-8 -*-
"""Tests for the ResourceFilterPlugin."""

import pytest

from mcpgateway.models import ResourceContent
from mcpgateway.plugins.framework.models import (
    HookType,
    PluginConfig,
    PluginContext,
    PluginMode,
    ResourcePostFetchPayload,
    ResourcePreFetchPayload,
)
from plugins.resource_filter.resource_filter import ResourceFilterPlugin


class TestResourceFilterPlugin:
    """Test the ResourceFilterPlugin implementation."""

    @pytest.fixture
    def plugin_config(self):
        """Create a test plugin configuration."""
        return PluginConfig(
            name="test_resource_filter",
            description="Test resource filter",
            author="test",
            kind="plugins.resource_filter.resource_filter.ResourceFilterPlugin",
            version="1.0.0",
            hooks=[HookType.RESOURCE_PRE_FETCH, HookType.RESOURCE_POST_FETCH],
            tags=["test", "filter"],
            mode=PluginMode.ENFORCE,
            config={
                "max_content_size": 1024,
                "allowed_protocols": ["http", "https", "test"],
                "blocked_domains": ["evil.com", "malicious.example.com"],
                "content_filters": [
                    {"pattern": r"password:\s*\S+", "replacement": "password: [REDACTED]"},
                    {"pattern": r"api[_-]?key:\s*\S+", "replacement": "api_key: [REDACTED]"},
                    {"pattern": r"secret:\s*\S+", "replacement": "secret: [REDACTED]"},
                ],
            },
        )

    @pytest.fixture
    def plugin(self, plugin_config):
        """Create a ResourceFilterPlugin instance."""
        return ResourceFilterPlugin(plugin_config)

    @pytest.fixture
    def context(self):
        """Create a plugin context."""
        return PluginContext(request_id="test-123", user="testuser")

    @pytest.mark.asyncio
    async def test_allowed_protocol(self, plugin, context):
        """Test that allowed protocols pass through."""
        payload = ResourcePreFetchPayload(uri="https://example.com/data", metadata={})
        result = await plugin.resource_pre_fetch(payload, context)

        assert result.continue_processing is True
        assert result.violation is None
        assert result.modified_payload is not None
        assert result.modified_payload.metadata["validated"] is True

    @pytest.mark.asyncio
    async def test_blocked_protocol(self, plugin, context):
        """Test that blocked protocols are rejected."""
        payload = ResourcePreFetchPayload(uri="file:///etc/passwd", metadata={})
        result = await plugin.resource_pre_fetch(payload, context)

        assert result.continue_processing is False
        assert result.violation is not None
        assert result.violation.code == "PROTOCOL_BLOCKED"
        assert "Protocol not allowed" in result.violation.reason

    @pytest.mark.asyncio
    async def test_blocked_domain(self, plugin, context):
        """Test that blocked domains are rejected."""
        payload = ResourcePreFetchPayload(uri="https://evil.com/malware", metadata={})
        result = await plugin.resource_pre_fetch(payload, context)

        assert result.continue_processing is False
        assert result.violation is not None
        assert result.violation.code == "DOMAIN_BLOCKED"
        assert "Domain is blocked" in result.violation.reason

    @pytest.mark.asyncio
    async def test_content_filtering(self, plugin, context):
        """Test that sensitive content is filtered."""
        # Set validation state
        context.set_state("uri_validated", True)

        content = ResourceContent(
            type="resource",
            uri="test://config",
            text="Database config:\npassword: mysecret123\napi_key: sk-12345\nport: 5432",
        )
        payload = ResourcePostFetchPayload(uri="test://config", content=content)

        result = await plugin.resource_post_fetch(payload, context)

        assert result.continue_processing is True
        assert result.modified_payload is not None
        modified_text = result.modified_payload.content.text
        assert "password: [REDACTED]" in modified_text
        assert "api_key: [REDACTED]" in modified_text
        assert "mysecret123" not in modified_text
        assert "sk-12345" not in modified_text
        assert "port: 5432" in modified_text  # Non-sensitive data preserved

    @pytest.mark.asyncio
    async def test_content_size_limit(self, plugin, context):
        """Test that content exceeding size limit is blocked."""
        # Set validation state
        context.set_state("uri_validated", True)

        large_content = ResourceContent(
            type="resource",
            uri="test://large",
            text="x" * 2000,  # Exceeds 1024 byte limit
        )
        payload = ResourcePostFetchPayload(uri="test://large", content=large_content)

        result = await plugin.resource_post_fetch(payload, context)

        assert result.continue_processing is False
        assert result.violation is not None
        assert result.violation.code == "CONTENT_TOO_LARGE"
        assert "exceeds maximum size" in result.violation.reason

    @pytest.mark.asyncio
    async def test_binary_content_handling(self, plugin, context):
        """Test handling of binary content."""
        # Set validation state
        context.set_state("uri_validated", True)

        binary_content = ResourceContent(
            type="resource",
            uri="test://binary",
            blob=b"\x00\x01\x02\x03",  # Binary data
        )
        payload = ResourcePostFetchPayload(uri="test://binary", content=binary_content)

        result = await plugin.resource_post_fetch(payload, context)

        # Binary content should pass through without text filtering
        assert result.continue_processing is True

    @pytest.mark.asyncio
    async def test_metadata_enrichment(self, plugin, context):
        """Test that metadata is enriched in pre-fetch."""
        payload = ResourcePreFetchPayload(uri="https://example.com/data", metadata={})
        result = await plugin.resource_pre_fetch(payload, context)

        assert result.modified_payload is not None
        metadata = result.modified_payload.metadata
        assert metadata["validated"] is True
        assert metadata["protocol"] == "https"
        assert metadata["request_id"] == "test-123"
        assert metadata["user"] == "testuser"

    @pytest.mark.asyncio
    async def test_permissive_mode(self, plugin_config, context):
        """Test plugin behavior in permissive mode."""
        plugin_config.mode = PluginMode.PERMISSIVE
        plugin = ResourceFilterPlugin(plugin_config)

        # Blocked protocol should log but not block
        payload = ResourcePreFetchPayload(uri="file:///etc/passwd", metadata={})
        result = await plugin.resource_pre_fetch(payload, context)

        # In permissive mode, should continue with violation logged
        assert result.continue_processing is True
        assert result.violation is not None  # Violation still recorded
        assert result.violation.code == "PROTOCOL_BLOCKED"

    @pytest.mark.asyncio
    async def test_multiple_content_filters(self, plugin, context):
        """Test multiple content filters applied correctly."""
        context.set_state("uri_validated", True)

        content = ResourceContent(
            type="resource",
            uri="test://config",
            text=(
                "Config file:\n"
                "password: pass123\n"
                "api-key: key456\n"
                "api_key: key789\n"
                "secret: sec000\n"
                "username: admin"
            ),
        )
        payload = ResourcePostFetchPayload(uri="test://config", content=content)

        result = await plugin.resource_post_fetch(payload, context)

        assert result.continue_processing is True
        modified_text = result.modified_payload.content.text
        assert "password: [REDACTED]" in modified_text
        assert "api_key: [REDACTED]" in modified_text
        assert "secret: [REDACTED]" in modified_text
        assert "username: admin" in modified_text
        assert "pass123" not in modified_text
        assert "key456" not in modified_text
        assert "key789" not in modified_text
        assert "sec000" not in modified_text

    @pytest.mark.asyncio
    async def test_case_insensitive_domain_blocking(self, plugin, context):
        """Test that domain blocking is case-insensitive."""
        payloads = [
            ResourcePreFetchPayload(uri="https://EVIL.COM/data", metadata={}),
            ResourcePreFetchPayload(uri="https://Evil.Com/data", metadata={}),
            ResourcePreFetchPayload(uri="https://evil.com/data", metadata={}),
        ]

        for payload in payloads:
            result = await plugin.resource_pre_fetch(payload, context)
            assert result.continue_processing is False
            assert result.violation.code == "DOMAIN_BLOCKED"

    @pytest.mark.asyncio
    async def test_subdomain_blocking(self, plugin, context):
        """Test that subdomains of blocked domains are also blocked."""
        payload = ResourcePreFetchPayload(uri="https://subdomain.evil.com/data", metadata={})
        result = await plugin.resource_pre_fetch(payload, context)

        assert result.continue_processing is False
        assert result.violation.code == "DOMAIN_BLOCKED"

    @pytest.mark.asyncio
    async def test_post_fetch_without_pre_validation(self, plugin, context):
        """Test post-fetch when pre-fetch validation wasn't done."""
        # Don't set uri_validated state
        content = ResourceContent(
            type="resource",
            uri="test://config",
            text="password: secret",
        )
        payload = ResourcePostFetchPayload(uri="test://config", content=content)

        result = await plugin.resource_post_fetch(payload, context)

        # Should skip processing if not validated
        assert result.continue_processing is True
        assert result.modified_payload == payload

    @pytest.mark.asyncio
    async def test_empty_content_handling(self, plugin, context):
        """Test handling of empty content."""
        context.set_state("uri_validated", True)

        empty_content = ResourceContent(
            type="resource",
            uri="test://empty",
            text="",
        )
        payload = ResourcePostFetchPayload(uri="test://empty", content=empty_content)

        result = await plugin.resource_post_fetch(payload, context)

        assert result.continue_processing is True
        assert result.modified_payload == payload

    @pytest.mark.asyncio
    async def test_invalid_uri_handling(self, plugin, context):
        """Test handling of invalid URIs."""
        payload = ResourcePreFetchPayload(uri="not-a-valid-uri", metadata={})
        result = await plugin.resource_pre_fetch(payload, context)

        # Should handle gracefully
        assert result.continue_processing is False
        assert result.violation is not None

    @pytest.mark.asyncio
    async def test_protocol_extraction(self, plugin, context):
        """Test correct protocol extraction from various URIs."""
        test_cases = [
            ("http://example.com", "http"),
            ("https://example.com", "https"),
            ("ftp://example.com", "ftp"),
            ("file:///path/to/file", "file"),
            ("test://resource", "test"),
        ]

        for uri, expected_protocol in test_cases:
            payload = ResourcePreFetchPayload(uri=uri, metadata={})
            result = await plugin.resource_pre_fetch(payload, context)

            if expected_protocol in ["http", "https", "test"]:
                assert result.modified_payload.metadata["protocol"] == expected_protocol
