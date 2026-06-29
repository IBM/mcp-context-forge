#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/sbom_generator/query/__init__.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Fionn Gavin
"""

from .component_search import ComponentSearch, ComponentSearchResult
from .cve_correlation import AffectedServer, CVECorrelation
from .license_analyzer import LicenseAnalyzer, LicenseSummary, ServerLicenseReport

__all__ = [
    "ComponentSearch",
    "ComponentSearchResult",
    "AffectedServer",
    "CVECorrelation",
    "LicenseAnalyzer",
    "LicenseSummary",
    "ServerLicenseReport",
]
