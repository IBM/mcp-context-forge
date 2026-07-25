#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/sbom_generator/errors.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Ayo

Custom exceptions for the SBOM Generator plugin.
"""


class SBOMGeneratorError(Exception):
    """Base exception for all SBOM Generator plugin errors."""

    def __init__(self, message: str, details: dict | None = None):
        """
        Initialize SBOM Generator error.

        Args:
            message: Human-readable error message
            details: Additional context about the error
        """
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        """Return string representation of error."""
        if self.details:
            details_str = ", ".join(f"{k}={v}" for k, v in self.details.items())
            return f"{self.message} ({details_str})"
        return self.message


class ExtractionError(SBOMGeneratorError):
    """Raised when dependency extraction fails."""

    pass


class GenerationError(SBOMGeneratorError):
    """Raised when SBOM document generation fails."""

    pass


class StorageError(SBOMGeneratorError):
    """Raised when SBOM storage operations fail."""

    pass


class ValidationError(SBOMGeneratorError):
    """Raised when SBOM validation fails."""

    pass


class TimeoutError(SBOMGeneratorError):
    """Raised when operations exceed configured timeouts."""

    pass


class UnsupportedFormatError(SBOMGeneratorError):
    """Raised when requested SBOM format is not supported."""

    pass
