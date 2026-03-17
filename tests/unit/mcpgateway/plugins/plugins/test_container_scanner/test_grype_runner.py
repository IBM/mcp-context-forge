#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/unit/plugins/test_container_scanner/test_grype_runner.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Agnetha

Unit tests for GrypeRunner._parse_grype_result and async run().
"""

from __future__ import annotations

import json
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from plugins.container_scanner.config import ScannerConfig
from plugins.container_scanner.scanners.grype_runner import GrypeRunner


def make_config(**kwargs: Any) -> ScannerConfig:
    defaults: Dict[str, Any] = dict(scanner="grype", mode="enforce")
    defaults.update(kwargs)
    return ScannerConfig(**defaults)


GRYPE_OUTPUT = {
    "matches": [
        {
            "vulnerability": {
                "id": "CVE-2023-0001",
                "severity": "HIGH",
                "description": "OpenSSL vulnerability",
                "fix": {"state": "fixed", "versions": ["1.1.1u-r0"]},
            },
            "artifact": {"name": "libssl", "version": "1.1.1t-r0"},
        },
        {
            "vulnerability": {
                "id": "CVE-2023-0002",
                "severity": "CRITICAL",
                "description": None,
                "fix": {"state": "not-fixed", "versions": []},
            },
            "artifact": {"name": "libcrypto", "version": "1.1.1t-r0"},
        },
    ]
}


class TestGrypeRunnerParseResult:
    runner = GrypeRunner(make_config())

    def test_parses_high_severity(self):
        findings = self.runner._parse_grype_result(GRYPE_OUTPUT)
        high = [f for f in findings if f.cve_id == "CVE-2023-0001"]
        assert len(high) == 1
        assert high[0].severity == "HIGH"
        assert high[0].package_name == "libssl"
        assert high[0].installed_version == "1.1.1t-r0"
        assert high[0].scanner == "grype"

    def test_parses_fixed_version(self):
        findings = self.runner._parse_grype_result(GRYPE_OUTPUT)
        high = [f for f in findings if f.cve_id == "CVE-2023-0001"]
        assert high[0].fixed_version == "1.1.1u-r0"

    def test_not_fixed_state_returns_none(self):
        findings = self.runner._parse_grype_result(GRYPE_OUTPUT)
        critical = [f for f in findings if f.cve_id == "CVE-2023-0002"]
        assert len(critical) == 1
        assert critical[0].fixed_version is None

    def test_empty_matches_returns_empty_list(self):
        assert self.runner._parse_grype_result({}) == []
        assert self.runner._parse_grype_result({"matches": []}) == []

    def test_match_missing_cve_id_is_skipped(self):
        data = {
            "matches": [
                {
                    "vulnerability": {"id": "", "severity": "HIGH", "fix": {}},
                    "artifact": {"name": "libfoo", "version": "1.0"},
                }
            ]
        }
        assert self.runner._parse_grype_result(data) == []

    def test_unknown_severity_is_included(self):
        data = {
            "matches": [
                {
                    "vulnerability": {"id": "CVE-2023-X", "severity": "UNKNOWN", "fix": {}},
                    "artifact": {"name": "libfoo", "version": "1.0"},
                }
            ]
        }
        findings = self.runner._parse_grype_result(data)
        assert len(findings) == 1
        assert findings[0].severity == "UNKNOWN"

    def test_invalid_severity_is_skipped(self):
        data = {
            "matches": [
                {
                    "vulnerability": {"id": "CVE-2023-Y", "severity": "BOGUS", "fix": {}},
                    "artifact": {"name": "libfoo", "version": "1.0"},
                }
            ]
        }
        assert self.runner._parse_grype_result(data) == []

    def test_fix_state_fixed_but_no_versions_returns_none(self):
        data = {
            "matches": [
                {
                    "vulnerability": {
                        "id": "CVE-2023-Z",
                        "severity": "LOW",
                        "fix": {"state": "fixed", "versions": []},
                    },
                    "artifact": {"name": "pkg", "version": "1.0"},
                }
            ]
        }
        findings = self.runner._parse_grype_result(data)
        assert findings[0].fixed_version is None

    def test_description_is_passed_through(self):
        findings = self.runner._parse_grype_result(GRYPE_OUTPUT)
        high = [f for f in findings if f.cve_id == "CVE-2023-0001"]
        assert high[0].description == "OpenSSL vulnerability"

    def test_fix_state_fixed_with_missing_versions_key_returns_none(self):
        data = {
            "matches": [
                {
                    "vulnerability": {
                        "id": "CVE-2023-B",
                        "severity": "HIGH",
                        "fix": {"state": "fixed"},  # no "versions" key at all
                    },
                    "artifact": {"name": "pkg", "version": "1.0"},
                }
            ]
        }
        findings = self.runner._parse_grype_result(data)
        assert findings[0].fixed_version is None

    def test_severity_is_uppercased(self):
        data = {
            "matches": [
                {
                    "vulnerability": {"id": "CVE-2023-A", "severity": "high", "fix": {}},
                    "artifact": {"name": "pkg", "version": "1.0"},
                }
            ]
        }
        findings = self.runner._parse_grype_result(data)
        assert findings[0].severity == "HIGH"


class TestGrypeRunnerRun:
    @pytest.mark.asyncio
    async def test_run_raises_timeout_error(self):
        runner = GrypeRunner(make_config(timeout_seconds=30))
        mock_result = MagicMock(timed_out=True, returncode=0, stdout="", stderr="")
        with patch("plugins.container_scanner.scanners.grype_runner.run_command", new=AsyncMock(return_value=mock_result)):
            with pytest.raises(TimeoutError, match="timed out"):
                await runner.run("ghcr.io/org/app:v1", {})

    @pytest.mark.asyncio
    async def test_run_raises_runtime_error_on_nonzero_exit(self):
        runner = GrypeRunner(make_config())
        mock_result = MagicMock(timed_out=False, returncode=1, stdout="", stderr="grype: image not found")
        with patch("plugins.container_scanner.scanners.grype_runner.run_command", new=AsyncMock(return_value=mock_result)):
            with pytest.raises(RuntimeError, match="Grype exited 1"):
                await runner.run("ghcr.io/org/app:v1", {})

    @pytest.mark.asyncio
    async def test_run_returns_parsed_vulnerabilities(self):
        runner = GrypeRunner(make_config())
        mock_result = MagicMock(timed_out=False, returncode=0, stdout=json.dumps(GRYPE_OUTPUT), stderr="")
        with patch("plugins.container_scanner.scanners.grype_runner.run_command", new=AsyncMock(return_value=mock_result)):
            vulns = await runner.run("ghcr.io/org/app:v1", {})
        assert len(vulns) == 2

    @pytest.mark.asyncio
    async def test_run_passes_auth_env_to_command(self):
        runner = GrypeRunner(make_config())
        mock_result = MagicMock(timed_out=False, returncode=0, stdout=json.dumps({}), stderr="")
        auth_env = {"GRYPE_REGISTRY_AUTH_TOKEN": "mytoken"}
        with patch("plugins.container_scanner.scanners.grype_runner.run_command", new=AsyncMock(return_value=mock_result)) as mock_cmd:
            await runner.run("ghcr.io/org/app:v1", auth_env)
            called_env = mock_cmd.call_args.kwargs["env"]
            assert called_env["GRYPE_REGISTRY_AUTH_TOKEN"] == "mytoken"

    @pytest.mark.asyncio
    async def test_run_handles_empty_stdout(self):
        runner = GrypeRunner(make_config())
        mock_result = MagicMock(timed_out=False, returncode=0, stdout="", stderr="")
        with patch("plugins.container_scanner.scanners.grype_runner.run_command", new=AsyncMock(return_value=mock_result)):
            vulns = await runner.run("ghcr.io/org/app:v1", {})
        assert vulns == []
