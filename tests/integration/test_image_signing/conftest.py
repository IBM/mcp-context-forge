#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_image_signing/conftest.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Xinyi

Shared fixtures for image signing integration tests.

Integration tests exercise the full plugin pipeline with only cosign CLI mocked:
    Plugin init → cosign verify (mocked) → matcher (real) → evaluator (real) → DB (real SQLite) → result
"""

# Future
from __future__ import annotations

# Standard
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# First-Party
from plugins.image_signing.config import (
    CosignConfig,
    ImageSigningConfig,
    SlsaConfig,
    TrustedSignerConfig,
    VerificationConfig,
)
from plugins.image_signing.image_signing import ImageSigningPlugin
from plugins.image_signing.storage.models import Base
from plugins.image_signing.storage.repository import ImageSigningRepository
from plugins.image_signing.types import (
    AttestationResult,
    EnforcementMode,
    SignerType,
    TrustedSigner,
    VerificationResult,
)


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_engine():
    """Create an in-memory SQLite engine with image signing tables."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(db_engine):
    """Create a DB session for each test, rolled back after."""
    SessionLocal = sessionmaker(bind=db_engine)
    session = SessionLocal()
    yield session
    session.rollback()
    session.close()


@pytest.fixture()
def repository(db_session):
    """Create an ImageSigningRepository backed by in-memory SQLite."""
    return ImageSigningRepository(db_session)


# ---------------------------------------------------------------------------
# Plugin factory
# ---------------------------------------------------------------------------


def make_plugin(
    mode: EnforcementMode = EnforcementMode.ENFORCE,
    require_signature: bool = True,
    verify_transparency_log: bool = True,
    require_trusted_signer: bool = True,
    require_attestation: bool = False,
    trusted_signers: list[TrustedSignerConfig] | None = None,
) -> ImageSigningPlugin:
    """Create an ImageSigningPlugin with real config but mocked verifier.

    Unlike unit tests which mock everything, integration tests use:
    - Real policy/matcher.py
    - Real policy/evaluator.py
    - Real storage/repository.py (with in-memory SQLite)
    - Mocked CosignVerifier (no real cosign binary needed)
    """
    config_dict = ImageSigningConfig(
        mode=mode,
        verification=VerificationConfig(
            require_signature=require_signature,
            verify_transparency_log=verify_transparency_log,
            require_trusted_signer=require_trusted_signer,
        ),
        slsa=SlsaConfig(
            require_attestation=require_attestation,
            trusted_builders=[
                "https://github.com/slsa-framework/slsa-github-generator"
            ],
        ),
        trusted_signers=trusted_signers or [],
    ).model_dump()

    mock_config = MagicMock()
    mock_config.config = config_dict

    with patch.object(ImageSigningPlugin, "__init__", lambda self, config: None):
        plugin = ImageSigningPlugin(mock_config)

    plugin._cfg = ImageSigningConfig(**config_dict)
    plugin._verifier = AsyncMock()
    plugin._config_signers = plugin._get_trusted_signers_from_config()

    return plugin


# ---------------------------------------------------------------------------
# Cosign response builders — return AsyncMock(return_value=...)
#
# These replace plugin._verifier.verify so that `await self._verifier.verify(...)`
# returns the desired VerificationResult regardless of what kwargs are passed.
# ---------------------------------------------------------------------------


def mock_verify_signed(
    signer_identity: str = "user@example.com",
    signer_issuer: str = "https://accounts.google.com",
    rekor_verified: bool = True,
) -> AsyncMock:
    """AsyncMock for CosignVerifier.verify() returning a valid signed result."""
    return AsyncMock(return_value=VerificationResult(
        signature_found=True,
        signature_valid=True,
        signer_identity=signer_identity,
        signer_issuer=signer_issuer,
        signed_at=datetime.now(timezone.utc),
        rekor_verified=rekor_verified,
    ))


def mock_verify_unsigned() -> AsyncMock:
    """AsyncMock for CosignVerifier.verify() returning an unsigned result."""
    return AsyncMock(return_value=VerificationResult(
        signature_found=False,
        signature_valid=False,
        signer_identity=None,
        signer_issuer=None,
        signed_at=None,
        rekor_verified=False,
    ))


def mock_verify_invalid() -> AsyncMock:
    """AsyncMock for CosignVerifier.verify() returning an invalid signature result."""
    return AsyncMock(return_value=VerificationResult(
        signature_found=True,
        signature_valid=False,
        signer_identity=None,
        signer_issuer=None,
        signed_at=None,
        rekor_verified=False,
        error="signature verification failed: key mismatch",
    ))


def mock_attestation(
    level: int = 3,
    builder: str = "https://github.com/slsa-framework/slsa-github-generator",
) -> AsyncMock:
    """AsyncMock for CosignVerifier.verify_attestation() returning a valid attestation."""
    return AsyncMock(return_value=AttestationResult(
        attestation_found=True,
        valid=True,
        level=level,
        builder=builder,
    ))