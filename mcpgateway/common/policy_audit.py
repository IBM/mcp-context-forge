# -*- coding: utf-8 -*-
"""Policy Decision Audit Models - Extension to audit_trail_service.py

Location: mcpgateway/common/policy_audit.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Extends the existing audit_trail system with policy decision logging.
Integrates with issue #2225 requirements while using existing infrastructure.
"""

# Standard
from datetime import datetime, timezone
from typing import Any, Dict
import uuid

# Third-Party
from sqlalchemy import Boolean, Column, Float, Index, Integer, JSON, String, Text, TIMESTAMP

# First-Party
from mcpgateway.db import Base


class PolicyDecision(Base):
    """Policy decision audit log - extends audit_trail for policy-specific data.

    Integrates with existing mcpgateway/services/audit_trail_service.py
    """

    __tablename__ = "policy_decisions"

    # Primary key (String UUID for SQLite/PostgreSQL portability)
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Timestamps
    timestamp = Column(TIMESTAMP(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    # Request correlation
    request_id = Column(String(100), index=True)
    gateway_node = Column(String(100))

    # Subject (who is making the request)
    subject_type = Column(String(50))
    subject_id = Column(String(255), index=True)
    subject_email = Column(String(255), index=True)
    subject_roles = Column(JSON)
    subject_teams = Column(JSON)
    subject_clearance_level = Column(Integer)
    subject_data = Column(JSON)

    # Action
    action = Column(String(255), nullable=False, index=True)

    # Resource (what is being accessed)
    resource_type = Column(String(100), index=True)
    resource_id = Column(String(255), index=True)
    resource_server = Column(String(255))
    resource_classification = Column(Integer)
    resource_data = Column(JSON)

    # Decision
    decision = Column(String(20), nullable=False, index=True)
    reason = Column(Text)

    # Policy evaluation
    matching_policies = Column(JSON)
    policy_engines_used = Column(JSON)

    # Context
    ip_address = Column(String(45))
    user_agent = Column(Text)
    mfa_verified = Column(Boolean)
    geo_location = Column(JSON)
    context_data = Column(JSON)

    # Performance
    duration_ms = Column(Float)

    # Compliance & Security
    severity = Column(String(20))
    risk_score = Column(Integer)
    anomaly_detected = Column(Boolean, default=False)
    compliance_frameworks = Column(JSON)

    # Metadata (renamed from 'metadata' to avoid SQLAlchemy reserved attribute)
    extra_metadata = Column("metadata", JSON)

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
