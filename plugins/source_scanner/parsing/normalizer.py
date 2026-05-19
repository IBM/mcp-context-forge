#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Finding normalization and deduplication.

Location: ./plugins/source_scanner/parsing/normalizer.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Ayo

Handles merging findings from multiple scanners and deduplication.
"""

# Standard
from typing import List

# Local
from ..models import Finding


class FindingNormalizer:
    """Merge and deduplicate findings from multiple scanners."""

    def merge_dedup(self, findings_by_scanner: List[List[Finding]]) -> List[Finding]:
        """
        Merge findings from all scanners and remove duplicates.

        Args:
            findings_by_scanner: List of finding lists (one per scanner)

        Returns:
            Deduplicated list of all findings

        Example:
            >>> semgrep_findings = [Finding(...), Finding(...)]
            >>> bandit_findings = [Finding(...)]
            >>> normalizer = FindingNormalizer()
            >>> merged = normalizer.merge_dedup([semgrep_findings, bandit_findings])
        """
        # Flatten all findings into single list
        all_findings: List[Finding] = []
        for findings in findings_by_scanner:
            all_findings.extend(findings)

        # Deduplicate using Finding.dedup_key()
        seen_keys = set()
        unique_findings: List[Finding] = []

        for finding in all_findings:
            key = finding.dedup_key()
            if key not in seen_keys:
                seen_keys.add(key)
                unique_findings.append(finding)

        return unique_findings
