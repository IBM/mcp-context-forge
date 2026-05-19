#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_container_scanner/test_hook_pipeline.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Agnetha

Integration tests for the ContainerScannerPlugin hook pipeline.

Coverage:
  TestScanPipeline    — plugin.scan() end-to-end with mocked scanner CLI
  TestHookHandlers    — server_pre_register / runtime_pre_deploy called directly
                        with ContainerScannerPayload → ContainerScannerResult
  TestScanResultViaAPI — scan results saved to repo are visible via GET /scans
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

# Third-Party
import pytest

# First-Party — framework models required by hook method signatures
from mcpgateway.plugins.framework.models import GlobalContext, PluginContext

# Local — plugin-only imports
from plugins.container_scanner.auth.auth_resolver import AuthResolver
from plugins.container_scanner.cache.cache_manager import CacheManager
from plugins.container_scanner.config import ScannerConfig
from plugins.container_scanner.container_scanner import (
    ContainerScannerPayload,
    ContainerScannerPlugin,
)
from plugins.container_scanner.policy.policy_evaluator import PolicyEvaluator
from plugins.container_scanner.scanners.trivy_runner import TrivyRunner
from plugins.container_scanner.types import Vulnerability


IMAGE_REF = "ghcr.io/org/app:v1"
DIGEST = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_plugin(repo, **config_kwargs) -> ContainerScannerPlugin:
    """Assemble a ContainerScannerPlugin from its internal components.

    Bypasses __init__ (which requires mcpgateway PluginConfig) so that tests
    depend only on the plugin package itself.
    """
    defaults = dict(scanner="trivy", mode="enforce", cache_enabled=False)
    defaults.update(config_kwargs)
    cfg = ScannerConfig(**defaults)

    plugin = object.__new__(ContainerScannerPlugin)
    plugin._scanner_config = cfg
    plugin._cache = CacheManager(ttl_hours=cfg.cache_ttl_hours, enabled=cfg.cache_enabled)
    plugin._auth = AuthResolver(cfg)
    plugin._runner = TrivyRunner(cfg)
    plugin._policy = PolicyEvaluator()
    plugin._repo = repo
    # Wire up the hook payload/result maps that __init__ would normally set
    plugin._hook_payloads = {
        "server_pre_register": ContainerScannerPayload,
        "runtime_pre_deploy": ContainerScannerPayload,
    }
    plugin._hook_results = {
        "server_pre_register": ContainerScannerPayload,
        "runtime_pre_deploy": ContainerScannerPayload,
    }
    return plugin


def _make_vuln(**kwargs) -> Vulnerability:
    defaults = dict(
        scanner="trivy",
        cve_id="CVE-2023-0001",
        severity="CRITICAL",
        package_name="libfoo",
        installed_version="1.0.0",
        fixed_version="2.0.0",
    )
    defaults.update(kwargs)
    return Vulnerability(**defaults)


def _make_payload(image_ref: str = IMAGE_REF, image_digest: str | None = DIGEST) -> ContainerScannerPayload:
    return ContainerScannerPayload(
        assessment_id=str(uuid.uuid4()),
        image_ref=image_ref,
        image_digest=image_digest,
    )


def _make_context() -> PluginContext:
    return PluginContext(global_context=GlobalContext(request_id=str(uuid.uuid4())))


# ---------------------------------------------------------------------------
# TestScanPipeline — tests plugin.scan() directly
# ---------------------------------------------------------------------------


