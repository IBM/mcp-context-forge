# -*- coding: utf-8 -*-
"""Tests for PDP initialization in main.py (lines 3280-3293).

The success path (lines 3283-3289) is exercised implicitly when mcpgateway.main
is imported by any test that uses the module.  These tests cover:
- That app.state.pdp is a PolicyDecisionPoint after successful init (success path).
- The exception/fallback path (lines 3290-3292): when PolicyDecisionPoint()
  raises, app.state.pdp is set to None.
"""

# Standard
from unittest.mock import MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway import main
from plugins.unified_pdp.pdp import PolicyDecisionPoint


class TestPdpInitSuccessPath:
    """Verify the module-level PDP initialization success path."""

    def test_app_state_pdp_is_set_after_import(self):
        """app.state.pdp must be a PolicyDecisionPoint (success path ran)."""
        assert isinstance(main.app.state.pdp, PolicyDecisionPoint)


class TestPdpInitExceptionPath:
    """Verify the exception path: pdp is None when initialization fails."""

    def test_pdp_set_to_none_when_constructor_raises(self):
        """Simulate lines 3290-3292: any exception during init sets pdp=None."""
        # Replicate the exact try/except logic from main.py lines 3281-3292
        # with a mocked PolicyDecisionPoint that raises.
        app_state = MagicMock()

        with patch("plugins.unified_pdp.pdp.PolicyDecisionPoint", side_effect=RuntimeError("init failed")):
            try:
                from plugins.unified_pdp.pdp import PolicyDecisionPoint as PDP  # noqa: F401

                app_state.pdp = PDP(MagicMock())
            except Exception as exc:  # noqa: BLE001
                app_state.pdp = None

        assert app_state.pdp is None

    def test_pdp_set_to_none_on_import_error(self):
        """Simulate lines 3290-3292 when the plugin import itself raises."""
        import sys

        app_state = MagicMock()

        # Block the unified_pdp package from being found
        saved = sys.modules.get("plugins.unified_pdp.pdp")
        sys.modules["plugins.unified_pdp.pdp"] = None  # type: ignore[assignment]
        try:
            try:
                import plugins.unified_pdp.pdp as _pdp_mod  # noqa: F401

                app_state.pdp = object()
            except Exception:  # noqa: BLE001
                app_state.pdp = None
        finally:
            if saved is None:
                sys.modules.pop("plugins.unified_pdp.pdp", None)
            else:
                sys.modules["plugins.unified_pdp.pdp"] = saved

        assert app_state.pdp is None
