#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/unit/plugins/sbom_generator/test_container_extractor.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Fionn

Unit tests for container dependency extraction.
"""

# Standard
from unittest.mock import AsyncMock, patch

# Third-Party
import pytest

# First-Party
from plugins.sbom_generator.errors import ExtractionError
from plugins.sbom_generator.extraction.container_extractor import (
    _map_ecosystem,
    _parse_components,
    ContainerExtractor,
)
from plugins.sbom_generator.models import ExtractionSource, PackageEcosystem


class TestContainerExtractorHelpers:
    """Test helper functions in container extractor."""

    def test_map_ecosystem_known_value(self):
        """Known Syft package type maps to expected ecosystem."""
        assert _map_ecosystem("python") == PackageEcosystem.PYTHON
        assert _map_ecosystem("npm") == PackageEcosystem.NPM

    def test_map_ecosystem_unknown_value(self):
        """Unknown Syft package type defaults to generic."""
        assert _map_ecosystem("unknown-type") == PackageEcosystem.GENERIC

    def test_parse_components_extracts_expected_fields(self):
        """Parser should extract component fields including license and hash."""
        syft_json = {
            "components": [
                {
                    "name": "requests",
                    "version": "2.31.0",
                    "type": "python",
                    "licenses": [{"id": "Apache-2.0"}],
                    "hashes": [{"alg": "SHA-256", "content": "abc123"}],
                }
            ]
        }

        components = _parse_components(syft_json)

        assert len(components) == 1
        assert components[0].name == "requests"
        assert components[0].version == "2.31.0"
        assert components[0].ecosystem == PackageEcosystem.PYTHON
        assert components[0].licenses == ["Apache-2.0"]
        assert components[0].hash_sha256 == "abc123"
        assert components[0].purl == "pkg:pypi/requests@2.31.0"

    def test_parse_components_skips_invalid_rows(self):
        """Rows without name or version should be ignored."""
        syft_json = {
            "components": [
                {"name": "", "version": "1.0.0"},
                {"name": "valid", "version": "1.0.0", "type": "python"},
                {"name": "missing-version", "version": ""},
            ]
        }

        components = _parse_components(syft_json)

        assert len(components) == 1
        assert components[0].name == "valid"

    def test_parse_components_uses_valid_purl_ecosystem(self):
        """If a valid purl is present, ecosystem is derived from purl type."""
        syft_json = {
            "components": [
                {
                    "name": "left-pad",
                    "version": "1.3.0",
                    "type": "python",
                    "purl": "pkg:npm/left-pad@1.3.0",
                }
            ]
        }

        components = _parse_components(syft_json)

        assert len(components) == 1
        assert components[0].ecosystem == PackageEcosystem.NPM


class TestContainerExtractor:
    """Test container extractor public behavior."""

    @pytest.mark.parametrize(
        "target,expected",
        [
            ("nginx:latest", True),
            ("ghcr.io/org/image:v1", True),
            ("docker.io/library/python:3.11", True),
            ("dir:/tmp/project", False),
            ("", False),
        ],
    )
    def test_supports_targets(self, target, expected):
        """Container extractor should correctly classify supported targets."""
        extractor = ContainerExtractor()

        assert extractor.supports(target) is expected

    @pytest.mark.asyncio
    async def test_extract_raises_for_unsupported_target(self):
        """Unsupported target should raise ExtractionError before calling Syft."""
        extractor = ContainerExtractor()

        with pytest.raises(ExtractionError, match="does not support target"):
            await extractor.extract("dir:/tmp/project")

    @pytest.mark.asyncio
    async def test_extract_success(self):
        """Successful extraction should return normalized ExtractionResult."""
        extractor = ContainerExtractor(fmt="cyclonedx", timeout=123)
        syft_json = {
            "components": [
                {
                    "name": "urllib3",
                    "version": "2.0.7",
                    "type": "python",
                    "licenses": ["MIT"],
                }
            ]
        }

        with (
            patch(
                "plugins.sbom_generator.extraction.container_extractor.get_syft_version",
                new=AsyncMock(return_value="1.0.0"),
            ),
            patch(
                "plugins.sbom_generator.extraction.container_extractor.run_syft",
                new=AsyncMock(return_value=syft_json),
            ) as mock_run_syft,
        ):
            result = await extractor.extract("nginx:latest")

        assert result.source == ExtractionSource.CONTAINER_IMAGE
        assert result.source_path == "nginx:latest"
        assert result.tool_name == "syft"
        assert result.tool_version == "1.0.0"
        assert result.component_count == 1
        assert result.components[0].name == "urllib3"
        assert result.components[0].ecosystem == PackageEcosystem.PYTHON
        mock_run_syft.assert_awaited_once_with("nginx:latest", fmt="cyclonedx", timeout=123)
