# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/plugins/resource_filter/test_resource_filter.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for the ResourceFilterPlugin.
"""

# Third-Party
import pytest

# First-Party
from mcpgateway.common.models import ResourceContent
from cpex.framework import (
    GlobalContext,
    PluginConfig,
    PluginContext,
    PluginMode,
    ResourceHookType,
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
            hooks=[ResourceHookType.RESOURCE_PRE_FETCH, ResourceHookType.RESOURCE_POST_FETCH],
            tags=["test", "filter"],
            mode=PluginMode.SEQUENTIAL,
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
        return PluginContext(global_context=GlobalContext(request_id="test-123", user="testuser"))

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
            id="123",
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
            id="123",
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
            id="123",
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
        permissive_config = plugin_config.model_copy(update={"mode": PluginMode.TRANSFORM})
        plugin = ResourceFilterPlugin(permissive_config)

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
            id="123",
            uri="test://config",
            text=("Config file:\npassword: pass123\napi-key: key456\napi_key: key789\nsecret: sec000\nusername: admin"),
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
            id="123",
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
            id="123",
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

    # Regression: the blocklist must be decided over the connected host, not the authority.

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "uri,expected_host",
        [
            pytest.param("http://good.com@evil.com/data", "evil.com", id="userinfo"),
            pytest.param("http://user:pw@evil.com/data", "evil.com", id="userinfo_with_password"),  # pragma: allowlist secret
            pytest.param("http://evil.com:8080/data", "evil.com", id="port"),
            pytest.param("http://user:pw@evil.com:8080/data", "evil.com", id="userinfo_and_port"),  # pragma: allowlist secret
            pytest.param("http://evil.com./data", "evil.com", id="trailing_dot"),
            pytest.param("http://good.com@evil.com.:443/data", "evil.com", id="userinfo_port_and_trailing_dot"),
            pytest.param("https://subdomain.evil.com/data", "subdomain.evil.com", id="subdomain"),
        ],
    )
    async def test_blocked_domain_not_bypassed_by_authority(self, plugin, context, uri, expected_host):
        """Blocked domains stay blocked regardless of userinfo, port, or trailing dot."""
        payload = ResourcePreFetchPayload(uri=uri, metadata={})
        result = await plugin.resource_pre_fetch(payload, context)

        assert result.continue_processing is False, f"{uri} bypassed the domain blocklist"
        assert result.violation is not None
        assert result.violation.code == "DOMAIN_BLOCKED"
        # The violation must name the evaluated host, not the raw authority.
        assert result.violation.details["domain"] == expected_host

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "uri",
        [
            pytest.param("https://good.com/data", id="unrelated_host"),
            pytest.param("https://notevil.com/data", id="suffix_confusion"),
            pytest.param("https://evil.com.attacker.net/data", id="blocked_domain_as_prefix_label"),
        ],
    )
    async def test_host_matching_does_not_overblock(self, plugin, context, uri):
        """Hosts that merely contain a blocked domain as a substring stay allowed."""
        payload = ResourcePreFetchPayload(uri=uri, metadata={})
        result = await plugin.resource_pre_fetch(payload, context)

        assert result.continue_processing is True
        assert result.violation is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "uri,expected_host",
        [
            pytest.param("http://evil%2ecom/data", "evil.com", id="percent_encoded_dot"),
            pytest.param("http://ev%69l.com/data", "evil.com", id="percent_encoded_letter"),
            pytest.param("http://EVIL.COM./data", "evil.com", id="uppercase_and_trailing_dot"),
        ],
    )
    async def test_encoded_host_spellings_are_blocked(self, plugin, context, uri, expected_host):
        """Alternative spellings of a blocked host canonicalize to the same entry."""
        payload = ResourcePreFetchPayload(uri=uri, metadata={})
        result = await plugin.resource_pre_fetch(payload, context)

        assert result.continue_processing is False, f"{uri} bypassed the domain blocklist"
        assert result.violation.code == "DOMAIN_BLOCKED"
        assert result.violation.details["domain"] == expected_host

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "configured,uri",
        [
            pytest.param("[::1]", "http://[::1]/data", id="bracketed_config_bracketed_uri"),
            pytest.param("::1", "http://[::1]/data", id="bare_config_bracketed_uri"),
            pytest.param("0:0:0:0:0:0:0:1", "http://[::1]/data", id="expanded_config_compressed_uri"),
        ],
    )
    async def test_ipv6_literals_match_regardless_of_spelling(self, plugin_config, context, configured, uri):
        """A bracketed IPv6 entry keeps blocking: matching on hostname strips the brackets."""
        ipv6_config = plugin_config.model_copy(update={"config": {**plugin_config.config, "blocked_domains": [configured]}})
        ipv6_plugin = ResourceFilterPlugin(ipv6_config)

        result = await ipv6_plugin.resource_pre_fetch(ResourcePreFetchPayload(uri=uri, metadata={}), context)

        assert result.continue_processing is False, f"config {configured!r} failed to block {uri}"
        assert result.violation.code == "DOMAIN_BLOCKED"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "uri",
        [
            pytest.param("http://2130706433/data", id="decimal_integer"),
            pytest.param("http://0x7f000001/data", id="hexadecimal"),
            pytest.param("http://0177.0.0.1/data", id="octal"),
            pytest.param("http://127.1/data", id="shortened_dotted"),
            pytest.param("http://127.0.0.1/data", id="canonical"),
            pytest.param("http://[::ffff:127.0.0.1]/data", id="ipv4_mapped_ipv6_dotted"),
            pytest.param("http://[::ffff:7f00:1]/data", id="ipv4_mapped_ipv6_hex"),
        ],
    )
    async def test_legacy_ipv4_spellings_are_blocked(self, plugin_config, context, uri):
        """Legacy IPv4 forms the resolver accepts must match a canonical blocked entry."""
        ip_config = plugin_config.model_copy(update={"config": {**plugin_config.config, "blocked_domains": ["127.0.0.1"]}})
        ip_plugin = ResourceFilterPlugin(ip_config)

        result = await ip_plugin.resource_pre_fetch(ResourcePreFetchPayload(uri=uri, metadata={}), context)

        assert result.continue_processing is False, f"{uri} bypassed the IP blocklist"
        assert result.violation.code == "DOMAIN_BLOCKED"
        assert result.violation.details["domain"] == "127.0.0.1"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "configured,uri",
        [
            pytest.param("evil.com:8443", "https://evil.com:8443/data", id="host_port_entry_same_port"),
            pytest.param("evil.com:8443", "https://evil.com/data", id="host_port_entry_becomes_host_wide"),
            pytest.param("[::1]:8443", "http://[::1]:8443/data", id="bracketed_ipv6_port_entry"),
            pytest.param("[::1]:8443", "http://[::1]/data", id="bracketed_ipv6_port_entry_no_port"),
        ],
    )
    async def test_port_bearing_config_entries_still_enforce(self, plugin_config, context, configured, uri):
        """An entry written as host:port degrades to a host-wide block rather than matching nothing."""
        port_config = plugin_config.model_copy(update={"config": {**plugin_config.config, "blocked_domains": [configured]}})
        port_plugin = ResourceFilterPlugin(port_config)

        result = await port_plugin.resource_pre_fetch(ResourcePreFetchPayload(uri=uri, metadata={}), context)

        assert result.continue_processing is False, f"config {configured!r} failed to block {uri}"
        assert result.violation.code == "DOMAIN_BLOCKED"

    @pytest.mark.asyncio
    async def test_port_bearing_config_entry_does_not_overblock(self, plugin_config, context):
        """Reducing host:port to the host must not start matching unrelated hosts."""
        port_config = plugin_config.model_copy(update={"config": {**plugin_config.config, "blocked_domains": ["evil.com:8443"]}})
        port_plugin = ResourceFilterPlugin(port_config)

        result = await port_plugin.resource_pre_fetch(ResourcePreFetchPayload(uri="https://good.com:8443/data", metadata={}), context)

        assert result.continue_processing is True
        assert result.violation is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "configured,uri",
        [
            pytest.param("münchen.de", "http://xn--mnchen-3ya.de/data", id="unicode_config_punycode_uri"),
            pytest.param("xn--mnchen-3ya.de", "http://münchen.de/data", id="punycode_config_unicode_uri"),
        ],
    )
    async def test_idn_matches_in_both_directions(self, plugin_config, context, configured, uri):
        """Unicode and punycode spell the same domain, so either config form blocks either URI form."""
        idn_config = plugin_config.model_copy(update={"config": {**plugin_config.config, "blocked_domains": [configured]}})
        idn_plugin = ResourceFilterPlugin(idn_config)

        result = await idn_plugin.resource_pre_fetch(ResourcePreFetchPayload(uri=uri, metadata={}), context)

        assert result.continue_processing is False, f"config {configured!r} failed to block {uri}"
        assert result.violation.code == "DOMAIN_BLOCKED"

    @pytest.mark.asyncio
    async def test_transform_mode_records_authority_bypass(self, plugin_config, context):
        """In transform mode a disguised blocked domain is recorded but not blocked."""
        transform_config = plugin_config.model_copy(update={"mode": PluginMode.TRANSFORM})
        transform_plugin = ResourceFilterPlugin(transform_config)

        payload = ResourcePreFetchPayload(uri="http://good.com@evil.com/data", metadata={})
        result = await transform_plugin.resource_pre_fetch(payload, context)

        assert result.continue_processing is True
        assert result.violation is not None
        assert result.violation.code == "DOMAIN_BLOCKED"
