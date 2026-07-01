# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_role_service_race_conditions.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Unit tests for role service IntegrityError race condition handling.

These tests use mocks to simulate database constraint violations without
requiring a real database with unique constraints.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from sqlalchemy.exc import IntegrityError
import uuid

# First-Party
from mcpgateway.services.role_service import RoleService
from mcpgateway.db import Role, UserRole


@pytest.mark.asyncio
async def test_create_role_success_path():
    """Test successful role creation (no IntegrityError).

    Covers role_service.py lines 231, 237, 239-240:
    - Add role inside savepoint or regular add
    - Commit and refresh
    - Log and return created role
    """
    mock_db = MagicMock()

    # Mock begin_nested to work (use context manager)
    mock_savepoint = MagicMock()
    mock_savepoint.__enter__ = MagicMock(return_value=mock_savepoint)
    mock_savepoint.__exit__ = MagicMock(return_value=None)
    mock_db.begin_nested.return_value = mock_savepoint

    role_service = RoleService(mock_db)

    # Mock get_role_by_name to return None (no duplicate)
    async def mock_get_role(name: str, scope: str):
        return None
    role_service.get_role_by_name = mock_get_role

    # Call create_role - should succeed without IntegrityError
    result = await role_service.create_role(
        name="new-role",
        description="New role",
        scope="global",
        permissions=["tools.read"],
        created_by="admin@example.com"
    )

    # Verify success path
    assert result is not None
    assert result.name == "new-role"

    # Verify add was called inside savepoint (line 231)
    mock_db.add.assert_called_once()

    # Verify commit and refresh were called (lines 236-237)
    mock_db.commit.assert_called_once()
    mock_db.refresh.assert_called_once()


@pytest.mark.asyncio
async def test_create_role_handles_integrity_error_and_refetches():
    """Test that create_role handles IntegrityError and refetches existing role.

    Covers role_service.py lines 244-250:
    - Rollback after IntegrityError
    - Log concurrent creation
    - Refetch and return existing role
    """
    mock_db = MagicMock()
    mock_db.begin_nested.side_effect = AttributeError  # Simulate no savepoint support

    # Create mock winner role
    winner_role = Role(
        id=str(uuid.uuid4()),
        name="test-role",
        description="Winner role",
        scope="global",
        permissions=["tools.read"],
        created_by="admin@example.com",
        is_system_role=False,
        is_active=True
    )

    role_service = RoleService(mock_db)

    # Mock get_role_by_name to simulate race window then successful refetch
    call_count = [0]
    async def mock_get_role(name: str, scope: str):
        call_count[0] += 1
        if call_count[0] == 1:
            # First call during duplicate check - return None (race window)
            return None
        # Second call after IntegrityError - return winner role
        return winner_role

    role_service.get_role_by_name = mock_get_role

    # Mock commit to raise IntegrityError
    mock_db.commit.side_effect = IntegrityError("UNIQUE constraint failed", {}, None)

    # Call create_role - should catch IntegrityError and refetch
    result = await role_service.create_role(
        name="test-role",
        description="Loser role",
        scope="global",
        permissions=["tools.read"],
        created_by="other@example.com"
    )

    # Verify IntegrityError was handled
    assert result is not None
    assert result.id == winner_role.id
    assert result.description == "Winner role"
    assert call_count[0] == 2  # Initial check + refetch

    # Verify rollback was called (line 244)
    mock_db.rollback.assert_called_once()


@pytest.mark.asyncio
async def test_create_role_raises_error_when_refetch_fails():
    """Test that create_role raises ValueError when refetch returns None.

    Covers role_service.py lines 253-254:
    - Error logging
    - Raise ValueError when role not found after IntegrityError
    """
    mock_db = MagicMock()
    mock_db.begin_nested.side_effect = AttributeError

    role_service = RoleService(mock_db)

    # Mock get_role_by_name to always return None
    async def mock_get_role(name: str, scope: str):
        return None

    role_service.get_role_by_name = mock_get_role

    # Mock commit to raise IntegrityError
    mock_db.commit.side_effect = IntegrityError("UNIQUE constraint failed", {}, None)

    # Call create_role - should raise ValueError
    with pytest.raises(ValueError, match="Failed to create or fetch role"):
        await role_service.create_role(
            name="mystery-role",
            description="Mystery role",
            scope="global",
            permissions=["tools.read"],
            created_by="admin@example.com"
        )

    # Verify rollback was called
    mock_db.rollback.assert_called_once()


