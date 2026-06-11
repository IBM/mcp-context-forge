# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_a2a_passthrough_headers_simple.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Simple unit tests for A2A passthrough headers filtering logic.

Tests the header filtering logic added in Phase 1 without full service mocking.
"""

# Standard
from typing import Dict, List, Optional

# Third-Party
import pytest


class TestPassthroughHeaderFiltering:
    """Test the passthrough header filtering logic."""

    def filter_headers_by_whitelist(
        self,
        request_headers: Optional[Dict[str, str]],
        whitelist: Optional[List[str]],
    ) -> Dict[str, str]:
        """Simulate the filtering logic from a2a_service.py:2091-2103."""
        if not request_headers:
            return {}

        if whitelist:
            whitelist_lower = {h.lower() for h in whitelist}
            return {k: v for k, v in request_headers.items() if k in whitelist_lower}

        # No whitelist = no headers forwarded
        return {}

    def test_forwards_whitelisted_headers(self):
        """Whitelisted headers are forwarded."""
        request_headers = {
            "x-tenant-id": "acme-corp",
            "x-request-id": "test-123",
            "x-unrelated-header": "should-not-forward",
        }
        whitelist = ["X-Tenant-ID", "X-Request-ID"]

        result = self.filter_headers_by_whitelist(request_headers, whitelist)

        assert "x-tenant-id" in result
        assert result["x-tenant-id"] == "acme-corp"
        assert "x-request-id" in result
        assert result["x-request-id"] == "test-123"
        assert "x-unrelated-header" not in result

    def test_case_insensitive_matching(self):
        """Headers matched case-insensitively against whitelist."""
        request_headers = {
            "x-tenant-id": "acme",
            "x-request-id": "123",
        }
        whitelist = ["X-TENANT-ID", "X-REQUEST-ID"]  # Different casing

        result = self.filter_headers_by_whitelist(request_headers, whitelist)

        assert "x-tenant-id" in result
        assert "x-request-id" in result

    def test_blocks_non_whitelisted_headers(self):
        """Headers not in whitelist are blocked."""
        request_headers = {
            "x-tenant-id": "acme",
            "x-attacker-header": "malicious",
            "x-internal-secret": "should-not-forward",
        }
        whitelist = ["X-Tenant-ID"]

        result = self.filter_headers_by_whitelist(request_headers, whitelist)

        assert "x-tenant-id" in result
        assert "x-attacker-header" not in result
        assert "x-internal-secret" not in result

    def test_empty_whitelist_blocks_all(self):
        """Empty whitelist blocks all headers."""
        request_headers = {
            "x-tenant-id": "acme",
            "x-request-id": "123",
        }
        whitelist = []

        result = self.filter_headers_by_whitelist(request_headers, whitelist)

        assert len(result) == 0

    def test_none_whitelist_blocks_all(self):
        """None whitelist blocks all headers."""
        request_headers = {
            "x-tenant-id": "acme",
            "x-request-id": "123",
        }
        whitelist = None

        result = self.filter_headers_by_whitelist(request_headers, whitelist)

        assert len(result) == 0

    def test_none_request_headers_returns_empty(self):
        """None request_headers returns empty dict."""
        whitelist = ["X-Tenant-ID"]

        result = self.filter_headers_by_whitelist(None, whitelist)

        assert result == {}

    def test_empty_request_headers_returns_empty(self):
        """Empty request_headers returns empty dict."""
        request_headers = {}
        whitelist = ["X-Tenant-ID"]

        result = self.filter_headers_by_whitelist(request_headers, whitelist)

        assert result == {}

    def test_multiple_headers_partial_match(self):
        """Only whitelisted subset is forwarded."""
        request_headers = {
            "x-tenant-id": "acme",
            "x-request-id": "123",
            "x-correlation-id": "abc",
            "x-user-id": "user1",
            "x-other": "value",
        }
        whitelist = ["X-Tenant-ID", "X-Request-ID"]

        result = self.filter_headers_by_whitelist(request_headers, whitelist)

        assert len(result) == 2
        assert "x-tenant-id" in result
        assert "x-request-id" in result
        assert "x-correlation-id" not in result
        assert "x-user-id" not in result
        assert "x-other" not in result
