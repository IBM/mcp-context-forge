# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/jit_service.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Ioannis Ioannou

Just-in-Time (JIT) Access Service.

This module provides the business logic for JIT access grant management,
including request creation, approval workflows, and automatic expiration.

Examples:
    >>> from unittest.mock import Mock
    >>> service = JITService(Mock())
    >>> isinstance(service, JITService)
    True
"""

# Standard
from datetime import timedelta
import logging
from typing import List, Optional

# Third-Party
from sqlalchemy import select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import JITGrant, utc_now

logger = logging.getLogger(__name__)


class JITGrantNotFoundError(Exception):
    """Raised when a JIT grant is not found.

    Examples:
        >>> e = JITGrantNotFoundError("abc-123")
        >>> str(e)
        'abc-123'
    """


class JITGrantInvalidStatusError(Exception):
    """Raised when an action is invalid for the current grant status.

    Examples:
        >>> e = JITGrantInvalidStatusError("Cannot approve an active grant")
        >>> str(e)
        'Cannot approve an active grant'
    """


class JITService:
    """Service for managing Just-in-Time access grants.

    Handles the full lifecycle of JIT grants: request, approve,
    reject, revoke, and automatic expiration.

    Attributes:
        db: SQLAlchemy database session

    Examples:
        >>> from unittest.mock import Mock
        >>> service = JITService(Mock())
        >>> service.__class__.__name__
        'JITService'
        >>> hasattr(service, 'db')
        True
    """

    MAX_DURATION_HOURS = 8
    DEFAULT_DURATION_HOURS = 4

    def __init__(self, db: Session):
        """Initialize JIT service.

        Args:
            db: Database session

        Examples:
            >>> from unittest.mock import Mock
            >>> db = Mock()
            >>> service = JITService(db)
            >>> service.db is db
            True
        """
        self.db = db

    async def create_grant(
        self,
        requester_email: str,
        requested_role: str,
        justification: str,
        duration_hours: int = DEFAULT_DURATION_HOURS,
        ticket_url: Optional[str] = None,
    ) -> JITGrant:
        """Create a new JIT access grant request.

        Args:
            requester_email: Email of the user requesting access
            requested_role: Role being requested
            justification: Reason for the access request
            duration_hours: Duration in hours (1-8)
            ticket_url: Optional URL to incident ticket

        Returns:
            The created JITGrant instance

        Raises:
            ValueError: If duration_hours exceeds maximum

        Examples:
            >>> from unittest.mock import Mock, MagicMock
            >>> db = MagicMock()
            >>> service = JITService(db)
            >>> import asyncio
            >>> grant = asyncio.get_event_loop().run_until_complete(
            ...     service.create_grant("dev@example.com", "incident-responder", "INC-123 issue", 2)
            ... )
            >>> grant.status
            'pending'
            >>> grant.requester_email
            'dev@example.com'
        """
        if duration_hours > self.MAX_DURATION_HOURS:
            raise ValueError(f"Duration cannot exceed {self.MAX_DURATION_HOURS} hours")

        grant = JITGrant(
            requester_email=requester_email,
            requested_role=requested_role,
            justification=justification,
            duration_hours=duration_hours,
            ticket_url=ticket_url,
            status="pending",
        )
        self.db.add(grant)
        self.db.commit()
        self.db.refresh(grant)
        logger.info("JIT grant created: %s by %s for role %s", grant.id, requester_email, requested_role)
        return grant

    async def approve_grant(self, grant_id: str, approver_email: str, note: Optional[str] = None) -> JITGrant:
        """Approve a pending JIT grant and activate it immediately.

        Args:
            grant_id: ID of the grant to approve
            approver_email: Email of the approving admin
            note: Optional approval note

        Returns:
            The updated JITGrant instance

        Raises:
            JITGrantNotFoundError: If grant does not exist
            JITGrantInvalidStatusError: If grant is not in pending status

        Examples:
            >>> from unittest.mock import Mock, MagicMock, patch
            >>> db = MagicMock()
            >>> service = JITService(db)
            >>> service.__class__.__name__
            'JITService'
        """
        grant = self._get_grant(grant_id)
        if grant.status != "pending":
            raise JITGrantInvalidStatusError(f"Cannot approve grant with status '{grant.status}'")

        now = utc_now()
        grant.status = "active"
        grant.approved_by = approver_email
        grant.approved_at = now
        grant.note = note
        grant.starts_at = now
        grant.expires_at = now + timedelta(hours=grant.duration_hours)
        grant.updated_at = now

        self.db.commit()
        self.db.refresh(grant)
        logger.info("JIT grant %s approved by %s, expires at %s", grant_id, approver_email, grant.expires_at)
        return grant

    async def reject_grant(self, grant_id: str, approver_email: str, reason: str) -> JITGrant:
        """Reject a pending JIT grant.

        Args:
            grant_id: ID of the grant to reject
            approver_email: Email of the rejecting admin
            reason: Reason for rejection

        Returns:
            The updated JITGrant instance

        Raises:
            JITGrantNotFoundError: If grant does not exist
            JITGrantInvalidStatusError: If grant is not in pending status

        Examples:
            >>> from unittest.mock import MagicMock
            >>> service = JITService(MagicMock())
            >>> service.__class__.__name__
            'JITService'
        """
        grant = self._get_grant(grant_id)
        if grant.status != "pending":
            raise JITGrantInvalidStatusError(f"Cannot reject grant with status '{grant.status}'")

        now = utc_now()
        grant.status = "rejected"
        grant.approved_by = approver_email
        grant.reject_reason = reason
        grant.updated_at = now

        self.db.commit()
        self.db.refresh(grant)
        logger.info("JIT grant %s rejected by %s", grant_id, approver_email)
        return grant

    async def revoke_grant(self, grant_id: str, revoker_email: str, reason: str) -> JITGrant:
        """Revoke an active JIT grant.

        Args:
            grant_id: ID of the grant to revoke
            revoker_email: Email of the user revoking access
            reason: Reason for revocation

        Returns:
            The updated JITGrant instance

        Raises:
            JITGrantNotFoundError: If grant does not exist
            JITGrantInvalidStatusError: If grant is not active

        Examples:
            >>> from unittest.mock import MagicMock
            >>> service = JITService(MagicMock())
            >>> service.__class__.__name__
            'JITService'
        """
        grant = self._get_grant(grant_id)
        if grant.status != "active":
            raise JITGrantInvalidStatusError(f"Cannot revoke grant with status '{grant.status}'")

        now = utc_now()
        grant.status = "revoked"
        grant.revoked_by = revoker_email
        grant.revoke_reason = reason
        grant.updated_at = now

        self.db.commit()
        self.db.refresh(grant)
        logger.info("JIT grant %s revoked by %s: %s", grant_id, revoker_email, reason)
        return grant

    async def get_grant(self, grant_id: str) -> JITGrant:
        """Get a JIT grant by ID.

        Args:
            grant_id: ID of the grant

        Returns:
            The JITGrant instance

        Raises:
            JITGrantNotFoundError: If grant does not exist

        Examples:
            >>> from unittest.mock import MagicMock
            >>> service = JITService(MagicMock())
            >>> service.__class__.__name__
            'JITService'
        """
        return self._get_grant(grant_id)

    async def list_grants(
        self,
        requester_email: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[JITGrant]:
        """List JIT grants with optional filters.

        Args:
            requester_email: Filter by requester email
            status: Filter by status
            limit: Maximum number of results
            offset: Pagination offset

        Returns:
            List of JITGrant instances

        Examples:
            >>> from unittest.mock import MagicMock
            >>> db = MagicMock()
            >>> db.execute.return_value.scalars.return_value.all.return_value = []
            >>> service = JITService(db)
            >>> service.__class__.__name__
            'JITService'
        """
        query = select(JITGrant)
        if requester_email:
            query = query.where(JITGrant.requester_email == requester_email)
        if status:
            query = query.where(JITGrant.status == status)
        query = query.order_by(JITGrant.created_at.desc()).limit(limit).offset(offset)
        result = self.db.execute(query)
        return list(result.scalars().all())

    async def expire_grants(self) -> int:
        """Expire all active grants that have passed their expiry time.

        Returns:
            Number of grants expired

        Examples:
            >>> from unittest.mock import MagicMock
            >>> db = MagicMock()
            >>> db.execute.return_value.scalars.return_value.all.return_value = []
            >>> service = JITService(db)
            >>> import asyncio
            >>> count = asyncio.get_event_loop().run_until_complete(service.expire_grants())
            >>> count
            0
        """
        now = utc_now()
        query = select(JITGrant).where(
            JITGrant.status == "active",
            JITGrant.expires_at <= now,
        )
        expired = list(self.db.execute(query).scalars().all())
        for grant in expired:
            grant.status = "expired"
            grant.updated_at = now
        if expired:
            self.db.commit()
            logger.info("Expired %d JIT grants", len(expired))
        return len(expired)

    def _get_grant(self, grant_id: str) -> JITGrant:
        """Fetch a grant by ID or raise JITGrantNotFoundError.

        Args:
            grant_id: Grant ID to look up

        Returns:
            JITGrant instance

        Raises:
            JITGrantNotFoundError: If not found

        Examples:
            >>> from unittest.mock import MagicMock
            >>> db = MagicMock()
            >>> db.execute.return_value.scalar_one_or_none.return_value = None
            >>> service = JITService(db)
            >>> try:
            ...     service._get_grant("nonexistent")
            ... except Exception as e:
            ...     type(e).__name__
            'JITGrantNotFoundError'
        """
        result = self.db.execute(select(JITGrant).where(JITGrant.id == grant_id))
        grant = result.scalar_one_or_none()
        if not grant:
            raise JITGrantNotFoundError(f"JIT grant '{grant_id}' not found")
        return grant
