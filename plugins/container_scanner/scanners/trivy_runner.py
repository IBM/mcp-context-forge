#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/container_scanner/scanners/trivy_runner.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Agnetha

Trivy scanner runner — executes the Trivy CLI and normalizes its JSON output
into the unified Vulnerability schema.
"""

# Future
from __future__ import annotations

# Standard
import json
import os
from typing import Any, Dict, List

# Local
from plugins.container_scanner.config import ScannerConfig
from plugins.container_scanner.scanners.base import ScannerRunner
from plugins.container_scanner.types import Vulnerability
from mcpgateway.utils.exec import run_command

# UNKNOWN is included: Trivy emits it when no CVSS score exists (common in
# Alpine/Debian vendor advisories). Dropping UNKNOWN silently would hide real CVEs.
_SEVERITY_MAP = {"CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"}


class TrivyRunner(ScannerRunner):
    def __init__(self, config: ScannerConfig) -> None:
        super().__init__()
        self.enabled = config.mode != "disabled"
        self.timeout_s = config.timeout_seconds
        self.mode = config.mode

    def _parse_trivy_result(self, scan_output: dict[str, Any]) -> List[Vulnerability]:
        findings: List[Vulnerability] = []
        results = scan_output.get("Results", [])

        for result in results:
            # Trivy omits "Vulnerabilities" entirely when a target has none — use `or []`
            for vuln in result.get("Vulnerabilities") or []:
                if vuln.get("Severity") not in _SEVERITY_MAP:
                    continue
                findings.append(
                    Vulnerability(
                        scanner="trivy",
                        cve_id=vuln.get("VulnerabilityID"),
                        severity=vuln.get("Severity"),
                        package_name=vuln.get("PkgName"),
                        installed_version=vuln.get("InstalledVersion"),
                        fixed_version=vuln.get("FixedVersion"),
                        description=vuln.get("Description"),
                    )
                )

        return findings

    async def run(self, image_ref: str, auth_env: Dict[str, str]) -> List[Vulnerability]:
        commands = ["trivy", "image", "--format", "json", "--quiet", "--timeout", f"{self.timeout_s}s", image_ref]

        # Merge auth credentials into the subprocess environment.
        # auth_env is {} for public images so this is a no-op in the common case.
        env = {**os.environ, **auth_env}
        result = await run_command(cmd=commands, timeout_seconds=self.timeout_s, cwd=None, env=env)

        if result.timed_out:
            raise TimeoutError(f"Trivy scan timed out after {self.timeout_s}s for '{image_ref}'")
        if result.returncode != 0:
            raise RuntimeError(f"Trivy exited {result.returncode} for '{image_ref}'. stderr: {result.stderr.strip()}")

        data: dict[str, Any] = json.loads(result.stdout) if result.stdout else {}
        return self._parse_trivy_result(data)
