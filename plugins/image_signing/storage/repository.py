#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/image_signing/storage/repository.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Xinyi, Liam

CRUD operations for trusted signers and verification result persistence.

Stable data contracts (do NOT modify):
    - TrustedSigner (types.py)
    - SignatureVerificationResult (types.py)
    - MatchResult (types.py)
    - PolicyDecision (types.py)

DB models (storage/models.py):
    - TrustedSignerRecord
    - SignatureVerificationRecord
"""

# Future
from __future__ import annotations

# Standard
from typing import List, Optional

# Third-Party
from sqlalchemy.ext.asyncio import AsyncSession

# First-Party
from plugins.image_signing.storage.models import (
    SignatureVerificationRecord,
    TrustedSignerRecord,
)
from plugins.image_signing.types import (
    SignatureVerificationResult,
    TrustedSigner,
)


# ---------------------------------------------------------------------------
# Trusted Signer CRUD
# ---------------------------------------------------------------------------
# TODO(Liam): All methods below should use AsyncSession for DB access.
#   Reference pattern: plugins/source_scanner/storage/repository.py
#   All IDs are UUID strings (uuid4), generate in create methods.
#   NOTE: Repository functions only call session.flush().
#   Commit/Rollback is handled by the caller (service/plugin) to keep transactions consistent.
# ---------------------------------------------------------------------------


async def list_trusted_signers(
    session: AsyncSession,
    enabled_only: bool = True,
) -> List[TrustedSigner]:
    """List all trusted signers from the database.

    TODO(Liam):
        - Query TrustedSignerRecord table
        - If enabled_only=True:
             filter:
                 - enabled == True
                 - (expires_at IS NULL OR expires_at > now_utc)
        - Convert each TrustedSignerRecord to TrustedSigner (types.py)
        - Order by created_at desc

    Args:
        session: Async database session.
        enabled_only: If True, return only enabled signers.

    Returns:
        List of TrustedSigner domain objects.
    """
    raise NotImplementedError


async def get_trusted_signer(
    session: AsyncSession,
    signer_id: str,
) -> Optional[TrustedSigner]:
    """Get a single trusted signer by ID.

    TODO(Liam):
        - Query TrustedSignerRecord by primary key
        - Return None if not found
        - Convert to TrustedSigner domain object

    Args:
        session: Async database session.
        signer_id: UUID string of the signer.

    Returns:
        TrustedSigner if found, None otherwise.
    """
    raise NotImplementedError


async def create_trusted_signer(
    session: AsyncSession,
    signer: TrustedSigner,
) -> TrustedSigner:
    """Create a new trusted signer record.

    TODO(Liam):
        - If signer.id is empty/blank, generate uuid4; otherwise use provided id.
          (But backend-generated IDs are recommended.)
        - Map TrustedSigner fields to TrustedSignerRecord columns:
            signer.type.value -> signer_type
            signer.oidc_issuer -> oidc_issuer
            signer.subject -> subject
            signer.subject_regex -> subject_regex
            signer.public_key -> public_key
            signer.kms_key_ref -> kms_key_ref
        - session.add() + session.flush()
        - Return the created TrustedSigner

    Args:
        session: Async database session.
        signer: TrustedSigner domain object to persist.

    Returns:
        Created TrustedSigner with generated ID.
    """
    raise NotImplementedError


async def update_trusted_signer(
    session: AsyncSession,
    signer_id: str,
    updates: dict[str, object],
) -> Optional[TrustedSigner]:
    """Update an existing trusted signer.

    TODO(Liam):
        - Fetch TrustedSignerRecord by ID
        - Return None if not found
        - Apply updates dict to record fields
        - Validate: do NOT allow changing signer_type after creation
        - session.flush()
        - Return updated TrustedSigner
    NOTE: Allowed update fields:
           name, oidc_issuer, subject, subject_regex, public_key, kms_key_ref, enabled, expires_at
          Disallowed fields:
           id, signer_type, created_at, created_by
          Behavior:
           - If updates contains disallowed keys -> raise ValueError

    Args:
        session: Async database session.
        signer_id: UUID string of the signer to update.
        updates: Dictionary of field names to new values.

    Returns:
        Updated TrustedSigner if found, None otherwise.
    """
    raise NotImplementedError


async def delete_trusted_signer(
    session: AsyncSession,
    signer_id: str,
) -> bool:
    """Delete a trusted signer by ID.

    TODO(Liam):
        - Fetch TrustedSignerRecord by ID
        - Return False if not found
        - session.delete()
        - Return True on success

    Args:
        session: Async database session.
        signer_id: UUID string of the signer to delete.

    Returns:
        True if deleted, False if not found.
    """
    raise NotImplementedError


# ---------------------------------------------------------------------------
# Verification Result Persistence
# ---------------------------------------------------------------------------
# TODO(Liam): These methods store/query SignatureVerificationRecord.
#   The plugin calls save_verification_result after each image check.
#   assessment_id links to the security assessment pipeline (#2215).
# ---------------------------------------------------------------------------


async def save_verification_result(
    session: AsyncSession,
    result: SignatureVerificationResult,
    assessment_id: Optional[str] = None,
) -> str:
    """Persist a signature verification result to the database.

    TODO(Liam):
        - Generate UUID for record ID
        - Map SignatureVerificationResult fields to SignatureVerificationRecord:
            result.image_ref -> image_ref
            result.image_digest -> image_digest
            result.signature_found -> signature_found
            result.signature_valid -> record.signature_valid
            result.signer_identity -> signer_identity
            result.signer_issuer -> signer_issuer
            result.signed_at -> signed_at
            result.rekor_verified -> rekor_verified
            result.slsa.level -> slsa_level
            result.slsa.builder -> slsa_builder
            result.blocked -> blocked
            result.reason -> reason
        - Set assessment_id if provided
        - session.add() + session.flush()
        - Return the generated record ID

    Args:
        session: Async database session.
        result: Verification result to persist.
        assessment_id: Optional security assessment ID for linking.

    Returns:
        Generated UUID string of the persisted record.
    """
    raise NotImplementedError


async def get_verification_history(
    session: AsyncSession,
    image_ref: Optional[str] = None,
    assessment_id: Optional[str] = None,
    limit: int = 50,
) -> List[SignatureVerificationResult]:
    """Query verification history with optional filters.

    TODO(Liam):
        - Query SignatureVerificationRecord table
        - Filter by image_ref if provided
        - Filter by assessment_id if provided
        - Order by created_at desc
        - Apply limit
        - Convert each record to SignatureVerificationResult

    Args:
        session: Async database session.
        image_ref: Optional image reference to filter by.
        assessment_id: Optional assessment ID to filter by.
        limit: Maximum number of results to return.

    Returns:
        List of SignatureVerificationResult domain objects.
    """
    raise NotImplementedError


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------
# TODO(Liam): Implement these two helpers for mapping between DB and domain.
# ---------------------------------------------------------------------------


def _record_to_signer(record: TrustedSignerRecord) -> TrustedSigner:
    """Convert a TrustedSignerRecord ORM object to a TrustedSigner domain object.

    TODO(Liam):
        - Map record.signer_type -> SignerType enum
        - Map all other fields directly
        - Handle nullable fields
        - return TrustedSigner(
            id=record.id,
            name=record.name,
            type=SignerType(record.signer_type),
            oidc_issuer=record.oidc_issuer,
            subject=record.subject,
            subject_regex=record.subject_regex,
            public_key=record.public_key,
            kms_key_ref=record.kms_key_ref,
            enabled=record.enabled,
            expires_at=record.expires_at,
          )

    Args:
        record: ORM record from database.

    Returns:
        TrustedSigner domain object.
    """
    raise NotImplementedError


def _record_to_result(record: SignatureVerificationRecord) -> SignatureVerificationResult:
    """Convert a SignatureVerificationRecord to a SignatureVerificationResult.

    TODO(Liam):
        - Map flat DB fields to nested SlsaResult for slsa_level/slsa_builder
        - Handle nullable fields
        - return SignatureVerificationResult(
            image_ref=record.image_ref,
            image_digest=record.image_digest,
            signature_found=record.signature_found,
            signature_valid=bool(record.signature_valid) if record.signature_valid is not None else False,
            signer_identity=record.signer_identity,
            signer_issuer=record.signer_issuer,
            signed_at=record.signed_at,
            rekor_verified=record.rekor_verified,
            slsa=SlsaResult(level=record.slsa_level, builder=record.slsa_builder),
            blocked=record.blocked,
            reason=record.reason,   
          )
    Args:
        record: ORM record from database.

    Returns:
        SignatureVerificationResult domain object.
    """
    raise NotImplementedError