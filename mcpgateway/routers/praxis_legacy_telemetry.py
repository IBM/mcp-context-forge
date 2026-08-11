"""Authenticated legacy telemetry and platform-admin removal reports."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from mcpgateway.auth_context import get_user_email
from mcpgateway.db import EmailUser, get_db, utc_now
from mcpgateway.middleware.rbac import get_current_user_with_permissions
from mcpgateway.services.praxis_legacy_models import (
    AttestationReceipt,
    HeartbeatReceipt,
    InventoryAttestation,
    InventoryStatus,
    LegacyHeartbeat,
    RemovalReadinessReport,
)
from mcpgateway.services.praxis_legacy_telemetry import LegacyTelemetryError, PraxisLegacyTelemetryService

router = APIRouter(prefix="/praxis/legacy", tags=["Praxis Legacy Telemetry"])


class _SystemClock:
    def now(self) -> datetime:
        return utc_now()


def get_legacy_telemetry_service(db: Annotated[Session, Depends(get_db)]) -> PraxisLegacyTelemetryService:
    """Build a request-scoped telemetry service."""
    return PraxisLegacyTelemetryService(db, _SystemClock())


def _require_platform_admin(user: dict, db: Session) -> str:
    actor = get_user_email(user)
    is_admin = db.scalar(select(EmailUser.is_admin).where(EmailUser.email == actor, EmailUser.is_active.is_(True)))
    if not is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Access denied")
    return actor


@router.post("/heartbeat", response_model=HeartbeatReceipt, status_code=status.HTTP_202_ACCEPTED)
async def heartbeat(
    payload: LegacyHeartbeat,
    user: dict = Depends(get_current_user_with_permissions),
    service: PraxisLegacyTelemetryService = Depends(get_legacy_telemetry_service),
) -> HeartbeatReceipt:
    """Accept a heartbeat whose identity comes only from authentication."""
    try:
        return service.heartbeat(get_user_email(user), payload)
    except LegacyTelemetryError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from None


@router.put("/inventory-attestation", response_model=AttestationReceipt)
async def attest_inventory(
    payload: InventoryAttestation,
    user: dict = Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
    service: PraxisLegacyTelemetryService = Depends(get_legacy_telemetry_service),
) -> AttestationReceipt:
    """Replace the declared inventory as a platform administrator."""
    return service.attest(_require_platform_admin(user, db), payload)


@router.get("/inventory", response_model=InventoryStatus)
async def inventory(
    user: dict = Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
    service: PraxisLegacyTelemetryService = Depends(get_legacy_telemetry_service),
) -> InventoryStatus:
    """Return redacted inventory to a platform administrator."""
    _require_platform_admin(user, db)
    return service.inventory()


@router.get("/removal-readiness", response_model=RemovalReadinessReport)
async def removal_readiness(
    user: dict = Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
    service: PraxisLegacyTelemetryService = Depends(get_legacy_telemetry_service),
) -> RemovalReadinessReport:
    """Return a report-only later-release decision."""
    _require_platform_admin(user, db)
    return service.removal_report()


__all__ = ("get_legacy_telemetry_service", "router")
