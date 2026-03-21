#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/image_signing/cosign/verifier.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Xinyi

High-level cosign verify and verify-attestation orchestration.
"""

# Future
from __future__ import annotations

# Standard
import logging
from typing import Dict, List, Optional

# First-Party
from plugins.image_signing.config import CosignConfig, TrustedSignerConfig, VerificationConfig
from plugins.image_signing.cosign.command_builder import (
    build_verify_attestation_command,
    build_verify_command,
)
from plugins.image_signing.cosign.parser import parse_attestation_output, parse_verify_output
from plugins.image_signing.cosign.runner import check_cosign_installed, run_cosign
from plugins.image_signing.errors import CosignNotFoundError, CosignTimeoutError, CosignVerificationError
from plugins.image_signing.types import AttestationResult, SignerType, VerificationResult

logger = logging.getLogger(__name__)


class CosignVerifier:
    """High-level wrapper for cosign signature and attestation verification.

    Orchestrates command building, execution, and output parsing
    for cosign verify and cosign verify-attestation flows.

    Attributes:
        cosign_config: Cosign CLI settings (path, timeout).
        verification_config: Signature verification settings.
    """

    def __init__(
        self,
        cosign_config: CosignConfig,
        verification_config: VerificationConfig,
    ) -> None:
        """Initialize CosignVerifier.

        Args:
            cosign_config: Cosign CLI settings (path, timeout).
            verification_config: Signature verification settings.
        """
        self._cosign_config = cosign_config
        self._verification_config = verification_config

    def check_available(self) -> None:
        """Check that the cosign binary is installed and accessible.

        Raises:
            CosignNotFoundError: If cosign binary is not found.
        """
        check_cosign_installed(self._cosign_config.path)

    async def verify(
        self,
        image_ref: str,
        signer: Optional[TrustedSignerConfig] = None,
        image_digest: Optional[str] = None,
    ) -> VerificationResult:
        """Verify a container image signature using cosign.

        Builds the appropriate cosign verify command, executes it,
        and parses the output into a normalized VerificationResult.

        Args:
            image_ref: Container image reference (e.g. registry/repo:tag).
            signer: Optional trusted signer config to constrain verification.
            image_digest: Optional image digest for immutable reference.

        Returns:
            Normalized VerificationResult with signature status and signer info.
        """
        cmd = build_verify_command(
            image_ref=image_ref,
            cosign_config=self._cosign_config,
            verification_config=self._verification_config,
            signer=signer,
            image_digest=image_digest,
        )

        # For PUBLIC_KEY signers, pass the PEM via environment variable
        env_override = _build_env_for_signer(signer)

        try:
            result = await run_cosign(
                cmd=cmd,
                timeout_seconds=self._cosign_config.timeout_seconds,
                env_override=env_override,
                raise_on_nonzero=True,
            )
        except CosignNotFoundError:
            raise
        except (CosignTimeoutError, CosignVerificationError) as exc:
            logger.warning("Cosign verify failed for %s: %s", image_ref, exc)
            return VerificationResult(
                signature_found=False,
                signature_valid=False,
                error=str(exc),
            )
        except Exception:
            logger.exception("Unexpected error during cosign verify for %s", image_ref)
            raise

        return parse_verify_output(
            stdout=result.stdout,
            stderr=result.stderr,
            return_code=result.returncode,
        )

    async def verify_attestation(
        self,
        image_ref: str,
        trusted_builders: Optional[List[str]] = None,
        image_digest: Optional[str] = None,
        attestation_type: str = "slsaprovenance",
    ) -> AttestationResult:
        """Verify SLSA attestation for a container image using cosign.

        Builds the appropriate cosign verify-attestation command, executes it,
        and parses the output into a normalized AttestationResult.

        Args:
            image_ref: Container image reference (e.g. registry/repo:tag).
            trusted_builders: Optional list of trusted builder identities.
            image_digest: Optional image digest for immutable reference.
            attestation_type: Attestation predicate type to verify.

        Returns:
            Normalized AttestationResult with SLSA level and builder info.
        """
        cmd = build_verify_attestation_command(
            image_ref=image_ref,
            cosign_config=self._cosign_config,
            verification_config=self._verification_config,
            attestation_type=attestation_type,
            image_digest=image_digest,
        )

        try:
            result = await run_cosign(
                cmd=cmd,
                timeout_seconds=self._cosign_config.timeout_seconds,
                raise_on_nonzero=True,
            )
        except CosignNotFoundError:
            raise
        except (CosignTimeoutError, CosignVerificationError) as exc:
            logger.warning("Cosign verify-attestation failed for %s: %s", image_ref, exc)
            return AttestationResult(
                attestation_found=False,
                valid=False,
            )
        except Exception:
            logger.exception("Unexpected error during cosign verify-attestation for %s", image_ref)
            raise

        return parse_attestation_output(
            stdout=result.stdout,
            stderr=result.stderr,
            return_code=result.returncode,
            trusted_builders=trusted_builders,
        )


def _build_env_for_signer(signer: Optional[TrustedSignerConfig]) -> Optional[Dict[str, str]]:
    """Build environment variable overrides for signer-specific verification.

    For PUBLIC_KEY signers, the PEM key is passed via the COSIGN_PUBLIC_KEY
    environment variable, matching the env://COSIGN_PUBLIC_KEY reference
    set by command_builder.

    Args:
        signer: Optional trusted signer config.

    Returns:
        Dictionary of environment variables, or None if not needed.
    """
    if signer is None:
        return None

    if signer.type == SignerType.PUBLIC_KEY and signer.public_key:
        return {"COSIGN_PUBLIC_KEY": signer.public_key}

    return None