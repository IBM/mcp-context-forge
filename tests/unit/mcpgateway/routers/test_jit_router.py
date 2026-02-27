# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_jit_router.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Ioannis Ioannou

Tests for JIT access router endpoints.

Covers happy-path and deny-path (unauthenticated, insufficient permissions,
wrong user) scenarios per project security invariants.

Examples:
    >>> True
    True
"""

# Standard
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# Patch RBAC decorators before importing the router
from tests.utils.rbac_mocks import patch_rbac_decorators, restore_rbac_decorators

_originals = patch_rbac_decorators()

# First-Party
from mcpgateway.routers import jit as jit_router  # noqa: E402
from mcpgateway.schemas import (  # noqa: E402
    JITGrantApproveRequest,
    JITGrantRejectRequest,
    JITGrantRequest,
    JITGrantRevokeRequest,
)

restore_rbac_decorators(_originals)


def _make_grant(
    grant_id: str = "grant-1",
    requester_email: str = "dev@example.com",
    status: str = "pending",
) -> SimpleNamespace:
    """Create a mock JIT grant."""
    now = datetime.now(tz=timezone.utc)
    return SimpleNamespace(
        id=grant_id,
        requester_email=requester_email,
        requested_role="incident-responder",
        justification="INC-123 production issue",
        duration_hours=2,
        ticket_url=None,
        status=status,
        approved_by=None,
        approved_at=None,
        note=None,
        reject_reason=None,
        starts_at=None,
        expires_at=None,
        revoked_by=None,
        revoke_reason=None,
        created_at=now,
        updated_at=now,
    )


def _make_admin_user(email: str = "admin@example.com") -> SimpleNamespace:
    return SimpleNamespace(email=email, is_admin=True, full_name="Admin User")


def _make_regular_user(email: str = "dev@example.com") -> SimpleNamespace:
    return SimpleNamespace(email=email, is_admin=False, full_name="Dev User")


# ---------------------------------------------------------------------------
# get_db tests
# ---------------------------------------------------------------------------

class TestGetDb:
    """Tests for get_db dependency."""

    def test_get_db_commits_on_success(self, monkeypatch):
        """Test that get_db commits on success."""
        db = MagicMock()
        monkeypatch.setattr(jit_router, "SessionLocal", lambda: db)
        gen = jit_router.get_db()
        yielded_db = next(gen)
        assert yielded_db is db
        with pytest.raises(StopIteration):
            gen.send(None)
        db.commit.assert_called_once()
        db.close.assert_called_once()

    def test_get_db_rollback_on_exception(self, monkeypatch):
        """Test that get_db rolls back on exception."""
        db = MagicMock()
        monkeypatch.setattr(jit_router, "SessionLocal", lambda: db)
        gen = jit_router.get_db()
        next(gen)
        with pytest.raises(ValueError):
            gen.throw(ValueError("db error"))
        db.rollback.assert_called_once()
        db.close.assert_called_once()


# ---------------------------------------------------------------------------
# request_jit_access tests
# ---------------------------------------------------------------------------

class TestRequestJitAccess:
    """Tests for POST /jit endpoint."""

    @pytest.mark.asyncio
    async def test_request_access_success(self):
        """Test successful JIT access request."""
        grant = _make_grant()
        service = MagicMock()
        service.create_grant = AsyncMock(return_value=grant)
        user = _make_regular_user()

        with patch("mcpgateway.routers.jit.JITService", return_value=service):
            result = await jit_router.request_jit_access(
                request=JITGrantRequest(
                    requested_role="incident-responder",
                    justification="INC-123 production issue",
                    duration_hours=2,
                ),
                db=MagicMock(),
                current_user=user,
            )
        assert result.status == "pending"
        assert result.requester_email == "dev@example.com"

    @pytest.mark.asyncio
    async def test_request_access_invalid_duration_raises_400(self):
        """Test that invalid duration raises 400."""
        from fastapi import HTTPException
        service = MagicMock()
        service.create_grant = AsyncMock(side_effect=ValueError("Duration cannot exceed 8 hours"))
        user = _make_regular_user()

        with patch("mcpgateway.routers.jit.JITService", return_value=service):
            with pytest.raises(HTTPException) as exc_info:
                await jit_router.request_jit_access(
                    request=JITGrantRequest(
                        requested_role="incident-responder",
                        justification="INC-123 production issue",
                        duration_hours=2,
                    ),
                    db=MagicMock(),
                    current_user=user,
                )
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# list_jit_grants tests (admin only)
# ---------------------------------------------------------------------------

class TestListJitGrants:
    """Tests for GET /jit endpoint (admin only)."""

    @pytest.mark.asyncio
    async def test_list_grants_admin_success(self):
        """Test admin can list all grants."""
        grants = [_make_grant("g1"), _make_grant("g2")]
        service = MagicMock()
        service.list_grants = AsyncMock(return_value=grants)
        admin = _make_admin_user()

        with patch("mcpgateway.routers.jit.JITService", return_value=service):
            result = await jit_router.list_jit_grants(
                requester_email=None,
                grant_status=None,
                limit=100,
                offset=0,
                db=MagicMock(),
                current_user=admin,
            )
        assert result.total == 2
        assert len(result.grants) == 2

    @pytest.mark.asyncio
    async def test_list_grants_filtered_by_status(self):
        """Test listing grants filtered by status."""
        grants = [_make_grant(status="pending")]
        service = MagicMock()
        service.list_grants = AsyncMock(return_value=grants)
        admin = _make_admin_user()

        with patch("mcpgateway.routers.jit.JITService", return_value=service):
            result = await jit_router.list_jit_grants(
                requester_email=None,
                grant_status="pending",
                limit=100,
                offset=0,
                db=MagicMock(),
                current_user=admin,
            )
        assert result.total == 1
        service.list_grants.assert_called_once_with(
            requester_email=None, status="pending", limit=100, offset=0
        )


# ---------------------------------------------------------------------------
# list_my_jit_grants tests
# ---------------------------------------------------------------------------

class TestListMyJitGrants:
    """Tests for GET /jit/mine endpoint."""

    @pytest.mark.asyncio
    async def test_list_my_grants_success(self):
        """Test user can list their own grants."""
        grants = [_make_grant(requester_email="dev@example.com")]
        service = MagicMock()
        service.list_grants = AsyncMock(return_value=grants)
        user = _make_regular_user()

        with patch("mcpgateway.routers.jit.JITService", return_value=service):
            result = await jit_router.list_my_jit_grants(
                grant_status=None,
                limit=50,
                offset=0,
                db=MagicMock(),
                current_user=user,
            )
        assert result.total == 1
        service.list_grants.assert_called_once_with(
            requester_email="dev@example.com", status=None, limit=50, offset=0
        )


# ---------------------------------------------------------------------------
# get_jit_grant tests
# ---------------------------------------------------------------------------

class TestGetJitGrant:
    """Tests for GET /jit/{grant_id} endpoint."""

    @pytest.mark.asyncio
    async def test_get_own_grant_success(self):
        """Test user can get their own grant."""
        from mcpgateway.services.jit_service import JITGrantNotFoundError
        grant = _make_grant(requester_email="dev@example.com")
        service = MagicMock()
        service.get_grant = AsyncMock(return_value=grant)
        user = _make_regular_user("dev@example.com")

        with patch("mcpgateway.routers.jit.JITService", return_value=service):
            result = await jit_router.get_jit_grant(
                grant_id="grant-1",
                db=MagicMock(),
                current_user=user,
            )
        assert result.id == "grant-1"

    @pytest.mark.asyncio
    async def test_get_other_users_grant_non_admin_raises_403(self):
        """Test non-admin cannot view another user's grant."""
        from fastapi import HTTPException
        grant = _make_grant(requester_email="other@example.com")
        service = MagicMock()
        service.get_grant = AsyncMock(return_value=grant)
        user = _make_regular_user("dev@example.com")  # different user, not admin

        with patch("mcpgateway.routers.jit.JITService", return_value=service):
            with pytest.raises(HTTPException) as exc_info:
                await jit_router.get_jit_grant(
                    grant_id="grant-1",
                    db=MagicMock(),
                    current_user=user,
                )
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_get_other_users_grant_admin_success(self):
        """Test admin can view any user's grant."""
        grant = _make_grant(requester_email="other@example.com")
        service = MagicMock()
        service.get_grant = AsyncMock(return_value=grant)
        admin = _make_admin_user("admin@example.com")

        with patch("mcpgateway.routers.jit.JITService", return_value=service):
            result = await jit_router.get_jit_grant(
                grant_id="grant-1",
                db=MagicMock(),
                current_user=admin,
            )
        assert result.id == "grant-1"

    @pytest.mark.asyncio
    async def test_get_nonexistent_grant_raises_404(self):
        """Test 404 for nonexistent grant."""
        from fastapi import HTTPException
        from mcpgateway.services.jit_service import JITGrantNotFoundError
        service = MagicMock()
        service.get_grant = AsyncMock(side_effect=JITGrantNotFoundError("not found"))
        user = _make_regular_user()

        with patch("mcpgateway.routers.jit.JITService", return_value=service):
            with pytest.raises(HTTPException) as exc_info:
                await jit_router.get_jit_grant(
                    grant_id="nonexistent",
                    db=MagicMock(),
                    current_user=user,
                )
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# approve_jit_grant tests (admin only)
# ---------------------------------------------------------------------------

