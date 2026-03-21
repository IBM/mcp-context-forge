#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/image_signing/policy/evaluator.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Xinyi

Policy evaluation: combine signature, signer match, and SLSA results into a decision.
"""

# Future
from __future__ import annotations

# Standard
import logging
from typing import Optional

# First-Party
from plugins.image_signing.config import ImageSigningConfig
from plugins.image_signing.policy.slsa import check_slsa_requirements
from plugins.image_signing.types import (
    AttestationResult,
    EnforcementMode,
    MatchResult,
    PolicyDecision,
    VerificationResult,
)

logger = logging.getLogger(__name__)


def evaluate_policy(
    verification: VerificationResult,
    match: MatchResult,
    config: ImageSigningConfig,
    attestation: AttestationResult | None = None,
) -> PolicyDecision:
    """Evaluate policy based on verification, signer match, and attestation results.

    Checks are evaluated in order. The first violation found sets the reason.
    In AUDIT mode, reason is set but blocked is always False.
    In ENFORCE mode, blocked is True on any violation.

    Enforcement rules:
        1. require_signature=True and signature_found=False -> block
        2. signature_found=True but signature_valid=False -> block
        3. Trusted signer not matched -> block
        4. verify_transparency_log=True and rekor_verified is not True -> block
        5. SLSA requirements not met -> block

    Args:
        verification: Cosign signature verification result.
        match: Trusted signer matching result.
        config: Plugin configuration with enforcement mode and requirements.
        attestation: Optional SLSA attestation verification result.

    Returns:
        PolicyDecision with blocked status and reason.
    """
    reason = _check_violations(verification, match, attestation, config)

    if reason is None:
        logger.info("Policy evaluation passed")
        return PolicyDecision(blocked=False)

    if config.mode == EnforcementMode.AUDIT:
        logger.warning("Policy violation (AUDIT, not blocking): %s", reason)
        return PolicyDecision(blocked=False, reason=reason)

    logger.warning("Policy violation (ENFORCE, blocking): %s", reason)
    return PolicyDecision(blocked=True, reason=reason)


def _check_violations(
    verification: VerificationResult,
    match: MatchResult,
    attestation: AttestationResult | None,
    config: ImageSigningConfig,
) -> Optional[str]:
    """Check all policy rules and return the first violation reason.

    Args:
        verification: Cosign signature verification result.
        match: Trusted signer matching result.
        attestation: Optional SLSA attestation result.
        config: Plugin configuration.

    Returns:
        Violation reason string, or None if all checks pass.
    """
    # Rule 1: Signature required but not found
    if config.verification.require_signature and not verification.signature_found:
        return "No signature found for image"

    # Rule 2: Signature found but invalid
    if verification.signature_found and not verification.signature_valid:
        return "Image signature is invalid"

    # Only check remaining rules if signature is valid
    if not verification.signature_valid:
        return None

    # Rule 3: Trusted signer not matched
    if not match.matched:
        return "Signer identity did not match any trusted signer"

    # Rule 4: Rekor transparency log verification
    if config.verification.verify_transparency_log:
        if verification.rekor_verified is not True:
            return "Rekor transparency log verification failed"

    # Rule 5: SLSA attestation requirements
    slsa_passed, slsa_reason = check_slsa_requirements(
        attestation=attestation,
        require_attestation=config.slsa.require_attestation,
        minimum_level=config.slsa.minimum_level,
        trusted_builders=config.slsa.trusted_builders,
    )
    if not slsa_passed:
        return slsa_reason

    return None