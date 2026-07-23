#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/sbom_router.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Ayo
"""

# Standard
import json
import logging
from typing import Optional
from uuid import UUID

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import get_db
from plugins.sbom_generator.storage.models import (
    SBOMComponentDB,
    SBOMDocumentDB,
)
from plugins.sbom_generator.storage.repository import SBOMRepository

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/sbom",
    tags=["SBOM"],
    responses={404: {"description": "Not found"}},
)


# ============================================================================
# Dependency Injection
# ============================================================================


def get_sbom_repository(
    session: Session = Depends(get_db),
) -> SBOMRepository:
    """Get SBOM repository instance."""
    return SBOMRepository(session)


# ============================================================================
# Request/Response Models
# ============================================================================


class CleanupResponse(BaseModel):
    """Response for cleanup endpoint."""

    sboms_affected: int
    retention_days: int
    dry_run: bool
    message: str


# ============================================================================
# Component Search Endpoints
# ============================================================================


@router.get("/components/search")
def search_components(
    name: Optional[str] = Query(None, description="Component name filter"),
    version: Optional[str] = Query(None, description="Exact version match"),
    ecosystem: Optional[str] = Query(None, description="Package ecosystem"),
    purl: Optional[str] = Query(None, description="Package URL"),
    limit: int = Query(100, description="Maximum results", ge=1, le=1000),
    repository: SBOMRepository = Depends(get_sbom_repository),
):
    """Search for components across all SBOMs."""
    logger.info(f"Searching components: name={name}, version={version}, ecosystem={ecosystem}")

    components = repository.search_components(
        name=name,
        version=version,
        ecosystem=ecosystem,
        purl=purl,
        limit=limit,
    )

    return {
        "count": len(components),
        "components": [_serialize_component(c) for c in components],
    }


# ============================================================================
# Vulnerability Analysis Endpoints
# ============================================================================


@router.get("/affected")
def find_affected_servers(
    package: str = Query(..., description="Package name"),
    version_lt: Optional[str] = Query(None, description="Version less than"),
    version_eq: Optional[str] = Query(None, description="Exact version"),
    ecosystem: Optional[str] = Query(None, description="Package ecosystem"),
    repository: SBOMRepository = Depends(get_sbom_repository),
):
    """Find servers affected by a vulnerable package."""
    # Validate that package parameter is provided
    if not package:
        raise HTTPException(status_code=422, detail="Package name is required")

    logger.info(f"Finding affected servers: package={package}, version_lt={version_lt}")

    affected = repository.find_affected_servers(
        package_name=package,
        version_constraint=version_lt,
        version_eq=version_eq,
        ecosystem=ecosystem,
    )

    display_constraint = None
    if version_lt:
        display_constraint = f"<{version_lt}"
    elif version_eq:
        display_constraint = f"=={version_eq}"

    return {
        "package": package,
        "version_constraint": display_constraint,
        "version_eq": version_eq,
        "ecosystem": ecosystem,
        "affected_count": len(affected),
        "affected_servers": affected,
    }


# ============================================================================
# License Analysis Endpoints
# ============================================================================


@router.get("/licenses/summary")
def get_license_summary(
    repository: SBOMRepository = Depends(get_sbom_repository),
):
    """Get license usage summary across all SBOMs."""
    logger.info("Fetching license summary")

    summary = repository.get_license_summary()

    return {
        "total_licenses": len(summary),
        "license_counts": summary,
    }


# ============================================================================
# Statistics Endpoints
# ============================================================================


@router.get("/stats")
def get_stats(
    repository: SBOMRepository = Depends(get_sbom_repository),
):
    """Get SBOM statistics."""
    logger.info("Fetching SBOM statistics")

    # First-Party
    from plugins.sbom_generator.storage.models import SBOMComponentDB

    # Use repository's session
    session = repository.db

    total_sboms = session.query(SBOMDocumentDB).count()
    total_components = session.query(SBOMComponentDB).count()

    # Get unique ecosystems
    ecosystems = session.query(SBOMComponentDB.ecosystem).distinct().all()
    unique_ecosystems = [e[0] for e in ecosystems]

    return {
        "total_sboms": total_sboms,
        "total_components": total_components,
        "unique_ecosystems": unique_ecosystems,
        "ecosystem_count": len(unique_ecosystems),
    }


# ============================================================================
# Cleanup Endpoints
# ============================================================================


@router.delete("/cleanup")
def cleanup_old_sboms(
    retention_days: int = Query(..., ge=1, description="Keep SBOMs newer than this many days"),
    dry_run: bool = Query(True, description="Preview without deleting"),
    repository: SBOMRepository = Depends(get_sbom_repository),
):
    """Delete SBOMs older than retention period."""
    logger.info(f"Cleanup: retention_days={retention_days}, dry_run={dry_run}")

    count = repository.cleanup_old_sboms(
        retention_days=retention_days,
        dry_run=dry_run,
    )

    return CleanupResponse(
        sboms_affected=count,
        retention_days=retention_days,
        dry_run=dry_run,
        message=f"{'Would delete' if dry_run else 'Deleted'} {count} SBOM(s) older than {retention_days} days",
    )


# ============================================================================
# SBOM Document Endpoints
# ============================================================================


@router.get("/{sbom_id}")
def get_sbom(
    sbom_id: str,
    include_components: bool = Query(True, description="Include component list"),
    repository: SBOMRepository = Depends(get_sbom_repository),
):
    """Retrieve SBOM document by ID."""
    # Validate UUID format
    try:
        UUID(sbom_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid UUID format")

    logger.info(f"Fetching SBOM: {sbom_id}")

    sbom = repository.get_sbom(sbom_id, include_components=include_components)

    if not sbom:
        raise HTTPException(status_code=404, detail=f"SBOM {sbom_id} not found")

    return {
        "id": str(sbom.id),
        "server_id": str(sbom.server_id),
        "format": sbom.format,
        "spec_version": sbom.spec_version,
        "serial_number": sbom.serial_number,
        "document_version": sbom.document_version,
        "generated_at": sbom.generated_at.isoformat(),
        "generator_tool": sbom.generator_tool,
        "generator_version": sbom.generator_version,
        "main_component": {
            "name": sbom.main_component_name,
            "version": sbom.main_component_version,
        },
        "component_count": len(sbom.components) if include_components else None,
        "components": ([_serialize_component(c) for c in sbom.components] if include_components else None),
        "created_at": sbom.created_at.isoformat(),
    }


@router.get("/server/{server_id}")
def get_sbom_by_server(
    server_id: str,
    latest_only: bool = Query(True, description="Return only latest SBOM"),
    repository: SBOMRepository = Depends(get_sbom_repository),
):
    """Retrieve SBOM documents for a specific MCP server."""
    logger.info(f"Fetching SBOMs for server: {server_id}")

    sboms = repository.get_sbom_by_server(server_id, latest_only=latest_only)

    if not sboms:
        raise HTTPException(
            status_code=404,
            detail=f"No SBOMs found for server {server_id}",
        )

    return {
        "server_id": str(server_id),
        "count": len(sboms),
        "sboms": [
            {
                "id": str(sbom.id),
                "format": sbom.format,
                "spec_version": sbom.spec_version,
                "generated_at": sbom.generated_at.isoformat(),
                "component_count": len(sbom.components),
                "main_component": {
                    "name": sbom.main_component_name,
                    "version": sbom.main_component_version,
                },
            }
            for sbom in sboms
        ],
    }


# ============================================================================
# Helper Functions
# ============================================================================


def _serialize_component(component: SBOMComponentDB) -> dict:
    """Serialize component to JSON."""
    return {
        "id": str(component.id),
        "name": component.name,
        "version": component.version,
        "purl": component.purl,
        "ecosystem": component.ecosystem,
        "component_type": component.component_type,
        "licenses": json.loads(component.licenses) if component.licenses else [],
        "hash_sha256": component.hash_sha256,
        "is_direct": component.is_direct,
        "metadata": json.loads(component.component_metadata) if component.component_metadata else {},
        "created_at": component.created_at.isoformat(),
    }
