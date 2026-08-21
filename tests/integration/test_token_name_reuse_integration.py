# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_token_name_reuse_integration.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Integration tests for API token name reuse after revocation.

Token revocation is a soft delete (is_active = false).  These tests verify against a
real database (SQLite, schema from db.py models) that:
- Creating a token, revoking it, and creating a new token with the same name succeeds
  (previously failed with IntegrityError: the uniqueness rule covered revoked rows)
- Duplicate ACTIVE token names are still rejected at the database level
"""

# Standard
from datetime import datetime, timezone

# Third-Party
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.db import Base, EmailApiToken, EmailUser
from mcpgateway.services.token_catalog_service import TokenCatalogService

TEST_EMAIL = "token-reuse@example.com"


@pytest.fixture
def db_session():
    """Create a real SQLite database session with the full schema and a test user."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(
        EmailUser(
            email=TEST_EMAIL,
            password_hash="not-a-real-hash",
            full_name="Token Reuse Test User",
            is_admin=False,
            is_active=True,
            auth_provider="local",
            email_verified_at=datetime.now(timezone.utc),
        )
    )
    session.commit()
    yield session
    session.close()
    engine.dispose()


@pytest.mark.asyncio
async def test_revoked_token_name_can_be_reused(db_session):
    """Create -> revoke -> create with the same name must succeed."""
    service = TokenCatalogService(db_session)

    token, _raw = await service.create_token(user_email=TEST_EMAIL, name="my-token", expires_in_days=30)
    revoked = await service.revoke_token(token.id, TEST_EMAIL, revoked_by=TEST_EMAIL, reason="test")
    assert revoked is True

    # The revoked token's name must be reusable
    new_token, _raw = await service.create_token(user_email=TEST_EMAIL, name="my-token", expires_in_days=30)
    assert new_token.id != token.id
    assert new_token.is_active is True

    # Both rows coexist: the revoked one is kept for audit
    rows = db_session.query(EmailApiToken).filter_by(user_email=TEST_EMAIL, name="my-token").all()
    assert len(rows) == 2
    assert sorted(r.is_active for r in rows) == [False, True]


@pytest.mark.asyncio
async def test_duplicate_active_token_name_still_rejected(db_session):
    """Two ACTIVE tokens with the same name in the same scope must be rejected."""
    service = TokenCatalogService(db_session)

    await service.create_token(user_email=TEST_EMAIL, name="my-token", expires_in_days=30)
    with pytest.raises(ValueError, match="already exists"):
        await service.create_token(user_email=TEST_EMAIL, name="my-token", expires_in_days=30)
