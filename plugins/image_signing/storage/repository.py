#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/image_signing/storage/repository.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Xinyi

CRUD operations for trusted signers and verification result persistence.
"""

# Future
from __future__ import annotations

# Standard
import uuid
from datetime import datetime, timezone
from typing import List, Optional

# Third-Party
from sqlalchemy import select
from sqlalchemy.orm import Session

# First-Party
from plugins.image_signing.storage.models import (
    SignatureVerificationRecord,
    TrustedSignerRecord,
)
from plugins.image_signing.types import (
    SignatureVerificationResult,
    SignerType,
    SlsaResult,
    TrustedSigner,
)


class ImageSigningRepository:
    """Repository for trusted signers and verification results."""

    def __init__(self, db: Session) -> None:
        """Initialize repository with database session.

        Args:
            db: SQLAlchemy database session.
        """
        self.db = db

    # ------------------------------------------------------------------
    # Trusted Signer CRUD
    # ------------------------------------------------------------------

    def list_trusted_signers(self, enabled_only: bool = True) -> List[TrustedSigner]:
        """List all trusted signers from the database.

        Args:
            enabled_only: If True, return only enabled and non-expired signers.

        Returns:
            List of TrustedSigner domain objects.
        """
        query = self.db.query(TrustedSignerRecord)

        if enabled_only:
            now = datetime.now(timezone.utc)
            query = query.filter(TrustedSignerRecord.enabled == True)  # noqa: E712
            query = query.filter(
                (TrustedSignerRecord.expires_at.is_(None))
                | (TrustedSignerRecord.expires_at > now)
            )

        return [
            _record_to_signer(record)
            for record in query.order_by(TrustedSignerRecord.created_at.desc()).all()
        ]

    def get_trusted_signer(self, signer_id: str) -> Optional[TrustedSigner]:
        """Get a single trusted signer by ID.

        Args:
            signer_id: UUID string of the signer.

        Returns:
            TrustedSigner if found, None otherwise.
        """
        record = self.db.query(TrustedSignerRecord).filter(
            TrustedSignerRecord.id == signer_id
        ).first()

        if record is None:
            return None

        return _record_to_signer(record)

    def create_trusted_signer(self, signer: TrustedSigner) -> TrustedSigner:
        """Create a new trusted signer record.

        Args:
            signer: TrustedSigner domain object to persist.

        Returns:
            Created TrustedSigner with generated ID.
        """
        signer_id = signer.id if signer.id and signer.id.strip() else str(uuid.uuid4())

        record = TrustedSignerRecord(
            id=signer_id,
            name=signer.name,
            signer_type=signer.type.value,
            oidc_issuer=signer.oidc_issuer,
            subject=signer.subject,
            subject_regex=signer.subject_regex,
            public_key=signer.public_key,
            kms_key_ref=signer.kms_key_ref,
            enabled=signer.enabled,
            expires_at=signer.expires_at,
        )

        self.db.add(record)
        self.db.flush()

        return _record_to_signer(record)

    def update_trusted_signer(
        self,
        signer_id: str,
        updates: dict[str, object],
    ) -> Optional[TrustedSigner]:
        """Update an existing trusted signer.

        Args:
            signer_id: UUID string of the signer to update.
            updates: Dictionary of field names to new values.

        Returns:
            Updated TrustedSigner if found, None otherwise.

        Raises:
            ValueError: If updates contain disallowed fields.
        """
        disallowed = {"id", "signer_type", "created_at", "created_by"}
        bad_keys = disallowed & set(updates.keys())
        if bad_keys:
            raise ValueError(f"Cannot update disallowed fields: {bad_keys}")

        record = self.db.query(TrustedSignerRecord).filter(
            TrustedSignerRecord.id == signer_id
        ).first()

        if record is None:
            return None

        for key, value in updates.items():
            if hasattr(record, key):
                setattr(record, key, value)

        self.db.flush()

        return _record_to_signer(record)

    def delete_trusted_signer(self, signer_id: str) -> bool:
        """Delete a trusted signer by ID.

        Args:
            signer_id: UUID string of the signer to delete.

        Returns:
            True if deleted, False if not found.
        """
        record = self.db.query(TrustedSignerRecord).filter(
            TrustedSignerRecord.id == signer_id
        ).first()

        if record is None:
            return False

        self.db.delete(record)
        self.db.flush()
        return True

    # ------------------------------------------------------------------
    # Verification Result Persistence
    # ------------------------------------------------------------------

    def save_verification_result(
        self,
        result: SignatureVerificationResult,
        assessment_id: Optional[str] = None,
    ) -> str:
        """Persist a signature verification result to the database.

        Args:
            result: Verification result to persist.
            assessment_id: Optional security assessment ID for linking.

        Returns:
            Generated UUID string of the persisted record.
        """
        record_id = str(uuid.uuid4())

        record = SignatureVerificationRecord(
            id=record_id,
            assessment_id=assessment_id,
            image_ref=result.image_ref,
            image_digest=result.image_digest,
            signature_found=result.signature_found,
            signature_valid=result.signature_valid,
            signer_identity=result.signer_identity,
            signer_issuer=result.signer_issuer,
            signed_at=result.signed_at,
            rekor_verified=result.rekor_verified,
            slsa_level=result.slsa.level if result.slsa else None,
            slsa_builder=result.slsa.builder if result.slsa else None,
            blocked=result.blocked,
            reason=result.reason,
        )

        self.db.add(record)
        self.db.flush()

        return record_id

    def get_verification_history(
        self,
        image_ref: Optional[str] = None,
        assessment_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[SignatureVerificationResult]:
        """Query verification history with optional filters.

        Args:
            image_ref: Optional image reference to filter by.
            assessment_id: Optional assessment ID to filter by.
            limit: Maximum number of results to return.
            offset: Number of results to skip.

        Returns:
            List of SignatureVerificationResult domain objects.
        """
        query = self.db.query(SignatureVerificationRecord)

        if image_ref:
            query = query.filter(SignatureVerificationRecord.image_ref == image_ref)
        if assessment_id:
            query = query.filter(SignatureVerificationRecord.assessment_id == assessment_id)

        records = (
            query
            .order_by(SignatureVerificationRecord.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

        return [_record_to_result(record) for record in records]


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------


def _record_to_signer(record: TrustedSignerRecord) -> TrustedSigner:
    """Convert a TrustedSignerRecord ORM object to a TrustedSigner domain object.

    Args:
        record: ORM record from database.

    Returns:
        TrustedSigner domain object.
    """
    return TrustedSigner(
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


def _record_to_result(record: SignatureVerificationRecord) -> SignatureVerificationResult:
    """Convert a SignatureVerificationRecord to a SignatureVerificationResult.

    Args:
        record: ORM record from database.

    Returns:
        SignatureVerificationResult domain object.
    """
    return SignatureVerificationResult(
        image_ref=record.image_ref,
        image_digest=record.image_digest,
        signature_found=record.signature_found,
        signature_valid=bool(record.signature_valid) if record.signature_valid is not None else False,
        signer_identity=record.signer_identity,
        signer_issuer=record.signer_issuer,
        signed_at=record.signed_at,
        rekor_verified=record.rekor_verified,
        slsa=SlsaResult(
            level=record.slsa_level,
            builder=record.slsa_builder,
        ),
        blocked=record.blocked,
        reason=record.reason,
    )