#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Location: tests/unit/plugins/test_source_scanner/test_errors.py
Copyright: 2026
SPDX-License-Identifier: Apache-2.0
Authors: Yaser
"""

# First-Party
from plugins.source_scanner.errors import (
    CheckoutError,
    CloneTimeoutError,
    ParseError,
    PolicyError,
    RepoFetchError,
    RepoSizeLimitError,
    ScannerError,
    ScannerNotFoundError,
    ScannerTimeoutError,
    SourceScannerError,
)


def test_exception_hierarchy() -> None:
    assert issubclass(RepoFetchError, SourceScannerError)
    assert issubclass(CloneTimeoutError, RepoFetchError)
    assert issubclass(RepoSizeLimitError, RepoFetchError)
    assert issubclass(CheckoutError, RepoFetchError)

    assert issubclass(ScannerError, SourceScannerError)
    assert issubclass(ScannerTimeoutError, ScannerError)
    assert issubclass(ScannerNotFoundError, ScannerError)

    assert issubclass(ParseError, SourceScannerError)
    assert issubclass(PolicyError, SourceScannerError)