@pytest.mark.asyncio
async def test_assign_role_success_path():
    """Test successful role assignment (no IntegrityError).

    Covers role_service.py lines 660, 666, 668-669:
    - Add user_role inside savepoint or regular add
    - Commit and refresh
    - Log and return assignment
    """
    mock_db = MagicMock()

    # Mock begin_nested to work
    mock_savepoint = MagicMock()
    mock_savepoint.__enter__ = MagicMock(return_value=mock_savepoint)
    mock_savepoint.__exit__ = MagicMock(return_value=None)
    mock_db.begin_nested.return_value = mock_savepoint

    mock_role = Role(
        id=str(uuid.uuid4()),
        name="test-role",
        description="Test role",
        scope="team",
        permissions=["tools.read"],
        created_by="admin@example.com",
        is_system_role=False,
        is_active=True
    )

    role_service = RoleService(mock_db)

    # Mock get_role_by_id
    async def mock_get_role_by_id(role_id: str):
        return mock_role
    role_service.get_role_by_id = mock_get_role_by_id

    # Mock get_user_role_assignment to return None (no existing assignment)
    async def mock_get_assignment(user_email: str, role_id: str, scope: str, scope_id: str):
        return None
    role_service.get_user_role_assignment = mock_get_assignment

    # Call assign_role_to_user - should succeed
    result = await role_service.assign_role_to_user(
        user_email="user@example.com",
        role_id=mock_role.id,
        scope="team",
        scope_id="team-123",
        granted_by="admin@example.com"
    )

    # Verify success path
    assert result is not None
    assert result.user_email == "user@example.com"

    # Verify add was called inside savepoint (line 660)
    mock_db.add.assert_called_once()

    # Verify commit and refresh were called (lines 665-666)
    mock_db.commit.assert_called_once()
    mock_db.refresh.assert_called_once()


@pytest.mark.asyncio
async def test_assign_role_handles_integrity_error_and_refetches():
    """Test that assign_role_to_user handles IntegrityError and refetches existing assignment.

    Covers role_service.py lines 673-679:
    - Rollback after IntegrityError
    - Log concurrent assignment
    - Refetch and return existing assignment
    """
    mock_db = MagicMock()
    mock_db.begin_nested.side_effect = AttributeError

    # Create mock role and assignment
    mock_role = Role(
        id=str(uuid.uuid4()),
        name="test-role",
        description="Test role",
        scope="team",
        permissions=["tools.read"],
        created_by="admin@example.com",
        is_system_role=False,
        is_active=True
    )

    winner_assignment = UserRole(
        id=str(uuid.uuid4()),
        user_email="user@example.com",
        role_id=mock_role.id,
        scope="team",
        scope_id="team-123",
        granted_by="admin@example.com",
        is_active=True
    )

    role_service = RoleService(mock_db)

    # Mock get_role_by_id to return the role
    async def mock_get_role_by_id(role_id: str):
        return mock_role
    role_service.get_role_by_id = mock_get_role_by_id

    # Mock get_user_role_assignment to simulate race window then successful refetch
    call_count = [0]
    async def mock_get_assignment(user_email: str, role_id: str, scope: str, scope_id: str):
        call_count[0] += 1
        if call_count[0] == 1:
            # First call during duplicate check - return None (race window)
            return None
        # Second call after IntegrityError - return winner assignment
        return winner_assignment

    role_service.get_user_role_assignment = mock_get_assignment

    # Mock commit to raise IntegrityError
    mock_db.commit.side_effect = IntegrityError("UNIQUE constraint failed", {}, None)

    # Call assign_role_to_user - should catch IntegrityError and refetch
    result = await role_service.assign_role_to_user(
        user_email="user@example.com",
        role_id=mock_role.id,
        scope="team",
        scope_id="team-123",
        granted_by="other@example.com"
    )

    # Verify IntegrityError was handled
    assert result is not None
    assert result.id == winner_assignment.id
    assert result.granted_by == "admin@example.com"
    assert call_count[0] == 2  # Initial check + refetch

    # Verify rollback was called (line 673)
    mock_db.rollback.assert_called_once()


@pytest.mark.asyncio
async def test_assign_role_raises_error_when_refetch_fails():
    """Test that assign_role_to_user raises ValueError when refetch returns None.

    Covers role_service.py lines 682-683:
    - Error logging
    - Raise ValueError when assignment not found after IntegrityError
    """
    mock_db = MagicMock()
    mock_db.begin_nested.side_effect = AttributeError

    mock_role = Role(
        id=str(uuid.uuid4()),
        name="test-role",
        description="Test role",
        scope="team",
        permissions=["tools.read"],
        created_by="admin@example.com",
        is_system_role=False,
        is_active=True
    )

    role_service = RoleService(mock_db)

    # Mock get_role_by_id
    async def mock_get_role_by_id(role_id: str):
        return mock_role
    role_service.get_role_by_id = mock_get_role_by_id

    # Mock get_user_role_assignment to always return None
    async def mock_get_assignment(user_email: str, role_id: str, scope: str, scope_id: str):
        return None

    role_service.get_user_role_assignment = mock_get_assignment

    # Mock commit to raise IntegrityError
    mock_db.commit.side_effect = IntegrityError("UNIQUE constraint failed", {}, None)

    # Call assign_role_to_user - should raise ValueError
    with pytest.raises(ValueError, match="Failed to create or fetch role assignment"):
        await role_service.assign_role_to_user(
            user_email="user@example.com",
            role_id=mock_role.id,
            scope="team",
            scope_id="team-mystery",
            granted_by="admin@example.com"
        )

    # Verify rollback was called
    mock_db.rollback.assert_called_once()


