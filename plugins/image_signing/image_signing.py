#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/image_signing/image_signing.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Xinyi

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
from dataclasses import dataclass, field

# First-Party
from mcpgateway.db import SessionLocal
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
#    AssessmentPostContainerScanPayload
#    AssessmentPostContainerScanResult
    PluginViolation,
)
from plugins.image_signing.config import ImageSigningConfig, TrustedSignerConfig
from plugins.image_signing.cosign.verifier import CosignVerifier
from plugins.image_signing.errors import CosignNotFoundError
from plugins.image_signing.policy.evaluator import evaluate_policy
from plugins.image_signing.policy.matcher import match_signer
from plugins.image_signing.storage.repository import ImageSigningRepository
from plugins.image_signing.types import (
    AttestationResult,
    EnforcementMode,
    MatchResult,
    SignatureVerificationResult,
    SlsaResult,
    TrustedSigner,
    VerificationResult,
    SignerType,
)

logger = logging.getLogger(__name__)

@dataclass
class AssessmentPostContainerScanPayload:
    """Stub until framework exports this type."""
    image_ref: str = ""
    image_digest: str | None = None
    assessment_id: str | None = None

@dataclass
class AssessmentPostContainerScanResult:
    """Stub until framework exports this type."""
    continue_processing: bool = True
    violation: PluginViolation | None = None


