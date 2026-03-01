#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/image_signing_router.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Xinyi, Liam

REST API endpoints for Image Signing & Verification plugin.

Endpoints:
    Trusted Signers CRUD:
        GET    /api/v1/image-signing/signers          - List all trusted signers
        GET    /api/v1/image-signing/signers/{id}      - Get a single signer
        POST   /api/v1/image-signing/signers           - Create a new signer
        PATCH  /api/v1/image-signing/signers/{id}      - Update a signer
        DELETE /api/v1/image-signing/signers/{id}      - Delete a signer

    Verification:
        GET    /api/v1/image-signing/verifications      - Query verification history
        POST   /api/v1/image-signing/verify             - Trigger manual verification

Stable data contracts (do NOT modify):
    - TrustedSigner (plugins/image_signing/types.py)
    - SignatureVerificationResult (plugins/image_signing/types.py)

Reference pattern: mcpgateway/routers/source_scanner_router.py
"""

# Future
from __future__ import annotations

# Standard
from typing import List, Optional
from datetime import datetime

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

# First-Party
from plugins.image_signing.types import (
    SignatureVerificationResult,
    SignerType,
    TrustedSigner,
)

router = APIRouter(
    prefix="/api/v1/image-signing",
    tags=["image-signing"],
)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------
# TODO(Liam): These are separate from domain types to decouple API surface
#   from internal models. Add validation as needed.
# ---------------------------------------------------------------------------


class CreateSignerRequest(BaseModel):
    """Request body for creating a trusted signer.

    TODO(Liam):
        - Validate that keyless signers have oidc_issuer + (subject or subject_regex)
        - Validate that public_key signers have public_key
        - Validate that kms signers have kms_key_ref
        - Can reuse TrustedSigner.validate_by_type logic or call it after mapping
    """

    name: str
    type: SignerType
    oidc_issuer: Optional[str] = None
    subject: Optional[str] = None
    subject_regex: Optional[str] = None
    public_key: Optional[str] = None
    kms_key_ref: Optional[str] = None
    enabled: bool = True
    expires_at: Optional[datetime] = None


class UpdateSignerRequest(BaseModel):
    """Request body for updating a trusted signer.

    TODO(Liam):
        - All fields optional (partial update)
        - Do NOT allow changing type (enforced in repository layer)
    """

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
        if v is None:
            return v
        if not v.startswith("sha256:"):
            raise ValueError("image_digest must start with 'sha256:'")
        return v

class SignerResponse(BaseModel):
    """Response body for a trusted signer.

    TODO(Liam):
         - public_key / kms_key_ref are NOT returned by default (sensitive).
         - If needed in UI later, only return a masked preview (e.g., first/last 6 chars).
         - created_at and expires_at are returned for admin visibility.
    """

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
# Trusted Signers CRUD
# ---------------------------------------------------------------------------
# TODO(Liam): All endpoints need DB session dependency injection.
#   Reference: how source_scanner_router.py gets its session.
#   All endpoints should return proper HTTP status codes:
#     201 for create, 200 for get/update, 204 for delete, 404 for not found.
# ---------------------------------------------------------------------------


@router.get("/signers", response_model=List[SignerResponse])
async def list_signers(
    enabled_only: bool = Query(True, description="Filter to enabled signers only"),
) -> List[SignerResponse]:
    """List all trusted signers.

    TODO(Liam):
        - Inject AsyncSession dependency
        - Call repository.list_trusted_signers(session, enabled_only)
        - Convert TrustedSigner -> SignerResponse (exclude sensitive fields)
        - Return list
    """
    raise NotImplementedError


@router.get("/signers/{signer_id}", response_model=SignerResponse)
async def get_signer(signer_id: str) -> SignerResponse:
    """Get a single trusted signer by ID.

    TODO(Liam):
        - Inject AsyncSession dependency
        - Call repository.get_trusted_signer(session, signer_id)
        - Raise HTTPException(404) if not found
        - Convert to SignerResponse
    """
    raise NotImplementedError


@router.post("/signers", response_model=SignerResponse, status_code=201)
async def create_signer(request: CreateSignerRequest) -> SignerResponse:
    """Create a new trusted signer.

    TODO(Liam):
        - Inject AsyncSession dependency
        - Map CreateSignerRequest -> TrustedSigner domain object
        - Call repository.create_trusted_signer(session, signer)
        - session.commit()
        - Convert to SignerResponse
    """
    raise NotImplementedError


@router.patch("/signers/{signer_id}", response_model=SignerResponse)
async def update_signer(signer_id: str, request: UpdateSignerRequest) -> SignerResponse:
    """Update an existing trusted signer.

    TODO(Liam):
        - Inject AsyncSession dependency
        - Build updates dict from request:
            updates = request.model_dump(exclude_none=True)
          NOTE:
           - None means "not provided" (no update)
           - Clearing a field to NULL is not supported in MVP
        - Call repository.update_trusted_signer(session, signer_id, updates)
        - Raise HTTPException(404) if not found
        - session.commit()
        - Convert to SignerResponse
    """
    raise NotImplementedError


@router.delete("/signers/{signer_id}", status_code=204)
async def delete_signer(signer_id: str) -> None:
    """Delete a trusted signer.

    TODO(Liam):
        - Inject AsyncSession dependency
        - Call repository.delete_trusted_signer(session, signer_id)
        - Raise HTTPException(404) if not found
        - session.commit()
    """
    raise NotImplementedError


# ---------------------------------------------------------------------------
# Verification endpoints
# ---------------------------------------------------------------------------
# TODO(Liam): These endpoints integrate with the plugin's verify flow.
#   The POST /verify endpoint triggers manual verification outside the
#   normal security assessment pipeline.
# ---------------------------------------------------------------------------


@router.get("/verifications", response_model=List[SignatureVerificationResult])
async def list_verifications(
    image_ref: Optional[str] = Query(None, description="Filter by image reference"),
    assessment_id: Optional[str] = Query(None, description="Filter by assessment ID"),
    limit: int = Query(50, ge=1, le=200, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
) -> List[SignatureVerificationResult]:
    """Query verification history.

    TODO(Liam):
        - Inject AsyncSession dependency
        - Call repository.get_verification_history(session, image_ref, assessment_id, limit, offset)
        - repository.get_verification_history should support offset
        - Return list
    """
    raise NotImplementedError


@router.post("/verify", response_model=SignatureVerificationResult)
async def verify_image(request: VerifyRequest) -> SignatureVerificationResult:
    """Trigger manual image signature verification.

    TODO(Liam):
        - Require admin/auth for this endpoint (manual verification)
        - Inject AsyncSession dependency
        - Get ImageSigningPlugin instance (from app state or dependency)
        - Call plugin.verify(image_ref, image_digest)
        - Save result via repository.save_verification_result(session, result)
        - session.commit()
        - Return result

    NOTE: This is for ad-hoc verification. Normal flow goes through
        the security assessment pipeline hook.
    """
    raise NotImplementedError