#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/unit/plugins/sbom_generator/test_source_extractor.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Fionn

Unit tests for source directory dependency extraction.
"""

# Standard
from unittest.mock import AsyncMock, patch

# Third-Party
import pytest

# First-Party
from plugins.sbom_generator.errors import ExtractionError
from plugins.sbom_generator.extraction.source_extractor import (
    _map_ecosystem,
    _parse_components,
    SourceExtractor,
)
from plugins.sbom_generator.models import ExtractionSource, PackageEcosystem


class TestSourceExtractorHelpers:
    """Test helper functions in source extractor."""

    def test_map_ecosystem_known_and_unknown_values(self):
        """Known values map correctly, unknown values become generic."""
        assert _map_ecosystem("go-module") == PackageEcosystem.GO
        assert _map_ecosystem("not-real") == PackageEcosystem.GENERIC

    def test_parse_components_with_valid_purl(self):
        """Valid purl should be preserved and used for ecosystem detection."""
        syft_json = {
            "components": [
                {
                    "name": "serde",
                    "version": "1.0.0",
                    "type": "python",
                    "purl": "pkg:cargo/serde@1.0.0",
                }
            ]
        }

        components = _parse_components(syft_json)

        assert len(components) == 1
        assert components[0].ecosystem == PackageEcosystem.RUST
        assert components[0].purl == "pkg:cargo/serde@1.0.0"

    def test_parse_components_generates_purl_when_missing(self):
        """Missing purl should be generated from package type."""
        syft_json = {
            "components": [
                {
                    "name": "lodash",
                    "version": "4.17.21",
                    "type": "npm",
                    "licenses": [{"name": "MIT"}],
                }
            ]
        }

        components = _parse_components(syft_json)

        assert len(components) == 1
        assert components[0].ecosystem == PackageEcosystem.NPM
        assert components[0].purl == "pkg:npm/lodash@4.17.21"
        assert components[0].licenses == ["MIT"]


class TestSourceExtractor:
    """Test source extractor public behavior."""

    @pytest.mark.parametrize(
        "target,expected",
        [
            ("dir:/any/path", True),
            ("/definitely/not/real", False),
            ("nginx:latest", False),
        ],
    )
    def test_supports_targets(self, tmp_path, target, expected):
        """Source extractor should correctly classify supported targets."""
        extractor = SourceExtractor()

        if target == "/definitely/not/real":
            # Ensure this branch is deterministic and not tied to host filesystem.
            target = str(tmp_path / "missing-dir")

        assert extractor.supports(target) is expected

    def test_supports_existing_directory(self, tmp_path):
        """Existing bare directory paths should be supported."""
        extractor = SourceExtractor()

        assert extractor.supports(str(tmp_path)) is True

    @pytest.mark.asyncio
    async def test_extract_raises_for_missing_directory(self):
        """Extract should fail fast when directory does not exist."""
        extractor = SourceExtractor()

        with pytest.raises(ExtractionError, match="does not exist"):
            await extractor.extract("dir:/no/such/dir")

    @pytest.mark.asyncio
    async def test_extract_success_for_bare_path(self, tmp_path):
        """Bare path should be normalized to dir: when calling Syft."""
        extractor = SourceExtractor(fmt="spdx", timeout=99)
        syft_json = {
            "components": [
                {
                    "name": "requests",
                    "version": "2.31.0",
                    "type": "python",
                }
            ]
        }

        with (
            patch(
                "plugins.sbom_generator.extraction.source_extractor.get_syft_version",
                new=AsyncMock(return_value="1.2.3"),
            ),
            patch(
                "plugins.sbom_generator.extraction.source_extractor.run_syft",
                new=AsyncMock(return_value=syft_json),
            ) as mock_run_syft,
        ):
            result = await extractor.extract(str(tmp_path))

        assert result.source == ExtractionSource.SOURCE_DIRECTORY
        assert result.source_path == str(tmp_path)
        assert result.tool_version == "1.2.3"
        assert result.component_count == 1
        mock_run_syft.assert_awaited_once_with(f"dir:{tmp_path}", fmt="spdx", timeout=99)

    @pytest.mark.asyncio
    async def test_extract_success_for_dir_prefixed_path(self, tmp_path):
        """dir: prefixed path should be passed through to Syft unchanged."""
        extractor = SourceExtractor()
        prefixed_target = f"dir:{tmp_path}"

        with (
            patch(
                "plugins.sbom_generator.extraction.source_extractor.get_syft_version",
                new=AsyncMock(return_value="0.99.0"),
            ),
            patch(
                "plugins.sbom_generator.extraction.source_extractor.run_syft",
                new=AsyncMock(return_value={"components": []}),
            ) as mock_run_syft,
        ):
            result = await extractor.extract(prefixed_target)

        assert result.source_path == str(tmp_path)
        assert result.component_count == 0
        mock_run_syft.assert_awaited_once_with(prefixed_target, fmt="cyclonedx", timeout=300)
