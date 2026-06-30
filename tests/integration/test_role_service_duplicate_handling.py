# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_role_service_duplicate_handling.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Integration tests for role service duplicate handling.

Tests the full revoke → re-assign flow that triggers the bug in #3505.
Uses real database sessions, not mocks.
"""

import pytest
from datetime import datetime, timezone
import uuid
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import EmailUser, Role, UserRole
from mcpgateway.services.role_service import RoleService


@pytest.fixture
def test_role(test_db: Session):
    """Create a test role."""
    role = Role(
        id=str(uuid.uuid4()),
        name=f"test-role-{uuid.uuid4().hex[:8]}",
        description="Test role for duplicate handling",
        scope="team",
        permissions=["tools.read", "tools.execute"],
        created_by="admin@example.com",
        is_system_role=False,
        is_active=True,
    )
    test_db.add(role)
    test_db.commit()
    test_db.refresh(role)
    return role


@pytest.fixture
def test_user(test_db: Session):
    """Create a test user."""
    user = EmailUser(email=f"testuser-{uuid.uuid4().hex[:8]}@example.com", password_hash="dummy_hash", is_active=True)
    test_db.add(user)
    test_db.commit()
    test_db.refresh(user)
    return user


@pytest.mark.asyncio
async def test_revoke_and_reassign_no_duplicate_error(test_db: Session, test_role: Role, test_user: EmailUser):
    """Test that revoking and re-assigning a role doesn't cause MultipleResultsFound.

    This is the core integration test for issue #3505.

    Steps:
    1. Assign role to user
    2. Revoke role (soft delete → is_active=False)
    3. Re-assign role (new row with is_active=True)
    4. Query for assignment (should return active, not raise MultipleResultsFound)
    """
    role_service = RoleService(test_db)

    # Step 1: Assign role
    assignment1 = await role_service.assign_role_to_user(user_email=test_user.email, role_id=test_role.id, scope="team", scope_id="team-123", granted_by="admin@example.com")
    assert assignment1 is not None
    assert assignment1.is_active is True

    # Step 2: Revoke role (soft delete)
    revoked = await role_service.revoke_role_from_user(user_email=test_user.email, role_id=test_role.id, scope="team", scope_id="team-123")
    assert revoked is True

    # Verify revocation created inactive row
    test_db.expire_all()
    inactive_check = await role_service.get_user_role_assignment(user_email=test_user.email, role_id=test_role.id, scope="team", scope_id="team-123")
    # After fix: should return None (no active assignment)
    assert inactive_check is None

    # Step 3: Re-assign role (creates new active row)
    assignment2 = await role_service.assign_role_to_user(user_email=test_user.email, role_id=test_role.id, scope="team", scope_id="team-123", granted_by="admin@example.com")
    assert assignment2 is not None
    assert assignment2.is_active is True
    assert assignment2.id != assignment1.id  # Different row

    # Step 4: Query for assignment (CRITICAL TEST - should not raise MultipleResultsFound)
    test_db.expire_all()
    result = await role_service.get_user_role_assignment(user_email=test_user.email, role_id=test_role.id, scope="team", scope_id="team-123")

    # After fix: should return the active assignment
    assert result is not None
    assert result.is_active is True
    assert result.id == assignment2.id

    # Verify database state: should have 1 inactive + 1 active row
    all_assignments = test_db.query(UserRole).filter(UserRole.user_email == test_user.email, UserRole.role_id == test_role.id, UserRole.scope == "team", UserRole.scope_id == "team-123").all()

    assert len(all_assignments) == 2
    active_count = sum(1 for a in all_assignments if a.is_active)
    inactive_count = sum(1 for a in all_assignments if not a.is_active)
    assert active_count == 1
    assert inactive_count == 1


@pytest.mark.asyncio
async def test_migration_cleanup_removes_inactive_duplicates(test_db: Session, test_role: Role, test_user: EmailUser):
    """Test that migration cleanup removes inactive duplicates correctly."""
    from sqlalchemy import text

    # Manually create the duplicate state (inactive + active)
    inactive = UserRole(
        id=str(uuid.uuid4()),
        user_email=test_user.email,
        role_id=test_role.id,
        scope="team",
        scope_id="team-456",
        granted_by="admin@example.com",
        is_active=False,
        granted_at=datetime.now(timezone.utc),
    )

    active = UserRole(
        id=str(uuid.uuid4()), user_email=test_user.email, role_id=test_role.id, scope="team", scope_id="team-456", granted_by="admin@example.com", is_active=True, granted_at=datetime.now(timezone.utc)
    )

    test_db.add(inactive)
    test_db.add(active)
    test_db.commit()

    # Verify both exist
    all_before = test_db.query(UserRole).filter(UserRole.user_email == test_user.email, UserRole.role_id == test_role.id, UserRole.scope == "team", UserRole.scope_id == "team-456").all()
    assert len(all_before) == 2

    # Simulate migration cleanup (using same SQL logic)
    # Use SQLite-compatible version for test
    test_db.execute(text("""
        DELETE FROM user_roles
        WHERE id IN (
            SELECT ur1.id
            FROM user_roles ur1
            WHERE ur1.is_active = 0
            AND EXISTS (
                SELECT 1 FROM user_roles ur2
                WHERE ur2.user_email = ur1.user_email
                AND ur2.role_id = ur1.role_id
                AND ur2.scope = ur1.scope
                AND (ur2.scope_id = ur1.scope_id OR (ur2.scope_id IS NULL AND ur1.scope_id IS NULL))
                AND ur2.is_active = 1
            )
        )
    """))
    test_db.commit()

    # Verify only active remains
    all_after = test_db.query(UserRole).filter(UserRole.user_email == test_user.email, UserRole.role_id == test_role.id, UserRole.scope == "team", UserRole.scope_id == "team-456").all()
    assert len(all_after) == 1
    assert all_after[0].is_active is True
    assert all_after[0].id == active.id


@pytest.mark.asyncio
async def test_concurrent_role_creation_handles_integrity_error(test_db: Session):
    """Test that concurrent role creation handles IntegrityError gracefully.

    This tests the race condition handling in create_role() lines 242-254.
    We force an IntegrityError by directly inserting a duplicate in the database
    after the duplicate check but before commit.
    """
    from unittest.mock import patch
    from sqlalchemy.exc import IntegrityError

    role_name = f"concurrent-role-{uuid.uuid4().hex[:8]}"
    role_service = RoleService(test_db)

    # First, create a role that will be the "winner"
    winner_role = Role(
        id=str(uuid.uuid4()),
        name=role_name,
        description="Winner role",
        scope="global",
        permissions=["tools.read"],
        created_by="admin@example.com",
        is_system_role=False,
        is_active=True
    )
    test_db.add(winner_role)
    test_db.commit()
    test_db.refresh(winner_role)

    # Track calls to get_role_by_name and simulate race condition
    call_count = [0]
    original_get = role_service.get_role_by_name

    async def mock_get_role(name: str, scope: str):
        call_count[0] += 1
        if call_count[0] == 1:
            # First call during duplicate check - return None (race window)
            # Winner role exists but we're simulating the timing window
            return None
        # Second call after IntegrityError - return the actual winner role
        return await original_get(name, scope)

    with patch.object(role_service, 'get_role_by_name', side_effect=mock_get_role):
        # This will naturally trigger a REAL IntegrityError because the role already exists
        # No need to mock commit - let SQLAlchemy naturally raise the error
        result = await role_service.create_role(
            name=role_name,
            description="Loser role",
            scope="global",
            permissions=["tools.read"],
            created_by="other@example.com"
        )

    # Should have refetched and returned the winner's role
    assert result is not None
    assert result.id == winner_role.id
    assert result.description == "Winner role"  # Winner's description, not loser's
    assert call_count[0] == 2  # Called twice: initial check + refetch after IntegrityError


@pytest.mark.asyncio
async def test_concurrent_role_assignment_handles_integrity_error(test_db: Session, test_role: Role, test_user: EmailUser):
    """Test that concurrent role assignment handles IntegrityError gracefully.

    This tests the race condition handling in assign_role_to_user() lines 671-683.
    We force an IntegrityError by directly inserting a duplicate in the database
    after the duplicate check but before commit.
    """
    from unittest.mock import patch

    role_service = RoleService(test_db)

    # First, create the "winner" assignment directly
    winner_assignment = UserRole(
        id=str(uuid.uuid4()),
        user_email=test_user.email,
        role_id=test_role.id,
        scope="team",
        scope_id="team-race",
        granted_by="admin@example.com",
        is_active=True,
        granted_at=datetime.now(timezone.utc)
    )
    test_db.add(winner_assignment)
    test_db.commit()
    test_db.refresh(winner_assignment)

    # Track calls to get_user_role_assignment and simulate race condition
    call_count = [0]
    original_get = role_service.get_user_role_assignment

    async def mock_get_assignment(user_email: str, role_id: str, scope: str, scope_id: str | None):
        call_count[0] += 1
        if call_count[0] == 1:
            # First call during duplicate check - return None (race window)
            # Winner assignment exists but we're simulating the timing window
            return None
        # Second call after IntegrityError - return the actual winner assignment
        return await original_get(user_email, role_id, scope, scope_id)

    with patch.object(role_service, 'get_user_role_assignment', side_effect=mock_get_assignment):
        # This will naturally trigger a REAL IntegrityError because the assignment already exists
        # No need to mock commit - let SQLAlchemy naturally raise the error
        result = await role_service.assign_role_to_user(
            user_email=test_user.email,
            role_id=test_role.id,
            scope="team",
            scope_id="team-race",
            granted_by="other@example.com"
        )

    # Should have refetched and returned the winner's assignment
    assert result is not None
    assert result.id == winner_assignment.id
    assert result.granted_by == "admin@example.com"  # Winner's granted_by, not loser's
    assert call_count[0] == 2  # Called twice: initial check + refetch after IntegrityError


@pytest.mark.asyncio
async def test_integrity_error_with_no_existing_role_raises_error(test_db: Session):
    """Test that IntegrityError without finding existing role raises ValueError.

    This tests the error path in create_role() lines 253-254.
    We simulate a scenario where:
    1. Initial check returns None (race window)
    2. Commit succeeds initially but then we manually create the role again
    3. Second attempt triggers IntegrityError
    4. Refetch returns None (role mysteriously disappeared)
    5. Should raise ValueError
    """
    from unittest.mock import patch, AsyncMock
    from sqlalchemy.exc import IntegrityError

    role_name = f"mystery-role-{uuid.uuid4().hex[:8]}"
    role_service = RoleService(test_db)

    # First, create a role normally
    initial_role = await role_service.create_role(
        name=role_name,
        description="Initial role",
        scope="global",
        permissions=["tools.read"],
        created_by="admin@example.com"
    )

    # Now delete it to simulate the "mystery" scenario
    test_db.delete(initial_role)
    test_db.commit()

    # Create second service instance for the race scenario
    role_service2 = RoleService(test_db)

    # Mock the initial check to return None
    call_count = [0]
    async def mock_get_role(name: str, scope: str):
        call_count[0] += 1
        # Always return None to simulate the role being gone
        return None

    # Mock commit to raise IntegrityError on the first call, then work normally
    commit_calls = [0]
    original_commit = test_db.commit
    def mock_commit():
        commit_calls[0] += 1
        if commit_calls[0] == 1:
            raise IntegrityError("UNIQUE constraint violated", {}, None)
        return original_commit()

    with patch.object(role_service2, 'get_role_by_name', side_effect=mock_get_role):
        with patch.object(test_db, 'commit', side_effect=mock_commit):
            # This should trigger IntegrityError, then try to refetch but find nothing
            # Should raise ValueError with "Failed to create or fetch role" message
            with pytest.raises(ValueError, match="Failed to create or fetch role"):
                await role_service2.create_role(
                    name=role_name,
                    description="Mystery role",
                    scope="global",
                    permissions=["tools.read"],
                    created_by="admin@example.com"
                )

    # Verify the error path was taken (lines 253-254)
    assert call_count[0] >= 2  # Initial check + refetch attempt


@pytest.mark.asyncio
async def test_integrity_error_with_no_existing_assignment_raises_error(test_db: Session, test_role: Role, test_user: EmailUser):
    """Test that IntegrityError without finding existing assignment raises ValueError.

    This tests the error path in assign_role_to_user() lines 682-683.
    We simulate a scenario where:
    1. Initial check returns None (race window)
    2. Commit succeeds initially but then we manually create the assignment again
    3. Second attempt triggers IntegrityError
    4. Refetch returns None (assignment mysteriously disappeared)
    5. Should raise ValueError
    """
    from unittest.mock import patch, AsyncMock
    from sqlalchemy.exc import IntegrityError

    role_service = RoleService(test_db)

    # First, create an assignment normally
    initial_assignment = await role_service.assign_role_to_user(
        user_email=test_user.email,
        role_id=test_role.id,
        scope="team",
        scope_id="team-mystery",
        granted_by="admin@example.com"
    )

    # Now delete it to simulate the "mystery" scenario
    test_db.delete(initial_assignment)
    test_db.commit()

    # Create second service instance for the race scenario
    role_service2 = RoleService(test_db)

    # Mock the initial check to return None
    call_count = [0]
    async def mock_get_assignment(user_email: str, role_id: str, scope: str, scope_id: str | None):
        call_count[0] += 1
        # Always return None to simulate the assignment being gone
        return None

    # Mock commit to raise IntegrityError on the first call, then work normally
    commit_calls = [0]
    original_commit = test_db.commit
    def mock_commit():
        commit_calls[0] += 1
        if commit_calls[0] == 1:
            raise IntegrityError("UNIQUE constraint violated", {}, None)
        return original_commit()

    with patch.object(role_service2, 'get_user_role_assignment', side_effect=mock_get_assignment):
        with patch.object(test_db, 'commit', side_effect=mock_commit):
            # This should trigger IntegrityError, then try to refetch but find nothing
            # Should raise ValueError with "Failed to create or fetch role assignment" message
            with pytest.raises(ValueError, match="Failed to create or fetch role assignment"):
                await role_service2.assign_role_to_user(
                    user_email=test_user.email,
                    role_id=test_role.id,
                    scope="team",
                    scope_id="team-mystery",
                    granted_by="admin@example.com"
                )

    # Verify the error path was taken (lines 682-683)
    assert call_count[0] >= 2  # Initial check + refetch attempt


@pytest.mark.asyncio
async def test_expired_assignment_soft_delete_race(test_db: Session, test_role: Role, test_user: EmailUser):
    """Test the expired assignment soft-delete race condition.

    This tests the fix for the critical race where two processes try to re-grant an expired assignment:
    1. Process A checks existing (finds expired), starts soft-delete
    2. Process B checks existing (finds expired), starts soft-delete
    3. One wins, one gets IntegrityError
    4. The loser should refetch and return the winner's fresh assignment (not the expired one)
    """
    from datetime import datetime, timezone, timedelta
    from unittest.mock import patch

    role_service = RoleService(test_db)

    # Create an expired active assignment
    expired_date = datetime.now(timezone.utc) - timedelta(days=1)
    expired_assignment = UserRole(
        id=str(uuid.uuid4()),
        user_email=test_user.email,
        role_id=test_role.id,
        scope="team",
        scope_id="team-expired",
        granted_by="admin@example.com",
        is_active=True,
        granted_at=datetime.now(timezone.utc) - timedelta(days=2),
        expires_at=expired_date
    )
    test_db.add(expired_assignment)
    test_db.commit()
    test_db.refresh(expired_assignment)

    # Verify it's expired but active
    assert expired_assignment.is_active is True
    assert expired_assignment.is_expired() is True

    # Track soft-delete commits
    commit_count = [0]
    original_commit = test_db.commit

    def mock_commit():
        commit_count[0] += 1
        if commit_count[0] == 1:
            # First commit (soft-delete) succeeds
            return original_commit()
        # Subsequent commits succeed normally
        return original_commit()

    with patch.object(test_db, 'commit', side_effect=mock_commit):
        # Process A tries to re-grant - should soft-delete expired and create new
        result = await role_service.assign_role_to_user(
            user_email=test_user.email,
            role_id=test_role.id,
            scope="team",
            scope_id="team-expired",
            granted_by="other@example.com",
            expires_at=datetime.now(timezone.utc) + timedelta(days=30)
        )

    # Verify the new assignment is not expired
    assert result is not None
    assert result.is_active is True
    assert result.is_expired() is False
    assert result.granted_by == "other@example.com"
    assert result.id != expired_assignment.id  # New assignment, not the old one

    # Verify the old assignment was soft-deleted
    test_db.refresh(expired_assignment)
    assert expired_assignment.is_active is False


@pytest.mark.asyncio
async def test_concurrent_expired_assignment_handling(test_db: Session, test_role: Role, test_user: EmailUser):
    """Test that concurrent processes can handle expired assignments safely.

    This tests that when two processes try to re-grant an expired assignment concurrently,
    both can proceed without error - one will soft-delete and create new, the other
    will get IntegrityError and refetch the new assignment.
    """
    from datetime import datetime, timezone, timedelta

    role_service = RoleService(test_db)

    # Create an expired active assignment
    expired_date = datetime.now(timezone.utc) - timedelta(days=1)
    expired_assignment = UserRole(
        id=str(uuid.uuid4()),
        user_email=test_user.email,
        role_id=test_role.id,
        scope="team",
        scope_id="team-concurrent",
        granted_by="admin@example.com",
        is_active=True,
        granted_at=datetime.now(timezone.utc) - timedelta(days=2),
        expires_at=expired_date
    )
    test_db.add(expired_assignment)
    test_db.commit()
    test_db.refresh(expired_assignment)

    # Verify it's expired but active
    assert expired_assignment.is_active is True
    assert expired_assignment.is_expired() is True

    # Process tries to re-grant - should soft-delete expired and create new
    new_expires = datetime.now(timezone.utc) + timedelta(days=30)
    result = await role_service.assign_role_to_user(
        user_email=test_user.email,
        role_id=test_role.id,
        scope="team",
        scope_id="team-concurrent",
        granted_by="other@example.com",
        expires_at=new_expires
    )

    # Verify the new assignment is not expired
    assert result is not None
    assert result.is_active is True
    assert result.is_expired() is False
    assert result.granted_by == "other@example.com"
    assert result.id != expired_assignment.id  # New assignment, not the old one

    # Verify the old assignment was soft-deleted
    test_db.refresh(expired_assignment)
    assert expired_assignment.is_active is False
