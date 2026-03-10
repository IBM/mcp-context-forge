#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/image_signing_router.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Xinyi

REST API endpoints for Image Signing & Verification plugin.
"""

# Future
from __future__ import annotations

# Standard
from datetime import datetime
from typing import List, Optional
from types import SimpleNamespace

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import SessionLocal
from plugins.image_signing.storage.repository import ImageSigningRepository
from plugins.image_signing.types import (
    SignatureVerificationResult,
    SignerType,
    TrustedSigner,
)
from plugins.image_signing.image_signing import ImageSigningPlugin

router = APIRouter(
    prefix="/api/v1/image-signing",
    tags=["image-signing"],
)

templates = Jinja2Templates(directory="mcpgateway/templates")


# ---------------------------------------------------------------------------
# Database dependency
# ---------------------------------------------------------------------------


def get_db():
    """Database dependency for image signing endpoints.

    Commits the transaction on successful completion to avoid implicit rollbacks
    for read-only operations. Rolls back explicitly on exception.

    Yields:
        Session: SQLAlchemy database session.
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        raise
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class CreateSignerRequest(BaseModel):
    """Request body for creating a trusted signer."""

    name: str
    type: SignerType
    oidc_issuer: Optional[str] = None
    subject: Optional[str] = None
    subject_regex: Optional[str] = None
    public_key: Optional[str] = None
    kms_key_ref: Optional[str] = None
    enabled: bool = True
    expires_at: Optional[datetime] = None

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("name must not be empty")
        return v.strip()    


class UpdateSignerRequest(BaseModel):
    """Request body for updating a trusted signer."""

    name: Optional[str] = None
    oidc_issuer: Optional[str] = None
    subject: Optional[str] = None
    subject_regex: Optional[str] = None
    public_key: Optional[str] = None
    kms_key_ref: Optional[str] = None
    enabled: Optional[bool] = None
    expires_at: Optional[datetime] = None


class VerifyRequest(BaseModel):
    """Request body for triggering manual image verification."""

    image_ref: str
    image_digest: Optional[str] = None

    @field_validator("image_digest")
    @classmethod
    def _validate_digest(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.startswith("sha256:"):
            raise ValueError("image_digest must start with 'sha256:'")
        return v


class SignerResponse(BaseModel):
    """Response body for a trusted signer (sensitive fields excluded)."""

    id: str
    name: str
    type: SignerType
    oidc_issuer: Optional[str] = None
    subject: Optional[str] = None
    subject_regex: Optional[str] = None
    enabled: bool = True
    expires_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _signer_to_response(signer: TrustedSigner) -> SignerResponse:
    """Convert TrustedSigner to SignerResponse (exclude sensitive fields).

    Args:
        signer: TrustedSigner domain object.

    Returns:
        SignerResponse without public_key / kms_key_ref.
    """
    return SignerResponse(
        id=signer.id,
        name=signer.name,
        type=signer.type,
        oidc_issuer=signer.oidc_issuer,
        subject=signer.subject,
        subject_regex=signer.subject_regex,
        enabled=signer.enabled,
        expires_at=signer.expires_at,
    )


def _build_plugin() -> ImageSigningPlugin:
    """Create ImageSigningPlugin with an empty/default plugin config."""
    fake_plugin_config = SimpleNamespace(config={})
    return ImageSigningPlugin(fake_plugin_config)


# ---------------------------------------------------------------------------
# Trusted Signers CRUD
# ---------------------------------------------------------------------------


@router.get("/signers", response_model=List[SignerResponse])
def list_signers(
    enabled: Optional[bool] = Query(None, description="Filter by enabled status"),
    db: Session = Depends(get_db),
) -> List[SignerResponse]:
    repo = ImageSigningRepository(db)

    if enabled is None:
        signers = repo.list_trusted_signers(enabled_only=False)
    elif enabled is True:
        signers = repo.list_trusted_signers(enabled_only=True)
    else:
        signers = [
            s for s in repo.list_trusted_signers(enabled_only=False)
            if s.enabled is False
        ]

    return [_signer_to_response(s) for s in signers]


@router.get("/signers/{signer_id}", response_model=SignerResponse)
def get_signer(
    signer_id: str,
    db: Session = Depends(get_db),
) -> SignerResponse:
    """Get a single trusted signer by ID."""
    repo = ImageSigningRepository(db)
    signer = repo.get_trusted_signer(signer_id)
    if signer is None:
        raise HTTPException(status_code=404, detail="Signer not found")
    return _signer_to_response(signer)


@router.post("/signers", response_model=SignerResponse, status_code=201)
def create_signer(
    request: CreateSignerRequest,
    db: Session = Depends(get_db),
) -> SignerResponse:
    """Create a new trusted signer."""
    signer = TrustedSigner(
        id="",
        name=request.name,
        type=request.type,
        oidc_issuer=request.oidc_issuer,
        subject=request.subject,
        subject_regex=request.subject_regex,
        public_key=request.public_key,
        kms_key_ref=request.kms_key_ref,
        enabled=request.enabled,
        expires_at=request.expires_at,
    )

    repo = ImageSigningRepository(db)
    created = repo.create_trusted_signer(signer)
    return _signer_to_response(created)


@router.patch("/signers/{signer_id}", response_model=SignerResponse)
def update_signer(
    signer_id: str,
    request: UpdateSignerRequest,
    db: Session = Depends(get_db),
) -> SignerResponse:
    """Update an existing trusted signer."""
    updates = request.model_dump(exclude_none=True)
    if "type" in updates:
        updates["signer_type"] = updates.pop("type")

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    repo = ImageSigningRepository(db)
    try:
        updated = repo.update_trusted_signer(signer_id, updates)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if updated is None:
        raise HTTPException(status_code=404, detail="Signer not found")

    return _signer_to_response(updated)


@router.delete("/signers/{signer_id}", status_code=204)
def delete_signer(
    signer_id: str,
    db: Session = Depends(get_db),
) -> None:
    """Delete a trusted signer."""
    repo = ImageSigningRepository(db)
    if not repo.delete_trusted_signer(signer_id):
        raise HTTPException(status_code=404, detail="Signer not found")


# ---------------------------------------------------------------------------
# Verification endpoints
# ---------------------------------------------------------------------------


@router.get("/verifications", response_model=List[SignatureVerificationResult])
def list_verifications(
    image_ref: Optional[str] = Query(None, description="Filter by image reference"),
    assessment_id: Optional[str] = Query(None, description="Filter by assessment ID"),
    limit: int = Query(50, ge=1, le=200, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    db: Session = Depends(get_db),
) -> List[SignatureVerificationResult]:
    """Query verification history."""
    repo = ImageSigningRepository(db)
    return repo.get_verification_history(
        image_ref=image_ref,
        assessment_id=assessment_id,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/verify",
    response_model=SignatureVerificationResult,
    summary="Manually verify an image signature",
)
async def verify_image_endpoint(
    request: VerifyRequest,
) -> SignatureVerificationResult:
    """Manually trigger image signature verification for a container image."""
    try:
        plugin = _build_plugin()
        result = await plugin.verify_image(
            image_ref=request.image_ref,
            image_digest=request.image_digest,
        )
        return result
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Image verification failed: {exc}",
        ) from exc


# ---------------------------------------------------------------------------
# Admin UI partial
# ---------------------------------------------------------------------------


@router.get("/partial", response_class=HTMLResponse, include_in_schema=False)
async def image_signing_partial(request: Request) -> HTMLResponse:
    """Serve the Admin UI partial for the image-signing tab."""
    return templates.TemplateResponse(
        "image_signing_partial.html",
        {"request": request},
    )