# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/f3a3a3d901b8_remove_gateway_url_unique_constraint.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Keval Mahajan

Alembic migration to remove unique constraint on gateway URL. 
An improved alternative duplication check has been implemented for gateway duplication prevention.

Revision ID: f3a3a3d901b8
Revises: aac21d6f9522
Create Date: 2025-11-11 22:30:05.474282

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine import Inspector



# revision identifiers, used by Alembic.
revision: str = 'f3a3a3d901b8'
down_revision: Union[str, Sequence[str], None] = 'aac21d6f9522'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def constraint_exists(inspector, table_name, constraint_name):
    """Check if a constraint exists in the table."""
    try:
        unique_constraints = inspector.get_unique_constraints(table_name)
        return any(uc['name'] == constraint_name for uc in unique_constraints)
    except Exception:
        # Fallback: assume constraint exists if we can't check
        return True


def upgrade():
    """Remove the unique constraint on (team_id, owner_email, url) from gateway table."""
    
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)
    
    # Check if constraint exists before attempting to drop
    if not constraint_exists(inspector, 'gateways', 'uq_team_owner_url_gateway'):
        print("Constraint 'uq_team_owner_url_gateway' does not exist, skipping drop.")
        return
    
    if conn.dialect.name == 'sqlite':
        # SQLite: Use batch mode to recreate table without the constraint
        with op.batch_alter_table('gateways', schema=None) as batch_op:
            batch_op.drop_constraint(
                'uq_team_owner_url_gateway', 
                type_='unique'
            )
    else:
        # PostgreSQL, MySQL, etc.: Direct constraint drop
        op.drop_constraint(
            'uq_team_owner_url_gateway',
            'gateways',
            type_='unique'
        )
    
    print("Successfully removed constraint 'uq_team_owner_url_gateway' from gateway table.")


def downgrade():
    """Re-add the unique constraint on (team_id, owner_email, url) to gateway table."""
    
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)
    
    # Check if constraint already exists before attempting to create
    if constraint_exists(inspector, 'gateways', 'uq_team_owner_url_gateway'):
        print("Constraint 'uq_team_owner_url_gateway' already exists, skipping creation.")
        return
    
    if conn.dialect.name == 'sqlite':
        # SQLite: Use batch mode to recreate table with the constraint
        with op.batch_alter_table('gateways', schema=None) as batch_op:
            batch_op.create_unique_constraint(
                'uq_team_owner_url_gateway',
                ['team_id', 'owner_email', 'url']
            )
    else:
        # PostgreSQL, MySQL, etc.: Direct constraint creation
        op.create_unique_constraint(
            'uq_team_owner_url_constraint',
            'gateways',
            ['team_id', 'owner_email', 'url']
        )
    
    print("Successfully re-added constraint 'uq_team_owner_url_gateway' to gateways table.")
