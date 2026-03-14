#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/unit/plugins/test_image_signing/test_policy_evaluator.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Xinyi

Unit tests for policy evaluator.
"""

# Future
from __future__ import annotations

# Third-Party
import pytest

# First-Party
from plugins.image_signing.config import ImageSigningConfig, VerificationConfig, SlsaConfig
from plugins.image_signing.policy.evaluator import evaluate_policy
from plugins.image_signing.types import (
    AttestationResult,
    EnforcementMode,
    MatchResult,
    VerificationResult,
)


# ---------------------------------------------------------------------------
# Helpers: build common inputs
# ---------------------------------------------------------------------------

def _config(
    mode: EnforcementMode = EnforcementMode.ENFORCE,
    require_signature: bool = True,
    verify_transparency_log: bool = True,
    require_attestation: bool = False,
    minimum_level: int = 1,
) -> ImageSigningConfig:
    return ImageSigningConfig(
        mode=mode,
        verification=VerificationConfig(
            require_signature=require_signature,
            verify_transparency_log=verify_transparency_log,
        ),
        slsa=SlsaConfig(
            require_attestation=require_attestation,
            minimum_level=minimum_level,
        ),
    )


def _valid_verification() -> VerificationResult:
    return VerificationResult(
        signature_found=True,
        signature_valid=True,
        signer_identity="builder@example.com",
        signer_issuer="https://accounts.google.com",
        rekor_verified=True,
    )


def _valid_match() -> MatchResult:
    return MatchResult(
        matched=True,
        matched_signer_id="signer-1",
        matched_signer_name="CI Builder",
    )


# ---------------------------------------------------------------------------
# Tests: All checks pass
# ---------------------------------------------------------------------------

class TestPolicyPass:
    """Tests where all policy checks pass."""

    def test_all_pass_enforce(self) -> None:
        """All checks pass in ENFORCE mode -> not blocked."""
        decision = evaluate_policy(
            verification=_valid_verification(),
            match=_valid_match(),
            config=_config(),
        )

        assert decision.blocked is False
        assert decision.reason is None

    def test_all_pass_audit(self) -> None:
        """All checks pass in AUDIT mode -> not blocked."""
        decision = evaluate_policy(
            verification=_valid_verification(),
            match=_valid_match(),
            config=_config(mode=EnforcementMode.AUDIT),
        )

        assert decision.blocked is False
        assert decision.reason is None


# ---------------------------------------------------------------------------
# Tests: Rule 1 - Signature required but not found
# ---------------------------------------------------------------------------

class TestRule1SignatureRequired:
    """Rule 1: require_signature=True and signature_found=False."""

    def test_no_signature_enforce(self) -> None:
        """No signature in ENFORCE mode -> blocked."""
        decision = evaluate_policy(
            verification=VerificationResult(signature_found=False),
            match=MatchResult(matched=False),
            config=_config(),
        )

        assert decision.blocked is True
        assert "no signature" in decision.reason.lower()

    def test_no_signature_audit(self) -> None:
        """No signature in AUDIT mode -> not blocked, reason set."""
        decision = evaluate_policy(
            verification=VerificationResult(signature_found=False),
            match=MatchResult(matched=False),
            config=_config(mode=EnforcementMode.AUDIT),
        )

        assert decision.blocked is False
        assert decision.reason is not None

    def test_no_signature_not_required(self) -> None:
        """Signature not required and not found -> not blocked."""
        decision = evaluate_policy(
            verification=VerificationResult(signature_found=False),
            match=MatchResult(matched=False),
            config=_config(require_signature=False, verify_transparency_log=False),
        )

        assert decision.blocked is False


# ---------------------------------------------------------------------------
# Tests: Rule 2 - Signature found but invalid
# ---------------------------------------------------------------------------

class TestRule2SignatureInvalid:
    """Rule 2: signature_found=True but signature_valid=False."""

    def test_invalid_signature_enforce(self) -> None:
        """Invalid signature in ENFORCE mode -> blocked."""
        decision = evaluate_policy(
            verification=VerificationResult(
                signature_found=True,
                signature_valid=False,
            ),
            match=MatchResult(matched=False),
            config=_config(),
        )

        assert decision.blocked is True
        assert "invalid" in decision.reason.lower()

    def test_invalid_signature_audit(self) -> None:
        """Invalid signature in AUDIT mode -> not blocked, reason set."""
        decision = evaluate_policy(
            verification=VerificationResult(
                signature_found=True,
                signature_valid=False,
            ),
            match=MatchResult(matched=False),
            config=_config(mode=EnforcementMode.AUDIT),
        )

        assert decision.blocked is False
        assert decision.reason is not None


# ---------------------------------------------------------------------------
# Tests: Rule 3 - Trusted signer not matched
# ---------------------------------------------------------------------------

class TestRule3SignerMatch:
    """Rule 3: signature valid but signer not in trusted list."""

    def test_no_match_enforce(self) -> None:
        """Signer not matched in ENFORCE mode -> blocked."""
        decision = evaluate_policy(
            verification=_valid_verification(),
            match=MatchResult(matched=False),
            config=_config(),
        )

        assert decision.blocked is True
        assert "trusted signer" in decision.reason.lower()

    def test_no_match_audit(self) -> None:
        """Signer not matched in AUDIT mode -> not blocked, reason set."""
        decision = evaluate_policy(
            verification=_valid_verification(),
            match=MatchResult(matched=False),
            config=_config(mode=EnforcementMode.AUDIT),
        )

        assert decision.blocked is False
        assert decision.reason is not None


# ---------------------------------------------------------------------------
# Tests: Rule 4 - Rekor transparency log
# ---------------------------------------------------------------------------

class TestRule4Rekor:
    """Rule 4: verify_transparency_log=True and rekor_verified is not True."""

    def test_rekor_not_verified_enforce(self) -> None:
        """Rekor not verified in ENFORCE mode -> blocked."""
        verification = _valid_verification()
        verification.rekor_verified = None

        decision = evaluate_policy(
            verification=verification,
            match=_valid_match(),
            config=_config(),
        )

        assert decision.blocked is True
        assert "rekor" in decision.reason.lower()

    def test_rekor_false_enforce(self) -> None:
        """Rekor explicitly False in ENFORCE mode -> blocked."""
        verification = _valid_verification()
        verification.rekor_verified = False

        decision = evaluate_policy(
            verification=verification,
            match=_valid_match(),
            config=_config(),
        )

        assert decision.blocked is True

    def test_rekor_not_required(self) -> None:
        """Rekor not required -> pass even if not verified."""
        verification = _valid_verification()
        verification.rekor_verified = None

        decision = evaluate_policy(
            verification=verification,
            match=_valid_match(),
            config=_config(verify_transparency_log=False),
        )

        assert decision.blocked is False


# ---------------------------------------------------------------------------
# Tests: Rule 5 - SLSA attestation
# ---------------------------------------------------------------------------

class TestRule5Slsa:
    """Rule 5: SLSA attestation requirements."""

    def test_slsa_not_required(self) -> None:
        """SLSA not required -> pass without attestation."""
        decision = evaluate_policy(
            verification=_valid_verification(),
            match=_valid_match(),
            config=_config(require_attestation=False),
        )

        assert decision.blocked is False

    def test_slsa_required_but_missing_enforce(self) -> None:
        """SLSA required but no attestation in ENFORCE mode -> blocked."""
        decision = evaluate_policy(
            verification=_valid_verification(),
            match=_valid_match(),
            config=_config(require_attestation=True),
            attestation=None,
        )

        assert decision.blocked is True
        assert "slsa" in decision.reason.lower()

    def test_slsa_required_and_present(self) -> None:
        """SLSA required and attestation present -> pass."""
        decision = evaluate_policy(
            verification=_valid_verification(),
            match=_valid_match(),
            config=_config(require_attestation=True),
            attestation=AttestationResult(
                attestation_found=True,
                valid=True,
                level=3,
                builder="https://github.com/slsa-framework/slsa-github-generator",
            ),
        )

        assert decision.blocked is False

    def test_slsa_level_too_low_enforce(self) -> None:
        """SLSA level below minimum in ENFORCE mode -> blocked."""
        decision = evaluate_policy(
            verification=_valid_verification(),
            match=_valid_match(),
            config=_config(require_attestation=True, minimum_level=3),
            attestation=AttestationResult(
                attestation_found=True,
                valid=True,
                level=1,
            ),
        )

        assert decision.blocked is True
        assert "level" in decision.reason.lower()


# ---------------------------------------------------------------------------
# Tests: AUDIT mode never blocks
# ---------------------------------------------------------------------------

class TestAuditModeNeverBlocks:
    """AUDIT mode should never block, regardless of violations."""

    def test_all_violations_audit(self) -> None:
        """Multiple violations in AUDIT mode -> not blocked, reason set."""
        decision = evaluate_policy(
            verification=VerificationResult(signature_found=False),
            match=MatchResult(matched=False),
            config=_config(mode=EnforcementMode.AUDIT),
        )

        assert decision.blocked is False
        assert decision.reason is not None