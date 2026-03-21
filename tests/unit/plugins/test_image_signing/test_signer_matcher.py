#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/unit/plugins/test_image_signing/test_signer_matcher.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Xinyi

Unit tests for trusted signer matcher.
"""

# Future
from __future__ import annotations

# Standard
from datetime import datetime, timedelta, timezone

# Third-Party
import pytest

# First-Party
from plugins.image_signing.policy.matcher import match_signer
from plugins.image_signing.types import MatchResult, SignerType, TrustedSigner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _keyless_signer(
    subject: str | None = "builder@example.com",
    subject_regex: str | None = None,
    issuer: str = "https://accounts.google.com",
    enabled: bool = True,
    expires_at: datetime | None = None,
    signer_id: str = "signer-1",
    name: str = "CI Builder",
) -> TrustedSigner:
    return TrustedSigner(
        id=signer_id,
        name=name,
        type=SignerType.KEYLESS,
        oidc_issuer=issuer,
        subject=subject,
        subject_regex=subject_regex,
        enabled=enabled,
        expires_at=expires_at,
    )


def _public_key_signer(
    signer_id: str = "signer-pk",
    enabled: bool = True,
) -> TrustedSigner:
    return TrustedSigner(
        id=signer_id,
        name="Key Signer",
        type=SignerType.PUBLIC_KEY,
        public_key="-----BEGIN PUBLIC KEY-----\ntest\n-----END PUBLIC KEY-----",
        enabled=enabled,
    )


def _kms_signer(
    signer_id: str = "signer-kms",
    enabled: bool = True,
) -> TrustedSigner:
    return TrustedSigner(
        id=signer_id,
        name="KMS Signer",
        type=SignerType.KMS,
        kms_key_ref="gcpkms://projects/myproject/locations/global/keyRings/ring/cryptoKeys/key",
        enabled=enabled,
    )


# ---------------------------------------------------------------------------
# Tests: Keyless matching
# ---------------------------------------------------------------------------

class TestKeylessMatching:
    """Tests for keyless signer matching."""

    def test_exact_match(self) -> None:
        """Exact subject and issuer match."""
        result = match_signer(
            signer_identity="builder@example.com",
            signer_issuer="https://accounts.google.com",
            trusted_signers=[_keyless_signer()],
        )

        assert result.matched is True
        assert result.matched_signer_id == "signer-1"
        assert result.matched_signer_name == "CI Builder"

    def test_wrong_identity(self) -> None:
        """Identity does not match."""
        result = match_signer(
            signer_identity="attacker@evil.com",
            signer_issuer="https://accounts.google.com",
            trusted_signers=[_keyless_signer()],
        )

        assert result.matched is False

    def test_wrong_issuer(self) -> None:
        """Issuer does not match."""
        result = match_signer(
            signer_identity="builder@example.com",
            signer_issuer="https://evil-issuer.com",
            trusted_signers=[_keyless_signer()],
        )

        assert result.matched is False

    def test_regex_match(self) -> None:
        """Subject regex match."""
        signer = _keyless_signer(
            subject=None,
            subject_regex=r"https://github\.com/myorg/.*",
        )

        result = match_signer(
            signer_identity="https://github.com/myorg/my-repo",
            signer_issuer="https://accounts.google.com",
            trusted_signers=[signer],
        )

        assert result.matched is True

    def test_regex_no_match(self) -> None:
        """Subject regex does not match."""
        signer = _keyless_signer(
            subject=None,
            subject_regex=r"https://github\.com/myorg/.*",
        )

        result = match_signer(
            signer_identity="https://github.com/other-org/repo",
            signer_issuer="https://accounts.google.com",
            trusted_signers=[signer],
        )

        assert result.matched is False

    def test_regex_fullmatch(self) -> None:
        """Regex uses fullmatch, not partial match."""
        signer = _keyless_signer(
            subject=None,
            subject_regex=r"builder@example\.com",
        )

        result = match_signer(
            signer_identity="builder@example.com.evil.com",
            signer_issuer="https://accounts.google.com",
            trusted_signers=[signer],
        )

        assert result.matched is False

    def test_invalid_regex(self) -> None:
        """Invalid regex does not crash, returns no match."""
        signer = _keyless_signer(
            subject=None,
            subject_regex=r"[invalid(regex",
        )

        result = match_signer(
            signer_identity="builder@example.com",
            signer_issuer="https://accounts.google.com",
            trusted_signers=[signer],
        )

        assert result.matched is False


# ---------------------------------------------------------------------------
# Tests: Public key and KMS matching
# ---------------------------------------------------------------------------

class TestKeyBasedMatching:
    """Tests for public key and KMS signer matching."""

    def test_public_key_always_matches(self) -> None:
        """Public key signer matches if cosign verify succeeded."""
        result = match_signer(
            signer_identity="builder@example.com",
            signer_issuer="https://accounts.google.com",
            trusted_signers=[_public_key_signer()],
        )

        assert result.matched is True
        assert result.matched_signer_id == "signer-pk"

    def test_kms_always_matches(self) -> None:
        """KMS signer matches if cosign verify succeeded."""
        result = match_signer(
            signer_identity="builder@example.com",
            signer_issuer="https://accounts.google.com",
            trusted_signers=[_kms_signer()],
        )

        assert result.matched is True
        assert result.matched_signer_id == "signer-kms"


# ---------------------------------------------------------------------------
# Tests: No identity provided
# ---------------------------------------------------------------------------

class TestNoIdentity:
    """Tests when signer identity is not provided."""

    def test_none_identity(self) -> None:
        """None identity -> no match."""
        result = match_signer(
            signer_identity=None,
            signer_issuer="https://accounts.google.com",
            trusted_signers=[_keyless_signer()],
        )

        assert result.matched is False

    def test_empty_identity(self) -> None:
        """Empty string identity -> no match."""
        result = match_signer(
            signer_identity="",
            signer_issuer="https://accounts.google.com",
            trusted_signers=[_keyless_signer()],
        )

        assert result.matched is False


# ---------------------------------------------------------------------------
# Tests: Enabled / expired filtering
# ---------------------------------------------------------------------------

class TestSignerFiltering:
    """Tests for enabled and expiry filtering."""

    def test_disabled_signer_skipped(self) -> None:
        """Disabled signer is skipped."""
        result = match_signer(
            signer_identity="builder@example.com",
            signer_issuer="https://accounts.google.com",
            trusted_signers=[_keyless_signer(enabled=False)],
        )

        assert result.matched is False

    def test_expired_signer_skipped(self) -> None:
        """Expired signer is skipped."""
        past = datetime.now(timezone.utc) - timedelta(days=1)
        result = match_signer(
            signer_identity="builder@example.com",
            signer_issuer="https://accounts.google.com",
            trusted_signers=[_keyless_signer(expires_at=past)],
        )

        assert result.matched is False

    def test_not_yet_expired_signer_matches(self) -> None:
        """Signer that hasn't expired yet still matches."""
        future = datetime.now(timezone.utc) + timedelta(days=30)
        result = match_signer(
            signer_identity="builder@example.com",
            signer_issuer="https://accounts.google.com",
            trusted_signers=[_keyless_signer(expires_at=future)],
        )

        assert result.matched is True

    def test_naive_datetime_treated_as_utc(self) -> None:
        """Naive datetime (no tzinfo) is treated as UTC."""
        future = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=30)
        result = match_signer(
            signer_identity="builder@example.com",
            signer_issuer="https://accounts.google.com",
            trusted_signers=[_keyless_signer(expires_at=future)],
        )

        assert result.matched is True


