# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/tools/builder/test_build_hooks.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for mcpgateway/tools/builder/build_hooks.py.
"""

# Standard
from importlib.metadata import PackageNotFoundError, version
import importlib.util
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
# Build module availability check
# ---------------------------------------------------------------------------


def _has_build_module() -> bool:
    """Check if the PyPA build frontend is importable."""
    return importlib.util.find_spec("build") is not None


def _can_build_without_isolation() -> bool:
    """Check if the running environment already satisfies the wheel test's build requirements."""
    try:
        installed = tuple(int(part) for part in version("setuptools").split(".")[:3])
    except (PackageNotFoundError, ValueError):
        return False
    return installed >= (78, 1, 1)


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


_WHEEL_BUNDLE_NAME = "bundle-deadbeef.js"


def _build_wheel(project_dir: Path) -> Path:
    """Build a wheel from the minimal project in project_dir; return the .whl path."""
    dist_dir = project_dir / "dist"
    env = {k: v for k, v in os.environ.items() if k != "BUILD_UI_ASSETS"}
    command = [sys.executable, "-m", "build", "--wheel", "--outdir", str(dist_dir)]
    # Trade-off: the host setuptools (>=78.1.1) replaces the isolated build env, which avoids a network install of the
    # build backend. The real pyproject.toml pins a newer setuptools; this test project does not need it.
    if _can_build_without_isolation():
        command.append("--no-isolation")
    result = subprocess.run(command, check=False, cwd=str(project_dir), env=env, capture_output=True, text=True)
    assert result.returncode == 0, f"wheel build failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    wheels = list(dist_dir.glob("*.whl"))
    assert len(wheels) == 1, f"expected 1 wheel, got {wheels}"
    return wheels[0]


@pytest.fixture(scope="module")
def wheel_names(tmp_path_factory) -> list:
    """Build a wheel once for the module and return the names of its entries."""
    project_dir = tmp_path_factory.mktemp("wheel-project")
    static = project_dir / "mcpgateway" / "static"
    static.mkdir(parents=True)
    (project_dir / "mcpgateway" / "__init__.py").write_text("")
    (static / _WHEEL_BUNDLE_NAME).write_text("// vite bundle")
    (static / "tailwind.min.css").write_text("/* tailwind */")
    (static / "secret.txt").write_text("should not ship")
    (project_dir / "pyproject.toml").write_text(_MINIMAL_PYPROJECT)
    with zipfile.ZipFile(_build_wheel(project_dir)) as zf:
        return zf.namelist()


@pytest.mark.slow
@pytest.mark.skipif(not _has_build_module(), reason="build module not installed")
class TestWheelContents:
    """Verify which UI assets the shared minimal wheel contains."""

    def test_wheel_contains_bundle_js(self, wheel_names):
        assert any(_WHEEL_BUNDLE_NAME in n for n in wheel_names), f"{_WHEEL_BUNDLE_NAME} not found in wheel: {wheel_names}"

    def test_wheel_contains_tailwind_css(self, wheel_names):
        assert any("tailwind.min.css" in n for n in wheel_names), f"tailwind.min.css not found in wheel: {wheel_names}"

    def test_wheel_excludes_files_outside_globs(self, wheel_names):
        assert not any("secret.txt" in n for n in wheel_names)
