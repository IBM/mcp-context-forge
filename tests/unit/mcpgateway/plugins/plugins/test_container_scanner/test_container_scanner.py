#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/unit/plugins/test_container_scanner/test_container_scanner.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Agnetha

Unit tests for ContainerScannerPlugin.scan() pipeline.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from mcpgateway.plugins.framework import PluginConfig
from plugins.container_scanner.container_scanner import ContainerScannerPlugin
from plugins.container_scanner.types import Vulnerability

DIGEST_V1 = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
DIGEST_V2 = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
DIGEST_V3 = "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
DIGEST_UNKNOWN = "sha256:0000000000000000000000000000000000000000000000000000000000000000"

def make_plugin_config(**scanner_config_kwargs) -> PluginConfig:
    """Build a minimal PluginConfig with scanner config overrides."""
    defaults = dict(scanner="trivy", mode="enforce", cache_enabled=False)
    defaults.update(scanner_config_kwargs)
    return PluginConfig(
        name="container_scanner",
        kind="plugins.container_scanner.container_scanner.ContainerScannerPlugin",
        priority=100,
        config=defaults,
    )


def make_vuln(**kwargs) -> Vulnerability:
    defaults = dict(
        scanner="trivy",
        cve_id="CVE-2023-0001",
        severity="HIGH",
        package_name="libfoo",
        installed_version="1.0.0",
        fixed_version="1.0.1",
    )
    defaults.update(kwargs)
    return Vulnerability(**defaults)


class TestScanDisabledMode:
    @pytest.mark.asyncio
    async def test_scan_disabled_mode_returns_unblocked(self):
        plugin = ContainerScannerPlugin(make_plugin_config(mode="disabled"))
        result = await plugin.scan("ghcr.io/org/app:v1", DIGEST_V1)
        assert result.blocked is False
        assert result.image_ref == "ghcr.io/org/app:v1"

    @pytest.mark.asyncio
    async def test_scan_disabled_skips_runner(self):
        plugin = ContainerScannerPlugin(make_plugin_config(mode="disabled"))
        plugin._runner.run = AsyncMock()
        await plugin.scan("ghcr.io/org/app:v1", DIGEST_V1)
        plugin._runner.run.assert_not_called()


class TestScanCacheHit:
    @pytest.mark.asyncio
    async def test_cache_hit_skips_runner(self):
        plugin = ContainerScannerPlugin(make_plugin_config(cache_enabled=True))
        cached_vulns = [make_vuln(severity="LOW")]
        plugin._cache.lookup = MagicMock(return_value=cached_vulns)
        plugin._runner.run = AsyncMock()
        await plugin.scan("ghcr.io/org/app:v1", DIGEST_V1)
        plugin._runner.run.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_hit_re_evaluates_policy(self):
        """Cache returns vulns but policy is always re-evaluated (not cached)."""
        plugin = ContainerScannerPlugin(make_plugin_config(cache_enabled=True, severity_threshold="CRITICAL"))
        # Only a HIGH vuln cached — CRITICAL threshold means no block
        cached_vulns = [make_vuln(severity="HIGH")]
        plugin._cache.lookup = MagicMock(return_value=cached_vulns)
        result = await plugin.scan("ghcr.io/org/app:v1", DIGEST_V1)
        assert result.blocked is False


class TestScanCacheMiss:
    @pytest.mark.asyncio
    async def test_scan_cache_miss_runs_scanner(self):
        plugin = ContainerScannerPlugin(make_plugin_config(cache_enabled=True))
        plugin._cache.lookup = MagicMock(return_value=None)
        plugin._runner.run = AsyncMock(return_value=[])
        plugin._cache.store = MagicMock()
        plugin._repo.save = MagicMock()
        await plugin.scan("ghcr.io/org/app:v1", DIGEST_V1)
        plugin._runner.run.assert_called_once()

    @pytest.mark.asyncio
    async def test_scan_stores_result_after_scan(self):
        plugin = ContainerScannerPlugin(make_plugin_config(cache_enabled=True))
        plugin._cache.lookup = MagicMock(return_value=None)
        plugin._runner.run = AsyncMock(return_value=[])
        plugin._cache.store = MagicMock()
        plugin._repo.save = MagicMock()
        await plugin.scan("ghcr.io/org/app:v1", DIGEST_V1)
        plugin._cache.store.assert_called_once()
        plugin._repo.save.assert_called_once()





