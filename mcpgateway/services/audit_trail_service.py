# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/audit_trail_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Audit Trail Service.

This module provides audit trail management for CRUD operations,
data access tracking, and compliance logging.
"""

# Standard
from datetime import datetime, timezone
from enum import Enum
import logging
from typing import Any, Dict, Optional

# Third-Party
from sqlalchemy import select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import AuditTrail, SessionLocal
from mcpgateway.utils.correlation_id import get_or_generate_correlation_id

logger = logging.getLogger(__name__)


class AuditAction(str, Enum):
    """Audit trail action types."""

    CREATE = "CREATE"
    READ = "READ"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    EXECUTE = "EXECUTE"
    ACCESS = "ACCESS"
    EXPORT = "EXPORT"
    IMPORT = "IMPORT"


class DataClassification(str, Enum):
    """Data classification levels."""

    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


REVIEW_REQUIRED_ACTIONS = {
    "delete_server",
    "delete_tool",
    "delete_resource",
    "delete_gateway",
    "update_sensitive_config",
    "bulk_delete",
}


class AuditTrailService:
    """Service for managing audit trails and compliance logging.

    Provides comprehensive audit trail management with data classification,
    change tracking, and compliance reporting capabilities.
    """

    def __init__(self):
        """Initialize audit trail service."""

    def log_action(  # pylint: disable=too-many-positional-arguments
        self,
        action: str,
        resource_type: str,
        resource_id: str,
        user_id: str,
        user_email: Optional[str] = None,
        team_id: Optional[str] = None,
        resource_name: Optional[str] = None,
        client_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        request_path: Optional[str] = None,
        request_method: Optional[str] = None,
        old_values: Optional[Dict[str, Any]] = None,
        new_values: Optional[Dict[str, Any]] = None,
        changes: Optional[Dict[str, Any]] = None,
        data_classification: Optional[str] = None,
        requires_review: Optional[bool] = None,
        success: bool = True,
        error_message: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        details: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        db: Optional[Session] = None,
    ) -> Optional[AuditTrail]:
        """Log an audit trail entry.

        Args:
            action: Action performed (CREATE, READ, UPDATE, DELETE, etc.)
            resource_type: Type of resource (tool, server, prompt, etc.)
            resource_id: ID of the resource
            user_id: User who performed the action
            user_email: User's email address
            team_id: Team ID if applicable
            resource_name: Name of the resource
            client_ip: Client IP address
            user_agent: Client user agent
            request_path: HTTP request path
            request_method: HTTP request method
            old_values: Previous values before change
            new_values: New values after change
            changes: Specific changes made
            data_classification: Data classification level
            requires_review: Whether this action requires review (None = auto)
            success: Whether the action succeeded
            error_message: Error message if failed
            context: Additional context
            details: Extra key/value payload (stored under context.details)
            metadata: Extra metadata payload (stored under context.metadata)
            db: Optional database session

        Returns:
            Created AuditTrail entry or None if logging disabled
        """
        # Check if audit trail logging is enabled
        if not settings.audit_trail_enabled:
            return None

        correlation_id = get_or_generate_correlation_id()

        # Use provided session or create new one
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            context_payload: Dict[str, Any] = dict(context) if context else {}
            if details:
                context_payload["details"] = details
            if metadata:
                context_payload["metadata"] = metadata
            context_value = context_payload if context_payload else None

            requires_review_flag = self._determine_requires_review(
                action=action,
                data_classification=data_classification,
                requires_review_param=requires_review,
            )

            # Create audit trail entry
            audit_entry = AuditTrail(
                timestamp=datetime.now(timezone.utc),
                correlation_id=correlation_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                resource_name=resource_name,
                user_id=user_id,
                user_email=user_email,
                team_id=team_id,
                client_ip=client_ip,
                user_agent=user_agent,
                request_path=request_path,
                request_method=request_method,
                old_values=old_values,
                new_values=new_values,
                changes=changes,
                data_classification=data_classification,
                requires_review=requires_review_flag,
                success=success,
                error_message=error_message,
                context=context_value,
            )

            db.add(audit_entry)
            db.commit()
            db.refresh(audit_entry)

            logger.debug(
                f"Audit trail logged: {action} {resource_type}/{resource_id} by {user_id}",
                extra={"correlation_id": correlation_id, "action": action, "resource_type": resource_type, "resource_id": resource_id, "user_id": user_id, "success": success},
            )

            return audit_entry

        except Exception as e:
            logger.error(f"Failed to log audit trail: {e}", exc_info=True, extra={"correlation_id": correlation_id, "action": action, "resource_type": resource_type, "resource_id": resource_id})
            if close_db:
                db.rollback()
            return None

        finally:
            if close_db:
                db.close()

    def _determine_requires_review(
        self,
        action: Optional[str],
        data_classification: Optional[str],
        requires_review_param: Optional[bool],
    ) -> bool:
        """Resolve whether an audit entry should require review.

        Args:
            action: Action being performed
            data_classification: Data classification level
            requires_review_param: Explicit review requirement

        Returns:
            bool: Whether the audit entry requires review
        """
        if requires_review_param is not None:
            return requires_review_param

        if data_classification in {DataClassification.CONFIDENTIAL.value, DataClassification.RESTRICTED.value}:
            return True

        normalized_action = (action or "").lower()
        if normalized_action in REVIEW_REQUIRED_ACTIONS:
            return True

        return False

    def log_crud_operation(
        self,
        operation: str,
        resource_type: str,
        resource_id: str,
        user_id: str,
        user_email: Optional[str] = None,
        team_id: Optional[str] = None,
        resource_name: Optional[str] = None,
        old_values: Optional[Dict[str, Any]] = None,
        new_values: Optional[Dict[str, Any]] = None,
        success: bool = True,
        error_message: Optional[str] = None,
        db: Optional[Session] = None,
        **kwargs,
    ) -> Optional[AuditTrail]:
        """Log a CRUD operation with change tracking.

        Args:
            operation: CRUD operation (CREATE, READ, UPDATE, DELETE)
            resource_type: Type of resource
            resource_id: ID of the resource
            user_id: User who performed the operation
            user_email: User's email
            team_id: Team ID if applicable
            resource_name: Name of the resource
            old_values: Previous values (for UPDATE/DELETE)
            new_values: New values (for CREATE/UPDATE)
            success: Whether the operation succeeded
            error_message: Error message if failed
            db: Optional database session
            **kwargs: Additional arguments passed to log_action

        Returns:
            Created AuditTrail entry
        """
        # Calculate changes for UPDATE operations
        changes = None
        if operation == "UPDATE" and old_values and new_values:
            changes = {}
            for key in set(old_values.keys()) | set(new_values.keys()):
                old_val = old_values.get(key)
                new_val = new_values.get(key)
                if old_val != new_val:
                    changes[key] = {"old": old_val, "new": new_val}

        # Determine data classification based on resource type
        data_classification = None
        if resource_type in ["user", "team", "token", "credential"]:
            data_classification = DataClassification.CONFIDENTIAL.value
        elif resource_type in ["tool", "server", "prompt", "resource"]:
            data_classification = DataClassification.INTERNAL.value

        # Determine if review is required
        requires_review = False
        if data_classification == DataClassification.CONFIDENTIAL.value:
            requires_review = True
        if operation == "DELETE" and resource_type in ["tool", "server", "gateway"]:
            requires_review = True

        return self.log_action(
            action=operation,
            resource_type=resource_type,
            resource_id=resource_id,
            user_id=user_id,
            user_email=user_email,
            team_id=team_id,
            resource_name=resource_name,
            old_values=old_values,
            new_values=new_values,
            changes=changes,
            data_classification=data_classification,
            requires_review=requires_review,
            success=success,
            error_message=error_message,
            db=db,
            **kwargs,
        )

    def log_data_access(
        self,
        resource_type: str,
        resource_id: str,
        user_id: str,
        access_type: str = "READ",
        user_email: Optional[str] = None,
        team_id: Optional[str] = None,
        resource_name: Optional[str] = None,
        data_classification: Optional[str] = None,
        db: Optional[Session] = None,
        **kwargs,
    ) -> Optional[AuditTrail]:
        """Log data access for compliance tracking.

        Args:
            resource_type: Type of resource accessed
            resource_id: ID of the resource
            user_id: User who accessed the data
            access_type: Type of access (READ, EXPORT, etc.)
            user_email: User's email
            team_id: Team ID if applicable
            resource_name: Name of the resource
            data_classification: Data classification level
            db: Optional database session
            **kwargs: Additional arguments passed to log_action

        Returns:
            Created AuditTrail entry
        """
        requires_review = data_classification in [DataClassification.CONFIDENTIAL.value, DataClassification.RESTRICTED.value]

        return self.log_action(
            action=access_type,
            resource_type=resource_type,
            resource_id=resource_id,
            user_id=user_id,
            user_email=user_email,
            team_id=team_id,
            resource_name=resource_name,
            data_classification=data_classification,
            requires_review=requires_review,
            success=True,
            db=db,
            **kwargs,
        )

    def log_audit(
        self, user_id: str, resource_type: str, resource_id: str, action: str, user_email: Optional[str] = None, description: Optional[str] = None, db: Optional[Session] = None, **kwargs
    ) -> Optional[AuditTrail]:
        """Convenience method for simple audit logging.

        Args:
            user_id: User who performed the action
            resource_type: Type of resource
            resource_id: ID of the resource
            action: Action performed
            user_email: User's email
            description: Description of the action
            db: Optional database session
            **kwargs: Additional arguments passed to log_action

        Returns:
            Created AuditTrail entry
        """
        # Build context if description provided
        context = kwargs.pop("context", {})
        if description:
            context["description"] = description

        return self.log_action(action=action, resource_type=resource_type, resource_id=resource_id, user_id=user_id, user_email=user_email, context=context if context else None, db=db, **kwargs)

    def get_audit_trail(
        self,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        user_id: Optional[str] = None,
        action: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
        db: Optional[Session] = None,
    ) -> list[AuditTrail]:
        """Query audit trail entries.

        Args:
            resource_type: Filter by resource type
            resource_id: Filter by resource ID
            user_id: Filter by user ID
            action: Filter by action
            start_time: Filter by start time
            end_time: Filter by end time
            limit: Maximum number of results
            offset: Offset for pagination
            db: Optional database session

        Returns:
            List of AuditTrail entries
        """
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            query = select(AuditTrail)

            if resource_type:
                query = query.where(AuditTrail.resource_type == resource_type)
            if resource_id:
                query = query.where(AuditTrail.resource_id == resource_id)
            if user_id:
                query = query.where(AuditTrail.user_id == user_id)
            if action:
                query = query.where(AuditTrail.action == action)
            if start_time:
                query = query.where(AuditTrail.timestamp >= start_time)
            if end_time:
                query = query.where(AuditTrail.timestamp <= end_time)

            query = query.order_by(AuditTrail.timestamp.desc())
            query = query.limit(limit).offset(offset)

            result = db.execute(query)
            return list(result.scalars().all())

        finally:
            if close_db:
                db.commit()  # End read-only transaction cleanly
                db.close()


# Singleton instance
_audit_trail_service: Optional[AuditTrailService] = None


def get_audit_trail_service() -> AuditTrailService:
    """Get or create the singleton audit trail service instance.

    Returns:
        AuditTrailService instance
    """
    global _audit_trail_service  # pylint: disable=global-statement
    if _audit_trail_service is None:
        _audit_trail_service = AuditTrailService()
    return _audit_trail_service
