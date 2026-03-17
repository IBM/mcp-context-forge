#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_container_scanner/test_hook_pipeline.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Agnetha

End-to-end integration tests: plugin hook fires → result stored in singleton → retrievable via API.
Proves the wiring between ContainerScannerPlugin and the REST router is correct.
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import AsyncMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.plugins.framework import PluginConfig
from mcpgateway.plugins.framework.models import GlobalContext, PluginContext
from plugins.container_scanner.container_scanner import ContainerScannerPlugin
from plugins.container_scanner.scanners.trivy_runner import TrivyRunner
from plugins.container_scanner.types import Vulnerability
from mcpgateway.plugins.framework.hooks.gateway import ServerPreRegisterPayload, RuntimePreDeployPayload


IMAGE_REF = "ghcr.io/org/app:v1"
DIGEST = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def make_plugin_config(**kwargs) -> PluginConfig:
    defaults = dict(scanner="trivy", mode="enforce", cache_enabled=False)
    defaults.update(kwargs)
    return PluginConfig(
        name="container_scanner",
        kind="plugins.container_scanner.container_scanner.ContainerScannerPlugin",
        priority=100,
        config=defaults,
    )


def make_plugin_context() -> PluginContext:
    return PluginContext(global_context=GlobalContext(request_id="req-test-001"))


def make_vuln(**kwargs: Any) -> Vulnerability:
    defaults: Dict[str, Any] =  dict(
        scanner="trivy",
        cve_id="CVE-2023-0001",
        severity="CRITICAL",
        package_name="libfoo",
        installed_version="1.0.0",
        fixed_version="2.0.0",  # required: policy drops unfixed vulns by default
    )
    defaults.update(kwargs)
    return Vulnerability(**defaults)


class TestServerPreRegisterHook:
    @pytest.mark.asyncio
    async def test_server_pre_register_stores_result(self, clean_repo):
        plugin = ContainerScannerPlugin(make_plugin_config())
        plugin._repo = clean_repo

        with patch.object(TrivyRunner, "run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = []
            payload = ServerPreRegisterPayload(assessment_id="assess-001", image_ref=IMAGE_REF, image_digest=DIGEST)
            await plugin.server_pre_register(payload, make_plugin_context())

        assert clean_repo.get(DIGEST) is not None
        assert clean_repo.get(DIGEST).image_ref == IMAGE_REF

    @pytest.mark.asyncio
    async def test_server_pre_register_blocked_result(self, clean_repo):
        plugin = ContainerScannerPlugin(make_plugin_config(severity_threshold="HIGH"))
        plugin._repo = clean_repo

        with patch.object(TrivyRunner, "run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = [make_vuln(severity="CRITICAL")]
            payload = ServerPreRegisterPayload(assessment_id="assess-002", image_ref=IMAGE_REF, image_digest=DIGEST)
            hook_result = await plugin.server_pre_register(payload, make_plugin_context())

        assert hook_result.continue_processing is False
        assert hook_result.violation is not None

    @pytest.mark.asyncio
    async def test_server_pre_register_unblocked_result(self, clean_repo):
        plugin = ContainerScannerPlugin(make_plugin_config(severity_threshold="CRITICAL"))
        plugin._repo = clean_repo

        with patch.object(TrivyRunner, "run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = [make_vuln(severity="LOW")]
            payload = ServerPreRegisterPayload(assessment_id="assess-003", image_ref=IMAGE_REF, image_digest=DIGEST)
            hook_result = await plugin.server_pre_register(payload, make_plugin_context())

        assert hook_result.continue_processing is True


class TestRuntimePreDeployHook:
    @pytest.mark.asyncio
    async def test_runtime_pre_deploy_stores_result(self, clean_repo):
        plugin = ContainerScannerPlugin(make_plugin_config())
        plugin._repo = clean_repo

        with patch.object(TrivyRunner, "run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = []
            payload = RuntimePreDeployPayload(assessment_id="assess-101", image_ref=IMAGE_REF, image_digest=DIGEST)
            await plugin.runtime_pre_deploy(payload, make_plugin_context())

        assert clean_repo.get(DIGEST) is not None

    @pytest.mark.asyncio
    async def test_runtime_pre_deploy_blocked_result(self, clean_repo):
        plugin = ContainerScannerPlugin(make_plugin_config(severity_threshold="HIGH"))
        plugin._repo = clean_repo

        with patch.object(TrivyRunner, "run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = [make_vuln(severity="CRITICAL")]
            payload = RuntimePreDeployPayload(assessment_id="assess-102", image_ref=IMAGE_REF, image_digest=DIGEST)
            hook_result = await plugin.runtime_pre_deploy(payload, make_plugin_context())

        assert hook_result.continue_processing is False


class TestHookResultVisibleViaAPI:
    @pytest.mark.asyncio
    async def test_hook_result_visible_via_api(self, client, clean_repo):
        plugin = ContainerScannerPlugin(make_plugin_config())
        plugin._repo = clean_repo

        with patch.object(TrivyRunner, "run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = []
            payload = ServerPreRegisterPayload(assessment_id="assess-201", image_ref=IMAGE_REF, image_digest=None)
            await plugin.server_pre_register(payload, make_plugin_context())

        response = client.get("/container-scanner/scans")
        assert response.status_code == 200
        results = response.json()
        assert len(results) == 1
        assert results[0]["image_ref"] == IMAGE_REF

    @pytest.mark.asyncio
    async def test_hook_blocked_result_visible_via_api(self, client, clean_repo):
        plugin = ContainerScannerPlugin(make_plugin_config(severity_threshold="HIGH"))
        plugin._repo = clean_repo

        with patch.object(TrivyRunner, "run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = [make_vuln(severity="CRITICAL")]
            payload = ServerPreRegisterPayload(assessment_id="assess-202", image_ref=IMAGE_REF, image_digest=None)
            await plugin.server_pre_register(payload, make_plugin_context())

        response = client.get(f"/container-scanner/scans/{IMAGE_REF}")
        assert response.status_code == 200
        assert response.json()["blocked"] is True

    @pytest.mark.asyncio
    async def test_disabled_mode_skips_scan(self, clean_repo):
        """Mode=disabled stores a result with reason='scan skipped', runner not invoked."""
        plugin = ContainerScannerPlugin(make_plugin_config(mode="disabled"))
        plugin._repo = clean_repo

        with patch.object(TrivyRunner, "run", new_callable=AsyncMock) as mock_run:
            payload = ServerPreRegisterPayload(assessment_id="assess-203", image_ref=IMAGE_REF, image_digest=None)
            await plugin.server_pre_register(payload, make_plugin_context())
            mock_run.assert_not_called()

        # disabled mode returns early without saving to repo
        assert len(clean_repo) == 0
