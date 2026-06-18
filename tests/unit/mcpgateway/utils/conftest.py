# -*- coding: utf-8 -*-
# Copyright (c) 2025 ContextForge Contributors.
# SPDX-License-Identifier: Apache-2.0

"""Location: ./tests/unit/mcpgateway/utils/conftest.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Shared fixtures for mcpgateway.utils unit tests.

The passthrough-headers tests patch ``mcpgateway.utils.passthrough_headers.settings``
(the module-level reference), but ``global_config_cache.get_passthrough_headers()``
does its own ``from mcpgateway.config import settings`` import, reading the *real*
settings object.  Environment variables such as ``PASSTHROUGH_HEADERS_SOURCE`` or
``ENABLE_HEADER_PASSTHROUGH`` can therefore leak into the tests and cause spurious
failures.

The fixture below pins the real ``mcpgateway.config.settings`` attributes that the
cache reads to their documented defaults so the tests are fully isolated from the
host environment.
"""

# Future
from __future__ import annotations

# Third-Party
import pytest

# Shared test constants for header filtering tests
# These reduce duplication across test files and ensure consistent test data

# Sensitive headers that should be filtered by default
SENSITIVE_HEADERS = {  # pragma: allowlist secret
    "authorization": "Bearer token123",  # pragma: allowlist secret
    "x-api-key": "secret-key-456",  # pragma: allowlist secret
    "cookie": "session=abc123",  # pragma: allowlist secret
}

# Non-sensitive headers that should pass through
SAFE_HEADERS = {
    "x-tenant-id": "acme",
    "x-trace-id": "trace-123",
    "content-type": "application/json",
}

# Common whitelists for testing
WHITELIST_WITH_SENSITIVE = ["Authorization", "X-Tenant-ID", "X-API-Key"]
WHITELIST_SAFE_ONLY = ["X-Tenant-ID", "X-Trace-ID", "Content-Type"]


@pytest.fixture(autouse=True)
def _isolate_passthrough_settings(monkeypatch):
    """Pin environment-sensitive settings to their defaults for every test.

    This ensures ``global_config_cache`` (which imports ``settings`` directly
    from ``mcpgateway.config``) sees deterministic values regardless of the
    caller's shell environment.
    """
    # First-Party
    from mcpgateway.config import settings  # pylint: disable=import-outside-toplevel

    monkeypatch.setattr(settings, "passthrough_headers_source", "db")
    monkeypatch.setattr(settings, "enable_header_passthrough", False)
    monkeypatch.setattr(settings, "enable_overwrite_base_headers", False)
    monkeypatch.setattr(settings, "default_passthrough_headers", [])
