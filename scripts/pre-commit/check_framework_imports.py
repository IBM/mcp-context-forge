#!/usr/bin/env python3
"""Pre-commit hook: enforce plugin framework import isolation.

The plugin framework (``mcpgateway/plugins/framework/``) must not import from
``mcpgateway.common`` or ``mcpgateway.utils`` to maintain a clean dependency
boundary.

Exit codes:
    0 - no violations found
    1 - violations detected (printed to stderr)

Usage::

    python3 scripts/pre-commit/check_framework_imports.py
    python3 scripts/pre-commit/check_framework_imports.py mcpgateway/plugins/framework/manager.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

FRAMEWORK_DIR = Path("mcpgateway/plugins/framework")
FORBIDDEN_PREFIXES = ("mcpgateway.common", "mcpgateway.utils")


def _check_file(file_path: Path) -> list[str]:
    """Return ``file:line -> module`` violation strings for *file_path*."""
    try:
        source = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError:
        return []

    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(FORBIDDEN_PREFIXES):
            violations.append(f"{file_path}:{node.lineno} -> {node.module}")

    return violations


def main() -> int:
    """Entry point."""
    if len(sys.argv) > 1:
        files = [Path(p) for p in sys.argv[1:] if Path(p).suffix == ".py"]
    else:
        files = list(FRAMEWORK_DIR.rglob("*.py"))

    violations: list[str] = []
    for f in files:
        violations.extend(_check_file(f))

    if violations:
        print("Plugin framework imports from gateway internals:", file=sys.stderr)
        for v in sorted(violations):
            print(f"  {v}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
