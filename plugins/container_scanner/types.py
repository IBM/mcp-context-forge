#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/container_scanner/types.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Agnetha

Data schemas for findings and scan results.
"""

# Future
from __future__ import annotations

# Standard
import datetime
from typing import List, Literal, Optional

# Third-Party
from pydantic import BaseModel

class Vulnerability(BaseModel):
    """Unified vulnerability schema from any scanner.

    Attributes:
        scanner: Scanner tool name (e.g., "trivy", "grype").
        cve_id: CVE identifier (e.g., "CVE-2023-12345").
        severity: Normalized severity level (CRITICAL|HIGH|MEDIUM|LOW).
        package_name: Name of the vulnerable package.
        installed_version: Currently installed version.
        fixed_version: Version that fixes the vulnerability, if available.
        description: Human-readable description of the vulnerability.
    """

    scanner: Literal["trivy", "grype"]
    cve_id: str
    severity: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"]
    package_name: str
    installed_version: str
    fixed_version: Optional[str] = None
    description: Optional[str] = None

class Summary(BaseModel):
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int


class ScanResult(BaseModel):
    """Complete scan result contract.

    Attributes:
        image_ref:
        image_digest:
        scanners:
        scan_time:
        duration_ms:
        vulnerabilities:
        summary:
        blocked:
        reason:
        scan_error:
    """

    image_ref : str
    image_digest : Optional[str] = None
    scanners: Literal["trivy", "grype"]
    scan_time: datetime.datetime
    duration_ms: int
    vulnerabilities: List[Vulnerability]
    summary: Summary
    blocked:bool
    reason : Optional[str] = None
    scan_error : Optional[str] = None
