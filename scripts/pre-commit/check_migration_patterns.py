#!/usr/bin/env python3
"""Pre-commit hook: verify Alembic migration source patterns.

Checks that migration files follow required coding standards:

- Filename follows ``<12-char-alphanumeric>_<description>.py`` naming convention
  (Alembic's default generator uses hex but revision IDs are not required
  to be hex — any unique string is valid)
- Revision string in file matches the filename prefix
- No duplicate revision IDs across the migrations directory
- DateTime columns use ``timezone=True``
- SQLAlchemy types used instead of raw SQL types
- ``op.create_index``/``op.drop_index`` used instead of raw SQL
- ``op.drop_index`` specifies ``table_name=``
- Balanced create/drop index counts per migration
- Boolean defaults use ``sa.false()`` not string ``"0"``
- Role permission helpers have PostgreSQL dialect branching
- Token uniqueness migration has orphaned temp table guards

Invocation modes
================

* With filename arguments (pre-commit default): only the supplied files are
  linted for per-file rules. The duplicate-revision check still scans every
  migration, but only *reports* conflicts that involve a changed file.
* With no arguments: scan every migration in the versions directory. Useful
  for ``pre-commit run --all-files`` / CI integrity sweeps.

Exit codes:
    0 - all checks pass
    1 - violations detected (printed to stderr)
"""

from __future__ import annotations

# Standard
from pathlib import Path
import re
import sys
from typing import Iterable, List, Optional, Set