class TestScanPipeline:
    @pytest.mark.asyncio
    async def test_clean_image_is_allowed(self, clean_repo):
        plugin = _make_plugin(clean_repo)
        with patch.object(TrivyRunner, "run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = []
            result = await plugin.scan(IMAGE_REF, DIGEST)

        assert result.blocked is False
        assert result.scan_error is None

    @pytest.mark.asyncio
    async def test_critical_vuln_blocks_above_threshold(self, clean_repo):
        plugin = _make_plugin(clean_repo, severity_threshold="HIGH")
        with patch.object(TrivyRunner, "run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = [_make_vuln(severity="CRITICAL")]
            result = await plugin.scan(IMAGE_REF, DIGEST)

        assert result.blocked is True
        assert result.reason is not None

    @pytest.mark.asyncio
    async def test_low_vuln_allowed_above_threshold(self, clean_repo):
        plugin = _make_plugin(clean_repo, severity_threshold="CRITICAL")
        with patch.object(TrivyRunner, "run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = [_make_vuln(severity="LOW")]
            result = await plugin.scan(IMAGE_REF, DIGEST)

        assert result.blocked is False

    @pytest.mark.asyncio
    async def test_result_stored_in_repo(self, clean_repo):
        plugin = _make_plugin(clean_repo)
        with patch.object(TrivyRunner, "run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = []
            await plugin.scan(IMAGE_REF, DIGEST)

        assert clean_repo.get(DIGEST) is not None
        assert clean_repo.get(DIGEST).image_ref == IMAGE_REF

    @pytest.mark.asyncio
    async def test_disabled_mode_skips_runner(self, clean_repo):
        plugin = _make_plugin(clean_repo, mode="disabled")
        with patch.object(TrivyRunner, "run", new_callable=AsyncMock) as mock_run:
            await plugin.scan(IMAGE_REF, DIGEST)
            mock_run.assert_not_called()

        assert len(clean_repo) == 0

    @pytest.mark.asyncio
    async def test_fail_closed_on_scanner_error(self, clean_repo):
        plugin = _make_plugin(clean_repo, on_scan_error="fail_closed")
        with patch.object(TrivyRunner, "run", new_callable=AsyncMock) as mock_run:
            mock_run.side_effect = RuntimeError("trivy not found")
            result = await plugin.scan(IMAGE_REF, DIGEST)

        assert result.blocked is True
        assert result.scan_error is not None

    @pytest.mark.asyncio
    async def test_fail_open_on_scanner_error(self, clean_repo):
        plugin = _make_plugin(clean_repo, on_scan_error="fail_open")
        with patch.object(TrivyRunner, "run", new_callable=AsyncMock) as mock_run:
            mock_run.side_effect = RuntimeError("trivy not found")
            result = await plugin.scan(IMAGE_REF, DIGEST)

        assert result.blocked is False
        assert result.scan_error is not None

    @pytest.mark.asyncio
    async def test_summary_counts_match_vulns(self, clean_repo):
        plugin = _make_plugin(clean_repo, severity_threshold="LOW")
        vulns = [
            _make_vuln(severity="CRITICAL"),
            _make_vuln(severity="HIGH", cve_id="CVE-2023-0002"),
            _make_vuln(severity="MEDIUM", cve_id="CVE-2023-0003"),
            _make_vuln(severity="LOW", cve_id="CVE-2023-0004"),
        ]
        with patch.object(TrivyRunner, "run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = vulns
            result = await plugin.scan(IMAGE_REF, DIGEST)

        assert result.summary.critical_count == 1
        assert result.summary.high_count == 1
        assert result.summary.medium_count == 1
        assert result.summary.low_count == 1


# ---------------------------------------------------------------------------
# TestHookHandlers — tests server_pre_register and runtime_pre_deploy directly
# ---------------------------------------------------------------------------


class TestHookHandlers:
    """Tests the hook entry-points using ContainerScannerPayload directly.

    These methods are called by the framework after JSON→Pydantic deserialization.
    Now that ContainerScannerPlugin.__init__ passes hook_payloads to the base class,
    the full ExternalPluginServer.invoke_hook() JSON path is also functional.
    """

    @pytest.mark.asyncio
    async def test_server_pre_register_allows_clean_image(self, clean_repo):
        plugin = _make_plugin(clean_repo)
        with patch.object(TrivyRunner, "run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = []
            result = await plugin.server_pre_register(_make_payload(), _make_context())

        assert result.continue_processing is True
        assert result.violation is None

    @pytest.mark.asyncio
    async def test_server_pre_register_blocks_critical_vuln(self, clean_repo):
        plugin = _make_plugin(clean_repo, severity_threshold="HIGH")
        with patch.object(TrivyRunner, "run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = [_make_vuln(severity="CRITICAL")]
            result = await plugin.server_pre_register(_make_payload(), _make_context())

        assert result.continue_processing is False
        assert result.violation is not None
        assert result.violation.code == "CVE_POLICY_VIOLATION"

    @pytest.mark.asyncio
    async def test_runtime_pre_deploy_allows_clean_image(self, clean_repo):
        plugin = _make_plugin(clean_repo)
        with patch.object(TrivyRunner, "run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = []
            result = await plugin.runtime_pre_deploy(_make_payload(), _make_context())

        assert result.continue_processing is True
        assert result.violation is None

    @pytest.mark.asyncio
    async def test_runtime_pre_deploy_blocks_critical_vuln(self, clean_repo):
        plugin = _make_plugin(clean_repo, severity_threshold="HIGH")
        with patch.object(TrivyRunner, "run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = [_make_vuln(severity="CRITICAL")]
            result = await plugin.runtime_pre_deploy(_make_payload(), _make_context())

        assert result.continue_processing is False
        assert result.violation is not None
        assert result.violation.code == "CVE_POLICY_VIOLATION"

    @pytest.mark.asyncio
    async def test_hook_clean_image_returns_no_violation(self, clean_repo):
        """A clean image produces a result with no violation and processing continues."""
        plugin = _make_plugin(clean_repo)
        with patch.object(TrivyRunner, "run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = []
            result = await plugin.server_pre_register(_make_payload(), _make_context())

        assert result.continue_processing is True
        assert result.violation is None
        assert result.metadata == {}

    @pytest.mark.asyncio
    async def test_hooks_are_consistent_for_same_image(self, clean_repo):
        """server_pre_register and runtime_pre_deploy return the same block decision."""
        plugin = _make_plugin(clean_repo, severity_threshold="HIGH")
        vulns = [_make_vuln(severity="CRITICAL")]
        payload = _make_payload()

        with patch.object(TrivyRunner, "run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = vulns
            reg_result = await plugin.server_pre_register(payload, _make_context())

        with patch.object(TrivyRunner, "run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = vulns
            dep_result = await plugin.runtime_pre_deploy(payload, _make_context())

        assert reg_result.continue_processing == dep_result.continue_processing

    @pytest.mark.asyncio
    async def test_disabled_mode_hook_always_allows(self, clean_repo):
        plugin = _make_plugin(clean_repo, mode="disabled")
        with patch.object(TrivyRunner, "run", new_callable=AsyncMock) as mock_run:
            result = await plugin.server_pre_register(_make_payload(), _make_context())
            mock_run.assert_not_called()

        assert result.continue_processing is True

    @pytest.mark.asyncio
    async def test_hook_violation_has_non_empty_reason(self, clean_repo):
        plugin = _make_plugin(clean_repo, severity_threshold="LOW")
        with patch.object(TrivyRunner, "run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = [_make_vuln(severity="CRITICAL")]
            result = await plugin.server_pre_register(_make_payload(), _make_context())

        assert result.violation is not None
        assert result.violation.reason != ""
        assert result.violation.description != ""


# ---------------------------------------------------------------------------
# TestScanResultViaAPI — results saved by scan() are visible via GET /scans
# ---------------------------------------------------------------------------


class TestScanResultViaAPI:
    @pytest.mark.asyncio
    async def test_scan_result_appears_in_scans_endpoint(self, client, clean_repo):
        plugin = _make_plugin(clean_repo)
        with patch.object(TrivyRunner, "run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = []
            await plugin.scan(IMAGE_REF, None)

        response = client.get("/scans")
        assert response.status_code == 200
        results = response.json()
        assert len(results) == 1
        assert results[0]["image_ref"] == IMAGE_REF

    @pytest.mark.asyncio
    async def test_blocked_result_visible_via_scans_endpoint(self, client, clean_repo):
        plugin = _make_plugin(clean_repo, severity_threshold="HIGH")
        with patch.object(TrivyRunner, "run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = [_make_vuln(severity="CRITICAL")]
            await plugin.scan(IMAGE_REF, None)

        response = client.get("/scans")
        assert response.status_code == 200
        results = response.json()
        assert any(r["image_ref"] == IMAGE_REF and r["blocked"] is True for r in results)

    @pytest.mark.asyncio
    async def test_multiple_scans_ordered_most_recent_first(self, client, clean_repo):
        plugin = _make_plugin(clean_repo)
        with patch.object(TrivyRunner, "run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = []
            await plugin.scan("ghcr.io/org/app:v1", None)
            await plugin.scan("ghcr.io/org/app:v2", None)

        response = client.get("/scans")
        results = response.json()
        assert results[0]["image_ref"] == "ghcr.io/org/app:v2"
        assert results[1]["image_ref"] == "ghcr.io/org/app:v1"
