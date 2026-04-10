"""Unit tests for content type matching in plugin framework.

Tests the content_types condition matching functionality added to fix issue #3925.
"""

import pytest

from cpex.framework import GlobalContext, PluginCondition
from cpex.framework.utils import matches, normalize_content_type


class TestNormalizeContentType:
    """Test content type normalization helper function."""

    def test_normalize_content_type_basic(self):
        """Test basic content type normalization."""
        assert normalize_content_type("application/json") == "application/json"
        assert normalize_content_type("text/html") == "text/html"
        assert normalize_content_type("text/plain") == "text/plain"

    def test_normalize_content_type_with_charset(self):
        """Test normalization strips charset parameter."""
        assert normalize_content_type("application/json; charset=utf-8") == "application/json"
        assert normalize_content_type("text/html; charset=iso-8859-1") == "text/html"
        assert normalize_content_type("text/plain;charset=utf-8") == "text/plain"

    def test_normalize_content_type_case_insensitive(self):
        """Test case-insensitive normalization."""
        assert normalize_content_type("APPLICATION/JSON") == "application/json"
        assert normalize_content_type("Text/Plain") == "text/plain"
        assert normalize_content_type("TEXT/HTML") == "text/html"

    def test_normalize_content_type_with_multiple_parameters(self):
        """Test normalization with multiple parameters."""
        assert normalize_content_type("application/json; charset=utf-8; boundary=something") == "application/json"
        assert normalize_content_type("multipart/form-data; boundary=----WebKitFormBoundary") == "multipart/form-data"

    def test_normalize_content_type_with_spaces(self):
        """Test normalization handles extra spaces."""
        assert normalize_content_type("application/json ; charset=utf-8") == "application/json"
        assert normalize_content_type("text/plain  ;  charset=utf-8") == "text/plain"


