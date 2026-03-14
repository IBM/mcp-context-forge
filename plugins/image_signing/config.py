# -*- coding: utf-8 -*-
"""Location: ./plugins/image_signing/config.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Xinyi

Plugin configuration models and defaults for the Image Signing & Verification plugin.
"""

# Future
from __future__ import annotations

# Standard
from typing import List, Optional

# Third-Party
from pydantic import BaseModel, Field, ConfigDict

# First-Party
from plugins.image_signing.types import EnforcementMode, SignerType


class TrustedSignerConfig(BaseModel):
    """Inline trusted signer configuration entry.

    Attributes:
        type: Signer type (keyless, public_key, kms).
        issuer: OIDC issuer URL for keyless signers.
        subject: Exact subject identity for keyless signers.
        subject_regex: Regex pattern for subject matching.
        public_key: PEM-encoded public key for public_key signers.
        kms_key_ref: KMS key reference URI for kms signers.
    """
    model_config = ConfigDict(populate_by_name=True)

    type: SignerType
    oidc_issuer: Optional[str] = Field(default=None, alias="issuer")
    subject: Optional[str] = None
    subject_regex: Optional[str] = None
    public_key: Optional[str] = None
    kms_key_ref: Optional[str] = None


class VerificationConfig(BaseModel):
    """Signature verification settings.

    Attributes:
        require_signature: Whether a valid signature is required.
        verify_transparency_log: Whether to verify Rekor transparency log entries.
        offline_mode: Whether to run in offline mode (skip online lookups).
    """

    require_signature: bool = True
    verify_transparency_log: bool = True
    offline_mode: bool = False


class SlsaConfig(BaseModel):
    """SLSA attestation verification settings.

    Attributes:
        require_attestation: Whether SLSA attestation is required.
        minimum_level: Minimum acceptable SLSA level.
        trusted_builders: List of trusted builder identities.
    """

    require_attestation: bool = False
    minimum_level: int = 1
    trusted_builders: List[str] = Field(default_factory=list)


class CosignConfig(BaseModel):
    """Cosign CLI settings.

    Attributes:
        path: Path to the Cosign binary.
        timeout_seconds: Maximum time in seconds for a Cosign invocation.
    """

    path: str = "/usr/local/bin/cosign"
    timeout_seconds: int = 30


class ImageSigningConfig(BaseModel):
    """Top-level configuration for the ImageSigningPlugin.

    Attributes:
        mode: Enforcement mode (audit or enforce).
        verification: Signature verification settings.
        slsa: SLSA attestation verification settings.
        cosign: Cosign CLI settings.
        trusted_signers: Inline list of trusted signer configurations.
    """

    mode: EnforcementMode = EnforcementMode.ENFORCE
    verification: VerificationConfig = Field(default_factory=VerificationConfig)
    slsa: SlsaConfig = Field(default_factory=SlsaConfig)
    cosign: CosignConfig = Field(default_factory=CosignConfig)
    trusted_signers: List[TrustedSignerConfig] = Field(default_factory=list) # pyright: ignore[reportUnknownVariableType] 
