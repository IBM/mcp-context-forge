# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_metadata_capture.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for metadata capture utilities.
This module tests the metadata capture functionality for comprehensive
audit tracking of entity creation and modification operations.
"""

# Standard
from types import SimpleNamespace

# Third-Party

# First-Party
from mcpgateway.utils.metadata_capture import MetadataCapture


class TestMetadataCapture:
    """Test cases for MetadataCapture utility class."""

    def test_extract_request_context_basic(self):
        """Test basic request context extraction."""
        # Create mock request
        request = SimpleNamespace()
        request.client = SimpleNamespace()
        request.client.host = "192.168.1.100"
        request.headers = {"user-agent": "Mozilla/5.0 (Linux)"}
        request.url = SimpleNamespace()
        request.url.path = "/tools"

        context = MetadataCapture.extract_request_context(request)

        assert context["from_ip"] == "192.168.1.100"
        assert context["user_agent"] == "Mozilla/5.0 (Linux)"
        assert context["via"] == "api"

    def test_extract_request_context_admin_ui(self):
        """Test request context extraction for admin UI."""
        request = SimpleNamespace()
        request.client = SimpleNamespace()
        request.client.host = "10.0.0.1"
        request.headers = {"user-agent": "Chrome/90.0"}
        request.url = SimpleNamespace()
        request.url.path = "/ui/tools"  # Use /ui path (default UI base path)

        context = MetadataCapture.extract_request_context(request)

        assert context["from_ip"] == "10.0.0.1"
        assert context["via"] == "ui"

    def test_extract_request_context_proxy_headers(self):
        """Test IP extraction with proxy headers."""
        request = SimpleNamespace()
        request.client = SimpleNamespace()
        request.client.host = "127.0.0.1"
        request.headers = {"user-agent": "curl/7.68.0", "x-forwarded-for": "203.0.113.1, 192.168.1.1, 127.0.0.1"}
        request.url = SimpleNamespace()
        request.url.path = "/api/tools"

        context = MetadataCapture.extract_request_context(request)

        # Should use first IP from X-Forwarded-For
        assert context["from_ip"] == "203.0.113.1"
        assert context["user_agent"] == "curl/7.68.0"

    def test_extract_request_context_no_client(self):
        """Test request context when client info is missing."""
        request = SimpleNamespace()
        request.client = None
        request.headers = {"user-agent": "test/1.0"}
        request.url = SimpleNamespace()
        request.url.path = "/tools"

        context = MetadataCapture.extract_request_context(request)

        assert context["from_ip"] is None
        assert context["user_agent"] == "test/1.0"
        assert context["via"] == "api"

    def test_extract_creation_metadata(self):
        """Test complete creation metadata extraction."""
        request = SimpleNamespace()
        request.client = SimpleNamespace()
        request.client.host = "172.16.0.5"
        request.headers = {"user-agent": "HTTPie/2.4.0"}
        request.url = SimpleNamespace()
        request.url.path = "/ui/servers"  # Use /ui path (default UI base path)

        metadata = MetadataCapture.extract_creation_metadata(request, "admin", import_batch_id="batch-123", federation_source="gateway-prod")

        assert metadata["created_by"] == "admin"
        assert metadata["created_from_ip"] == "172.16.0.5"
        assert metadata["created_via"] == "ui"
        assert metadata["created_user_agent"] == "HTTPie/2.4.0"
        assert metadata["import_batch_id"] == "batch-123"
        assert metadata["federation_source"] == "gateway-prod"
        assert metadata["version"] == 1

    def test_extract_creation_metadata_anonymous_user(self):
        """Test creation metadata with anonymous user."""
        request = SimpleNamespace()
        request.client = SimpleNamespace()
        request.client.host = "192.168.1.1"
        request.headers = {"user-agent": "test-client"}
        request.url = SimpleNamespace()
        request.url.path = "/tools"

        metadata = MetadataCapture.extract_creation_metadata(request, "anonymous")

        assert metadata["created_by"] == "anonymous"
        assert metadata["created_via"] == "api"
        assert metadata["version"] == 1

    def test_extract_modification_metadata(self):
        """Test modification metadata extraction."""
        request = SimpleNamespace()
        request.client = SimpleNamespace()
        request.client.host = "10.1.1.1"
        request.headers = {"user-agent": "PostmanRuntime/7.28.0"}
        request.url = SimpleNamespace()
        request.url.path = "/tools/123"

        metadata = MetadataCapture.extract_modification_metadata(request, "alice", 3)

        assert metadata["modified_by"] == "alice"
        assert metadata["modified_from_ip"] == "10.1.1.1"
        assert metadata["modified_via"] == "api"
        assert metadata["modified_user_agent"] == "PostmanRuntime/7.28.0"
        assert metadata["version"] == 4  # current_version + 1

    def test_determine_source_from_context_import(self):
        """Test source determination for bulk import."""
        source = MetadataCapture.determine_source_from_context(import_batch_id="batch-456", via="api")
        assert source == "import"

    def test_determine_source_from_context_federation(self):
        """Test source determination for federation."""
        source = MetadataCapture.determine_source_from_context(federation_source="gateway-east", via="api")
        assert source == "federation"

    def test_determine_source_from_context_normal(self):
        """Test source determination for normal operations."""
        source = MetadataCapture.determine_source_from_context(via="ui")
        assert source == "ui"

    def test_sanitize_user_agent_normal(self):
        """Test normal user agent sanitization."""
        result = MetadataCapture.sanitize_user_agent("Mozilla/5.0 (Windows NT 10.0)")
        assert result == "Mozilla/5.0 (Windows NT 10.0)"

    def test_sanitize_user_agent_none(self):
        """Test user agent sanitization with None input."""
        result = MetadataCapture.sanitize_user_agent(None)
        assert result is None

    def test_sanitize_user_agent_empty(self):
        """Test user agent sanitization with empty string."""
        result = MetadataCapture.sanitize_user_agent("")
        assert result is None

    def test_sanitize_user_agent_long(self):
        """Test user agent sanitization with overly long input."""
        long_ua = "x" * 1000
        result = MetadataCapture.sanitize_user_agent(long_ua)
        assert len(result) == 503  # 500 + "..."
        assert result.endswith("...")

    def test_sanitize_user_agent_with_special_chars(self):
        """Test user agent sanitization with special characters."""
        ua_with_newlines = "Mozilla/5.0\n(Linux;\r\tX11)"
        result = MetadataCapture.sanitize_user_agent(ua_with_newlines)
        assert "\n" not in result
        assert "\r" not in result
        assert "\t" not in result
        assert result == "Mozilla/5.0 (Linux;  X11)"

    def test_validate_ip_address_ipv4(self):
        """Test IP address validation for IPv4."""
        result = MetadataCapture.validate_ip_address("192.168.1.1")
        assert result == "192.168.1.1"

    def test_validate_ip_address_ipv6(self):
        """Test IP address validation for IPv6."""
        result = MetadataCapture.validate_ip_address("2001:db8::1")
        assert result == "2001:db8::1"

    def test_validate_ip_address_none(self):
        """Test IP address validation with None."""
        result = MetadataCapture.validate_ip_address(None)
        assert result is None

    def test_validate_ip_address_empty(self):
        """Test IP address validation with empty string."""
        result = MetadataCapture.validate_ip_address("")
        assert result is None

    def test_validate_ip_address_long(self):
        """Test IP address validation with overly long input."""
        long_ip = "x" * 100
        result = MetadataCapture.validate_ip_address(long_ip)
        assert len(result) == 45  # Truncated to max IPv6 length

    def test_validate_ip_address_with_whitespace(self):
        """Test IP address validation with whitespace."""
        result = MetadataCapture.validate_ip_address("  192.168.1.1  ")
        assert result == "192.168.1.1"

    def test_extract_creation_metadata_all_none(self):
        """Test creation metadata with all optional parameters None."""
        request = SimpleNamespace()
        request.client = SimpleNamespace()
        request.client.host = "192.168.1.1"
        request.headers = {"user-agent": "test"}
        request.url = SimpleNamespace()
        request.url.path = "/tools"

        metadata = MetadataCapture.extract_creation_metadata(request, "user", import_batch_id=None, federation_source=None)

        assert metadata["created_by"] == "user"
        assert metadata["import_batch_id"] is None
        assert metadata["federation_source"] is None

    def test_extract_modification_metadata_default_version(self):
        """Test modification metadata with default version."""
        request = SimpleNamespace()
        request.client = SimpleNamespace()
        request.client.host = "10.0.0.1"
        request.headers = {"user-agent": "test"}
        request.url = SimpleNamespace()
        request.url.path = "/tools/123"

        metadata = MetadataCapture.extract_modification_metadata(request, "bob")

        assert metadata["modified_by"] == "bob"
        assert metadata["version"] == 2  # 1 + 1

    def test_edge_case_no_url_attribute(self):
        """Test edge case where request has no url attribute."""
        request = SimpleNamespace()
        request.client = SimpleNamespace()
        request.client.host = "192.168.1.1"
        request.headers = {"user-agent": "test"}
        # No url attribute

        context = MetadataCapture.extract_request_context(request)

        assert context["from_ip"] == "192.168.1.1"
        assert context["via"] == "api"  # default when no path available

    def test_edge_case_no_headers(self):
        """Test edge case where request has no headers."""
        request = SimpleNamespace()
        request.client = SimpleNamespace()
        request.client.host = "192.168.1.1"
        request.headers = {}
        request.url = SimpleNamespace()
        request.url.path = "/tools"

        context = MetadataCapture.extract_request_context(request)

        assert context["user_agent"] is None
        assert context["from_ip"] == "192.168.1.1"

    def test_edge_case_malformed_forwarded_header(self):
        """Test edge case with malformed X-Forwarded-For header."""
        request = SimpleNamespace()
        request.client = SimpleNamespace()
        request.client.host = "127.0.0.1"
        request.headers = {"user-agent": "test", "x-forwarded-for": "malformed"}
        request.url = SimpleNamespace()
        request.url.path = "/tools"

        context = MetadataCapture.extract_request_context(request)

        # Should still extract the forwarded IP even if malformed
        assert context["from_ip"] == "malformed"

    def test_extract_username_string(self):
        """Test username extraction from string."""
        result = MetadataCapture.extract_username("admin")
        assert result == "admin"

    def test_extract_username_dict_username(self):
        """Test username extraction from dict with username field."""
        result = MetadataCapture.extract_username({"username": "alice", "exp": 123})
        assert result == "alice"

    def test_extract_username_dict_sub(self):
        """Test username extraction from dict with sub field."""
        result = MetadataCapture.extract_username({"sub": "bob", "exp": 123})
        assert result == "bob"

    def test_extract_username_dict_empty(self):
        """Test username extraction from empty dict."""
        result = MetadataCapture.extract_username({})
        assert result == "unknown"

    def test_extract_username_none(self):
        """Test username extraction from None."""
        result = MetadataCapture.extract_username(None)
        assert result == "unknown"

    def test_extract_username_invalid_type(self):
        """Test username extraction from invalid type."""
        result = MetadataCapture.extract_username(123)
        assert result == "unknown"
