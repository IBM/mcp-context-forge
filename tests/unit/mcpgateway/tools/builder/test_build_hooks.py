# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/tools/builder/test_build_hooks.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for mcpgateway/tools/builder/build_hooks.py.
"""

# Standard
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

# Third-Party
import pytest

import mcpgateway.tools.builder.build_hooks as bh_module
from mcpgateway.tools.builder.build_hooks import BuildPyWithUI

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project(tmp_path: Path, *, with_static: bool = True, with_node_modules: bool = False) -> Path:
    """Minimal project tree under tmp_path."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    if with_static:
        (tmp_path / "mcpgateway" / "static").mkdir(parents=True)
    if with_node_modules:
        (tmp_path / "node_modules").mkdir()
    return tmp_path


@pytest.fixture()
def hook():
    """BuildPyWithUI instance without calling __init__."""
    return BuildPyWithUI.__new__(BuildPyWithUI)


@pytest.fixture()
def project(tmp_path):
    """Project tree with static dir and node_modules."""
    return _make_project(tmp_path, with_static=True, with_node_modules=True)


@pytest.fixture()
def anchored(project, monkeypatch):
    """Anchor build_hooks.__file__ inside the tmp project so path discovery works."""
    fake_file = project / "mcpgateway" / "tools" / "builder" / "build_hooks.py"
    fake_file.parent.mkdir(parents=True, exist_ok=True)
    fake_file.write_text("")
    monkeypatch.setattr(bh_module, "__file__", str(fake_file))
    return project


# ---------------------------------------------------------------------------
# BUILD_UI_ASSETS flag
# ---------------------------------------------------------------------------


