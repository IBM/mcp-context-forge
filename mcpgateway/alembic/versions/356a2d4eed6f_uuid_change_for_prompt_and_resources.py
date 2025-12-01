"""UUID Change for Prompt and Resources

Revision ID: 356a2d4eed6f
Revises: z1a2b3c4d5e6
Create Date: 2025-12-01 14:52:01.957105

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import uuid
import logging

from sqlalchemy import text

# logger for migration messages
logger = logging.getLogger(__name__)
# Exceptions we expect when dropping non-existent constraints/columns
EXPECTED_DB_EXCEPTIONS = (
    sa.exc.ProgrammingError,
    sa.exc.OperationalError,
    getattr(sa.exc, 'NoSuchTableError', Exception),
    getattr(sa.exc, 'NoSuchColumnError', Exception),
    NotImplementedError,
)



# revision identifiers, used by Alembic.
revision: str = '356a2d4eed6f'
down_revision: Union[str, Sequence[str], None] = 'z1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add new UUID columns (temporary names) if they don't already exist
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    def _column_exists(table_name: str, column_name: str) -> bool:
        try:
            return column_name in [c['name'] for c in inspector.get_columns(table_name)]
        except Exception:
            return False

    if not _column_exists('resources', 'new_id'):
        op.add_column('resources', sa.Column('new_id', sa.String(length=36), nullable=True))
    else:
        logger.debug("Column 'new_id' already exists on 'resources', skipping add_column")

    if not _column_exists('prompts', 'new_id'):
        op.add_column('prompts', sa.Column('new_id', sa.String(length=36), nullable=True))
    else:
        logger.debug("Column 'new_id' already exists on 'prompts', skipping add_column")

    if not _column_exists('resource_metrics', 'new_resource_id'):
        op.add_column('resource_metrics', sa.Column('new_resource_id', sa.String(length=36), nullable=True))
    else:
        logger.debug("Column 'new_resource_id' already exists on 'resource_metrics', skipping add_column")

    # Populate resources -> new_id and update resource_metrics to preserve relations
    resources = conn.execute(sa.text('SELECT id FROM resources')).fetchall()
    for (old_id,) in resources:
        new_uuid = uuid.uuid4().hex
        conn.execute(sa.text('UPDATE resources SET new_id = :new WHERE id = :old'), {'new': new_uuid, 'old': old_id})
        conn.execute(sa.text('UPDATE resource_metrics SET new_resource_id = :new WHERE resource_id = :old'), {'new': new_uuid, 'old': old_id})

    # Populate prompts -> new_id
    prompts = conn.execute(sa.text('SELECT id FROM prompts')).fetchall()
    for (old_id,) in prompts:
        new_uuid = uuid.uuid4().hex
        conn.execute(sa.text('UPDATE prompts SET new_id = :new WHERE id = :old'), {'new': new_uuid, 'old': old_id})

    # Make the new id columns non-nullable and perform renames in a SQLite-safe way
    # Use batch_alter_table so Alembic will recreate the table for SQLite.
    with op.batch_alter_table('resources') as batch_op:
        batch_op.alter_column('new_id', existing_type=sa.String(length=36), nullable=False)

    with op.batch_alter_table('prompts') as batch_op:
        batch_op.alter_column('new_id', existing_type=sa.String(length=36), nullable=False)

    with op.batch_alter_table('resource_metrics') as batch_op:
        batch_op.alter_column('new_resource_id', existing_type=sa.String(length=36), nullable=False)

    # Try to drop existing primary key constraints (common default names are '<table>_pkey')
    try:
        op.drop_constraint('resources_pkey', 'resources', type_='primary')
    except EXPECTED_DB_EXCEPTIONS as e:
        logger.debug("Ignoring missing/failed drop_constraint resources_pkey: %s", e)
    try:
        op.drop_constraint('prompts_pkey', 'prompts', type_='primary')
    except EXPECTED_DB_EXCEPTIONS as e:
        logger.debug("Ignoring missing/failed drop_constraint prompts_pkey: %s", e)

    # Rename old integer id columns to keep them temporarily and rename new_id -> id
    # Use batch_alter_table so renames are portable across SQLite and other DBs.
    with op.batch_alter_table('resources') as batch_op:
        batch_op.alter_column('id', new_column_name='old_id', existing_type=sa.Integer())
        batch_op.alter_column('new_id', new_column_name='id', existing_type=sa.String(length=36))
        # Create primary key on the new UUID id column in a batch-safe way
        batch_op.create_primary_key('resources_pkey', ['id'])
        # Drop the old integer PK column as part of the same batch table rebuild
        try:
            batch_op.drop_column('old_id')
        except Exception:
            logger.debug("Failed to drop 'old_id' in resources batch; will attempt later")

    with op.batch_alter_table('prompts') as batch_op:
        batch_op.alter_column('id', new_column_name='old_id', existing_type=sa.Integer())
        batch_op.alter_column('new_id', new_column_name='id', existing_type=sa.String(length=36))
        # Create primary key on the new UUID id column in a batch-safe way
        batch_op.create_primary_key('prompts_pkey', ['id'])
        # Drop the old integer PK column as part of the same batch table rebuild
        try:
            batch_op.drop_column('old_id')
        except Exception:
            logger.debug("Failed to drop 'old_id' in prompts batch; will attempt later")

    # Primary keys created inside batch_alter_table blocks for SQLite compatibility

    # Replace resource_metrics.resource_id with the UUID-based column and recreate FK
    try:
        op.drop_constraint('resource_metrics_resource_id_fkey', 'resource_metrics', type_='foreignkey')
    except EXPECTED_DB_EXCEPTIONS as e:
        logger.debug("Ignoring missing/failed drop_constraint resource_metrics_resource_id_fkey: %s", e)

    with op.batch_alter_table('resource_metrics') as batch_op:
        batch_op.alter_column('resource_id', new_column_name='old_resource_id', existing_type=sa.Integer())
        batch_op.alter_column('new_resource_id', new_column_name='resource_id', existing_type=sa.String(length=36))
        # Create FK in batch mode so SQLite will rebuild the table with constraint
        batch_op.create_foreign_key('resource_metrics_resource_id_fkey', 'resources', ['resource_id'], ['id'])
        # Drop the old integer FK column as part of the same batch table rebuild
        try:
            batch_op.drop_column('old_resource_id')
        except Exception:
            logger.debug("Failed to drop 'old_resource_id' in resource_metrics batch; will attempt later")

    # Foreign key created inside batch_alter_table block for SQLite compatibility

    # Drop the old integer id columns now that UUIDs are in place
    # Use batch_alter_table so SQLite can rebuild tables when dropping columns
    if _column_exists('resources', 'old_id'):
        with op.batch_alter_table('resources') as batch_op:
            batch_op.drop_column('old_id')
    else:
        logger.debug("Column 'old_id' not present on 'resources', skipping drop_column")

    if _column_exists('prompts', 'old_id'):
        with op.batch_alter_table('prompts') as batch_op:
            batch_op.drop_column('old_id')
    else:
        logger.debug("Column 'old_id' not present on 'prompts', skipping drop_column")

    if _column_exists('resource_metrics', 'old_resource_id'):
        with op.batch_alter_table('resource_metrics') as batch_op:
            batch_op.drop_column('old_resource_id')
    else:
        logger.debug("Column 'old_resource_id' not present on 'resource_metrics', skipping drop_column")


def downgrade() -> None:
    """Downgrade schema."""
    # NOTE: The original integer primary key values were dropped during the upgrade.
    # This downgrade cannot restore the original integer values; instead it
    # recreates integer `id` columns populated with new sequential integers and
    # remaps foreign keys accordingly so the schema returns to integer-based PKs.

    conn = op.get_bind()

    # 1) Add integer columns to resources and prompts
    op.add_column('resources', sa.Column('old_id', sa.Integer(), nullable=True))
    op.add_column('prompts', sa.Column('old_id', sa.Integer(), nullable=True))

    # Populate sequential integers for resources
    resources = conn.execute(sa.text('SELECT id FROM resources')).fetchall()
    for idx, (uuid_val,) in enumerate(resources, start=1):
        conn.execute(sa.text('UPDATE resources SET old_id = :num WHERE id = :uuid'), {'num': idx, 'uuid': uuid_val})

    # Populate sequential integers for prompts
    prompts = conn.execute(sa.text('SELECT id FROM prompts')).fetchall()
    for idx, (uuid_val,) in enumerate(prompts, start=1):
        conn.execute(sa.text('UPDATE prompts SET old_id = :num WHERE id = :uuid'), {'num': idx, 'uuid': uuid_val})

    # 2) Drop primary key constraints on UUID id columns
    try:
        op.drop_constraint('resources_pkey', 'resources', type_='primary')
    except EXPECTED_DB_EXCEPTIONS as e:
        logger.debug("Ignoring missing/failed drop_constraint resources_pkey (downgrade): %s", e)
    try:
        op.drop_constraint('prompts_pkey', 'prompts', type_='primary')
    except EXPECTED_DB_EXCEPTIONS as e:
        logger.debug("Ignoring missing/failed drop_constraint prompts_pkey (downgrade): %s", e)

    # 3) Rename UUID id columns to keep them (uuid_id) and rename old_id -> id
    with op.batch_alter_table('resources') as batch_op:
        batch_op.alter_column('id', new_column_name='uuid_id', existing_type=sa.String(length=36))
        batch_op.alter_column('old_id', new_column_name='id', existing_type=sa.Integer())
        # Recreate primary key on integer id column in batch mode for SQLite
        batch_op.create_primary_key('resources_pkey', ['id'])

    with op.batch_alter_table('prompts') as batch_op:
        batch_op.alter_column('id', new_column_name='uuid_id', existing_type=sa.String(length=36))
        batch_op.alter_column('old_id', new_column_name='id', existing_type=sa.Integer())
        # Recreate primary key on integer id column in batch mode for SQLite
        batch_op.create_primary_key('prompts_pkey', ['id'])

    # Primary keys recreated inside batch_alter_table blocks for SQLite compatibility

    # 5) For resource_metrics, add integer column and populate using mapping from resources
    op.add_column('resource_metrics', sa.Column('old_resource_id', sa.Integer(), nullable=True))
    # Fetch mapping of resource uuid -> new integer id
    mapping = conn.execute(sa.text('SELECT uuid_id, id FROM resources')).fetchall()
    for uuid_val, int_id in mapping:
        conn.execute(sa.text('UPDATE resource_metrics SET old_resource_id = :num WHERE resource_id = :uuid'), {'num': int_id, 'uuid': uuid_val})

    # 6) Replace FK: drop existing FK, swap columns, recreate FK to integer PK
    try:
        op.drop_constraint('resource_metrics_resource_id_fkey', 'resource_metrics', type_='foreignkey')
    except EXPECTED_DB_EXCEPTIONS as e:
        logger.debug("Ignoring missing/failed drop_constraint resource_metrics_resource_id_fkey (downgrade): %s", e)

    # Rename current uuid resource_id to uuid_resource_id, and old_resource_id -> resource_id
    with op.batch_alter_table('resource_metrics') as batch_op:
        batch_op.alter_column('resource_id', new_column_name='uuid_resource_id', existing_type=sa.String(length=36))
        batch_op.alter_column('old_resource_id', new_column_name='resource_id', existing_type=sa.Integer())
        # Recreate FK to resources.id (integer PK) in batch mode for SQLite
        batch_op.create_foreign_key('resource_metrics_resource_id_fkey', 'resources', ['resource_id'], ['id'])

    # Foreign key recreated inside batch_alter_table block for SQLite compatibility

    # 7) Drop UUID columns from resources, prompts, and resource_metrics
    inspector = sa.inspect(conn)

    def _col_exists_down(table_name: str, column_name: str) -> bool:
        try:
            return column_name in [c['name'] for c in inspector.get_columns(table_name)]
        except Exception:
            return False

    if _col_exists_down('resources', 'uuid_id'):
        with op.batch_alter_table('resources') as batch_op:
            batch_op.drop_column('uuid_id')
    else:
        logger.debug("Column 'uuid_id' not present on 'resources', skipping drop_column")

    if _col_exists_down('prompts', 'uuid_id'):
        with op.batch_alter_table('prompts') as batch_op:
            batch_op.drop_column('uuid_id')
    else:
        logger.debug("Column 'uuid_id' not present on 'prompts', skipping drop_column")

    # resource_metrics uuid column was renamed to uuid_resource_id earlier; drop it if present
    if _col_exists_down('resource_metrics', 'uuid_resource_id'):
        with op.batch_alter_table('resource_metrics') as batch_op:
            batch_op.drop_column('uuid_resource_id')
    else:
        logger.debug("Column 'uuid_resource_id' not present on 'resource_metrics', skipping drop_column")

    # NOTE: This downgrade generates new integer IDs and therefore will not
    # match the original IDs that existed prior to the upgrade. Use with care.
