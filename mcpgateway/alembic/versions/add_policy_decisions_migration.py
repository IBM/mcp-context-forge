"""Add policy_decisions table

Revision ID: add_policy_decisions
Revises: b1b2b3b4b5b6
Create Date: 2026-02-10

Adds policy decision logging to extend audit_trail functionality.
Implements issue #2225.
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "add_policy_decisions"
down_revision: Union[str, Sequence[str], None] = "b1b2b3b4b5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create policy_decisions table."""
    inspector = sa.inspect(op.get_bind())

    # Skip if table already exists (idempotent)
    if "policy_decisions" in inspector.get_table_names():
        return

    op.create_table(
        "policy_decisions",
        # Primary key
        sa.Column("id", sa.String(36), primary_key=True),
        # Timestamps
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        # Request correlation
        sa.Column("request_id", sa.String(100), index=True),
        sa.Column("gateway_node", sa.String(100)),
        # Subject (who)
        sa.Column("subject_type", sa.String(50)),
        sa.Column("subject_id", sa.String(255), index=True),
        sa.Column("subject_email", sa.String(255), index=True),
        sa.Column("subject_roles", sa.JSON),
        sa.Column("subject_teams", sa.JSON),
        sa.Column("subject_clearance_level", sa.Integer),
        sa.Column("subject_data", sa.JSON),
        # Action
        sa.Column("action", sa.String(255), nullable=False, index=True),
        # Resource (what)
        sa.Column("resource_type", sa.String(100), index=True),
        sa.Column("resource_id", sa.String(255), index=True),
        sa.Column("resource_server", sa.String(255)),
        sa.Column("resource_classification", sa.Integer),
        sa.Column("resource_data", sa.JSON),
        # Decision
        sa.Column("decision", sa.String(20), nullable=False, index=True),
        sa.Column("reason", sa.Text),
        # Policy evaluation
        sa.Column("matching_policies", sa.JSON),
        sa.Column("policy_engines_used", sa.JSON),
        # Context
        sa.Column("ip_address", sa.String(45)),
        sa.Column("user_agent", sa.Text),
        sa.Column("mfa_verified", sa.Boolean),
        sa.Column("geo_location", sa.JSON),
        sa.Column("context_data", sa.JSON),
        # Performance
        sa.Column("duration_ms", sa.Float),
        # Compliance & Security
        sa.Column("severity", sa.String(20)),
        sa.Column("risk_score", sa.Integer),
        sa.Column("anomaly_detected", sa.Boolean, default=False),
        sa.Column("compliance_frameworks", sa.JSON),
        # Metadata
        sa.Column("metadata", sa.JSON),
    )

    # Create composite indexes for common queries
    op.create_index("idx_policy_decision_subject", "policy_decisions", ["subject_id", "subject_email"])
    op.create_index("idx_policy_decision_resource", "policy_decisions", ["resource_type", "resource_id"])
    op.create_index("idx_policy_decision_action_decision", "policy_decisions", ["action", "decision"])


def downgrade() -> None:
    """Remove policy_decisions table."""
    inspector = sa.inspect(op.get_bind())

    if "policy_decisions" not in inspector.get_table_names():
        return

    op.drop_index("idx_policy_decision_action_decision", "policy_decisions")
    op.drop_index("idx_policy_decision_resource", "policy_decisions")
    op.drop_index("idx_policy_decision_subject", "policy_decisions")
    op.drop_table("policy_decisions")
