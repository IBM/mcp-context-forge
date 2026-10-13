# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/5e211ec89cad_allow_nullable_email_user_password_hash.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Allow email users without local password hashes.

Revision ID: 5e211ec89cad
Revises: 12d4a0c7789c
Create Date: 2026-09-04 09:37:21.131648
"""

# Standard
import hashlib
import json
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "5e211ec89cad"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "12d4a0c7789c"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DISABLED_PASSWORD_HASH = "!disabled"
PASSWORDLESS_HASH_TYPE = "none"
COMPATIBLE_PASSWORD_HASH_TYPE = "argon2id"
NULL_HASH_KEY_PREFIX = "password_hash_was_null:"
NONE_TYPE_KEY_PREFIX = "password_hash_type_was_none:"


def _email_users_columns() -> dict[str, dict]:
    """Return reflected email_users columns keyed by name."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "email_users" not in inspector.get_table_names():
        return {}
    return {column["name"]: column for column in inspector.get_columns("email_users")}


def _has_migration_metadata_table() -> bool:
    """Return whether migration_metadata is available for round-trip state."""
    bind = op.get_bind()
    return "migration_metadata" in sa.inspect(bind).get_table_names()


def _metadata_key(prefix: str, email: str) -> str:
    """Build a migration_metadata key that is stable and below key length limits."""
    email_hash = hashlib.sha256(email.encode("utf-8")).hexdigest()
    return f"{prefix}{email_hash}"


def _metadata_value(email: str, password_hash: str | None = None) -> str:
    """Serialize passwordless metadata for a downgraded row."""
    if password_hash is None:
        return email
    return json.dumps({"email": email, "password_hash": password_hash}, separators=(",", ":"))


def _parse_metadata_value(value: str) -> tuple[str, str | None]:
    """Return email and optional original password hash from metadata."""
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return value, None

    if not isinstance(parsed, dict):
        return value, None

    email = parsed.get("email")
    if not isinstance(email, str):
        return value, None

    password_hash = parsed.get("password_hash")
    return email, password_hash if isinstance(password_hash, str) else None


def _snapshot_metadata(prefix: str, rows: list[tuple[str, str | None]]) -> None:
    """Persist email rows whose passwordless state must survive downgrade-to-upgrade."""
    if not rows or not _has_migration_metadata_table():
        return

    bind = op.get_bind()
    for email, password_hash in rows:
        key = _metadata_key(prefix, email)
        bind.execute(sa.text("DELETE FROM migration_metadata WHERE revision = :revision AND key = :key"), {"revision": revision, "key": key})
        bind.execute(
            sa.text(
                "INSERT INTO migration_metadata (revision, key, value, created_at) "
                "VALUES (:revision, :key, :value, CURRENT_TIMESTAMP)"
            ),
            {"revision": revision, "key": key, "value": _metadata_value(email, password_hash)},
        )


def _passwordless_metadata_rows() -> list[tuple[str, str]]:
    """Return stored passwordless row metadata for this revision."""
    if not _has_migration_metadata_table():
        return []

    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT key, value FROM migration_metadata WHERE revision = :revision"), {"revision": revision}).all()
    return [
        (str(row[0]), str(row[1]))
        for row in rows
        if row[1] is not None and (str(row[0]).startswith(NULL_HASH_KEY_PREFIX) or str(row[0]).startswith(NONE_TYPE_KEY_PREFIX))
    ]


