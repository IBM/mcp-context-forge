#!/usr/bin/env python3
"""Pre-commit hook: verify Alembic revision-chain integrity.

Enforces only cross-file integrity — the invariants that break Alembic
silently when violated and that a reviewer cannot catch by reading a
single migration diff:

- Filename follows ``<12-char-alphanumeric>_<description>.py``
- The ``revision = "..."`` string inside the file matches the filename prefix
- No duplicate revision IDs across the ``versions/`` directory
- The revision graph has exactly one head (no stranded branches)

Stylistic rules (``timezone=True``, ``sa.false()`` vs ``"0"``, balanced
``op.create_index``/``op.drop_index`` counts, dialect branching) are
intentionally NOT enforced here — they belong in code review or a linter.

Invocation modes
================

* With filename arguments (pre-commit default): per-file naming/revision
  checks run on the supplied files. The duplicate-revision and single-head
  scans always traverse every migration; duplicates only *report* conflicts
  involving a changed file, while the single-head check is global because
  any new file can introduce a stranded branch even if it parses cleanly.
* With no arguments: full sweep. Used by ``pre-commit run --all-files``.

Exit codes:
    0 - all checks pass
    1 - violations detected (printed to stderr)
"""

from __future__ import annotations

import ast
from pathlib import Path
import re
import sys
from typing import Any, Iterable, List, Optional, Set, Tuple, Union

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


DownRevision = Union[None, str, Tuple[Any, ...], List[Any]]


def _parse_revision_metadata(path: Path) -> Tuple[Optional[str], DownRevision, bool]:
    content = _read(path)
    if content is None:
        return None, None, False
    try:
        tree = ast.parse(content, filename=str(path))
    except SyntaxError:
        return None, None, False

    revision: Optional[str] = None
    down_revision: DownRevision = None
    saw_down = False

    for node in tree.body:
        target_name: Optional[str] = None
        value: Optional[ast.expr] = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target_name = node.target.id
            value = node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target_name = node.targets[0].id
            value = node.value

        if target_name is None or value is None:
            continue

        try:
            literal = ast.literal_eval(value)
        except (ValueError, SyntaxError):
            continue

        if target_name == "revision" and isinstance(literal, str):
            revision = literal
        elif target_name == "down_revision":
            down_revision = literal  # type: ignore[assignment]
            saw_down = True

    return revision, down_revision, saw_down


def _check_single_head() -> list[str]:
    if not VERSIONS_DIR.exists():
        return []

    revisions: Set[str] = set()
    referenced: Set[str] = set()

    for py_file in sorted(VERSIONS_DIR.glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        revision, down_revision, _saw_down = _parse_revision_metadata(py_file)
        if not revision:
            continue
        revisions.add(revision)
        if isinstance(down_revision, str):
            referenced.add(down_revision)
        elif isinstance(down_revision, (tuple, list)):
            for item in down_revision:
                if isinstance(item, str):
                    referenced.add(item)

    if not revisions:
        return []

    heads = sorted(revisions - referenced)
    if len(heads) == 1:
        return []
    if not heads:
        return ["alembic chain has no head revisions (cycle or missing root)"]
    head_list = ", ".join(heads)
    suggestion = f"alembic merge -m \"merge heads\" {' '.join(heads)}"
    return [f"alembic chain has {len(heads)} heads (expected 1): {head_list}; resolve with `{suggestion}`"]


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
    # Single-head invariant always scans the full tree: a new migration with
    # the wrong down_revision can split the chain even when the diff itself
    # looks well-formed in isolation.
    violations.extend(_check_single_head())

    if violations:
        print("Migration pattern violations:", file=sys.stderr)
        for v in sorted(violations):
            print(f"  {v}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