REPO_ROOT = Path(__file__).resolve().parents[2]
VERSIONS_DIR = REPO_ROOT / "mcpgateway" / "alembic" / "versions"
# Alembic revisions are "any unique string". The default generator produces
# 12-char hex, but some migrations in this repo use 12-char alphanumeric with
# non-hex letters. Accept the broader form; keep the length constraint so we
# still catch truly unstructured filenames.
FILENAME_RE = re.compile(r"^([0-9a-z]{12})_\w+\.py$")
REVISION_RE = re.compile(r'^revision(?::\s*str)?\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)


def _migration_files(paths: Iterable[Path]) -> List[Path]:
    """Filter paths down to migration modules that actually exist on disk."""
    keep: List[Path] = []
    for p in paths:
        if not p.exists():
            continue
        if p.name == "__init__.py":
            continue
        if p.suffix != ".py":
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
    """Verify per-file filename/revision-id rules for the given files."""
    violations: list[str] = []

    for py_file in sorted(files):
        name = py_file.name
        match = FILENAME_RE.match(name)
        if not match:
            violations.append(f"{name}: filename must match <12-char-alphanumeric>_<description>.py")
            continue

        filename_hash = match.group(1)
        content = _read(py_file)
        if content is None:
            continue

        rev_match = REVISION_RE.search(content)
        if not rev_match:
            violations.append(f"{name}: cannot find revision string in file")
            continue

        file_revision = rev_match.group(1)
        if file_revision != filename_hash:
            violations.append(f"{name}: revision '{file_revision}' does not match filename hash '{filename_hash}'")

    return violations


def _check_duplicate_revisions(changed_names: Optional[Set[str]]) -> list[str]:
    """Scan all migrations for duplicate revision IDs.

    When ``changed_names`` is provided, only report duplicates where at least
    one of the colliding files is in the changed set — conflicts between two
    untouched migrations are pre-existing drift, not something this commit
    introduced.
    """
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


def _check_universal_patterns(files: Iterable[Path]) -> list[str]:
    """Check per-file coding standards on the given files."""
    violations: list[str] = []

    for py_file in sorted(files):
        source = _read(py_file)
        if source is None:
            continue

        name = py_file.name

        # --- DateTime columns must use timezone=True ---
        for match in re.findall(r"sa\.DateTime\([^)]*\)", source):
            if "timezone=True" not in match:
                violations.append(f"{name}: DateTime column missing timezone=True: {match}")

        # --- SQLAlchemy types, not raw SQL types ---
        if "op.create_table" in source:
            if not ("sa.String" in source or "sa.Text" in source or "sa.Integer" in source or "sa.Boolean" in source or "sa.DateTime" in source or "sa.JSON" in source):
                violations.append(f"{name}: create_table should use SQLAlchemy types (sa.String, sa.Integer, etc.)")

        # --- Use op.create_index / op.drop_index, not raw SQL ---
        if "CREATE INDEX IF NOT EXISTS" in source:
            violations.append(f"{name}: use op.create_index instead of raw SQL CREATE INDEX IF NOT EXISTS")
        if "DROP INDEX IF EXISTS" in source:
            violations.append(f"{name}: use op.drop_index instead of raw SQL DROP INDEX IF EXISTS")

        # --- op.drop_index must specify table_name= ---
        if "op.drop_index" in source and "table_name=" not in source:
            violations.append(f"{name}: op.drop_index should specify table_name= parameter")

        # --- Balanced create_index / drop_index counts ---
        create_count = source.count("op.create_index")
        drop_count = source.count("op.drop_index")
        if (create_count > 0 or drop_count > 0) and create_count != drop_count:
            violations.append(f"{name}: op.create_index count ({create_count}) != op.drop_index count ({drop_count})")

        # --- Boolean defaults: use sa.false() not string "0" ---
        if 'sa.Boolean(), nullable=False, server_default="0"' in source:
            violations.append(f'{name}: Boolean server_default should use sa.false(), not string "0"')

        # --- Role permission helpers need dialect branching ---
        if "_update_role_permissions" in source:
            if 'dialect_name == "postgresql"' not in source:
                violations.append(f"{name}: _update_role_permissions missing PostgreSQL dialect branching")

    return violations


def _check_token_uniqueness(changed_names: Optional[Set[str]]) -> list[str]:
    """Check the token-uniqueness migration for orphaned temp table guards.

    Only runs when that specific migration is in the changed set (or when no
    changed set is supplied, i.e. a full sweep).
    """
    violations: list[str] = []
    path = next(VERSIONS_DIR.glob("d9e0f1a2b3c4*"), None)
    if path is None:
        return []
    if changed_names is not None and path.name not in changed_names:
        return []

    source = _read(path)
    if source is None:
        return []

    if "_alembic_tmp_email_api_tokens" not in source:
        violations.append("token_uniqueness: missing temp table guard reference")
    if 'op.drop_table("_alembic_tmp_email_api_tokens")' not in source:
        violations.append("token_uniqueness: missing op.drop_table for temp table")
    if "batch_alter_table" not in source:
        violations.append("token_uniqueness: missing batch_alter_table (SQLite compat)")

    if 'op.drop_table("_alembic_tmp_email_api_tokens")' in source and "op.batch_alter_table" in source:
        guard_pos = source.index('op.drop_table("_alembic_tmp_email_api_tokens")')
        batch_pos = source.index("op.batch_alter_table")
        if guard_pos >= batch_pos:
            violations.append("token_uniqueness: temp table guard must appear before batch_alter_table")

    return violations


def main(argv: list[str]) -> int:
    """Run the checks. ``argv`` is the list of files the caller (usually pre-commit) passes in."""
    if not VERSIONS_DIR.exists():
        return 0

    # pre-commit passes the changed file paths as argv. When the caller
    # provides no paths (e.g. manual ``--all-files``), fall back to every
    # migration so the hook still works as an integrity sweep.
    if argv:
        supplied = [Path(a) if Path(a).is_absolute() else REPO_ROOT / a for a in argv]
        files = _migration_files(supplied)
        if not files:
            # None of the supplied paths were migration files — nothing to do.
            return 0
        changed_names: Optional[Set[str]] = {p.name for p in files}
    else:
        files = _migration_files(VERSIONS_DIR.glob("*.py"))
        changed_names = None

    violations: list[str] = []
    violations.extend(_check_naming(files))
    violations.extend(_check_universal_patterns(files))
    violations.extend(_check_duplicate_revisions(changed_names))
    violations.extend(_check_token_uniqueness(changed_names))

    if violations:
        print("Migration pattern violations:", file=sys.stderr)
        for v in sorted(violations):
            print(f"  {v}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
