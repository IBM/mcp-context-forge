# -*- coding: utf-8 -*-
# Copyright (c) 2025 ContextForge Contributors.
# SPDX-License-Identifier: Apache-2.0

"""Shared fixtures for mcpgateway.utils unit tests.

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
