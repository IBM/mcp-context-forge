# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/tools/builder/test_factory.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Unit tests for DeployFactory.
"""

# Standard
import sys
from types import SimpleNamespace
from unittest.mock import patch

# Third-Party
import pytest

# First-Party
from mcpgateway.tools.builder.factory import CICDTypes, DeployFactory


class DummyDagger:
    """Mock Dagger deployer."""

    def __init__(self, verbose):
        self.verbose = verbose


class DummyPython:
    """Mock Python deployer."""

    def __init__(self, verbose):
        self.verbose = verbose


def test_deploy_factory_dagger_verbose_logs(monkeypatch):
    """Test Dagger mode with verbose logging enabled."""
    monkeypatch.setitem(
        sys.modules,
        "mcpgateway.tools.builder.dagger_deploy",
        SimpleNamespace(DAGGER_AVAILABLE=True, MCPStackDagger=DummyDagger),
    )
    monkeypatch.setitem(
        sys.modules,
        "mcpgateway.tools.builder.python_deploy",
        SimpleNamespace(MCPStackPython=DummyPython),
    )

    with patch("mcpgateway.tools.builder.factory.console.print") as mock_print:
        deployer, mode = DeployFactory.create_deployer("dagger", verbose=True)

    assert isinstance(deployer, DummyDagger)
    assert mode == CICDTypes.DAGGER
    # Verify verbose message was printed
    mock_print.assert_called_once_with("[green]✓ Dagger module loaded[/green]")


def test_deploy_factory_python_explicit_request(monkeypatch):
    """Test explicitly requesting Python mode (not fallback)."""
    monkeypatch.setitem(
        sys.modules,
        "mcpgateway.tools.builder.python_deploy",
        SimpleNamespace(MCPStackPython=DummyPython),
    )

    with patch("mcpgateway.tools.builder.factory.console.print") as mock_print:
        deployer, mode = DeployFactory.create_deployer("python", verbose=True)

    assert isinstance(deployer, DummyPython)
    assert mode == CICDTypes.PYTHON
    # Verify explicit Python mode message was printed
    mock_print.assert_called_once_with("[blue]Using plain Python implementation[/blue]")


def test_deploy_factory_python_non_verbose(monkeypatch):
    """Test Python mode without verbose logging."""
    monkeypatch.setitem(
        sys.modules,
        "mcpgateway.tools.builder.python_deploy",
        SimpleNamespace(MCPStackPython=DummyPython),
    )

    with patch("mcpgateway.tools.builder.factory.console.print") as mock_print:
        deployer, mode = DeployFactory.create_deployer("python", verbose=False)

    assert isinstance(deployer, DummyPython)
    assert mode == CICDTypes.PYTHON
    # Verify no verbose message when verbose=False
    mock_print.assert_not_called()
