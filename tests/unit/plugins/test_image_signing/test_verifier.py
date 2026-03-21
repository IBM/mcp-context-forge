#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/unit/plugins/test_image_signing/test_verifier.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Xinyi

Unit tests for CosignVerifier.
"""

# Future
from __future__ import annotations

# Standard
from pathlib import Path
from unittest.mock import patch

# Third-Party
import pytest

# First-Party
from mcpgateway.utils.exec import ExecResult
from plugins.image_signing.config import CosignConfig, TrustedSignerConfig, VerificationConfig
from plugins.image_signing.cosign.verifier import CosignVerifier, _build_env_for_signer
from plugins.image_signing.errors import (
    CosignNotFoundError,
    CosignTimeoutError,
    CosignVerificationError,
)
from plugins.image_signing.types import SignerType

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "cosign_outputs"


@pytest.fixture
def verifier() -> CosignVerifier:
    """Create a CosignVerifier with default config."""
    return CosignVerifier(
        cosign_config=CosignConfig(),
        verification_config=VerificationConfig(),
    )


# ---------------------------------------------------------------------------
# Tests: CosignVerifier.verify
# ---------------------------------------------------------------------------

class TestVerify:
    """Tests for CosignVerifier.verify."""

    @pytest.mark.asyncio
    @patch("plugins.image_signing.cosign.verifier.run_cosign")
    async def test_signed_image(self, mock_run, verifier) -> None:
        """Successful verification of a signed image."""
        stdout = (FIXTURES_DIR / "verify_success.json").read_text()
        mock_run.return_value = ExecResult(
            returncode=0, stdout=stdout, stderr="", timed_out=False
        )

        result = await verifier.verify(image_ref="ghcr.io/org/image:v1")

        assert result.signature_found is True
        assert result.signature_valid is True
        assert result.signer_identity == "builder@example.com"
        mock_run.assert_called_once()

    @pytest.mark.asyncio
    @patch("plugins.image_signing.cosign.verifier.run_cosign")
    async def test_with_digest(self, mock_run, verifier) -> None:
        """Digest is passed through to command builder."""
        stdout = (FIXTURES_DIR / "verify_success.json").read_text()
        mock_run.return_value = ExecResult(
            returncode=0, stdout=stdout, stderr="", timed_out=False
        )

        await verifier.verify(
            image_ref="nginx",
            image_digest="sha256:abc123",
        )

        cmd = mock_run.call_args.kwargs.get("cmd")
        assert any("sha256:abc123" in arg for arg in cmd)

    @pytest.mark.asyncio
    @patch("plugins.image_signing.cosign.verifier.run_cosign")
    async def test_verification_error_returns_result(self, mock_run, verifier) -> None:
        """CosignVerificationError is caught and returned as failed result."""
        mock_run.side_effect = CosignVerificationError(
            reason="exit=1: no matching signatures"
        )

        result = await verifier.verify(image_ref="nginx:latest")

        assert result.signature_found is False
        assert result.signature_valid is False
        assert result.error is not None

    @pytest.mark.asyncio
    @patch("plugins.image_signing.cosign.verifier.run_cosign")
    async def test_timeout_returns_result(self, mock_run, verifier) -> None:
        """CosignTimeoutError is caught and returned as failed result."""
        mock_run.side_effect = CosignTimeoutError("timed out after 30s")

        result = await verifier.verify(image_ref="nginx:latest")

        assert result.signature_found is False
        assert result.error is not None

    @pytest.mark.asyncio
    @patch("plugins.image_signing.cosign.verifier.run_cosign")
    async def test_cosign_not_found_propagates(self, mock_run, verifier) -> None:
        """CosignNotFoundError is NOT caught, propagates to caller."""
        mock_run.side_effect = CosignNotFoundError("cosign not found")

        with pytest.raises(CosignNotFoundError):
            await verifier.verify(image_ref="nginx:latest")

    @pytest.mark.asyncio
    @patch("plugins.image_signing.cosign.verifier.run_cosign")
    async def test_unexpected_error_propagates(self, mock_run, verifier) -> None:
        """Unexpected exceptions re-raise after logging."""
        mock_run.side_effect = RuntimeError("something unexpected")

        with pytest.raises(RuntimeError, match="unexpected"):
            await verifier.verify(image_ref="nginx:latest")

    @pytest.mark.asyncio
    @patch("plugins.image_signing.cosign.verifier.run_cosign")
    async def test_public_key_signer_env(self, mock_run, verifier) -> None:
        """Public key signer passes COSIGN_PUBLIC_KEY env override."""
        stdout = (FIXTURES_DIR / "verify_success.json").read_text()
        mock_run.return_value = ExecResult(
            returncode=0, stdout=stdout, stderr="", timed_out=False
        )

        signer = TrustedSignerConfig(
            type=SignerType.PUBLIC_KEY,
            public_key="-----BEGIN PUBLIC KEY-----\ntest\n-----END PUBLIC KEY-----",
        )

        await verifier.verify(image_ref="registry.io/image:latest", signer=signer)

        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs["env_override"] == {"COSIGN_PUBLIC_KEY": signer.public_key}

    @pytest.mark.asyncio
    @patch("plugins.image_signing.cosign.verifier.run_cosign")
    async def test_keyless_signer_no_env(self, mock_run, verifier) -> None:
        """Keyless signer does not set env override."""
        stdout = (FIXTURES_DIR / "verify_success.json").read_text()
        mock_run.return_value = ExecResult(
            returncode=0, stdout=stdout, stderr="", timed_out=False
        )

        signer = TrustedSignerConfig(
            type=SignerType.KEYLESS,
            oidc_issuer="https://accounts.google.com",
            subject="builder@example.com",
        )

        await verifier.verify(image_ref="ghcr.io/org/image:v1", signer=signer)

        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs.get("env_override") is None


# ---------------------------------------------------------------------------
# Tests: CosignVerifier.verify_attestation
# ---------------------------------------------------------------------------

class TestVerifyAttestation:
    """Tests for CosignVerifier.verify_attestation."""

    @pytest.mark.asyncio
    @patch("plugins.image_signing.cosign.verifier.run_cosign")
    async def test_attestation_success(self, mock_run, verifier) -> None:
        """Successful attestation verification."""
        stdout = (FIXTURES_DIR / "attestation_success.json").read_text()
        mock_run.return_value = ExecResult(
            returncode=0, stdout=stdout, stderr="", timed_out=False
        )

        result = await verifier.verify_attestation(
            image_ref="ghcr.io/org/image:v1"
        )

        assert result.attestation_found is True
        assert result.valid is True
        assert result.builder is not None

    @pytest.mark.asyncio
    @patch("plugins.image_signing.cosign.verifier.run_cosign")
    async def test_attestation_with_trusted_builders(self, mock_run, verifier) -> None:
        """Trusted builders list is passed to parser."""
        stdout = (FIXTURES_DIR / "attestation_success.json").read_text()
        mock_run.return_value = ExecResult(
            returncode=0, stdout=stdout, stderr="", timed_out=False
        )

        result = await verifier.verify_attestation(
            image_ref="ghcr.io/org/image:v1",
            trusted_builders=["https://github.com/slsa-framework/slsa-github-generator"],
        )

        assert result.attestation_found is True

    @pytest.mark.asyncio
    @patch("plugins.image_signing.cosign.verifier.run_cosign")
    async def test_attestation_failure(self, mock_run, verifier) -> None:
        """CosignVerificationError returns not-found result."""
        mock_run.side_effect = CosignVerificationError(reason="no attestation")

        result = await verifier.verify_attestation(image_ref="nginx:latest")

        assert result.attestation_found is False
        assert result.valid is False

    @pytest.mark.asyncio
    @patch("plugins.image_signing.cosign.verifier.run_cosign")
    async def test_attestation_timeout(self, mock_run, verifier) -> None:
        """CosignTimeoutError returns not-found result."""
        mock_run.side_effect = CosignTimeoutError("timed out")

        result = await verifier.verify_attestation(image_ref="nginx:latest")

        assert result.attestation_found is False

    @pytest.mark.asyncio
    @patch("plugins.image_signing.cosign.verifier.run_cosign")
    async def test_attestation_not_found_propagates(self, mock_run, verifier) -> None:
        """CosignNotFoundError propagates."""
        mock_run.side_effect = CosignNotFoundError("cosign not found")

        with pytest.raises(CosignNotFoundError):
            await verifier.verify_attestation(image_ref="nginx:latest")

    @pytest.mark.asyncio
    @patch("plugins.image_signing.cosign.verifier.run_cosign")
    async def test_attestation_unexpected_error_propagates(self, mock_run, verifier) -> None:
        """Unexpected exceptions re-raise."""
        mock_run.side_effect = RuntimeError("unexpected")

        with pytest.raises(RuntimeError):
            await verifier.verify_attestation(image_ref="nginx:latest")


# ---------------------------------------------------------------------------
# Tests: check_available
# ---------------------------------------------------------------------------

class TestCheckAvailable:
    """Tests for CosignVerifier.check_available."""

    @patch("plugins.image_signing.cosign.verifier.check_cosign_installed")
    def test_available(self, mock_check, verifier) -> None:
        """No exception when cosign is available."""
        verifier.check_available()
        mock_check.assert_called_once()

    @patch(
        "plugins.image_signing.cosign.verifier.check_cosign_installed",
        side_effect=CosignNotFoundError("not found"),
    )
    def test_not_available(self, mock_check, verifier) -> None:
        """Raises CosignNotFoundError."""
        with pytest.raises(CosignNotFoundError):
            verifier.check_available()


# ---------------------------------------------------------------------------
# Tests: _build_env_for_signer
# ---------------------------------------------------------------------------

class TestBuildEnvForSigner:
    """Tests for _build_env_for_signer helper."""

    def test_none_signer(self) -> None:
        """None signer -> None env."""
        assert _build_env_for_signer(None) is None

    def test_keyless_signer(self) -> None:
        """Keyless signer -> None env."""
        signer = TrustedSignerConfig(
            type=SignerType.KEYLESS,
            oidc_issuer="https://accounts.google.com",
            subject="builder@example.com",
        )
        assert _build_env_for_signer(signer) is None

    def test_public_key_signer(self) -> None:
        """Public key signer -> COSIGN_PUBLIC_KEY env."""
        signer = TrustedSignerConfig(
            type=SignerType.PUBLIC_KEY,
            public_key="-----BEGIN PUBLIC KEY-----\ntest\n-----END PUBLIC KEY-----",
        )
        env = _build_env_for_signer(signer)
        assert env is not None
        assert env["COSIGN_PUBLIC_KEY"] == signer.public_key

    def test_kms_signer(self) -> None:
        """KMS signer -> None env (key ref is in CLI args, not env)."""
        signer = TrustedSignerConfig(
            type=SignerType.KMS,
            kms_key_ref="gcpkms://projects/myproject/locations/global/keyRings/ring/cryptoKeys/key",
        )
        assert _build_env_for_signer(signer) is None