# ---------------------------------------------------------------------------
# Tests: Multiple signers
# ---------------------------------------------------------------------------

class TestMultipleSigners:
    """Tests with multiple signers in the list."""

    def test_first_match_wins(self) -> None:
        """First matching signer is returned."""
        signers = [
            _keyless_signer(signer_id="first", name="First"),
            _keyless_signer(signer_id="second", name="Second"),
        ]

        result = match_signer(
            signer_identity="builder@example.com",
            signer_issuer="https://accounts.google.com",
            trusted_signers=signers,
        )

        assert result.matched_signer_id == "first"

    def test_skip_disabled_match_next(self) -> None:
        """Disabled signer skipped, next one matches."""
        signers = [
            _keyless_signer(signer_id="disabled", enabled=False),
            _keyless_signer(signer_id="active", name="Active"),
        ]

        result = match_signer(
            signer_identity="builder@example.com",
            signer_issuer="https://accounts.google.com",
            trusted_signers=signers,
        )

        assert result.matched is True
        assert result.matched_signer_id == "active"

    def test_empty_signers_list(self) -> None:
        """Empty trusted signers list -> no match."""
        result = match_signer(
            signer_identity="builder@example.com",
            signer_issuer="https://accounts.google.com",
            trusted_signers=[],
        )

        assert result.matched is False