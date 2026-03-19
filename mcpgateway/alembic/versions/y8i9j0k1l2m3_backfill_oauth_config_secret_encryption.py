# -*- coding: utf-8 -*-
"""Backfill oauth_config secret encryption for gateway/server/a2a rows.

Revision ID: y8i9j0k1l2m3
Revises: x7h8i9j0k1l2
Create Date: 2026-02-23 08:10:00.000000
"""

# Standard
import json
import os
import sys
from typing import Any, Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "y8i9j0k1l2m3"
down_revision: Union[str, Sequence[str], None] = "x7h8i9j0k1l2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OAUTH_SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "client_secret",
        "password",
        "refresh_token",
        "access_token",
        "id_token",
        "token",
        "secret",
        "private_key",
    }
)


def _is_sensitive_oauth_key(key: Any) -> bool:
    """Return whether the key should be treated as secret oauth material.

    Args:
        key: OAuth config key candidate.

    Returns:
        bool: True when the key should be treated as sensitive.
    """
    return isinstance(key, str) and key.lower() in _OAUTH_SENSITIVE_KEYS


def _protect_sensitive_value(value: Any, encryption: Any) -> Any:
    """Protect a sensitive oauth field value.

    Args:
        value: Candidate secret value.
        encryption: Encryption service instance.

    Returns:
        Any: Protected value.
    """
    if isinstance(value, dict):
        return _protect_oauth_config(value, encryption)
    if isinstance(value, list):
        return [_protect_sensitive_value(item, encryption) for item in value]
    if value is None or value == "":
        return value
    if not isinstance(value, str):
        return value
    if encryption.is_encrypted(value):
        return value
    try:
        return encryption.encrypt_secret(value)
    except Exception:
        return value


def _protect_oauth_config(value: Any, encryption: Any) -> Any:
    """Recursively protect oauth_config secret values.

    Args:
        value: oauth_config fragment to process.
        encryption: Encryption service instance.

    Returns:
        Any: Protected oauth_config fragment.
    """
    if isinstance(value, dict):
        protected: dict[str, Any] = {}
        for key, item in value.items():
            if _is_sensitive_oauth_key(key):
                protected[key] = _protect_sensitive_value(item, encryption)
            else:
                protected[key] = _protect_oauth_config(item, encryption)
        return protected
    if isinstance(value, list):
        return [_protect_oauth_config(item, encryption) for item in value]
    return value


def _normalize_oauth_config(raw_value: Any) -> Any:
    """Normalize JSON payloads from DB rows to dict/list values.

    Args:
        raw_value: Raw DB value.

    Returns:
        Any: Normalized dict/list value or None when unusable.
    """
    if isinstance(raw_value, (dict, list)):
        return raw_value
    if isinstance(raw_value, str):
        try:
            parsed = json.loads(raw_value)
            if isinstance(parsed, (dict, list)):
                return parsed
        except Exception:
            return None
    return None


def _backfill_oauth_config_table(bind: sa.Connection, table_name: str, encryption: Any) -> int:
    """Backfill one table and return number of updated rows.

    Args:
        bind: Alembic DB connection.
        table_name: Table name to process.
        encryption: Encryption service instance.

    Returns:
        int: Number of updated rows.
    """
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    if table_name not in tables:
        return 0

    columns = [col["name"] for col in inspector.get_columns(table_name)]
    if "oauth_config" not in columns:
        return 0

    table = sa.table(
        table_name,
        sa.column("id", sa.String()),
        sa.column("oauth_config", sa.JSON()),
    )
    rows = bind.execute(sa.select(table.c.id, table.c.oauth_config).where(table.c.oauth_config.is_not(None))).all()

    updated_rows = 0
    for row in rows:
        oauth_config = _normalize_oauth_config(row.oauth_config)
        if oauth_config is None:
            continue

        protected_config = _protect_oauth_config(oauth_config, encryption)
        if protected_config != oauth_config:
            bind.execute(table.update().where(table.c.id == row.id).values(oauth_config=protected_config))
            updated_rows += 1

    return updated_rows


def upgrade() -> None:
    """Encrypt plaintext oauth_config secret values in existing rows."""
    bind = op.get_bind()

    try:
        # First-Party
        from mcpgateway.config import settings  # pylint: disable=import-outside-toplevel
        from mcpgateway.services.encryption_service import get_encryption_service  # pylint: disable=import-outside-toplevel
    except ModuleNotFoundError:
        # Alembic can run with cwd=mcpgateway/, where package import requires repo root on sys.path.
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        if repo_root not in sys.path:
            sys.path.insert(0, repo_root)
        # First-Party
        from mcpgateway.config import settings  # pylint: disable=import-outside-toplevel,reimported
        from mcpgateway.services.encryption_service import get_encryption_service  # pylint: disable=import-outside-toplevel,reimported

    encryption = get_encryption_service(settings.auth_encryption_secret)

    _backfill_oauth_config_table(bind, "gateways", encryption)
    _backfill_oauth_config_table(bind, "servers", encryption)
    _backfill_oauth_config_table(bind, "a2a_agents", encryption)


def downgrade() -> None:
    """No-op downgrade.

    This migration protects existing secrets at rest. Downgrade intentionally does
    not attempt to rewrite encrypted values back to plaintext.
    """
    return
