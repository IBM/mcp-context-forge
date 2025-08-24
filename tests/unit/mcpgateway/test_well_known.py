# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_well_known.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Test cases for well-known URI endpoints.
"""

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


class TestWellKnownDisabled:
    """Test well-known endpoints when disabled."""

    @pytest.fixture
    def client(self):
        """Create a test client for the FastAPI app."""
        return TestClient(app)

    @patch("mcpgateway.routers.well_known.settings")
    def test_well_known_disabled_returns_404(self, mock_settings, client):
        """Test that requests return 404 when well_known_enabled is False."""
        # Configure settings to disable well-known
        mock_settings.well_known_enabled = False

        # Test various well-known files should all return 404
        response = client.get("/.well-known/robots.txt")
        assert response.status_code == 404
        assert "Not found" in response.text

        response = client.get("/.well-known/security.txt")
        assert response.status_code == 404
        assert "Not found" in response.text

        response = client.get("/.well-known/any-file.txt")
        assert response.status_code == 404
        assert "Not found" in response.text


class TestSecurityTxtWithContent:
    """Test security.txt with various content configurations."""

    @pytest.fixture
    def client(self):
        """Create a test client for the FastAPI app."""
        return TestClient(app)

    @patch("mcpgateway.routers.well_known.settings")
    def test_security_txt_enabled_with_empty_content(self, mock_settings, client):
        """Test security.txt enabled but with empty content returns 404."""
        # Configure settings for security.txt enabled with empty content
        mock_settings.well_known_enabled = True
        mock_settings.well_known_security_txt_enabled = True
        mock_settings.well_known_security_txt = ""
        mock_settings.well_known_cache_max_age = 3600

        response = client.get("/.well-known/security.txt")
        assert response.status_code == 404
        assert "security.txt not configured" in response.text

    @patch("mcpgateway.routers.well_known.settings")
    def test_security_txt_enabled_with_none_content(self, mock_settings, client):
        """Test security.txt enabled but with None content returns 404."""
        # Configure settings for security.txt enabled with None content
        mock_settings.well_known_enabled = True
        mock_settings.well_known_security_txt_enabled = True
        mock_settings.well_known_security_txt = None
        mock_settings.well_known_cache_max_age = 3600

        response = client.get("/.well-known/security.txt")
        assert response.status_code == 404
        assert "security.txt not configured" in response.text

    @patch("mcpgateway.routers.well_known.settings")
    def test_security_txt_enabled_with_valid_content(self, mock_settings, client):
        """Test security.txt enabled with valid content returns content."""
        # Configure settings for security.txt enabled with valid content
        mock_settings.well_known_enabled = True
        mock_settings.well_known_security_txt_enabled = True
        mock_settings.well_known_security_txt = "Contact: security@example.com"
        mock_settings.well_known_cache_max_age = 3600

        response = client.get("/.well-known/security.txt")
        assert response.status_code == 200
        assert "Contact: security@example.com" in response.text
        assert "Expires:" in response.text
        assert response.headers["content-type"] == "text/plain; charset=utf-8"
        assert "Cache-Control" in response.headers
        assert "public, max-age=3600" in response.headers["Cache-Control"]


class TestCustomWellKnownFiles:
    """Test custom well-known files functionality."""

    @pytest.fixture
    def client(self):
        """Create a test client for the FastAPI app."""
        return TestClient(app)

    @patch("mcpgateway.routers.well_known.settings")
    def test_custom_well_known_file_known_type(self, mock_settings, client):
        """Test custom well-known file with known content type."""
        # Configure settings with custom file that has a known content type
        mock_settings.well_known_enabled = True
        mock_settings.custom_well_known_files = {
            "ai.txt": "User-agent: *\nDisallow: /private/"
        }
        mock_settings.well_known_cache_max_age = 7200

        response = client.get("/.well-known/ai.txt")
        assert response.status_code == 200
        assert "User-agent: *" in response.text
        assert "Disallow: /private/" in response.text
        assert response.headers["content-type"] == "text/plain; charset=utf-8"
        assert "Cache-Control" in response.headers
        assert "public, max-age=7200" in response.headers["Cache-Control"]

    @patch("mcpgateway.routers.well_known.settings")
    def test_custom_well_known_file_unknown_type(self, mock_settings, client):
        """Test custom well-known file with unknown content type."""
        # Configure settings with custom file that's not in the registry
        mock_settings.well_known_enabled = True
        mock_settings.custom_well_known_files = {
            "custom-file.txt": "This is a custom well-known file"
        }
        mock_settings.well_known_cache_max_age = 1800

        response = client.get("/.well-known/custom-file.txt")
        assert response.status_code == 200
        assert "This is a custom well-known file" in response.text
        assert response.headers["content-type"] == "text/plain; charset=utf-8"
        assert "Cache-Control" in response.headers
        assert "public, max-age=1800" in response.headers["Cache-Control"]


class TestWellKnownAdminEndpoint:
    """Test admin well-known status endpoint."""

    @pytest.fixture
    def auth_client(self):
        """Create a test client with auth dependency override."""
        from mcpgateway.utils.verify_credentials import require_auth
        app.dependency_overrides[require_auth] = lambda: "test_user"
        client = TestClient(app)
        yield client
        app.dependency_overrides.pop(require_auth, None)

    @patch("mcpgateway.routers.well_known.settings")
    def test_admin_well_known_status_basic(self, mock_settings, auth_client):
        """Test admin well-known status endpoint with basic configuration."""
        # Configure basic settings
        mock_settings.well_known_enabled = True
        mock_settings.well_known_security_txt_enabled = False
        mock_settings.custom_well_known_files = {}
        mock_settings.well_known_cache_max_age = 3600

        response = auth_client.get("/admin/well-known")
        assert response.status_code == 200

        data = response.json()
        assert data["enabled"] is True
        assert data["cache_max_age"] == 3600
        assert "configured_files" in data
        assert "supported_files" in data

        # Should always have robots.txt
        configured_files = data["configured_files"]
        robots_file = next((f for f in configured_files if f["path"] == "/.well-known/robots.txt"), None)
        assert robots_file is not None
        assert robots_file["enabled"] is True
        assert robots_file["description"] == "Robot exclusion standard"
        assert robots_file["cache_max_age"] == 3600

    @patch("mcpgateway.routers.well_known.settings")
    def test_admin_well_known_status_with_security_txt(self, mock_settings, auth_client):
        """Test admin well-known status endpoint with security.txt enabled."""
        # Configure settings with security.txt enabled
        mock_settings.well_known_enabled = True
        mock_settings.well_known_security_txt_enabled = True
        mock_settings.custom_well_known_files = {}
        mock_settings.well_known_cache_max_age = 7200

        response = auth_client.get("/admin/well-known")
        assert response.status_code == 200

        data = response.json()
        configured_files = data["configured_files"]

        # Should have security.txt listed
        security_file = next((f for f in configured_files if f["path"] == "/.well-known/security.txt"), None)
        assert security_file is not None
        assert security_file["enabled"] is True
        assert security_file["description"] == "Security contact information"
        assert security_file["cache_max_age"] == 7200

    @patch("mcpgateway.routers.well_known.settings")
    def test_admin_well_known_status_with_custom_files(self, mock_settings, auth_client):
        """Test admin well-known status endpoint with custom files."""
        # Configure settings with custom files
        mock_settings.well_known_enabled = True
        mock_settings.well_known_security_txt_enabled = False
        mock_settings.custom_well_known_files = {
            "custom1.txt": "Custom content 1",
            "custom2.txt": "Custom content 2"
        }
        mock_settings.well_known_cache_max_age = 1800

        response = auth_client.get("/admin/well-known")
        assert response.status_code == 200

        data = response.json()
        configured_files = data["configured_files"]

        # Should have custom files listed
        custom1_file = next((f for f in configured_files if f["path"] == "/.well-known/custom1.txt"), None)
        assert custom1_file is not None
        assert custom1_file["enabled"] is True
        assert custom1_file["description"] == "Custom well-known file"
        assert custom1_file["cache_max_age"] == 1800

        custom2_file = next((f for f in configured_files if f["path"] == "/.well-known/custom2.txt"), None)
        assert custom2_file is not None
        assert custom2_file["enabled"] is True
        assert custom2_file["description"] == "Custom well-known file"
        assert custom2_file["cache_max_age"] == 1800


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
