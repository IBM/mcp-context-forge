# -*- coding: utf-8 -*-
"""Add LLM settings tables for internal LLM Chat feature.

Revision ID: l6f7g8h9i0j1
Revises: k5e6f7g8h9i0
Create Date: 2025-12-13 10:00:00.000000

"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "l6f7g8h9i0j1"
down_revision: Union[str, Sequence[str], None] = "k5e6f7g8h9i0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add LLM providers and models tables."""
    # Check if tables already exist
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if "llm_providers" not in existing_tables:
        op.create_table(
            "llm_providers",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("slug", sa.String(255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("provider_type", sa.String(50), nullable=False),
            sa.Column("api_key", sa.Text(), nullable=True),
            sa.Column("api_base", sa.String(512), nullable=True),
            sa.Column("api_version", sa.String(50), nullable=True),
            sa.Column("config", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("default_model", sa.String(255), nullable=True),
            sa.Column("default_temperature", sa.Float(), nullable=False, server_default="0.7"),
            sa.Column("default_max_tokens", sa.Integer(), nullable=True),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
            sa.Column("health_status", sa.String(20), nullable=False, server_default="'unknown'"),
            sa.Column("last_health_check", sa.DateTime(timezone=True), nullable=True),
            sa.Column("plugin_ids", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_by", sa.String(255), nullable=True),
            sa.Column("modified_by", sa.String(255), nullable=True),
            sa.UniqueConstraint("name", name="uq_llm_providers_name"),
            sa.UniqueConstraint("slug", name="uq_llm_providers_slug"),
        )

        # Create indexes for llm_providers
        op.create_index("idx_llm_providers_enabled", "llm_providers", ["enabled"])
        op.create_index("idx_llm_providers_type", "llm_providers", ["provider_type"])
        op.create_index("idx_llm_providers_health", "llm_providers", ["health_status"])

    if "llm_models" not in existing_tables:
        op.create_table(
            "llm_models",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("provider_id", sa.String(36), sa.ForeignKey("llm_providers.id", ondelete="CASCADE"), nullable=False),
            sa.Column("model_id", sa.String(255), nullable=False),
            sa.Column("model_name", sa.String(255), nullable=False),
            sa.Column("model_alias", sa.String(255), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("supports_chat", sa.Boolean(), nullable=False, server_default="1"),
            sa.Column("supports_streaming", sa.Boolean(), nullable=False, server_default="1"),
            sa.Column("supports_function_calling", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("supports_vision", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("context_window", sa.Integer(), nullable=True),
            sa.Column("max_output_tokens", sa.Integer(), nullable=True),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
            sa.Column("deprecated", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("provider_id", "model_id", name="uq_llm_models_provider_model"),
        )

        # Create indexes for llm_models
        op.create_index("idx_llm_models_provider", "llm_models", ["provider_id"])
        op.create_index("idx_llm_models_enabled", "llm_models", ["enabled"])
        op.create_index("idx_llm_models_deprecated", "llm_models", ["deprecated"])


def downgrade() -> None:
    """Remove LLM providers and models tables."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    # Drop indexes first
    if "llm_models" in existing_tables:
        try:
            existing_indexes = [idx["name"] for idx in inspector.get_indexes("llm_models")]
            for index_name in ["idx_llm_models_deprecated", "idx_llm_models_enabled", "idx_llm_models_provider"]:
                if index_name in existing_indexes:
                    op.drop_index(index_name, "llm_models")
        except Exception as e:
            print(f"Warning: Could not drop indexes for llm_models: {e}")

        op.drop_table("llm_models")

    if "llm_providers" in existing_tables:
        try:
            existing_indexes = [idx["name"] for idx in inspector.get_indexes("llm_providers")]
            for index_name in ["idx_llm_providers_health", "idx_llm_providers_type", "idx_llm_providers_enabled"]:
                if index_name in existing_indexes:
                    op.drop_index(index_name, "llm_providers")
        except Exception as e:
            print(f"Warning: Could not drop indexes for llm_providers: {e}")

        op.drop_table("llm_providers")