class TestContentTypeMatching:
    """Test content_types condition matching in matches() function."""

    def test_matches_content_type_single_match(self):
        """Test matching single content type."""
        condition = PluginCondition(content_types=["application/json"])
        context = GlobalContext(request_id="req1", content_type="application/json")
        assert matches(condition, context) is True

    def test_matches_content_type_single_no_match(self):
        """Test non-matching single content type."""
        condition = PluginCondition(content_types=["application/json"])
        context = GlobalContext(request_id="req1", content_type="text/plain")
        assert matches(condition, context) is False

    def test_matches_content_type_multiple_match(self):
        """Test matching one of multiple content types."""
        condition = PluginCondition(content_types=["application/json", "text/plain"])
        context = GlobalContext(request_id="req1", content_type="text/plain")
        assert matches(condition, context) is True

    def test_matches_content_type_multiple_no_match(self):
        """Test non-matching multiple content types."""
        condition = PluginCondition(content_types=["application/json", "application/xml"])
        context = GlobalContext(request_id="req1", content_type="text/plain")
        assert matches(condition, context) is False

    def test_matches_content_type_with_charset(self):
        """Test matching ignores charset parameter."""
        condition = PluginCondition(content_types=["application/json"])
        context = GlobalContext(request_id="req1", content_type="application/json; charset=utf-8")
        assert matches(condition, context) is True

    def test_matches_content_type_case_insensitive(self):
        """Test case-insensitive content type matching."""
        condition = PluginCondition(content_types=["application/json"])
        context = GlobalContext(request_id="req1", content_type="APPLICATION/JSON")
        assert matches(condition, context) is True

    def test_matches_content_type_none_context(self):
        """Test strict AND logic: condition fails when context.content_type is None but required."""
        condition = PluginCondition(content_types=["application/json"])
        context = GlobalContext(request_id="req1", content_type=None)
        # Strict AND logic - plugin should NOT execute when content_type is None but required
        assert matches(condition, context) is False

    def test_matches_content_type_empty_list(self):
        """Test empty content_types list matches everything."""
        condition = PluginCondition(content_types=[])
        context = GlobalContext(request_id="req1", content_type="application/json")
        assert matches(condition, context) is True

    def test_matches_content_type_none_condition(self):
        """Test None content_types condition matches everything."""
        condition = PluginCondition(content_types=None)
        context = GlobalContext(request_id="req1", content_type="application/json")
        assert matches(condition, context) is True

    def test_matches_content_type_combined_with_server_id(self):
        """Test content_types combined with server_ids condition."""
        condition = PluginCondition(
            server_ids={"srv1"},
            content_types=["application/json"]
        )

        # Both match
        context1 = GlobalContext(
            request_id="req1",
            server_id="srv1",
            content_type="application/json"
        )
        assert matches(condition, context1) is True

        # Server ID mismatch
        context2 = GlobalContext(
            request_id="req2",
            server_id="srv2",
            content_type="application/json"
        )
        assert matches(condition, context2) is False

        # Content type mismatch
        context3 = GlobalContext(
            request_id="req3",
            server_id="srv1",
            content_type="text/plain"
        )
        assert matches(condition, context3) is False

    def test_matches_content_type_combined_with_tenant_id(self):
        """Test content_types combined with tenant_ids condition."""
        condition = PluginCondition(
            tenant_ids={"tenant1"},
            content_types=["application/json"]
        )

        # Both match
        context1 = GlobalContext(
            request_id="req1",
            tenant_id="tenant1",
            content_type="application/json"
        )
        assert matches(condition, context1) is True

        # Tenant ID mismatch
        context2 = GlobalContext(
            request_id="req2",
            tenant_id="tenant2",
            content_type="application/json"
        )
        assert matches(condition, context2) is False

    def test_matches_content_type_combined_with_user_patterns(self):
        """Test content_types combined with user_patterns condition."""
        condition = PluginCondition(
            user_patterns=["admin"],
            content_types=["application/json"]
        )

        # Both match
        context1 = GlobalContext(
            request_id="req1",
            user="admin_user",
            content_type="application/json"
        )
        assert matches(condition, context1) is True

        # User pattern mismatch
        context2 = GlobalContext(
            request_id="req2",
            user="regular_user",
            content_type="application/json"
        )
        assert matches(condition, context2) is False

    def test_matches_content_type_all_conditions_combined(self):
        """Test content_types with all other conditions."""
        condition = PluginCondition(
            server_ids={"srv1"},
            tenant_ids={"tenant1"},
            user_patterns=["admin"],
            content_types=["application/json"]
        )

        # All match
        context1 = GlobalContext(
            request_id="req1",
            server_id="srv1",
            tenant_id="tenant1",
            user="admin_user",
            content_type="application/json"
        )
        assert matches(condition, context1) is True

        # One condition fails
        context2 = GlobalContext(
            request_id="req2",
            server_id="srv1",
            tenant_id="tenant1",
            user="admin_user",
            content_type="text/plain"
        )
        assert matches(condition, context2) is False

    def test_matches_content_type_multipart_form_data(self):
        """Test matching multipart/form-data content type."""
        condition = PluginCondition(content_types=["multipart/form-data"])
        context = GlobalContext(
            request_id="req1",
            content_type="multipart/form-data; boundary=----WebKitFormBoundary"
        )
        assert matches(condition, context) is True

    def test_matches_content_type_xml(self):
        """Test matching XML content types."""
        condition = PluginCondition(content_types=["application/xml", "text/xml"])

        context1 = GlobalContext(request_id="req1", content_type="application/xml")
        assert matches(condition, context1) is True

        context2 = GlobalContext(request_id="req2", content_type="text/xml")
        assert matches(condition, context2) is True

    def test_matches_backward_compatibility_no_content_type_field(self):
        """Test backward compatibility when content_type is not set."""
        condition = PluginCondition(content_types=["application/json"])
        # Create context without content_type (defaults to None)
        context = GlobalContext(request_id="req1")
        # Strict AND logic - plugin should NOT execute when content_type is None but required
        assert matches(condition, context) is False
