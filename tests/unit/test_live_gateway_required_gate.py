# -*- coding: utf-8 -*-
"""Location: ./tests/unit/test_live_gateway_required_gate.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for the ``LIVE_GATEWAY_REQUIRED`` gate in the live-gateway helpers.

A self-skipping suite reports success when nothing ran, so a Makefile target that
claims to prove live behavior can pass while testing nothing. These tests cover
the gate that turns that silent skip into a hard failure, and confirm the default
(skip-allowed) path is unchanged.

This file sits directly under ``tests/unit/`` rather than in the
``tests/unit/mcpgateway/`` source mirror because its subject is test
infrastructure, not a module of the gateway. It follows
``test_makefile_rust_targets.py``.

``tests.live_gateway.helpers.mcp_test_helpers`` probes ``GET /health`` at import
time, so it is imported inside each test rather than at module scope. A
module-level import would issue real HTTP requests during ``make test``
collection, which ``tests/AGENTS.md`` prohibits for unit tests.
"""

# Standard
import importlib
from unittest.mock import patch

# Third-Party
import pytest

HELPERS_MODULE = "tests.live_gateway.helpers.mcp_test_helpers"


def _helpers():
    """Import the live-gateway helpers lazily.

    Returns:
        module: The imported ``mcp_test_helpers`` module.
    """
    return importlib.import_module(HELPERS_MODULE)


class TestLiveGatewayRequiredFlag:
    """Parsing of the ``LIVE_GATEWAY_REQUIRED`` environment variable."""

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", " 1 ", "True"])
    def test_truthy_values_enable_requirement(self, value, monkeypatch):
        monkeypatch.setenv("LIVE_GATEWAY_REQUIRED", value)
        assert _helpers()._live_gateway_required() is True

    @pytest.mark.parametrize("value", ["0", "false", "no", "off", "", "   "])
    def test_falsy_values_leave_skipping_allowed(self, value, monkeypatch):
        monkeypatch.setenv("LIVE_GATEWAY_REQUIRED", value)
        assert _helpers()._live_gateway_required() is False

    def test_absent_variable_leaves_skipping_allowed(self, monkeypatch):
        monkeypatch.delenv("LIVE_GATEWAY_REQUIRED", raising=False)
        assert _helpers()._live_gateway_required() is False


class TestLiveGatewayRequirementError:
    """The policy decision behind the collection-time gate."""

    def test_required_and_unreachable_returns_message(self, monkeypatch):
        monkeypatch.setenv("LIVE_GATEWAY_REQUIRED", "1")
        helpers = _helpers()
        with patch.object(helpers, "_gateway_reachable", return_value=False):
            message = helpers.live_gateway_requirement_error()
        assert message is not None
        assert "LIVE_GATEWAY_REQUIRED is set but ContextForge is not reachable" in message

    def test_required_and_reachable_returns_none(self, monkeypatch):
        monkeypatch.setenv("LIVE_GATEWAY_REQUIRED", "1")
        helpers = _helpers()
        with patch.object(helpers, "_gateway_reachable", return_value=True):
            assert helpers.live_gateway_requirement_error() is None

    def test_not_required_and_unreachable_returns_none(self, monkeypatch):
        # The default path: an unreachable gateway still yields a skip, not an error.
        monkeypatch.delenv("LIVE_GATEWAY_REQUIRED", raising=False)
        helpers = _helpers()
        with patch.object(helpers, "_gateway_reachable", return_value=False):
            assert helpers.live_gateway_requirement_error() is None

    def test_not_required_skips_the_reachability_probe(self, monkeypatch):
        # Short-circuit check: the default path must not add an HTTP call, since
        # this helper is imported by every live suite at collection time.
        monkeypatch.delenv("LIVE_GATEWAY_REQUIRED", raising=False)
        helpers = _helpers()
        with patch.object(helpers, "_gateway_reachable") as probe:
            helpers.live_gateway_requirement_error()
        probe.assert_not_called()

    def test_message_names_the_remedy(self, monkeypatch):
        monkeypatch.setenv("LIVE_GATEWAY_REQUIRED", "1")
        helpers = _helpers()
        with patch.object(helpers, "_gateway_reachable", return_value=False):
            message = helpers.live_gateway_requirement_error()
        assert "make testing-up" in message
        assert "LIVE_GATEWAY_REQUIRED" in message


class TestMakefileWiring:
    """The target must set the variable, or the gate never engages."""

    @staticmethod
    def _target_body(target: str) -> str:
        """Return the recipe lines for *target* from the repository Makefile.

        Args:
            target: Makefile target name.

        Returns:
            str: The target's recipe body.
        """
        # Standard
        from pathlib import Path

        makefile = Path(__file__).resolve().parents[2] / "Makefile"
        lines = makefile.read_text(encoding="utf-8").splitlines()
        start = next(i for i, line in enumerate(lines) if line.startswith(f"{target}:"))
        body: list[str] = []
        for line in lines[start + 1 :]:
            if line and not line.startswith("\t") and not line.startswith(" "):
                break
            body.append(line)
        return "\n".join(body)

    def test_live_target_sets_required_flag(self):
        assert "LIVE_GATEWAY_REQUIRED=1" in self._target_body("test-private-key-jwt-live")

    def test_live_target_is_phony(self):
        # Standard
        from pathlib import Path

        makefile = Path(__file__).resolve().parents[2] / "Makefile"
        content = makefile.read_text(encoding="utf-8")
        phony_block = content.split(".PHONY: smoketest")[1].split("\n\n")[0]
        assert "test-private-key-jwt-live" in phony_block


class TestConftestFailureMechanism:
    """How the gate fails, not just whether it fails.

    A ``pytest_configure`` hook that raises a bare exception produces an
    INTERNALERROR traceback and exit code 3, which reads as a broken test rig
    rather than an unmet precondition. ``pytest.UsageError`` gives one actionable
    line and exit code 4.
    """

    @staticmethod
    def _conftest_source() -> str:
        """Return the live-gateway conftest source.

        Returns:
            str: File contents.
        """
        # Standard
        from pathlib import Path

        return (Path(__file__).resolve().parents[2] / "tests" / "live_gateway" / "conftest.py").read_text(encoding="utf-8")

    def test_gate_raises_usage_error(self):
        source = self._conftest_source()
        assert "pytest.UsageError" in source
        assert "raise RuntimeError" not in source

    def test_gate_delegates_to_single_policy_point(self):
        # The conftest chooses the failure mechanism; the helper owns the
        # decision. Re-deriving the env/reachability rule here would create a
        # second policy point that can disagree with the helper.
        source = self._conftest_source()
        assert "live_gateway_requirement_error" in source
        assert "LIVE_GATEWAY_REQUIRED" not in source.split('"""')[2]
