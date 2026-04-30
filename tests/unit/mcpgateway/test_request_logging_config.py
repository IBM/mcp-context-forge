# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_request_logging_config.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Configuration tests for request-logging Rust integration.
"""

from mcpgateway.config import Settings


def test_request_logging_uses_single_pyo3_flag(monkeypatch):
    """The request-logging Rust integration should be controlled by one PyO3 flag."""
    monkeypatch.setenv("EXPERIMENTAL_RUST_REQUEST_LOGGING_MASKING_ENABLED", "true")

    settings = Settings(_env_file=None)

    assert settings.experimental_rust_request_logging_masking_enabled is True