def _restore_passwordless_metadata(columns: dict[str, dict]) -> None:
    """Restore passwordless markers saved by downgrade()."""
    rows = _passwordless_metadata_rows()
    if not rows:
        return

    bind = op.get_bind()
    has_password_hash_type = "password_hash_type" in columns
    null_hash_emails = [_parse_metadata_value(value)[0] for key, value in rows if key.startswith(NULL_HASH_KEY_PREFIX)]
    none_type_entries = [_parse_metadata_value(value) for key, value in rows if key.startswith(NONE_TYPE_KEY_PREFIX)]

    for email in null_hash_emails:
        if has_password_hash_type:
            bind.execute(
                sa.text(
                    "UPDATE email_users "
                    "SET password_hash = NULL, password_hash_type = :passwordless_hash_type "
                    "WHERE email = :email AND password_hash = :disabled_hash"
                ),
                {"email": email, "disabled_hash": DISABLED_PASSWORD_HASH, "passwordless_hash_type": PASSWORDLESS_HASH_TYPE},
            )
        else:
            bind.execute(
                sa.text("UPDATE email_users SET password_hash = NULL WHERE email = :email AND password_hash = :disabled_hash"),
                {"email": email, "disabled_hash": DISABLED_PASSWORD_HASH},
            )

    if has_password_hash_type:
        for email, original_hash in none_type_entries:
            if original_hash is None:
                bind.execute(
                    sa.text(
                        "UPDATE email_users "
                        "SET password_hash_type = :passwordless_hash_type "
                        "WHERE email = :email AND password_hash_type = :compatible_hash_type AND password_hash IS NULL"
                    ),
                    {"email": email, "passwordless_hash_type": PASSWORDLESS_HASH_TYPE, "compatible_hash_type": COMPATIBLE_PASSWORD_HASH_TYPE},
                )
            else:
                bind.execute(
                    sa.text(
                        "UPDATE email_users "
                        "SET password_hash_type = :passwordless_hash_type "
                        "WHERE email = :email AND password_hash_type = :compatible_hash_type AND password_hash = :original_hash"
                    ),
                    {
                        "email": email,
                        "passwordless_hash_type": PASSWORDLESS_HASH_TYPE,
                        "compatible_hash_type": COMPATIBLE_PASSWORD_HASH_TYPE,
                        "original_hash": original_hash,
                    },
                )

    for key, _email in rows:
        bind.execute(sa.text("DELETE FROM migration_metadata WHERE revision = :revision AND key = :key"), {"revision": revision, "key": key})


def upgrade() -> None:
    """Allow passwordless SSO-only users to store NULL password_hash."""
    columns = _email_users_columns()
    password_hash = columns.get("password_hash")
    if password_hash is None:
        return

    if not password_hash.get("nullable"):
        with op.batch_alter_table("email_users", schema=None) as batch_op:
            batch_op.alter_column("password_hash", existing_type=sa.String(length=255), nullable=True)

    _restore_passwordless_metadata(columns)


def downgrade() -> None:
    """Restore NOT NULL password_hash after disabling passwordless rows."""
    columns = _email_users_columns()
    password_hash = columns.get("password_hash")
    if password_hash is None:
        return

    bind = op.get_bind()
    password_hash_type = columns.get("password_hash_type")

    null_hash_rows = [(str(email), None) for email in bind.execute(sa.text("SELECT email FROM email_users WHERE password_hash IS NULL")).scalars().all()]
    _snapshot_metadata(NULL_HASH_KEY_PREFIX, null_hash_rows)

    if password_hash_type is not None:
        none_type_rows = [
            (str(row[0]), str(row[1]) if row[1] is not None else None)
            for row in bind.execute(
                sa.text("SELECT email, password_hash FROM email_users WHERE password_hash_type = :passwordless_hash_type"),
                {"passwordless_hash_type": PASSWORDLESS_HASH_TYPE},
            )
            .all()
        ]
        _snapshot_metadata(NONE_TYPE_KEY_PREFIX, none_type_rows)

    bind.execute(
        sa.text("UPDATE email_users SET password_hash = :disabled_hash WHERE password_hash IS NULL"),
        {"disabled_hash": DISABLED_PASSWORD_HASH},
    )

    if password_hash_type is not None:
        bind.execute(
            sa.text("UPDATE email_users SET password_hash_type = :hash_type WHERE password_hash_type = :passwordless_hash_type"),
            {"hash_type": COMPATIBLE_PASSWORD_HASH_TYPE, "passwordless_hash_type": PASSWORDLESS_HASH_TYPE},
        )

    if not password_hash.get("nullable"):
        return

    with op.batch_alter_table("email_users", schema=None) as batch_op:
        batch_op.alter_column("password_hash", existing_type=sa.String(length=255), nullable=False)
