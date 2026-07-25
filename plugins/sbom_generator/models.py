#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/sbom_generator/models.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Ayo

Internal data models for SBOM Generator plugin.
"""

# Standard
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class SBOMFormat(str, Enum):
    """Supported SBOM output formats."""

    CYCLONEDX = "cyclonedx"
    SPDX = "spdx"


class PackageEcosystem(str, Enum):
    """Supported package ecosystems."""

    PYTHON = "python"
    NPM = "npm"
    GO = "go"
    RUST = "rust"
    GENERIC = "generic"


class ExtractionSource(str, Enum):
    """Source types for dependency extraction."""

    CONTAINER_IMAGE = "container_image"
    SOURCE_DIRECTORY = "source_directory"
    PACKAGE_FILE = "package_file"


@dataclass
class SBOMComponent:
    """Represents a single software component (dependency)."""

    name: str
    version: str
    ecosystem: PackageEcosystem
    purl: str | None = None  # Package URL
    licenses: list[str] = field(default_factory=list)
    hash_sha256: str | None = None
    is_direct: bool = True  # Direct vs transitive dependency
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validate component data after initialization."""
        if not self.name:
            raise ValueError("Component name is required")
        if not self.version:
            raise ValueError("Component version is required")


@dataclass
class ExtractionResult:
    """
    Result from dependency extraction process.

    Contains all components found and metadata about the extraction.
    """

    components: list[SBOMComponent]
    source: ExtractionSource
    source_path: str  # Image name or directory path
    extracted_at: datetime = field(default_factory=datetime.utcnow)
    tool_name: str = "syft"
    tool_version: str | None = None
    extraction_duration_ms: int | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def component_count(self) -> int:
        """Return total number of components extracted."""
        return len(self.components)

    @property
    def has_errors(self) -> bool:
        """Return True if extraction had errors."""
        return len(self.errors) > 0

    @property
    def has_warnings(self) -> bool:
        """Return True if extraction had warnings."""
        return len(self.warnings) > 0


@dataclass
class SBOMDocument:
    """Complete SBOM document model."""

    format: SBOMFormat
    spec_version: str
    serial_number: str  # UUID for this SBOM
    version: int = 1  # SBOM document version
    generated_at: datetime = field(default_factory=datetime.utcnow)

    # Main component being described (the MCP server)
    main_component_name: str | None = None
    main_component_version: str | None = None

    # All dependencies
    components: list[SBOMComponent] = field(default_factory=list)

    # Tool that generated the SBOM
    tool_name: str = "mcp-gateway-sbom-generator"
    tool_version: str = "0.1.0"

    # Additional metadata
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def component_count(self) -> int:
        """Return total number of components in SBOM."""
        return len(self.components)

    @property
    def ecosystems(self) -> set[PackageEcosystem]:
        """Return set of all ecosystems found in components."""
        return {component.ecosystem for component in self.components}

    @property
    def licenses(self) -> set[str]:
        """Return set of all licenses found in components."""
        licenses = set()
        for component in self.components:
            licenses.update(component.licenses)
        return licenses

    def get_components_by_ecosystem(self, ecosystem: PackageEcosystem) -> list[SBOMComponent]:
        """
        Get all components from a specific ecosystem.

        Args:
            ecosystem: The package ecosystem to filter by

        Returns:
            List of components from that ecosystem
        """
        return [c for c in self.components if c.ecosystem == ecosystem]

    def get_components_by_license(self, license_id: str) -> list[SBOMComponent]:
        """
        Get all components with a specific license.

        Args:
            license_id: SPDX license identifier

        Returns:
            List of components with that license
        """
        return [c for c in self.components if license_id in c.licenses]


@dataclass
class LicensePolicy:
    """
    License compliance policy configuration.

    Defines which licenses are blocked, flagged, or allowed.
    """

    blocked: list[str] = field(default_factory=list)  # GPL-3.0, AGPL-3.0, etc.
    flagged: list[str] = field(default_factory=list)  # Require manual review
    allowed: list[str] = field(default_factory=list)  # Explicit allowlist

    def is_blocked(self, license_id: str) -> bool:
        """Check if a license is blocked."""
        return license_id in self.blocked

    def is_flagged(self, license_id: str) -> bool:
        """Check if a license requires review."""
        return license_id in self.flagged

    def is_allowed(self, license_id: str) -> bool:
        """Check if a license is explicitly allowed."""
        # If allowlist is empty, everything not blocked is allowed
        if not self.allowed:
            return not self.is_blocked(license_id)
        return license_id in self.allowed

    def validate_licenses(self, licenses: list[str]) -> dict[str, list[str]]:
        """
        Validate a list of licenses against policy.

        Args:
            licenses: List of SPDX license identifiers

        Returns:
            Dict with 'blocked', 'flagged', 'allowed' keys
        """
        result = {
            "blocked": [],
            "flagged": [],
            "allowed": [],
        }

        for license_id in licenses:
            if self.is_blocked(license_id):
                result["blocked"].append(license_id)
            elif self.is_flagged(license_id):
                result["flagged"].append(license_id)
            elif self.is_allowed(license_id):
                result["allowed"].append(license_id)
            else:
                # Unknown license - flag for review if allowlist exists
                if self.allowed:
                    result["flagged"].append(license_id)
                else:
                    result["allowed"].append(license_id)

        return result
