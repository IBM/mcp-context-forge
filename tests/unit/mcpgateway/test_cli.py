# -*- coding: utf-8 -*-
"""Tests for the mcpgateway CLI module (cli.py).

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

This module contains tests for the tiny "Uvicorn wrapper" found in
mcpgateway.cli.  It exercises **every** decision point:

* `_needs_app`  - missing vs. present app path
* `_insert_defaults` - all permutations of host/port injection
* `main()` - early-return on --version / -V **and** the happy path that
  actually calls Uvicorn with a patched ``sys.argv``.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

import mcpgateway.cli as cli

# ---------------------------------------------------------------------------
# helpers / fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _restore_sys_argv() -> None:
    """Keep the global *sys.argv* pristine between tests."""
    original = sys.argv.copy()
    yield
    sys.argv[:] = original


def _capture_uvicorn_main(monkeypatch) -> Dict[str, Any]:
    """Monkey-patch *uvicorn.main* and record the argv it sees."""
    captured: Dict[str, Any] = {}

    def _fake_main() -> None:
        # Copy because tests mutate sys.argv afterwards.
        captured["argv"] = sys.argv.copy()

    monkeypatch.setattr(cli.uvicorn, "main", _fake_main)
    return captured


# ---------------------------------------------------------------------------
#  _needs_app
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "missing"),
    [
        ([], True),  # no positional args at all
        (["--reload"], True),  # first token is an option
        (["somepkg.app:app"], False),  # explicit app path present
    ],
)
def test_needs_app_detection(argv: List[str], missing: bool) -> None:
    assert cli._needs_app(argv) is missing


# ---------------------------------------------------------------------------
#  _insert_defaults
# ---------------------------------------------------------------------------


def test_insert_defaults_injects_everything() -> None:
    """No app/host/port supplied ⇒ inject all three."""
    raw = ["--reload"]
    out = cli._insert_defaults(raw)

    # original list must remain untouched (function copies)
    assert raw == ["--reload"]

    assert out[0] == cli.DEFAULT_APP
    assert "--host" in out and cli.DEFAULT_HOST in out
    assert "--port" in out and str(cli.DEFAULT_PORT) in out


def test_insert_defaults_respects_explicit_host(monkeypatch) -> None:
    """Host given, port missing ⇒ only port default injected."""
    raw = ["myapp:app", "--host", "0.0.0.0"]
    out = cli._insert_defaults(raw)

    # our app path must stay first
    assert out[0] == "myapp:app"
    # host left untouched, port injected
    assert out.count("--host") == 1
    assert "--port" in out and str(cli.DEFAULT_PORT) in out


def test_insert_defaults_skips_for_uds() -> None:
    """When --uds is present no host/port defaults are added."""
    raw = ["--uds", "/tmp/app.sock"]
    out = cli._insert_defaults(raw)

    assert "--host" not in out
    assert "--port" not in out


# ---------------------------------------------------------------------------
#  main() - early *--version* short-circuit
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("flag", ["--version", "-V"])
def test_main_prints_version_and_exits(flag: str, capsys, monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["mcpgateway", flag])
    # If Uvicorn accidentally ran we'd hang the tests - make sure it can't.
    monkeypatch.setattr(cli.uvicorn, "main", lambda: (_ for _ in ()).throw(RuntimeError("should not be called")))
    cli.main()

    out, err = capsys.readouterr()
    assert out.strip() == f"mcpgateway {cli.__version__}"
    assert err == ""


# ---------------------------------------------------------------------------
#  main() - normal execution path (calls Uvicorn)
# ---------------------------------------------------------------------------


def test_main_invokes_uvicorn_with_patched_argv(monkeypatch) -> None:
    """Ensure *main()* rewrites argv then delegates to Uvicorn."""
    captured = _capture_uvicorn_main(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["mcpgateway", "--reload"])

    cli.main()

    # The fake Uvicorn ran exactly once
    assert "argv" in captured
    patched = captured["argv"]

    # Position 0 must be the console-script name
    assert patched[0] == "mcpgateway"
    # The injected app path must follow
    assert patched[1] == cli.DEFAULT_APP
    # Original flag preserved
    assert "--reload" in patched
    # Defaults present
    assert "--host" in patched and cli.DEFAULT_HOST in patched
    assert "--port" in patched and str(cli.DEFAULT_PORT) in patched
