# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/admin_external_group_mappings.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Admin CRUD router for external group mappings (issue #5976).

Exposes POST/PUT/GET/DELETE under /admin/external-group-mappings. Each
endpoint requires the admin.system_config permission, the same permission
used by sibling admin routers such as runtime_admin_router.

Write-time validation:
- cf_team_id must exist in the email_teams table (400 otherwise).
- cf_role, when provided, must resolve to an active row in the roles
  table (400 otherwise). Resolution is scope-exact: roles.name is unique
  only per (name, scope) among active rows, so the team-scoped row wins
  over a global row of the same name and rows are never unioned. cf_role
  carries no foreign key: roles.name has only a partial unique index, so
  existence is validated here at the application level.
- The injectable group_exists_validator seam checks that the external group
  exists in the IdP. It ships disabled by default: the stub always returns
  "valid". The real Microsoft Graph validator lands with the app-only Graph
  client (#5977). The semantics are WARN-AND-ALLOW: when Graph is unreachable
  the validator returns "unknown", the mapping row is still stored, the row
  is audit-logged, and a warning is emitted. A missing group never grants
  access through this seam; the resolver fails closed at read time.
"""

# Future
from __future__ import annotations

# Standard
from datetime import datetime, timezone
from typing import Callable, List, Optional

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.auth_context import get_user_email
from mcpgateway.db import EmailTeam, ExternalGroupMapping
from mcpgateway.middleware.rbac import get_current_user_with_permissions, get_db, require_permission
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.role_resolution import resolve_mapping_role
from mcpgateway.services.security_logger import get_security_logger
from mcpgateway.utils.verify_credentials import invalidate_external_identity_cache

logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

admin_external_group_mappings_router = APIRouter()

#: Injectable validator seam. Signature: (issuer, tenant, external_group_id)
#: -> validation_status. Ships disabled: the stub always returns "valid".
#: WO-B.7 (#5977) wires the real Microsoft Graph validator.
GroupExistsValidator = Callable[[str, str, str], str]


def _disabled_group_exists_validator(issuer: str, tenant: str, external_group_id: str) -> str:
    """Default group-existence validator: disabled, always reports "valid".

    Args:
        issuer: Token issuer the mapping is scoped to.
        tenant: Tenant the mapping is scoped to ("" when the row is tenant-less).
        external_group_id: External IdP group ID to check.

    Returns:
        str: Always "valid"; no IdP call is made until #5977 lands.
    """
    return "valid"


group_exists_validator: GroupExistsValidator = _disabled_group_exists_validator


class ExternalGroupMappingCreate(BaseModel):
    """Request body for POST /admin/external-group-mappings."""

    issuer: str = Field(min_length=1, max_length=512)
    tenant: Optional[str] = Field(default=None, max_length=512)
    external_group_id: str = Field(min_length=1, max_length=512)
    cf_team_id: str = Field(min_length=1, max_length=255)
    cf_role: Optional[str] = Field(default=None, max_length=255)


class ExternalGroupMappingUpdate(BaseModel):
    """Request body for PUT /admin/external-group-mappings/{id}."""

    issuer: Optional[str] = Field(default=None, min_length=1, max_length=512)
    tenant: Optional[str] = Field(default=None, max_length=512)
    external_group_id: Optional[str] = Field(default=None, min_length=1, max_length=512)
    cf_team_id: Optional[str] = Field(default=None, min_length=1, max_length=255)
    cf_role: Optional[str] = Field(default=None, max_length=255)


class ExternalGroupMappingResponse(BaseModel):
    """Response body for external group mapping endpoints."""

    model_config = {"from_attributes": True}

    id: int
    issuer: str
    tenant: Optional[str]
    external_group_id: str
    cf_team_id: str
    cf_role: Optional[str]
    validation_status: str
    last_validated_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


def _validate_team_exists(db: Session, cf_team_id: str) -> None:
    """Raise 400 when cf_team_id does not exist in email_teams.

    Args:
        db: Database session.
        cf_team_id: ContextForge team ID to check.

    Raises:
        HTTPException: 400 when the team does not exist.
    """
    team = db.query(EmailTeam).filter(EmailTeam.id == cf_team_id).first()
    if not team:
        raise HTTPException(status_code=400, detail=f"Team not found: {cf_team_id}")


def _validate_role_exists(db: Session, cf_role: Optional[str], cf_team_id: Optional[str] = None) -> None:
    """Raise 400 when cf_role is set but resolves to no active Role row.

    Resolution is scope-exact via resolve_mapping_role: exactly one
    active row, team scope preferred over global, never a union of rows.
    An inactive role does not pass validation.

    Args:
        db: Database session.
        cf_role: Role name to check. None skips the check.
        cf_team_id: Team context of the mapping being validated.

    Raises:
        HTTPException: 400 when the role name resolves to no active row.
    """
    if cf_role is None:
        return
    if resolve_mapping_role(db, cf_role, cf_team_id) is None:
        raise HTTPException(status_code=400, detail=f"Role not found: {cf_role}")


def _check_null_tenant_duplicate(db: Session, issuer: str, external_group_id: str, exclude_id: Optional[int] = None) -> None:
    """Raise 409 when a NULL-tenant mapping already exists for (issuer, external_group_id).

    The plain unique constraint on (issuer, tenant, external_group_id) treats
    NULL tenants as distinct on SQLite and PostgreSQL, so the tenant-IS-NULL
    case is pre-checked here at the application level (and backstopped by the
    uq_external_group_mappings_null_tenant partial unique index).

    Args:
        db: Database session.
        issuer: Token issuer of the mapping being written.
        external_group_id: External group ID of the mapping being written.
        exclude_id: Mapping primary key to exclude (the row being updated).

    Raises:
        HTTPException: 409 when another NULL-tenant row already maps this
            (issuer, external_group_id) pair.
    """
    query = db.query(ExternalGroupMapping).filter(
        ExternalGroupMapping.issuer == issuer,
        ExternalGroupMapping.tenant.is_(None),
        ExternalGroupMapping.external_group_id == external_group_id,
    )
    if exclude_id is not None:
        query = query.filter(ExternalGroupMapping.id != exclude_id)
    if query.first() is not None:
        raise HTTPException(status_code=409, detail="Mapping already exists for (issuer, tenant, external_group_id)")


def _run_group_validation(mapping: ExternalGroupMapping, user, db: Session) -> None:
    """Run the group-existence validator and record the outcome on the row.

    WARN-AND-ALLOW: a validation_status of "unknown" (Graph unreachable) does
    not block the write. The outcome is audit-logged and a warning is emitted.

    Args:
        mapping: The mapping row to annotate.
        user: Authenticated user context for the audit entry.
        db: Database session for the audit entry.
    """
    status_value = group_exists_validator(mapping.issuer, mapping.tenant or "", mapping.external_group_id)
    mapping.validation_status = status_value
    mapping.last_validated_at = datetime.now(timezone.utc)
    if status_value == "unknown":
        logger.warning(
            "External group existence could not be validated (IdP unreachable); storing mapping with validation_status=unknown: issuer=%s external_group_id=%s",
            mapping.issuer,
            mapping.external_group_id,
        )
        try:
            get_security_logger().log_data_access(
                action="create",
                resource_type="external_group_mapping",
                resource_id=mapping.external_group_id,
                resource_name=mapping.external_group_id,
                user_id=get_user_email(user),
                user_email=get_user_email(user),
                team_id=mapping.cf_team_id,
                client_ip=user.get("ip_address") if isinstance(user, dict) else None,
                user_agent=user.get("user_agent") if isinstance(user, dict) else None,
                success=True,
                old_values=None,
                new_values={"validation_status": "unknown"},
                additional_context={"reason": "idp_unreachable_warn_and_allow"},
                db=db,
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Audit write for unvalidated external group mapping failed (write still proceeded): %s", exc)


@admin_external_group_mappings_router.post("", response_model=ExternalGroupMappingResponse)
@require_permission("admin.system_config")
async def create_external_group_mapping(
    body: ExternalGroupMappingCreate,
    request: Request,
    user=Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> ExternalGroupMapping:
    """Create an external group mapping.

    Args:
        body: Mapping fields.
        request: FastAPI request.
        user: Authenticated user context (injected).
        db: Database session (injected).

    Returns:
        ExternalGroupMapping: The stored mapping row.

    Raises:
        HTTPException: 400 on unknown team or role; 409 on duplicate
            (issuer, tenant, external_group_id).
    """
    _validate_team_exists(db, body.cf_team_id)
    _validate_role_exists(db, body.cf_role, body.cf_team_id)
    if body.tenant is None:
        _check_null_tenant_duplicate(db, body.issuer, body.external_group_id)

    mapping = ExternalGroupMapping(
        issuer=body.issuer,
        tenant=body.tenant,
        external_group_id=body.external_group_id,
        cf_team_id=body.cf_team_id,
        cf_role=body.cf_role,
    )
    _run_group_validation(mapping, user, db)
    db.add(mapping)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Mapping already exists for (issuer, tenant, external_group_id)") from exc
    db.refresh(mapping)
    await invalidate_external_identity_cache()
    return mapping


@admin_external_group_mappings_router.get("", response_model=List[ExternalGroupMappingResponse])
@require_permission("admin.system_config")
async def list_external_group_mappings(
    request: Request,
    user=Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> List[ExternalGroupMapping]:
    """List all external group mappings.

    Args:
        request: FastAPI request.
        user: Authenticated user context (injected).
        db: Database session (injected).

    Returns:
        List[ExternalGroupMapping]: All mapping rows, oldest first.
    """
    return db.query(ExternalGroupMapping).order_by(ExternalGroupMapping.id).all()


@admin_external_group_mappings_router.put("/{mapping_id}", response_model=ExternalGroupMappingResponse)
@require_permission("admin.system_config")
async def update_external_group_mapping(
    mapping_id: int,
    body: ExternalGroupMappingUpdate,
    request: Request,
    user=Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> ExternalGroupMapping:
    """Update an external group mapping.

    Args:
        mapping_id: Primary key of the mapping row.
        body: Fields to change; unset fields stay unchanged.
        request: FastAPI request.
        user: Authenticated user context (injected).
        db: Database session (injected).

    Returns:
        ExternalGroupMapping: The updated mapping row.

    Raises:
        HTTPException: 404 when the mapping does not exist; 400 on unknown
            team or role; 409 when the change violates the unique constraint.
    """
    mapping = db.query(ExternalGroupMapping).filter(ExternalGroupMapping.id == mapping_id).first()
    if not mapping:
        raise HTTPException(status_code=404, detail=f"External group mapping not found: {mapping_id}")

    updates = body.model_dump(exclude_unset=True)
    if "cf_team_id" in updates:
        _validate_team_exists(db, updates["cf_team_id"])
    if "cf_role" in updates:
        _validate_role_exists(db, updates["cf_role"], updates.get("cf_team_id", mapping.cf_team_id))
    # Pre-check the effective identity before mutating the row: applying the
    # updates first would let query autoflush hit the partial unique index
    # with a raw IntegrityError instead of the 409 below.
    if updates.get("tenant", mapping.tenant) is None:
        _check_null_tenant_duplicate(db, updates.get("issuer", mapping.issuer), updates.get("external_group_id", mapping.external_group_id), exclude_id=mapping.id)
    for field, value in updates.items():
        setattr(mapping, field, value)

    _run_group_validation(mapping, user, db)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Mapping already exists for (issuer, tenant, external_group_id)") from exc
    db.refresh(mapping)
    await invalidate_external_identity_cache()
    return mapping


@admin_external_group_mappings_router.delete("/{mapping_id}")
@require_permission("admin.system_config")
async def delete_external_group_mapping(
    mapping_id: int,
    request: Request,
    user=Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> dict:
    """Delete an external group mapping.

    Args:
        mapping_id: Primary key of the mapping row.
        request: FastAPI request.
        user: Authenticated user context (injected).
        db: Database session (injected).

    Returns:
        dict: Confirmation with the deleted mapping ID.

    Raises:
        HTTPException: 404 when the mapping does not exist.
    """
    mapping = db.query(ExternalGroupMapping).filter(ExternalGroupMapping.id == mapping_id).first()
    if not mapping:
        raise HTTPException(status_code=404, detail=f"External group mapping not found: {mapping_id}")
    db.delete(mapping)
    db.commit()
    await invalidate_external_identity_cache()
    return {"detail": "deleted", "id": mapping_id}
