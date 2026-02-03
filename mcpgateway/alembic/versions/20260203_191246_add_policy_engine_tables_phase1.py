"""add policy engine tables phase1 #2019

Revision ID: policy_engine_phase1
Revises: 
Create Date: 2026-02-03

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'policy_engine_phase1'
down_revision = 'b1b2b3b4b5b6'
branch_labels = None
depends_on = None


def upgrade():
    """Create policy engine tables."""
    
    # AccessPermission table
    op.create_table(
        'access_permissions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('resource_type', sa.String(length=50), nullable=True),
        sa.Column('action', sa.String(length=50), nullable=True),
        sa.Column('is_system', sa.Boolean(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )
    op.create_index(op.f('ix_access_permissions_name'), 'access_permissions', ['name'], unique=False)
    
    # AccessPolicy table
    op.create_table(
        'access_policies',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('effect', sa.String(length=10), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=True),
        sa.Column('conditions', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )
    op.create_index(op.f('ix_access_policies_name'), 'access_policies', ['name'], unique=False)
    
    # AccessDecisionLog table
    op.create_table(
        'access_decisions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('subject_email', sa.String(length=255), nullable=True),
        sa.Column('subject_type', sa.String(length=50), nullable=True),
        sa.Column('permission', sa.String(length=100), nullable=True),
        sa.Column('action', sa.String(length=50), nullable=True),
        sa.Column('resource_type', sa.String(length=50), nullable=True),
        sa.Column('resource_id', sa.String(length=255), nullable=True),
        sa.Column('decision', sa.String(length=10), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('matching_policies', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('context', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('request_id', sa.String(length=100), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_access_decisions_decision'), 'access_decisions', ['decision'], unique=False)
    op.create_index(op.f('ix_access_decisions_permission'), 'access_decisions', ['permission'], unique=False)
    op.create_index(op.f('ix_access_decisions_request_id'), 'access_decisions', ['request_id'], unique=False)
    op.create_index(op.f('ix_access_decisions_resource_type'), 'access_decisions', ['resource_type'], unique=False)
    op.create_index(op.f('ix_access_decisions_subject_email'), 'access_decisions', ['subject_email'], unique=False)
    op.create_index(op.f('ix_access_decisions_timestamp'), 'access_decisions', ['timestamp'], unique=False)
    
    # ResourceAccessRule table
    op.create_table(
        'resource_access_rules',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('resource_type', sa.String(length=50), nullable=False),
        sa.Column('resource_id', sa.String(length=255), nullable=True),
        sa.Column('policy_id', sa.UUID(), nullable=True),
        sa.Column('allowed_roles', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('denied_users', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['policy_id'], ['access_policies.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_resource_access_rules_resource_type'), 'resource_access_rules', ['resource_type'], unique=False)


def downgrade():
    """Drop policy engine tables."""
    op.drop_index(op.f('ix_resource_access_rules_resource_type'), table_name='resource_access_rules')
    op.drop_table('resource_access_rules')
    
    op.drop_index(op.f('ix_access_decisions_timestamp'), table_name='access_decisions')
    op.drop_index(op.f('ix_access_decisions_subject_email'), table_name='access_decisions')
    op.drop_index(op.f('ix_access_decisions_resource_type'), table_name='access_decisions')
    op.drop_index(op.f('ix_access_decisions_request_id'), table_name='access_decisions')
    op.drop_index(op.f('ix_access_decisions_permission'), table_name='access_decisions')
    op.drop_index(op.f('ix_access_decisions_decision'), table_name='access_decisions')
    op.drop_table('access_decisions')
    
    op.drop_index(op.f('ix_access_policies_name'), table_name='access_policies')
    op.drop_table('access_policies')
    
    op.drop_index(op.f('ix_access_permissions_name'), table_name='access_permissions')
    op.drop_table('access_permissions')
