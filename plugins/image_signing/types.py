# -*- coding: utf-8 -*-
"""Location: ./plugins/image_signing/types.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Xinyi

Unified result schemas for the Image Signing & Verification plugin.
"""

# Future
from __future__ import annotations

# Standard
from datetime import datetime
from enum import Enum
from typing import Optional

# Third-Party
from pydantic import BaseModel, Field, model_validator


class SignerType(str, Enum):
    """Supported signer types."""

    KEYLESS = "keyless"
    PUBLIC_KEY = "public_key"
    KMS = "kms"


class EnforcementMode(str, Enum):
    """Plugin enforcement modes."""

    AUDIT = "audit"
    ENFORCE = "enforce"


class TrustedSigner(BaseModel):
    """Trusted signer configuration.

    Attributes:
        id: Unique identifier for the signer.
        name: Human-readable signer name.
        type: Signer type (keyless, public_key, kms).
        oidc_issuer: OIDC issuer URL for keyless signers.
        subject: Exact subject identity for keyless signers.
        subject_regex: Regex pattern for subject matching.
        public_key: PEM-encoded public key for public_key signers.
        kms_key_ref: KMS key reference URI for kms signers.
        enabled: Whether the signer is currently active.
        expires_at: Optional expiration timestamp.
    """

    id: str
    name: str
    type: SignerType
    oidc_issuer: Optional[str] = None
    subject: Optional[str] = None
    subject_regex: Optional[str] = None
    public_key: Optional[str] = None
    kms_key_ref: Optional[str] = None
    enabled: bool = True
    expires_at: Optional[datetime] = None

    @model_validator(mode="after")
    def validate_by_type(self) -> "TrustedSigner":
        if self.type == SignerType.KEYLESS:
            if not self.oidc_issuer:
                raise ValueError("KEYLESS signer requires oidc_issuer")
            if self.subject and self.subject_regex:
                raise ValueError("KEYLESS signer must not set both subject and subject_regex")
            if not (self.subject or self.subject_regex):
                raise ValueError("KEYLESS signer requires subject or subject_regex")

        elif self.type == SignerType.PUBLIC_KEY:
            if not self.public_key:
                raise ValueError("PUBLIC_KEY signer requires public_key (PEM)")

        elif self.type == SignerType.KMS:
            if not self.kms_key_ref:
                raise ValueError("KMS signer requires kms_key_ref")

        return self


class VerificationResult(BaseModel):
    """Cosign signature verification output.

    Attributes:
        signature_found: Whether a signature was found for the image.
        signature_valid: Whether the signature is cryptographically valid.
        signer_identity: Identity of the signer (e.g. email or URI).
        signer_issuer: OIDC issuer of the signer.
        signed_at: Timestamp when the image was signed.
        rekor_verified: Whether the Rekor transparency log entry was verified.
        error: Error message if verification failed.
    """

    signature_found: bool
    signature_valid: bool = False
    signer_identity: Optional[str] = None
    signer_issuer: Optional[str] = None
    signed_at: Optional[datetime] = None
    rekor_verified: Optional[bool] = None
    error: Optional[str] = None


class AttestationResult(BaseModel):
    """SLSA attestation verification output.

    Attributes:
        attestation_found: Whether an attestation was found for the image.
        valid: Whether the attestation is valid.
        level: SLSA level extracted from the attestation.
        builder: Builder identity from the attestation.
    """

    attestation_found: bool
    valid: bool = False
    level: Optional[int] = None
    builder: Optional[str] = None


class MatchResult(BaseModel):
    """Trusted signer matching output.

    Attributes:
        matched: Whether the signer matched a trusted signer.
        matched_signer_id: Unique identifier of the matched trusted signer, if any.
        matched_signer_name: Human-readable name of the matched trusted signer, if any.

    """

    matched: bool
    matched_signer_id: Optional[str] = None
    matched_signer_name: Optional[str] = None


class PolicyDecision(BaseModel):
    """Policy evaluation output.

    Attributes:
        blocked: Whether the image deployment should be blocked.
        reason: Reason for blocking, if applicable.
    """

    blocked: bool
    reason: Optional[str] = None


class SlsaResult(BaseModel):
    """SLSA verification summary embedded in the final result.

    Attributes:
        attestation_found: Whether an attestation was found.
        level: SLSA level extracted from the attestation.
        builder: Builder identity from the attestation.
    """

    attestation_found: Optional[bool] = None
    level: Optional[int] = None
    builder: Optional[str] = None


class SignatureVerificationResult(BaseModel):
    """Final unified result returned by the ImageSigningPlugin.

    Attributes:
        image_ref: Container image reference (e.g. registry/repo:tag).
        image_digest: Image digest (e.g. sha256:abc...).
        signature_found: Whether a signature was found.
        signature_valid: Whether the signature is valid.
        signer_identity: Identity of the signer.
        signer_issuer: OIDC issuer of the signer.
        signed_at: Timestamp when the image was signed.
        rekor_verified: Whether the Rekor transparency log entry was verified.
        slsa: SLSA verification summary.
        blocked: Whether the image deployment is blocked.
        reason: Reason for blocking, if applicable.
    """

    image_ref: str
    image_digest: Optional[str] = None
    signature_found: bool = False
    signature_valid: bool = False
    signer_identity: Optional[str] = None
    signer_issuer: Optional[str] = None
    signed_at: Optional[datetime] = None
    rekor_verified: Optional[bool] = None
    slsa: SlsaResult = Field(default_factory=SlsaResult)
    blocked: bool = False
    reason: Optional[str] = None