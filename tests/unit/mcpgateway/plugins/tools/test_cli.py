# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/tools/test_cli.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

Tests for the mcpplugins CLI module (plugins/tools/cli.py).
"""

# Future
from __future__ import annotations

# Standard
import builtins
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

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


def test_command_exists(monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda _name: "/bin/true")
    assert cli.command_exists("git") is True

    monkeypatch.setattr(cli.shutil, "which", lambda _name: None)
    assert cli.command_exists("git") is False


def test_git_user_name_email(monkeypatch):
    class _Result:
        returncode = 0
        stdout = b"Jane Doe\n"

    monkeypatch.setattr(cli.subprocess, "run", lambda *_args, **_kwargs: _Result())
    assert cli.git_user_name() == "Jane Doe"

    class _EmailResult:
        returncode = 0
        stdout = b"jane@example.com\n"

    monkeypatch.setattr(cli.subprocess, "run", lambda *_args, **_kwargs: _EmailResult())
    assert cli.git_user_email() == "jane@example.com"


def test_git_user_name_email_defaults_on_error(monkeypatch):
    def _boom(*_args, **_kwargs):
        raise RuntimeError("fail")

    monkeypatch.setattr(cli.subprocess, "run", _boom)
    assert cli.git_user_name() == cli.DEFAULT_AUTHOR_NAME
    assert cli.git_user_email() == cli.DEFAULT_AUTHOR_EMAIL


def test_bootstrap_missing_copier_raises(monkeypatch):
    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "copier":
            raise ImportError("no copier")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    with pytest.raises(cli.typer.Exit) as excinfo:
        cli.bootstrap()
    assert excinfo.value.exit_code == 1


def test_bootstrap_skips_without_git(monkeypatch, tmp_path):
    run_copy = MagicMock()
    monkeypatch.setitem(sys.modules, "copier", SimpleNamespace(run_copy=run_copy))
    monkeypatch.setattr(cli, "command_exists", lambda _name: False)

    cli.bootstrap(destination=tmp_path, template_url="https://example.com/repo.git", dry_run=True)
    run_copy.assert_not_called()


def test_bootstrap_calls_copier_when_git_available(monkeypatch, tmp_path):
    run_copy = MagicMock()
    monkeypatch.setitem(sys.modules, "copier", SimpleNamespace(run_copy=run_copy))
    monkeypatch.setattr(cli, "command_exists", lambda _name: True)
    monkeypatch.setattr(cli, "git_user_name", lambda: "Alice")
    monkeypatch.setattr(cli, "git_user_email", lambda: "alice@example.com")

    cli.bootstrap(destination=tmp_path, template_url="https://example.com/repo.git", defaults=True, dry_run=True)
    run_copy.assert_called_once()


def test_main_calls_typer_app(monkeypatch):
    called = {}

    def _fake_app(*args, **kwargs):  # noqa: ANN002, ANN003
        called["args"] = args
        called["kwargs"] = kwargs

    monkeypatch.setattr(cli, "app", _fake_app)

    cli.main()

    assert called["args"] == ()
    assert called["kwargs"] == {}
