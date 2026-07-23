"""add_sbom_tables

Revision ID: dea0b85ed98e
Revises: f1a2b3c4d5e6
Create Date: 2026-03-21 20:28:04.262077

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'dea0b85ed98e'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create SBOM tables."""
    # Create SBOM documents table
    op.create_table('sbom_documents',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('server_id', sa.String(length=36), nullable=False),
        sa.Column('format', sa.String(length=50), nullable=False),
        sa.Column('spec_version', sa.String(length=20), nullable=False),
        sa.Column('serial_number', sa.String(length=255), nullable=False),
        sa.Column('document_version', sa.Integer(), nullable=False),
        sa.Column('generated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('generator_tool', sa.String(length=100), nullable=False),
        sa.Column('generator_version', sa.String(length=50), nullable=True),
        sa.Column('main_component_name', sa.String(length=255), nullable=True),
        sa.Column('main_component_version', sa.String(length=100), nullable=True),
        sa.Column('document_json', sa.Text(), nullable=False),
        sa.Column('is_compressed', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('serial_number')
    )
    op.create_index('ix_sbom_documents_created_at', 'sbom_documents', ['created_at'], unique=False)
    op.create_index('ix_sbom_documents_format', 'sbom_documents', ['format'], unique=False)
    op.create_index('ix_sbom_documents_server_id', 'sbom_documents', ['server_id'], unique=False)
    op.create_index('ix_sbom_documents_server_id_generated_at', 'sbom_documents', ['server_id', 'generated_at'], unique=False)

    # Create SBOM components table
    op.create_table('sbom_components',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('sbom_document_id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('version', sa.String(length=100), nullable=False),
        sa.Column('purl', sa.String(length=500), nullable=True),
        sa.Column('ecosystem', sa.String(length=50), nullable=False),
        sa.Column('component_type', sa.String(length=50), nullable=False),
        sa.Column('licenses', sa.Text(), nullable=True),
        sa.Column('hash_sha256', sa.String(length=64), nullable=True),
        sa.Column('is_direct', sa.Boolean(), nullable=False),
        sa.Column('component_metadata', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['sbom_document_id'], ['sbom_documents.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_sbom_components_ecosystem', 'sbom_components', ['ecosystem'], unique=False)
    op.create_index('ix_sbom_components_name', 'sbom_components', ['name'], unique=False)
    op.create_index('ix_sbom_components_name_version', 'sbom_components', ['name', 'version'], unique=False)
    op.create_index('ix_sbom_components_purl', 'sbom_components', ['purl'], unique=False)
    op.create_index('ix_sbom_components_sbom_doc_id_name', 'sbom_components', ['sbom_document_id', 'name'], unique=False)
    op.create_index('ix_sbom_components_sbom_document_id', 'sbom_components', ['sbom_document_id'], unique=False)
    op.create_index('ix_sbom_components_version', 'sbom_components', ['version'], unique=False)

    # Create SBOM vulnerabilities table
    op.create_table('sbom_vulnerabilities',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('cve_id', sa.String(length=50), nullable=False),
        sa.Column('package_name', sa.String(length=255), nullable=False),
        sa.Column('package_ecosystem', sa.String(length=50), nullable=False),
        sa.Column('affected_version_range', sa.String(length=200), nullable=False),
        sa.Column('fixed_version', sa.String(length=100), nullable=True),
        sa.Column('severity', sa.String(length=20), nullable=True),
        sa.Column('cvss_score', sa.String(length=10), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('references', sa.Text(), nullable=True),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_modified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('cve_id')
    )
    op.create_index('ix_sbom_vulnerabilities_cve_id', 'sbom_vulnerabilities', ['cve_id'], unique=False)
    op.create_index('ix_sbom_vulnerabilities_package_ecosystem', 'sbom_vulnerabilities', ['package_ecosystem'], unique=False)
    op.create_index('ix_sbom_vulnerabilities_package_name', 'sbom_vulnerabilities', ['package_name'], unique=False)
    op.create_index('ix_sbom_vulnerabilities_severity', 'sbom_vulnerabilities', ['severity'], unique=False)


def downgrade() -> None:
    """Drop SBOM tables."""
    op.drop_index('ix_sbom_vulnerabilities_severity', table_name='sbom_vulnerabilities')
    op.drop_index('ix_sbom_vulnerabilities_package_name', table_name='sbom_vulnerabilities')
    op.drop_index('ix_sbom_vulnerabilities_package_ecosystem', table_name='sbom_vulnerabilities')
    op.drop_index('ix_sbom_vulnerabilities_cve_id', table_name='sbom_vulnerabilities')
    op.drop_table('sbom_vulnerabilities')
    
    op.drop_index('ix_sbom_components_version', table_name='sbom_components')
    op.drop_index('ix_sbom_components_sbom_document_id', table_name='sbom_components')
    op.drop_index('ix_sbom_components_sbom_doc_id_name', table_name='sbom_components')
    op.drop_index('ix_sbom_components_purl', table_name='sbom_components')
    op.drop_index('ix_sbom_components_name_version', table_name='sbom_components')
    op.drop_index('ix_sbom_components_name', table_name='sbom_components')
    op.drop_index('ix_sbom_components_ecosystem', table_name='sbom_components')
    op.drop_table('sbom_components')
    
    op.drop_index('ix_sbom_documents_server_id_generated_at', table_name='sbom_documents')
    op.drop_index('ix_sbom_documents_server_id', table_name='sbom_documents')
    op.drop_index('ix_sbom_documents_format', table_name='sbom_documents')
    op.drop_index('ix_sbom_documents_created_at', table_name='sbom_documents')
    op.drop_table('sbom_documents')