# -*- coding: utf-8 -*-
"""Location: ./tests/migration/test_oauth_tokens_unique_constraint.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Regression test for issue #5538: the stale unique_gateway_user (gateway_id,
user_id) constraint on oauth_tokens must be dropped so a second user can
authorize a gateway that shares an OAuth client_id, while the per-user
(gateway_id, app_user_email) uniqueness is preserved.
"""

# Standard
import os
from pathlib import Path
import subprocess
import sys

# Third-Party
import pytest
import sqlalchemy as sa

REPO_ROOT = Path(__file__).resolve().parents[2]


def _upgrade_to_head(db_url: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "mcpgateway/alembic.ini", "upgrade", "head"],
        check=True,
        capture_output=True,
        cwd=REPO_ROOT,
        env={**os.environ, "DATABASE_URL": db_url},
    )


def _insert_token(engine: sa.Engine, columns: list[str], token_id: str, email: str) -> None:
    data = {
        "id": token_id,
        "gateway_id": "gw",
        "user_id": "shared_client_id",
        "app_user_email": email,
        "access_token": "tok",
    }
    row = {name: data.get(name, "x") for name in columns}
    with engine.begin() as conn:
        col_sql = ", ".join(row)
        val_sql = ", ".join(f":{name}" for name in row)
        conn.execute(sa.text(f"INSERT INTO oauth_tokens ({col_sql}) VALUES ({val_sql})"), row)


def test_second_user_can_authorize_same_gateway(tmp_path):
    db_path = tmp_path / "forge.db"
    _upgrade_to_head(f"sqlite:///{db_path}")

    engine = sa.create_engine(f"sqlite:///{db_path}")
    inspector = sa.inspect(engine)

    constraint_names = {uc["name"] for uc in inspector.get_unique_constraints("oauth_tokens")}
    assert "unique_gateway_user" not in constraint_names

    unique_email_indexes = [ix for ix in inspector.get_indexes("oauth_tokens") if ix.get("unique") and set(ix["column_names"]) == {"gateway_id", "app_user_email"}]
    assert unique_email_indexes, "per-user (gateway_id, app_user_email) uniqueness must be preserved"

    columns = [c["name"] for c in inspector.get_columns("oauth_tokens")]
    _insert_token(engine, columns, "t1", "user1@example.com")
    # A second user authorizing the same gateway (same shared client_id) must now succeed.
    _insert_token(engine, columns, "t2", "user2@example.com")

    # A true duplicate (same gateway + app_user_email) must still be rejected.
    with pytest.raises(sa.exc.IntegrityError):
        _insert_token(engine, columns, "t3", "user1@example.com")
