#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Forbid sunset markers in the codebase.

Location: ./.github/tools/check_sunset_markers.py
Copyright contributors to the mcp-context-forge project
SPDX-License-Identifier: Apache-2.0

A sunset marker is a code comment of the form:

    # [#NNNN] remove after ...
    # [#NNNN] Code to be removed after ...

No sunset markers are allowed in committed code regardless of the stated
deadline date.  Deprecated code must be removed before merging, not
scheduled for removal via a time-bomb comment.  This hook fails on any
match so that expiry-based CI failures can never happen.

Examples:
    Run from the repository root:
        >>> import subprocess, sys
        >>> result = subprocess.run([sys.executable, ".github/tools/check_sunset_markers.py"], capture_output=True)
        >>> result.returncode in (0, 1)
        True
"""

# Standard
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Matches the marker regardless of the date that follows, e.g.:
#   [#2754] remove after Sun, 01 Nov 2026 23:59:59 UTC
#   [#2754] Code to be removed after Sun, 01 Nov 2026 23:59:59 UTC
SUNSET_PATTERN = re.compile(
    r"\[#\d+\]\s+(?:remove|Code to be removed)\s+after\b",
    re.IGNORECASE,
)

# Directories that are never part of the production source scan.
SKIP_DIR_PREFIXES = (".", "node_modules", "__pycache__", "build", "dist")


def _should_skip(path: Path) -> bool:
    """Return True if *path* lives inside a directory that should be ignored.

    Args:
        path: File path to evaluate.

    Returns:
        bool: True when the path should be skipped.
    """
    return any(part.startswith(prefix) for part in path.parts for prefix in SKIP_DIR_PREFIXES)


def scan(root: Path) -> list[tuple[Path, int]]:
    """Walk *root* recursively and collect every sunset marker location.

    Args:
        root: Repository root to scan from.

    Returns:
        list[tuple[Path, int]]: Each element is (file, 1-based line number).
    """
    found: list[tuple[Path, int]] = []

    for path in sorted(root.rglob("*.py")):
        if _should_skip(path):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        for match in SUNSET_PATTERN.finditer(text):
            line_no = text[: match.start()].count("\n") + 1
            found.append((path, line_no))

    return found


def main() -> int:
    """Entry point for the pre-commit hook.

    Returns:
        int: 0 when no sunset markers are found, 1 otherwise.
    """
    root = Path(".")
    found = scan(root)

    if not found:
        return 0

    print("ERROR: Sunset markers are not allowed — remove the deprecated code before committing:")
    for path, line_no in found:
        print(f"  {path}:{line_no}")

    return 1


if __name__ == "__main__":
    sys.exit(main())
