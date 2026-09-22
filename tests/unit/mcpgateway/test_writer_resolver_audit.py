# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_writer_resolver_audit.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

AST audit for #5893: every UserRole/EmailTeamMember construction site under
mcpgateway/services must dual-write: resolve the canonical user ID through
the shared resolver resolve_canonical_user_id in the enclosing function,
store it via a user_id= keyword, and keep user_email= on the e-mail form
(never the resolver output) so the FK to email_users.email stays valid.
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


def _keyword_value(node: ast.Call, name: str):
    """Return the AST value of a keyword argument, or None when absent."""
    for keyword in node.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _resolver_target_name(function_node) -> str:
    """Return the variable assigned from resolve_canonical_user_id, or ''."""
    for node in ast.walk(function_node):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        if _call_constructor_name(node.value) != RESOLVER_NAME:
            continue
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            return node.targets[0].id
    return ""


def _construction_sites():
    """Yield (path, line, constructor, call_node, function_node) for each audited construction."""
    for path in sorted(SERVICES_DIR.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for child in ast.walk(node):
                if isinstance(child, ast.Call) and _call_constructor_name(child) in AUDITED_CONSTRUCTORS:
                    yield path, child.lineno, _call_constructor_name(child), child, node


def test_every_writer_site_dual_writes():
    """Every UserRole/EmailTeamMember construction resolves the canonical ID and dual-writes it."""
    violations = []
    for path, lineno, constructor, call_node, function_node in _construction_sites():
        site = f"{path.name}:{lineno} ({constructor})"
        if site in ALLOWLIST:
            continue
        resolver_target = _resolver_target_name(function_node)
        if not resolver_target:
            violations.append(f"{site}: enclosing function never calls {RESOLVER_NAME}")
            continue
        user_email_value = _keyword_value(call_node, "user_email")
        if user_email_value is None:
            violations.append(f"{site}: missing user_email= keyword")
        elif isinstance(user_email_value, ast.Name) and user_email_value.id == resolver_target:
            violations.append(f"{site}: user_email={resolver_target} stores the resolver output in the FK column; store the e-mail form")
        if _keyword_value(call_node, "user_id") is None:
            violations.append(f"{site}: missing user_id= keyword (dual-write requires the canonical ID alongside user_email)")

    assert not violations, f"Writer sites violating the dual-write rule: {violations}"


def test_writer_enumeration_is_exact():
    """The audited enumeration stays exact: one UserRole site, four EmailTeamMember sites."""
    counts = {name: 0 for name in AUDITED_CONSTRUCTORS}
    for _path, _lineno, constructor, _call_node, _function_node in _construction_sites():
        counts[constructor] += 1

    assert counts == {"UserRole": 1, "EmailTeamMember": 4}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
