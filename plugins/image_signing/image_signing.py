#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/image_signing/image_signing.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Xinyi, Liam

Image Signing & Verification Plugin.
Verifies container image signatures and SLSA attestations before MCP server deployment.

Architecture:
    This plugin is the main orchestrator that wires together:
    - CosignVerifier (cosign/) -> signature + attestation verification
    - TrustedSignerMatcher (policy/matcher.py) -> signer identity matching
    - PolicyEvaluator (policy/evaluator.py) -> enforce/audit decision
    - Repository (storage/repository.py) -> DB persistence

Flow:
    1. Receive image_ref from security assessment pipeline hook
    2. CosignVerifier.verify() -> VerificationResult
    3. match_signer() -> MatchResult
    4. CosignVerifier.verify_attestation() -> AttestationResult (if configured)
    5. evaluate_policy() -> PolicyDecision
    6. Assemble SignatureVerificationResult
    7. Persist to DB via repository
    8. Return result / raise PolicyViolationError if blocked in ENFORCE mode
"""

# Future
from __future__ import annotations

# Standard
import logging
from typing import List, Optional

# First-Party
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    AssessmentPostContainerScanPayload,
    AssessmentPostContainerScanResult,
    PluginViolation,
)
from plugins.image_signing.config import ImageSigningConfig, TrustedSignerConfig
from plugins.image_signing.cosign.verifier import CosignVerifier
from plugins.image_signing.policy.evaluator import evaluate_policy
from plugins.image_signing.policy.matcher import match_signer
from plugins.image_signing.types import (
    AttestationResult,
    EnforcementMode,
    MatchResult,
    SignatureVerificationResult,
    SlsaResult,
    TrustedSigner,
    VerificationResult,
)

logger = logging.getLogger(__name__)


class ImageSigningPlugin(Plugin):
    """Verify container image signatures and SLSA attestations.

    TODO(Liam): Wire this plugin into the gateway's plugin framework.
        Reference: plugins/code_safety_linter/code_safety_linter.py

    Lifecycle:
        1. __init__: Parse config, create CosignVerifier instance
        2. startup (optional): Check cosign binary availability
        3. hook invocation: Verify image on each MCP server deployment
    """

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the Image Signing plugin.

        TODO(Liam):
            - Call super().__init__(config)
            - Parse config.config dict into ImageSigningConfig
            - Create CosignVerifier with cosign_config + verification_config
            - Load inline trusted_signers from config
            - Optionally check cosign availability at startup

        Args:
            config: Plugin configuration from gateway.
        """
        super().__init__(config)
        self._cfg = ImageSigningConfig(**(config.config or {}))
        self._verifier = CosignVerifier(
            cosign_config=self._cfg.cosign,
            verification_config=self._cfg.verification,
        )
        logger.info(
            "ImageSigningPlugin initialized: mode=%s, require_signature=%s",
            self._cfg.mode.value,
            self._cfg.verification.require_signature,
        )

    # ------------------------------------------------------------------
    # Core verification method
    # ------------------------------------------------------------------

    async def verify_image(
        self,
        image_ref: str,
        image_digest: Optional[str] = None,
        assessment_id: Optional[str] = None,
    ) -> SignatureVerificationResult:
        """Run full verification pipeline for a container image.

        TODO(Liam): This is the main method called by:
            1. The security assessment pipeline hook
            2. The manual POST /api/v1/image-signing/verify endpoint

        Implementation steps:
            1. Gather trusted signers:
                - From YAML config: self._cfg.trusted_signers
                - From DB: await repository.list_trusted_signers(session)
                - Merge both lists into List[TrustedSigner]
               NOTE: _config_signer_to_domain() helper converts TrustedSignerConfig -> TrustedSigner

            2. Run cosign verify:
                verification = await self._verifier.verify(image_ref=image_ref, image_digest=image_digest)
            
            3. Match signer identity:
                match = match_signer(
                    signer_identity=verification.signer_identity,
                    signer_issuer=verification.signer_issuer,
                    trusted_signers=trusted_signers,
                )
            
            4. Run SLSA attestation (if configured):
                if self._cfg.slsa.require_attestation:
                    attestation = await self._verifier.verify_attestation(
                        image_ref=image_ref,
                        trusted_builders=self._cfg.slsa.trusted_builders,
                        image_digest=image_digest,
                    )
                
                NOTE: attestation: Optional[AttestationResult] = None if not required/configured

            5. Evaluate policy (Xinyi provides implementation):
                decision = evaluate_policy(verification = verification, match = match, config = self._cfg, attestation = attestation)

            6. Assemble SignatureVerificationResult:
                - Map fields from verification, match, attestation, decision
                - Use _assemble_result() helper below

            7. Persist to DB:
                await repository.save_verification_result(session, result, assessment_id)

            8. Return result

        Args:
            image_ref: Container image reference (e.g. registry/repo:tag).
            image_digest: Optional image digest for immutable reference.

        Returns:
            SignatureVerificationResult with full verification details.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Gateway hook integration
    # ------------------------------------------------------------------

    async def assessment_post_container_scan(
        self,
        payload: AssessmentPostContainerScanPayload,
        context: PluginContext,
    ) -> AssessmentPostContainerScanResult:
        """
        Hook called after container scan in assessment pipeline.

        TODO(Liam): Extract image_ref from payload and call verify_image().
            - Extract image_ref from payload (format TBD based on gateway contract)
            - Call self.verify_image(image_ref)
            - If result.blocked and mode == ENFORCE:
                return AssessmentPostContainerScanResult(
                    blocked=True,
                    violation=PluginViolation(
                        reason="Image signature verification failed",
                        description=result.reason,
                        code="IMAGE_SIGNING",
                        details=result.model_dump(),
                    ),
                )
            - Otherwise: return AssessmentPostContainerScanResult(continue_processing=True)

        NOTE: The exact payload field for image_ref depends on how the
            security assessment pipeline passes container info.
            Coordinate with #2215 integration.

        Args:
            payload: Tool invocation payload.
            context: Plugin execution context.

        Returns:
            AssessmentPostContainerScanResult allowing or blocking the invocation.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------

    def _get_trusted_signers_from_config(self) -> List[TrustedSigner]:
        """Convert inline TrustedSignerConfig entries to TrustedSigner domain objects.

        TODO(Liam):
            - Iterate self._cfg.trusted_signers
            - For each, create TrustedSigner with:
                id=f"config-{index}"  (synthetic ID for config-sourced signers)
                name=f"config-signer-{index}"
                type=signer_config.type
                oidc_issuer=signer_config.oidc_issuer
                subject=signer_config.subject
                subject_regex=signer_config.subject_regex
                public_key=signer_config.public_key
                kms_key_ref=signer_config.kms_key_ref
            - Return list

        Returns:
            List of TrustedSigner domain objects from YAML config.
        """
        raise NotImplementedError

    @staticmethod
    def _assemble_result(
        image_ref: str,
        image_digest: Optional[str],
        verification: VerificationResult,
        attestation: Optional[AttestationResult],
        blocked: bool,
        reason: Optional[str],
    ) -> SignatureVerificationResult:
        """Assemble the final SignatureVerificationResult from component results.

        TODO(Liam):
            return SignatureVerificationResult(
                image_ref=image_ref,
                image_digest=image_digest,
                signature_found=verification.signature_found,
                signature_valid=verification.signature_valid,
                signer_identity=verification.signer_identity,
                signer_issuer=verification.signer_issuer,
                signed_at=verification.signed_at,
                rekor_verified=verification.rekor_verified,
                slsa=SlsaResult(
                    attestation_found=attestation.attestation_found if attestation else None,
                    level=attestation.level if attestation else None,
                    builder=attestation.builder if attestation else None,
                ),
                blocked=blocked,
                reason=reason,
            )

        Args:
            image_ref: Container image reference.
            image_digest: Image digest.
            verification: Cosign verification result.
            attestation: Optional SLSA attestation result.
            blocked: Whether image is blocked.
            reason: Block reason if applicable.

        Returns:
            Assembled SignatureVerificationResult.
        """
        raise NotImplementedError