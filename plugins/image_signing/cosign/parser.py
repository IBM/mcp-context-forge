#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/image_signing/cosign/parser.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Xinyi

Parse Cosign CLI outputs into normalized schemas.
"""

# Future
from __future__ import annotations

# Standard
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# First-Party
from plugins.image_signing.types import AttestationResult, VerificationResult

logger = logging.getLogger(__name__)


def _parse_timestamp(value: Any) -> Optional[datetime]:
    """Parse an ISO 8601 timestamp string or epoch seconds into a datetime object.

    Args:
        value: ISO 8601 formatted timestamp string, epoch seconds (int/float), or None.

    Returns:
        Parsed datetime object in UTC, or None if parsing fails.
    """
    if value is None or value == "":
        return None

    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc)

        if isinstance(value, str):
            s = value.strip()
            if s.isdigit():
                return datetime.fromtimestamp(int(s), tz=timezone.utc)

            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return dt.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        logger.warning("Failed to parse timestamp: %s", value)
        return None

    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        logger.warning("Failed to parse timestamp: %s", value)
        return None


def _extract_cert_identity(cert_info: Dict[str, Any]) -> Optional[str]:
    """Extract signer identity from certificate extensions.

    Cosign keyless verification embeds the signer identity in the
    certificate's Subject Alternative Name (SAN) extension.

    Args:
        cert_info: Certificate metadata from Cosign output.

    Returns:
        Signer identity string, or None if not found.
    """
    # Cosign stores identity in SubjectAlternativeName or Subject field
    return (
        cert_info.get("SubjectAlternativeName")
        or cert_info.get("Subject")
        or cert_info.get("subjectAlternativeName")
        or cert_info.get("subject")
    )


def _extract_cert_issuer(cert_info: Dict[str, Any]) -> Optional[str]:
    """Extract OIDC issuer from certificate extensions.

    Cosign keyless verification embeds the OIDC issuer in the
    certificate's custom OID extension (1.3.6.1.4.1.57264.1.1).

    Args:
        cert_info: Certificate metadata from Cosign output.

    Returns:
        OIDC issuer string, or None if not found.
    """
    # Cosign uses custom OID or Issuer field
    return (
        cert_info.get("Issuer")
        or cert_info.get("issuer")
        or cert_info.get("oidcIssuer")
    )


def parse_verify_output(stdout: str, stderr: str, return_code: int) -> VerificationResult:
    """Parse cosign verify command output into a VerificationResult.

    Handles both successful JSON output and failure cases from stderr.

    Args:
        stdout: Standard output from cosign verify.
        stderr: Standard error from cosign verify.
        return_code: Exit code from cosign verify.

    Returns:
        Normalized VerificationResult.
    """
    if return_code != 0:
        # Check for common failure patterns
        error_msg = stderr.strip() or stdout.strip() or "Unknown verification error"

        if "no matching signatures" in error_msg.lower():
            return VerificationResult(
                signature_found=False,
                signature_valid=False,
                error=error_msg,
            )

        return VerificationResult(
            signature_found=False,
            signature_valid=False,
            error=error_msg,
        )

    # Parse successful JSON output
    try:
        payloads: List[Dict[str, Any]] = json.loads(stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning("Failed to parse cosign JSON output: %s", exc)
        return VerificationResult(
            signature_found=False,
            signature_valid=False,
            error=f"Failed to parse cosign output: {exc}",
        )

    if not payloads:
        return VerificationResult(
            signature_found=False,
            signature_valid=False,
            error="Cosign returned empty verification payload",
        )

    # Use the first verified signature entry
    entry = payloads[0]

    # Extract certificate info from optional claims
    optional: Dict[str, Any] = entry.get("optional") or {}
    bundle_info: Dict[str, Any] = optional.get("Bundle") or {}
    payload_info: Dict[str, Any] = bundle_info.get("Payload") or {}
    cert_info: Dict[str, Any] = payload_info.get("body") or {}

    # Also check direct certificate fields (varies by cosign version)
    if not cert_info:
        cert_info = optional

    signer_identity = _extract_cert_identity(cert_info)
    signer_issuer = _extract_cert_issuer(cert_info)
    signed_at = _parse_timestamp(optional.get("signedTimestamp") or optional.get("IntegratedTime"))

    # Rekor transparency log verification
    rekor_verified: Optional[bool] = None
    bundle = optional.get("Bundle")
    if bundle is not None:
        rekor_verified = True
    elif "rekor" in stderr.lower() and "verified" in stderr.lower():
        rekor_verified = True

    return VerificationResult(
        signature_found=True,
        signature_valid=True,
        signer_identity=signer_identity,
        signer_issuer=signer_issuer,
        signed_at=signed_at,
        rekor_verified=rekor_verified,
    )


def parse_attestation_output(
    stdout: str,
    stderr: str,
    return_code: int,
    trusted_builders: Optional[List[str]] = None,
) -> AttestationResult:
    """Parse cosign verify-attestation command output into an AttestationResult.

    Args:
        stdout: Standard output from cosign verify-attestation.
        stderr: Standard error from cosign verify-attestation.
        return_code: Exit code from cosign verify-attestation.
        trusted_builders: Optional list of trusted builder identities.

    Returns:
        Normalized AttestationResult.
    """
    if return_code != 0:
        return AttestationResult(
            attestation_found=False,
            valid=False,
        )

    try:
        payloads: List[Dict[str, Any]] = json.loads(stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning("Failed to parse cosign attestation output: %s", exc)
        return AttestationResult(
            attestation_found=False,
            valid=False,
        )

    if not payloads:
        return AttestationResult(
            attestation_found=False,
            valid=False,
        )

    entry = payloads[0]

    # Extract SLSA provenance from in-toto attestation
    payload_body = entry.get("payload") or entry.get("PayloadBody") or ""
    predicate = _extract_slsa_predicate(payload_body)

    builder = predicate.get("builder", {}).get("id") if predicate else None
    slsa_level = _infer_slsa_level(builder, trusted_builders)

    return AttestationResult(
        attestation_found=True,
        valid=True,
        level=slsa_level,
        builder=builder,
    )


def _extract_slsa_predicate(payload_body: str) -> Optional[Dict[str, Any]]:
    """Extract SLSA predicate from base64-encoded in-toto attestation payload.

    Args:
        payload_body: Base64-encoded or raw JSON attestation payload.

    Returns:
        Parsed predicate dictionary, or None if extraction fails.
    """
    # Standard
    import base64

    if not payload_body:
        return None

    # Try raw JSON first
    try:
        data = json.loads(payload_body)
        return data.get("predicate", data)
    except (json.JSONDecodeError, TypeError):
        pass

    # Try base64 decoding
    try:
        decoded = base64.b64decode(payload_body).decode("utf-8")
        data = json.loads(decoded)
        return data.get("predicate", data)
    except Exception:
        logger.debug("Failed to decode attestation payload")
        return None


def _infer_slsa_level(
    builder: Optional[str],
    trusted_builders: Optional[List[str]] = None,
) -> Optional[int]:
    """Infer SLSA level from builder identity.

    Known SLSA builders from the slsa-framework are mapped to their
    corresponding SLSA levels. Other builders default to level 1
    if they are in the trusted builders list.

    Args:
        builder: Builder identity string.
        trusted_builders: Optional list of trusted builder identities.

    Returns:
        Inferred SLSA level, or None if builder is unknown.
    """
    if not builder:
        return None

    # Well-known SLSA builders and their levels
    known_builders: Dict[str, int] = {
        "https://github.com/slsa-framework/slsa-github-generator": 3,
        "https://cloudbuild.googleapis.com/GoogleHostedWorker": 3,
    }

    for known_builder, level in known_builders.items():
        if builder.startswith(known_builder):
            return level

    # If builder is in trusted list, assume at least level 1
    if trusted_builders and builder in trusted_builders:
        return 1

    return None