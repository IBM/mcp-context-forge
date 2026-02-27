# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_jit_service.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Ioannis Ioannou

Tests for JIT access service.

Examples:
    >>> True
    True
"""

# Standard
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.db import JITGrant
from mcpgateway.services.jit_service import (
    JITGrantInvalidStatusError,
    JITGrantNotFoundError,
    JITService,
)


def make_grant(**kwargs) -> JITGrant:
    """Create a JITGrant instance for testing."""
    defaults = dict(
        id="test-grant-id",
        requester_email="dev@example.com",
        requested_role="incident-responder",
        justification="INC-123 production issue",
        duration_hours=2,
        ticket_url=None,
        status="pending",
        approved_by=None,
        approved_at=None,
        note=None,
        reject_reason=None,
        starts_at=None,
        expires_at=None,
        revoked_by=None,
        revoke_reason=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    defaults.update(kwargs)
    grant = JITGrant()
    for k, v in defaults.items():
        setattr(grant, k, v)
    return grant


@pytest.fixture
def db():
    """Mock database session."""
    return MagicMock()


@pytest.fixture
def service(db):
    """JITService instance with mock db."""
    return JITService(db)


class TestCreateGrant:
    """Tests for create_grant."""

    @pytest.mark.asyncio
    async def test_create_grant_success(self, service, db):
        """Test successful grant creation."""
        db.refresh = MagicMock()
        grant =             await service.create_grant(
                requester_email="dev@example.com",
                requested_role="incident-responder",
                justification="INC-123 prod issue",
                duration_hours=2,
        )
        assert grant.status == "pending"
        assert grant.requester_email == "dev@example.com"
        db.add.assert_called_once()
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_grant_exceeds_max_duration(self, service):
        """Test that exceeding max duration raises ValueError."""
        with pytest.raises(ValueError, match="Duration cannot exceed"):
                            await service.create_grant(
                    requester_email="dev@example.com",
                    requested_role="incident-responder",
                    justification="INC-123 prod issue",
                    duration_hours=9,
            )

    @pytest.mark.asyncio
    async def test_create_grant_with_ticket_url(self, service, db):
        """Test grant creation with ticket URL."""
        db.refresh = MagicMock()
        grant =             await service.create_grant(
                requester_email="dev@example.com",
                requested_role="incident-responder",
                justification="INC-123 prod issue",
                duration_hours=2,
                ticket_url="https://jira.example.com/INC-123",
        )
        assert grant.ticket_url == "https://jira.example.com/INC-123"


class TestApproveGrant:
    """Tests for approve_grant."""

    @pytest.mark.asyncio
    async def test_approve_pending_grant(self, service, db):
        """Test approving a pending grant."""
        grant = make_grant(status="pending")
        db.execute.return_value.scalar_one_or_none.return_value = grant
        db.refresh = MagicMock()

        result =             await service.approve_grant("test-grant-id", "admin@example.com", note="Approved")
        assert result.status == "active"
        assert result.approved_by == "admin@example.com"
        assert result.expires_at is not None

    @pytest.mark.asyncio
    async def test_approve_already_active_raises(self, service, db):
        """Test approving an already active grant raises error."""
        grant = make_grant(status="active")
        db.execute.return_value.scalar_one_or_none.return_value = grant

        with pytest.raises(JITGrantInvalidStatusError):
                            await service.approve_grant("test-grant-id", "admin@example.com")

    @pytest.mark.asyncio
    async def test_approve_nonexistent_grant_raises(self, service, db):
        """Test approving nonexistent grant raises error."""
        db.execute.return_value.scalar_one_or_none.return_value = None

        with pytest.raises(JITGrantNotFoundError):
                            await service.approve_grant("nonexistent", "admin@example.com")


class TestRejectGrant:
    """Tests for reject_grant."""

    @pytest.mark.asyncio
    async def test_reject_pending_grant(self, service, db):
        """Test rejecting a pending grant."""
        grant = make_grant(status="pending")
        db.execute.return_value.scalar_one_or_none.return_value = grant
        db.refresh = MagicMock()

        result =             await service.reject_grant("test-grant-id", "admin@example.com", "No active incident")
        assert result.status == "rejected"
        assert result.reject_reason == "No active incident"

    @pytest.mark.asyncio
    async def test_reject_active_grant_raises(self, service, db):
        """Test rejecting an active grant raises error."""
        grant = make_grant(status="active")
        db.execute.return_value.scalar_one_or_none.return_value = grant

        with pytest.raises(JITGrantInvalidStatusError):
                            await service.reject_grant("test-grant-id", "admin@example.com", "reason")


class TestRevokeGrant:
    """Tests for revoke_grant."""

    @pytest.mark.asyncio
    async def test_revoke_active_grant(self, service, db):
        """Test revoking an active grant."""
        grant = make_grant(status="active")
        db.execute.return_value.scalar_one_or_none.return_value = grant
        db.refresh = MagicMock()

        result =             await service.revoke_grant("test-grant-id", "admin@example.com", "Incident resolved")
        assert result.status == "revoked"
        assert result.revoked_by == "admin@example.com"
        assert result.revoke_reason == "Incident resolved"

    @pytest.mark.asyncio
    async def test_revoke_pending_grant_raises(self, service, db):
        """Test revoking a pending grant raises error."""
        grant = make_grant(status="pending")
        db.execute.return_value.scalar_one_or_none.return_value = grant

        with pytest.raises(JITGrantInvalidStatusError):
                            await service.revoke_grant("test-grant-id", "admin@example.com", "reason")


class TestExpireGrants:
    """Tests for expire_grants."""

    @pytest.mark.asyncio
    async def test_expire_grants_none_expired(self, service, db):
        """Test expiration when no grants have expired."""
        db.execute.return_value.scalars.return_value.all.return_value = []
        count = await service.expire_grants()
        assert count == 0

    @pytest.mark.asyncio
    async def test_expire_grants_some_expired(self, service, db):
        """Test expiration marks grants as expired."""
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        grant1 = make_grant(status="active", expires_at=past)
        grant2 = make_grant(status="active", expires_at=past, id="grant-2")
        db.execute.return_value.scalars.return_value.all.return_value = [grant1, grant2]

        count = await service.expire_grants()
        assert count == 2
        assert grant1.status == "expired"
        assert grant2.status == "expired"
        db.commit.assert_called_once()


class TestListGrants:
    """Tests for list_grants."""

    @pytest.mark.asyncio
    async def test_list_grants_no_filters(self, service, db):
        """Test listing grants without filters."""
        grants = [make_grant(), make_grant(id="grant-2")]
        db.execute.return_value.scalars.return_value.all.return_value = grants
        result = await service.list_grants()
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_list_grants_empty(self, service, db):
        """Test listing grants returns empty list."""
        db.execute.return_value.scalars.return_value.all.return_value = []
        result = await service.list_grants()
        assert result == []


class TestIsExpired:
    """Tests for JITGrant.is_expired."""

    @pytest.mark.asyncio
    async def test_not_expired_no_expiry(self):
        """Test grant with no expiry is not expired."""
        grant = make_grant(expires_at=None)
        assert grant.is_expired() is False

    @pytest.mark.asyncio
    async def test_not_expired_future(self):
        """Test grant with future expiry is not expired."""
        grant = make_grant(expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
        assert grant.is_expired() is False

    @pytest.mark.asyncio
    async def test_expired_past(self):
        """Test grant with past expiry is expired."""
        grant = make_grant(expires_at=datetime.now(timezone.utc) - timedelta(hours=1))
        assert grant.is_expired() is True