class TestScanErrorHandling:
    @pytest.mark.asyncio
    async def test_fail_closed_blocks_on_scanner_error(self):
        plugin = ContainerScannerPlugin(make_plugin_config(on_scan_error="fail_closed"))
        plugin._runner.run = AsyncMock(side_effect=RuntimeError("trivy not found"))
        plugin._cache.lookup = MagicMock(return_value=None)
        result = await plugin.scan("ghcr.io/org/app:v1", DIGEST_V1)
        assert result.blocked is True
        assert result.scan_error is not None

    @pytest.mark.asyncio
    async def test_fail_open_allows_on_scanner_error(self):
        plugin = ContainerScannerPlugin(make_plugin_config(on_scan_error="fail_open"))
        plugin._runner.run = AsyncMock(side_effect=RuntimeError("trivy not found"))
        plugin._cache.lookup = MagicMock(return_value=None)
        result = await plugin.scan("ghcr.io/org/app:v1", DIGEST_V1)
        assert result.blocked is False
        assert result.scan_error is not None

    @pytest.mark.asyncio
    async def test_scan_error_is_recorded_in_result(self):
        plugin = ContainerScannerPlugin(make_plugin_config(on_scan_error="fail_open"))
        plugin._runner.run = AsyncMock(side_effect=RuntimeError("connection timeout"))
        plugin._cache.lookup = MagicMock(return_value=None)
        result = await plugin.scan("ghcr.io/org/app:v1", DIGEST_V1)
        assert "connection timeout" in result.scan_error


class TestScanResultStructure:
    @pytest.mark.asyncio
    async def test_result_summary_counts_severities(self):
        plugin = ContainerScannerPlugin(make_plugin_config(mode="audit"))
        vulns = [
            make_vuln(severity="CRITICAL", cve_id="CVE-1"),
            make_vuln(severity="HIGH", cve_id="CVE-2"),
            make_vuln(severity="HIGH", cve_id="CVE-3"),
            make_vuln(severity="MEDIUM", cve_id="CVE-4"),
        ]
        plugin._runner.run = AsyncMock(return_value=vulns)
        plugin._cache.lookup = MagicMock(return_value=None)
        plugin._cache.store = MagicMock()
        plugin._repo.save = MagicMock()
        result = await plugin.scan("ghcr.io/org/app:v1", DIGEST_V1)
        assert result.summary.critical_count == 1
        assert result.summary.high_count == 2
        assert result.summary.medium_count == 1
        assert result.summary.low_count == 0

    @pytest.mark.asyncio
    async def test_result_image_ref_matches_input(self):
        plugin = ContainerScannerPlugin(make_plugin_config(mode="audit"))
        plugin._runner.run = AsyncMock(return_value=[])
        plugin._cache.lookup = MagicMock(return_value=None)
        plugin._cache.store = MagicMock()
        plugin._repo.save = MagicMock()
        result = await plugin.scan("ghcr.io/org/app:latest", DIGEST_V1)
        assert result.image_ref == "ghcr.io/org/app:latest"

    @pytest.mark.asyncio
    async def test_result_duration_ms_is_non_negative(self):
        plugin = ContainerScannerPlugin(make_plugin_config(mode="audit"))
        plugin._runner.run = AsyncMock(return_value=[])
        plugin._cache.lookup = MagicMock(return_value=None)
        plugin._cache.store = MagicMock()
        plugin._repo.save = MagicMock()
        result = await plugin.scan("ghcr.io/org/app:v1", DIGEST_V1)
        assert result.duration_ms >= 0
