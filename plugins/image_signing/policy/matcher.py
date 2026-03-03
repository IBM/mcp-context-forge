#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/image_signing/policy/matcher.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Xinyi

Trusted signer matching against identity and issuer from verification results.
"""

# Future
from __future__ import annotations

# Standard
import logging
import re
from datetime import datetime, timezone
from typing import List, Optional

# First-Party
from plugins.image_signing.types import MatchResult, SignerType, TrustedSigner

logger = logging.getLogger(__name__)


def match_signer(
    signer_identity: Optional[str],
    signer_issuer: Optional[str],
    trusted_signers: List[TrustedSigner],
) -> MatchResult:
    """Match a signer identity and issuer against a list of trusted signers.

    Iterates through trusted signers and returns the first match.
    A signer must be enabled and not expired to be considered.

    Args:
        signer_identity: Identity of the signer from cosign output (e.g. email or URI).
        signer_issuer: OIDC issuer of the signer from cosign output.
        trusted_signers: List of trusted signer configurations to match against.

    Returns:
        MatchResult indicating whether a match was found and which signer matched.
    """
    if not signer_identity:
        logger.debug("No signer identity provided, cannot match")
        return MatchResult(matched=False)

    for signer in trusted_signers:
        if not _is_signer_active(signer):
            continue

        if _matches(signer, signer_identity, signer_issuer):
            logger.info(
                "Signer matched: identity=%s, issuer=%s, matched_signer=%s",
                signer_identity,
                signer_issuer,
                signer.name,
            )
            return MatchResult(
                matched=True,
                matched_signer_id=signer.id,
                matched_signer_name=signer.name,
            )

    logger.info(
        "No trusted signer matched for identity=%s, issuer=%s",
        signer_identity,
        signer_issuer,
    )
    return MatchResult(matched=False)


def _is_signer_active(signer: TrustedSigner) -> bool:
    """Check whether a trusted signer is enabled and not expired.

    Args:
        signer: Trusted signer to check.

    Returns:
        True if signer is active, False otherwise.
    """
    if not signer.enabled:
        return False

    if signer.expires_at is not None:
        now = datetime.now(timezone.utc)
        expires = signer.expires_at
        # Handle naive datetime by assuming UTC
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if now > expires:
            return False

    return True


def _matches(
    signer: TrustedSigner,
    identity: str,
    issuer: Optional[str],
) -> bool:
    """Check whether a signer identity and issuer match a trusted signer config.

    Args:
        signer: Trusted signer configuration to match against.
        identity: Signer identity string from verification result.
        issuer: OIDC issuer string from verification result.

    Returns:
        True if the identity and issuer match the signer config.
    """
    if signer.type == SignerType.KEYLESS:
        return _match_keyless(signer, identity, issuer)

    if signer.type == SignerType.PUBLIC_KEY:
        # Public key matching happens during cosign verify via --key flag.
        # If cosign verify succeeded with this key, it's a match.
        return True

    if signer.type == SignerType.KMS:
        # Same as public key: KMS key matching happens during cosign verify.
        return True

    return False


def _match_keyless(
    signer: TrustedSigner,
    identity: str,
    issuer: Optional[str],
) -> bool:
    """Match a keyless signer against identity and issuer.

    For keyless signers, both issuer and identity (exact or regex) must match.

    Args:
        signer: Keyless trusted signer configuration.
        identity: Signer identity string.
        issuer: OIDC issuer string.

    Returns:
        True if issuer and identity match.
    """
    # Issuer must match
    if not signer.oidc_issuer or not issuer:
        return False
    if signer.oidc_issuer != issuer:
        return False

    # Identity: exact match
    if signer.subject:
        return signer.subject == identity

    # Identity: regex match
    if signer.subject_regex:
        try:
            return bool(re.fullmatch(signer.subject_regex, identity))
        except re.error:
            logger.warning(
                "Invalid regex in trusted signer %s: %s",
                signer.id,
                signer.subject_regex,
            )
            return False

    return False