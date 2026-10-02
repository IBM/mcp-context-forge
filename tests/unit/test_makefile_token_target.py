# -*- coding: utf-8 -*-
"""Location: ./tests/unit/test_makefile_token_target.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Regression tests for the ``make token`` developer target and the
``inspector-up`` token hint.
"""

# Future
from __future__ import annotations

# Standard
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys

# Third-Party
from dotenv import dotenv_values
import jwt
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = REPO_ROOT / "Makefile"
JWT_CLI = "-m mcpgateway.utils.create_jwt_token"
WEAK_INSPECTOR_SECRET = "my-test-key-but-now-longer-than-32-bytes"  # pragma: allowlist secret

pytestmark = pytest.mark.skipif(shutil.which("make") is None, reason="GNU make is not installed")


def _clean_env(**extra: str) -> dict[str, str]:
    """Build a minimal environment so caller MAKEFLAGS, JWT_* or LOG_* values cannot leak in."""
    env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/tmp"), "PYTHONPATH": str(REPO_ROOT)}
    env.update(extra)
    return env


def _make(cwd: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run the repository Makefile with *cwd* as the make working directory."""
    return subprocess.run(
        ["make", "-f", str(MAKEFILE), "-C", str(cwd), *args],
        env=env or _clean_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def _fake_venv(tmp_path: Path) -> Path:
    """Create a VENV_DIR whose bin/python runs the interpreter that runs this test."""
    venv_dir = tmp_path / "venv"
    python = venv_dir / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n', encoding="utf-8")
    python.chmod(python.stat().st_mode | stat.S_IXUSR)
    return venv_dir


def test_token_target_is_listed_in_make_help() -> None:
    """`make help` lists the token target, its default subject and its overrides."""
    result = _make(REPO_ROOT, "-s", "help")
    help_lines = [line for line in result.stdout.splitlines() if line.startswith("token ")]

    assert result.returncode == 0, result.stderr
    assert len(help_lines) == 1
    assert "admin@example.com" in help_lines[0]
    assert "USERNAME=" in help_lines[0]
    assert "EXP=" in help_lines[0]


def test_inspector_up_points_to_make_token_instead_of_a_weak_secret() -> None:
    """The inspector-up hint uses `make token` and no hardcoded secret."""
    result = _make(REPO_ROOT, "-n", "inspector-up")

    assert result.returncode == 0, result.stderr
    assert WEAK_INSPECTOR_SECRET not in result.stdout
    assert "--secret" not in result.stdout
    assert "make token" in result.stdout


def test_token_target_defaults_to_admin_for_one_week() -> None:
    """Without overrides the recipe requests a 10080-minute admin token for admin@example.com."""
    result = _make(REPO_ROOT, "-n", "token")

    assert result.returncode == 0, result.stderr
    assert JWT_CLI in result.stdout
    assert '--username "admin@example.com"' in result.stdout
    assert "--admin" in result.stdout
    assert '--exp "10080"' in result.stdout


def test_token_target_ignores_inherited_username_but_honours_inherited_exp() -> None:
    """An exported USERNAME (the OS login name) never becomes the subject; an exported EXP applies."""
    result = _make(REPO_ROOT, "-n", "token", env=_clean_env(USERNAME="os-login-name", EXP="60"))

    assert result.returncode == 0, result.stderr
    assert '--username "admin@example.com"' in result.stdout
    assert "os-login-name" not in result.stdout
    assert '--exp "60"' in result.stdout


def test_token_target_lets_settings_load_the_signing_key_from_env_file() -> None:
    """The recipe passes no secret or algorithm, so Settings reads them from .env."""
    result = _make(REPO_ROOT, "-n", "token")

    assert result.returncode == 0, result.stderr
    assert "--secret" not in result.stdout
    assert "--algo" not in result.stdout
    assert "JWT_SECRET_KEY" not in result.stdout


def test_token_target_honours_command_line_overrides() -> None:
    """USERNAME and EXP given on the make command line reach the CLI."""
    result = _make(REPO_ROOT, "-n", "token", "USERNAME=other@example.com", "EXP=60")

    assert result.returncode == 0, result.stderr
    assert '--username "other@example.com"' in result.stdout
    assert '--exp "60"' in result.stdout


def test_token_target_without_env_file_points_to_make_setup(tmp_path: Path) -> None:
    """A missing .env fails with a `make setup` hint on stderr."""
    result = _make(tmp_path, "-s", "token", f"VENV_DIR={_fake_venv(tmp_path)}")

    assert result.returncode != 0
    assert result.stdout == ""
    assert "make setup" in result.stderr


def test_token_target_without_venv_points_to_make_install_dev(tmp_path: Path) -> None:
    """A missing venv interpreter fails with a `make install-dev` hint on stderr."""
    (tmp_path / ".env").write_text("", encoding="utf-8")

    result = _make(tmp_path, "-s", "token", f"VENV_DIR={tmp_path / 'missing-venv'}")

    assert result.returncode != 0
    assert result.stdout == ""
    assert "make install-dev" in result.stderr


@pytest.mark.parametrize(
    ("overrides", "expected_sub", "expected_minutes"),
    [
        ((), "admin@example.com", 10080),
        (("USERNAME=other@example.com", "EXP=60"), "other@example.com", 60),
    ],
)
def test_token_target_prints_only_a_token_signed_with_the_env_file_secret(tmp_path: Path, overrides: tuple[str, ...], expected_sub: str, expected_minutes: int) -> None:
    """stdout holds one admin token signed with the JWT_SECRET_KEY from .env, and stderr holds no INFO logs."""
    env_file = tmp_path / ".env"
    shutil.copyfile(REPO_ROOT / ".env.example", env_file)
    subprocess.run(
        [sys.executable, "-m", "mcpgateway.scripts.init_secrets", "--patch-env", ".env"],
        cwd=tmp_path,
        env=_clean_env(),
        capture_output=True,
        check=True,
    )
    signing_key = dotenv_values(env_file)["JWT_SECRET_KEY"]

    result = _make(tmp_path, "-s", "token", f"VENV_DIR={_fake_venv(tmp_path)}", *overrides, env=_clean_env(USERNAME="os-login-name"))

    assert result.returncode == 0, result.stderr
    assert " - INFO - " not in result.stderr
    stdout_lines = result.stdout.splitlines()
    assert len(stdout_lines) == 1
    claims = jwt.decode(stdout_lines[0], signing_key, algorithms=["HS256"], audience="mcpgateway-api", issuer="mcpgateway")
    assert claims["sub"] == expected_sub
    assert claims["user"]["is_admin"] is True
    assert claims["teams"] is None
    assert claims["exp"] - claims["iat"] == expected_minutes * 60
