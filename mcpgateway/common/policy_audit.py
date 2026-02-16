# -*- coding: utf-8 -*-
"""Policy Decision Audit Models - Extension to audit_trail_service.py

Location: mcpgateway/common/policy_audit.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Extends the existing audit_trail system with policy decision logging.
Integrates with issue #2225 requirements while using existing infrastructure.
"""

# Standard
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid

# Third-Party
from sqlalchemy import Boolean, DateTime, Float, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

# First-Party
from mcpgateway.db import Base


class PolicyDecision(Base):
    """Policy decision audit log - extends audit_trail for policy-specific data.

    Integrates with existing mcpgateway/services/audit_trail_service.py
    """

    __tablename__ = "policy_decisions"

    # Primary key (String UUID for SQLite/PostgreSQL portability)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Timestamps (indexed via idx_policy_decision_timestamp in __table_args__)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    # Request correlation (indexed via idx_policy_decision_request in __table_args__)
    request_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    gateway_node: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Subject (who is making the request)
    # subject_id is leading column of composite idx_policy_decision_subject
    subject_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    subject_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    subject_email: Mapped[Optional[str]] = mapped_column(String(255), index=True, nullable=True)
    subject_roles: Mapped[Optional[List]] = mapped_column(JSON, nullable=True)
    subject_teams: Mapped[Optional[List]] = mapped_column(JSON, nullable=True)
    subject_clearance_level: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    subject_data: Mapped[Optional[Dict]] = mapped_column(JSON, nullable=True)

    # Action (leading column of composite idx_policy_decision_action_decision)
    action: Mapped[str] = mapped_column(String(255), nullable=False)

    # Resource (what is being accessed)
    # resource_type is leading column of composite idx_policy_decision_resource
    resource_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    resource_id: Mapped[Optional[str]] = mapped_column(String(255), index=True, nullable=True)
    resource_server: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    resource_classification: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    resource_data: Mapped[Optional[Dict]] = mapped_column(JSON, nullable=True)

    # Decision (trailing column of composite idx_policy_decision_action_decision)
    decision: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Policy evaluation
    matching_policies: Mapped[Optional[List]] = mapped_column(JSON, nullable=True)
    policy_engines_used: Mapped[Optional[List]] = mapped_column(JSON, nullable=True)

    # Context
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    mfa_verified: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    geo_location: Mapped[Optional[Dict]] = mapped_column(JSON, nullable=True)
    context_data: Mapped[Optional[Dict]] = mapped_column(JSON, nullable=True)

    # Performance
    duration_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Compliance & Security
    severity: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    risk_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    anomaly_detected: Mapped[Optional[bool]] = mapped_column(Boolean, default=False, nullable=True)
    compliance_frameworks: Mapped[Optional[List]] = mapped_column(JSON, nullable=True)

    # Metadata (column named 'metadata' in DB, attribute renamed to avoid SQLAlchemy reserved name)
    extra_metadata: Mapped[Optional[Dict]] = mapped_column("metadata", JSON, nullable=True)

    # Indexes for common queries
    __table_args__ = (
        Index("idx_policy_decision_timestamp", "timestamp"),
        Index("idx_policy_decision_subject", "subject_id", "subject_email"),
        Index("idx_policy_decision_resource", "resource_type", "resource_id"),
        Index("idx_policy_decision_action_decision", "action", "decision"),
        Index("idx_policy_decision_request", "request_id"),
        Index("idx_policy_decision_severity", "severity"),
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary matching issue #2225 schema."""
        return {
            "id": str(self.id),
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "request_id": self.request_id,
            "gateway_node": self.gateway_node,
            "subject": (
                {
                    "type": self.subject_type,
                    "id": self.subject_id,
                    "email": self.subject_email,
                    "roles": self.subject_roles or [],
                    "teams": self.subject_teams or [],
                    "clearance_level": self.subject_clearance_level,
                    **(self.subject_data or {}),
                }
                if self.subject_id
                else None
            ),
            "action": self.action,
            "resource": (
                {
                    "type": self.resource_type,
                    "id": self.resource_id,
                    "server": self.resource_server,
                    "classification": self.resource_classification,
                    **(self.resource_data or {}),
                }
                if self.resource_id
                else None
            ),
            "decision": self.decision,
            "reason": self.reason,
            "matching_policies": self.matching_policies or [],
            "context": self.context_data,
            "duration_ms": self.duration_ms,
            "metadata": {
                "severity": self.severity,
                "risk_score": self.risk_score,
                "anomaly_detected": self.anomaly_detected,
                "compliance_frameworks": self.compliance_frameworks,
                **(self.extra_metadata or {}),
            },
        }

    def to_splunk_hec(self) -> Dict[str, Any]:
        """Convert to Splunk HTTP Event Collector format."""
        return {
            "time": int(self.timestamp.timestamp()) if self.timestamp else None,
            "host": self.gateway_node or "unknown",
            "source": "mcp-policy-engine",
            "sourcetype": "policy_decision",
            "event": self.to_dict(),
        }

    def to_elasticsearch(self) -> Dict[str, Any]:
        """Convert to Elasticsearch document format."""
        doc = self.to_dict()
        doc["@timestamp"] = self.timestamp.isoformat() if self.timestamp else None
        doc["event_type"] = "policy_decision"
        return doc

    def to_webhook(self) -> Dict[str, Any]:
        """Generic webhook format."""
        return {
            "event_type": "policy.decision",
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "data": self.to_dict(),
        }
