# -*- coding: utf-8 -*-
"""Policy Decision Logging Service - Extends audit_trail_service.py

Location: mcpgateway/services/policy_decision_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Integrates with existing audit_trail_service.py and SQLAlchemy infrastructure.
Addresses reviewer feedback from PR #2707.
"""

# Standard
from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional

# Third-Party
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.common.policy_audit import PolicyDecision
from mcpgateway.config import settings
from mcpgateway.db import SessionLocal

logger = logging.getLogger(__name__)


class PolicyDecisionService:
    """Service for logging and querying policy decisions.

    Integrates with existing mcpgateway infrastructure:
    - Uses sync SQLAlchemy sessions (matching audit_trail_service.py pattern)
    - Parameterized queries (no SQL injection)
    - Uses logging.getLogger instead of print()
    """

    def __init__(self):
        self._siem_processor = None

    def set_siem_processor(self, processor) -> None:
        """Attach a SIEMBatchProcessor for forwarding decisions to SIEM."""
        self._siem_processor = processor

    def log_decision(  # pylint: disable=too-many-positional-arguments
        self,
        *,
        action: str,
        decision: str,
        subject_id: Optional[str] = None,
        subject_email: Optional[str] = None,
        subject_type: str = "user",
        subject_roles: Optional[List[str]] = None,
        subject_teams: Optional[List[str]] = None,
        subject_clearance_level: Optional[int] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        resource_server: Optional[str] = None,
        resource_classification: Optional[int] = None,
        reason: Optional[str] = None,
        matching_policies: Optional[List[Dict]] = None,
        policy_engines_used: Optional[List[str]] = None,
        request_id: Optional[str] = None,
        gateway_node: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        mfa_verified: bool = False,
        duration_ms: Optional[float] = None,
        severity: str = "info",
        risk_score: int = 0,
        anomaly_detected: bool = False,
        compliance_frameworks: Optional[List[str]] = None,
        db: Optional[Session] = None,
        **kwargs,
    ) -> PolicyDecision:
        """Log a policy decision to the database.

        Always returns PolicyDecision - addresses reviewer feedback #5.

        Args:
            action: Action being performed (e.g., "tools.invoke")
            decision: Decision result ("allow", "deny", "not_applicable")
            db: Optional database session

        Returns:
            Created PolicyDecision record
        """
        if not settings.policy_audit_enabled:
            logger.debug("Policy decision logging is disabled")
            return PolicyDecision(
                action=action,
                decision=decision,
                timestamp=datetime.now(timezone.utc),
            )

        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            record = PolicyDecision(
                timestamp=datetime.now(timezone.utc),
                request_id=request_id,
                gateway_node=gateway_node,
                subject_type=subject_type,
                subject_id=subject_id,
                subject_email=subject_email,
                subject_roles=subject_roles,
                subject_teams=subject_teams,
                subject_clearance_level=subject_clearance_level,
                subject_data=kwargs.get("subject_data"),
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                resource_server=resource_server,
                resource_classification=resource_classification,
                resource_data=kwargs.get("resource_data"),
                decision=decision,
                reason=reason,
                matching_policies=matching_policies,
                policy_engines_used=policy_engines_used,
                ip_address=ip_address,
                user_agent=user_agent,
                mfa_verified=mfa_verified,
                geo_location=kwargs.get("geo_location"),
                context_data=kwargs.get("context_data"),
                duration_ms=duration_ms,
                severity=severity,
                risk_score=risk_score,
                anomaly_detected=anomaly_detected,
                compliance_frameworks=compliance_frameworks,
                extra_metadata=kwargs.get("metadata"),
            )

            db.add(record)
            db.commit()
            db.refresh(record)

            logger.info(
                f"Policy decision logged: {decision} for {action} by {subject_id or 'unknown'}",
                extra={
                    "decision_id": str(record.id),
                    "decision": decision,
                    "action": action,
                    "subject_id": subject_id,
                },
            )

            # Queue to SIEM if processor is set
            if self._siem_processor is not None:
                try:
                    # Standard
                    import asyncio  # pylint: disable=import-outside-toplevel

                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        loop.create_task(self._siem_processor.add(record))
                    else:
                        asyncio.run(self._siem_processor.add(record))
                except Exception as siem_err:
                    logger.warning(f"Failed to queue policy decision to SIEM: {siem_err}")

            return record

        except Exception as e:
            logger.error(f"Failed to log policy decision: {e}", exc_info=True)
            if close_db:
                db.rollback()
            return PolicyDecision(
                action=action,
                decision=decision,
                timestamp=datetime.now(timezone.utc),
            )

        finally:
            if close_db:
                db.close()

    def query_decisions(
        self,
        *,
        subject_email: Optional[str] = None,
        subject_id: Optional[str] = None,
        resource_id: Optional[str] = None,
        resource_type: Optional[str] = None,
        action: Optional[str] = None,
        decision: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        severity: Optional[str] = None,
        min_risk_score: Optional[int] = None,
        limit: int = 100,
        offset: int = 0,
        sort_by: str = "timestamp",
        sort_order: str = "desc",
        db: Optional[Session] = None,
    ) -> List[PolicyDecision]:
        """Query policy decisions with filters.

        Uses parameterized queries - addresses reviewer feedback #2 (SQL injection).
        """
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            query = select(PolicyDecision)
            conditions = []

            if subject_email:
                conditions.append(PolicyDecision.subject_email == subject_email)
            if subject_id:
                conditions.append(PolicyDecision.subject_id == subject_id)
            if resource_id:
                conditions.append(PolicyDecision.resource_id == resource_id)
            if resource_type:
                conditions.append(PolicyDecision.resource_type == resource_type)
            if action:
                conditions.append(PolicyDecision.action == action)
            if decision:
                conditions.append(PolicyDecision.decision == decision)
            if start_time:
                conditions.append(PolicyDecision.timestamp >= start_time)
            if end_time:
                conditions.append(PolicyDecision.timestamp <= end_time)
            if severity:
                conditions.append(PolicyDecision.severity == severity)
            if min_risk_score is not None:
                conditions.append(PolicyDecision.risk_score >= min_risk_score)

            if conditions:
                query = query.where(and_(*conditions))

            # Validate sort column (allowlist approach - addresses feedback #2)
            allowed_sort_columns = {
                "timestamp",
                "action",
                "decision",
                "severity",
                "risk_score",
                "subject_email",
                "resource_type",
            }

            if sort_by not in allowed_sort_columns:
                logger.warning(f"Invalid sort_by column '{sort_by}', using 'timestamp'")
                sort_by = "timestamp"

            if sort_order not in ("asc", "desc"):
                logger.warning(f"Invalid sort_order '{sort_order}', using 'desc'")
                sort_order = "desc"

            sort_column = getattr(PolicyDecision, sort_by)
            if sort_order == "desc":
                query = query.order_by(sort_column.desc())
            else:
                query = query.order_by(sort_column.asc())

            query = query.limit(limit).offset(offset)

            result = db.execute(query)
            return list(result.scalars().all())

        finally:
            if close_db:
                db.commit()
                db.close()

    def get_statistics(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        db: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """Get statistics about policy decisions."""
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            conditions = []
            if start_time:
                conditions.append(PolicyDecision.timestamp >= start_time)
            if end_time:
                conditions.append(PolicyDecision.timestamp <= end_time)

            # Total decisions
            query = select(func.count(PolicyDecision.id))
            if conditions:
                query = query.where(and_(*conditions))
            result = db.execute(query)
            total = result.scalar() or 0

            # Decisions by type
            query = select(PolicyDecision.decision, func.count(PolicyDecision.id)).group_by(PolicyDecision.decision)
            if conditions:
                query = query.where(and_(*conditions))
            result = db.execute(query)
            decisions_by_type = {row[0]: row[1] for row in result}

            # Average duration
            query = select(func.avg(PolicyDecision.duration_ms))
            if conditions:
                query = query.where(and_(*conditions))
            result = db.execute(query)
            avg_duration = result.scalar() or 0.0

            return {
                "total_decisions": total,
                "allowed": decisions_by_type.get("allow", 0),
                "denied": decisions_by_type.get("deny", 0),
                "avg_duration_ms": float(avg_duration),
                "time_range": {
                    "start": start_time.isoformat() if start_time else None,
                    "end": end_time.isoformat() if end_time else None,
                },
            }

        finally:
            if close_db:
                db.commit()
                db.close()


# Global service instance
policy_decision_service = PolicyDecisionService()
