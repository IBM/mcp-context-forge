#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/sbom_generator/query/component_search.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Fionn Gavin

High-level component search API built on top of SBOMRepository.
Used by the gateway admin UI and REST endpoints.
"""

# Future
from __future__ import annotations

# Standard
from dataclasses import dataclass, field
import logging
from typing import Any

# Local
from ..storage.models import SBOMComponentDB
from ..storage.repository import SBOMRepository

logger = logging.getLogger(__name__)


@dataclass
class ComponentSearchResult:
    """A single result row from a component search.

    Attributes:
        sbom_id: ID of the SBOM document this component belongs to.
        server_id: ID of the MCP server that was assessed.
        name: Component / package name.
        version: Component version string.
        ecosystem: Package ecosystem (python, npm, go, …).
        purl: Package URL, if available.
        licenses: List of SPDX license identifiers.
        is_direct: Whether this is a direct (vs transitive) dependency.
    """

    sbom_id: str
    server_id: str
    name: str
    version: str
    ecosystem: str
    purl: str | None = None
    licenses: list[str] = field(default_factory=list)
    is_direct: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict for JSON API responses."""
        return {
            "sbom_id": self.sbom_id,
            "server_id": self.server_id,
            "name": self.name,
            "version": self.version,
            "ecosystem": self.ecosystem,
            "purl": self.purl,
            "licenses": self.licenses,
            "is_direct": self.is_direct,
        }


def _db_to_result(db_component: SBOMComponentDB) -> ComponentSearchResult:
    """Map a DB row to a ComponentSearchResult."""
    # Standard
    import json

    licenses: list[str] = []
    if db_component.licenses:
        try:
            licenses = json.loads(db_component.licenses)
        except (ValueError, TypeError):
            licenses = []

    server_id = db_component.sbom_document.server_id if db_component.sbom_document else ""

    return ComponentSearchResult(
        sbom_id=db_component.sbom_document_id,
        server_id=server_id,
        name=db_component.name,
        version=db_component.version,
        ecosystem=db_component.ecosystem,
        purl=db_component.purl,
        licenses=licenses,
        is_direct=db_component.is_direct,
    )


class ComponentSearch:
    """Query interface for searching components stored across all SBOMs.

    Args:
        repository: An initialised :class:`~plugins.sbom_generator.storage.repository.SBOMRepository`.
    """

    def __init__(self, repository: SBOMRepository):
        """Initialise with a repository."""
        self._repo = repository

    def search(
        self,
        name: str | None = None,
        version: str | None = None,
        ecosystem: str | None = None,
        purl: str | None = None,
        limit: int = 100,
    ) -> list[ComponentSearchResult]:
        """Search stored SBOM components by one or more filters.

        All supplied filters are combined with AND logic. Omitted filters are
        ignored (i.e. they match everything).

        Args:
            name: Partial package name to match (SQL ``LIKE`` ``%name%``).
            version: Exact version string to match.
            ecosystem: Exact ecosystem string (e.g. ``"python"``).
            purl: Exact PURL to match.
            limit: Maximum number of results to return (default 100).

        Returns:
            List of :class:`ComponentSearchResult` objects.
        """
        logger.debug(
            "Component search: name=%r version=%r ecosystem=%r purl=%r limit=%d",
            name,
            version,
            ecosystem,
            purl,
            limit,
        )

        db_rows = self._repo.search_components(
            name=name,
            version=version,
            ecosystem=ecosystem,
            purl=purl,
            limit=limit,
        )

        results = [_db_to_result(row) for row in db_rows]
        logger.debug("Component search returned %d results", len(results))
        return results

    def get_by_sbom(self, sbom_id: str) -> list[ComponentSearchResult]:
        """Return all components belonging to a specific SBOM document.

        Args:
            sbom_id: The SBOM document ID.

        Returns:
            List of :class:`ComponentSearchResult` objects.
        """
        sbom = self._repo.get_sbom(sbom_id, include_components=True)
        if not sbom:
            return []
        return [_db_to_result(c) for c in sbom.components]

    def get_by_server(self, server_id: str, latest_only: bool = True) -> list[ComponentSearchResult]:
        """Return all components for a given MCP server.

        Args:
            server_id: The MCP server ID.
            latest_only: If ``True`` (default), only return components from
                the most recent SBOM for this server.

        Returns:
            List of :class:`ComponentSearchResult` objects.
        """
        sboms = self._repo.get_sbom_by_server(server_id, latest_only=latest_only)
        results: list[ComponentSearchResult] = []
        for sbom in sboms:
            results.extend(_db_to_result(c) for c in sbom.components)
        return results
