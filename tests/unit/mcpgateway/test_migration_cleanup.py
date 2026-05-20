# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_migration_cleanup.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Test migration cleanup SQL on SQLite.

Validates that the dialect-specific cleanup SQL in the migration
correctly removes inactive duplicate user_role rows.
"""

from datetime import datetime, timezone
import uuid
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# First-Party
from mcpgateway.db import Base, EmailUser, Role, UserRole


def test_migration_cleanup_sqlite():
    """Test migration cleanup SQL works on SQLite.

    This test validates that the dialect-specific cleanup SQL in the migration
    works correctly on SQLite.
    """

    # Create test database and session - SQLite in memory
    db_url = "sqlite:///:memory:"
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    try:
        # Create test user
        user = EmailUser(email=f"test-{uuid.uuid4().hex[:8]}@example.com", password_hash="dummy_hash", is_active=True)
        session.add(user)
        session.commit()

        # Create test role
        role = Role(
            id=str(uuid.uuid4()),
            name=f"test-role-{uuid.uuid4().hex[:8]}",
            description="Test",
            scope="team",
            permissions=["tools.read"],
            created_by="admin@example.com",
            is_system_role=False,
            is_active=True,
        )
        session.add(role)
        session.commit()

        # Create duplicate state (inactive + active)
        inactive = UserRole(
            id=str(uuid.uuid4()), user_email=user.email, role_id=role.id, scope="team", scope_id="team-123", granted_by="admin@example.com", is_active=False, granted_at=datetime.now(timezone.utc)
        )

        active = UserRole(
            id=str(uuid.uuid4()), user_email=user.email, role_id=role.id, scope="team", scope_id="team-123", granted_by="admin@example.com", is_active=True, granted_at=datetime.now(timezone.utc)
        )

        session.add(inactive)
        session.add(active)
        session.commit()

        # Verify duplicates exist
        count_before = session.query(UserRole).filter(UserRole.user_email == user.email, UserRole.role_id == role.id).count()
        assert count_before == 2, f"Expected 2 rows before cleanup, got {count_before}"

        # Run cleanup SQL (SQLite version)
        session.execute(text("""
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
        session.commit()

        # Verify only active remains
        count_after = session.query(UserRole).filter(UserRole.user_email == user.email, UserRole.role_id == role.id).count()
        assert count_after == 1, f"Expected 1 row after cleanup, got {count_after}"

        remaining = session.query(UserRole).filter(UserRole.user_email == user.email, UserRole.role_id == role.id).first()
        assert remaining is not None
        assert remaining.is_active is True
        assert remaining.id == active.id

        print(f"✓ Migration cleanup test passed for SQLite")

    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()
