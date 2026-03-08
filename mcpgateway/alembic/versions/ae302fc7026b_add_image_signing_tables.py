"""add_image_signing_tables

Revision ID: ae302fc7026b
Revises: f1a2b3c4d5e6
Create Date: 2026-03-08 16:33:52.743269

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ae302fc7026b'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create image signing tables."""

    # Trusted signers table
    op.create_table(
        "image_signing_trusted_signers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("signer_type", sa.String(20), nullable=False),
        sa.Column("oidc_issuer", sa.String(255), nullable=True),
        sa.Column("subject", sa.String(255), nullable=True),
        sa.Column("subject_regex", sa.String(255), nullable=True),
        sa.Column("public_key", sa.Text, nullable=True),
        sa.Column("kms_key_ref", sa.String(500), nullable=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_index("idx_trusted_signer_type", "image_signing_trusted_signers", ["signer_type"])
    op.create_index("idx_trusted_signer_enabled", "image_signing_trusted_signers", ["enabled"])
    op.create_index("idx_trusted_signer_issuer", "image_signing_trusted_signers", ["oidc_issuer"])

    # Verification results table
    op.create_table(
        "image_signing_verifications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("assessment_id", sa.String(36), nullable=True),
        sa.Column("image_ref", sa.String(500), nullable=False),
        sa.Column("image_digest", sa.String(100), nullable=True),
        sa.Column("signature_found", sa.Boolean, nullable=False),
        sa.Column("signature_valid", sa.Boolean, nullable=True),
        sa.Column("signer_identity", sa.String(255), nullable=True),
        sa.Column("signer_issuer", sa.String(255), nullable=True),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rekor_verified", sa.Boolean, nullable=True),
        sa.Column("slsa_level", sa.Integer, nullable=True),
        sa.Column("slsa_builder", sa.String(255), nullable=True),
        sa.Column("blocked", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("verification_error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_index("idx_verification_assessment_id", "image_signing_verifications", ["assessment_id"])
    op.create_index("idx_verification_image_ref", "image_signing_verifications", ["image_ref"])
    op.create_index("idx_verification_created_at", "image_signing_verifications", ["created_at"])
    op.create_index("idx_verification_assessment", "image_signing_verifications", ["assessment_id", "created_at"])


def downgrade() -> None:
    """Drop image signing tables."""
    op.drop_table("image_signing_verifications")
    op.drop_table("image_signing_trusted_signers")