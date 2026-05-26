# -*- coding: utf-8 -*-
"""Location: ./tests/unit/charts/test_deployment_mcpgateway.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Helm chart render tests — gateway Deployment env wiring.

Pins the migration-Job / gateway-Deployment contract:

    "When the chart enables the migration Job, the gateway Deployment must
     set MCPGATEWAY_SKIP_MIGRATIONS=true so app pods don't redundantly
     bootstrap the schema. When the Job is disabled, the gateway must
     either omit the env var or set it to false so pods bootstrap
     themselves via the in-process fast-path."

Tests are skipped automatically when ``helm`` is not on PATH; they don't
require a Kubernetes cluster — only chart rendering.
"""

# Standard
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
from typing import Any

# Third-Party
import pytest
import yaml

CHART_DIR = Path(__file__).resolve().parents[3] / "charts" / "mcp-stack"
GATEWAY_DEPLOYMENT_NAME_SUFFIX = "mcp-stack-mcpgateway"

# Helm refuses to render without these, so populate with throwaway values.
# Values must be strings — the chart's schema is strict about types.
REQUIRED_SECRETS = {
    "mcpContextForge.secret.JWT_SECRET_KEY": "x" * 32,
    "mcpContextForge.secret.AUTH_ENCRYPTION_SECRET": "y" * 32,
    "mcpContextForge.secret.BASIC_AUTH_PASSWORD": "throwaway-pass-1234567",  # pragma: allowlist secret
    "mcpContextForge.secret.PLATFORM_ADMIN_PASSWORD": "throwaway-pass-1234567",  # pragma: allowlist secret
    "mcpContextForge.secret.REQUIRE_STRONG_SECRETS": '"false"',  # quoted: schema demands string
}

pytestmark = pytest.mark.skipif(
    shutil.which("helm") is None,
    reason="helm not installed; chart-render tests cannot run",
)


def _helm_template(*set_overrides: str) -> list[dict[str, Any]]:
    """Render the chart with the given --set overrides, return parsed manifests."""
    sets: list[str] = []
    for k, v in REQUIRED_SECRETS.items():
        sets.extend(["--set", f"{k}={v}"])
    for override in set_overrides:
        sets.extend(["--set", override])

    result = subprocess.run(
        ["helm", "template", "release-test", str(CHART_DIR), *sets],
        check=True,
        capture_output=True,
        text=True,
    )
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def _gateway_deployment(manifests: list[dict[str, Any]]) -> dict[str, Any]:
    for m in manifests:
        if m.get("kind") == "Deployment" and m.get("metadata", {}).get("name", "").endswith(GATEWAY_DEPLOYMENT_NAME_SUFFIX):
            return m
    raise AssertionError("gateway Deployment not found in rendered chart — selector may have drifted")


def _gateway_env(manifests: list[dict[str, Any]]) -> dict[str, str]:
    """Return the gateway container's ``env`` list as a dict for easy assertions."""
    deploy = _gateway_deployment(manifests)
    containers = deploy["spec"]["template"]["spec"]["containers"]
    gateway_container = next(c for c in containers if c["name"] in ("mcp-context-forge", "mcpgateway", "gateway"))
    out: dict[str, str] = {}
    for entry in gateway_container.get("env", []) or []:
        # Plain string values only — env entries with valueFrom are skipped.
        if "value" in entry:
            out[entry["name"]] = str(entry["value"])
    return out


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_skip_migrations_set_to_true_when_migration_job_enabled():
    """When the chart's migration Job is enabled, app pods must skip
    in-pod bootstrap so they don't race the Job's schema work."""
    env = _gateway_env(_helm_template("migration.enabled=true"))
    assert env.get("MCPGATEWAY_SKIP_MIGRATIONS") == "true", (
        "Expected MCPGATEWAY_SKIP_MIGRATIONS=true on the gateway Deployment "
        "when migration.enabled=true — the chart-level contract that ties "
        "the migration Job to the in-pod bootstrap skip. "
        f"Got: {env.get('MCPGATEWAY_SKIP_MIGRATIONS')!r}. Full env keys: {sorted(env)}"
    )


def test_skip_migrations_off_when_migration_job_disabled():
    """When the chart's migration Job is disabled, gateway pods are the
    sole bootstrap path. The L1 fast-path makes the in-pod path safe."""
    env = _gateway_env(_helm_template("migration.enabled=false"))
    value = env.get("MCPGATEWAY_SKIP_MIGRATIONS", "false")
    assert value == "false", (
        "Expected MCPGATEWAY_SKIP_MIGRATIONS to be absent or false when " "migration.enabled=false (the gateway is the only bootstrap path " f"in this configuration). Got: {value!r}"
    )


def test_skip_migrations_default_matches_migration_enabled_default():
    """The chart's default for migration.enabled is True (see values.yaml).
    Default render therefore must set SKIP=true."""
    env = _gateway_env(_helm_template())
    assert env.get("MCPGATEWAY_SKIP_MIGRATIONS") == "true", (
        "Default chart values render to migration.enabled=true, so " "MCPGATEWAY_SKIP_MIGRATIONS must default to 'true'. Got: " f"{env.get('MCPGATEWAY_SKIP_MIGRATIONS')!r}"
    )
