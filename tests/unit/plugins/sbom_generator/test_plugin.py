#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/unit/plugins/sbom_generator/test_plugin.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Ayo
"""

# Standard
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

# Third-Party
import pytest

# First-Party
from mcpgateway.plugins.framework import PluginViolationError  # ← Changed import
from plugins.sbom_generator import SBOMGeneratorPlugin
from plugins.sbom_generator.errors import (
    ExtractionError,
    GenerationError,
    StorageError,
    ValidationError,
)
from plugins.sbom_generator.models import (
    PackageEcosystem,
    SBOMComponent,
    SBOMDocument,
    SBOMFormat,
)


class TestPluginInitialization:
    """Test plugin initialization and configuration."""

    def test_init_with_default_config(self, plugin_config):
        """Test plugin initializes with default configuration."""
        plugin = SBOMGeneratorPlugin(plugin_config)

        assert plugin.name == "sbom_generator"
        assert plugin.config.version == "0.1.0"
        assert plugin.plugin_config.syft.format == "cyclonedx"
        assert plugin.plugin_config.syft.spec_version == "1.5"

    def test_init_with_custom_config(self, plugin_config):
        """Test plugin initializes with custom configuration."""
        plugin_config.config["syft"]["format"] = "spdx"
        plugin_config.config["syft"]["spec_version"] = "2.3"

        plugin = SBOMGeneratorPlugin(plugin_config)

        assert plugin.plugin_config.syft.format == "spdx"
        assert plugin.plugin_config.syft.spec_version == "2.3"

    def test_init_with_invalid_config(self, plugin_config):
        """Test plugin raises error with invalid configuration."""
        plugin_config.config["syft"]["format"] = "invalid_format"

        with pytest.raises(ValidationError):
            SBOMGeneratorPlugin(plugin_config)

    def test_license_policy_initialization(self, plugin_config):
        """Test license policy is properly initialized."""
        plugin = SBOMGeneratorPlugin(plugin_config)

        assert plugin.license_policy.is_blocked("GPL-3.0")
        assert plugin.license_policy.is_blocked("AGPL-3.0")
        assert plugin.license_policy.is_flagged("GPL-2.0")
        assert not plugin.license_policy.is_blocked("MIT")


class TestLicenseValidation:
    """Test license validation logic."""

    def test_validate_licenses_all_allowed(self, sbom_plugin):
        """Test validation with all allowed licenses."""
        sbom = SBOMDocument(
            format=SBOMFormat.CYCLONEDX,
            spec_version="1.5",
            serial_number=f"urn:uuid:{uuid4()}",
            generated_at=datetime.now(timezone.utc),
            components=[
                SBOMComponent(
                    name="test",
                    version="1.0.0",
                    ecosystem=PackageEcosystem.PYTHON,
                    licenses=["MIT", "Apache-2.0"],
                )
            ],
        )

        result = sbom_plugin._validate_licenses(sbom)

        assert len(result["blocked"]) == 0
        assert len(result["allowed"]) == 2
        assert "MIT" in result["allowed"]
        assert "Apache-2.0" in result["allowed"]

    def test_validate_licenses_blocked(self, sbom_plugin):
        """Test validation with blocked licenses."""
        sbom = SBOMDocument(
            format=SBOMFormat.CYCLONEDX,
            spec_version="1.5",
            serial_number=f"urn:uuid:{uuid4()}",
            generated_at=datetime.now(timezone.utc),
            components=[
                SBOMComponent(
                    name="copyleft-lib",
                    version="1.0.0",
                    ecosystem=PackageEcosystem.PYTHON,
                    licenses=["GPL-3.0"],
                )
            ],
        )

        result = sbom_plugin._validate_licenses(sbom)

        assert len(result["blocked"]) == 1
        assert "GPL-3.0" in result["blocked"]

    def test_validate_licenses_flagged(self, sbom_plugin):
        """Test validation with flagged licenses."""
        sbom = SBOMDocument(
            format=SBOMFormat.CYCLONEDX,
            spec_version="1.5",
            serial_number=f"urn:uuid:{uuid4()}",
            generated_at=datetime.now(timezone.utc),
            components=[
                SBOMComponent(
                    name="lib",
                    version="1.0.0",
                    ecosystem=PackageEcosystem.PYTHON,
                    licenses=["GPL-2.0"],
                )
            ],
        )

        result = sbom_plugin._validate_licenses(sbom)

        assert len(result["flagged"]) == 1
        assert "GPL-2.0" in result["flagged"]

    def test_validate_licenses_mixed(self, sbom_plugin):
        """Test validation with mixed license types."""
        sbom = SBOMDocument(
            format=SBOMFormat.CYCLONEDX,
            spec_version="1.5",
            serial_number=f"urn:uuid:{uuid4()}",
            generated_at=datetime.now(timezone.utc),
            components=[
                SBOMComponent(
                    name="lib1",
                    version="1.0.0",
                    ecosystem=PackageEcosystem.PYTHON,
                    licenses=["MIT"],
                ),
                SBOMComponent(
                    name="lib2",
                    version="1.0.0",
                    ecosystem=PackageEcosystem.PYTHON,
                    licenses=["GPL-3.0"],
                ),
                SBOMComponent(
                    name="lib3",
                    version="1.0.0",
                    ecosystem=PackageEcosystem.PYTHON,
                    licenses=["GPL-2.0"],
                ),
            ],
        )

        result = sbom_plugin._validate_licenses(sbom)

        assert "MIT" in result["allowed"]
        assert "GPL-3.0" in result["blocked"]
        assert "GPL-2.0" in result["flagged"]


class TestAssessmentPostScanHook:
    """Test assessment_post_scan hook execution."""

    @pytest.mark.asyncio
    async def test_successful_sbom_generation(self, sbom_plugin, plugin_context, assessment_payload, sbom_document):
        """Test successful SBOM generation flow."""
        with (
            patch.object(sbom_plugin, "_extract_dependencies", new_callable=AsyncMock) as mock_extract,
            patch.object(sbom_plugin, "_generate_sbom", new_callable=AsyncMock) as mock_generate,
            patch.object(sbom_plugin, "_store_sbom", new_callable=AsyncMock) as mock_store,
        ):

            mock_extract.return_value = MagicMock(
                components=sbom_document.components,
                has_errors=False,
                errors=[],
            )
            mock_generate.return_value = sbom_document
            mock_store.return_value = str(uuid4())

            result = await sbom_plugin.assessment_post_scan(plugin_context, assessment_payload)

            assert "sbom_id" in result
            assert result["component_count"] == len(sbom_document.components)
            assert result["format"] == "cyclonedx"
            assert len(result["licenses"]["blocked"]) == 0

            mock_extract.assert_called_once()
            mock_generate.assert_called_once()
            mock_store.assert_called_once()

    @pytest.mark.asyncio
    async def test_blocked_license_raises_violation(self, sbom_plugin, plugin_context, assessment_payload, blocked_license_sbom):
        """Test that blocked licenses raise PluginViolationError."""
        with patch.object(sbom_plugin, "_extract_dependencies", new_callable=AsyncMock) as mock_extract, patch.object(sbom_plugin, "_generate_sbom", new_callable=AsyncMock) as mock_generate:

            mock_extract.return_value = MagicMock(
                components=blocked_license_sbom.components,
                has_errors=False,
                errors=[],
            )
            mock_generate.return_value = blocked_license_sbom

            # ← FIXED: Catch PluginViolationError (Exception)
            with pytest.raises(PluginViolationError) as exc_info:
                await sbom_plugin.assessment_post_scan(plugin_context, assessment_payload)

            # Check the violation object
            assert "blocked licenses" in str(exc_info.value.message).lower()
            assert exc_info.value.violation is not None
            assert "GPL-3.0" in exc_info.value.violation.details["blocked_licenses"]

    @pytest.mark.asyncio
    async def test_extraction_error_handling(self, sbom_plugin, plugin_context, assessment_payload):
        """Test handling of extraction errors."""
        with patch.object(sbom_plugin, "_extract_dependencies", new_callable=AsyncMock) as mock_extract:

            mock_extract.side_effect = ExtractionError("Syft extraction failed", {"exit_code": 1})

            result = await sbom_plugin.assessment_post_scan(plugin_context, assessment_payload)

            assert "error" in result
            assert result["error"] == "extraction_failed"

    @pytest.mark.asyncio
    async def test_extraction_error_with_fail_on_missing(self, plugin_config, plugin_context, assessment_payload):
        """Test extraction error raises violation when fail_on_missing_sbom=True."""
        plugin_config.config["fail_on_missing_sbom"] = True
        plugin = SBOMGeneratorPlugin(plugin_config)

        with patch.object(plugin, "_extract_dependencies", new_callable=AsyncMock) as mock_extract:

            mock_extract.side_effect = ExtractionError("Extraction failed")

            # ← FIXED: Catch PluginViolationError
            with pytest.raises(PluginViolationError):
                await plugin.assessment_post_scan(plugin_context, assessment_payload)

    @pytest.mark.asyncio
    async def test_generation_error_handling(self, sbom_plugin, plugin_context, assessment_payload, extraction_result):
        """Test handling of generation errors."""
        with patch.object(sbom_plugin, "_extract_dependencies", new_callable=AsyncMock) as mock_extract, patch.object(sbom_plugin, "_generate_sbom", new_callable=AsyncMock) as mock_generate:

            mock_extract.return_value = extraction_result
            mock_generate.side_effect = GenerationError("Invalid SBOM format")

            result = await sbom_plugin.assessment_post_scan(plugin_context, assessment_payload)

            assert "error" in result
            assert result["error"] == "generation_failed"

    @pytest.mark.asyncio
    async def test_storage_error_raises_violation(self, sbom_plugin, plugin_context, assessment_payload, sbom_document):
        """Test that storage errors always raise violations."""
        with (
            patch.object(sbom_plugin, "_extract_dependencies", new_callable=AsyncMock) as mock_extract,
            patch.object(sbom_plugin, "_generate_sbom", new_callable=AsyncMock) as mock_generate,
            patch.object(sbom_plugin, "_store_sbom", new_callable=AsyncMock) as mock_store,
        ):

            mock_extract.return_value = MagicMock(
                components=sbom_document.components,
                has_errors=False,
            )
            mock_generate.return_value = sbom_document
            mock_store.side_effect = StorageError("Database connection failed")

            # ← FIXED: Catch PluginViolationError
            with pytest.raises(PluginViolationError):
                await sbom_plugin.assessment_post_scan(plugin_context, assessment_payload)

    @pytest.mark.asyncio
    async def test_missing_server_id_raises_error(self, sbom_plugin, plugin_context):
        """Test that missing server_id in payload raises error."""
        payload = {"server_name": "test"}

        with pytest.raises(ValueError, match="server_id required"):
            await sbom_plugin.assessment_post_scan(plugin_context, payload)


class TestHealthCheck:
    """Test plugin health check."""

    @pytest.mark.asyncio
    async def test_health_check_success(self, sbom_plugin):
        """Test successful health check."""
        result = await sbom_plugin.health_check()

        assert result["status"] == "healthy"
        assert result["plugin"] == "sbom_generator"  # ← FIXED
        assert result["version"] == "0.1.0"
        assert result["config"]["format"] == "cyclonedx"

    @pytest.mark.asyncio
    async def test_health_check_failure(self, sbom_plugin, monkeypatch):
        """Test health check handles errors gracefully."""

        # ← FIXED: Mock to actually cause an error
        def raise_error(*args, **kwargs):
            raise RuntimeError("Config error")

        monkeypatch.setattr(sbom_plugin.plugin_config, "syft", property(raise_error))

        result = await sbom_plugin.health_check()

        assert result["status"] == "unhealthy"
        assert result["plugin"] == "sbom_generator"  # ← FIXED
        assert "error" in result


class TestCleanup:
    """Test plugin cleanup."""

    @pytest.mark.asyncio
    async def test_cleanup(self, sbom_plugin):
        """Test plugin cleanup runs without error."""
        await sbom_plugin.cleanup()


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_components_validation(self, sbom_plugin):
        """Test validation with empty component list."""
        sbom = SBOMDocument(
            format=SBOMFormat.CYCLONEDX,
            spec_version="1.5",
            serial_number=f"urn:uuid:{uuid4()}",
            generated_at=datetime.now(timezone.utc),
            components=[],
        )

        result = sbom_plugin._validate_licenses(sbom)

        assert len(result["blocked"]) == 0
        assert len(result["flagged"]) == 0
        assert len(result["allowed"]) == 0

    def test_component_without_licenses(self, sbom_plugin):
        """Test validation with components that have no licenses."""
        sbom = SBOMDocument(
            format=SBOMFormat.CYCLONEDX,
            spec_version="1.5",
            serial_number=f"urn:uuid:{uuid4()}",
            generated_at=datetime.now(timezone.utc),
            components=[
                SBOMComponent(
                    name="unlicensed-lib",
                    version="1.0.0",
                    ecosystem=PackageEcosystem.PYTHON,
                    licenses=[],
                )
            ],
        )

        result = sbom_plugin._validate_licenses(sbom)

        assert len(result["blocked"]) == 0
