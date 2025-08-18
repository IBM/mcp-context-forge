# -*- coding: utf-8 -*-
"""Tests for the mcpplugins CLI module (plugins/tools/cli.py).

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

"""

# Future
from __future__ import annotations

# Third-Party
import pytest
from typer.testing import CliRunner

# First-Party
import mcpgateway.plugins.tools.cli as cli


@pytest.fixture(scope="module", autouse=True)
def runner():
    runner = CliRunner()
    yield runner


def test_bootrap_command_help(runner: CliRunner):
    """Boostrapping help."""
    raw = ["bootstrap", "--help"]
    result = runner.invoke(cli.app, raw)
    assert "Creates a new plugin project from template" in result.stdout

def test_bootrap_command_dry_run(runner: CliRunner):
    """Boostrapping dry run."""
    raw = ["bootstrap", "--destination", "/tmp/myplugin", "--template_url", ".", "--defaults", "--dry_run"]
    result = runner.invoke(cli.app, raw)
    assert result.exit_code == 0
