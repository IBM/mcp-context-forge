#!/usr/bin/env python3
"""Pre-commit hook: reject machine-specific home directory paths.

Scans files for hardcoded home-directory paths that should never appear in the
repository.

Exit codes:
    0 - no violations found
    1 - violations detected (printed to stderr)

Usage::

    python3 scripts/pre-commit/check_machine_paths.py
    python3 scripts/pre-commit/check_machine_paths.py file1.py file2.yaml
"""

from __future__ import annotations

import sys
from pathlib import Path

FORBIDDEN_PATHS = [
    "/home/cmihai",
]

SKIP_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".pyc", ".woff", ".woff2", ".ttf", ".eot"}


SELF = Path(__file__).resolve()


def _check_file(file_path: Path) -> list[str]:
    """Return violation strings for *file_path*."""
    if file_path.resolve() == SELF:
        return []
    if file_path.suffix.lower() in SKIP_EXTENSIONS:
        return []
    if ".git" in file_path.parts:
        return []

    try:
        content = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    violations: list[str] = []
    for forbidden in FORBIDDEN_PATHS:
        if forbidden in content:
            violations.append(f"{file_path}: contains '{forbidden}'")

    return violations


def main() -> int:
    """Entry point."""
    if len(sys.argv) > 1:
        files = [Path(p) for p in sys.argv[1:] if Path(p).is_file()]
    else:
        repo_root = Path(__file__).resolve().parents[2]
        files = [p for p in repo_root.rglob("*") if p.is_file()]

    violations: list[str] = []
    for f in files:
        violations.extend(_check_file(f))

    if violations:
        print("Machine-specific paths found:", file=sys.stderr)
        for v in sorted(violations):
            print(f"  {v}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
