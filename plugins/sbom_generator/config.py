#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/sbom_generator/config.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Ayo
"""

# Standard
from typing import List

# Third-Party
from pydantic import BaseModel, Field


class SyftConfig(BaseModel):
    """Syft configuration for SBOM generation.

    Attributes:
        enabled: Whether Syft is enabled.
        format: Output format (e.g., cyclonedx, spdx).
        spec_version: Specification version (e.g., 1.5).
        include_dev_deps: Whether to include development dependencies.
        include_files: Whether to include file information in the SBOM.
        timeout_seconds: Maximum time allowed for SBOM generation.
    """

    enabled: bool = True
    format: str = Field(default="cyclonedx", pattern="^(cyclonedx|spdx)$")
    spec_version: str = "1.5"
    include_dev_deps: bool = False
    include_files: bool = False
    timeout_seconds: int = 300


class LicenseConfig(BaseModel):
    """License detection configuration.

    Attributes:

    """

    detect_licenses: bool = True
    blocked_licenses: List[str] = Field(
        default_factory=lambda: [
            "GPL-3.0",
            "AGPL-3.0",
            "GPL-3.0-only",
            "GPL-3.0-or-later",
        ]
    )
    warn_licenses: List[str] = Field(
        default_factory=lambda: [
            "GPL-2.0",
            "LGPL-3.0",
        ]
    )


class StorageConfig(BaseModel):
    """SBOM storage configuration.

    Attributes:
        store_full_sbom: Whether to store the full SBOM or just metadata.
        retention_days: Number of days to retain SBOM data.
        enable_compression: Whether to compress stored SBOMs to save space.
    """

    store_full_sbom: bool = True
    retention_days: int = 365
    enable_compression: bool = True


class SBOMGeneratorConfig(BaseModel):
    """Configuration for the SBOM Generator Plugin.

    Attributes:
        syft: Syft configuration for SBOM generation.
        license: License detection configuration.
        storage: SBOM storage configuration.
        fail_on_blocked_licenses: Whether to fail the build if blocked licenses are detected.
        fail_on_missing_sbom: Whether to fail the build if SBOM generation fails or results
    """

    syft: SyftConfig = Field(default_factory=SyftConfig)
    license: LicenseConfig = Field(default_factory=LicenseConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)

    fail_on_blocked_licenses: bool = True
    fail_on_missing_sbom: bool = False
