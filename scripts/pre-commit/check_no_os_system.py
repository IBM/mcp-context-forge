#!/usr/bin/env python3
"""Pre-commit hook: ensure run_mutmut.py does not use os / os.system.

``run_mutmut.py`` must use ``shutil.rmtree`` for directory cleanup, never
``os.system``.  This hook enforces that the ``os`` module is not imported and
no ``os.system()`` calls appear in the file.

Exit codes:
    0 - no violations found
    1 - violations detected (printed to stderr)

Usage::

    python3 scripts/pre-commit/check_no_os_system.py run_mutmut.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path


def _check_file(file_path: Path) -> list[str]:
    """Return violation strings for *file_path*."""
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
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "os" or alias.name.startswith("os."):
                    violations.append(f"{file_path}:{node.lineno}: imports os module")
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "os" or node.module.startswith("os."):
                violations.append(f"{file_path}:{node.lineno}: imports from os module")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "os" and node.func.attr == "system":
                violations.append(f"{file_path}:{node.lineno}: os.system() call")

    return violations


def main() -> int:
    """Entry point."""
    if len(sys.argv) > 1:
        files = [Path(p) for p in sys.argv[1:] if Path(p).suffix == ".py"]
    else:
        target = Path("run_mutmut.py")
        files = [target] if target.exists() else []

    violations: list[str] = []
    for f in files:
        violations.extend(_check_file(f))

    if violations:
        print("Forbidden os module usage detected:", file=sys.stderr)
        for v in sorted(violations):
            print(f"  {v}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
