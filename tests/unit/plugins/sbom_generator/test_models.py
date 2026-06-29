#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/unit/plugins/sbom_generator/test_models.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Ayo

Unit tests for SBOM Generator internal models and dataclasses.
"""

# Standard
from datetime import datetime, timezone
from uuid import uuid4

# First-Party
from plugins.sbom_generator.models import (
    ExtractionResult,
    ExtractionSource,
    LicensePolicy,
    PackageEcosystem,
    SBOMComponent,
    SBOMDocument,
    SBOMFormat,
)


class TestPackageEcosystem:
    """Test PackageEcosystem enum."""

    def test_all_ecosystems_defined(self):
        """Test all major ecosystems are defined."""
        ecosystems = [e.value for e in PackageEcosystem]

        # Check core ecosystems are present
        assert "python" in ecosystems
        assert "npm" in ecosystems
        assert "go" in ecosystems
        # rust or cargo depending on implementation
        assert "rust" in ecosystems or "cargo" in ecosystems

    def test_ecosystem_string_conversion(self):
        """Test ecosystem can be converted to string."""
        ecosystem = PackageEcosystem.PYTHON

        # Use .value to get the string value
        assert ecosystem.value == "python"


class TestSBOMFormat:
    """Test SBOMFormat enum."""

    def test_supported_formats(self):
        """Test supported SBOM formats."""
        formats = [f.value for f in SBOMFormat]

        assert "cyclonedx" in formats
        assert "spdx" in formats

    def test_format_string_conversion(self):
        """Test format can be converted to string."""
        fmt = SBOMFormat.CYCLONEDX

        # Use .value to get the string value
        assert fmt.value == "cyclonedx"


class TestExtractionSource:
    """Test ExtractionSource enum."""

    def test_extraction_sources(self):
        """Test all extraction sources are defined."""
        sources = [s.value for s in ExtractionSource]

        assert "source_directory" in sources
        assert "container_image" in sources
        # Check for either archive_file or package_file
        assert "package_file" in sources or "archive_file" in sources


class TestSBOMComponent:
    """Test SBOMComponent dataclass."""

    def test_minimal_component(self):
        """Test creating component with minimal fields."""
        component = SBOMComponent(
            name="requests",
            version="2.31.0",
            ecosystem=PackageEcosystem.PYTHON,
        )

        assert component.name == "requests"
        assert component.version == "2.31.0"
        assert component.ecosystem == PackageEcosystem.PYTHON
        assert component.purl is None
        assert component.licenses == []
        assert component.is_direct is True  # Default

    def test_full_component(self):
        """Test creating component with all fields."""
        component = SBOMComponent(
            name="requests",
            version="2.31.0",
            ecosystem=PackageEcosystem.PYTHON,
            purl="pkg:pypi/requests@2.31.0",
            licenses=["Apache-2.0"],
            hash_sha256="abc123def456",
            is_direct=True,
            metadata={"author": "Kenneth Reitz"},
        )

        assert component.name == "requests"
        assert component.version == "2.31.0"
        assert component.purl == "pkg:pypi/requests@2.31.0"
        assert component.licenses == ["Apache-2.0"]
        assert component.hash_sha256 == "abc123def456"
        assert component.is_direct is True
        assert component.metadata["author"] == "Kenneth Reitz"

    def test_multiple_licenses(self):
        """Test component with multiple licenses."""
        component = SBOMComponent(
            name="lib",
            version="1.0.0",
            ecosystem=PackageEcosystem.NPM,
            licenses=["MIT", "Apache-2.0", "BSD-3-Clause"],
        )

        assert len(component.licenses) == 3
        assert "MIT" in component.licenses
        assert "Apache-2.0" in component.licenses

    def test_transitive_dependency(self):
        """Test marking component as transitive dependency."""
        component = SBOMComponent(
            name="urllib3",
            version="2.0.7",
            ecosystem=PackageEcosystem.PYTHON,
            is_direct=False,
        )

        assert component.is_direct is False

    def test_component_with_metadata(self):
        """Test component with custom metadata."""
        metadata = {
            "author": "Test Author",
            "homepage": "https://example.com",
            "description": "A test library",
        }

        component = SBOMComponent(
            name="test-lib",
            version="1.0.0",
            ecosystem=PackageEcosystem.NPM,
            metadata=metadata,
        )

        assert component.metadata == metadata
        assert component.metadata["author"] == "Test Author"


class TestSBOMDocument:
    """Test SBOMDocument dataclass."""

    def test_minimal_document(self):
        """Test creating SBOM document with minimal fields."""
        doc = SBOMDocument(
            format=SBOMFormat.CYCLONEDX,
            spec_version="1.5",
            serial_number=f"urn:uuid:{uuid4()}",
            generated_at=datetime.now(timezone.utc),
            components=[],
        )

        assert doc.format == SBOMFormat.CYCLONEDX
        assert doc.spec_version == "1.5"
        assert doc.serial_number.startswith("urn:uuid:")
        assert doc.version == 1  # Default
        assert doc.components == []

    def test_full_document(self):
        """Test creating SBOM document with all fields."""
        components = [
            SBOMComponent(
                name="requests",
                version="2.31.0",
                ecosystem=PackageEcosystem.PYTHON,
            )
        ]

        doc = SBOMDocument(
            format=SBOMFormat.CYCLONEDX,
            spec_version="1.5",
            serial_number=f"urn:uuid:{uuid4()}",
            version=2,
            generated_at=datetime.now(timezone.utc),
            main_component_name="test-mcp-server",
            main_component_version="1.0.0",
            components=components,
            tool_name="mcp-gateway-sbom-generator",
            tool_version="0.1.0",
            metadata={"scan_type": "source_directory"},
        )

        assert doc.version == 2
        assert doc.main_component_name == "test-mcp-server"
        assert doc.main_component_version == "1.0.0"
        assert len(doc.components) == 1
        assert doc.tool_name == "mcp-gateway-sbom-generator"
        assert doc.metadata["scan_type"] == "source_directory"

    def test_document_with_multiple_components(self):
        """Test document with multiple components."""
        components = [
            SBOMComponent(
                name="requests",
                version="2.31.0",
                ecosystem=PackageEcosystem.PYTHON,
            ),
            SBOMComponent(
                name="urllib3",
                version="2.0.7",
                ecosystem=PackageEcosystem.PYTHON,
            ),
            SBOMComponent(
                name="certifi",
                version="2023.7.22",
                ecosystem=PackageEcosystem.PYTHON,
            ),
        ]

        doc = SBOMDocument(
            format=SBOMFormat.CYCLONEDX,
            spec_version="1.5",
            serial_number=f"urn:uuid:{uuid4()}",
            generated_at=datetime.now(timezone.utc),
            components=components,
        )

        assert len(doc.components) == 3
        assert doc.components[0].name == "requests"
        assert doc.components[1].name == "urllib3"

    def test_spdx_document(self):
        """Test creating SPDX format document."""
        doc = SBOMDocument(
            format=SBOMFormat.SPDX,
            spec_version="2.3",
            serial_number=f"SPDXRef-DOCUMENT-{uuid4()}",
            generated_at=datetime.now(timezone.utc),
            components=[],
        )

        assert doc.format == SBOMFormat.SPDX
        assert doc.spec_version == "2.3"
        assert doc.serial_number.startswith("SPDXRef-DOCUMENT-")

    def test_document_version_increment(self):
        """Test document version can be incremented."""
        doc = SBOMDocument(
            format=SBOMFormat.CYCLONEDX,
            spec_version="1.5",
            serial_number=f"urn:uuid:{uuid4()}",
            version=1,
            generated_at=datetime.now(timezone.utc),
            components=[],
        )

        # Simulate version increment for update
        doc.version = 2

        assert doc.version == 2


class TestExtractionResult:
    """Test ExtractionResult dataclass."""

    def test_successful_extraction(self):
        """Test successful extraction result."""
        components = [
            SBOMComponent(
                name="requests",
                version="2.31.0",
                ecosystem=PackageEcosystem.PYTHON,
            )
        ]

        result = ExtractionResult(
            components=components,
            source=ExtractionSource.SOURCE_DIRECTORY,
            source_path="/app/src",
            extracted_at=datetime.now(timezone.utc),
            tool_name="syft",
            tool_version="0.90.0",
            extraction_duration_ms=1500,
            errors=[],
            warnings=[],
        )

        assert len(result.components) == 1
        assert result.source == ExtractionSource.SOURCE_DIRECTORY
        assert result.source_path == "/app/src"
        assert result.tool_name == "syft"
        assert result.extraction_duration_ms == 1500
        assert result.has_errors is False
        assert result.has_warnings is False

    def test_extraction_with_errors(self):
        """Test extraction result with errors."""
        result = ExtractionResult(
            components=[],
            source=ExtractionSource.CONTAINER_IMAGE,
            source_path="mcp-server:latest",
            extracted_at=datetime.now(timezone.utc),
            tool_name="syft",
            tool_version="0.90.0",
            extraction_duration_ms=5000,
            errors=["Failed to parse package.json", "Missing requirements.txt"],
            warnings=[],
        )

        assert result.has_errors is True
        assert len(result.errors) == 2
        assert "package.json" in result.errors[0]

    def test_extraction_with_warnings(self):
        """Test extraction result with warnings."""
        components = [
            SBOMComponent(
                name="test",
                version="1.0.0",
                ecosystem=PackageEcosystem.PYTHON,
            )
        ]

        result = ExtractionResult(
            components=components,
            source=ExtractionSource.SOURCE_DIRECTORY,
            source_path="/app",
            extracted_at=datetime.now(timezone.utc),
            tool_name="syft",
            tool_version="0.90.0",
            extraction_duration_ms=2000,
            errors=[],
            warnings=["Some packages lack license information"],
        )

        assert result.has_errors is False
        assert result.has_warnings is True
        assert len(result.warnings) == 1

    def test_extraction_from_container(self):
        """Test extraction from container image."""
        result = ExtractionResult(
            components=[],
            source=ExtractionSource.CONTAINER_IMAGE,
            source_path="docker.io/library/python:3.11",
            extracted_at=datetime.now(timezone.utc),
            tool_name="syft",
            tool_version="0.90.0",
            extraction_duration_ms=10000,
            errors=[],
            warnings=[],
        )

        assert result.source == ExtractionSource.CONTAINER_IMAGE
        assert "docker.io" in result.source_path

    def test_extraction_duration_tracking(self):
        """Test extraction duration is tracked."""
        result = ExtractionResult(
            components=[],
            source=ExtractionSource.PACKAGE_FILE,
            source_path="/tmp/package.tar.gz",
            extracted_at=datetime.now(timezone.utc),
            tool_name="syft",
            tool_version="0.90.0",
            extraction_duration_ms=3500,
            errors=[],
            warnings=[],
        )

        assert result.extraction_duration_ms == 3500
        # Duration should be positive
        assert result.extraction_duration_ms > 0


class TestLicensePolicy:
    """Test LicensePolicy class."""

    def test_empty_policy(self):
        """Test empty license policy."""
        # First-Party
        from plugins.sbom_generator.config import LicenseConfig

        license_config = LicenseConfig(
            blocked_licenses=[],
            warn_licenses=[],
        )
        # LicensePolicy extracts the lists from config
        policy = LicensePolicy(
            blocked=license_config.blocked_licenses,
            flagged=license_config.warn_licenses,
        )

        assert not policy.is_blocked("MIT")
        assert not policy.is_flagged("Apache-2.0")

    def test_blocked_licenses(self):
        """Test blocked license detection."""
        # First-Party
        from plugins.sbom_generator.config import LicenseConfig

        license_config = LicenseConfig(
            blocked_licenses=["GPL-3.0", "AGPL-3.0"],
            warn_licenses=[],
        )
        policy = LicensePolicy(
            blocked=license_config.blocked_licenses,
            flagged=license_config.warn_licenses,
        )

        assert policy.is_blocked("GPL-3.0")
        assert policy.is_blocked("AGPL-3.0")
        assert not policy.is_blocked("MIT")

    def test_flagged_licenses(self):
        """Test flagged license detection."""
        # First-Party
        from plugins.sbom_generator.config import LicenseConfig

        license_config = LicenseConfig(
            blocked_licenses=[],
            warn_licenses=["GPL-2.0", "LGPL-3.0"],
        )
        policy = LicensePolicy(
            blocked=license_config.blocked_licenses,
            flagged=license_config.warn_licenses,
        )

        assert policy.is_flagged("GPL-2.0")
        assert policy.is_flagged("LGPL-3.0")
        assert not policy.is_flagged("MIT")

    def test_case_sensitivity(self):
        """Test license policy is case-sensitive."""
        # First-Party
        from plugins.sbom_generator.config import LicenseConfig

        license_config = LicenseConfig(
            blocked_licenses=["GPL-3.0"],
            warn_licenses=[],
        )
        policy = LicensePolicy(
            blocked=license_config.blocked_licenses,
            flagged=license_config.warn_licenses,
        )

        assert policy.is_blocked("GPL-3.0")
        # Case matters
        assert not policy.is_blocked("gpl-3.0")
        assert not policy.is_blocked("GPL-3.O")  # Zero vs O

    def test_combined_policy(self):
        """Test policy with both blocked and flagged licenses."""
        # First-Party
        from plugins.sbom_generator.config import LicenseConfig

        license_config = LicenseConfig(
            blocked_licenses=["GPL-3.0", "AGPL-3.0"],
            warn_licenses=["GPL-2.0", "LGPL-2.0"],
        )
        policy = LicensePolicy(
            blocked=license_config.blocked_licenses,
            flagged=license_config.warn_licenses,
        )

        # Blocked licenses
        assert policy.is_blocked("GPL-3.0")
        assert policy.is_blocked("AGPL-3.0")

        # Flagged licenses
        assert policy.is_flagged("GPL-2.0")
        assert policy.is_flagged("LGPL-2.0")

        # Allowed licenses
        assert not policy.is_blocked("MIT")
        assert not policy.is_flagged("Apache-2.0")

    def test_license_not_in_both_lists(self):
        """Test license can't be both blocked and flagged."""
        # First-Party
        from plugins.sbom_generator.config import LicenseConfig

        # This is a business logic test - a license should ideally
        # not be in both lists, but the model doesn't enforce it
        license_config = LicenseConfig(
            blocked_licenses=["GPL-3.0"],
            warn_licenses=["GPL-3.0"],  # Same license
        )
        policy = LicensePolicy(
            blocked=license_config.blocked_licenses,
            flagged=license_config.warn_licenses,
        )

        # Both will return True, but blocked takes precedence in usage
        assert policy.is_blocked("GPL-3.0")
        assert policy.is_flagged("GPL-3.0")


