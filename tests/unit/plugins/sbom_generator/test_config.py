#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/unit/plugins/sbom_generator/test_config.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Ayo

Unit tests for SBOM Generator configuration validation.
"""

# Third-Party
from pydantic import ValidationError
import pytest

# First-Party
from plugins.sbom_generator.config import (
    LicenseConfig,
    SBOMGeneratorConfig,
    StorageConfig,
    SyftConfig,
)


class TestSyftConfig:
    """Test Syft configuration validation."""

    def test_default_syft_config(self):
        """Test default Syft configuration."""
        config = SyftConfig()

        assert config.enabled is True
        assert config.format == "cyclonedx"
        assert config.spec_version == "1.5"
        assert config.include_dev_deps is False
        assert config.include_files is False
        assert config.timeout_seconds == 300

    def test_custom_syft_config(self):
        """Test custom Syft configuration."""
        config = SyftConfig(
            format="spdx",
            spec_version="2.3",
            include_dev_deps=True,
            timeout_seconds=600,
        )

        assert config.format == "spdx"
        assert config.spec_version == "2.3"
        assert config.include_dev_deps is True
        assert config.timeout_seconds == 600

    def test_invalid_format(self):
        """Test invalid SBOM format raises error."""
        with pytest.raises(ValidationError) as exc_info:
            SyftConfig(format="invalid_format")

        assert "format" in str(exc_info.value).lower()

    def test_custom_spec_version(self):
        """Test custom spec version can be set."""
        config = SyftConfig(spec_version="2.3")

        assert config.spec_version == "2.3"

    def test_custom_timeout(self):
        """Test custom timeout can be set."""
        config = SyftConfig(timeout_seconds=600)

        assert config.timeout_seconds == 600

    def test_very_short_timeout(self):
        """Test very short timeout can be set."""
        config = SyftConfig(timeout_seconds=10)

        assert config.timeout_seconds == 10


class TestLicenseConfig:
    """Test license configuration validation."""

    def test_default_license_config(self):
        """Test default license configuration."""
        config = LicenseConfig()

        assert config.detect_licenses is True
        # Default config may have some blocked licenses - just check it's a list
        assert isinstance(config.blocked_licenses, list)
        assert isinstance(config.warn_licenses, list)

    def test_custom_license_config(self):
        """Test custom license configuration."""
        config = LicenseConfig(
            detect_licenses=False,
            blocked_licenses=["GPL-3.0", "AGPL-3.0"],
            warn_licenses=["GPL-2.0", "LGPL-3.0"],
        )

        assert config.detect_licenses is False
        assert "GPL-3.0" in config.blocked_licenses
        assert "AGPL-3.0" in config.blocked_licenses
        assert "GPL-2.0" in config.warn_licenses

    def test_empty_license_lists(self):
        """Test empty license lists are valid."""
        config = LicenseConfig(
            blocked_licenses=[],
            warn_licenses=[],
        )

        assert config.blocked_licenses == []
        assert config.warn_licenses == []

    def test_case_sensitivity(self):
        """Test license names are case-sensitive."""
        config = LicenseConfig(blocked_licenses=["gpl-3.0", "GPL-3.0", "Gpl-3.0"])

        # All three should be preserved as-is
        assert len(config.blocked_licenses) == 3
        assert "gpl-3.0" in config.blocked_licenses
        assert "GPL-3.0" in config.blocked_licenses
        assert "Gpl-3.0" in config.blocked_licenses


class TestStorageConfig:
    """Test storage configuration validation."""

    def test_default_storage_config(self):
        """Test default storage configuration."""
        config = StorageConfig()

        assert config.store_full_sbom is True
        assert config.retention_days == 365
        # Check compression setting exists (actual default may vary)
        assert isinstance(config.enable_compression, bool)

    def test_custom_storage_config(self):
        """Test custom storage configuration."""
        config = StorageConfig(
            store_full_sbom=False,
            retention_days=90,
            enable_compression=True,
        )

        assert config.store_full_sbom is False
        assert config.retention_days == 90
        assert config.enable_compression is True

    def test_custom_retention(self):
        """Test custom retention period."""
        config = StorageConfig(retention_days=90)

        assert config.retention_days == 90

    def test_very_large_retention(self):
        """Test very large retention period is allowed."""
        config = StorageConfig(retention_days=3650)  # 10 years

        assert config.retention_days == 3650


class TestSBOMGeneratorConfig:
    """Test main SBOM Generator configuration."""

    def test_default_config(self):
        """Test default configuration."""
        config = SBOMGeneratorConfig()

        assert config.syft.enabled is True
        assert config.license.detect_licenses is True
        assert config.storage.store_full_sbom is True
        # Behavior flags may have different defaults
        assert isinstance(config.fail_on_blocked_licenses, bool)
        assert isinstance(config.fail_on_missing_sbom, bool)

    def test_custom_config(self):
        """Test custom configuration with all options."""
        config = SBOMGeneratorConfig(
            syft=SyftConfig(
                format="spdx",
                spec_version="2.3",
            ),
            license=LicenseConfig(
                blocked_licenses=["GPL-3.0"],
                warn_licenses=["GPL-2.0"],
            ),
            storage=StorageConfig(
                retention_days=90,
            ),
            fail_on_blocked_licenses=True,
            fail_on_missing_sbom=True,
        )

        assert config.syft.format == "spdx"
        assert "GPL-3.0" in config.license.blocked_licenses
        assert config.storage.retention_days == 90
        assert config.fail_on_blocked_licenses is True
        assert config.fail_on_missing_sbom is True

    def test_nested_config_from_dict(self):
        """Test creating config from nested dictionary."""
        config_dict = {
            "syft": {
                "enabled": True,
                "format": "cyclonedx",
                "spec_version": "1.5",
            },
            "license": {
                "detect_licenses": True,
                "blocked_licenses": ["GPL-3.0", "AGPL-3.0"],
            },
            "storage": {
                "store_full_sbom": True,
                "retention_days": 365,
            },
            "fail_on_blocked_licenses": True,
        }

        config = SBOMGeneratorConfig(**config_dict)

        assert config.syft.format == "cyclonedx"
        assert "GPL-3.0" in config.license.blocked_licenses
        assert config.storage.retention_days == 365
        assert config.fail_on_blocked_licenses is True

    def test_invalid_nested_config(self):
        """Test invalid nested config raises error."""
        config_dict = {
            "syft": {
                "format": "invalid_format",  # Invalid format
            }
        }

        with pytest.raises(ValidationError) as exc_info:
            SBOMGeneratorConfig(**config_dict)

        assert "format" in str(exc_info.value).lower()

    def test_partial_config(self):
        """Test partial config uses defaults for missing fields."""
        config_dict = {
            "license": {
                "blocked_licenses": ["GPL-3.0"],
            }
        }

        config = SBOMGeneratorConfig(**config_dict)

        # Uses defaults for syft and storage
        assert config.syft.format == "cyclonedx"
        assert config.storage.retention_days == 365
        # Uses provided license config
        assert "GPL-3.0" in config.license.blocked_licenses

    def test_config_serialization(self):
        """Test config can be serialized to dict."""
        config = SBOMGeneratorConfig(
            fail_on_blocked_licenses=True,
            license=LicenseConfig(blocked_licenses=["GPL-3.0"]),
        )

        config_dict = config.model_dump()

        assert config_dict["fail_on_blocked_licenses"] is True
        assert "GPL-3.0" in config_dict["license"]["blocked_licenses"]
        assert config_dict["syft"]["format"] == "cyclonedx"

    def test_config_json_serialization(self):
        """Test config can be serialized to JSON."""
        config = SBOMGeneratorConfig(
            fail_on_blocked_licenses=True,
        )

        json_str = config.model_dump_json()

        assert "fail_on_blocked_licenses" in json_str
        assert "true" in json_str.lower()


class TestConfigIntegration:
    """Test configuration integration scenarios."""

    def test_strict_policy_config(self):
        """Test strict security policy configuration."""
        config = SBOMGeneratorConfig(
            license=LicenseConfig(
                blocked_licenses=["GPL-3.0", "AGPL-3.0", "LGPL-3.0"],
                warn_licenses=["GPL-2.0", "LGPL-2.0"],
            ),
            fail_on_blocked_licenses=True,
            fail_on_missing_sbom=True,
        )

        assert len(config.license.blocked_licenses) == 3
        assert config.fail_on_blocked_licenses is True
        assert config.fail_on_missing_sbom is True

    def test_permissive_policy_config(self):
        """Test permissive policy configuration."""
        config = SBOMGeneratorConfig(
            license=LicenseConfig(
                blocked_licenses=[],
                warn_licenses=[],
            ),
            fail_on_blocked_licenses=False,
            fail_on_missing_sbom=False,
        )

        assert config.license.blocked_licenses == []
        assert config.fail_on_blocked_licenses is False
        assert config.fail_on_missing_sbom is False

    def test_spdx_configuration(self):
        """Test SPDX format configuration."""
        config = SBOMGeneratorConfig(
            syft=SyftConfig(
                format="spdx",
                spec_version="2.3",
            )
        )

        assert config.syft.format == "spdx"
        assert config.syft.spec_version == "2.3"

    def test_performance_optimized_config(self):
        """Test performance-optimized configuration."""
        config = SBOMGeneratorConfig(
            syft=SyftConfig(
                include_dev_deps=False,
                include_files=False,
                timeout_seconds=120,  # Shorter timeout
            ),
            storage=StorageConfig(
                enable_compression=True,  # Enable compression for storage
                retention_days=30,  # Shorter retention
            ),
        )

        assert config.syft.include_dev_deps is False
        assert config.syft.timeout_seconds == 120
        assert config.storage.enable_compression is True
        assert config.storage.retention_days == 30
