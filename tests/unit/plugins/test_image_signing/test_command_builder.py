#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/unit/plugins/test_image_signing/test_command_builder.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Xinyi

Unit tests for cosign command builder.
"""

# Future
from __future__ import annotations

# Third-Party
import pytest

# First-Party
from plugins.image_signing.config import CosignConfig, TrustedSignerConfig, VerificationConfig
from plugins.image_signing.cosign.command_builder import (
    build_verify_attestation_command,
    build_verify_command,
)
from plugins.image_signing.types import SignerType


class TestBuildVerifyCommand:
    """Tests for build_verify_command."""

    def test_basic_command(self) -> None:
        """Minimal command without signer or digest."""
        cmd = build_verify_command(
            image_ref="nginx:latest",
            cosign_config=CosignConfig(),
            verification_config=VerificationConfig(),
        )

        assert cmd[0] == "/usr/local/bin/cosign"
        assert "verify" in cmd
        assert "--output" in cmd
        assert cmd[-1] == "nginx:latest"

    def test_keyless_signer(self) -> None:
        """Keyless signer adds certificate identity flags."""
        cmd = build_verify_command(
            image_ref="ghcr.io/org/image:v1",
            cosign_config=CosignConfig(),
            verification_config=VerificationConfig(),
            signer=TrustedSignerConfig(
                type=SignerType.KEYLESS,
                issuer="https://accounts.google.com",
                subject="builder@example.com",
            ),
        )

        assert "--certificate-oidc-issuer" in cmd
        assert "https://accounts.google.com" in cmd
        assert "--certificate-identity" in cmd
        assert "builder@example.com" in cmd

    def test_keyless_signer_with_regex(self) -> None:
        """Keyless signer with subject_regex uses regexp flag."""
        cmd = build_verify_command(
            image_ref="ghcr.io/org/image:v1",
            cosign_config=CosignConfig(),
            verification_config=VerificationConfig(),
            signer=TrustedSignerConfig(
                type=SignerType.KEYLESS,
                issuer="https://token.actions.githubusercontent.com",
                subject_regex="https://github.com/myorg/.*",
            ),
        )

        assert "--certificate-identity-regexp" in cmd
        assert "--certificate-identity" not in cmd

    def test_public_key_signer(self) -> None:
        """Public key signer adds --key env://COSIGN_PUBLIC_KEY."""
        cmd = build_verify_command(
            image_ref="registry.io/image:latest",
            cosign_config=CosignConfig(),
            verification_config=VerificationConfig(),
            signer=TrustedSignerConfig(
                type=SignerType.PUBLIC_KEY,
                public_key="-----BEGIN PUBLIC KEY-----\nMFkw...\n-----END PUBLIC KEY-----",
            ),
        )

        assert "--key" in cmd
        assert "env://COSIGN_PUBLIC_KEY" in cmd

    def test_kms_signer(self) -> None:
        """KMS signer adds --key with KMS reference."""
        kms_ref = "gcpkms://projects/myproject/locations/global/keyRings/myring/cryptoKeys/mykey"
        cmd = build_verify_command(
            image_ref="gcr.io/myproject/image:latest",
            cosign_config=CosignConfig(),
            verification_config=VerificationConfig(),
            signer=TrustedSignerConfig(
                type=SignerType.KMS,
                kms_key_ref=kms_ref,
            ),
        )

        assert "--key" in cmd
        assert kms_ref in cmd

    def test_digest_reference(self) -> None:
        """Image digest is appended as image_ref@digest."""
        cmd = build_verify_command(
            image_ref="nginx",
            cosign_config=CosignConfig(),
            verification_config=VerificationConfig(),
            image_digest="sha256:abc123",
        )

        assert cmd[-1] == "nginx@sha256:abc123"

    def test_offline_mode(self) -> None:
        """Offline mode adds --offline flag."""
        cmd = build_verify_command(
            image_ref="nginx:latest",
            cosign_config=CosignConfig(),
            verification_config=VerificationConfig(offline_mode=True),
        )

        assert "--offline" in cmd

    def test_keyless_missing_issuer_raises(self) -> None:
        """Keyless signer without oidc_issuer raises ValueError."""
        with pytest.raises(ValueError, match="oidc_issuer"):
            build_verify_command(
                image_ref="nginx:latest",
                cosign_config=CosignConfig(),
                verification_config=VerificationConfig(),
                signer=TrustedSignerConfig(
                    type=SignerType.KEYLESS,
                    subject="builder@example.com",
                ),
            )

    def test_keyless_missing_subject_raises(self) -> None:
        """Keyless signer without subject or subject_regex raises ValueError."""
        with pytest.raises(ValueError, match="subject"):
            build_verify_command(
                image_ref="nginx:latest",
                cosign_config=CosignConfig(),
                verification_config=VerificationConfig(),
                signer=TrustedSignerConfig(
                    type=SignerType.KEYLESS,
                    issuer="https://accounts.google.com",
                ),
            )

    def test_public_key_missing_key_raises(self) -> None:
        """Public key signer without public_key raises ValueError."""
        with pytest.raises(ValueError, match="public_key"):
            build_verify_command(
                image_ref="nginx:latest",
                cosign_config=CosignConfig(),
                verification_config=VerificationConfig(),
                signer=TrustedSignerConfig(type=SignerType.PUBLIC_KEY),
            )


class TestBuildVerifyAttestationCommand:
    """Tests for build_verify_attestation_command."""

    def test_basic_attestation_command(self) -> None:
        """Minimal attestation command."""
        cmd = build_verify_attestation_command(
            image_ref="nginx:latest",
            cosign_config=CosignConfig(),
            verification_config=VerificationConfig(),
        )

        assert "verify-attestation" in cmd
        assert "--type" in cmd
        assert "slsaprovenance" in cmd
        assert cmd[-1] == "nginx:latest"

    def test_custom_attestation_type(self) -> None:
        """Custom attestation type is passed through."""
        cmd = build_verify_attestation_command(
            image_ref="nginx:latest",
            cosign_config=CosignConfig(),
            verification_config=VerificationConfig(),
            attestation_type="vuln",
        )

        assert "vuln" in cmd