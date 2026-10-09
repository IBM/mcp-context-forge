# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/conftest.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Collection-time gate for the live-gateway suites.

Every suite under ``tests/live_gateway/`` self-skips when the gateway is
unreachable, which is right for an opportunistic local run but means a target
that claims to prove live behavior can report success having executed nothing.

Makefile targets that make that claim set ``LIVE_GATEWAY_REQUIRED=1``. This hook
turns an unreachable gateway into a hard error in that mode, so an all-skipped
run cannot be mistaken for a passing one.

The decision itself lives in ``live_gateway_requirement_error()`` so there is one
policy point; this module only chooses how to fail. Keeping it out of helper
import time also leaves the helpers side-effect free for the unit tests that
exercise the gate.
"""

# Future
from __future__ import annotations

# Third-Party
import pytest

# Local
from tests.live_gateway.helpers.mcp_test_helpers import live_gateway_requirement_error


def pytest_configure(config: pytest.Config) -> None:
    """Fail fast when a required live gateway is unreachable.

    Args:
        config: The pytest config object (unused; required by the hook signature).

    Raises:
        pytest.UsageError: If ``LIVE_GATEWAY_REQUIRED`` is set and the gateway is
            unreachable. ``UsageError`` keeps the output to one actionable line
            and exits with code 4, rather than an INTERNALERROR traceback.
    """
    del config  # unused; the hook signature requires it
    message = live_gateway_requirement_error()
    if message:
        raise pytest.UsageError(message)
