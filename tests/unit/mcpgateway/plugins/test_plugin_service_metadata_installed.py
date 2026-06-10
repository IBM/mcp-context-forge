# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/test_plugin_service_metadata_installed.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for installed plugin metadata through the real manager path.
"""

# Standard
from importlib import metadata
from importlib.metadata import PackageNotFoundError
import sys

# Third-Party
import pytest

# First-Party
from mcpgateway.plugins.gateway_plugin_manager import TenantPluginManagerFactory
from mcpgateway.services.plugin_service import PluginService


def _rate_limiter_package_metadata():
    try:
        package_metadata = metadata.metadata("cpex-rate-limiter")
    except PackageNotFoundError:
        pytest.skip("cpex-rate-limiter plugin not installed")

    return (
        metadata.version("cpex-rate-limiter"),
        package_metadata.get("Author") or package_metadata.get("Maintainer") or package_metadata.get("Author-email"),
        package_metadata.get("Summary"),
    )


def _write_config(tmp_path, mode: str):
    config_file = tmp_path / "plugins.yaml"
    config_file.write_text(
        f"""
plugins:
  - name: "RateLimiterPlugin"
    kind: "cpex_rate_limiter.RateLimiterPlugin"
    hooks: ["prompt_pre_fetch"]
    tags: ["limits"]
    mode: "{mode}"
    priority: 50
    config:
      by_user: "2/s"
      by_tenant:
      by_tool: {{}}
""",
        encoding="utf-8",
    )
    return config_file


@pytest.mark.asyncio
async def test_installed_plugin_metadata_overrides_stale_config_for_disabled_plugin(tmp_path, monkeypatch):
    """Verify disabled installed plugins get package metadata without importing plugin modules."""
    monkeypatch.delitem(sys.modules, "cpex_rate_limiter", raising=False)
    expected_version, expected_author, expected_summary = _rate_limiter_package_metadata()
    factory = TenantPluginManagerFactory(str(_write_config(tmp_path, "disabled")))

    manager = await factory.get_manager()
    try:
        plugin = PluginService(manager).get_all_plugins()[0]
    finally:
        await factory.shutdown()

    assert plugin["version"] == expected_version
    assert plugin["author"] == expected_author
    assert plugin["description"] == expected_summary
    assert plugin["hooks"] == ["prompt_pre_fetch"]
    assert plugin["tags"] == ["limits"]
    assert plugin["priority"] == 50
    assert plugin["config_summary"]["by_user"] == "2/s"
    assert "cpex_rate_limiter" not in sys.modules


@pytest.mark.asyncio
async def test_installed_plugin_metadata_available_for_registered_plugin(tmp_path):
    """Verify registered plugin display metadata survives real manager initialization."""
    expected_version, expected_author, expected_summary = _rate_limiter_package_metadata()
    factory = TenantPluginManagerFactory(str(_write_config(tmp_path, "sequential")))

    manager = await factory.get_manager()
    try:
        plugin = PluginService(manager).get_plugin_by_name("RateLimiterPlugin")
    finally:
        await factory.shutdown()

    assert plugin["version"] == expected_version
    assert plugin["author"] == expected_author
    assert plugin["description"] == expected_summary
    assert plugin["hooks"] == ["prompt_pre_fetch"]
    assert plugin["tags"] == ["limits"]
    assert plugin["priority"] == 50
