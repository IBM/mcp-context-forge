"""Location: ./tests/unit/mcpgateway/services/test_resource_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Madhav Kandukuri

SQLAlchemy modifiers

- json_contains_expr: handles json_contains logic for different dialects
"""

# Standard
import json

# Third-Party
from sqlalchemy import func, text


def json_contains_expr(session, col, value) -> bool:
    """
    Return a SQLAlchemy expression that is True when JSON column `col`
    contains the scalar `value`. `session` is used to detect dialect.
    Assumes `col` is a JSON/JSONB column (array-of-strings case).

    Args:
        session: database session
        col: column that contains JSON
        value: value to check for in json

    Returns:
        bool: Whether value in col JSON

    Raises:
        RuntimeError: If dialect is not supported
    """
    dialect = session.get_bind().dialect.name

    if dialect == "mysql":
        # MySQL: JSON_CONTAINS(target, candidate) -> returns 1 for true
        # candidate must be a JSON value; json.dumps(value) -> '"value"'
        return func.json_contains(col, json.dumps(value)) == 1

    if dialect == "postgresql":
        # Postgres JSONB: .contains() works with Python objects (casts to JSONB)
        # For an array-of-strings column, check contains([value])
        return col.contains([value])

    if dialect == "sqlite":
        # SQLite json1: no json_contains; use json_each to test array membership.
        # This assumes `col` holds a JSON array of scalars.
        return text(f"EXISTS (SELECT 1 FROM json_each({col.name}) WHERE value = :_val)").bindparams(_val=value)

    raise RuntimeError(f"Unsupported dialect for json_contains: {dialect}")
