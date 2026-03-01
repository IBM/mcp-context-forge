# -*- coding: utf-8 -*-
"""Location: ./plugins/image_signing/storage/models.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Xinyi

SQLAlchemy ORM models for Image Signing & Verification persistence layer.
"""

# Standard
from datetime import datetime, timezone

# Third-Party
from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import declarative_base, Mapped, mapped_column

Base = declarative_base()


class TrustedSignerRecord(Base):
    """ORM model for trusted signer configurations."""

    __tablename__ = "image_signing_trusted_signers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    signer_type: Mapped[str] = mapped_column(String(20), nullable=False)  # keyless, public_key, kms

    # Keyless fields
    oidc_issuer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject_regex: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Key fields
    public_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    kms_key_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        Index("idx_trusted_signer_type", "signer_type"),
        Index("idx_trusted_signer_enabled", "enabled"),
        Index("idx_trusted_signer_issuer", "oidc_issuer"),
    )

    def __repr__(self) -> str:
        """Return string representation.

        Returns:
            str: String representation of TrustedSignerRecord.
        """
        return f"<TrustedSignerRecord(id={self.id}, name={self.name}, type={self.signer_type})>"


class SignatureVerificationRecord(Base):
    """ORM model for signature verification results."""

    __tablename__ = "image_signing_verifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    assessment_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    image_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    image_digest: Mapped[str | None] = mapped_column(String(100), nullable=True)

    signature_found: Mapped[bool] = mapped_column(Boolean, nullable=False)
    signature_valid: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    signer_identity: Mapped[str | None] = mapped_column(String(255), nullable=True)
    signer_issuer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    rekor_verified: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    slsa_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    slsa_builder: Mapped[str | None] = mapped_column(String(255), nullable=True)

    blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    verification_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    __table_args__ = (
        Index("idx_verification_image_ref", "image_ref"),
        Index("idx_verification_assessment", "assessment_id", "created_at"),
    )

    def __repr__(self) -> str:
        """Return string representation.

        Returns:
            str: String representation of SignatureVerificationRecord.
        """
        return f"<SignatureVerificationRecord(id={self.id}, image={self.image_ref}, blocked={self.blocked})>"