@pytest.mark.asyncio
async def test_assign_role_handles_expired_assignment_soft_delete():
    """Test that assign_role_to_user soft-deletes expired assignments during IntegrityError handling.

    Covers role_service.py lines 659, 661-662:
    - Catch IntegrityError during expired assignment soft-delete
    - Rollback and log concurrent modification
    - Refetch to see current state
    """
    from datetime import datetime, timedelta, timezone

    mock_db = MagicMock()
    mock_db.begin_nested.side_effect = AttributeError

    # Create mock role
    mock_role = Role(
        id=str(uuid.uuid4()),
        name="test-role",
        description="Test role",
        scope="team",
        permissions=["tools.read"],
        created_by="admin@example.com",
        is_system_role=False,
        is_active=True
    )

    # Create expired assignment that will trigger soft-delete path
    expired_assignment = UserRole(
        id=str(uuid.uuid4()),
        user_email="user@example.com",
        role_id=mock_role.id,
        scope="team",
        scope_id="team-123",
        granted_by="admin@example.com",
        is_active=True,
        expires_at=datetime.now(timezone.utc) - timedelta(days=1)  # Expired
    )

    # Create a fresh assignment that will be returned after race condition
    fresh_assignment = UserRole(
        id=str(uuid.uuid4()),
        user_email="user@example.com",
        role_id=mock_role.id,
        scope="team",
        scope_id="team-123",
        granted_by="other@example.com",
        is_active=True,
        expires_at=None
    )

    role_service = RoleService(mock_db)

    # Mock get_role_by_id
    async def mock_get_role_by_id(role_id: str):
        return mock_role
    role_service.get_role_by_id = mock_get_role_by_id

    # Mock get_user_role_assignment to return expired assignment first, then fresh
    call_count = [0]
    async def mock_get_assignment(user_email: str, role_id: str, scope: str, scope_id: str):
        call_count[0] += 1
        if call_count[0] == 1:
            # First call: return expired assignment
            return expired_assignment
        elif call_count[0] == 2:
            # Second call after soft-delete race: return fresh assignment
            return fresh_assignment
        return None

    role_service.get_user_role_assignment = mock_get_assignment

    # Mock commit to raise IntegrityError on first commit (during soft-delete)
    commit_count = [0]
    def mock_commit():
        commit_count[0] += 1
        if commit_count[0] == 1:
            # First commit (soft-delete) raises IntegrityError
            raise IntegrityError("UNIQUE constraint failed", {}, None)
        # Second commit succeeds (no-op for testing)
        pass

    mock_db.commit = mock_commit

    # Call assign_role_to_user - should handle expired assignment soft-delete race
    result = await role_service.assign_role_to_user(
        user_email="user@example.com",
        role_id=mock_role.id,
        scope="team",
        scope_id="team-123",
        granted_by="admin@example.com"
    )

    # Verify that the fresh assignment was returned
    assert result is not None
    assert result.id == fresh_assignment.id
    assert result.granted_by == "other@example.com"

    # Verify rollback was called after IntegrityError (line 661)
    mock_db.rollback.assert_called()


