#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/unit/plugins/test_image_signing/test_image_signing_plugin.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Xinyi

Unit tests for ImageSigningPlugin.
"""

# Future
from __future__ import annotations

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from plugins.image_signing.config import (
    CosignConfig,
    ImageSigningConfig,
    SlsaConfig,
    TrustedSignerConfig,
    VerificationConfig,
)
from plugins.image_signing.errors import CosignNotFoundError
from plugins.image_signing.image_signing import ImageSigningPlugin
from plugins.image_signing.types import (
    AttestationResult,
    EnforcementMode,
    MatchResult,
    PolicyDecision,
    SignerType,
    SignatureVerificationResult,
    SlsaResult,
    TrustedSigner,
    VerificationResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_plugin(
    mode: EnforcementMode = EnforcementMode.ENFORCE,
    require_signature: bool = True,
    verify_transparency_log: bool = True,
    require_attestation: bool = False,
    trusted_signers: list | None = None,
) -> ImageSigningPlugin:
    """Create an ImageSigningPlugin with a mock PluginConfig."""
    config_dict = ImageSigningConfig(
        mode=mode,
        verification=VerificationConfig(
            require_signature=require_signature,
            verify_transparency_log=verify_transparency_log,
        ),
        slsa=SlsaConfig(require_attestation=require_attestation),
        trusted_signers=trusted_signers or [],
    ).model_dump()

    mock_config = MagicMock()
    mock_config.config = config_dict

    with patch.object(ImageSigningPlugin, "__init__", lambda self, config: None):
        plugin = ImageSigningPlugin(mock_config)

    plugin._cfg = ImageSigningConfig(**config_dict)
    plugin._verifier = MagicMock()
    plugin._config_signers = plugin._get_trusted_signers_from_config()

    return plugin


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
# Tests: __init__ and helpers
# ---------------------------------------------------------------------------

class TestPluginInit:
    """Tests for plugin initialization."""

    def test_default_config(self) -> None:
        """Plugin initializes with default config."""
        plugin = _make_plugin()

        assert plugin._cfg.mode == EnforcementMode.ENFORCE
        assert plugin._cfg.verification.require_signature is True

    def test_config_signers_loaded(self) -> None:
        """Inline trusted signers are loaded from config."""
        plugin = _make_plugin(
            trusted_signers=[
                TrustedSignerConfig(
                    type=SignerType.KEYLESS,
                    oidc_issuer="https://accounts.google.com",
                    subject="builder@example.com",
                ),
            ],
        )

        assert len(plugin._config_signers) == 1
        assert plugin._config_signers[0].id == "config-0"
        assert plugin._config_signers[0].type == SignerType.KEYLESS

    def test_config_signers_empty(self) -> None:
        """No inline signers -> empty list."""
        plugin = _make_plugin()

        assert plugin._config_signers == []


class TestDomainSignerToConfig:
    """Tests for _domain_signer_to_config."""

    def test_keyless_conversion(self) -> None:
        """TrustedSigner -> TrustedSignerConfig for keyless."""
        signer = TrustedSigner(
            id="s1",
            name="test",
            type=SignerType.KEYLESS,
            oidc_issuer="https://accounts.google.com",
            subject="builder@example.com",
        )

        config = ImageSigningPlugin._domain_signer_to_config(signer)

        assert config.type == SignerType.KEYLESS
        assert config.oidc_issuer == "https://accounts.google.com"
        assert config.subject == "builder@example.com"

    def test_public_key_conversion(self) -> None:
        """TrustedSigner -> TrustedSignerConfig for public_key."""
        signer = TrustedSigner(
            id="s2",
            name="key-signer",
            type=SignerType.PUBLIC_KEY,
            public_key="-----BEGIN PUBLIC KEY-----\\ntest\\n-----END PUBLIC KEY-----",
        )

        config = ImageSigningPlugin._domain_signer_to_config(signer)

        assert config.type == SignerType.PUBLIC_KEY
        assert config.public_key == signer.public_key


class TestAssembleResult:
    """Tests for _assemble_result."""

    def test_basic_assembly(self) -> None:
        """Assembles result from verification data."""
        result = ImageSigningPlugin._assemble_result(
            image_ref="nginx:latest",
            image_digest="sha256:abc",
            verification=_valid_verification(),
            attestation=None,
            blocked=False,
            reason=None,
        )

        assert result.image_ref == "nginx:latest"
        assert result.image_digest == "sha256:abc"
        assert result.signature_found is True
        assert result.blocked is False
        assert result.slsa.attestation_found is None

    def test_assembly_with_attestation(self) -> None:
        """Assembles result with SLSA attestation."""
        attestation = AttestationResult(
            attestation_found=True,
            valid=True,
            level=3,
            builder="https://github.com/slsa-framework/slsa-github-generator",
        )

        result = ImageSigningPlugin._assemble_result(
            image_ref="nginx:latest",
            image_digest=None,
            verification=_valid_verification(),
            attestation=attestation,
            blocked=False,
            reason=None,
        )

        assert result.slsa.attestation_found is True
        assert result.slsa.level == 3

    def test_assembly_blocked(self) -> None:
        """Assembles blocked result with reason."""
        result = ImageSigningPlugin._assemble_result(
            image_ref="nginx:latest",
            image_digest=None,
            verification=VerificationResult(signature_found=False),
            attestation=None,
            blocked=True,
            reason="No signature found",
        )

        assert result.blocked is True
        assert result.reason == "No signature found"


# ---------------------------------------------------------------------------
# Tests: verify_image - keyless flow
# ---------------------------------------------------------------------------

class TestVerifyImageKeyless:
    """Tests for verify_image with keyless signers."""

    @pytest.mark.asyncio
    @patch("plugins.image_signing.image_signing.match_signer")
    @patch("plugins.image_signing.image_signing.evaluate_policy")
    async def test_signed_image_passes(self, mock_eval, mock_match) -> None:
        """Signed image with matching signer passes policy."""
        plugin = _make_plugin()
        plugin._verifier.verify = AsyncMock(return_value=_valid_verification())

        mock_match.return_value = _valid_match()
        mock_eval.return_value = PolicyDecision(blocked=False)

        result = await plugin.verify_image(image_ref="ghcr.io/org/image:v1")

        assert result.signature_found is True
        assert result.signature_valid is True
        assert result.blocked is False
        plugin._verifier.verify.assert_called_once()

    @pytest.mark.asyncio
    @patch("plugins.image_signing.image_signing.match_signer")
    @patch("plugins.image_signing.image_signing.evaluate_policy")
    async def test_unsigned_image_blocked(self, mock_eval, mock_match) -> None:
        """Unsigned image is blocked in ENFORCE mode."""
        plugin = _make_plugin()
        plugin._verifier.verify = AsyncMock(
            return_value=VerificationResult(signature_found=False)
        )

        mock_match.return_value = MatchResult(matched=False)
        mock_eval.return_value = PolicyDecision(blocked=True, reason="No signature found")

        result = await plugin.verify_image(image_ref="nginx:latest")

        assert result.blocked is True
        assert result.reason is not None

    @pytest.mark.asyncio
    @patch("plugins.image_signing.image_signing.match_signer")
    @patch("plugins.image_signing.image_signing.evaluate_policy")
    async def test_with_digest(self, mock_eval, mock_match) -> None:
        """Image digest is passed through to verifier."""
        plugin = _make_plugin()
        plugin._verifier.verify = AsyncMock(return_value=_valid_verification())

        mock_match.return_value = _valid_match()
        mock_eval.return_value = PolicyDecision(blocked=False)

        await plugin.verify_image(
            image_ref="nginx",
            image_digest="sha256:abc123",
        )

        call_kwargs = plugin._verifier.verify.call_args.kwargs
        assert call_kwargs["image_digest"] == "sha256:abc123"


# ---------------------------------------------------------------------------
# Tests: verify_image - public key flow
# ---------------------------------------------------------------------------

class TestVerifyImagePublicKey:
    """Tests for verify_image with public key signers."""

    @pytest.mark.asyncio
    @patch("plugins.image_signing.image_signing.evaluate_policy")
    async def test_public_key_signer_matched(self, mock_eval) -> None:
        """Public key signer is tried and matched directly."""
        plugin = _make_plugin(
            trusted_signers=[
                TrustedSignerConfig(
                    type=SignerType.PUBLIC_KEY,
                    public_key="-----BEGIN PUBLIC KEY-----\\ntest\\n-----END PUBLIC KEY-----",
                ),
            ],
        )
        plugin._verifier.verify = AsyncMock(return_value=_valid_verification())
        mock_eval.return_value = PolicyDecision(blocked=False)

        result = await plugin.verify_image(image_ref="registry.io/image:latest")

        assert result.signature_found is True
        assert result.signature_valid is True
        # verify was called with signer config (not bare)
        call_kwargs = plugin._verifier.verify.call_args.kwargs
        assert call_kwargs.get("signer") is not None

    @pytest.mark.asyncio
    @patch("plugins.image_signing.image_signing.match_signer")
    @patch("plugins.image_signing.image_signing.evaluate_policy")
    async def test_public_key_fails_falls_back(self, mock_eval, mock_match) -> None:
        """Public key verify fails -> falls back to keyless verify."""
        plugin = _make_plugin(
            trusted_signers=[
                TrustedSignerConfig(
                    type=SignerType.PUBLIC_KEY,
                    public_key="-----BEGIN PUBLIC KEY-----\\ntest\\n-----END PUBLIC KEY-----",
                ),
            ],
        )

        # First call (public key) fails, second call (keyless) succeeds
        plugin._verifier.verify = AsyncMock(
            side_effect=[
                VerificationResult(signature_found=False, signature_valid=False),
                _valid_verification(),
            ]
        )
        mock_match.return_value = _valid_match()
        mock_eval.return_value = PolicyDecision(blocked=False)

        result = await plugin.verify_image(image_ref="nginx:latest")

        assert plugin._verifier.verify.call_count == 2
        assert result.signature_found is True


# ---------------------------------------------------------------------------
# Tests: verify_image - SLSA attestation
# ---------------------------------------------------------------------------

class TestVerifyImageSlsa:
    """Tests for verify_image with SLSA attestation."""

    @pytest.mark.asyncio
    @patch("plugins.image_signing.image_signing.match_signer")
    @patch("plugins.image_signing.image_signing.evaluate_policy")
    async def test_attestation_checked_when_required(self, mock_eval, mock_match) -> None:
        """SLSA attestation is fetched when require_attestation=True."""
        plugin = _make_plugin(require_attestation=True)
        plugin._verifier.verify = AsyncMock(return_value=_valid_verification())
        plugin._verifier.verify_attestation = AsyncMock(
            return_value=AttestationResult(
                attestation_found=True, valid=True, level=3
            )
        )

        mock_match.return_value = _valid_match()
        mock_eval.return_value = PolicyDecision(blocked=False)

        result = await plugin.verify_image(image_ref="ghcr.io/org/image:v1")

        plugin._verifier.verify_attestation.assert_called_once()
        assert result.slsa.attestation_found is True
        assert result.slsa.level == 3

    @pytest.mark.asyncio
    @patch("plugins.image_signing.image_signing.match_signer")
    @patch("plugins.image_signing.image_signing.evaluate_policy")
    async def test_attestation_skipped_when_not_required(self, mock_eval, mock_match) -> None:
        """SLSA attestation is NOT fetched when require_attestation=False."""
        plugin = _make_plugin(require_attestation=False)
        plugin._verifier.verify = AsyncMock(return_value=_valid_verification())
        plugin._verifier.verify_attestation = AsyncMock()

        mock_match.return_value = _valid_match()
        mock_eval.return_value = PolicyDecision(blocked=False)

        await plugin.verify_image(image_ref="nginx:latest")

        plugin._verifier.verify_attestation.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: verify_image - error handling
# ---------------------------------------------------------------------------

class TestVerifyImageErrors:
    """Tests for verify_image error handling."""

    @pytest.mark.asyncio
    async def test_cosign_not_found_propagates(self) -> None:
        """CosignNotFoundError propagates from verify_image."""
        plugin = _make_plugin()
        plugin._verifier.verify = AsyncMock(
            side_effect=CosignNotFoundError("cosign not found")
        )

        with pytest.raises(CosignNotFoundError):
            await plugin.verify_image(image_ref="nginx:latest")


# ---------------------------------------------------------------------------
# Tests: assessment_post_container_scan hook
# ---------------------------------------------------------------------------

class TestAssessmentHook:
    """Tests for assessment_post_container_scan hook."""

    @pytest.mark.asyncio
    async def test_no_image_ref_skips(self) -> None:
        """Missing image_ref in payload -> skip verification."""
        plugin = _make_plugin()
        payload = MagicMock(spec=[])  # no attributes

        result = await plugin.assessment_post_container_scan(
            payload=payload, context=MagicMock()
        )

        assert result.continue_processing is True

    @pytest.mark.asyncio
    async def test_signed_image_passes(self) -> None:
        """Signed image -> continue processing."""
        plugin = _make_plugin()
        plugin.verify_image = AsyncMock(
            return_value=SignatureVerificationResult(
                image_ref="nginx:latest",
                signature_found=True,
                signature_valid=True,
                blocked=False,
            )
        )

        payload = MagicMock()
        payload.image_ref = "nginx:latest"
        payload.image_digest = None
        payload.assessment_id = None

        result = await plugin.assessment_post_container_scan(
            payload=payload, context=MagicMock()
        )

        assert result.continue_processing is True

    @pytest.mark.asyncio
    async def test_blocked_enforce_mode(self) -> None:
        """Blocked image in ENFORCE mode -> stop processing."""
        plugin = _make_plugin(mode=EnforcementMode.ENFORCE)
        plugin.verify_image = AsyncMock(
            return_value=SignatureVerificationResult(
                image_ref="nginx:latest",
                blocked=True,
                reason="No signature found",
            )
        )

        payload = MagicMock()
        payload.image_ref = "nginx:latest"
        payload.image_digest = None
        payload.assessment_id = None

        result = await plugin.assessment_post_container_scan(
            payload=payload, context=MagicMock()
        )

        assert result.continue_processing is False
        assert result.violation is not None
        assert result.violation.code == "IMAGE_SIGNING"

    @pytest.mark.asyncio
    async def test_blocked_audit_mode(self) -> None:
        """Blocked image in AUDIT mode -> continue processing."""
        plugin = _make_plugin(mode=EnforcementMode.AUDIT)
        plugin.verify_image = AsyncMock(
            return_value=SignatureVerificationResult(
                image_ref="nginx:latest",
                blocked=False,
                reason="No signature found",
            )
        )

        payload = MagicMock()
        payload.image_ref = "nginx:latest"
        payload.image_digest = None
        payload.assessment_id = None

        result = await plugin.assessment_post_container_scan(
            payload=payload, context=MagicMock()
        )

        assert result.continue_processing is True

    @pytest.mark.asyncio
    async def test_cosign_not_found_enforce(self) -> None:
        """CosignNotFoundError in ENFORCE mode -> block."""
        plugin = _make_plugin(mode=EnforcementMode.ENFORCE)
        plugin.verify_image = AsyncMock(
            side_effect=CosignNotFoundError("not found")
        )

        payload = MagicMock()
        payload.image_ref = "nginx:latest"
        payload.image_digest = None
        payload.assessment_id = None

        result = await plugin.assessment_post_container_scan(
            payload=payload, context=MagicMock()
        )

        assert result.continue_processing is False
        assert result.violation.code == "IMAGE_SIGNING_UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_cosign_not_found_audit(self) -> None:
        """CosignNotFoundError in AUDIT mode -> continue."""
        plugin = _make_plugin(mode=EnforcementMode.AUDIT)
        plugin.verify_image = AsyncMock(
            side_effect=CosignNotFoundError("not found")
        )

        payload = MagicMock()
        payload.image_ref = "nginx:latest"
        payload.image_digest = None
        payload.assessment_id = None

        result = await plugin.assessment_post_container_scan(
            payload=payload, context=MagicMock()
        )

        assert result.continue_processing is True