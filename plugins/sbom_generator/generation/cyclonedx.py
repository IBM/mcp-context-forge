#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/sbom_generator/generation/cyclonedx.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Fionn Gavin

Generates CycloneDX 1.5 JSON SBOM documents.
Spec: https://cyclonedx.org/specification/overview/
"""

# Future
from __future__ import annotations

# Standard
from datetime import datetime, timezone
import json
from typing import Any
import uuid

# Local
from ..errors import GenerationError
from ..models import (
    ExtractionResult,
    SBOMComponent,
    SBOMDocument,
    SBOMFormat,
)
from .base import BaseGenerator


class CycloneDXGenerator(BaseGenerator):
    """Produces CycloneDX 1.5 JSON SBOM documents.

    Args:
        spec_version: CycloneDX specification version string (default ``"1.5"``).
        tool_name: Generator tool name embedded in SBOM metadata.
        tool_version: Generator tool version embedded in SBOM metadata.
    """

    def __init__(
        self,
        spec_version: str = "1.5",
        tool_name: str = "mcp-gateway-sbom-generator",
        tool_version: str = "0.1.0",
    ):
        """Initialise with optional spec version and tool metadata."""
        self.spec_version = spec_version
        self.tool_name = tool_name
        self.tool_version = tool_version

    def generate(
        self,
        extraction_result: ExtractionResult,
        server_name: str | None = None,
        server_version: str | None = None,
    ) -> SBOMDocument:
        """Build a CycloneDX SBOMDocument from *extraction_result*.

        Args:
            extraction_result: Components from dependency extraction.
            server_name: MCP server name used as the main component.
            server_version: MCP server version.

        Returns:
            A populated :class:`~plugins.sbom_generator.models.SBOMDocument`.

        Raises:
            GenerationError: If document construction fails.
        """
        try:
            return SBOMDocument(
                format=SBOMFormat.CYCLONEDX,
                spec_version=self.spec_version,
                serial_number=str(uuid.uuid4()),
                version=1,
                generated_at=datetime.now(timezone.utc),
                main_component_name=server_name,
                main_component_version=server_version,
                components=extraction_result.components,
                tool_name=self.tool_name,
                tool_version=self.tool_version,
                metadata={
                    "source_type": extraction_result.source.value,
                    "source_path": extraction_result.source_path,
                    "extraction_tool_version": extraction_result.tool_version,
                },
            )
        except Exception as exc:
            raise GenerationError(
                f"CycloneDX document generation failed: {exc}",
                details={"spec_version": self.spec_version},
            ) from exc

    def serialise(self, sbom_doc: SBOMDocument) -> str:
        """Serialise *sbom_doc* to a CycloneDX 1.5 JSON string.

        Args:
            sbom_doc: SBOM document to serialise.

        Returns:
            Indented JSON string conforming to CycloneDX 1.5.

        Raises:
            GenerationError: If JSON serialisation fails.
        """
        try:
            payload = self._to_cyclonedx_dict(sbom_doc)
            return json.dumps(payload, indent=2, default=str)
        except Exception as exc:
            raise GenerationError(
                f"CycloneDX serialisation failed: {exc}",
            ) from exc

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _to_cyclonedx_dict(self, sbom_doc: SBOMDocument) -> dict[str, Any]:
        """Convert an SBOMDocument to a CycloneDX-compliant dict."""
        metadata: dict[str, Any] = {
            "timestamp": sbom_doc.generated_at.isoformat(),
            "tools": [{"name": sbom_doc.tool_name, "version": sbom_doc.tool_version}],
        }

        if sbom_doc.main_component_name:
            metadata["component"] = {
                "type": "application",
                "name": sbom_doc.main_component_name,
                "version": sbom_doc.main_component_version or "",
            }

        return {
            "bomFormat": "CycloneDX",
            "specVersion": sbom_doc.spec_version,
            "serialNumber": f"urn:uuid:{sbom_doc.serial_number}",
            "version": sbom_doc.version,
            "metadata": metadata,
            "components": [self._component_to_dict(c) for c in sbom_doc.components],
        }

    @staticmethod
    def _component_to_dict(component: SBOMComponent) -> dict[str, Any]:
        """Convert a single SBOMComponent to a CycloneDX component dict."""
        result: dict[str, Any] = {
            "type": "library",
            "name": component.name,
            "version": component.version,
        }
        if component.purl:
            result["purl"] = component.purl
        if component.licenses:
            result["licenses"] = [{"id": lic} for lic in component.licenses]
        if component.hash_sha256:
            result["hashes"] = [{"alg": "SHA-256", "content": component.hash_sha256}]
        return result
