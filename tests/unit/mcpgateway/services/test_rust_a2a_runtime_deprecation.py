# -*- coding: utf-8 -*-
"""Import-time DeprecationWarning for the Rust A2A runtime module (Plan T27).

Location: ./tests/unit/mcpgateway/services/test_rust_a2a_runtime_deprecation.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

Plan T27 (Wave 6 full-system smoke) closes the verified DeprecationWarning
contract introduced by T26: importing ``mcpgateway.services.rust_a2a_runtime``
must emit exactly one ``DeprecationWarning`` so any consumer still relying on
the symbol receives a clear migration signal before the release N+1 physical
removal.

This is a different concern from T23's startup ``logger.warning`` (which fires
conditionally at lifespan time when the env var is True). T27 here fires
UNCONDITIONALLY at import time, including in deployments that never set the
flag — that's the load-bearing guarantee operators get a warned release
regardless of their config.
"""

from __future__ import annotations

import importlib
import sys
import warnings

import pytest


@pytest.fixture
def reimport_rust_a2a_runtime():
    """Drop the cached module so a fresh import re-fires the warning.

    ``warnings.warn`` at module level only fires the FIRST time the module is
    imported in a Python process. The full test suite always sees the warning
    because the test runner imports things in dependency order, but THIS test
    needs to assert the warning fires on a CLEAN import, so we drop the cached
    module entry and restore it after the test.
    """
    module_key = "mcpgateway.services.rust_a2a_runtime"
    saved = sys.modules.pop(module_key, None)
    yield
    if saved is not None:
        sys.modules[module_key] = saved


def test_import_emits_deprecation_warning_exactly_once(reimport_rust_a2a_runtime):  # pylint: disable=unused-argument
    """Importing ``rust_a2a_runtime`` emits one DeprecationWarning with the migration message.

    Pins the T26 contract that an import-time deprecation must be visible to
    any code that loads the module, including code that never instantiates
    the client. ``warnings.catch_warnings`` records every warning so this
    test stays accurate even when other warnings (Pydantic v2 migration, etc.)
    fire during the same import.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")

        importlib.import_module("mcpgateway.services.rust_a2a_runtime")

    rust_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning) and "rust_a2a_runtime" in str(w.message)]

    assert len(rust_warnings) == 1, f"expected exactly one DeprecationWarning mentioning rust_a2a_runtime, " f"got: {[str(w.message) for w in rust_warnings]}"
    message = str(rust_warnings[0].message)
    assert "DEPRECATED" in message
    assert "release N+1" in message
    assert "a2a_service" in message
    assert "plans/a2a-native-passthrough.md" in message
