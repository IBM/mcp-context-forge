# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/tools/test_cli.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

Tests for the mcpplugins CLI module (plugins/tools/cli.py).
"""

# Future
from __future__ import annotations

# Third-Party
import pytest
from typer.testing import CliRunner
import yaml

# First-Party
import mcpgateway.plugins.tools.cli as cli
from mcpgateway.plugins.tools.models import InstallManifest


@pytest.fixture(scope="module", autouse=True)
def runner():
    runner = CliRunner()
    yield runner


def test_bootrap_command_help(runner: CliRunner):
    """Boostrapping help."""
    raw = ["bootstrap", "--help"]
    result = runner.invoke(cli.app, raw)
    assert "Creates a new plugin project from template" in result.stdout


def test_bootstrap_command_dry_run(runner: CliRunner):
    """Boostrapping dry run."""
    pytest.importorskip("copier")
    raw = ["bootstrap", "--destination", "/tmp/myplugin", "--template_url", ".", "--defaults", "--dry_run"]
    result = runner.invoke(cli.app, raw)
    assert result.exit_code == 0


def test_install_manifest():
    """Test install manifest."""
    with open("./tests/unit/mcpgateway/plugins/fixtures/install.yaml") as f:
        data = yaml.safe_load(f)
        manifest = InstallManifest.model_validate(data)
        assert manifest
        assert len(manifest.packages) > 0
