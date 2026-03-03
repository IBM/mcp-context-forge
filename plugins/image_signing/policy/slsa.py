#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/image_signing/policy/slsa.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Xinyi

SLSA attestation level checking and builder validation.
"""

# Future
from __future__ import annotations

# Standard
import logging
from typing import List, Optional

# First-Party
from plugins.image_signing.types import AttestationResult

logger = logging.getLogger(__name__)


def check_slsa_requirements(
    attestation: AttestationResult | None = None,
    require_attestation: bool = False,
    minimum_level: Optional[int] = None,
    trusted_builders: Optional[List[str]] = None,
) -> tuple[bool, Optional[str]]:
    """Check whether SLSA attestation meets policy requirements.

    Checks are evaluated in order:
        1. If require_attestation=False, always pass
        2. If attestation is None or not found, fail
        3. If attestation is invalid, fail
        4. If minimum_level is set and level is below it, fail
        5. If trusted_builders is set and builder is not in the list, fail

    Args:
        attestation: Attestation verification result, or None if not checked.
        require_attestation: Whether attestation is required.
        minimum_level: Minimum acceptable SLSA level.
        trusted_builders: Optional list of trusted builder identities.

    Returns:
        Tuple of (passed, reason). passed=True if requirements met,
        reason is set when passed=False.
    """
    if not require_attestation:
        return True, None

    # Attestation required but not provided or not found
    if attestation is None or not attestation.attestation_found:
        return False, "SLSA attestation required but not found"

    # Attestation found but invalid
    if not attestation.valid:
        return False, "SLSA attestation found but invalid"

    # Minimum level check
    if minimum_level is not None:
        if attestation.level is None:
            return False, f"SLSA level required (minimum {minimum_level}) but not present in attestation"
        if attestation.level < minimum_level:
            return False, f"SLSA level {attestation.level} below minimum required level {minimum_level}"

    # Trusted builder check
    if trusted_builders and attestation.builder:
        if attestation.builder not in trusted_builders:
            return False, f"Builder '{attestation.builder}' is not in the trusted builders list"

    return True, None