# -*- coding: utf-8 -*-
"""Startup-time deprecation warning for EXPERIMENTAL_RUST_A2A_RUNTIME_ENABLED (Plan T23).

Location: ./tests/unit/mcpgateway/test_main_rust_a2a_deprecation.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

Plan T23 introduces a lifespan-time ``logger.warning(...)`` so any
operator who still has ``EXPERIMENTAL_RUST_A2A_RUNTIME_ENABLED=true``
in their environment sees a clear deprecation notice on every
gateway start. The Python dispatcher (T4 + T5) is the only execution
path post-Wave 6; the flag has no effect.

The test exercises the helper directly rather than spinning up the
full ``lifespan`` context manager. The helper is small and pure (no
I/O, no async), so direct invocation gives the same signal with an
order of magnitude less fixture cost.
"""

from __future__ import annotations

import logging

import pytest

from mcpgateway import config as config_module
from mcpgateway.main import _warn_if_rust_a2a_runtime_deprecated


@pytest.fixture
def restore_rust_flag(monkeypatch):
    """Snapshot + restore the experimental_rust_a2a_runtime_enabled flag.

    The settings object is process-wide; without restore, a True value
    set in one test would leak into others and trigger unrelated
    warnings.
    """
    original = config_module.settings.experimental_rust_a2a_runtime_enabled
    yield
    monkeypatch.setattr(config_module.settings, "experimental_rust_a2a_runtime_enabled", original)


def test_warn_when_rust_a2a_runtime_flag_enabled(monkeypatch, caplog, restore_rust_flag):
    """Helper emits a single WARNING log entry when the flag is True."""
    monkeypatch.setattr(config_module.settings, "experimental_rust_a2a_runtime_enabled", True)

    with caplog.at_level(logging.WARNING, logger="mcpgateway.main"):
        _warn_if_rust_a2a_runtime_deprecated()

    matching = [record for record in caplog.records if record.levelno == logging.WARNING and "EXPERIMENTAL_RUST_A2A_RUNTIME_ENABLED" in record.getMessage()]
    assert len(matching) == 1, f"expected exactly one deprecation warning, got: " f"{[r.getMessage() for r in caplog.records]}"
    message = matching[0].getMessage()
    assert "DEPRECATED" in message
    assert "Python dispatcher" in message
    assert "flag is now ignored" in message


def test_no_warning_when_rust_a2a_runtime_flag_disabled(monkeypatch, caplog, restore_rust_flag):
    """Helper is a no-op when the flag is False (the default secure state)."""
    monkeypatch.setattr(config_module.settings, "experimental_rust_a2a_runtime_enabled", False)

    with caplog.at_level(logging.WARNING, logger="mcpgateway.main"):
        _warn_if_rust_a2a_runtime_deprecated()

    matching = [record for record in caplog.records if "EXPERIMENTAL_RUST_A2A_RUNTIME_ENABLED" in record.getMessage()]
    assert matching == [], f"expected no deprecation warning when flag is False, got: " f"{[r.getMessage() for r in matching]}"
