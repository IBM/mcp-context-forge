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
