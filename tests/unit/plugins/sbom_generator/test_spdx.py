#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/unit/plugins/sbom_generator/test_spdx.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Fionn

Unit tests for SPDX generator.
"""

# Standard
import json

# Third-Party
import pytest

# First-Party
from plugins.sbom_generator.errors import GenerationError
from plugins.sbom_generator.generation.spdx import _spdx_id, SPDXGenerator
from plugins.sbom_generator.models import PackageEcosystem, SBOMComponent, SBOMFormat


class TestSpdxIdHelper:
    """Test SPDX ID generation helper."""

    def test_spdx_id_sanitizes_invalid_characters(self):
        """Invalid characters should be replaced with dashes."""
        value = _spdx_id("pkg/name+with spaces", "1.0.0-beta+1")

        assert value.startswith("SPDXRef-")
        assert "/" not in value
        assert " " not in value
        assert "+" not in value


class TestSPDXGeneratorInit:
    """Test SPDX generator initialization."""

    def test_default_init(self):
        """Default constructor values should match expected defaults."""
        generator = SPDXGenerator()

        assert generator.tool_name == "mcp-gateway-sbom-generator"
        assert generator.tool_version == "0.1.0"

    def test_custom_init(self):
        """Custom constructor values should be retained."""
        generator = SPDXGenerator(
            tool_name="custom-generator",
            tool_version="2.0.0",
        )

        assert generator.tool_name == "custom-generator"
        assert generator.tool_version == "2.0.0"


class TestSPDXGenerate:
    """Test SBOMDocument generation."""

    def test_generate_success(self, extraction_result):
        """Generate should create a valid SPDX SBOM document."""
        generator = SPDXGenerator()

        doc = generator.generate(
            extraction_result,
            server_name="demo-server",
            server_version="2.1.0",
        )

        assert doc.format == SBOMFormat.SPDX
        assert doc.spec_version == "SPDX-2.3"
        assert doc.main_component_name == "demo-server"
        assert doc.main_component_version == "2.1.0"
        assert len(doc.components) == len(extraction_result.components)
        assert doc.metadata["source_type"] == extraction_result.source.value
        assert doc.metadata["source_path"] == extraction_result.source_path

    def test_generate_raises_generation_error_on_failure(self):
        """Generate should wrap underlying errors as GenerationError."""
        generator = SPDXGenerator()

        with pytest.raises(GenerationError, match="SPDX document generation failed"):
            generator.generate(None)  # type: ignore[arg-type]


class TestSPDXComponentConversion:
    """Test component conversion to SPDX package data."""

    def test_component_to_package_with_metadata(self):
        """PURL, license and checksum fields should be included when present."""
        component = SBOMComponent(
            name="requests",
            version="2.31.0",
            ecosystem=PackageEcosystem.PYTHON,
            purl="pkg:pypi/requests@2.31.0",
            licenses=["Apache-2.0", "MIT"],
            hash_sha256="abc123",
        )

        package = SPDXGenerator._component_to_package(component)

        assert package["name"] == "requests"
        assert package["versionInfo"] == "2.31.0"
        assert package["licenseConcluded"] == "Apache-2.0 AND MIT"
        assert package["licenseInfoFromFiles"] == ["Apache-2.0", "MIT"]
        assert package["externalRefs"][0]["referenceLocator"] == "pkg:pypi/requests@2.31.0"
        assert package["checksums"] == [{"algorithm": "SHA256", "checksumValue": "abc123"}]

    def test_component_to_package_without_licenses(self):
        """Missing licenses should default to NOASSERTION fields."""
        component = SBOMComponent(
            name="core",
            version="1.0.0",
            ecosystem=PackageEcosystem.GENERIC,
        )

        package = SPDXGenerator._component_to_package(component)

        assert package["licenseConcluded"] == "NOASSERTION"
        assert package["licenseInfoFromFiles"] == ["NOASSERTION"]
        assert "externalRefs" not in package
        assert "checksums" not in package


class TestSPDXSerialisation:
    """Test SPDX payload generation and serialization."""

    def test_to_spdx_dict_structure(self, sbom_document):
        """Internal dict should contain required SPDX top-level fields."""
        generator = SPDXGenerator()

        payload = generator._to_spdx_dict(sbom_document)

        assert payload["spdxVersion"] == "SPDX-2.3"
        assert payload["SPDXID"] == "SPDXRef-DOCUMENT"
        assert payload["dataLicense"] == "CC0-1.0"
        assert isinstance(payload["packages"], list)
        assert isinstance(payload["relationships"], list)
        assert payload["documentNamespace"].endswith(sbom_document.serial_number)

    def test_to_spdx_dict_uses_unknown_name_when_missing(self, sbom_document):
        """Document name should fallback to unknown when main component missing."""
        sbom_document.main_component_name = None
        generator = SPDXGenerator()

        payload = generator._to_spdx_dict(sbom_document)

        assert payload["name"] == "unknown"

    def test_serialise_success(self, sbom_document):
        """Serialise should return valid SPDX JSON string."""
        generator = SPDXGenerator()

        raw_json = generator.serialise(sbom_document)
        parsed = json.loads(raw_json)

        assert parsed["spdxVersion"] == "SPDX-2.3"
        assert parsed["SPDXID"] == "SPDXRef-DOCUMENT"

    def test_serialise_wraps_internal_error(self, sbom_document, monkeypatch):
        """Errors from dict conversion should be wrapped in GenerationError."""
        generator = SPDXGenerator()

        def _explode(_doc):
            raise RuntimeError("boom")

        monkeypatch.setattr(generator, "_to_spdx_dict", _explode)

        with pytest.raises(GenerationError, match="SPDX serialisation failed"):
            generator.serialise(sbom_document)
