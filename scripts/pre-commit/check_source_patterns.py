#!/usr/bin/env python3
"""Pre-commit hook: verify cross-module source code patterns.

Checks that:
- Cancellation router conditional registration code exists in main.py
- A2A agent registration commits agent before tool creation

Exit codes:
    0 - all checks pass
    1 - violations detected (printed to stderr)
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _extract_function_source(file_source: str, func_name: str) -> str | None:
    """Extract the source text of a function/method by name from a file."""
    try:
        tree = ast.parse(file_source)
    except SyntaxError:
        return None

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            lines = file_source.splitlines()
            return "\n".join(lines[node.lineno - 1 : node.end_lineno])

    return None


def _check_cancellation_router() -> list[str]:
    """Verify conditional cancellation router registration exists in main.py."""
    violations: list[str] = []
    main_py = REPO_ROOT / "mcpgateway" / "main.py"

    if not main_py.exists():
        return ["mcpgateway/main.py not found"]

    source = main_py.read_text(encoding="utf-8")

    expected_patterns = [
        "if settings.mcpgateway_tool_cancellation_enabled:",
        "app.include_router(cancellation_router)",
        "Cancellation router included",
    ]

    for pattern in expected_patterns:
        if pattern not in source:
            violations.append(f"main.py: missing cancellation router pattern: {pattern}")

    return violations


def _check_a2a_registration_order() -> list[str]:
    """Verify A2A agent registration commits before tool creation."""
    violations: list[str] = []
    a2a_service_path = REPO_ROOT / "mcpgateway" / "services" / "a2a_service.py"

    if not a2a_service_path.exists():
        return []

    file_source = a2a_service_path.read_text(encoding="utf-8")
    source = _extract_function_source(file_source, "register_agent")
    if source is None:
        return []

    required = ["db.add(new_agent)", "db.commit()", "create_tool_from_a2a_agent"]
    for pattern in required:
        if pattern not in source:
            violations.append(f"a2a_service.py:register_agent: missing pattern: {pattern}")
            return violations

    positions = [source.find(p) for p in required]
    if not (positions[0] < positions[1] < positions[2]):
        violations.append("a2a_service.py:register_agent: db.add → db.commit → create_tool_from_a2a_agent ordering violation")

    return violations


def main() -> int:
    violations: list[str] = []
    violations.extend(_check_cancellation_router())
    violations.extend(_check_a2a_registration_order())

    if violations:
        print("Source pattern violations:", file=sys.stderr)
        for v in sorted(violations):
            print(f"  {v}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
