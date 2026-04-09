#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/source_scanner/report.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Author: Yanko

Generates a report from the scanner json findings
"""

# from plugins.source_scanner.parsing.normalizer import Normalizer

# Standard
from typing import Dict, List

# Local
from .models import Finding


class Report:
    """Generates a report from the scanner's findings"""

    def __init__(self, findings: List[Finding]):
        """initialize the report

        Args:
            findings: List of findings from the scanner
        """

        self.findings = findings

    def summary(self) -> Dict[str, int]:
        """gives a summary of the findings

        Returns:
            A Dictionary with a summary of the findings"""

        levels = {"ERROR": 0, "WARNING": 0, "INFO": 0}

        for finding in self.findings:
            levels[finding.severity] += 1

        summary = {
            # "total_findings": len(self.findings),
            "total_issues": (levels["ERROR"] + levels["WARNING"] + levels["INFO"]),
            "ERROR": levels["ERROR"],
            "WARNING": levels["WARNING"],
            "INFO": levels["INFO"],
        }
        return summary

    def ordered(self) -> Dict[str, Dict[str, int]]:
        """gives an rdered list of the findings

        Returns:
            A Dictionary with 3 Dictionaries named after the severity levels, each containing issues of that severity and their counts"""

        ordered: Dict[str, Dict[str, int]] = {"ERROR": {}, "WARNING": {}, "INFO": {}}

        for finding in self.findings:
            if finding.rule_id not in ordered[finding.severity]:
                ordered[finding.severity][finding.rule_id] = 1
            else:
                ordered[finding.severity][finding.rule_id] += 1
        return ordered
    
    def detailed(self) -> List[Finding]:
        """gives the Findings in details"""
        
        return self.findings