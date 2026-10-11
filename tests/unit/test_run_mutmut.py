# -*- coding: utf-8 -*-
"""Location: ./tests/unit/test_run_mutmut.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for run_mutmut.py cleanup logic.

Covers the shutil.rmtree replacement for os.system in run_mutmut.py (PR #3944).
"""

# Standard
import importlib
from unittest.mock import call, patch

# Third-Party
import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def _mutmut_module(tmp_path, monkeypatch):
    """Import (or reload) run_mutmut in an isolated cwd with controlled argv."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["run_mutmut.py"])

    # First-Party
    import run_mutmut

    importlib.reload(run_mutmut)  # ensure module picks up current cwd
    return run_mutmut


# ===========================================================================
# run_mutmut.py: shutil.rmtree replacement
# ===========================================================================


class TestMutmutCleanup:
    """Verify shutil.rmtree replaced os.system for directory cleanup."""

    def test_existing_dirs_are_removed(self, tmp_path, _mutmut_module):
        """Both mutants/ and .mutmut-cache/ are deleted before mutant generation."""
        (tmp_path / "mutants").mkdir()
        (tmp_path / ".mutmut-cache").mkdir()
        (tmp_path / "mutants" / "file.py").write_text("x")

        with patch.object(_mutmut_module, "run_command", return_value=("", "", 1)):
            _mutmut_module.main()

        assert not (tmp_path / "mutants").exists()
        assert not (tmp_path / ".mutmut-cache").exists()

    def test_missing_dirs_do_not_raise(self, tmp_path, _mutmut_module):
        """FileNotFoundError is caught so absent directories are silently skipped."""
        assert not (tmp_path / "mutants").exists()
        assert not (tmp_path / ".mutmut-cache").exists()

        with patch.object(_mutmut_module, "run_command", return_value=("", "", 1)):
            result = _mutmut_module.main()

        assert result == 1  # returns 1 because mutants/ never appears

    def test_rmtree_called_without_ignore_errors(self, _mutmut_module):
        """shutil.rmtree is called without ignore_errors (real errors must propagate)."""
        with patch.object(_mutmut_module.shutil, "rmtree") as mock_rm:
            with patch.object(_mutmut_module, "run_command", return_value=("", "", 1)):
                _mutmut_module.main()

        # rmtree must be called without ignore_errors — only FileNotFoundError is caught
        assert mock_rm.call_args_list == [
            call("mutants"),
            call(".mutmut-cache"),
        ]

    def test_partial_dir_removal(self, tmp_path, _mutmut_module):
        """Only one of the two dirs exists; the other is a no-op."""
        (tmp_path / ".mutmut-cache").mkdir()

        with patch.object(_mutmut_module, "run_command", return_value=("", "", 1)):
            _mutmut_module.main()

        assert not (tmp_path / ".mutmut-cache").exists()

    def test_permission_error_propagates(self, tmp_path, _mutmut_module):
        """Non-FileNotFoundError exceptions (e.g. PermissionError) must not be swallowed.

        If stale directories can't actually be removed, the script must fail
        rather than silently proceeding with stale mutant data.
        """

        def rmtree_perm_error(path):
            if path == "mutants":
                raise PermissionError(f"Cannot remove {path}")

        with patch.object(_mutmut_module.shutil, "rmtree", side_effect=rmtree_perm_error):
            with patch.object(_mutmut_module, "run_command", return_value=("", "", 1)):
                with pytest.raises(PermissionError, match="Cannot remove mutants"):
                    _mutmut_module.main()
