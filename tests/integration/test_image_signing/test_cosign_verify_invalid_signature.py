#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_image_signing/test_cosign_verify_invalid_signature.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Xinyi

Integration test: images with invalid signatures are blocked in ENFORCE mode.

Tests the complete flow with real components:
    cosign verify (mocked → invalid sig) → matcher (real) → evaluator (real) → blocked → DB
"""

# Future
from __future__ import annotations

# Standard
import uuid
from unittest.mock import patch, MagicMock

# Third-Party
import pytest

# First-Party
from plugins.image_signing.config import TrustedSignerConfig
from plugins.image_signing.types import EnforcementMode, SignerType, TrustedSigner

# Local
from tests.integration.test_image_signing.conftest import (
    make_plugin,
    mock_verify_invalid,
    mock_verify_signed,
)


IMAGE_REF = "registry.example.com/tampered/app:v1.0"
IMAGE_DIGEST = "sha256:deadbeef1234"


def _patch_session(db_session):
    """Helper to create a mock SessionLocal context manager."""
    mock_session_ctx = MagicMock()
    mock_session_ctx.__enter__ = lambda s: db_session
    mock_session_ctx.__exit__ = MagicMock(return_value=False)
    return patch("plugins.image_signing.image_signing.SessionLocal", return_value=mock_session_ctx)


class TestInvalidSignatureEnforceMode:
    """Images with invalid signatures in ENFORCE mode should be blocked."""

    @pytest.mark.asyncio
    async def test_invalid_signature_blocked(self, db_session, repository):
        """Image with invalid signature is blocked in ENFORCE mode."""
        plugin = make_plugin(
            mode=EnforcementMode.ENFORCE,
            require_signature=True,
        )

        plugin._verifier.verify = mock_verify_invalid()

        with _patch_session(db_session):
            result = await plugin.verify_image(
                image_ref=IMAGE_REF,
                image_digest=IMAGE_DIGEST,
            )

        assert result.blocked is True
        assert result.signature_found is True
        assert result.signature_valid is False
        assert result.reason is not None

    @pytest.mark.asyncio
    async def test_invalid_signature_persisted_as_blocked(self, db_session, repository):
        """Invalid signature result is persisted to DB with blocked=True."""
        plugin = make_plugin(
            mode=EnforcementMode.ENFORCE,
            require_signature=True,
        )

        plugin._verifier.verify = mock_verify_invalid()

        with _patch_session(db_session):
            result = await plugin.verify_image(
                image_ref=IMAGE_REF,
                image_digest=IMAGE_DIGEST,
            )

        history = repository.get_verification_history(image_ref=IMAGE_REF)
        assert len(history) == 1
        assert history[0].blocked is True
        assert history[0].signature_valid is False


class TestInvalidSignatureAuditMode:
    """Images with invalid signatures in AUDIT mode should NOT be blocked."""

    @pytest.mark.asyncio
    async def test_invalid_signature_not_blocked_in_audit(self, db_session, repository):
        """Invalid signature passes in AUDIT mode (log only)."""
        plugin = make_plugin(
            mode=EnforcementMode.AUDIT,
            require_signature=True,
        )

        plugin._verifier.verify = mock_verify_invalid()

        with _patch_session(db_session):
            result = await plugin.verify_image(image_ref=IMAGE_REF)

        assert result.blocked is False
        assert result.signature_found is True
        assert result.signature_valid is False


class TestUntrustedSignerEnforceMode:
    """Signed images from untrusted signers should be blocked in ENFORCE mode."""

    @pytest.mark.asyncio
    async def test_valid_signature_untrusted_signer_blocked(self, db_session, repository):
        """Valid signature but signer not in trusted list is blocked."""
        plugin = make_plugin(
            mode=EnforcementMode.ENFORCE,
            require_trusted_signer=True,
            trusted_signers=[
                TrustedSignerConfig(
                    type=SignerType.KEYLESS,
                    oidc_issuer="https://accounts.google.com",
                    subject="trusted@mycompany.com",
                ),
            ],
        )

        # Signed by a different identity than what's trusted
        plugin._verifier.verify = mock_verify_signed(
            signer_identity="attacker@evil.com",
            signer_issuer="https://accounts.google.com",
        )

        with _patch_session(db_session):
            result = await plugin.verify_image(image_ref=IMAGE_REF)

        assert result.blocked is True
        assert result.signature_found is True
        assert result.signature_valid is True

    @pytest.mark.asyncio
    async def test_valid_signature_wrong_issuer_blocked(self, db_session, repository):
        """Valid signature but wrong OIDC issuer is blocked."""
        plugin = make_plugin(
            mode=EnforcementMode.ENFORCE,
            require_trusted_signer=True,
            trusted_signers=[
                TrustedSignerConfig(
                    type=SignerType.KEYLESS,
                    oidc_issuer="https://accounts.google.com",
                    subject="user@example.com",
                ),
            ],
        )

        plugin._verifier.verify = mock_verify_signed(
            signer_identity="user@example.com",
            signer_issuer="https://evil-issuer.com",
        )

        with _patch_session(db_session):
            result = await plugin.verify_image(image_ref=IMAGE_REF)

        assert result.blocked is True


class TestRekorVerificationRequired:
    """When transparency log verification is required, missing rekor fails."""

    @pytest.mark.asyncio
    async def test_missing_rekor_blocked(self, db_session, repository):
        """Image signed but not in Rekor transparency log is blocked."""
        plugin = make_plugin(
            mode=EnforcementMode.ENFORCE,
            verify_transparency_log=True,
            trusted_signers=[
                TrustedSignerConfig(
                    type=SignerType.KEYLESS,
                    oidc_issuer="https://accounts.google.com",
                    subject="user@example.com",
                ),
            ],
        )

        plugin._verifier.verify = mock_verify_signed(rekor_verified=False)

        with _patch_session(db_session):
            result = await plugin.verify_image(image_ref=IMAGE_REF)

        assert result.blocked is True
        assert result.rekor_verified is False


class TestDBSignersIntegration:
    """Test that DB-sourced trusted signers work alongside config signers."""

    @pytest.mark.asyncio
    async def test_db_signer_used_for_matching(self, db_session, repository):
        """Signer from DB (not config) is used for matching."""
        # Add a signer to DB (not in config)
        db_signer = TrustedSigner(
            id=str(uuid.uuid4()),
            name="db-signer",
            type=SignerType.KEYLESS,
            oidc_issuer="https://accounts.google.com",
            subject="db-user@example.com",
            enabled=True,
        )
        repository.create_trusted_signer(db_signer)
        db_session.commit()

        # Plugin with NO config signers
        plugin = make_plugin(
            mode=EnforcementMode.ENFORCE,
            require_trusted_signer=True,
            trusted_signers=[],  # empty config
        )

        plugin._verifier.verify = mock_verify_signed(
            signer_identity="db-user@example.com",
            signer_issuer="https://accounts.google.com",
        )

        with _patch_session(db_session):
            result = await plugin.verify_image(image_ref=IMAGE_REF)

        # Should pass because DB signer matches
        assert result.blocked is False
        assert result.signature_valid is True