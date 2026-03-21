#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_image_signing/test_cosig_verify_signed_image.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Xinyi

Integration test: properly signed container images pass the full verification pipeline.

Tests the complete flow with real components:
    cosign verify (mocked) → matcher (real) → evaluator (real) → DB persistence (real SQLite)
"""

# Future
from __future__ import annotations

# Standard
from unittest.mock import patch, MagicMock

# Third-Party
import pytest

# First-Party
from plugins.image_signing.config import TrustedSignerConfig
from plugins.image_signing.types import EnforcementMode, SignerType

# Local
from tests.integration.test_image_signing.conftest import (
    make_plugin,
    mock_verify_signed,
    mock_attestation,
)


IMAGE_REF = "ghcr.io/myorg/myapp:v1.2.3"
IMAGE_DIGEST = "sha256:abc123def456"


def _patch_session(db_session):
    """Helper to create a mock SessionLocal context manager that yields our test session."""
    mock_session_ctx = MagicMock()
    mock_session_ctx.__enter__ = lambda s: db_session
    mock_session_ctx.__exit__ = MagicMock(return_value=False)
    return patch("plugins.image_signing.image_signing.SessionLocal", return_value=mock_session_ctx)


class TestSignedImageEnforceMode:
    """Signed images in ENFORCE mode should pass and not be blocked."""

    @pytest.mark.asyncio
    async def test_keyless_signed_image_passes(self, db_session, repository):
        """Keyless-signed image with matching trusted signer passes verification."""
        plugin = make_plugin(
            mode=EnforcementMode.ENFORCE,
            trusted_signers=[
                TrustedSignerConfig(
                    type=SignerType.KEYLESS,
                    oidc_issuer="https://accounts.google.com",
                    subject="user@example.com",
                ),
            ],
        )

        plugin._verifier.verify = mock_verify_signed()

        with _patch_session(db_session):
            result = await plugin.verify_image(
                image_ref=IMAGE_REF,
                image_digest=IMAGE_DIGEST,
            )

        assert result.blocked is False
        assert result.signature_found is True
        assert result.signature_valid is True
        assert result.signer_identity == "user@example.com"
        assert result.signer_issuer == "https://accounts.google.com"
        assert result.rekor_verified is True

        # Verify result was persisted to DB
        history = repository.get_verification_history(image_ref=IMAGE_REF)
        assert len(history) >= 1
        assert history[0].image_ref == IMAGE_REF
        assert history[0].blocked is False

    @pytest.mark.asyncio
    async def test_keyless_signed_with_regex_subject_passes(self, db_session, repository):
        """Keyless signer with subject_regex matching passes verification."""
        plugin = make_plugin(
            mode=EnforcementMode.ENFORCE,
            trusted_signers=[
                TrustedSignerConfig(
                    type=SignerType.KEYLESS,
                    oidc_issuer="https://token.actions.githubusercontent.com",
                    subject_regex="https://github.com/myorg/.*",
                ),
            ],
        )

        plugin._verifier.verify = mock_verify_signed(
            signer_identity="https://github.com/myorg/myrepo/.github/workflows/release.yml@refs/tags/v1.0",
            signer_issuer="https://token.actions.githubusercontent.com",
        )

        with _patch_session(db_session):
            result = await plugin.verify_image(image_ref=IMAGE_REF)

        assert result.blocked is False
        assert result.signature_found is True
        assert result.signature_valid is True

    @pytest.mark.asyncio
    async def test_signed_image_with_slsa_attestation_passes(self, db_session, repository):
        """Signed image with valid SLSA attestation passes when attestation is required."""
        plugin = make_plugin(
            mode=EnforcementMode.ENFORCE,
            require_attestation=True,
            trusted_signers=[
                TrustedSignerConfig(
                    type=SignerType.KEYLESS,
                    oidc_issuer="https://accounts.google.com",
                    subject="user@example.com",
                ),
            ],
        )

        plugin._verifier.verify = mock_verify_signed()
        plugin._verifier.verify_attestation = mock_attestation()

        with _patch_session(db_session):
            result = await plugin.verify_image(image_ref=IMAGE_REF)

        assert result.blocked is False
        assert result.signature_found is True
        assert result.slsa is not None
        assert result.slsa.level == 3


class TestSignedImageAuditMode:
    """Signed images in AUDIT mode should always pass."""

    @pytest.mark.asyncio
    async def test_signed_image_audit_mode_passes(self, db_session, repository):
        """Signed image in AUDIT mode passes verification."""
        plugin = make_plugin(
            mode=EnforcementMode.AUDIT,
            trusted_signers=[
                TrustedSignerConfig(
                    type=SignerType.KEYLESS,
                    oidc_issuer="https://accounts.google.com",
                    subject="user@example.com",
                ),
            ],
        )

        plugin._verifier.verify = mock_verify_signed()

        with _patch_session(db_session):
            result = await plugin.verify_image(image_ref=IMAGE_REF)

        assert result.blocked is False


class TestSignedImageDBPersistence:
    """Verify that signed image results are correctly persisted to DB."""

    @pytest.mark.asyncio
    async def test_verification_result_persisted_with_all_fields(self, db_session, repository):
        """All fields from signed verification are stored in the database."""
        plugin = make_plugin(
            mode=EnforcementMode.ENFORCE,
            trusted_signers=[
                TrustedSignerConfig(
                    type=SignerType.KEYLESS,
                    oidc_issuer="https://accounts.google.com",
                    subject="user@example.com",
                ),
            ],
        )

        plugin._verifier.verify = mock_verify_signed()

        with _patch_session(db_session):
            result = await plugin.verify_image(
                image_ref=IMAGE_REF,
                image_digest=IMAGE_DIGEST,
                assessment_id="assessment-001",
            )

        history = repository.get_verification_history(image_ref=IMAGE_REF)
        assert len(history) == 1

        record = history[0]
        assert record.image_ref == IMAGE_REF
        assert record.image_digest == IMAGE_DIGEST
        assert record.signature_found is True
        assert record.signature_valid is True
        assert record.signer_identity == "user@example.com"
        assert record.signer_issuer == "https://accounts.google.com"
        assert record.rekor_verified is True
        assert record.blocked is False
        assert record.reason is None

    @pytest.mark.asyncio
    async def test_multiple_verifications_create_history(self, db_session, repository):
        """Multiple verify_image calls create multiple DB records."""
        plugin = make_plugin(
            mode=EnforcementMode.ENFORCE,
            trusted_signers=[
                TrustedSignerConfig(
                    type=SignerType.KEYLESS,
                    oidc_issuer="https://accounts.google.com",
                    subject="user@example.com",
                ),
            ],
        )

        plugin._verifier.verify = mock_verify_signed()

        with _patch_session(db_session):
            await plugin.verify_image(image_ref="image-a:latest")
            await plugin.verify_image(image_ref="image-b:latest")
            await plugin.verify_image(image_ref="image-a:latest")

        all_history = repository.get_verification_history()
        assert len(all_history) == 3

        image_a_history = repository.get_verification_history(image_ref="image-a:latest")
        assert len(image_a_history) == 2