@pytest.mark.asyncio
async def test_assign_role_handles_expired_assignment_no_active_after_race():
    """Test that assign_role_to_user continues with creation when no active assignment exists after race.

    Covers role_service.py lines 665-666, 668, 670:
    - Refetch after concurrent modification during expired soft-delete
    - Check if fresh assignment exists
    - Continue to creation if no active assignment
    """
    from datetime import datetime, timedelta, timezone

    mock_db = MagicMock()

    # Mock begin_nested to work for final creation
    mock_savepoint = MagicMock()
    mock_savepoint.__enter__ = MagicMock(return_value=mock_savepoint)
    mock_savepoint.__exit__ = MagicMock(return_value=None)
    mock_db.begin_nested.return_value = mock_savepoint

    # Create mock role
    mock_role = Role(
        id=str(uuid.uuid4()),
        name="test-role",
        description="Test role",
        scope="team",
        permissions=["tools.read"],
        created_by="admin@example.com",
        is_system_role=False,
        is_active=True
    )

    # Create expired assignment
    expired_assignment = UserRole(
        id=str(uuid.uuid4()),
        user_email="user@example.com",
        role_id=mock_role.id,
        scope="team",
        scope_id="team-123",
        granted_by="admin@example.com",
        is_active=True,
        expires_at=datetime.now(timezone.utc) - timedelta(days=1)
    )

    role_service = RoleService(mock_db)

    # Mock get_role_by_id
    async def mock_get_role_by_id(role_id: str):
        return mock_role
    role_service.get_role_by_id = mock_get_role_by_id

    # Mock get_user_role_assignment to return expired, then None after race
    call_count = [0]
    async def mock_get_assignment(user_email: str, role_id: str, scope: str, scope_id: str):
        call_count[0] += 1
        if call_count[0] == 1:
            # First call: return expired assignment
            return expired_assignment
        # Second call after soft-delete race: return None (no active assignment)
        return None

    role_service.get_user_role_assignment = mock_get_assignment

    # Mock commit to raise IntegrityError on first commit, succeed on second
    commit_count = [0]
    def mock_commit():
        commit_count[0] += 1
        if commit_count[0] == 1:
            # First commit (soft-delete) raises IntegrityError
            raise IntegrityError("UNIQUE constraint failed", {}, None)
        # Second commit succeeds
        pass

    mock_db.commit = mock_commit

    # Call assign_role_to_user - should proceed with creation after race
    result = await role_service.assign_role_to_user(
        user_email="user@example.com",
        role_id=mock_role.id,
        scope="team",
        scope_id="team-123",
        granted_by="admin@example.com"
    )

    # Verify that a new assignment was created
    assert result is not None
    assert result.user_email == "user@example.com"

    # Verify rollback was called after first IntegrityError
    mock_db.rollback.assert_called()

    # Verify add was called (line 682) for the new assignment
    mock_db.add.assert_called()


@pytest.mark.asyncio
async def test_assign_role_handles_refetched_expired_assignment():
    """Test that assign_role_to_user soft-deletes refetched expired assignments after IntegrityError.

    Covers role_service.py lines 705-707, 709:
    - Check if refetched assignment is expired after IntegrityError
    - Soft-delete expired assignment
    - Raise ValueError to signal retry needed
    """
    from datetime import datetime, timedelta, timezone

    mock_db = MagicMock()
    mock_db.begin_nested.side_effect = AttributeError

    # Create mock role
    mock_role = Role(
        id=str(uuid.uuid4()),
        name="test-role",
        description="Test role",
        scope="team",
        permissions=["tools.read"],
        created_by="admin@example.com",
        is_system_role=False,
        is_active=True
    )

    # Create expired assignment that will be refetched after IntegrityError
    expired_assignment = UserRole(
        id=str(uuid.uuid4()),
        user_email="user@example.com",
        role_id=mock_role.id,
        scope="team",
        scope_id="team-123",
        granted_by="admin@example.com",
        is_active=True,
        expires_at=datetime.now(timezone.utc) - timedelta(days=1)
    )

    role_service = RoleService(mock_db)

    # Mock get_role_by_id
    async def mock_get_role_by_id(role_id: str):
        return mock_role
    role_service.get_role_by_id = mock_get_role_by_id

    # Mock get_user_role_assignment
    call_count = [0]
    async def mock_get_assignment(user_email: str, role_id: str, scope: str, scope_id: str):
        call_count[0] += 1
        if call_count[0] == 1:
            # First call: return None (no existing assignment)
            return None
        # Second call after IntegrityError: return expired assignment
        return expired_assignment

    role_service.get_user_role_assignment = mock_get_assignment

    # Mock commit to raise IntegrityError on first attempt
    commit_count = [0]
    def mock_commit():
        commit_count[0] += 1
        if commit_count[0] == 1:
            # First commit raises IntegrityError
            raise IntegrityError("UNIQUE constraint failed", {}, None)
        # Second commit (soft-delete) succeeds
        pass

    mock_db.commit = mock_commit

    # Call assign_role_to_user - should raise ValueError for expired refetched assignment
    with pytest.raises(ValueError, match="Refetched assignment.*was expired"):
        await role_service.assign_role_to_user(
            user_email="user@example.com",
            role_id=mock_role.id,
            scope="team",
            scope_id="team-123",
            granted_by="admin@example.com"
        )

    # Verify that expired assignment was soft-deleted
    assert expired_assignment.is_active is False

    # Verify commits happened (first attempt + soft-delete)
    assert commit_count[0] == 2
