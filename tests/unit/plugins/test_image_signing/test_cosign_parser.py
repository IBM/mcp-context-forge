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


class TestParseTimestamp:
    """Tests for _parse_timestamp internal function."""

    def test_epoch_int(self) -> None:
        """Parse integer epoch seconds."""
        from plugins.image_signing.cosign.parser import _parse_timestamp

        result = _parse_timestamp(1700000000)
        assert result is not None
        assert result.year == 2023

    def test_epoch_float(self) -> None:
        """Parse float epoch seconds."""
        from plugins.image_signing.cosign.parser import _parse_timestamp

        result = _parse_timestamp(1700000000.5)
        assert result is not None

    def test_digit_string(self) -> None:
        """Parse digit string as epoch seconds."""
        from plugins.image_signing.cosign.parser import _parse_timestamp

        result = _parse_timestamp("1700000000")
        assert result is not None

    def test_iso_string(self) -> None:
        """Parse ISO 8601 string."""
        from plugins.image_signing.cosign.parser import _parse_timestamp

        result = _parse_timestamp("2024-01-15T10:30:00Z")
        assert result is not None
        assert result.year == 2024

    def test_none(self) -> None:
        """None returns None."""
        from plugins.image_signing.cosign.parser import _parse_timestamp

        assert _parse_timestamp(None) is None

    def test_empty_string(self) -> None:
        """Empty string returns None."""
        from plugins.image_signing.cosign.parser import _parse_timestamp

        assert _parse_timestamp("") is None

    def test_invalid_value(self) -> None:
        """Invalid value returns None."""
        from plugins.image_signing.cosign.parser import _parse_timestamp

        assert _parse_timestamp("not-a-date") is None


class TestRekorStderrDetection:
    """Tests for rekor verification via stderr."""

    def test_rekor_in_stderr(self) -> None:
        """Rekor verified detected from stderr."""
        stdout = '[{"optional": {}}]'
        result = parse_verify_output(
            stdout=stdout,
            stderr="tlog entry verified for rekor",
            return_code=0,
        )

        assert result.signature_found is True
        assert result.rekor_verified is True

    def test_no_rekor_in_stderr(self) -> None:
        """No rekor mention in stderr -> rekor_verified stays None."""
        stdout = '[{"optional": {}}]'
        result = parse_verify_output(
            stdout=stdout,
            stderr="some other info",
            return_code=0,
        )

        assert result.rekor_verified is None


class TestSlsaPredicate:
    """Tests for SLSA predicate extraction."""

    def test_base64_payload(self) -> None:
        """Parse base64-encoded attestation payload."""
        import base64
        import json

        predicate_data = {
            "predicate": {
                "builder": {"id": "https://github.com/slsa-framework/slsa-github-generator"},
                "buildType": "https://github.com/slsa-framework/slsa-github-generator/generic@v1",
            }
        }
        encoded = base64.b64encode(json.dumps(predicate_data).encode()).decode()

        payload = json.dumps([{"payload": encoded}])
        result = parse_attestation_output(
            stdout=payload, stderr="", return_code=0
        )

        assert result.attestation_found is True
        assert result.builder is not None
        assert "slsa-github-generator" in result.builder

    def test_raw_json_payload(self) -> None:
        """Parse raw JSON attestation payload."""
        import json

        predicate_data = {
            "predicate": {
                "builder": {"id": "https://custom-builder.example.com"},
            }
        }
        payload = json.dumps([{"payload": json.dumps(predicate_data)}])
        result = parse_attestation_output(
            stdout=payload, stderr="", return_code=0,
            trusted_builders=["https://custom-builder.example.com"],
        )

        assert result.attestation_found is True
        assert result.level == 1

    def test_invalid_base64_payload(self) -> None:
        """Invalid payload falls back gracefully."""
        import json

        payload = json.dumps([{"payload": "not-valid-base64!!!"}])
        result = parse_attestation_output(
            stdout=payload, stderr="", return_code=0
        )

        assert result.attestation_found is True
        assert result.builder is None


class TestInferSlsaLevel:
    """Tests for SLSA level inference."""

    def test_known_github_builder(self) -> None:
        """Known GitHub SLSA builder -> level 3."""
        from plugins.image_signing.cosign.parser import _infer_slsa_level

        level = _infer_slsa_level(
            "https://github.com/slsa-framework/slsa-github-generator/.github/workflows/generator_generic_slsa3.yml"
        )
        assert level == 3

    def test_known_gcp_builder(self) -> None:
        """Known GCP builder -> level 3."""
        from plugins.image_signing.cosign.parser import _infer_slsa_level

        level = _infer_slsa_level(
            "https://cloudbuild.googleapis.com/GoogleHostedWorker@v1"
        )
        assert level == 3

    def test_trusted_builder(self) -> None:
        """Builder in trusted list -> level 1."""
        from plugins.image_signing.cosign.parser import _infer_slsa_level

        level = _infer_slsa_level(
            "https://custom-builder.example.com",
            trusted_builders=["https://custom-builder.example.com"],
        )
        assert level == 1

    def test_unknown_builder(self) -> None:
        """Unknown builder not in trusted list -> None."""
        from plugins.image_signing.cosign.parser import _infer_slsa_level

        level = _infer_slsa_level("https://unknown-builder.com")
        assert level is None

    def test_none_builder(self) -> None:
        """None builder -> None."""
        from plugins.image_signing.cosign.parser import _infer_slsa_level

        assert _infer_slsa_level(None) is None        