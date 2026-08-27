# -*- coding: utf-8 -*-
"""Location: ./tests/unit/loadtest/test_locustfile_spin_detector.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Regression tests for the Fast Time users in the spin-detector Locust file.
"""

# Standard
import os

# Belt and braces: avoid gevent monkey-patching during unit-test imports.
os.environ.setdefault("LOCUST_SKIP_MONKEY_PATCH", "1")

# First-Party
from tests.loadtest import locustfile_spin_detector as spin  # noqa: E402


def test_fast_time_user_includes_echo_task():
    """The spin detector keeps coverage for the required-argument echo tool."""
    assert hasattr(spin.FastTimeUser, "call_echo")
    assert getattr(spin.FastTimeUser.call_echo, "locust_task_weight", None) == 3
