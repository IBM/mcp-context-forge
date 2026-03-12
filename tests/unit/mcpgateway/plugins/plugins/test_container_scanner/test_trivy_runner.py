#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/unit/plugins/test_container_scanner/test_trivy_runner.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Agnetha

Unit tests for TrivyRunner._parse_trivy_result and async run().
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from plugins.container_scanner.config import ScannerConfig
from plugins.container_scanner.scanners.trivy_runner import TrivyRunner


def make_config(**kwargs) -> ScannerConfig:
    defaults = dict(scanner="trivy", mode="enforce")
    defaults.update(kwargs)
    return ScannerConfig(**defaults)


TRIVY_OUTPUT = {
    "Results": [
        {
            "Target": "app:latest (alpine 3.18)",
            "Vulnerabilities": [
                {
                    "VulnerabilityID": "CVE-2023-0001",
                    "Severity": "HIGH",
                    "PkgName": "libssl",
                    "InstalledVersion": "1.1.1t-r0",
                    "FixedVersion": "1.1.1u-r0",
                    "Description": "OpenSSL vulnerability",
                },
                {
                    "VulnerabilityID": "CVE-2023-0002",
                    "Severity": "CRITICAL",
                    "PkgName": "libcrypto",
                    "InstalledVersion": "1.1.1t-r0",
                    "FixedVersion": None,
                    "Description": None,
                },
            ],
        },
        {
            # Target with no vulnerabilities key — common in Trivy output
            "Target": "app:latest (config)",
        },
    ]
}


class TestTrivyRunnerParseResult:
    runner = TrivyRunner(make_config())

    def test_parses_high_severity(self):
        findings = self.runner._parse_trivy_result(TRIVY_OUTPUT)
        high = [f for f in findings if f.cve_id == "CVE-2023-0001"]
        assert len(high) == 1
        assert high[0].severity == "HIGH"
        assert high[0].package_name == "libssl"
        assert high[0].fixed_version == "1.1.1u-r0"
        assert high[0].scanner == "trivy"

    def test_parses_critical_with_no_fix(self):
        findings = self.runner._parse_trivy_result(TRIVY_OUTPUT)
        critical = [f for f in findings if f.cve_id == "CVE-2023-0002"]
        assert len(critical) == 1
        assert critical[0].fixed_version is None

    def test_target_with_no_vulnerabilities_key_is_skipped(self):
        # No "Vulnerabilities" key in the second target — should not raise
        findings = self.runner._parse_trivy_result(TRIVY_OUTPUT)
        assert len(findings) == 2  # only 2 vulns from the first target

    def test_empty_results(self):
        findings = self.runner._parse_trivy_result({})
        assert findings == []

    def test_empty_vulnerabilities_list(self):
        data = {"Results": [{"Target": "scratch", "Vulnerabilities": []}]}
        findings = self.runner._parse_trivy_result(data)
        assert findings == []

    def test_unknown_severity_is_included(self):
        data = {
            "Results": [
                {
                    "Target": "app:latest",
                    "Vulnerabilities": [
                        {
                            "VulnerabilityID": "CVE-2023-X",
                            "Severity": "UNKNOWN",
                            "PkgName": "libfoo",
                            "InstalledVersion": "1.0",
                        }
                    ],
                }
            ]
        }
        findings = self.runner._parse_trivy_result(data)
        assert len(findings) == 1
        assert findings[0].severity == "UNKNOWN"


class TestTrivyRunnerRun:
    @pytest.mark.asyncio
    async def test_run_raises_timeout_error(self):
        runner = TrivyRunner(make_config(timeout_seconds=30))
        mock_result = MagicMock(timed_out=True, returncode=0, stdout="", stderr="")
        with patch("plugins.container_scanner.scanners.trivy_runner.run_command", new=AsyncMock(return_value=mock_result)):
            with pytest.raises(TimeoutError, match="timed out"):
                await runner.run("ghcr.io/org/app:v1", {})

    @pytest.mark.asyncio
    async def test_run_raises_runtime_error_on_nonzero_exit(self):
        runner = TrivyRunner(make_config())
        mock_result = MagicMock(timed_out=False, returncode=1, stdout="", stderr="trivy: image not found")
        with patch("plugins.container_scanner.scanners.trivy_runner.run_command", new=AsyncMock(return_value=mock_result)):
            with pytest.raises(RuntimeError, match="Trivy exited 1"):
                await runner.run("ghcr.io/org/app:v1", {})

    @pytest.mark.asyncio
    async def test_run_returns_parsed_vulnerabilities(self):
        import json

        runner = TrivyRunner(make_config())
        mock_result = MagicMock(timed_out=False, returncode=0, stdout=json.dumps(TRIVY_OUTPUT), stderr="")
        with patch("plugins.container_scanner.scanners.trivy_runner.run_command", new=AsyncMock(return_value=mock_result)):
            vulns = await runner.run("ghcr.io/org/app:v1", {})
        assert len(vulns) == 2

    @pytest.mark.asyncio
    async def test_run_passes_auth_env_to_command(self):
        import json

        runner = TrivyRunner(make_config())
        mock_result = MagicMock(timed_out=False, returncode=0, stdout=json.dumps({}), stderr="")
        auth_env = {"TRIVY_USERNAME": "", "TRIVY_PASSWORD": "mytoken"}
        with patch("plugins.container_scanner.scanners.trivy_runner.run_command", new=AsyncMock(return_value=mock_result)) as mock_cmd:
            await runner.run("ghcr.io/org/app:v1", auth_env)
            called_env = mock_cmd.call_args.kwargs["env"]
            assert called_env["TRIVY_PASSWORD"] == "mytoken"

    @pytest.mark.asyncio
    async def test_run_handles_empty_stdout(self):
        runner = TrivyRunner(make_config())
        mock_result = MagicMock(timed_out=False, returncode=0, stdout="", stderr="")
        with patch("plugins.container_scanner.scanners.trivy_runner.run_command", new=AsyncMock(return_value=mock_result)):
            vulns = await runner.run("ghcr.io/org/app:v1", {})
        assert vulns == []
