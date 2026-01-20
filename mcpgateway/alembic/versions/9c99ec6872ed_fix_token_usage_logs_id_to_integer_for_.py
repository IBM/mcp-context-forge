# -*- coding: utf-8 -*-
"""fix_token_usage_logs_id_to_integer

Revision ID: 9c99ec6872ed
Revises: 2f67b12600b4
Create Date: 2025-10-12 13:17:13.892897

"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "9c99ec6872ed"
down_revision: Union[str, Sequence[str], None] = "2f67b12600b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Fix token_usage_logs.id from BigInteger to Integer for all databases.

    BigInteger doesn't work properly with autoincrement in SQLite.
    For consistency and correctness, this migration changes the column type
    to Integer for all database backends (SQLite, PostgreSQL, MySQL).
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Skip if fresh database (tables created via create_all + stamp)
    if not inspector.has_table("gateways"):
        print("Fresh database detected. Skipping migration.")
        return

    # Skip if token_usage_logs table doesn't exist
    if not inspector.has_table("token_usage_logs"):
        print("token_usage_logs table not found. Skipping migration.")
        return

    if bind.dialect.name == "sqlite":
        # For SQLite: Recreate the table with INTEGER id
        # SQLite doesn't support ALTER COLUMN, so we need to recreate the table
        op.execute(
            """
            CREATE TABLE token_usage_logs_new (
                id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                token_jti VARCHAR(36) NOT NULL,
                user_email VARCHAR(255) NOT NULL,
                timestamp DATETIME NOT NULL,
                endpoint VARCHAR(255),
                method VARCHAR(10),
                ip_address VARCHAR(45),
                user_agent TEXT,
                status_code INTEGER,
                response_time_ms INTEGER,
                blocked BOOLEAN NOT NULL,
                block_reason VARCHAR(255)
            )
        """
        )

        # Copy data from old table to new table
        op.execute(
            """
            INSERT INTO token_usage_logs_new
            (id, token_jti, user_email, timestamp, endpoint, method, ip_address,
             user_agent, status_code, response_time_ms, blocked, block_reason)
            SELECT id, token_jti, user_email, timestamp, endpoint, method, ip_address,
                   user_agent, status_code, response_time_ms, blocked, block_reason
            FROM token_usage_logs
        """
        )

        # Drop old table
        op.execute("DROP TABLE token_usage_logs")

        # Rename new table
        op.execute("ALTER TABLE token_usage_logs_new RENAME TO token_usage_logs")

        # Recreate indexes
        op.execute("CREATE INDEX idx_token_usage_logs_token_jti ON token_usage_logs (token_jti)")
        op.execute("CREATE INDEX idx_token_usage_logs_user_email ON token_usage_logs (user_email)")
        op.execute("CREATE INDEX idx_token_usage_logs_timestamp ON token_usage_logs (timestamp)")
        op.execute("CREATE INDEX idx_token_usage_logs_token_jti_timestamp ON token_usage_logs (token_jti, timestamp)")
        op.execute("CREATE INDEX idx_token_usage_logs_user_email_timestamp ON token_usage_logs (user_email, timestamp)")
    else:
        # For PostgreSQL/MySQL: Change from BIGINT to INTEGER for consistency
        # Both databases handle INTEGER auto-increment correctly and it's sufficient for this use case
        op.alter_column("token_usage_logs", "id", existing_type=sa.BigInteger(), type_=sa.Integer(), existing_nullable=False, autoincrement=True)


def downgrade() -> None:
    """Downgrade schema - revert INTEGER back to BigInteger."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Skip if fresh database
    if not inspector.has_table("gateways"):
        print("Fresh database detected. Skipping migration.")
        return

    # Skip if token_usage_logs table doesn't exist
    if not inspector.has_table("token_usage_logs"):
        print("token_usage_logs table not found. Skipping migration.")
        return

    if bind.dialect.name == "sqlite":
        # For SQLite: Recreate with BigInteger (though it won't work properly)
        op.execute(
            """
            CREATE TABLE token_usage_logs_new (
                id BIGINT NOT NULL PRIMARY KEY,
                token_jti VARCHAR(36) NOT NULL,
                user_email VARCHAR(255) NOT NULL,
                timestamp DATETIME NOT NULL,
                endpoint VARCHAR(255),
                method VARCHAR(10),
                ip_address VARCHAR(45),
                user_agent TEXT,
                status_code INTEGER,
                response_time_ms INTEGER,
                blocked BOOLEAN NOT NULL,
                block_reason VARCHAR(255)
            )
        """
        )

        op.execute(
            """
            INSERT INTO token_usage_logs_new
            (id, token_jti, user_email, timestamp, endpoint, method, ip_address,
             user_agent, status_code, response_time_ms, blocked, block_reason)
            SELECT id, token_jti, user_email, timestamp, endpoint, method, ip_address,
                   user_agent, status_code, response_time_ms, blocked, block_reason
            FROM token_usage_logs
        """
        )

        op.execute("DROP TABLE token_usage_logs")
        op.execute("ALTER TABLE token_usage_logs_new RENAME TO token_usage_logs")

        # Recreate indexes
        op.execute("CREATE INDEX idx_token_usage_logs_token_jti ON token_usage_logs (token_jti)")
        op.execute("CREATE INDEX idx_token_usage_logs_user_email ON token_usage_logs (user_email)")
        op.execute("CREATE INDEX idx_token_usage_logs_timestamp ON token_usage_logs (timestamp)")
        op.execute("CREATE INDEX idx_token_usage_logs_token_jti_timestamp ON token_usage_logs (token_jti, timestamp)")
        op.execute("CREATE INDEX idx_token_usage_logs_user_email_timestamp ON token_usage_logs (user_email, timestamp)")
    else:
        # For PostgreSQL/MySQL: Revert INTEGER back to BIGINT
        op.alter_column("token_usage_logs", "id", existing_type=sa.Integer(), type_=sa.BigInteger(), existing_nullable=False, autoincrement=True)
