#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/sbom_generator/generation/base.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Fionn Gavin

Abstract base class for SBOM document generators.
"""

# Future
from __future__ import annotations

# Standard
from abc import ABC, abstractmethod

# Local
from ..models import ExtractionResult, SBOMDocument


class BaseGenerator(ABC):
    """Abstract base class all SBOM generators must implement.

    Subclasses:
        - CycloneDXGenerator — produces CycloneDX 1.5 JSON
        - SPDXGenerator      — produces SPDX 2.3 JSON
    """

    @abstractmethod
    def generate(
        self,
        extraction_result: ExtractionResult,
        server_name: str | None = None,
        server_version: str | None = None,
    ) -> SBOMDocument:
        """Build an :class:`~plugins.sbom_generator.models.SBOMDocument` from
        an extraction result.

        Args:
            extraction_result: Components discovered during extraction.
            server_name: Name of the assessed MCP server (used as the main
                component name in the SBOM metadata).
            server_version: Version of the assessed MCP server.

        Returns:
            A fully populated :class:`~plugins.sbom_generator.models.SBOMDocument`.

        Raises:
            GenerationError: If the document cannot be constructed.
        """

    @abstractmethod
    def serialise(self, sbom_doc: SBOMDocument) -> str:
        """Serialise *sbom_doc* to a JSON string in the generator's format.

        Args:
            sbom_doc: The SBOM document to serialise.

        Returns:
            A JSON string conforming to the target SBOM specification.

        Raises:
            GenerationError: If serialisation fails.
        """