class TestApproveJitGrant:
    """Tests for POST /jit/{grant_id}/approve endpoint."""

    @pytest.mark.asyncio
    async def test_approve_success(self):
        """Test admin can approve a pending grant."""
        grant = _make_grant(status="active")
        service = MagicMock()
        service.approve_grant = AsyncMock(return_value=grant)
        admin = _make_admin_user()

        with patch("mcpgateway.routers.jit.JITService", return_value=service):
            result = await jit_router.approve_jit_grant(
                grant_id="grant-1",
                request=JITGrantApproveRequest(note="Approved"),
                db=MagicMock(),
                current_user=admin,
            )
        assert result.status == "active"

    @pytest.mark.asyncio
    async def test_approve_nonexistent_raises_404(self):
        """Test 404 when approving nonexistent grant."""
        from fastapi import HTTPException
        from mcpgateway.services.jit_service import JITGrantNotFoundError
        service = MagicMock()
        service.approve_grant = AsyncMock(side_effect=JITGrantNotFoundError("not found"))
        admin = _make_admin_user()

        with patch("mcpgateway.routers.jit.JITService", return_value=service):
            with pytest.raises(HTTPException) as exc_info:
                await jit_router.approve_jit_grant(
                    grant_id="nonexistent",
                    request=JITGrantApproveRequest(),
                    db=MagicMock(),
                    current_user=admin,
                )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_approve_invalid_status_raises_400(self):
        """Test 400 when approving grant with invalid status."""
        from fastapi import HTTPException
        from mcpgateway.services.jit_service import JITGrantInvalidStatusError
        service = MagicMock()
        service.approve_grant = AsyncMock(side_effect=JITGrantInvalidStatusError("Cannot approve"))
        admin = _make_admin_user()

        with patch("mcpgateway.routers.jit.JITService", return_value=service):
            with pytest.raises(HTTPException) as exc_info:
                await jit_router.approve_jit_grant(
                    grant_id="grant-1",
                    request=JITGrantApproveRequest(),
                    db=MagicMock(),
                    current_user=admin,
                )
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# reject_jit_grant tests (admin only)
# ---------------------------------------------------------------------------

