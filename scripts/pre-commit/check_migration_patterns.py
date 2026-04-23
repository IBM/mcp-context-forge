#!/usr/bin/env python3
"""Pre-commit hook: verify Alembic revision-chain integrity.

Enforces only cross-file integrity — the invariants that break Alembic
silently when violated and that a reviewer cannot catch by reading a
single migration diff:

- Filename follows ``<12-char-alphanumeric>_<description>.py``
- The ``revision = "..."`` string inside the file matches the filename prefix
- No duplicate revision IDs across the ``versions/`` directory

Stylistic rules (``timezone=True``, ``sa.false()`` vs ``"0"``, balanced
``op.create_index``/``op.drop_index`` counts, dialect branching) are
intentionally NOT enforced here — they belong in code review or a linter.

Invocation modes
================

* With filename arguments (pre-commit default): per-file naming/revision
  checks run on the supplied files. The duplicate-revision scan still
  traverses every migration but only *reports* conflicts involving a
  changed file — pre-existing duplicate drift is out of scope.
* With no arguments: full sweep. Used by ``pre-commit run --all-files``.

Exit codes:
    0 - all checks pass
    1 - violations detected (printed to stderr)
"""

from __future__ import annotations

from pathlib import Path
import re
import sys
from typing import Iterable, List, Optional, Set

REPO_ROOT = Path(__file__).resolve().parents[2]
VERSIONS_DIR = REPO_ROOT / "mcpgateway" / "alembic" / "versions"
FILENAME_RE = re.compile(r"^([0-9a-z]{12})_\w+\.py$")
REVISION_RE = re.compile(r'^revision(?::\s*str)?\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)


def _migration_files(paths: Iterable[Path]) -> List[Path]:
    keep: List[Path] = []
    for p in paths:
        if not p.exists() or p.name == "__init__.py" or p.suffix != ".py":
            continue
        try:
            p.resolve().relative_to(VERSIONS_DIR.resolve())
        except ValueError:
            continue
        keep.append(p)
    return keep


def _read(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _check_naming(files: Iterable[Path]) -> list[str]:
    violations: list[str] = []
    for py_file in sorted(files):
        match = FILENAME_RE.match(py_file.name)
        if not match:
            violations.append(f"{py_file.name}: filename must match <12-char-alphanumeric>_<description>.py")
            continue
        content = _read(py_file)
        if content is None:
            continue
        rev_match = REVISION_RE.search(content)
        if not rev_match:
            violations.append(f"{py_file.name}: cannot find revision string in file")
            continue
        if rev_match.group(1) != match.group(1):
            violations.append(f"{py_file.name}: revision '{rev_match.group(1)}' does not match filename hash '{match.group(1)}'")
    return violations


def _check_duplicate_revisions(changed_names: Optional[Set[str]]) -> list[str]:
    violations: list[str] = []
    if not VERSIONS_DIR.exists():
        return violations

    seen: dict[str, str] = {}
    for py_file in sorted(VERSIONS_DIR.glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        content = _read(py_file)
        if content is None:
            continue
        m = REVISION_RE.search(content)
        if not m:
            continue
        revision = m.group(1)
        if revision in seen:
            first, second = seen[revision], py_file.name
            if changed_names is None or first in changed_names or second in changed_names:
                violations.append(f"{second}: duplicate revision '{revision}' (also in {first})")
        else:
            seen[revision] = py_file.name
    return violations


def main(argv: list[str]) -> int:
    if not VERSIONS_DIR.exists():
        return 0

    if argv:
        supplied = [Path(a) if Path(a).is_absolute() else REPO_ROOT / a for a in argv]
        files = _migration_files(supplied)
        if not files:
            return 0
        changed_names: Optional[Set[str]] = {p.name for p in files}
    else:
        files = []
        changed_names = None

    violations: list[str] = []
    # Naming/revision-consistency only applies to changed files. Pre-existing
    # non-conforming legacy migrations in the repo are not this commit's concern.
    violations.extend(_check_naming(files))
    # Duplicate-revision detection always scans the full tree so new files
    # can't collide with old ones.
    violations.extend(_check_duplicate_revisions(changed_names))

    if violations:
        print("Migration pattern violations:", file=sys.stderr)
        for v in sorted(violations):
            print(f"  {v}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
