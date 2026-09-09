# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_writer_resolver_audit.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

AST audit for #5893: every UserRole/EmailTeamMember construction site under
mcpgateway/services must resolve the canonical user ID through the shared
resolver resolve_canonical_user_id in the enclosing function.
"""

# Standard
import ast
from pathlib import Path

# Third-Party
import pytest

SERVICES_DIR = Path(__file__).resolve().parents[3] / "mcpgateway" / "services"
AUDITED_CONSTRUCTORS = {"UserRole", "EmailTeamMember"}
RESOLVER_NAME = "resolve_canonical_user_id"
ALLOWLIST: set = set()  # Zero exceptions permitted: every site must resolve.


def _call_constructor_name(node: ast.Call) -> str:
    """Return the constructor name for a Call node, or an empty string."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _construction_sites():
    """Yield (path, line, constructor, enclosing_function_source) for each audited construction."""
    for path in sorted(SERVICES_DIR.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for child in ast.walk(node):
                if isinstance(child, ast.Call) and _call_constructor_name(child) in AUDITED_CONSTRUCTORS:
                    function_source = ast.get_source_segment(source, node) or ""
                    yield path, child.lineno, _call_constructor_name(child), function_source


def test_every_writer_site_calls_shared_resolver():
    """Every UserRole/EmailTeamMember construction resolves the canonical user ID."""
    violations = []
    for path, lineno, constructor, function_source in _construction_sites():
        site = f"{path.name}:{lineno} ({constructor})"
        if site in ALLOWLIST:
            continue
        if RESOLVER_NAME not in function_source:
            violations.append(site)

    assert not violations, f"Writer sites missing {RESOLVER_NAME}: {violations}"


def test_writer_enumeration_is_exact():
    """The audited enumeration stays exact: one UserRole site, four EmailTeamMember sites."""
    counts = {name: 0 for name in AUDITED_CONSTRUCTORS}
    for _path, _lineno, constructor, _function_source in _construction_sites():
        counts[constructor] += 1

    assert counts == {"UserRole": 1, "EmailTeamMember": 4}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
