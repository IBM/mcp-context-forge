#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/sbom_generator/query/cve_correlation.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Fionn Gavin

CVE correlation and vulnerability analysis API.
Matches vulnerable components across SBOMs and identifies affected servers.
"""

# Future
from __future__ import annotations

# Standard
from dataclasses import dataclass, field
import logging
from typing import Any, Optional

# Local
from ..storage.repository import SBOMRepository

logger = logging.getLogger(__name__)


@dataclass
class AffectedServer:
    """Result of CVE correlation showing which servers are affected.

    Attributes:
        server_id: ID of the affected MCP server.
        sbom_id: ID of the SBOM document where vulnerability was found.
        affected_components: List of component names that are vulnerable.
        component_count: Number of affected components.
        severity: Severity level of the vulnerability (critical, high, medium, low).
    """

    server_id: str
    sbom_id: str
    affected_components: list[str] = field(default_factory=list)
    component_count: int = 0
    severity: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict for JSON API responses."""
        return {
            "server_id": self.server_id,
            "sbom_id": self.sbom_id,
            "affected_components": self.affected_components,
            "component_count": self.component_count,
            "severity": self.severity,
        }


class CVECorrelation:
    """Query interface for CVE vulnerability correlation.

    Matches vulnerable components across stored SBOMs and identifies
    which servers are affected by known vulnerabilities.

    Args:
        repository: An initialised :class:`~plugins.sbom_generator.storage.repository.SBOMRepository`.
    """

    def __init__(self, repository: SBOMRepository):
        """Initialise with a repository."""
        self._repo = repository

    def find_affected_by_cve(self, cve_id: str) -> list[AffectedServer]:
        """Find all servers affected by a specific CVE.

        Args:
            cve_id: CVE identifier (e.g., ``"CVE-2024-0001"``).

        Returns:
            List of :class:`AffectedServer` objects with affected servers and components.
        """
        logger.debug("Searching for servers affected by CVE: %s", cve_id)
        # Implementation would query vulnerability database and match against
        # components in stored SBOMs. For now, returns empty list.
        return []

    def find_affected_by_component(self, name: str, version: str) -> list[AffectedServer]:
        """Find all servers containing a specific vulnerable component.

        Args:
            name: Component/package name.
            version: Component version.

        Returns:
            List of :class:`AffectedServer` objects.
        """
        logger.debug("Searching for servers with component: %s@%s", name, version)

        affected: list[AffectedServer] = []
        db_rows = self._repo.search_components(name=name, version=version, limit=10000)

        for row in db_rows:
            if row.sbom_document:
                affected.append(
                    AffectedServer(
                        server_id=row.sbom_document.server_id,
                        sbom_id=str(row.sbom_document_id),
                        affected_components=[row.name],
                        component_count=1,
                        severity=None,
                    )
                )

        return affected

    def find_affected_by_version_range(self, name: str, min_version: str, max_version: str) -> list[AffectedServer]:
        """Find servers with a component in a vulnerable version range.

        Args:
            name: Component/package name.
            min_version: Minimum version (inclusive).
            max_version: Maximum version (inclusive).

        Returns:
            List of :class:`AffectedServer` objects.
        """
        logger.debug("Searching for %s versions %s-%s", name, min_version, max_version)
        # This would need version comparison logic to match versions
        # For now, simple implementation
        all_results = self._repo.search_components(name=name, limit=10000)

        affected: list[AffectedServer] = []
        for row in all_results:
            if row.sbom_document:
                affected.append(
                    AffectedServer(
                        server_id=row.sbom_document.server_id,
                        sbom_id=str(row.sbom_document_id),
                        affected_components=[row.name],
                        component_count=1,
                    )
                )

        return affected

    def find_affected_servers(self, component_specs: list[tuple[str, str]]) -> list[AffectedServer]:
        """Find servers affected by a list of vulnerable component specifications.

        Args:
            component_specs: List of (name, version) tuples.

        Returns:
            List of :class:`AffectedServer` objects (deduplicated by server_id).
        """
        logger.debug("Searching for servers with %d component specs", len(component_specs))

        server_affected: dict[str, AffectedServer] = {}

        for name, version in component_specs:
            results = self.find_affected_by_component(name, version)
            for result in results:
                if result.server_id not in server_affected:
                    server_affected[result.server_id] = result
                else:
                    # Merge components
                    existing = server_affected[result.server_id]
                    existing.affected_components.extend(result.affected_components)
                    existing.component_count = len(set(existing.affected_components))

        return list(server_affected.values())

    def get_cve_severity(self, cve_id: str) -> Optional[str]:
        """Get severity level for a CVE.

        Args:
            cve_id: CVE identifier.

        Returns:
            Severity level or None if not found.
        """
        # Implementation would query CVE database
        # For now, returns None (not in CVE database)
        logger.debug("Retrieving severity for CVE: %s", cve_id)
        return None

    def get_impact_summary(self, cve_id: str) -> Optional[dict[str, Any]]:
        """Get impact summary for a CVE across all servers.

        Args:
            cve_id: CVE identifier.

        Returns:
            Dict with impact analysis or None if CVE not found.
        """
        logger.debug("Getting impact summary for CVE: %s", cve_id)
        # Implementation would analyze CVE impact
        return None
