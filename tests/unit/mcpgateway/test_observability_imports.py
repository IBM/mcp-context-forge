# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_observability_imports.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Test optional tracing imports without changing process-wide OTEL modules.
"""

# Standard
import ast
import logging
from pathlib import Path
from types import SimpleNamespace

# Third-Party
import pytest


@pytest.mark.parametrize("missing", [None, "baggage", "core"])
def test_optional_import_capabilities(missing):
    """Keep core tracing available independently of baggage support."""
    source = Path("mcpgateway/observability.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    start = next(index for index, node in enumerate(tree.body) if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "OTEL_AVAILABLE" for target in node.targets))
    nodes = tree.body[start : start + 3]
    assert isinstance(nodes[-1], ast.Try)
    marker = type("SDKComponent", (), {})

    def controlled_import(name, globals=None, locals=None, fromlist=(), level=0):
        if missing == "core" and name == "opentelemetry.sdk.resources":
            raise ImportError("SDK unavailable")
        if missing == "baggage" and "baggage" in fromlist:
            raise ImportError("Baggage unavailable")
        if name == "sys":
            return SimpleNamespace(modules={})
        if name == "types":
            return __import__("types")
        return SimpleNamespace(**{symbol: marker for symbol in fromlist})

    namespace = {
        "__builtins__": {**vars(__import__("builtins")), "__import__": controlled_import},
        "logging": logging,
        "cast": lambda kind, value: value,
        "Any": object,
        "Dict": dict,
        "os": SimpleNamespace(getenv=lambda name: None),
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "mcpgateway/observability.py", "exec"), namespace)
    assert namespace["OTEL_AVAILABLE"] is (missing != "core")
    assert (namespace["otel_baggage"] is not None) is (missing is None)


@pytest.mark.parametrize("incomplete", [False, True])
def test_sdk_tests_skip_missing_dependencies(monkeypatch, incomplete):
    """Skip SDK tests for absent packages and incomplete SDK shim modules."""
    import builtins
    import runpy

    real_import = builtins.__import__

    def optional_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "opentelemetry.sdk.trace":
            if incomplete:
                return SimpleNamespace()
            raise ModuleNotFoundError("SDK unavailable")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", optional_import)
    with pytest.raises(pytest.skip.Exception, match="unavailable or incomplete"):
        runpy.run_path("tests/unit/mcpgateway/test_observability_trace_policy.py")
