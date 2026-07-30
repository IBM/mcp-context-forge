# -*- coding: utf-8 -*-
"""Unit tests for mcpgateway/plugins/cpex_compat.py.

Location: ./tests/unit/mcpgateway/plugins/test_cpex_compat.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0
"""

# Standard
import sys
from unittest.mock import MagicMock, patch

# First-Party
import mcpgateway.plugins.cpex_compat as cpex_compat_mod
from mcpgateway.plugins.cpex_compat import execution_records_supported, get_executions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_cache():
    """Reset the module-level cache so each test starts clean."""
    cpex_compat_mod._EXECUTION_RECORDS_SUPPORTED = None  # pylint: disable=protected-access


# ---------------------------------------------------------------------------
# execution_records_supported
# ---------------------------------------------------------------------------


class TestExecutionRecordsSupported:
    """Tests for execution_records_supported()."""

    def setup_method(self):
        _reset_cache()

    def teardown_method(self):
        _reset_cache()

    def test_returns_true_when_cpex_available(self):
        """Returns True when cpex 0.1.2+ is installed (ControlExecutionRecord importable)."""
        result = execution_records_supported()
        assert result is True

    def test_result_is_bool(self):
        """Always returns a plain bool, not a truthy/falsy object."""
        result = execution_records_supported()
        assert isinstance(result, bool)

    def test_result_is_cached(self):
        """Second call returns the cached result without re-importing."""
        r1 = execution_records_supported()
        r2 = execution_records_supported()
        assert r1 is r2

    def test_returns_false_when_import_fails(self):
        """Returns False gracefully when cpex cannot be imported."""
        _reset_cache()
        cpex_compat_mod._EXECUTION_RECORDS_SUPPORTED = False  # pylint: disable=protected-access
        result = cpex_compat_mod.execution_records_supported()
        assert result is False


# ---------------------------------------------------------------------------
# execution_records_supported — actual ImportError branch (lines 51-52)
# ---------------------------------------------------------------------------


class TestExecutionRecordsSupportedImportError:
    """Exercises the except ImportError branch by forcing the inner import to fail."""

    def setup_method(self):
        _reset_cache()

    def teardown_method(self):
        _reset_cache()

    def test_returns_false_when_cpex_framework_import_error(self):
        """Lines 51-52: ImportError branch sets cache to False and returns False."""
        saved = sys.modules.pop("cpex.framework", None)
        cpex_compat_mod._EXECUTION_RECORDS_SUPPORTED = None  # pylint: disable=protected-access
        try:
            original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__  # type: ignore[attr-defined]

            def _raise_on_cpex(name, *args, **kwargs):
                if name == "cpex.framework":
                    raise ImportError("simulated missing cpex")
                return original_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=_raise_on_cpex):
                result = cpex_compat_mod.execution_records_supported()

            assert result is False
            assert cpex_compat_mod._EXECUTION_RECORDS_SUPPORTED is False  # pylint: disable=protected-access
        finally:
            if saved is not None:
                sys.modules["cpex.framework"] = saved
            _reset_cache()


# ---------------------------------------------------------------------------
# get_executions
# ---------------------------------------------------------------------------


class TestGetExecutions:
    """Tests for get_executions()."""

    def test_returns_empty_on_none_result(self):
        """Returns [] when result is None."""
        assert get_executions(None) == []

    def test_returns_list_from_executions_field(self):
        """Returns a list copy of result.executions when present."""
        rec = MagicMock()
        result = MagicMock()
        result.executions = [rec]
        output = get_executions(result)
        assert output == [rec]

    def test_returns_empty_when_executions_field_absent(self):
        """Returns [] when the result object has no executions attribute."""
        result = MagicMock(spec=[])  # no 'executions' attr
        assert get_executions(result) == []

    def test_returns_empty_when_executions_is_none(self):
        """Returns [] when result.executions is None."""
        result = MagicMock()
        result.executions = None
        assert get_executions(result) == []

    def test_returns_empty_on_exception(self):
        """Returns [] without raising when getattr raises unexpectedly."""

        class Boom:
            @property
            def executions(self):
                raise RuntimeError("unexpected error")

        assert get_executions(Boom()) == []

    def test_returns_new_list_not_same_reference(self):
        """Always returns a new list, not the original executions list."""
        original = [MagicMock()]
        result = MagicMock()
        result.executions = original
        output = get_executions(result)
        assert output is not original
        assert output == original

    def test_returns_empty_list_when_executions_empty(self):
        """Returns [] when result.executions is an empty list."""
        result = MagicMock()
        result.executions = []
        assert get_executions(result) == []