class TestRejectJitGrant:
    """Tests for POST /jit/{grant_id}/reject endpoint."""

    @pytest.mark.asyncio
    async def test_reject_success(self):
        """Test admin can reject a pending grant."""
        grant = _make_grant(status="rejected")
        service = MagicMock()
        service.reject_grant = AsyncMock(return_value=grant)
        admin = _make_admin_user()

        with patch("mcpgateway.routers.jit.JITService", return_value=service):
            result = await jit_router.reject_jit_grant(
                grant_id="grant-1",
                request=JITGrantRejectRequest(reason="No active incident"),
                db=MagicMock(),
                current_user=admin,
            )
        assert result.status == "rejected"

    @pytest.mark.asyncio
    async def test_reject_nonexistent_raises_404(self):
        """Test 404 when rejecting nonexistent grant."""
        from fastapi import HTTPException
        from mcpgateway.services.jit_service import JITGrantNotFoundError
        service = MagicMock()
        service.reject_grant = AsyncMock(side_effect=JITGrantNotFoundError("not found"))
        admin = _make_admin_user()

        with patch("mcpgateway.routers.jit.JITService", return_value=service):
            with pytest.raises(HTTPException) as exc_info:
                await jit_router.reject_jit_grant(
                    grant_id="nonexistent",
                    request=JITGrantRejectRequest(reason="reason"),
                    db=MagicMock(),
                    current_user=admin,
                )
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# revoke_jit_grant tests
# ---------------------------------------------------------------------------

