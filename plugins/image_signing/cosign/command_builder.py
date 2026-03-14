#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/image_signing/cosign/command_builder.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Xinyi

Build cosign CLI arguments safely from config and policy.
"""

# Future
from __future__ import annotations

# Standard
from typing import List, Optional

# First-Party
from plugins.image_signing.config import CosignConfig, TrustedSignerConfig, VerificationConfig
from plugins.image_signing.types import SignerType


def build_verify_command(
    image_ref: str,
    cosign_config: CosignConfig,
    verification_config: VerificationConfig,
    signer: Optional[TrustedSignerConfig] = None,
    image_digest: Optional[str] = None,
) -> List[str]:
    """Build a cosign verify command with appropriate flags.

    Constructs the full CLI argument list for cosign verify based on
    the plugin configuration and optional trusted signer constraints.

    Args:
        image_ref: Container image reference (e.g. registry/repo:tag).
        cosign_config: Cosign CLI settings (path, timeout).
        verification_config: Signature verification settings.
        signer: Optional trusted signer config to constrain verification.
        image_digest: Optional image digest for immutable reference.

    Returns:
        List of command-line arguments for subprocess execution.
    """
    cmd: List[str] = [cosign_config.path, "verify", "--output", "json"]

    # Keyless signer identity constraints
    if signer is not None:
        if signer.type == SignerType.KEYLESS:
            if not signer.oidc_issuer:
                raise ValueError("KEYLESS signer requires oidc_issuer")
            if not (signer.subject or signer.subject_regex):
                raise ValueError("KEYLESS signer requires subject or subject_regex")
            if signer.subject and signer.subject_regex:
                raise ValueError("KEYLESS signer must not set both subject and subject_regex")            
            
            cmd.extend(["--certificate-oidc-issuer", signer.oidc_issuer])

            if signer.subject:
                cmd.extend(["--certificate-identity", signer.subject])
            elif signer.subject_regex:
                cmd.extend(["--certificate-identity-regexp", signer.subject_regex])

        elif signer.type == SignerType.PUBLIC_KEY:
            if not signer.public_key:
                raise ValueError("PUBLIC_KEY signer requires public_key")
            
           # NOTE: runner must set COSIGN_PUBLIC_KEY to signer.public_key PEM
            cmd.extend(["--key", "env://COSIGN_PUBLIC_KEY"])

        elif signer.type == SignerType.KMS:
            if not signer.kms_key_ref:
                raise ValueError("KMS signer requires kms_key_ref")

            cmd.extend(["--key", signer.kms_key_ref])

        else:
            raise ValueError(f"Unsupported signer type: {signer.type}")    

    # Transparency log options
    # if not verification_config.verify_transparency_log:
    #     cmd.append("--insecure-ignore-tlog=true")

    if verification_config.offline_mode:
        cmd.append("--offline")

    # Image reference: prefer digest for immutable verification
    if image_digest:
        cmd.append(f"{image_ref}@{image_digest}")
    else:
        cmd.append(image_ref)

    return cmd


def build_verify_attestation_command(
    image_ref: str,
    cosign_config: CosignConfig,
    verification_config: VerificationConfig,
    attestation_type: str = "slsaprovenance",
    image_digest: Optional[str] = None,
) -> List[str]:
    """Build a cosign verify-attestation command with appropriate flags.

    Constructs the full CLI argument list for cosign verify-attestation
    to check SLSA provenance or other attestation types.

    Args:
        image_ref: Container image reference (e.g. registry/repo:tag).
        cosign_config: Cosign CLI settings (path, timeout).
        verification_config: Signature verification settings.
        attestation_type: Attestation predicate type to verify.
        image_digest: Optional image digest for immutable reference.

    Returns:
        List of command-line arguments for subprocess execution.
    """
    cmd: List[str] = [
        cosign_config.path,
        "verify-attestation",
        "--output", "json",
        "--type", attestation_type,
    ]

    # Transparency log options
    # if not verification_config.verify_transparency_log:
    #     cmd.append("--insecure-ignore-tlog=true")

    if verification_config.offline_mode:
        cmd.append("--offline")

    # Image reference
    if image_digest:
        cmd.append(f"{image_ref}@{image_digest}")
    else:
        cmd.append(image_ref)

    return cmd