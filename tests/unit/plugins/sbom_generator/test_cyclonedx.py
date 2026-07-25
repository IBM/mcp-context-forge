#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/unit/plugins/sbom_generator/test_cyclonedx.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Fionn

Unit tests for CycloneDX generator.
"""

# Standard
import json

# Third-Party
import pytest

# First-Party
from plugins.sbom_generator.errors import GenerationError
from plugins.sbom_generator.generation.cyclonedx import CycloneDXGenerator
from plugins.sbom_generator.models import PackageEcosystem, SBOMComponent, SBOMFormat


class TestCycloneDXGeneratorInit:
    """Test CycloneDX generator initialization."""

    def test_default_init(self):
        """Default constructor values should match expected defaults."""
        generator = CycloneDXGenerator()

        assert generator.spec_version == "1.5"
        assert generator.tool_name == "mcp-gateway-sbom-generator"
        assert generator.tool_version == "0.1.0"

    def test_custom_init(self):
        """Custom constructor values should be retained."""
        generator = CycloneDXGenerator(
            spec_version="1.6",
            tool_name="custom-tool",
            tool_version="9.9.9",
        )

        assert generator.spec_version == "1.6"
        assert generator.tool_name == "custom-tool"
        assert generator.tool_version == "9.9.9"


class TestCycloneDXGenerate:
    """Test SBOMDocument generation."""

    def test_generate_success(self, extraction_result):
        """Generate should create a valid CycloneDX SBOM document."""
        generator = CycloneDXGenerator()

        doc = generator.generate(
            extraction_result,
            server_name="demo-server",
            server_version="1.2.3",
        )

        assert doc.format == SBOMFormat.CYCLONEDX
        assert doc.spec_version == "1.5"
        assert doc.main_component_name == "demo-server"
        assert doc.main_component_version == "1.2.3"
        assert len(doc.components) == len(extraction_result.components)
        assert doc.metadata["source_type"] == extraction_result.source.value
        assert doc.metadata["source_path"] == extraction_result.source_path
        assert doc.metadata["extraction_tool_version"] == extraction_result.tool_version

    def test_generate_raises_generation_error_on_failure(self):
        """Generate should wrap underlying errors as GenerationError."""
        generator = CycloneDXGenerator()

        with pytest.raises(GenerationError, match="CycloneDX document generation failed"):
            generator.generate(None)  # type: ignore[arg-type]


class TestCycloneDXComponentConversion:
    """Test component dict conversion for CycloneDX payload."""

    def test_component_to_dict_with_optional_fields(self):
        """PURL, licenses and hashes should be emitted when present."""
        component = SBOMComponent(
            name="requests",
            version="2.31.0",
            ecosystem=PackageEcosystem.PYTHON,
            purl="pkg:pypi/requests@2.31.0",
            licenses=["Apache-2.0", "MIT"],
            hash_sha256="abc123",
        )

        data = CycloneDXGenerator._component_to_dict(component)

        assert data["name"] == "requests"
        assert data["version"] == "2.31.0"
        assert data["purl"] == "pkg:pypi/requests@2.31.0"
        assert data["licenses"] == [{"id": "Apache-2.0"}, {"id": "MIT"}]
        assert data["hashes"] == [{"alg": "SHA-256", "content": "abc123"}]

    def test_component_to_dict_without_optional_fields(self):
        """Optional fields should be omitted when absent."""
        component = SBOMComponent(
            name="core",
            version="1.0.0",
            ecosystem=PackageEcosystem.GENERIC,
        )

        data = CycloneDXGenerator._component_to_dict(component)

        assert "purl" not in data
        assert "licenses" not in data
        assert "hashes" not in data


class TestCycloneDXSerialisation:
    """Test CycloneDX payload generation and serialization."""

    def test_to_cyclonedx_dict_structure(self, sbom_document):
        """Internal dict should match required CycloneDX top-level structure."""
        generator = CycloneDXGenerator()

        payload = generator._to_cyclonedx_dict(sbom_document)

        assert payload["bomFormat"] == "CycloneDX"
        assert payload["specVersion"] == sbom_document.spec_version
        assert payload["version"] == sbom_document.version
        assert payload["serialNumber"].startswith("urn:uuid:")
        assert isinstance(payload["components"], list)
        assert "metadata" in payload

    def test_to_cyclonedx_dict_includes_main_component(self, sbom_document):
        """Main component block should be present when name is provided."""
        generator = CycloneDXGenerator()

        payload = generator._to_cyclonedx_dict(sbom_document)

        assert "component" in payload["metadata"]
        assert payload["metadata"]["component"]["name"] == sbom_document.main_component_name

    def test_to_cyclonedx_dict_omits_main_component_when_missing(self, sbom_document):
        """Main component block should be omitted when no name is available."""
        sbom_document.main_component_name = None
        generator = CycloneDXGenerator()

        payload = generator._to_cyclonedx_dict(sbom_document)

        assert "component" not in payload["metadata"]

    def test_serialise_success(self, sbom_document):
        """Serialise should return valid CycloneDX JSON string."""
        generator = CycloneDXGenerator()

        raw_json = generator.serialise(sbom_document)
        parsed = json.loads(raw_json)

        assert parsed["bomFormat"] == "CycloneDX"
        assert parsed["specVersion"] == sbom_document.spec_version

    def test_serialise_wraps_internal_error(self, sbom_document, monkeypatch):
        """Errors from dict conversion should be wrapped in GenerationError."""
        generator = CycloneDXGenerator()

        def _explode(_doc):
            raise RuntimeError("boom")

        monkeypatch.setattr(generator, "_to_cyclonedx_dict", _explode)

        with pytest.raises(GenerationError, match="CycloneDX serialisation failed"):
            generator.serialise(sbom_document)
