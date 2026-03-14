#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/source_scanner/errors.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Xinyi

Shared exception types for Source Scanner Plugin.
"""

# Future
from __future__ import annotations


class SourceScannerError(Exception):
    """Base exception for source scanner plugin."""


class RepoFetchError(SourceScannerError):
    """Repository fetch/clone operation failed."""


class CloneTimeoutError(RepoFetchError):
    """Git clone operation timed out."""


class RepoSizeLimitError(RepoFetchError):
    """Repository exceeds size limit."""


class CheckoutError(RepoFetchError):
    """Git checkout operation failed."""


class ScannerError(SourceScannerError):
    """Scanner execution failed."""


class ScannerTimeoutError(ScannerError):
    """Scanner execution timed out."""


class ScannerNotFoundError(ScannerError):
    """Scanner executable not found."""


class ParseError(SourceScannerError):
    """Failed to parse scanner output."""


class PolicyError(SourceScannerError):
    """Policy evaluation failed."""
