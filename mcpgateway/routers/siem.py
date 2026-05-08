# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/siem.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

SIEM admin API router.
"""

# Standard
import logging
from typing import Any, Dict, List, Optional

# Third-Party
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

# First-Party
from mcpgateway.middleware.rbac import get_current_user_with_permissions, require_permission
from mcpgateway.services.siem_export_service import get_siem_export_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/siem", tags=["SIEM"])


class DestinationFiltersRequest(BaseModel):
    """Optional destination filter config."""

    severity: Optional[List[str]] = None
    event_types: Optional[List[str]] = None
    categories: Optional[List[str]] = None


class DestinationUpsertRequest(BaseModel):
    """Runtime SIEM destination configuration payload."""

    name: str = Field(..., min_length=1)
    type: str = Field(..., min_length=1)
    enabled: bool = True
    format: str = "json"
    url: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    protocol: Optional[str] = None
    filters: Optional[DestinationFiltersRequest] = None
    model_config = ConfigDict(extra="allow")


class DestinationBulkReplaceRequest(BaseModel):
    """Bulk replacement payload for SIEM destinations."""

    destinations: List[DestinationUpsertRequest]


@router.get("/health")
@require_permission("admin.security_audit")
async def get_siem_health(_user=Depends(get_current_user_with_permissions)) -> Dict[str, Any]:
    """Get SIEM exporter health and per-destination delivery stats.

    Returns:
        Dict[str, Any]: Exporter health payload.
    """
    service = get_siem_export_service()
    return await service.get_health()


@router.get("/destinations")
@require_permission("admin.security_audit")
async def get_siem_destinations(_user=Depends(get_current_user_with_permissions)) -> Dict[str, Any]:
    """List current SIEM destination configuration (sensitive fields redacted).

    Returns:
        Dict[str, Any]: Destination list and exporter enablement state.
    """
    service = get_siem_export_service()
    return {
        "enabled": service.enabled,
        "destinations": service.list_destinations(),
    }


@router.post("/destinations")
@require_permission("admin.security_audit")
async def add_siem_destination(payload: DestinationUpsertRequest, _user=Depends(get_current_user_with_permissions)) -> Dict[str, Any]:
    """Add one SIEM destination at runtime (no restart required).

    Args:
        payload: Destination configuration payload.

    Returns:
        Dict[str, Any]: Operation result with sanitized destination.

    Raises:
        HTTPException: If validation or persistence fails.
    """
    service = get_siem_export_service()

    try:
        created = await service.add_destination(payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Failed to add SIEM destination: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to add SIEM destination") from exc

    return {
        "status": "ok",
        "destination": created,
    }


@router.put("/destinations")
@require_permission("admin.security_audit")
async def replace_siem_destinations(payload: DestinationBulkReplaceRequest, _user=Depends(get_current_user_with_permissions)) -> Dict[str, Any]:
    """Replace full SIEM destination set at runtime.

    Args:
        payload: Replacement destination list payload.

    Returns:
        Dict[str, Any]: Operation result with sanitized destinations.

    Raises:
        HTTPException: If validation or persistence fails.
    """
    service = get_siem_export_service()

    try:
        destinations = await service.replace_destinations([item.model_dump(exclude_none=True) for item in payload.destinations])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Failed to replace SIEM destinations: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to replace SIEM destinations") from exc

    return {
        "status": "ok",
        "destinations": destinations,
    }


@router.post("/test/{destination_name}")
@require_permission("admin.security_audit")
async def test_siem_destination(destination_name: str, _user=Depends(get_current_user_with_permissions)) -> Dict[str, Any]:
    """Send a test event to one destination.

    Args:
        destination_name: Destination identifier to test.

    Returns:
        Dict[str, Any]: Delivery test result.

    Raises:
        HTTPException: If destination is missing or test fails unexpectedly.
    """
    service = get_siem_export_service()

    try:
        return await service.test_destination(destination_name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Failed SIEM destination test for %s: %s", destination_name, exc)
        raise HTTPException(status_code=500, detail="Failed to test SIEM destination") from exc
