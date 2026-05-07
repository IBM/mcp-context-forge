# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_role_service_duplicate_handling.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

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
    Simulates the race by checking for the role returning None, then during commit
    we get an IntegrityError, and refetch returns the existing role.
    """
    from unittest.mock import AsyncMock, patch
    from sqlalchemy.exc import IntegrityError

    role_name = f"concurrent-role-{uuid.uuid4().hex[:8]}"
    role_service = RoleService(test_db)

    # First, create a role to simulate the "winner" of the race
    winner_role = await role_service.create_role(
        name=role_name,
        description="Winner role",
        scope="global",
        permissions=["tools.read"],
        created_by="admin@example.com"
    )
    assert winner_role is not None

    # Now simulate the rac scenario:
    # - First get_role_by_name() check (lines 198-200) returns None (race window)
    # - Commit fails with IntegrityError (line 236)
    # - Rollback happens (line 244)
    # - Second get_role_by_name() refetch (line 248) returns the winner

    call_count = [0]
    original_get = role_service.get_role_by_name

    async def mock_get_role(name: str, scope: str):
        call_count[0] += 1
        if call_count[0] == 1:
            # First call during duplicate check - return None (race window)
            return None
        # Second call after rollback - return the actual role
        return await original_get(name, scope)

    # Patch get_role_by_name and simulate IntegrityError on commit
    with patch.object(role_service, 'get_role_by_name', side_effect=mock_get_role):
        # Also patch begin_nested to skip savepoint logic and go straight to add
        with patch.object(test_db, 'begin_nested', side_effect=AttributeError("Mocked")):
            # Patch add to raise IntegrityError when called
            original_add = test_db.add

            def mock_add(instance):
                original_add(instance)
                # After add, when commit is called, it should raise
                test_db.commit = lambda: (_ for _ in ()).throw(IntegrityError("UNIQUE constraint failed: roles.name, roles.scope", {}, None))

            with patch.object(test_db, 'add', side_effect=mock_add):
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
    assert result.description == "Winner role"
    assert call_count[0] == 2  # Called twice: initial check + refetch


@pytest.mark.asyncio
async def test_concurrent_role_assignment_handles_integrity_error(test_db: Session, test_role: Role, test_user: EmailUser):
    """Test that concurrent role assignment handles IntegrityError gracefully.

    This tests the race condition handling in assign_role_to_user() lines 671-683.
    """
    from unittest.mock import patch
    from sqlalchemy.exc import IntegrityError

    role_service = RoleService(test_db)

    # First, create an assignment to simulate the "winner" of the race
    winner_assignment = await role_service.assign_role_to_user(
        user_email=test_user.email,
        role_id=test_role.id,
        scope="team",
        scope_id="team-race",
        granted_by="admin@example.com"
    )
    assert winner_assignment is not None

    # Now simulate the race scenario similar to role creation
    call_count = [0]
    original_get = role_service.get_user_role_assignment

    async def mock_get_assignment(user_email: str, role_id: str, scope: str, scope_id: str | None):
        call_count[0] += 1
        if call_count[0] == 1:
            # First call during duplicate check - return None (race window)
            return None
        # Second call after rollback - return the actual assignment
        return await original_get(user_email, role_id, scope, scope_id)

    with patch.object(role_service, 'get_user_role_assignment', side_effect=mock_get_assignment):
        with patch.object(test_db, 'begin_nested', side_effect=AttributeError("Mocked")):
            original_add = test_db.add

            def mock_add(instance):
                original_add(instance)
                test_db.commit = lambda: (_ for _ in ()).throw(IntegrityError("UNIQUE constraint failed", {}, None))

            with patch.object(test_db, 'add', side_effect=mock_add):
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
    assert result.granted_by == "admin@example.com"
    assert call_count[0] == 2  # Called twice: initial check + refetch


@pytest.mark.asyncio
async def test_integrity_error_with_no_existing_role_raises_error(test_db: Session):
    """Test that IntegrityError without finding existing role raises ValueError.

    This tests the error path in create_role() lines 253-254.
    """
    from unittest.mock import patch, AsyncMock
    from sqlalchemy.exc import IntegrityError

    role_name = f"mystery-role-{uuid.uuid4().hex[:8]}"
    role_service = RoleService(test_db)

    # Mock db.commit to raise IntegrityError
    with patch.object(test_db, 'commit', side_effect=IntegrityError("Unknown constraint", {}, None)):
        # Mock get_role_by_name to return None (role mysteriously not found)
        with patch.object(role_service, 'get_role_by_name', new=AsyncMock(return_value=None)):
            with pytest.raises(ValueError, match="Failed to create or fetch role"):
                await role_service.create_role(
                    name=role_name,
                    description="Mystery role",
                    scope="global",
                    permissions=["tools.read"],
                    created_by="admin@example.com"
                )


@pytest.mark.asyncio
async def test_integrity_error_with_no_existing_assignment_raises_error(test_db: Session, test_role: Role, test_user: EmailUser):
    """Test that IntegrityError without finding existing assignment raises ValueError.

    This tests the error path in assign_role_to_user() lines 682-683.
    """
    from unittest.mock import patch, AsyncMock
    from sqlalchemy.exc import IntegrityError

    role_service = RoleService(test_db)

    # Mock db.commit to raise IntegrityError
    with patch.object(test_db, 'commit', side_effect=IntegrityError("Unknown constraint", {}, None)):
        # Mock get_user_role_assignment to return None (assignment mysteriously not found)
        with patch.object(role_service, 'get_user_role_assignment', new=AsyncMock(return_value=None)):
            with pytest.raises(ValueError, match="Failed to create or fetch role assignment"):
                await role_service.assign_role_to_user(
                    user_email=test_user.email,
                    role_id=test_role.id,
                    scope="team",
                    scope_id="team-999",
                    granted_by="admin@example.com"
                )