class TestBuildUIAssetsFlag:
    def test_skips_when_flag_unset(self, hook, monkeypatch):
        monkeypatch.delenv("BUILD_UI_ASSETS", raising=False)
        with patch("mcpgateway.tools.builder.build_hooks.build_py.run") as super_run:
            hook.run()
        super_run.assert_called_once()

    @pytest.mark.parametrize("value", ["1", "0", "false", "FALSE", "yes", ""])
    def test_skips_for_non_true_values(self, hook, monkeypatch, value):
        monkeypatch.setenv("BUILD_UI_ASSETS", value)
        with patch("mcpgateway.tools.builder.build_hooks.build_py.run") as super_run:
            hook.run()
        super_run.assert_called_once()

    @pytest.mark.parametrize("value", ["true", "True", "TRUE"])
    def test_proceeds_for_true_values(self, hook, anchored, monkeypatch, value):
        monkeypatch.setenv("BUILD_UI_ASSETS", value)
        with patch("mcpgateway.tools.builder.build_hooks.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            with patch("mcpgateway.tools.builder.build_hooks.build_py.run"):
                hook.run()
        assert mock_run.called


# ---------------------------------------------------------------------------
# Project root discovery
# ---------------------------------------------------------------------------


class TestProjectRootDiscovery:
    def test_exits_when_pyproject_not_found(self, hook, tmp_path, monkeypatch):
        # __file__ inside a deep dir with no pyproject.toml anywhere
        deep = tmp_path / "a" / "b" / "c"
        deep.mkdir(parents=True)
        fake_file = deep / "build_hooks.py"
        fake_file.write_text("")
        monkeypatch.setattr(bh_module, "__file__", str(fake_file))
        monkeypatch.setenv("BUILD_UI_ASSETS", "true")

        with pytest.raises(SystemExit) as exc_info:
            hook.run()
        assert exc_info.value.code == 1

    def test_traversal_stops_at_max_depth(self, hook, tmp_path, monkeypatch):
        # pyproject.toml exists only at root, __file__ is 12 levels deep (> _max_depth=10)
        deep = tmp_path
        for _ in range(12):
            deep = deep / "sub"
        deep.mkdir(parents=True)
        (tmp_path / "pyproject.toml").write_text("")  # too far up

        fake_file = deep / "build_hooks.py"
        fake_file.write_text("")
        monkeypatch.setattr(bh_module, "__file__", str(fake_file))
        monkeypatch.setenv("BUILD_UI_ASSETS", "true")

        with pytest.raises(SystemExit) as exc_info:
            hook.run()
        assert exc_info.value.code == 1

    def test_finds_root_within_depth_limit(self, hook, anchored, monkeypatch):
        monkeypatch.setenv("BUILD_UI_ASSETS", "true")
        with patch("mcpgateway.tools.builder.build_hooks.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            with patch("mcpgateway.tools.builder.build_hooks.build_py.run"):
                hook.run()  # must not sys.exit
        assert mock_run.called


# ---------------------------------------------------------------------------
# Static directory validation
# ---------------------------------------------------------------------------


class TestStaticDirValidation:
    def test_exits_when_static_dir_missing(self, hook, tmp_path, monkeypatch):
        _make_project(tmp_path, with_static=False, with_node_modules=True)
        fake_file = tmp_path / "mcpgateway" / "tools" / "builder" / "build_hooks.py"
        fake_file.parent.mkdir(parents=True, exist_ok=True)
        fake_file.write_text("")
        monkeypatch.setattr(bh_module, "__file__", str(fake_file))
        monkeypatch.setenv("BUILD_UI_ASSETS", "true")

        with patch("mcpgateway.tools.builder.build_hooks.subprocess.run"):
            with pytest.raises(SystemExit) as exc_info:
                hook.run()
        assert exc_info.value.code == 1

    def test_removes_old_bundles(self, hook, anchored, monkeypatch):
        static = anchored / "mcpgateway" / "static"
        b1 = static / "bundle-aaa111.js"
        b2 = static / "bundle-bbb222.js"
        b1.write_text("old")
        b2.write_text("old")

        monkeypatch.setenv("BUILD_UI_ASSETS", "true")
        with patch("mcpgateway.tools.builder.build_hooks.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            with patch("mcpgateway.tools.builder.build_hooks.build_py.run"):
                hook.run()

        assert not b1.exists()
        assert not b2.exists()

    def test_non_bundle_js_files_untouched(self, hook, anchored, monkeypatch):
        static = anchored / "mcpgateway" / "static"
        keeper = static / "app.js"
        keeper.write_text("keep me")

        monkeypatch.setenv("BUILD_UI_ASSETS", "true")
        with patch("mcpgateway.tools.builder.build_hooks.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            with patch("mcpgateway.tools.builder.build_hooks.build_py.run"):
                hook.run()

        assert keeper.exists()


# ---------------------------------------------------------------------------
# npm checks
# ---------------------------------------------------------------------------


class TestNpmChecks:
    def test_exits_when_npm_not_found(self, hook, anchored, monkeypatch):
        monkeypatch.setenv("BUILD_UI_ASSETS", "true")
        with patch("mcpgateway.tools.builder.build_hooks.subprocess.run", side_effect=FileNotFoundError):
            with pytest.raises(SystemExit) as exc_info:
                hook.run()
        assert exc_info.value.code == 1

    def test_exits_when_npm_version_check_fails(self, hook, anchored, monkeypatch):
        monkeypatch.setenv("BUILD_UI_ASSETS", "true")
        with patch(
            "mcpgateway.tools.builder.build_hooks.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "npm"),
        ):
            with pytest.raises(SystemExit) as exc_info:
                hook.run()
        assert exc_info.value.code == 1

    def test_runs_npm_install_when_node_modules_missing(self, hook, tmp_path, monkeypatch):
        _make_project(tmp_path, with_static=True, with_node_modules=False)
        fake_file = tmp_path / "mcpgateway" / "tools" / "builder" / "build_hooks.py"
        fake_file.parent.mkdir(parents=True, exist_ok=True)
        fake_file.write_text("")
        monkeypatch.setattr(bh_module, "__file__", str(fake_file))
        monkeypatch.setenv("BUILD_UI_ASSETS", "true")

        with patch("mcpgateway.tools.builder.build_hooks.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            with patch("mcpgateway.tools.builder.build_hooks.build_py.run"):
                hook.run()

        calls = [c.args[0] for c in mock_run.call_args_list]
        assert ["npm", "install"] in calls

    def test_skips_npm_install_when_node_modules_present(self, hook, anchored, monkeypatch):
        monkeypatch.setenv("BUILD_UI_ASSETS", "true")
        with patch("mcpgateway.tools.builder.build_hooks.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            with patch("mcpgateway.tools.builder.build_hooks.build_py.run"):
                hook.run()

        calls = [c.args[0] for c in mock_run.call_args_list]
        assert ["npm", "install"] not in calls

    def test_exits_when_npm_install_fails(self, hook, tmp_path, monkeypatch):
        _make_project(tmp_path, with_static=True, with_node_modules=False)
        fake_file = tmp_path / "mcpgateway" / "tools" / "builder" / "build_hooks.py"
        fake_file.parent.mkdir(parents=True, exist_ok=True)
        fake_file.write_text("")
        monkeypatch.setattr(bh_module, "__file__", str(fake_file))
        monkeypatch.setenv("BUILD_UI_ASSETS", "true")

        def _side_effect(cmd, **kwargs):
            if cmd == ["npm", "--version"]:
                return MagicMock(returncode=0)
            if cmd == ["npm", "install"]:
                raise subprocess.CalledProcessError(1, "npm install")
            return MagicMock(returncode=0)

        with patch("mcpgateway.tools.builder.build_hooks.subprocess.run", side_effect=_side_effect):
            with pytest.raises(SystemExit) as exc_info:
                hook.run()
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# Build steps
# ---------------------------------------------------------------------------


class TestBuildSteps:
    def test_exits_when_vite_build_fails(self, hook, anchored, monkeypatch):
        monkeypatch.setenv("BUILD_UI_ASSETS", "true")

        def _side_effect(cmd, **kwargs):
            if cmd == ["npm", "run", "vite:build"]:
                raise subprocess.CalledProcessError(1, "vite:build")
            return MagicMock(returncode=0)

        with patch("mcpgateway.tools.builder.build_hooks.subprocess.run", side_effect=_side_effect):
            with pytest.raises(SystemExit) as exc_info:
                hook.run()
        assert exc_info.value.code == 1

    def test_exits_when_css_build_fails(self, hook, anchored, monkeypatch):
        monkeypatch.setenv("BUILD_UI_ASSETS", "true")

        def _side_effect(cmd, **kwargs):
            if cmd == ["npm", "run", "build:css"]:
                raise subprocess.CalledProcessError(1, "build:css")
            return MagicMock(returncode=0)

        with patch("mcpgateway.tools.builder.build_hooks.subprocess.run", side_effect=_side_effect):
            with pytest.raises(SystemExit) as exc_info:
                hook.run()
        assert exc_info.value.code == 1

    def test_happy_path_runs_all_npm_commands_and_calls_super(self, hook, anchored, monkeypatch):
        monkeypatch.setenv("BUILD_UI_ASSETS", "true")

        with patch("mcpgateway.tools.builder.build_hooks.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            with patch("mcpgateway.tools.builder.build_hooks.build_py.run") as super_run:
                hook.run()

        calls = [c.args[0] for c in mock_run.call_args_list]
        assert ["npm", "--version"] in calls
        assert ["npm", "run", "vite:build"] in calls
        assert ["npm", "run", "build:css"] in calls
        super_run.assert_called_once()

    def test_happy_path_npm_commands_use_project_root_as_cwd(self, hook, anchored, monkeypatch):
        monkeypatch.setenv("BUILD_UI_ASSETS", "true")

        with patch("mcpgateway.tools.builder.build_hooks.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            with patch("mcpgateway.tools.builder.build_hooks.build_py.run"):
                hook.run()

        cwd_values = {tuple(c.args[0]): c.kwargs.get("cwd") or c.args[1] if len(c.args) > 1 else c.kwargs.get("cwd") for c in mock_run.call_args_list if c.args[0] != ["npm", "--version"]}
        for cmd, cwd in cwd_values.items():
            assert cwd is not None, f"cwd not set for {cmd}"
            assert Path(str(cwd)).is_absolute()


# ---------------------------------------------------------------------------
# Wheel contents
# ---------------------------------------------------------------------------

_MINIMAL_PYPROJECT = """\
[build-system]
requires = ["setuptools>=78.1.1"]
build-backend = "setuptools.build_meta"

[project]
name = "mcpgateway-wheel-test"
version = "0.0.1"

[tool.setuptools.package-data]
mcpgateway = [
    "static/*.css",
    "static/*.js",
]
"""


@pytest.mark.slow
class TestWheelContents:
    """Build a real (minimal) wheel and verify UI assets are present inside."""

    def _build_wheel(self, tmp_path: Path) -> Path:
        """Build a wheel from a minimal project in tmp_path; return the .whl path."""
        dist_dir = tmp_path / "dist"
        env = {k: v for k, v in os.environ.items() if k != "BUILD_UI_ASSETS"}
        result = subprocess.run(
            [sys.executable, "-m", "build", "--wheel", "--outdir", str(dist_dir)],
            cwd=str(tmp_path),
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"wheel build failed:\n{result.stderr}"
        wheels = list(dist_dir.glob("*.whl"))
        assert len(wheels) == 1, f"expected 1 wheel, got {wheels}"
        return wheels[0]

    def _setup_project(self, tmp_path: Path, *, bundle_name: str = "bundle-abc123.js") -> None:
        """Create a minimal package tree with pre-seeded UI assets."""
        static = tmp_path / "mcpgateway" / "static"
        static.mkdir(parents=True)
        (tmp_path / "mcpgateway" / "__init__.py").write_text("")
        (static / bundle_name).write_text("// vite bundle")
        (static / "tailwind.min.css").write_text("/* tailwind */")
        (tmp_path / "pyproject.toml").write_text(_MINIMAL_PYPROJECT)

    def test_wheel_contains_bundle_js(self, tmp_path):
        bundle_name = "bundle-deadbeef.js"
        self._setup_project(tmp_path, bundle_name=bundle_name)
        wheel = self._build_wheel(tmp_path)
        with zipfile.ZipFile(wheel) as zf:
            names = zf.namelist()
        assert any(bundle_name in n for n in names), f"{bundle_name} not found in wheel: {names}"

    def test_wheel_contains_tailwind_css(self, tmp_path):
        self._setup_project(tmp_path)
        wheel = self._build_wheel(tmp_path)
        with zipfile.ZipFile(wheel) as zf:
            names = zf.namelist()
        assert any("tailwind.min.css" in n for n in names), f"tailwind.min.css not found in wheel: {names}"

    def test_wheel_excludes_files_outside_globs(self, tmp_path):
        self._setup_project(tmp_path)
        static = tmp_path / "mcpgateway" / "static"
        (static / "secret.txt").write_text("should not ship")
        wheel = self._build_wheel(tmp_path)
        with zipfile.ZipFile(wheel) as zf:
            names = zf.namelist()
        assert not any("secret.txt" in n for n in names)
