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
from typing import List, Optional

# First-Party
from plugins.image_signing.types import MatchResult, TrustedSigner


def match_signer(
    signer_identity: Optional[str],
    signer_issuer: Optional[str],
    trusted_signers: List[TrustedSigner],
) -> MatchResult:
    """Match a signer identity and issuer against a list of trusted signers.

    Iterates through trusted signers and returns the first match.
    A signer must be enabled and not expired to be considered.

    Args:
        signer_identity: Identity of the signer from cosign output.
        signer_issuer: OIDC issuer of the signer from cosign output.
        trusted_signers: List of trusted signer configurations.

    Returns:
        MatchResult indicating whether a match was found.
    """
    raise NotImplementedError