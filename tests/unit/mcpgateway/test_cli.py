# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_cli.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for the mcpgateway CLI module (cli.py).
This module contains tests for the tiny "Uvicorn wrapper" found in
mcpgateway.cli.  It exercises **every** decision point:

* `_needs_app`  - missing vs. present app path
* `_insert_defaults` - all permutations of host/port injection
* `main()` - early-return on --version / -V **and** the happy path that
  actually calls Uvicorn with a patched ``sys.argv``.
"""

# Future
from __future__ import annotations

# Standard
import sys
from typing import Any, Dict, List

# Third-Party
import pytest

# First-Party
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


def test_insert_defaults_respects_explicit_port() -> None:
    """Port given, host missing ⇒ only host default injected."""
    raw = ["myapp:app", "--port", "1234"]
    out = cli._insert_defaults(raw)

    assert out[0] == "myapp:app"
    assert out.count("--port") == 1
    assert "1234" in out
    assert str(cli.DEFAULT_PORT) not in out
    assert "--host" in out and cli.DEFAULT_HOST in out


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


def test_main_invokes_uvicorn_with_no_args(monkeypatch) -> None:
    """No arguments should still invoke Uvicorn with injected defaults."""
    captured = _capture_uvicorn_main(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["mcpgateway"])

    cli.main()

    assert "argv" in captured
    patched = captured["argv"]
    assert patched[0] == "mcpgateway"
    assert cli.DEFAULT_APP in patched
    assert "--host" in patched and cli.DEFAULT_HOST in patched
    assert "--port" in patched and str(cli.DEFAULT_PORT) in patched


@pytest.mark.parametrize(
    ("argv", "expected_path"),
    [
        (["mcpgateway", "--validate-config"], ".env"),
        (["mcpgateway", "--validate-config", ".env.example"], ".env.example"),
    ],
)
def test_main_validate_config_flag_calls_handler(argv: List[str], expected_path: str, monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(cli.uvicorn, "main", lambda: (_ for _ in ()).throw(RuntimeError("should not be called")))

    called = {}

    def _fake_handler(path: str = ".env") -> None:
        called["path"] = path

    monkeypatch.setattr(cli, "_handle_validate_config", _fake_handler)

    cli.main()
    assert called["path"] == expected_path


@pytest.mark.parametrize(
    ("argv", "expected_output"),
    [
        (["mcpgateway", "--config-schema"], None),
        (["mcpgateway", "--config-schema", "schema.json"], "schema.json"),
    ],
)
def test_main_config_schema_flag_calls_handler(argv: List[str], expected_output: str | None, monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(cli.uvicorn, "main", lambda: (_ for _ in ()).throw(RuntimeError("should not be called")))

    called = {}

    def _fake_handler(output: str | None = None) -> None:
        called["output"] = output

    monkeypatch.setattr(cli, "_handle_config_schema", _fake_handler)

    cli.main()
    assert called["output"] == expected_output


def test_main_support_bundle_parses_options(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["mcpgateway", "--support-bundle", "--no-system", "--unknown-flag"])
    monkeypatch.setattr(cli.uvicorn, "main", lambda: (_ for _ in ()).throw(RuntimeError("should not be called")))

    called = {}

    def _fake_handler(
        output_dir: str | None = None,
        log_lines: int = 1000,
        include_logs: bool = True,
        include_env: bool = True,
        include_system: bool = True,
    ) -> None:
        called.update(
            {
                "output_dir": output_dir,
                "log_lines": log_lines,
                "include_logs": include_logs,
                "include_env": include_env,
                "include_system": include_system,
            }
        )

    monkeypatch.setattr(cli, "_handle_support_bundle", _fake_handler)

    cli.main()

    assert called["include_system"] is False
    # Defaults for unspecified options
    assert called["include_logs"] is True
    assert called["include_env"] is True
    assert called["log_lines"] == 1000
