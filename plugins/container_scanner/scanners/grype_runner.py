#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/container_scanner/scanners/grype_runner.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Agnetha

Grype scanner runner — executes the Grype CLI and normalizes its JSON output
into the unified Vulnerability schema.
"""

# Future
from __future__ import annotations

# Standard
import json
import os
from typing import Any, Dict, List, Optional

# Local
from plugins.container_scanner.config import ScannerConfig
from plugins.container_scanner.scanners.base import ScannerRunner
from plugins.container_scanner.types import Vulnerability
from mcpgateway.utils.exec import run_command

_SEVERITY_MAP = {"CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"}


class GrypeRunner(ScannerRunner):
    def __init__(self, config: ScannerConfig) -> None:
        super().__init__()
        self.enabled = config.mode != "disabled"
        self.timeout_s = config.timeout_seconds
        self.mode = config.mode

    def _extract_fixed_version(self, fix: dict[str, Any]) -> Optional[str]:
        if fix.get("state") == "fixed":
            versions = fix.get("versions") or []
            return versions[0] if versions else None
        return None

    def _parse_grype_result(self, scan_output: dict[str, Any]) -> List[Vulnerability]:
        """Parse Grype JSON output into unified Vulnerability objects.

        Grype's top-level structure:
            {"matches": [{"vulnerability": {...}, "artifact": {...}}, ...]}

        Each match pairs one CVE record with one affected package.
        """
        findings: List[Vulnerability] = []

        for match in scan_output.get("matches") or []:
            vuln = match.get("vulnerability") or {}
            artifact = match.get("artifact") or {}

            cve_id: str = vuln.get("id") or ""
            if not cve_id:
                continue

            raw_severity: str = (vuln.get("severity") or "").upper()
            if raw_severity not in _SEVERITY_MAP:
                continue

            fix_info: dict[str, Any] = vuln.get("fix") or {}
            fixed_version = self._extract_fixed_version(fix_info)

            findings.append(
                Vulnerability(
                    scanner="grype",
                    cve_id=cve_id,
                    severity=raw_severity,
                    package_name=artifact.get("name") or "",
                    installed_version=artifact.get("version") or "",
                    fixed_version=fixed_version,
                    description=vuln.get("description"),
                )
            )

        return findings

    async def run(self, image_ref: str, auth_env: Dict[str, str]) -> List[Vulnerability]:
        # -o json — machine-readable output
        # -q     — suppress progress bars / status lines so stdout is pure JSON
        commands = ["grype", image_ref, "-o", "json", "-q"]

        # Merge auth credentials into the subprocess environment.
        # auth_env is {} for public images so this is a no-op in the common case.
        env = {**os.environ, **auth_env}
        result = await run_command(cmd=commands, timeout_seconds=self.timeout_s, cwd=None, env=env)

        if result.timed_out:
            raise TimeoutError(f"Grype scan timed out after {self.timeout_s}s for '{image_ref}'")
        if result.returncode != 0:
            raise RuntimeError(f"Grype exited {result.returncode} for '{image_ref}'. stderr: {result.stderr.strip()}")

        data: dict[str, Any] = json.loads(result.stdout) if result.stdout else {}
        return self._parse_grype_result(data)
