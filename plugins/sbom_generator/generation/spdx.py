#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/sbom_generator/generation/spdx.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Fionn Gavin

Generates SPDX 2.3 JSON SBOM documents.
Spec: https://spdx.github.io/spdx-spec/v2.3/
"""

# Future
from __future__ import annotations

# Standard
from datetime import datetime, timezone
import json
import re
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

# SPDX element IDs must match [idstring] pattern
_SAFE_ID = re.compile(r"[^a-zA-Z0-9.\-]")


def _spdx_id(name: str, version: str) -> str:
    """Build a safe SPDX element ID from name + version."""
    raw = f"SPDXRef-{name}-{version}"
    return _SAFE_ID.sub("-", raw)


class SPDXGenerator(BaseGenerator):
    """Produces SPDX 2.3 JSON SBOM documents.

    Args:
        tool_name: Generator tool name embedded in SBOM metadata.
        tool_version: Generator tool version embedded in SBOM metadata.
    """

    def __init__(
        self,
        tool_name: str = "mcp-gateway-sbom-generator",
        tool_version: str = "0.1.0",
    ):
        """Initialise with optional tool metadata."""
        self.tool_name = tool_name
        self.tool_version = tool_version

    def generate(
        self,
        extraction_result: ExtractionResult,
        server_name: str | None = None,
        server_version: str | None = None,
    ) -> SBOMDocument:
        """Build an SPDX SBOMDocument from *extraction_result*.

        Args:
            extraction_result: Components from dependency extraction.
            server_name: MCP server name used as the document name.
            server_version: MCP server version.

        Returns:
            A populated :class:`~plugins.sbom_generator.models.SBOMDocument`.

        Raises:
            GenerationError: If document construction fails.
        """
        try:
            return SBOMDocument(
                format=SBOMFormat.SPDX,
                spec_version="SPDX-2.3",
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
                f"SPDX document generation failed: {exc}",
            ) from exc

    def serialise(self, sbom_doc: SBOMDocument) -> str:
        """Serialise *sbom_doc* to an SPDX 2.3 JSON string.

        Args:
            sbom_doc: SBOM document to serialise.

        Returns:
            Indented JSON string conforming to SPDX 2.3.

        Raises:
            GenerationError: If JSON serialisation fails.
        """
        try:
            payload = self._to_spdx_dict(sbom_doc)
            return json.dumps(payload, indent=2, default=str)
        except Exception as exc:
            raise GenerationError(
                f"SPDX serialisation failed: {exc}",
            ) from exc

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _to_spdx_dict(self, sbom_doc: SBOMDocument) -> dict[str, Any]:
        """Convert an SBOMDocument to an SPDX 2.3 compliant dict."""
        doc_name = sbom_doc.main_component_name or "unknown"

        packages = [self._component_to_package(c) for c in sbom_doc.components]

        # Relationships: DOCUMENT DESCRIBES each package
        relationships = [
            {
                "spdxElementId": "SPDXRef-DOCUMENT",
                "relationshipType": "DESCRIBES",
                "relatedSpdxElement": _spdx_id(c.name, c.version),
            }
            for c in sbom_doc.components
        ]

        return {
            "spdxVersion": "SPDX-2.3",
            "dataLicense": "CC0-1.0",
            "SPDXID": "SPDXRef-DOCUMENT",
            "name": doc_name,
            "documentNamespace": (f"https://sbom.example.com/{doc_name}/{sbom_doc.serial_number}"),
            "creationInfo": {
                "created": sbom_doc.generated_at.isoformat(),
                "creators": [f"Tool: {sbom_doc.tool_name}-{sbom_doc.tool_version}"],
            },
            "packages": packages,
            "relationships": relationships,
        }

    @staticmethod
    def _component_to_package(component: SBOMComponent) -> dict[str, Any]:
        """Convert a single SBOMComponent to an SPDX package dict."""
        pkg: dict[str, Any] = {
            "SPDXID": _spdx_id(component.name, component.version),
            "name": component.name,
            "versionInfo": component.version,
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
        }
        if component.purl:
            pkg["externalRefs"] = [
                {
                    "referenceCategory": "PACKAGE-MANAGER",
                    "referenceType": "purl",
                    "referenceLocator": component.purl,
                }
            ]
        if component.licenses:
            pkg["licenseConcluded"] = " AND ".join(component.licenses)
            pkg["licenseInfoFromFiles"] = component.licenses
        else:
            pkg["licenseConcluded"] = "NOASSERTION"
            pkg["licenseInfoFromFiles"] = ["NOASSERTION"]
        if component.hash_sha256:
            pkg["checksums"] = [{"algorithm": "SHA256", "checksumValue": component.hash_sha256}]
        return pkg
