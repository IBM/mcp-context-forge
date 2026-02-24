#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/unit/plugins/test_image_signing/test_cosign_parser.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Xinyi

Unit tests for cosign output parser.
"""

# Future
from __future__ import annotations

from pathlib import Path

# First-Party
from plugins.image_signing.cosign.parser import (
    parse_attestation_output,
    parse_verify_output,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "cosign_outputs"


class TestParseVerifyOutput:
    """Tests for parse_verify_output."""

    def test_success_from_fixture(self) -> None:
        """Parse a successful cosign verify JSON output."""
        stdout = (FIXTURES_DIR / "verify_success.json").read_text()
        result = parse_verify_output(stdout=stdout, stderr="", return_code=0)

        assert result.signature_found is True
        assert result.signature_valid is True
        assert result.signer_identity == "builder@example.com"
        assert result.signer_issuer == "https://accounts.google.com"
        assert result.signed_at is not None

    def test_failure_no_matching_signatures(self) -> None:
        """Non-zero exit with 'no matching signatures' in stderr."""
        stderr = (FIXTURES_DIR / "verify_fail.txt").read_text()
        result = parse_verify_output(stdout="", stderr=stderr, return_code=1)

        assert result.signature_found is False
        assert result.signature_valid is False
        assert result.error is not None
        assert "no matching signatures" in result.error.lower()

    def test_failure_generic_error(self) -> None:
        """Non-zero exit with generic error message."""
        result = parse_verify_output(
            stdout="", stderr="registry auth failed", return_code=1
        )

        assert result.signature_found is False
        assert result.error is not None

    def test_invalid_json(self) -> None:
        """Return code 0 but stdout is not valid JSON."""
        result = parse_verify_output(
            stdout="not valid json", stderr="", return_code=0
        )

        assert result.signature_found is False
        assert result.error is not None

    def test_empty_payload(self) -> None:
        """Return code 0 but stdout is an empty JSON array."""
        result = parse_verify_output(stdout="[]", stderr="", return_code=0)

        assert result.signature_found is False
        assert result.error is not None

    def test_rekor_bundle_present(self) -> None:
        """Rekor verified when Bundle is present in optional."""
        stdout = (FIXTURES_DIR / "verify_success.json").read_text()
        result = parse_verify_output(stdout=stdout, stderr="", return_code=0)

        assert result.rekor_verified is True


class TestParseAttestationOutput:
    """Tests for parse_attestation_output."""

    def test_success_from_fixture(self) -> None:
        """Parse a successful cosign verify-attestation output."""
        stdout = (FIXTURES_DIR / "attestation_success.json").read_text()
        result = parse_attestation_output(
            stdout=stdout, stderr="", return_code=0
        )

        assert result.attestation_found is True
        assert result.valid is True
        assert result.builder is not None
        assert "slsa-github-generator" in result.builder

    def test_success_with_slsa_level(self) -> None:
        """SLSA level is inferred from known builder."""
        stdout = (FIXTURES_DIR / "attestation_success.json").read_text()
        result = parse_attestation_output(
            stdout=stdout, stderr="", return_code=0
        )

        assert result.level == 3

    def test_failure_nonzero_exit(self) -> None:
        """Non-zero exit code means no attestation found."""
        result = parse_attestation_output(
            stdout="", stderr="no attestation found", return_code=1
        )

        assert result.attestation_found is False
        assert result.valid is False

    def test_invalid_json(self) -> None:
        """Return code 0 but invalid JSON output."""
        result = parse_attestation_output(
            stdout="broken", stderr="", return_code=0
        )

        assert result.attestation_found is False

    def test_empty_payload(self) -> None:
        """Return code 0 but empty JSON array."""
        result = parse_attestation_output(stdout="[]", stderr="", return_code=0)

        assert result.attestation_found is False