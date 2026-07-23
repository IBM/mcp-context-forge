#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/sbom_generator/extraction/source_extractor.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Fionn Gavin

Extracts dependencies from a source directory using Syft.
Syft is invoked with the ``dir:<path>`` target syntax.
"""

# Future
from __future__ import annotations

# Standard
import logging
import os
import time
from typing import Any

# Local
from ..errors import ExtractionError
from ..models import (
    ExtractionResult,
    ExtractionSource,
    PackageEcosystem,
    SBOMComponent,
)
from ..utils.purl_generator import build_purl, is_valid_purl
from .base import BaseExtractor
from .syft_wrapper import get_syft_version, run_syft

logger = logging.getLogger(__name__)

_SYFT_TYPE_MAP: dict[str, PackageEcosystem] = {
    "python": PackageEcosystem.PYTHON,
    "pip": PackageEcosystem.PYTHON,
    "npm": PackageEcosystem.NPM,
    "node-module": PackageEcosystem.NPM,
    "go-module": PackageEcosystem.GO,
    "rust-crate": PackageEcosystem.RUST,
    "cargo": PackageEcosystem.RUST,
}


def _map_ecosystem(syft_type: str) -> PackageEcosystem:
    return _SYFT_TYPE_MAP.get(syft_type.lower(), PackageEcosystem.GENERIC)


def _parse_components(syft_json: dict[str, Any]) -> list[SBOMComponent]:
    """Convert Syft JSON output into SBOMComponent list."""
    components: list[SBOMComponent] = []

    for item in syft_json.get("components", []):
        name = item.get("name", "").strip()
        version = item.get("version", "").strip()
        if not name or not version:
            continue

        purl = item.get("purl")
        syft_type = item.get("type", "library")

        ecosystem = PackageEcosystem.GENERIC
        if purl and is_valid_purl(purl):
            purl_type = purl.split(":")[1].split("/")[0] if ":" in purl else ""
            reverse = {
                "pypi": PackageEcosystem.PYTHON,
                "npm": PackageEcosystem.NPM,
                "golang": PackageEcosystem.GO,
                "cargo": PackageEcosystem.RUST,
            }
            ecosystem = reverse.get(purl_type, PackageEcosystem.GENERIC)
        else:
            ecosystem = _map_ecosystem(syft_type)
            if not purl:
                purl = build_purl(name, version, ecosystem)

        licenses: list[str] = []
        for lic in item.get("licenses", []):
            if isinstance(lic, dict):
                lid = lic.get("id") or lic.get("name", "")
            else:
                lid = str(lic)
            if lid:
                licenses.append(lid)

        hash_sha256: str | None = None
        for h in item.get("hashes", []):
            if isinstance(h, dict) and h.get("alg", "").upper() == "SHA-256":
                hash_sha256 = h.get("content")
                break

        components.append(
            SBOMComponent(
                name=name,
                version=version,
                ecosystem=ecosystem,
                purl=purl,
                licenses=licenses,
                hash_sha256=hash_sha256,
            )
        )

    return components


class SourceExtractor(BaseExtractor):
    """Extracts dependencies from a source directory via Syft.

    Args:
        fmt: SBOM format (``"cyclonedx"`` or ``"spdx"``).
        timeout: Seconds before the Syft subprocess is killed.
    """

    def __init__(self, fmt: str = "cyclonedx", timeout: int = 300):
        """Initialise with optional format and timeout."""
        self.fmt = fmt
        self.timeout = timeout

    def supports(self, target: str) -> bool:
        """Return ``True`` for ``dir:`` prefixed paths and bare existing directories.

        Examples:
            >>> SourceExtractor().supports("dir:/some/path")
            True
            >>> SourceExtractor().supports("/tmp")
            True
            >>> SourceExtractor().supports("nginx:latest")
            False
        """
        if target.startswith("dir:"):
            return True
        # Bare path pointing at an existing directory
        return os.path.isdir(target)

    async def extract(self, target: str) -> ExtractionResult:
        """Extract dependencies from the source directory *target*.

        Args:
            target: Directory path, optionally prefixed with ``dir:``.

        Returns:
            Populated :class:`~plugins.sbom_generator.models.ExtractionResult`.

        Raises:
            ExtractionError: If the directory does not exist or Syft fails.
        """
        # Normalise to bare path for existence check
        bare_path = target[len("dir:") :] if target.startswith("dir:") else target
        if not os.path.isdir(bare_path):
            raise ExtractionError(
                f"Source directory does not exist: {bare_path!r}",
                details={"target": target},
            )

        # Always pass Syft the dir: prefix
        syft_target = target if target.startswith("dir:") else f"dir:{target}"

        logger.info("Extracting dependencies from source directory: %s", bare_path)
        start = time.monotonic()

        syft_version = await get_syft_version()
        syft_json = await run_syft(syft_target, fmt=self.fmt, timeout=self.timeout)
        components = _parse_components(syft_json)

        elapsed_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "Source extraction complete: %d components in %dms",
            len(components),
            elapsed_ms,
        )

        return ExtractionResult(
            components=components,
            source=ExtractionSource.SOURCE_DIRECTORY,
            source_path=bare_path,
            tool_name="syft",
            tool_version=syft_version,
            extraction_duration_ms=elapsed_ms,
        )
