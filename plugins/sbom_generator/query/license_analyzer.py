#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/sbom_generator/query/license_analyzer.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Fionn Gavin

License compliance analysis: summarises license usage, flags blocked/warned
licenses, and identifies which servers carry which licenses.
"""

# Future
from __future__ import annotations

# Standard
from dataclasses import dataclass, field
import json
import logging
from typing import Any

# Local
from ..models import LicensePolicy
from ..storage.models import SBOMComponentDB
from ..storage.repository import SBOMRepository

logger = logging.getLogger(__name__)


@dataclass
class LicenseSummary:
    """Aggregated license compliance report.

    Attributes:
        total_components: Total number of components analysed.
        license_counts: Mapping of license ID → occurrence count.
        blocked: License IDs present that are on the blocked list.
        flagged: License IDs present that are on the warn list.
        allowed: All other license IDs found.
        servers_with_blocked: server IDs that carry at least one blocked license.
    """

    total_components: int = 0
    license_counts: dict[str, int] = field(default_factory=dict)
    blocked: list[str] = field(default_factory=list)
    flagged: list[str] = field(default_factory=list)
    allowed: list[str] = field(default_factory=list)
    servers_with_blocked: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict for JSON API responses."""
        return {
            "total_components": self.total_components,
            "license_counts": self.license_counts,
            "blocked": self.blocked,
            "flagged": self.flagged,
            "allowed": self.allowed,
            "servers_with_blocked": self.servers_with_blocked,
        }


@dataclass
class ServerLicenseReport:
    """License compliance report for a single MCP server.

    Attributes:
        server_id: The MCP server ID.
        licenses: All unique license IDs found in its latest SBOM.
        blocked: Blocked licenses present in this server's SBOM.
        flagged: Flagged licenses present in this server's SBOM.
        is_compliant: ``True`` if no blocked licenses were found.
    """

    server_id: str
    licenses: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    flagged: list[str] = field(default_factory=list)
    is_compliant: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict for JSON API responses."""
        return {
            "server_id": self.server_id,
            "licenses": self.licenses,
            "blocked": self.blocked,
            "flagged": self.flagged,
            "is_compliant": self.is_compliant,
        }


def _extract_licenses(db_component: SBOMComponentDB) -> list[str]:
    """Safely deserialise the JSON-encoded license list from a DB row."""
    if not db_component.licenses:
        return []
    try:
        return json.loads(db_component.licenses)
    except (ValueError, TypeError):
        return []


class LicenseAnalyzer:
    """Analyses license compliance across all stored SBOM components.

    Args:
        repository: An initialised :class:`~plugins.sbom_generator.storage.repository.SBOMRepository`.
        policy: A :class:`~plugins.sbom_generator.models.LicensePolicy` defining
            blocked and flagged license IDs.
    """

    def __init__(self, repository: SBOMRepository, policy: LicensePolicy):
        """Initialise with a repository and license policy."""
        self._repo = repository
        self._policy = policy

    def global_summary(self) -> LicenseSummary:
        """Produce an aggregated license summary across all stored SBOMs.

        Returns:
            A :class:`LicenseSummary` with counts and compliance breakdown.
        """
        raw_counts = self._repo.get_license_summary()
        validation = self._policy.validate_licenses(list(raw_counts.keys()))

        # Identify servers that carry blocked licenses
        servers_with_blocked: list[str] = []
        if validation["blocked"]:
            servers_with_blocked = self._servers_with_licenses(validation["blocked"])

        return LicenseSummary(
            total_components=sum(raw_counts.values()),
            license_counts=raw_counts,
            blocked=validation["blocked"],
            flagged=validation["flagged"],
            allowed=validation["allowed"],
            servers_with_blocked=servers_with_blocked,
        )

    def server_report(self, server_id: str) -> ServerLicenseReport:
        """Produce a license compliance report for a single MCP server.

        Uses the most recent SBOM stored for the server.

        Args:
            server_id: The MCP server ID.

        Returns:
            A :class:`ServerLicenseReport` for that server.
        """
        sboms = self._repo.get_sbom_by_server(server_id, latest_only=True)
        if not sboms:
            logger.warning("No SBOM found for server %r", server_id)
            return ServerLicenseReport(server_id=server_id)

        all_licenses: set[str] = set()
        for sbom in sboms:
            for component in sbom.components:
                all_licenses.update(_extract_licenses(component))

        validation = self._policy.validate_licenses(list(all_licenses))

        return ServerLicenseReport(
            server_id=server_id,
            licenses=sorted(all_licenses),
            blocked=validation["blocked"],
            flagged=validation["flagged"],
            is_compliant=len(validation["blocked"]) == 0,
        )

    def _servers_with_licenses(self, license_ids: list[str]) -> list[str]:
        """Return deduplicated server IDs whose SBOMs contain any of *license_ids*.

        Args:
            license_ids: License IDs to search for.

        Returns:
            List of server ID strings.
        """
        server_ids: set[str] = set()

        for license_id in license_ids:
            rows = self._repo.search_components(limit=10_000)
            for row in rows:
                if license_id in _extract_licenses(row):
                    if row.sbom_document:
                        server_ids.add(row.sbom_document.server_id)

        return sorted(server_ids)
