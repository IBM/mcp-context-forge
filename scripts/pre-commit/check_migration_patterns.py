#!/usr/bin/env python3
"""Pre-commit hook: verify Alembic migration source patterns.

Checks that migration files follow required coding standards:
- Filename follows ``<12-char-hex>_<description>.py`` naming convention
- Revision hash in file matches the filename prefix and is valid hex
- No duplicate revision IDs
- DateTime columns use ``timezone=True``
- SQLAlchemy types used instead of raw SQL types
- ``op.create_index``/``op.drop_index`` used instead of raw SQL
- ``op.drop_index`` specifies ``table_name=``
- Balanced create/drop index counts per migration
- Boolean defaults use ``sa.false()`` not string ``"0"``
- Role permission helpers have PostgreSQL dialect branching
- Token uniqueness migration has orphaned temp table guards

Exit codes:
    0 - all checks pass
    1 - violations detected (printed to stderr)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VERSIONS_DIR = REPO_ROOT / "mcpgateway" / "alembic" / "versions"
FILENAME_RE = re.compile(r"^([0-9a-f]{12})_\w+\.py$")
REVISION_RE = re.compile(r'^revision(?::\s*str)?\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)


def _check_naming_and_hashes() -> list[str]:
    """Verify migration filenames follow naming convention and hashes are valid."""
    violations: list[str] = []

    if not VERSIONS_DIR.exists():
        return []

    seen_revisions: dict[str, str] = {}

    for py_file in sorted(VERSIONS_DIR.glob("*.py")):
        if py_file.name == "__init__.py":
            continue

        name = py_file.name

        # Check filename matches <12-char-hex>_<description>.py
        match = FILENAME_RE.match(name)
        if not match:
            violations.append(f"{name}: filename must match <12-char-hex>_<description>.py")
            continue

        filename_hash = match.group(1)

        # Read the file and extract the revision string
        try:
            content = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        rev_match = REVISION_RE.search(content)
        if not rev_match:
            violations.append(f"{name}: cannot find revision string in file")
            continue

        file_revision = rev_match.group(1)

        # Revision must match filename hash prefix
        if file_revision != filename_hash:
            violations.append(f"{name}: revision '{file_revision}' does not match filename hash '{filename_hash}'")

        # Revision must be valid lowercase hex
        if not all(ch in "0123456789abcdef" for ch in file_revision):
            violations.append(f"{name}: revision '{file_revision}' contains non-hex characters (must be 0-9, a-f)")

        # Check for duplicate revisions
        if file_revision in seen_revisions:
            violations.append(f"{name}: duplicate revision '{file_revision}' (also in {seen_revisions[file_revision]})")
        else:
            seen_revisions[file_revision] = name

    return violations


def _check_universal_patterns() -> list[str]:
    """Check all migrations for universal coding standards."""
    violations: list[str] = []

    if not VERSIONS_DIR.exists():
        return []

    for py_file in sorted(VERSIONS_DIR.glob("*.py")):
        if py_file.name == "__init__.py":
            continue

        try:
            source = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
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


def _check_token_uniqueness() -> list[str]:
    """Check migration d9e0f1a2b3c4 for orphaned temp table guards."""
    violations: list[str] = []
    path = next(VERSIONS_DIR.glob("d9e0f1a2b3c4*"), None)

    if path is None:
        return []

    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
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


def main() -> int:
    violations: list[str] = []
    violations.extend(_check_naming_and_hashes())
    violations.extend(_check_universal_patterns())
    violations.extend(_check_token_uniqueness())

    if violations:
        print("Migration pattern violations:", file=sys.stderr)
        for v in sorted(violations):
            print(f"  {v}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
