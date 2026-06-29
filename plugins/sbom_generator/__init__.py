#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/sbom_generator/__init__.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Ayo

SBOM Generator Plugin for MCP Gateway.

This plugin generates Software Bill of Materials (SBOM) for MCP servers,
enabling dependency tracking, CVE correlation, and license compliance.
"""

from .sbom_generator import SBOMGeneratorPlugin
from .errors import (
    SBOMGeneratorError,
    ExtractionError,
    GenerationError,
    StorageError,
    ValidationError,
)
from .models import (
    SBOMDocument,
    SBOMComponent,
    ExtractionResult,
)

__all__ = [
    "SBOMGeneratorPlugin",
    "SBOMGeneratorError",
    "ExtractionError",
    "GenerationError",
    "StorageError",
    "ValidationError",
    "SBOMDocument",
    "SBOMComponent",
    "ExtractionResult",
]

__version__ = "0.1.0"
