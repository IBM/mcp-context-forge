#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/sbom_service.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Ayo

Service layer for Software Bill of Materials (SBOM) operations.

Provides high-level API for SBOM generation, retrieval, and analysis,
abstracting away the plugin and repository implementation details.
"""

# Standard
import logging
from typing import Any, Optional

# Third-Party
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class SBOMServiceError(Exception):
    """Base exception for SBOM service errors."""

    def __init__(self, message: str, details: Optional[dict] = None):
        """Initialize with error message and optional details."""
        self.message = message
        self.details = details or {}
        super().__init__(message)


class SBOMNotFoundError(SBOMServiceError):
    """SBOM document not found."""

    pass


class SBOMService:
    """Service for SBOM operations.

    Provides a clean API for:
    - Retrieving SBOM documents and components
    - Searching for components across all SBOMs
    - Finding servers affected by vulnerabilities
    - License analysis and reporting
    - SBOM lifecycle management
    """

    def __init__(self, db_session: Session):
        """Initialize SBOM service.

        Args:
            db_session: SQLAlchemy database session
        """
        self.db_session = db_session

    # ================================================================
    # SBOM Retrieval
    # ================================================================

    def get_sbom(self, sbom_id: str, include_components: bool = True) -> dict[str, Any]:
        """Get SBOM document by ID.

        Args:
            sbom_id: SBOM document UUID
            include_components: Include component list in response

        Returns:
            SBOM document as dict

        Raises:
            SBOMNotFoundError: If SBOM not found
        """
        # First-Party
        from plugins.sbom_generator.storage import SBOMRepository

        repo = SBOMRepository(self.db_session)
        sbom_doc = repo.get_sbom(sbom_id, include_components=include_components)

        if not sbom_doc:
            raise SBOMNotFoundError(
                f"SBOM not found: {sbom_id}",
                details={"sbom_id": sbom_id},
            )

        return self._serialize_sbom_document(sbom_doc, include_components)

    def get_sbom_by_server(self, server_id: str, latest_only: bool = True) -> list[dict[str, Any]]:
        """Get SBOMs for a specific MCP server.

        Args:
            server_id: Server UUID
            latest_only: Return only the most recent SBOM

        Returns:
            List of SBOM documents (or single-item list if latest_only=True)
        """
        # First-Party
        from plugins.sbom_generator.storage import SBOMRepository

        repo = SBOMRepository(self.db_session)
        sbom_docs = repo.get_sbom_by_server(server_id, latest_only=latest_only)

        return [self._serialize_sbom_document(doc, include_components=False) for doc in sbom_docs]

    # ================================================================
    # Component Search
    # ================================================================

    def search_components(
        self,
        name: Optional[str] = None,
        version: Optional[str] = None,
        ecosystem: Optional[str] = None,
        purl: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Search for components across all SBOMs.

        Args:
            name: Component name (supports partial match)
            version: Exact version match
            ecosystem: Package ecosystem (python, npm, go, etc.)
            purl: Package URL
            limit: Maximum results to return

        Returns:
            List of matching components with SBOM context
        """
        # First-Party
        from plugins.sbom_generator.storage import SBOMRepository

        repo = SBOMRepository(self.db_session)
        components = repo.search_components(
            name=name,
            version=version,
            ecosystem=ecosystem,
            purl=purl,
            limit=limit,
        )

        return [self._serialize_component(comp) for comp in components]

    # ================================================================
    # Vulnerability Analysis
    # ================================================================

    def find_affected_servers(
        self,
        package_name: str,
        version_constraint: Optional[str] = None,
        version_eq: Optional[str] = None,
        ecosystem: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Find servers affected by a vulnerable package.

        Useful for security incident response - quickly identify all servers
        that use a specific package version.

        Args:
            package_name: Package/component name
            version_constraint: Version less than (e.g., "2.0.0")
            version_eq: Exact version match
            ecosystem: Package ecosystem to narrow search

        Returns:
            List of affected servers with component details
        """
        # First-Party
        from plugins.sbom_generator.storage import SBOMRepository

        repo = SBOMRepository(self.db_session)
        return repo.find_affected_servers(
            package_name=package_name,
            version_constraint=version_constraint,
            version_eq=version_eq,
            ecosystem=ecosystem,
        )

    # ================================================================
    # License Analysis
    # ================================================================

    def get_license_summary(self) -> dict[str, int]:
        """Get license usage summary across all SBOMs.

        Returns counts of how many components use each license type.
        Useful for compliance reporting and license policy enforcement.

        Returns:
            Dict mapping license identifiers to usage counts
        """
        # First-Party
        from plugins.sbom_generator.storage import SBOMRepository

        repo = SBOMRepository(self.db_session)
        return repo.get_license_summary()

    def get_license_report(self, blocked_licenses: Optional[list[str]] = None) -> dict[str, Any]:
        """Get comprehensive license report.

        Args:
            blocked_licenses: Optional list of blocked license identifiers

        Returns:
            Dict with license summary, blocked licenses, and affected servers
        """
        summary = self.get_license_summary()

        report = {
            "total_licenses": len(summary),
            "total_components": sum(summary.values()),
            "license_counts": summary,
        }

        if blocked_licenses:
            blocked_found = {lic: count for lic, count in summary.items() if lic in blocked_licenses}
            report["blocked_licenses"] = blocked_found
            report["has_violations"] = len(blocked_found) > 0

        return report

    # ================================================================
    # SBOM Lifecycle Management
    # ================================================================

    def cleanup_old_sboms(self, retention_days: int, dry_run: bool = False) -> dict[str, Any]:
        """Delete SBOMs older than retention period.

        Args:
            retention_days: Keep SBOMs newer than this many days
            dry_run: If True, count without deleting

        Returns:
            Dict with count of SBOMs affected
        """
        # First-Party
        from plugins.sbom_generator.storage import SBOMRepository

        repo = SBOMRepository(self.db_session)
        count = repo.cleanup_old_sboms(
            retention_days=retention_days,
            dry_run=dry_run,
        )

        return {
            "sboms_deleted" if not dry_run else "sboms_to_delete": count,
            "retention_days": retention_days,
            "dry_run": dry_run,
        }

    # ================================================================
    # Statistics
    # ================================================================

    def get_statistics(self) -> dict[str, Any]:
        """Get overall SBOM statistics.

        Returns:
            Dict with counts and summary statistics
        """
        # First-Party
        from plugins.sbom_generator.storage.models import (
            SBOMComponentDB,
            SBOMDocumentDB,
        )

        total_sboms = self.db_session.query(SBOMDocumentDB).count()
        total_components = self.db_session.query(SBOMComponentDB).count()

        # Get unique ecosystems
        ecosystems = self.db_session.query(SBOMComponentDB.ecosystem).distinct().all()
        unique_ecosystems = [e[0] for e in ecosystems]

        return {
            "total_sboms": total_sboms,
            "total_components": total_components,
            "unique_ecosystems": unique_ecosystems,
            "ecosystem_count": len(unique_ecosystems),
        }

    # ================================================================
    # SBOM Export
    # ================================================================

    def export_sbom(self, sbom_id: str, format: str = "json") -> str:
        """Export SBOM document in specified format.

        Args:
            sbom_id: SBOM document UUID
            format: Export format ("json", "xml", etc.)

        Returns:
            Serialized SBOM document as string

        Raises:
            SBOMNotFoundError: If SBOM not found
            ValueError: If format not supported
        """
        # First-Party
        from plugins.sbom_generator.storage import SBOMRepository

        repo = SBOMRepository(self.db_session)
        sbom_doc = repo.get_sbom(sbom_id)

        if not sbom_doc:
            raise SBOMNotFoundError(
                f"SBOM not found: {sbom_id}",
                details={"sbom_id": sbom_id},
            )

        if format == "json":
            # Return the stored JSON document
            return sbom_doc.document_json
        else:
            raise ValueError(f"Unsupported export format: {format}")

    # ================================================================
    # Internal Helpers
    # ================================================================

    def _serialize_sbom_document(self, sbom_doc: Any, include_components: bool = True) -> dict[str, Any]:
        """Serialize SBOM document database model to dict.

        Args:
            sbom_doc: SBOMDocumentDB instance
            include_components: Include component list

        Returns:
            Serialized document
        """
        result = {
            "id": str(sbom_doc.id),
            "server_id": str(sbom_doc.server_id),
            "format": sbom_doc.format,
            "spec_version": sbom_doc.spec_version,
            "serial_number": sbom_doc.serial_number,
            "version": sbom_doc.document_version,
            "generated_at": sbom_doc.generated_at.isoformat(),
            "generator_tool": sbom_doc.generator_tool,
            "generator_version": sbom_doc.generator_version,
            "main_component": (
                {
                    "name": sbom_doc.main_component_name,
                    "version": sbom_doc.main_component_version,
                }
                if sbom_doc.main_component_name
                else None
            ),
            "created_at": sbom_doc.created_at.isoformat(),
            "updated_at": sbom_doc.updated_at.isoformat(),
        }

        if include_components and hasattr(sbom_doc, "components"):
            result["components"] = [self._serialize_component(comp) for comp in sbom_doc.components]
            result["component_count"] = len(sbom_doc.components)

        return result

    def _serialize_component(self, component: Any) -> dict[str, Any]:
        """Serialize component database model to dict.

        Args:
            component: SBOMComponentDB instance

        Returns:
            Serialized component
        """
        # Standard
        import json

        return {
            "id": str(component.id),
            "sbom_document_id": str(component.sbom_document_id),
            "name": component.name,
            "version": component.version,
            "purl": component.purl,
            "ecosystem": component.ecosystem,
            "licenses": json.loads(component.licenses) if component.licenses else [],
            "hash_sha256": component.hash_sha256,
            "is_direct": component.is_direct,
            "metadata": (json.loads(component.component_metadata) if component.component_metadata else {}),
            "created_at": component.created_at.isoformat(),
        }
