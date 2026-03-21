#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_image_signing/test_cosign_verify_unsigned_image.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Xinyi

Integration test: unsigned container images are blocked in ENFORCE mode.

Tests the complete flow with real components:
    cosign verify (mocked → no signature) → evaluator (real) → blocked decision → DB persistence
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
    mock_verify_unsigned,
)


IMAGE_REF = "docker.io/untrusted/app:latest"


def _patch_session(db_session):
    """Helper to create a mock SessionLocal context manager."""
    mock_session_ctx = MagicMock()
    mock_session_ctx.__enter__ = lambda s: db_session
    mock_session_ctx.__exit__ = MagicMock(return_value=False)
    return patch("plugins.image_signing.image_signing.SessionLocal", return_value=mock_session_ctx)


class TestUnsignedImageEnforceMode:
    """Unsigned images in ENFORCE mode should be blocked."""

    @pytest.mark.asyncio
    async def test_unsigned_image_blocked(self, db_session, repository):
        """Unsigned image is blocked when require_signature=True in ENFORCE mode."""
        plugin = make_plugin(
            mode=EnforcementMode.ENFORCE,
            require_signature=True,
        )

        plugin._verifier.verify = mock_verify_unsigned()

        with _patch_session(db_session):
            result = await plugin.verify_image(image_ref=IMAGE_REF)

        assert result.blocked is True
        assert result.signature_found is False
        assert result.signature_valid is False
        assert result.reason is not None

    @pytest.mark.asyncio
    async def test_unsigned_image_blocked_persisted_to_db(self, db_session, repository):
        """Blocked unsigned image result is persisted to the database."""
        plugin = make_plugin(
            mode=EnforcementMode.ENFORCE,
            require_signature=True,
        )

        plugin._verifier.verify = mock_verify_unsigned()

        with _patch_session(db_session):
            result = await plugin.verify_image(
                image_ref=IMAGE_REF,
                assessment_id="assessment-block-001",
            )

        history = repository.get_verification_history(image_ref=IMAGE_REF)
        assert len(history) == 1
        assert history[0].blocked is True
        assert history[0].signature_found is False


class TestUnsignedImageAuditMode:
    """Unsigned images in AUDIT mode should NOT be blocked (log only)."""

    @pytest.mark.asyncio
    async def test_unsigned_image_not_blocked_in_audit(self, db_session, repository):
        """Unsigned image passes in AUDIT mode even without signature."""
        plugin = make_plugin(
            mode=EnforcementMode.AUDIT,
            require_signature=True,
        )

        plugin._verifier.verify = mock_verify_unsigned()

        with _patch_session(db_session):
            result = await plugin.verify_image(image_ref=IMAGE_REF)

        assert result.blocked is False
        assert result.signature_found is False

    @pytest.mark.asyncio
    async def test_unsigned_audit_still_persisted(self, db_session, repository):
        """AUDIT mode still persists the result to DB."""
        plugin = make_plugin(
            mode=EnforcementMode.AUDIT,
            require_signature=True,
        )

        plugin._verifier.verify = mock_verify_unsigned()

        with _patch_session(db_session):
            result = await plugin.verify_image(image_ref=IMAGE_REF)

        history = repository.get_verification_history(image_ref=IMAGE_REF)
        assert len(history) == 1
        assert history[0].blocked is False


class TestUnsignedImageSignatureNotRequired:
    """Unsigned images pass when require_signature=False."""

    @pytest.mark.asyncio
    async def test_unsigned_image_passes_when_not_required(self, db_session, repository):
        """Unsigned image passes when signature is not required."""
        plugin = make_plugin(
            mode=EnforcementMode.ENFORCE,
            require_signature=False,
        )

        plugin._verifier.verify = mock_verify_unsigned()

        with _patch_session(db_session):
            result = await plugin.verify_image(image_ref=IMAGE_REF)

        assert result.blocked is False
        assert result.signature_found is False


class TestUnsignedImageDBGracefulDegradation:
    """Plugin works even if DB is unavailable."""

    @pytest.mark.asyncio
    async def test_unsigned_blocked_even_without_db(self):
        """Plugin still blocks unsigned images even when DB write fails."""
        plugin = make_plugin(
            mode=EnforcementMode.ENFORCE,
            require_signature=True,
        )

        plugin._verifier.verify = mock_verify_unsigned()

        # Simulate DB failure for both Step 1 (read signers) and Step 7 (persist)
        mock_session_ctx = MagicMock()
        mock_session_ctx.__enter__ = MagicMock(side_effect=Exception("DB connection failed"))
        mock_session_ctx.__exit__ = MagicMock(return_value=False)

        with patch("plugins.image_signing.image_signing.SessionLocal", return_value=mock_session_ctx):
            result = await plugin.verify_image(image_ref=IMAGE_REF)

        # Verification logic still works, just DB persistence fails gracefully
        assert result.blocked is True
        assert result.signature_found is False