# -*- coding: utf-8 -*-
"""
Location: ./plugins/security_clearance/repository.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Katia Neli

ClearanceRepository — DB access layer for Bell-LaPadula MAC.
Every method has a silent fallback: if the DB is unavailable it returns
None and the plugin uses the YAML config as fallback.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from plugins.security_clearance.models import (
    SCClearanceAuditLog,
    SCServerClassification,
    SCTeamClearance,
    SCToolClassification,
    SCUserClearance,
)

logger = logging.getLogger(__name__)


class ClearanceRepository:
    """Read and write clearance data from the database."""

    # User clearance
    def get_user_clearance(
        self, db: Session, user_id: str, tenant_id: Optional[str] = None
    ) -> Optional[int]:
        """Return user clearance level or None if not found."""
        try:
            q = db.query(SCUserClearance).filter(
                SCUserClearance.user_id == user_id,
                SCUserClearance.is_active.is_(True),
            )
            if tenant_id:
                q = q.filter(SCUserClearance.tenant_id == tenant_id)
            row = q.first()
            if row:
                if row.expires_at and row.expires_at < datetime.now(timezone.utc):
                    return None
                return row.clearance_level
        except Exception as exc:
            logger.debug("DB user clearance lookup failed: %s", exc)
        return None

    # Team clearance
    def get_team_clearance(
        self, db: Session, team_id: str, tenant_id: Optional[str] = None
    ) -> Optional[int]:
        """Return team clearance level or None if not found."""
        try:
            q = db.query(SCTeamClearance).filter(
                SCTeamClearance.team_id == team_id,
                SCTeamClearance.is_active.is_(True),
            )
            if tenant_id:
                q = q.filter(SCTeamClearance.tenant_id == tenant_id)
            row = q.first()
            return row.clearance_level if row else None
        except Exception as exc:
            logger.debug("DB team clearance lookup failed: %s", exc)
        return None

    # Tool classification
    def get_tool_classification(
        self,
        db: Session,
        tool_name: str,
        server_name: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> Optional[int]:
        """Return tool classification level or None if not found."""
        try:
            q = db.query(SCToolClassification).filter(
                SCToolClassification.tool_name == tool_name,
                SCToolClassification.is_active.is_(True),
            )
            if server_name:
                q = q.filter(SCToolClassification.server_name == server_name)
            if tenant_id:
                q = q.filter(SCToolClassification.tenant_id == tenant_id)
            row = q.first()
            return row.classification_level if row else None
        except Exception as exc:
            logger.debug("DB tool classification lookup failed: %s", exc)
        return None

    # Server classification
    def get_server_classification(
        self, db: Session, server_name: str, tenant_id: Optional[str] = None
    ) -> Optional[int]:
        """Return server classification level or None if not found."""
        try:
            q = db.query(SCServerClassification).filter(
                SCServerClassification.server_name == server_name,
                SCServerClassification.is_active.is_(True),
            )
            if tenant_id:
                q = q.filter(SCServerClassification.tenant_id == tenant_id)
            row = q.first()
            return row.classification_level if row else None
        except Exception as exc:
            logger.debug("DB server classification lookup failed: %s", exc)
        return None

    # Audit log
    def write_audit_log(
        self,
        db: Session,
        *,
        user_id: Optional[str],
        tenant_id: Optional[str],
        request_id: Optional[str],
        user_clearance: int,
        resource_type: str,
        resource_name: Optional[str],
        resource_level: int,
        decision: str,
        violation_type: Optional[str] = None,
        hook: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Write an audit log entry. Silent fallback if DB is unavailable."""
        try:
            entry = SCClearanceAuditLog(
                user_id=user_id,
                tenant_id=tenant_id,
                request_id=request_id,
                user_clearance=user_clearance,
                resource_type=resource_type,
                resource_name=resource_name,
                resource_level=resource_level,
                decision=decision,
                violation_type=violation_type,
                hook=hook,
                extra=extra,
            )
            db.add(entry)
            db.commit()
        except Exception as exc:
            logger.warning("Audit log write failed: %s", exc)
            try:
                db.rollback()
            except Exception:
                pass

    # Audit trail
    def get_audit_trail(
        self,
        db: Session,
        *,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        decision: Optional[str] = None,
        limit: int = 100,
    ) -> list:
        """Return audit log entries filtered by user, tenant, or decision.

        Args:
            db: SQLAlchemy Session.
            user_id: Filter by user ID.
            tenant_id: Filter by tenant ID.
            decision: Filter by decision (ALLOW or DENY).
            limit: Maximum number of rows to return.

        Returns:
            List of SCClearanceAuditLog instances.
        """
        try:
            q = db.query(SCClearanceAuditLog).order_by(
                SCClearanceAuditLog.timestamp.desc()
            )
            if user_id:
                q = q.filter(SCClearanceAuditLog.user_id == user_id)
            if tenant_id:
                q = q.filter(SCClearanceAuditLog.tenant_id == tenant_id)
            if decision:
                q = q.filter(SCClearanceAuditLog.decision == decision)
            return q.limit(limit).all()
        except Exception as exc:
            logger.debug("Audit trail query failed: %s", exc)
            return []