# -*- coding: utf-8 -*-
"""Pytest configuration for differential A2A benchmarks.

Location: benchmarks/differential/conftest.py
Runs before test collection so LOG_LEVEL and sys.path are set before imports.
Copyright 2026
SPDX-License-Identifier: Apache-2.0
"""

# Standard
import os
import sys

# Set LOG_LEVEL before any mcpgateway imports to reduce benchmark noise
os.environ.setdefault("LOG_LEVEL", "CRITICAL")

# Ensure project root is on path for mcpgateway and mcpgateway_rust imports
_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _root not in sys.path:
    sys.path.insert(0, _root)


def pytest_configure(config):
    """Set lenient benchmark calibration for I/O-heavy tests (avoids stuck calibration)."""
    if hasattr(config.option, "benchmark_calibration_precision"):
        config.option.benchmark_calibration_precision = 100
