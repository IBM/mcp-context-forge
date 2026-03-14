# -*- coding: utf-8 -*-
"""Location: ./plugins/image_signing/errors.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Xinyi

Custom exceptions for the Image Signing & Verification plugin.
"""

# Future
from __future__ import annotations


class ImageSigningError(Exception):
    """Base exception for the image signing plugin."""


class CosignNotFoundError(ImageSigningError):
    """Raised when the Cosign CLI binary is not found."""


class CosignTimeoutError(ImageSigningError):
    """Raised when a Cosign CLI invocation exceeds the configured timeout."""


class CosignVerificationError(ImageSigningError):
    """Raised when Cosign returns a verification failure."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)    


class RegistryAuthError(ImageSigningError):
    """Raised when authentication to the container registry fails."""


class RegistryConnectionError(ImageSigningError):
    """Raised when the container registry is unreachable."""


class RekorLookupError(ImageSigningError):
    """Raised when the Rekor transparency log lookup fails."""


class PolicyViolationError(ImageSigningError):
    """Raised when an image violates the signing policy in enforce mode.

    Attributes:
        reason: Human-readable description of the policy violation.
    """

    def __init__(self, reason: str) -> None:
        """Initialize PolicyViolationError.

        Args:
            reason: Description of the policy violation.
        """
        self.reason = reason
        super().__init__(reason)


class AttestationError(ImageSigningError):
    """Raised when SLSA attestation verification fails."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)    