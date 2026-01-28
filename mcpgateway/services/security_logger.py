# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/security_logger.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Security Logger Service.

This module provides specialized logging for security events, threat detection,
and audit trail management with automated threat analysis and alerting.
"""

# Standard
from datetime import datetime, timedelta, timezone
from enum import Enum
import logging
from typing import Any, Dict, Optional

# Third-Party
from sqlalchemy import func, select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import AuditTrail, SecurityEvent, SessionLocal
from mcpgateway.utils.correlation_id import get_correlation_id

logger = logging.getLogger(__name__)


class SecuritySeverity(str, Enum):
    """Security event severity levels."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class SecurityEventType(str, Enum):
    """Types of security events."""

    AUTHENTICATION_FAILURE = "authentication_failure"
    AUTHENTICATION_SUCCESS = "authentication_success"
    AUTHORIZATION_FAILURE = "authorization_failure"
    SUSPICIOUS_ACTIVITY = "suspicious_activity"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    BRUTE_FORCE_ATTEMPT = "brute_force_attempt"
    TOKEN_MANIPULATION = "token_manipulation"  # nosec B105 - Not a password, security event type constant
    DATA_EXFILTRATION = "data_exfiltration"
    PRIVILEGE_ESCALATION = "privilege_escalation"
    INJECTION_ATTEMPT = "injection_attempt"
    ANOMALOUS_BEHAVIOR = "anomalous_behavior"


