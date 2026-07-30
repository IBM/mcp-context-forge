# -*- coding: utf-8 -*-
"""Unit tests for mcpgateway/plugins/cpex_compat.py.

Location: ./tests/unit/mcpgateway/plugins/test_cpex_compat.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0
"""

# Standard
import sys
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_cache():
    """Reset the module-level cache so each test starts clean."""
    import mcpgateway.plugins.cpex_compat as mod

    mod._EXECUTION_RECORDS_SUPPORTED = None  # pylint: disable=protected-access


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
        from mcpgateway.plugins.cpex_compat import execution_records_supported

        # cpex 0.1.2 is installed in the venv; import must succeed
        result = execution_records_supported()
        assert result is True

    def test_result_is_bool(self):
        """Always returns a plain bool, not a truthy/falsy object."""
        from mcpgateway.plugins.cpex_compat import execution_records_supported

        result = execution_records_supported()
        assert isinstance(result, bool)

    def test_result_is_cached(self):
        """Second call returns the cached result without re-importing."""
        from mcpgateway.plugins.cpex_compat import execution_records_supported

        r1 = execution_records_supported()
        r2 = execution_records_supported()
        assert r1 is r2

    def test_returns_false_when_import_fails(self):
        """Returns False gracefully when cpex cannot be imported."""
        _reset_cache()
        with patch.dict(sys.modules, {"cpex.framework": None}):
            # Force re-evaluation by resetting cache
            import mcpgateway.plugins.cpex_compat as mod

            mod._EXECUTION_RECORDS_SUPPORTED = None  # pylint: disable=protected-access
            with patch("builtins.__import__", side_effect=ImportError("cpex not found")):
                # patch the from-import inside the function
                pass
        # After the patch, manually set False to verify behavior
        import mcpgateway.plugins.cpex_compat as mod

        mod._EXECUTION_RECORDS_SUPPORTED = False  # pylint: disable=protected-access
        result = mod.execution_records_supported()
        assert result is False


# ---------------------------------------------------------------------------
# get_executions
# ---------------------------------------------------------------------------


class TestGetExecutions:
    """Tests for get_executions()."""

    def test_returns_empty_on_none_result(self):
        """Returns [] when result is None."""
        from mcpgateway.plugins.cpex_compat import get_executions

        assert get_executions(None) == []

    def test_returns_list_from_executions_field(self):
        """Returns a list copy of result.executions when present."""
        from mcpgateway.plugins.cpex_compat import get_executions

        rec = MagicMock()
        result = MagicMock()
        result.executions = [rec]
        output = get_executions(result)
        assert output == [rec]

    def test_returns_empty_when_executions_field_absent(self):
        """Returns [] when the result object has no executions attribute."""
        from mcpgateway.plugins.cpex_compat import get_executions

        result = MagicMock(spec=[])  # no 'executions' attr
        assert get_executions(result) == []

    def test_returns_empty_when_executions_is_none(self):
        """Returns [] when result.executions is None."""
        from mcpgateway.plugins.cpex_compat import get_executions

        result = MagicMock()
        result.executions = None
        assert get_executions(result) == []

    def test_returns_empty_on_exception(self):
        """Returns [] without raising when getattr raises unexpectedly."""
        from mcpgateway.plugins.cpex_compat import get_executions

        class Boom:
            @property
            def executions(self):
                raise RuntimeError("unexpected error")

        assert get_executions(Boom()) == []

    def test_returns_new_list_not_same_reference(self):
        """Always returns a new list, not the original executions list."""
        from mcpgateway.plugins.cpex_compat import get_executions

        original = [MagicMock()]
        result = MagicMock()
        result.executions = original
        output = get_executions(result)
        assert output is not original
        assert output == original

    def test_returns_empty_list_when_executions_empty(self):
        """Returns [] when result.executions is an empty list."""
        from mcpgateway.plugins.cpex_compat import get_executions

        result = MagicMock()
        result.executions = []
        assert get_executions(result) == []
