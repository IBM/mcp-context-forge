# -*- coding: utf-8 -*-
# pylint: disable=wrong-import-position, import-outside-toplevel, no-name-in-module
"""Location: ./tests/unit/mcpgateway/plugins/framework/test_constants.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for plugin framework constants.
"""

import pytest
from types import MappingProxyType

from mcpgateway.plugins.framework.constants import (
    PLUGIN_VIOLATION_CODE_MAPPING,
    PluginViolationCode,
)


class TestPluginViolationCode:
    """Test suite for PluginViolationCode dataclass."""

    def test_dataclass_immutability(self):
        """Test that PluginViolationCode dataclass is frozen (immutable)."""
        code = PluginViolationCode(429, "RATE_LIMIT", "Rate limit exceeded")
        with pytest.raises(AttributeError):
            code.code = 500

    def test_dataclass_structure(self):
        """Test that PluginViolationCode has correct fields."""
        code = PluginViolationCode(429, "RATE_LIMIT", "Rate limit exceeded")
        assert code.code == 429
        assert code.name == "RATE_LIMIT"
        assert code.message == "Rate limit exceeded"

    def test_dataclass_equality(self):
        """Test that dataclass instances with same values are equal."""
        code1 = PluginViolationCode(429, "RATE_LIMIT", "Rate limit exceeded")
        code2 = PluginViolationCode(429, "RATE_LIMIT", "Rate limit exceeded")
        assert code1 == code2

    def test_dataclass_hashable(self):
        """Test that frozen dataclass instances are hashable."""
        code1 = PluginViolationCode(429, "RATE_LIMIT", "Rate limit exceeded")
        code2 = PluginViolationCode(422, "PII_DETECTED", "PII detected")
        codes_dict = {code1: "rate_limit", code2: "pii"}
        assert codes_dict[code1] == "rate_limit"
        assert codes_dict[code2] == "pii"


