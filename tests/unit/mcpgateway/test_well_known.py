# -*- coding: utf-8 -*-
"""Test cases for well-known URI endpoints."""

import json
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

# Import the main FastAPI app
from mcpgateway.main import app


class TestWellKnownEndpoints:
    """Test suite for well-known URI endpoints."""

    @pytest.fixture
    def client(self):
        """Create a test client for the FastAPI app."""
        return TestClient(app)

    def test_robots_txt_default(self, client):
        """Test default robots.txt blocks all crawlers."""
        response = client.get("/.well-known/robots.txt")
        assert response.status_code == 200
        assert "User-agent: *" in response.text
        assert "Disallow: /" in response.text
        assert response.headers["content-type"] == "text/plain; charset=utf-8"
        assert "X-Robots-Tag" in response.headers
        assert response.headers["X-Robots-Tag"] == "noindex, nofollow"

    def test_security_txt_not_configured(self, client):
        """Test security.txt returns 404 when not configured."""
        response = client.get("/.well-known/security.txt")
        assert response.status_code == 404
        assert "security.txt not configured" in response.text

    def test_unknown_well_known_file(self, client):
        """Test unknown well-known file returns 404."""
        response = client.get("/.well-known/unknown.txt")
        assert response.status_code == 404

    def test_known_but_unconfigured_file(self, client):
        """Test known well-known URI that is not configured returns helpful 404."""
        response = client.get("/.well-known/change-password")
        assert response.status_code == 404
        assert "change-password is not configured" in response.text
        assert "Change password URL" in response.text

    def test_well_known_path_normalization(self, client):
        """Test that paths are properly normalized (removing leading slashes)."""
        # Test with leading slash
        response = client.get("/.well-known//robots.txt")
        assert response.status_code == 200
        assert "User-agent: *" in response.text


class TestSecurityTxtValidation:
    """Test security.txt validation functionality."""

    def test_validate_security_txt_empty(self):
        """Test validation with empty content."""
        from mcpgateway.routers.well_known import validate_security_txt

        result = validate_security_txt("")
        assert result is None

        result = validate_security_txt(None)
        assert result is None

    def test_validate_security_txt_adds_expires(self):
        """Test that validation adds Expires field."""
        from mcpgateway.routers.well_known import validate_security_txt

        content = "Contact: security@example.com"
        result = validate_security_txt(content)

        assert result is not None
        assert "Contact: security@example.com" in result
        assert "Expires:" in result
        assert "# Security contact information for MCP Gateway" in result

    def test_validate_security_txt_preserves_expires(self):
        """Test that validation preserves existing Expires field."""
        from mcpgateway.routers.well_known import validate_security_txt

        content = "Contact: security@example.com\nExpires: 2025-12-31T23:59:59Z"
        result = validate_security_txt(content)

        assert result is not None
        assert "Expires: 2025-12-31T23:59:59Z" in result
        # Should not add a second Expires field
        assert result.count("Expires:") == 1

    def test_validate_security_txt_preserves_comments(self):
        """Test that validation preserves existing comments."""
        from mcpgateway.routers.well_known import validate_security_txt

        content = "# Custom security information\nContact: security@example.com"
        result = validate_security_txt(content)

        assert result is not None
        assert "# Custom security information" in result
        assert "Contact: security@example.com" in result
        assert "Expires:" in result


class TestWellKnownRegistry:
    """Test well-known URI registry functionality."""

    def test_registry_contains_standard_files(self):
        """Test that registry contains expected standard files."""
        from mcpgateway.routers.well_known import WELL_KNOWN_REGISTRY

        expected_files = ["robots.txt", "security.txt", "ai.txt", "dnt-policy.txt", "change-password"]

        for file in expected_files:
            assert file in WELL_KNOWN_REGISTRY
            assert "content_type" in WELL_KNOWN_REGISTRY[file]
            assert "description" in WELL_KNOWN_REGISTRY[file]
            assert "rfc" in WELL_KNOWN_REGISTRY[file]

    def test_registry_content_types(self):
        """Test that registry has correct content types."""
        from mcpgateway.routers.well_known import WELL_KNOWN_REGISTRY

        # Most should be text/plain
        text_files = ["robots.txt", "security.txt", "ai.txt", "dnt-policy.txt", "change-password"]

        for file in text_files:
            assert WELL_KNOWN_REGISTRY[file]["content_type"] == "text/plain"