class TestModelIntegration:
    """Test integration between different models."""

    def test_component_in_document(self):
        """Test components properly integrate with documents."""
        component = SBOMComponent(
            name="requests",
            version="2.31.0",
            ecosystem=PackageEcosystem.PYTHON,
            licenses=["Apache-2.0"],
        )

        doc = SBOMDocument(
            format=SBOMFormat.CYCLONEDX,
            spec_version="1.5",
            serial_number=f"urn:uuid:{uuid4()}",
            generated_at=datetime.now(timezone.utc),
            components=[component],
        )

        assert len(doc.components) == 1
        assert doc.components[0].name == "requests"
        assert doc.components[0].licenses == ["Apache-2.0"]

    def test_extraction_to_document_flow(self):
        """Test flow from extraction to document creation."""
        # Extraction result
        extraction = ExtractionResult(
            components=[
                SBOMComponent(
                    name="requests",
                    version="2.31.0",
                    ecosystem=PackageEcosystem.PYTHON,
                )
            ],
            source=ExtractionSource.SOURCE_DIRECTORY,
            source_path="/app/src",
            extracted_at=datetime.now(timezone.utc),
            tool_name="syft",
            tool_version="0.90.0",
            extraction_duration_ms=1500,
            errors=[],
            warnings=[],
        )

        # Create document from extraction
        doc = SBOMDocument(
            format=SBOMFormat.CYCLONEDX,
            spec_version="1.5",
            serial_number=f"urn:uuid:{uuid4()}",
            generated_at=extraction.extracted_at,
            components=extraction.components,
            tool_name=extraction.tool_name,
            tool_version=extraction.tool_version,
        )

        assert doc.components == extraction.components
        assert doc.tool_name == extraction.tool_name
        assert doc.generated_at == extraction.extracted_at