class SecurityLogger:
    """Specialized logger for security events and audit trails.

    Provides threat detection, security event logging, and audit trail
    management with automated analysis and alerting capabilities.
    """

    def __init__(self):
        """Initialize security logger."""
        self.failed_auth_threshold = getattr(settings, "security_failed_auth_threshold", 5)
        self.threat_score_alert_threshold = getattr(settings, "security_threat_score_alert", 0.7)
        self.rate_limit_window_minutes = getattr(settings, "security_rate_limit_window", 5)

    def log_authentication_attempt(
        self,
        user_id: str,
        user_email: Optional[str],
        auth_method: str,
        success: bool,
        client_ip: str,
        user_agent: Optional[str] = None,
        failure_reason: Optional[str] = None,
        additional_context: Optional[Dict[str, Any]] = None,
        db: Optional[Session] = None,
    ) -> Optional[SecurityEvent]:
        """Log authentication attempts with security analysis.

        Args:
            user_id: User identifier
            user_email: User email address
            auth_method: Authentication method used
            success: Whether authentication succeeded
            client_ip: Client IP address
            user_agent: Client user agent
            failure_reason: Reason for failure if applicable
            additional_context: Additional event context
            db: Optional database session

        Returns:
            Created SecurityEvent or None if logging disabled
        """
        correlation_id = get_correlation_id()

        # Count recent failed attempts
        failed_attempts = self._count_recent_failures(user_id=user_id, client_ip=client_ip, db=db)

        # Calculate threat score
        threat_score = self._calculate_auth_threat_score(success=success, failed_attempts=failed_attempts, auth_method=auth_method)

        # Determine severity
        if not success:
            if failed_attempts >= self.failed_auth_threshold:
                severity = SecuritySeverity.HIGH
            elif failed_attempts >= 3:
                severity = SecuritySeverity.MEDIUM
            else:
                severity = SecuritySeverity.LOW
        else:
            severity = SecuritySeverity.LOW

        # Build event description
        description = f"Authentication {'successful' if success else 'failed'} for user {user_id}"
        if not success and failure_reason:
            description += f": {failure_reason}"

        # Build context
        context = {"auth_method": auth_method, "failed_attempts_recent": failed_attempts, "user_agent": user_agent, **(additional_context or {})}

        # Create security event
        event = self._create_security_event(
            event_type=SecurityEventType.AUTHENTICATION_SUCCESS if success else SecurityEventType.AUTHENTICATION_FAILURE,
            severity=severity,
            category="authentication",
            user_id=user_id,
            user_email=user_email,
            client_ip=client_ip,
            user_agent=user_agent,
            description=description,
            threat_score=threat_score,
            failed_attempts_count=failed_attempts,
            context=context,
            action_taken="allowed" if success else "denied",
            correlation_id=correlation_id,
            db=db,
        )

        # Log to standard logger as well
        log_level = logging.WARNING if not success else logging.INFO
        logger.log(
            log_level,
            f"Authentication attempt: {description}",
            extra={
                "security_event": True,
                "event_type": event.event_type if event else None,
                "severity": severity.value,
                "threat_score": threat_score,
                "correlation_id": correlation_id,
            },
        )

        return event

    def log_data_access(  # pylint: disable=too-many-positional-arguments
        self,
        action: str,
        resource_type: str,
        resource_id: str,
        resource_name: Optional[str],
        user_id: str,
        user_email: Optional[str],
        team_id: Optional[str],
        client_ip: Optional[str],
        user_agent: Optional[str],
        success: bool,
        data_classification: Optional[str] = None,
        old_values: Optional[Dict[str, Any]] = None,
        new_values: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
        additional_context: Optional[Dict[str, Any]] = None,
        db: Optional[Session] = None,
    ) -> Optional[AuditTrail]:
        """Log data access for audit trails.

        Args:
            action: Action performed (create, read, update, delete, execute)
            resource_type: Type of resource accessed
            resource_id: Resource identifier
            resource_name: Resource name
            user_id: User performing the action
            user_email: User email
            team_id: Team context
            client_ip: Client IP address
            user_agent: Client user agent
            success: Whether action succeeded
            data_classification: Data sensitivity classification
            old_values: Previous values (for updates)
            new_values: New values (for updates/creates)
            error_message: Error message if failed
            additional_context: Additional context
            db: Optional database session

        Returns:
            Created AuditTrail entry or None
        """
        correlation_id = get_correlation_id()

        # Determine if audit requires review
        requires_review = self._requires_audit_review(action=action, resource_type=resource_type, data_classification=data_classification, success=success)

        # Calculate changes
        changes = None
        if old_values and new_values:
            changes = {k: {"old": old_values.get(k), "new": new_values.get(k)} for k in set(old_values.keys()) | set(new_values.keys()) if old_values.get(k) != new_values.get(k)}

        # Create audit trail
        audit = self._create_audit_trail(
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            resource_name=resource_name,
            user_id=user_id,
            user_email=user_email,
            team_id=team_id,
            client_ip=client_ip,
            user_agent=user_agent,
            success=success,
            old_values=old_values,
            new_values=new_values,
            changes=changes,
            data_classification=data_classification,
            requires_review=requires_review,
            error_message=error_message,
            context=additional_context,
            correlation_id=correlation_id,
            db=db,
        )

        # Log sensitive data access as security event
        if data_classification in ["confidential", "restricted", "sensitive"]:
            self._create_security_event(
                event_type="data_access",
                severity=SecuritySeverity.MEDIUM if success else SecuritySeverity.HIGH,
                category="data_access",
                user_id=user_id,
                user_email=user_email,
                client_ip=client_ip or "unknown",
                user_agent=user_agent,
                description=f"Access to {data_classification} {resource_type}: {resource_name or resource_id}",
                threat_score=0.3 if success else 0.6,
                context={
                    "action": action,
                    "resource_type": resource_type,
                    "resource_id": resource_id,
                    "data_classification": data_classification,
                },
                correlation_id=correlation_id,
                db=db,
            )

        return audit

    def log_suspicious_activity(
        self,
        activity_type: str,
        description: str,
        user_id: Optional[str],
        user_email: Optional[str],
        client_ip: str,
        user_agent: Optional[str],
        threat_score: float,
        severity: SecuritySeverity,
        threat_indicators: Dict[str, Any],
        action_taken: str,
        additional_context: Optional[Dict[str, Any]] = None,
        db: Optional[Session] = None,
    ) -> Optional[SecurityEvent]:
        """Log suspicious activity with threat analysis.

        Args:
            activity_type: Type of suspicious activity
            description: Event description
            user_id: User identifier (if known)
            user_email: User email (if known)
            client_ip: Client IP address
            user_agent: Client user agent
            threat_score: Calculated threat score (0.0-1.0)
            severity: Event severity
            threat_indicators: Dictionary of threat indicators
            action_taken: Action taken in response
            additional_context: Additional context
            db: Optional database session

        Returns:
            Created SecurityEvent or None
        """
        correlation_id = get_correlation_id()

        event = self._create_security_event(
            event_type=SecurityEventType.SUSPICIOUS_ACTIVITY,
            severity=severity,
            category="suspicious_activity",
            user_id=user_id,
            user_email=user_email,
            client_ip=client_ip,
            user_agent=user_agent,
            description=description,
            threat_score=threat_score,
            threat_indicators=threat_indicators,
            action_taken=action_taken,
            context=additional_context,
            correlation_id=correlation_id,
            db=db,
        )

        logger.warning(
            f"Suspicious activity detected: {description}",
            extra={
                "security_event": True,
                "activity_type": activity_type,
                "severity": severity.value,
                "threat_score": threat_score,
                "action_taken": action_taken,
                "correlation_id": correlation_id,
            },
        )

        return event

    def _count_recent_failures(self, user_id: Optional[str] = None, client_ip: Optional[str] = None, minutes: Optional[int] = None, db: Optional[Session] = None) -> int:
        """Count recent authentication failures.

        Args:
            user_id: User identifier
            client_ip: Client IP address
            minutes: Time window in minutes
            db: Optional database session

        Returns:
            Count of recent failures
        """
        if not user_id and not client_ip:
            return 0

        window_minutes = minutes or self.rate_limit_window_minutes
        since = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)

        should_close = False
        if db is None:
            db = SessionLocal()
            should_close = True

        try:
            stmt = select(func.count(SecurityEvent.id)).where(SecurityEvent.event_type == SecurityEventType.AUTHENTICATION_FAILURE, SecurityEvent.timestamp >= since)  # pylint: disable=not-callable

            if user_id:
                stmt = stmt.where(SecurityEvent.user_id == user_id)
            if client_ip:
                stmt = stmt.where(SecurityEvent.client_ip == client_ip)

            result = db.execute(stmt).scalar()
            return result or 0

        finally:
            if should_close:
                db.commit()  # End read-only transaction cleanly
                db.close()

    def _calculate_auth_threat_score(self, success: bool, failed_attempts: int, auth_method: str) -> float:  # pylint: disable=unused-argument
        """Calculate threat score for authentication attempt.

        Args:
            success: Whether authentication succeeded
            failed_attempts: Count of recent failures
            auth_method: Authentication method used

        Returns:
            Threat score from 0.0 to 1.0
        """
        if success:
            return 0.0

        # Base score for failure
        score = 0.3

        # Increase based on failed attempts
        if failed_attempts >= 10:
            score += 0.5
        elif failed_attempts >= 5:
            score += 0.3
        elif failed_attempts >= 3:
            score += 0.2

        # Cap at 1.0
        return min(score, 1.0)

    def _requires_audit_review(self, action: str, resource_type: str, data_classification: Optional[str], success: bool) -> bool:
        """Determine if audit entry requires manual review.

        Args:
            action: Action performed
            resource_type: Resource type
            data_classification: Data classification
            success: Whether action succeeded

        Returns:
            True if review required
        """
        # Failed actions on sensitive data require review
        if not success and data_classification in ["confidential", "restricted"]:
            return True

        # Deletions of sensitive data require review
        if action == "delete" and data_classification in ["confidential", "restricted"]:
            return True

        # Privilege modifications require review
        if resource_type in ["role", "permission", "team_member"]:
            return True

        return False

    def _create_security_event(
        self,
        event_type: str,
        severity: SecuritySeverity,
        category: str,
        client_ip: str,
        description: str,
        threat_score: float,
        user_id: Optional[str] = None,
        user_email: Optional[str] = None,
        user_agent: Optional[str] = None,
        action_taken: Optional[str] = None,
        failed_attempts_count: int = 0,
        threat_indicators: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> Optional[SecurityEvent]:
        """Create a security event record.

        Args:
            event_type: Type of security event
            severity: Event severity
            category: Event category
            client_ip: Client IP address
            description: Event description
            threat_score: Threat score (0.0-1.0)
            user_id: User identifier
            user_email: User email
            user_agent: User agent string
            action_taken: Action taken
            failed_attempts_count: Failed attempts count
            threat_indicators: Threat indicators
            context: Additional context
            correlation_id: Correlation ID
            db: Optional database session

        Returns:
            Created SecurityEvent or None
        """
        should_close = False
        if db is None:
            db = SessionLocal()
            should_close = True

        try:
            event = SecurityEvent(
                event_type=event_type,
                severity=severity.value,
                category=category,
                user_id=user_id,
                user_email=user_email,
                client_ip=client_ip,
                user_agent=user_agent,
                description=description,
                action_taken=action_taken,
                threat_score=threat_score,
                threat_indicators=threat_indicators or {},
                failed_attempts_count=failed_attempts_count,
                context=context,
                correlation_id=correlation_id,
            )

            db.add(event)
            db.commit()
            db.refresh(event)

            return event

        except Exception as e:
            logger.error(f"Failed to create security event: {e}")
            db.rollback()
            return None

        finally:
            if should_close:
                db.close()

    def _create_audit_trail(  # pylint: disable=too-many-positional-arguments
        self,
        action: str,
        resource_type: str,
        user_id: str,
        success: bool,
        resource_id: Optional[str] = None,
        resource_name: Optional[str] = None,
        user_email: Optional[str] = None,
        team_id: Optional[str] = None,
        client_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        old_values: Optional[Dict[str, Any]] = None,
        new_values: Optional[Dict[str, Any]] = None,
        changes: Optional[Dict[str, Any]] = None,
        data_classification: Optional[str] = None,
        requires_review: bool = False,
        error_message: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> Optional[AuditTrail]:
        """Create an audit trail record.

        Args:
            action: Action performed
            resource_type: Resource type
            user_id: User performing action
            success: Whether action succeeded
            resource_id: Resource identifier
            resource_name: Resource name
            user_email: User email
            team_id: Team context
            client_ip: Client IP
            user_agent: User agent
            old_values: Previous values
            new_values: New values
            changes: Calculated changes
            data_classification: Data classification
            requires_review: Whether manual review needed
            error_message: Error message if failed
            context: Additional context
            correlation_id: Correlation ID
            db: Optional database session

        Returns:
            Created AuditTrail or None
        """
        should_close = False
        if db is None:
            db = SessionLocal()
            should_close = True

        try:
            audit = AuditTrail(
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                resource_name=resource_name,
                user_id=user_id,
                user_email=user_email,
                team_id=team_id,
                client_ip=client_ip,
                user_agent=user_agent,
                old_values=old_values,
                new_values=new_values,
                changes=changes,
                data_classification=data_classification,
                requires_review=requires_review,
                success=success,
                error_message=error_message,
                context=context,
                correlation_id=correlation_id,
            )

            db.add(audit)
            db.commit()
            db.refresh(audit)

            return audit

        except Exception as e:
            logger.error(f"Failed to create audit trail: {e}")
            db.rollback()
            return None

        finally:
            if should_close:
                db.close()


# Global security logger instance
_security_logger: Optional[SecurityLogger] = None


def get_security_logger() -> SecurityLogger:
    """Get or create the global security logger instance.

    Returns:
        Global SecurityLogger instance
    """
    global _security_logger  # pylint: disable=global-statement
    if _security_logger is None:
        _security_logger = SecurityLogger()
    return _security_logger
