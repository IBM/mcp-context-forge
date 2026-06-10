# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/test_cpex_migration_paths.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Regression tests for paths migrated from the in-repo plugin framework.
"""

from __future__ import annotations


def test_external_plugin_runtime_import_resolves_from_cpex() -> None:
    """External MCP runtime must be importable from the packaged CPEX path."""
    # First-Party
    from cpex.framework.external.mcp.server import runtime

    assert runtime.__file__
