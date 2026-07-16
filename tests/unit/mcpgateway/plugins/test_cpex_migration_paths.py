# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/test_cpex_migration_paths.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Regression tests for paths migrated from the in-repo plugin framework.
"""

from __future__ import annotations


def test_external_plugin_runtime_import_resolves_from_cpex() -> None:
    """External MCP runtime must be importable from the packaged CPEX path."""
    # First-Party
    from cpex.framework.external.mcp.server import runtime

    assert runtime.__file__