class TestPluginViolationCodeMapping:
    """Test suite for PLUGIN_VIOLATION_CODE_MAPPING."""

    def test_mapping_is_mappingproxy(self):
        """Test that mapping is wrapped in MappingProxyType for immutability."""
        assert isinstance(PLUGIN_VIOLATION_CODE_MAPPING, MappingProxyType)

    def test_mapping_is_immutable(self):
        """Test that mapping cannot be modified."""
        with pytest.raises(TypeError):
            PLUGIN_VIOLATION_CODE_MAPPING["NEW_CODE"] = PluginViolationCode(999, "NEW", "New code")

    def test_mapping_values_are_dataclass_instances(self):
        """Test that all mapping values are PluginViolationCode instances."""
        for key, value in PLUGIN_VIOLATION_CODE_MAPPING.items():
            assert isinstance(value, PluginViolationCode)
            assert isinstance(key, str)

    def test_rate_limiting_codes(self):
        """Test rate limiting violation codes."""
        rate_limit = PLUGIN_VIOLATION_CODE_MAPPING["RATE_LIMIT"]
        assert rate_limit.code == 429
        assert rate_limit.name == "RATE_LIMIT"
        assert "rate limit" in rate_limit.message.lower()

    def test_resource_validation_codes(self):
        """Test resource and URI validation codes."""
        invalid_uri = PLUGIN_VIOLATION_CODE_MAPPING["INVALID_URI"]
        assert invalid_uri.code == 400
        assert invalid_uri.name == "INVALID_URI"

        protocol_blocked = PLUGIN_VIOLATION_CODE_MAPPING["PROTOCOL_BLOCKED"]
        assert protocol_blocked.code == 403
        assert protocol_blocked.name == "PROTOCOL_BLOCKED"

        domain_blocked = PLUGIN_VIOLATION_CODE_MAPPING["DOMAIN_BLOCKED"]
        assert domain_blocked.code == 403
        assert domain_blocked.name == "DOMAIN_BLOCKED"

        content_too_large = PLUGIN_VIOLATION_CODE_MAPPING["CONTENT_TOO_LARGE"]
        assert content_too_large.code == 413
        assert content_too_large.name == "CONTENT_TOO_LARGE"

    def test_content_moderation_codes(self):
        """Test content moderation and safety codes."""
        content_moderation = PLUGIN_VIOLATION_CODE_MAPPING["CONTENT_MODERATION"]
        assert content_moderation.code == 422
        assert content_moderation.name == "CONTENT_MODERATION"

        moderation_error = PLUGIN_VIOLATION_CODE_MAPPING["MODERATION_ERROR"]
        assert moderation_error.code == 503
        assert moderation_error.name == "MODERATION_ERROR"

        pii_detected = PLUGIN_VIOLATION_CODE_MAPPING["PII_DETECTED"]
        assert pii_detected.code == 422
        assert pii_detected.name == "PII_DETECTED"

        sensitive_content = PLUGIN_VIOLATION_CODE_MAPPING["SENSITIVE_CONTENT"]
        assert sensitive_content.code == 422
        assert sensitive_content.name == "SENSITIVE_CONTENT"

    def test_authentication_codes(self):
        """Test authentication and authorization codes."""
        invalid_token = PLUGIN_VIOLATION_CODE_MAPPING["INVALID_TOKEN"]
        assert invalid_token.code == 401
        assert invalid_token.name == "INVALID_TOKEN"

        api_key_revoked = PLUGIN_VIOLATION_CODE_MAPPING["API_KEY_REVOKED"]
        assert api_key_revoked.code == 401
        assert api_key_revoked.name == "API_KEY_REVOKED"

        auth_required = PLUGIN_VIOLATION_CODE_MAPPING["AUTH_REQUIRED"]
        assert auth_required.code == 401
        assert auth_required.name == "AUTH_REQUIRED"

    def test_generic_violation_codes(self):
        """Test generic violation codes."""
        prohibited_content = PLUGIN_VIOLATION_CODE_MAPPING["PROHIBITED_CONTENT"]
        assert prohibited_content.code == 422
        assert prohibited_content.name == "PROHIBITED_CONTENT"

        blocked_content = PLUGIN_VIOLATION_CODE_MAPPING["BLOCKED_CONTENT"]
        assert blocked_content.code == 403
        assert blocked_content.name == "BLOCKED_CONTENT"

        blocked = PLUGIN_VIOLATION_CODE_MAPPING["BLOCKED"]
        assert blocked.code == 403
        assert blocked.name == "BLOCKED"

        execution_error = PLUGIN_VIOLATION_CODE_MAPPING["EXECUTION_ERROR"]
        assert execution_error.code == 500
        assert execution_error.name == "EXECUTION_ERROR"

        processing_error = PLUGIN_VIOLATION_CODE_MAPPING["PROCESSING_ERROR"]
        assert processing_error.code == 500
        assert processing_error.name == "PROCESSING_ERROR"

    def test_mapping_contains_expected_keys(self):
        """Test that mapping contains all expected violation code keys."""
        expected_keys = {
            "RATE_LIMIT",
            "INVALID_URI",
            "PROTOCOL_BLOCKED",
            "DOMAIN_BLOCKED",
            "CONTENT_TOO_LARGE",
            "CONTENT_MODERATION",
            "MODERATION_ERROR",
            "PII_DETECTED",
            "SENSITIVE_CONTENT",
            "INVALID_TOKEN",
            "API_KEY_REVOKED",
            "AUTH_REQUIRED",
            "PROHIBITED_CONTENT",
            "BLOCKED_CONTENT",
            "BLOCKED",
            "EXECUTION_ERROR",
            "PROCESSING_ERROR",
        }
        assert set(PLUGIN_VIOLATION_CODE_MAPPING.keys()) == expected_keys

    def test_mapping_count(self):
        """Test that mapping contains expected number of codes."""
        assert len(PLUGIN_VIOLATION_CODE_MAPPING) == 17

    def test_code_ranges(self):
        """Test that codes are in expected HTTP status code ranges."""
        for key, violation_code in PLUGIN_VIOLATION_CODE_MAPPING.items():
            # All codes should be valid HTTP status codes
            assert 400 <= violation_code.code <= 599, f"{key} has invalid code {violation_code.code}"

    def test_dataclass_repr(self):
        """Test that dataclass has a useful string representation."""
        code = PLUGIN_VIOLATION_CODE_MAPPING["RATE_LIMIT"]
        repr_str = repr(code)
        assert "429" in repr_str
        assert "RATE_LIMIT" in repr_str

    def test_all_codes_have_messages(self):
        """Test that all violation codes have non-empty messages."""
        for key, violation_code in PLUGIN_VIOLATION_CODE_MAPPING.items():
            assert violation_code.message, f"{key} has empty message"
            assert len(violation_code.message) > 0, f"{key} has empty message"

    def test_code_name_consistency(self):
        """Test that code names match their dictionary keys."""
        for key, violation_code in PLUGIN_VIOLATION_CODE_MAPPING.items():
            assert violation_code.name == key, f"Key {key} doesn't match code name {violation_code.name}"

    def test_http_status_code_categories(self):
        """Test that codes are grouped by HTTP status code categories."""
        # 4xx Client Errors
        client_error_codes = [
            "INVALID_URI",
            "PROTOCOL_BLOCKED",
            "DOMAIN_BLOCKED",
            "CONTENT_TOO_LARGE",
            "CONTENT_MODERATION",
            "PII_DETECTED",
            "SENSITIVE_CONTENT",
            "INVALID_TOKEN",
            "API_KEY_REVOKED",
            "AUTH_REQUIRED",
            "PROHIBITED_CONTENT",
            "BLOCKED_CONTENT",
            "BLOCKED",
            "RATE_LIMIT",
        ]
        for key in client_error_codes:
            code = PLUGIN_VIOLATION_CODE_MAPPING[key]
            assert 400 <= code.code < 500, f"{key} should be 4xx client error"

        # 5xx Server Errors
        server_error_codes = ["MODERATION_ERROR", "EXECUTION_ERROR", "PROCESSING_ERROR"]
        for key in server_error_codes:
            code = PLUGIN_VIOLATION_CODE_MAPPING[key]
            assert 500 <= code.code < 600, f"{key} should be 5xx server error"
