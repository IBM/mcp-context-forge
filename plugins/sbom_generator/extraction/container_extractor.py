#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/sbom_generator/extraction/container_extractor.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Fionn Gavin

Extracts dependencies from a container image using Syft.
"""

# Future
from __future__ import annotations

# Standard
import logging
import re
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

# Regex for a plausible container image reference
_IMAGE_RE = re.compile(
    r"^([a-zA-Z0-9._\-/:]+)"  # registry / repo / name
    r"(:[a-zA-Z0-9._\-]+)?$"  # optional tag
)

# Map Syft type strings → PackageEcosystem
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
    """Convert Syft CycloneDX/SPDX JSON output into SBOMComponent list."""
    components: list[SBOMComponent] = []

    # CycloneDX layout
    raw_components = syft_json.get("components", [])

    for item in raw_components:
        name = item.get("name", "").strip()
        version = item.get("version", "").strip()
        if not name or not version:
            continue

        purl = item.get("purl")
        syft_type = item.get("type", "library")

        # Derive ecosystem from purl type when present
        ecosystem = PackageEcosystem.GENERIC
        if purl and is_valid_purl(purl):
            purl_type = purl.split(":")[1].split("/")[0] if ":" in purl else ""
            reverse = {
                v: k
                for k, v in {
                    PackageEcosystem.PYTHON: "pypi",
                    PackageEcosystem.NPM: "npm",
                    PackageEcosystem.GO: "golang",
                    PackageEcosystem.RUST: "cargo",
                }.items()
            }
            ecosystem = reverse.get(purl_type, PackageEcosystem.GENERIC)
        else:
            ecosystem = _map_ecosystem(syft_type)
            if not purl:
                purl = build_purl(name, version, ecosystem)

        # Extract SPDX license IDs
        licenses: list[str] = []
        for lic in item.get("licenses", []):
            if isinstance(lic, dict):
                lid = lic.get("id") or lic.get("name", "")
            else:
                lid = str(lic)
            if lid:
                licenses.append(lid)

        # SHA-256 hash if present
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


class ContainerExtractor(BaseExtractor):
    """Extracts dependencies from a container image via Syft.

    Args:
        fmt: SBOM format to request from Syft (``"cyclonedx"`` or ``"spdx"``).
        timeout: Seconds before the Syft subprocess is killed.
    """

    def __init__(self, fmt: str = "cyclonedx", timeout: int = 300):
        """Initialise with optional format and timeout."""
        self.fmt = fmt
        self.timeout = timeout

    def supports(self, target: str) -> bool:
        """Return ``True`` for strings that look like container image references.

        Examples:
            >>> ContainerExtractor().supports("nginx:latest")
            True
            >>> ContainerExtractor().supports("ghcr.io/org/image:v1.0")
            True
            >>> ContainerExtractor().supports("dir:/some/path")
            False
        """
        if target.startswith("dir:"):
            return False
        return bool(_IMAGE_RE.match(target))

    async def extract(self, target: str) -> ExtractionResult:
        """Extract dependencies from the container image *target*.

        Args:
            target: Container image reference (e.g. ``"nginx:latest"``).

        Returns:
            Populated :class:`~plugins.sbom_generator.models.ExtractionResult`.

        Raises:
            ExtractionError: If Syft fails or output cannot be parsed.
        """
        if not self.supports(target):
            raise ExtractionError(
                f"ContainerExtractor does not support target {target!r}. " "Expected a container image reference.",
                details={"target": target},
            )

        logger.info("Extracting dependencies from container image: %s", target)
        start = time.monotonic()

        syft_version = await get_syft_version()
        syft_json = await run_syft(target, fmt=self.fmt, timeout=self.timeout)
        components = _parse_components(syft_json)

        elapsed_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "Container extraction complete: %d components in %dms",
            len(components),
            elapsed_ms,
        )

        return ExtractionResult(
            components=components,
            source=ExtractionSource.CONTAINER_IMAGE,
            source_path=target,
            tool_name="syft",
            tool_version=syft_version,
            extraction_duration_ms=elapsed_ms,
        )
