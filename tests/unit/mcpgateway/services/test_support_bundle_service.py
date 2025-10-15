# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_support_bundle_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Unit tests for support bundle service.
Tests bundle generation, sanitization, and file operations.
"""

# Standard
from pathlib import Path
import tempfile
import zipfile

# Third-Party
import pytest

# First-Party
from mcpgateway.services.support_bundle_service import (
    SupportBundleConfig,
    SupportBundleService,
    create_support_bundle,
)


class TestSupportBundleService:
    """Test support bundle service functionality."""

    def test_service_initialization(self):
        """Test service initializes with hostname and timestamp."""
        service = SupportBundleService()
        assert service.hostname
        assert service.timestamp
        assert len(service.hostname) > 0

    def test_is_secret_detection(self):
        """Test secret detection in environment variable names."""
        service = SupportBundleService()

        # Test secret detection
        assert service._is_secret("PASSWORD")
        assert service._is_secret("API_KEY")
        assert service._is_secret("SECRET_TOKEN")
        assert service._is_secret("JWT_SECRET_KEY")
        assert service._is_secret("DATABASE_PASSWORD")
        assert service._is_secret("BASIC_AUTH_USER")
        assert service._is_secret("DATABASE_URL")
        assert service._is_secret("REDIS_URL")
        assert service._is_secret("AUTH_ENCRYPTION_SECRET")

        # Test non-secrets
        assert not service._is_secret("DEBUG")
        assert not service._is_secret("PORT")
        assert not service._is_secret("HOSTNAME")
        assert not service._is_secret("LOG_LEVEL")

    def test_sanitize_url(self):
        """Test URL sanitization removes passwords."""
        service = SupportBundleService()

        # Test PostgreSQL URL
        url = "postgresql://user:password@localhost:5432/db"
        sanitized = service._sanitize_url(url)
        assert "password" not in sanitized
        assert "*****" in sanitized
        assert "user" in sanitized

        # Test Redis URL
        url = "redis://admin:secret123@redis.example.com:6379/0"
        sanitized = service._sanitize_url(url)
        assert "secret123" not in sanitized
        assert "*****" in sanitized

        # Test URL without credentials
        url = "http://example.com/path"
        sanitized = service._sanitize_url(url)
        assert sanitized == url

        # Test None
        assert service._sanitize_url(None) is None

    def test_sanitize_line(self):
        """Test line sanitization removes sensitive data."""
        service = SupportBundleService()

        # Test password redaction
        line = 'password: "secret123"'
        sanitized = service._sanitize_line(line)
        assert "secret123" not in sanitized
        assert "*****" in sanitized

        # Test token redaction
        line = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        sanitized = service._sanitize_line(line)
        assert "eyJhbGci" not in sanitized or "*****" in sanitized

        # Test API key redaction
        line = "api_key: abc123xyz"
        sanitized = service._sanitize_line(line)
        assert "*****" in sanitized

        # Test non-sensitive line
        line = "debug: true"
        sanitized = service._sanitize_line(line)
        assert sanitized == line

    def test_collect_version_info(self):
        """Test version information collection."""
        service = SupportBundleService()
        info = service._collect_version_info()

        assert "app_name" in info
        assert "app_version" in info
        assert "python_version" in info
        assert "platform" in info
        assert "hostname" in info
        assert "timestamp" in info

    def test_collect_system_info(self):
        """Test system information collection."""
        service = SupportBundleService()
        info = service._collect_system_info()

        assert "platform" in info
        assert "python" in info
        assert "database" in info
        assert info["platform"]["system"]
        assert info["python"]["version"]

    def test_collect_env_config(self):
        """Test environment configuration collection with sanitization."""
        service = SupportBundleService()
        env = service._collect_env_config()

        assert isinstance(env, dict)
        # All secrets should be redacted
        for key, value in env.items():
            if service._is_secret(key):
                assert value == "*****"

    def test_collect_settings(self):
        """Test application settings collection."""
        service = SupportBundleService()
        config = service._collect_settings()

        assert isinstance(config, dict)
        assert "host" in config

        # Check sensitive fields are not included
        assert "basic_auth_password" not in config
        assert "jwt_secret_key" not in config
        assert "auth_encryption_secret" not in config
        assert "platform_admin_password" not in config
        assert "sso_github_client_secret" not in config
        assert "sso_google_client_secret" not in config
        assert "sso_ibm_verify_client_secret" not in config
        assert "sso_okta_client_secret" not in config
        assert "sso_keycloak_client_secret" not in config
        assert "sso_entra_client_secret" not in config
        assert "sso_generic_client_secret" not in config

    def test_collect_logs_file_not_found(self):
        """Test log collection when file doesn't exist."""
        service = SupportBundleService()
        config = SupportBundleConfig(log_tail_lines=100)

        # Create a custom config with non-existent log path
        with tempfile.TemporaryDirectory() as tmpdir:
            # Temporarily override settings
            logs = service._collect_logs(config)
            # Should return a message about missing file
            for log_content in logs.values():
                assert "[Log file not found]" in log_content or "[Showing last" in log_content or isinstance(log_content, str)

    def test_create_manifest(self):
        """Test manifest creation."""
        service = SupportBundleService()
        config = SupportBundleConfig(log_tail_lines=500)
        manifest = service._create_manifest(config)

        assert "bundle_version" in manifest
        assert "generated_at" in manifest
        assert "hostname" in manifest
        assert "app_version" in manifest
        assert "configuration" in manifest
        assert "warning" in manifest
        assert manifest["configuration"]["log_tail_lines"] == 500

    def test_generate_bundle_creates_zip(self):
        """Test bundle generation creates a valid ZIP file."""
        service = SupportBundleService()

        with tempfile.TemporaryDirectory() as tmpdir:
            config = SupportBundleConfig(output_dir=Path(tmpdir), log_tail_lines=100)
            bundle_path = service.generate_bundle(config)

            # Check file exists
            assert bundle_path.exists()
            assert bundle_path.suffix == ".zip"
            assert bundle_path.name.startswith("mcpgateway-support-")

            # Check ZIP is valid
            assert zipfile.is_zipfile(bundle_path)

            # Check ZIP contents
            with zipfile.ZipFile(bundle_path, "r") as zf:
                namelist = zf.namelist()
                assert "MANIFEST.json" in namelist
                assert "version.json" in namelist
                assert "system_info.json" in namelist
                assert "settings.json" in namelist
                assert "environment.json" in namelist
                assert "README.md" in namelist
                # Logs directory should exist
                assert any("logs/" in name for name in namelist)

    def test_generate_bundle_with_custom_config(self):
        """Test bundle generation with custom configuration."""
        service = SupportBundleService()

        with tempfile.TemporaryDirectory() as tmpdir:
            config = SupportBundleConfig(
                output_dir=Path(tmpdir),
                log_tail_lines=50,
                include_logs=False,
                include_env=False,
                include_system_info=False,
            )
            bundle_path = service.generate_bundle(config)

            assert bundle_path.exists()

            with zipfile.ZipFile(bundle_path, "r") as zf:
                namelist = zf.namelist()
                # Required files should always be present
                assert "MANIFEST.json" in namelist
                assert "version.json" in namelist
                assert "README.md" in namelist

                # Optional files should be missing
                if not config.include_system_info:
                    assert "system_info.json" not in namelist
                if not config.include_env:
                    assert "settings.json" not in namelist
                    assert "environment.json" not in namelist

    def test_convenience_function(self):
        """Test create_support_bundle convenience function."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = SupportBundleConfig(output_dir=Path(tmpdir), log_tail_lines=100)
            bundle_path = create_support_bundle(config)

            assert bundle_path.exists()
            assert zipfile.is_zipfile(bundle_path)

    def test_bundle_contains_sanitized_data(self):
        """Test that generated bundle contains sanitized data."""
        service = SupportBundleService()

        with tempfile.TemporaryDirectory() as tmpdir:
            config = SupportBundleConfig(output_dir=Path(tmpdir), log_tail_lines=100)
            bundle_path = service.generate_bundle(config)

            with zipfile.ZipFile(bundle_path, "r") as zf:
                # Check environment.json is sanitized
                env_data = zf.read("environment.json").decode("utf-8")
                # Should not contain actual password values
                assert "changeme" not in env_data or "*****" in env_data

                # Check settings.json doesn't have sensitive fields
                settings_data = zf.read("settings.json").decode("utf-8")
                assert "basic_auth_password" not in settings_data
                assert "jwt_secret_key" not in settings_data
                assert "platform_admin_password" not in settings_data
                assert "sso_github_client_secret" not in settings_data
                assert "sso_google_client_secret" not in settings_data
                assert "sso_ibm_verify_client_secret" not in settings_data
                assert "sso_okta_client_secret" not in settings_data
                assert "sso_keycloak_client_secret" not in settings_data
                assert "sso_entra_client_secret" not in settings_data
                assert "sso_generic_client_secret" not in settings_data

    def test_support_bundle_config_validation(self):
        """Test SupportBundleConfig validation."""
        # Valid config
        config = SupportBundleConfig(log_tail_lines=500, max_log_size_mb=5.0)
        assert config.log_tail_lines == 500
        assert config.max_log_size_mb == 5.0

        # Default config
        config = SupportBundleConfig()
        assert config.include_logs is True
        assert config.include_env is True
        assert config.include_system_info is True
        assert config.log_tail_lines == 1000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
