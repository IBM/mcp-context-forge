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

# First-Party
from plugins.image_signing.config import ImageSigningConfig
from plugins.image_signing.types import (
    AttestationResult,
    MatchResult,
    PolicyDecision,
    VerificationResult,
)


def evaluate_policy(
    verification: VerificationResult,
    match: MatchResult,
    config: ImageSigningConfig,
    attestation: AttestationResult | None = None,
) -> PolicyDecision:
    """Evaluate policy based on verification, signer match, and attestation results.

    Checks require_signature, trusted signer match, rekor verification,
    and SLSA attestation requirements. In AUDIT mode, never blocks.
    In ENFORCE mode, blocks on policy violations.

    Args:
        verification: Cosign signature verification result.
        match: Trusted signer matching result.
        attestation: SLSA attestation verification result.
        config: Plugin configuration with enforcement mode and requirements.

    Returns:
        PolicyDecision with blocked status and reason.
    """
    raise NotImplementedError