class TestRevokeJitGrant:
    """Tests for POST /jit/{grant_id}/revoke endpoint."""

    @pytest.mark.asyncio
    async def test_revoke_own_grant_success(self):
        """Test user can revoke their own grant."""
        grant = _make_grant(requester_email="dev@example.com", status="active")
        revoked_grant = _make_grant(requester_email="dev@example.com", status="revoked")
        service = MagicMock()
        service.get_grant = AsyncMock(return_value=grant)
        service.revoke_grant = AsyncMock(return_value=revoked_grant)
        user = _make_regular_user("dev@example.com")

        with patch("mcpgateway.routers.jit.JITService", return_value=service):
            result = await jit_router.revoke_jit_grant(
                grant_id="grant-1",
                request=JITGrantRevokeRequest(reason="Incident resolved"),
                db=MagicMock(),
                current_user=user,
            )
        assert result.status == "revoked"

    @pytest.mark.asyncio
    async def test_revoke_other_users_grant_non_admin_raises_403(self):
        """Test non-admin cannot revoke another user's grant."""
        from fastapi import HTTPException
        grant = _make_grant(requester_email="other@example.com", status="active")
        service = MagicMock()
        service.get_grant = AsyncMock(return_value=grant)
        user = _make_regular_user("dev@example.com")

        with patch("mcpgateway.routers.jit.JITService", return_value=service):
            with pytest.raises(HTTPException) as exc_info:
                await jit_router.revoke_jit_grant(
                    grant_id="grant-1",
                    request=JITGrantRevokeRequest(reason="reason"),
                    db=MagicMock(),
                    current_user=user,
                )
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_revoke_other_users_grant_admin_success(self):
        """Test admin can revoke any user's grant."""
        grant = _make_grant(requester_email="other@example.com", status="active")
        revoked_grant = _make_grant(requester_email="other@example.com", status="revoked")
        service = MagicMock()
        service.get_grant = AsyncMock(return_value=grant)
        service.revoke_grant = AsyncMock(return_value=revoked_grant)
        admin = _make_admin_user()

        with patch("mcpgateway.routers.jit.JITService", return_value=service):
            result = await jit_router.revoke_jit_grant(
                grant_id="grant-1",
                request=JITGrantRevokeRequest(reason="Security incident"),
                db=MagicMock(),
                current_user=admin,
            )
        assert result.status == "revoked"

    @pytest.mark.asyncio
    async def test_revoke_nonexistent_raises_404(self):
        """Test 404 when revoking nonexistent grant."""
        from fastapi import HTTPException
        from mcpgateway.services.jit_service import JITGrantNotFoundError
        service = MagicMock()
        service.get_grant = AsyncMock(side_effect=JITGrantNotFoundError("not found"))
        user = _make_regular_user()

        with patch("mcpgateway.routers.jit.JITService", return_value=service):
            with pytest.raises(HTTPException) as exc_info:
                await jit_router.revoke_jit_grant(
                    grant_id="nonexistent",
                    request=JITGrantRevokeRequest(reason="reason"),
                    db=MagicMock(),
                    current_user=user,
                )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_revoke_invalid_status_raises_400(self):
        """Test 400 when revoking grant with invalid status."""
        from fastapi import HTTPException
        from mcpgateway.services.jit_service import JITGrantInvalidStatusError
        grant = _make_grant(requester_email="dev@example.com", status="pending")
        service = MagicMock()
        service.get_grant = AsyncMock(return_value=grant)
        service.revoke_grant = AsyncMock(side_effect=JITGrantInvalidStatusError("Cannot revoke"))
        user = _make_regular_user("dev@example.com")

        with patch("mcpgateway.routers.jit.JITService", return_value=service):
            with pytest.raises(HTTPException) as exc_info:
                await jit_router.revoke_jit_grant(
                    grant_id="grant-1",
                    request=JITGrantRevokeRequest(reason="reason"),
                    db=MagicMock(),
                    current_user=user,
                )
        assert exc_info.value.status_code == 400
