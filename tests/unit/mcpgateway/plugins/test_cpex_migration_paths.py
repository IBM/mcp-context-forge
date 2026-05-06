# -*- coding: utf-8 -*-
"""Regression tests for paths migrated from the in-repo plugin framework."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]


def test_runtime_plugin_configs_do_not_reference_deleted_framework_package() -> None:
    """Runtime-facing plugin configs must not reference removed framework files."""
    checked_paths = [
        Path("Makefile"),
        Path("plugins/external/config-stdio.yaml"),
        Path("plugins/external/cedar/run-server.sh"),
        Path("plugins/external/clamav_server/run.sh"),
        Path("plugins/external/llmguard/run-server.sh"),
        Path("plugins/external/opa/run-server.sh"),
        Path("plugins/resources/server/config-stdio.yaml"),
        Path("tests/integration/test_rate_limiter_redis_url_from_yaml.py"),
        *Path("tests/unit/mcpgateway/plugins/fixtures/configs").glob("*stdio*.yaml"),
    ]

    stale_needles = (
        "mcpgateway.plugins.framework",
        "mcpgateway/plugins/framework",
        "plugins.framework.mcp.server",
    )

    offenders = []
    for relative_path in checked_paths:
        path = REPO_ROOT / relative_path
        text = path.read_text(encoding="utf-8")
        for needle in stale_needles:
            if needle in text:
                offenders.append(f"{relative_path}: {needle}")

    assert offenders == []


def test_external_plugin_runtime_import_resolves_from_cpex() -> None:
    """External MCP runtime must be importable from the packaged CPEX path."""
    # First-Party
    from cpex.framework.external.mcp.server import runtime

    assert runtime.__file__