class ImageSigningPlugin(Plugin):
    """Verify container image signatures and SLSA attestations.

    Lifecycle:
        1. __init__: Parse config, create CosignVerifier instance
        2. startup (optional): Check cosign binary availability
        3. hook invocation: Verify image on each MCP server deployment
    """

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the Image Signing plugin.

        Args:
            config: Plugin configuration from gateway.
        """
        super().__init__(config)
        self._cfg = ImageSigningConfig(**(config.config or {}))
        self._verifier = CosignVerifier(
            cosign_config=self._cfg.cosign,
            verification_config=self._cfg.verification,
        )
        self._config_signers = self._get_trusted_signers_from_config()
        logger.info(
            "ImageSigningPlugin initialized: mode=%s, require_signature=%s, config_signers=%d",
            self._cfg.mode.value,
            self._cfg.verification.require_signature,
            len(self._config_signers),
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

        Args:
            image_ref: Container image reference (e.g. registry/repo:tag).
            image_digest: Optional image digest for immutable reference.
            assessment_id: Optional security assessment ID for DB linking.

        Returns:
            SignatureVerificationResult with full verification details.
        """
        logger.info("Verifying image: %s", image_ref)


        # Step 1: Gather trusted signers (config + DB)     
        trusted_signers = list(self._config_signers)
        try:
            with SessionLocal() as session:
                repo = ImageSigningRepository(session)
                db_signers = repo.list_trusted_signers(enabled_only=True)
                trusted_signers.extend(db_signers)
        except Exception:
            logger.warning("Failed to load DB signers, using config signers only", exc_info=True)

        # Step 2: Run cosign verify
        verification: Optional[VerificationResult] = None
        matched_config_signer: Optional[TrustedSigner] = None

        for signer in trusted_signers:
            if signer.type in {SignerType.PUBLIC_KEY, SignerType.KMS}:
                signer_config = self._domain_signer_to_config(signer)
                key_result = await self._verifier.verify(
                    image_ref=image_ref,
                    image_digest=image_digest,
                    signer=signer_config,
                )
                if key_result.signature_valid:
                    verification = key_result
                    matched_config_signer = signer
                    break

        # Fallback: keyless verify if no key-based signer matched
        if verification is None:
            verification = await self._verifier.verify(
                image_ref=image_ref,
                image_digest=image_digest,
            )

        # Step 3: Match signer identity
        if matched_config_signer is not None:
            signer_match = MatchResult(
                matched=True,
                matched_signer_id=matched_config_signer.id,
                matched_signer_name=matched_config_signer.name,
            )
        else:
            signer_match = match_signer(
                signer_identity=verification.signer_identity,
                signer_issuer=verification.signer_issuer,
                trusted_signers=trusted_signers,
            )

        # Step 4: Run SLSA attestation (if configured)
        attestation: Optional[AttestationResult] = None
        if self._cfg.slsa.require_attestation:
            attestation = await self._verifier.verify_attestation(
                image_ref=image_ref,
                trusted_builders=self._cfg.slsa.trusted_builders,
                image_digest=image_digest,
            )

        # Step 5: Evaluate policy
        decision = evaluate_policy(
            verification=verification,
            match=signer_match,
            config=self._cfg,
            attestation=attestation,
        )

        # Step 6: Assemble final result
        result = self._assemble_result(
            image_ref=image_ref,
            image_digest=image_digest,
            verification=verification,
            attestation=attestation,
            blocked=decision.blocked,
            reason=decision.reason,
        )

        # Step 7: Persist to DB
        try:
            with SessionLocal() as session:
                repo = ImageSigningRepository(session)
                repo.save_verification_result(result, assessment_id)
                session.commit()
        except Exception:
            logger.warning("Failed to persist verification result", exc_info=True)

        logger.info(
            "Verification complete: image=%s, signature_found=%s, blocked=%s",
            image_ref,
            result.signature_found,
            result.blocked,
        )

        return result

    # ------------------------------------------------------------------
    # Gateway hook integration
    # ------------------------------------------------------------------

    async def assessment_post_container_scan(
        self,
        payload: AssessmentPostContainerScanPayload,
        context: PluginContext,
    ) -> AssessmentPostContainerScanResult:
        """Hook called after container scan in assessment pipeline.

        Args:
            payload: Container scan payload with image reference.
            context: Plugin execution context.

        Returns:
            AssessmentPostContainerScanResult allowing or blocking the invocation.
        """
        # TODO: Confirm exact payload field names with #2215 integration
        def _first_attr(obj, names: list[str], default=""):
            for n in names:
                v = getattr(obj, n, None)
                if isinstance(v, str) and v.strip():
                    return v.strip()
            return default

        image_ref = _first_attr(payload, ["image_ref", "image", "image_reference", "container_image"])
        image_digest = getattr(payload, "image_digest", None) or getattr(payload, "digest", None)
        assessment_id = getattr(payload, "assessment_id", None)

        if not image_ref:
            logger.warning("No image_ref in payload, skipping verification")
            return AssessmentPostContainerScanResult(continue_processing=True)

        try:
            result = await self.verify_image(
                image_ref=image_ref,
                image_digest=image_digest,
                assessment_id=assessment_id,
            )
        except CosignNotFoundError:
            logger.error("Cosign binary not found, cannot verify images")
            if self._cfg.mode == EnforcementMode.ENFORCE:
                return AssessmentPostContainerScanResult(
                    continue_processing=False,
                    violation=PluginViolation(
                        reason="Image signature verification unavailable",
                        description="Cosign binary not found on system",
                        code="IMAGE_SIGNING_UNAVAILABLE",
                    ),
                )

            logger.warning("AUDIT mode: skipping verification because cosign is missing")    
            return AssessmentPostContainerScanResult(continue_processing=True)

        if result.blocked and self._cfg.mode == EnforcementMode.ENFORCE:
            return AssessmentPostContainerScanResult(
                continue_processing=False,
                violation=PluginViolation(
                    reason="Image signature verification failed",
                    description=result.reason or "Policy violation",
                    code="IMAGE_SIGNING",
                    details=result.model_dump(),
                ),
            )

        if result.reason:
            logger.warning("Image signing audit: %s", result.reason)

        return AssessmentPostContainerScanResult(continue_processing=True)

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------

    def _get_trusted_signers_from_config(self) -> List[TrustedSigner]:
        """Convert inline TrustedSignerConfig entries to TrustedSigner domain objects.

        Returns:
            List of TrustedSigner domain objects from YAML config.
        """
        signers: List[TrustedSigner] = []
        for index, signer_config in enumerate(self._cfg.trusted_signers):
            signers.append(
                TrustedSigner(
                    id=f"config-{index}",
                    name=f"config-signer-{index}",
                    type=signer_config.type,
                    oidc_issuer=signer_config.oidc_issuer,
                    subject=signer_config.subject,
                    subject_regex=signer_config.subject_regex,
                    public_key=signer_config.public_key,
                    kms_key_ref=signer_config.kms_key_ref,
                )
            )
        return signers

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

    
    @staticmethod
    def _domain_signer_to_config(signer: TrustedSigner) -> TrustedSignerConfig:
        """Convert TrustedSigner domain object back to TrustedSignerConfig for cosign verify.

        Args:
            signer: TrustedSigner domain object.

        Returns:
            TrustedSignerConfig for command builder.
        """
        return TrustedSignerConfig(
            type=signer.type,
            oidc_issuer=signer.oidc_issuer,
            subject=signer.subject,
            subject_regex=signer.subject_regex,
            public_key=signer.public_key,
            kms_key_ref=signer.kms_key_ref,
        )    