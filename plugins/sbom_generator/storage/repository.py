#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/sbom_generator/storage/repository.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Ayo
"""

# Standard
from datetime import datetime, timedelta, timezone
import json
import logging
from typing import Any, List, Optional
from uuid import uuid4

# Third-Party
from sqlalchemy.orm import Session

# Local
from ..errors import StorageError
from ..models import SBOMDocument
from .models import SBOMComponentDB, SBOMDocumentDB

logger = logging.getLogger(__name__)


class SBOMRepository:
    """Repository for SBOM database operations."""

    def __init__(self, session: Session):
        """Initialize repository."""
        self.db = session

    def create_sbom(
        self,
        server_id: str,
        sbom_doc: SBOMDocument,
        compress: bool = False,
    ) -> SBOMDocumentDB:
        """Store SBOM document in database."""
        try:
            document_json = self._sbom_to_json(sbom_doc)

            db_sbom = SBOMDocumentDB(
                id=str(uuid4()),
                server_id=server_id,
                format=sbom_doc.format.value,
                spec_version=sbom_doc.spec_version,
                serial_number=sbom_doc.serial_number,
                document_version=sbom_doc.version,
                generated_at=sbom_doc.generated_at,
                generator_tool=sbom_doc.tool_name,
                generator_version=sbom_doc.tool_version,
                main_component_name=sbom_doc.main_component_name,
                main_component_version=sbom_doc.main_component_version,
                document_json=json.dumps(document_json),
                is_compressed=compress,
            )

            self.db.add(db_sbom)
            self.db.flush()

            for component in sbom_doc.components:
                db_component = SBOMComponentDB(
                    id=str(uuid4()),
                    sbom_document_id=db_sbom.id,
                    name=component.name,
                    version=component.version,
                    purl=component.purl,
                    ecosystem=component.ecosystem.value,
                    licenses=json.dumps(component.licenses) if component.licenses else None,
                    hash_sha256=component.hash_sha256,
                    is_direct=component.is_direct,
                    component_metadata=json.dumps(component.metadata) if component.metadata else None,
                )
                self.db.add(db_component)

            self.db.commit()
            logger.info(f"Stored SBOM {db_sbom.id} with {len(sbom_doc.components)} components")

            return db_sbom

        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to store SBOM: {e}")
            raise StorageError(f"Failed to store SBOM: {e}")

    def get_sbom(self, sbom_id: str, include_components: bool = True) -> Optional[SBOMDocumentDB]:
        """Retrieve SBOM document by ID."""
        return self.db.query(SBOMDocumentDB).filter(SBOMDocumentDB.id == sbom_id).first()

    def get_sbom_by_server(self, server_id: str, latest_only: bool = True) -> List[SBOMDocumentDB]:
        """Retrieve SBOMs for a specific server."""
        query = self.db.query(SBOMDocumentDB).filter(SBOMDocumentDB.server_id == server_id).order_by(SBOMDocumentDB.generated_at.desc())

        if latest_only:
            query = query.limit(1)

        return query.all()

    def search_components(
        self,
        name: Optional[str] = None,
        version: Optional[str] = None,
        ecosystem: Optional[str] = None,
        purl: Optional[str] = None,
        limit: int = 100,
    ) -> List[SBOMComponentDB]:
        """Search for components with filters."""
        query = self.db.query(SBOMComponentDB)

        if name:
            query = query.filter(SBOMComponentDB.name.like(f"%{name}%"))
        if version:
            query = query.filter(SBOMComponentDB.version == version)
        if ecosystem:
            query = query.filter(SBOMComponentDB.ecosystem == ecosystem)
        if purl:
            query = query.filter(SBOMComponentDB.purl == purl)

        return query.limit(limit).all()

    def find_affected_servers(
        self,
        package_name: str,
        version_constraint: Optional[str] = None,
        version_eq: Optional[str] = None,
        ecosystem: Optional[str] = None,
    ) -> List[dict]:
        """Find servers affected by a vulnerable package."""
        query = self.db.query(SBOMDocumentDB.server_id, SBOMComponentDB.name, SBOMComponentDB.version, SBOMComponentDB.ecosystem).join(SBOMComponentDB)

        query = query.filter(SBOMComponentDB.name == package_name)

        if ecosystem:
            query = query.filter(SBOMComponentDB.ecosystem == ecosystem)
        if version_eq:
            query = query.filter(SBOMComponentDB.version == version_eq)
        if version_constraint:
            query = query.filter(SBOMComponentDB.version < version_constraint)

        results = query.all()

        return [
            {
                "server_id": r.server_id,
                "component_name": r.name,
                "component_version": r.version,
                "ecosystem": r.ecosystem,
            }
            for r in results
        ]

    def get_license_summary(self) -> dict[str, int]:
        """Get license usage summary across all SBOMs."""
        components = self.db.query(SBOMComponentDB).all()

        license_counts = {}
        for component in components:
            if component.licenses:
                licenses = json.loads(component.licenses)
                for license in licenses:
                    license_counts[license] = license_counts.get(license, 0) + 1

        return license_counts

    def cleanup_old_sboms(self, retention_days: int, dry_run: bool = False) -> int:
        """Delete SBOMs older than retention period."""
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)

        query = self.db.query(SBOMDocumentDB).filter(SBOMDocumentDB.created_at < cutoff_date)

        count = query.count()

        if not dry_run and count > 0:
            query.delete()
            self.db.commit()
            logger.info(f"Deleted {count} SBOMs older than {retention_days} days")

        return count

    def _sbom_to_json(self, sbom_doc: SBOMDocument) -> dict[str, Any]:
        """Convert SBOM document to JSON."""
        metadata = sbom_doc.metadata or {}

        # Add timestamp if not present
        if "timestamp" not in metadata:
            metadata["timestamp"] = sbom_doc.generated_at.isoformat()

        if "tools" not in metadata:
            metadata["tools"] = [{"name": sbom_doc.tool_name or "unknown", "version": sbom_doc.tool_version or "unknown"}]

        return {
            "format": sbom_doc.format.value,
            "specVersion": sbom_doc.spec_version,
            "serialNumber": sbom_doc.serial_number,
            "version": sbom_doc.version,
            "metadata": metadata,
            "components": [
                {
                    "name": c.name,
                    "version": c.version,
                    "purl": c.purl,
                    "ecosystem": c.ecosystem.value,
                    "licenses": c.licenses or [],
                }
                for c in sbom_doc.components
            ],
        }
