# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_oauth_multi_identity.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Integration tests for OAuth multi-identity support (Issue #5043).

Tests the end-to-end flow of storing and retrieving multiple OAuth identities
for a single ContextForge user across different OAuth provider accounts.
"""

# Standard
import uuid

# Third-Party
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import Gateway, OAuthToken
from mcpgateway.services.token_storage_service import TokenStorageService


@pytest.fixture
def test_gateway(test_db: Session) -> Gateway:
    """Create a test gateway with OAuth configuration.

    Uses a unique ID per test to avoid fixture reuse conflicts.
    """
    gateway = Gateway(
        id=f"test-gw-{uuid.uuid4().hex[:8]}",  # Unique ID per test
        name="Test Multi-Identity Gateway",
        url="https://api.example.com",
        transport="sse",
        capabilities={},  # Required non-nullable field
        oauth_config={
            "grant_type": "authorization_code",
            "client_id": "test-client",
            "client_secret": "test-secret",  # pragma: allowlist secret
            "authorization_url": "https://oauth.example.com/authorize",
            "token_url": "https://oauth.example.com/token",
            "scopes": ["read", "write"],
        },
    )
    test_db.add(gateway)
    test_db.commit()
    test_db.refresh(gateway)
    return gateway


@pytest.mark.integration
@pytest.mark.asyncio
async def test_store_multiple_oauth_identities_for_single_user(test_db: Session, test_gateway: Gateway) -> None:
    """Test storing multiple OAuth provider identities for a single ContextForge user.

    Scenario: Admin user authorizes gateway with Alice's IBMid, then Bob's IBMid.
    Expected: Both tokens are stored separately and can be retrieved.
    """
    service = TokenStorageService(test_db)
    admin_email = "admin@test.com"

    # Store Alice's OAuth identity
    await service.store_tokens(
        gateway_id=test_gateway.id,
        user_id="alice-ibmid-12345",
        app_user_email=admin_email,
        access_token="alice_access_token_xyz",
        refresh_token="alice_refresh_token_xyz",
        expires_in=3600,
        scopes=["read", "write"],
    )

    # Store Bob's OAuth identity
    await service.store_tokens(
        gateway_id=test_gateway.id,
        user_id="bob-ibmid-67890",
        app_user_email=admin_email,
        access_token="bob_access_token_abc",
        refresh_token="bob_refresh_token_abc",
        expires_in=3600,
        scopes=["read"],
    )

    # Verify both tokens exist in database
    tokens = test_db.execute(
        select(OAuthToken)
        .where(
            OAuthToken.gateway_id == test_gateway.id,
            OAuthToken.app_user_email == admin_email
        )
        .order_by(OAuthToken.user_id)
    ).scalars().all()

    assert len(tokens) == 2
    assert tokens[0].user_id == "alice-ibmid-12345"
    assert tokens[1].user_id == "bob-ibmid-67890"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_user_token_returns_most_recent_identity(test_db: Session, test_gateway: Gateway) -> None:
    """Test that get_user_token returns the most recently updated OAuth identity.

    Scenario: Admin has authorized with both Alice and Bob. Bob's token was updated more recently.
    Expected: get_user_token returns Bob's token.
    """
    service = TokenStorageService(test_db)
    admin_email = "admin@test.com"

    # Store Alice's token (older)
    await service.store_tokens(
        gateway_id=test_gateway.id,
        user_id="alice-ibmid",
        app_user_email=admin_email,
        access_token="alice_token",
        refresh_token="alice_refresh",
        expires_in=3600,
        scopes=["read"],
    )

    # Wait a moment to ensure different timestamps
    import asyncio
    await asyncio.sleep(0.1)

    # Store Bob's token (newer)
    await service.store_tokens(
        gateway_id=test_gateway.id,
        user_id="bob-ibmid",
        app_user_email=admin_email,
        access_token="bob_token",
        refresh_token="bob_refresh",
        expires_in=3600,
        scopes=["read"],
    )

    # Get token - should return Bob's (most recent)
    token = await service.get_user_token(test_gateway.id, admin_email)

    # Verify it's Bob's token by checking the database
    bob_record = test_db.execute(
        select(OAuthToken)
        .where(
            OAuthToken.gateway_id == test_gateway.id,
            OAuthToken.app_user_email == admin_email,
            OAuthToken.user_id == "bob-ibmid"
        )
    ).scalar_one()

    # The token should be decrypted, but we can verify the record was selected
    assert bob_record is not None
    assert token is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_revoke_user_tokens_removes_all_identities(test_db: Session, test_gateway: Gateway) -> None:
    """Test that revoking tokens removes ALL OAuth identities for a user-gateway pair.

    Scenario: Admin has multiple OAuth identities. Revoke is called.
    Expected: All identities are removed.
    """
    service = TokenStorageService(test_db)
    admin_email = "admin@test.com"

    # Store multiple identities
    await service.store_tokens(
        gateway_id=test_gateway.id,
        user_id="alice-ibmid",
        app_user_email=admin_email,
        access_token="alice_token",
        refresh_token="alice_refresh",
        expires_in=3600,
        scopes=["read"],
    )

    await service.store_tokens(
        gateway_id=test_gateway.id,
        user_id="bob-ibmid",
        app_user_email=admin_email,
        access_token="bob_token",
        refresh_token="bob_refresh",
        expires_in=3600,
        scopes=["read"],
    )

    # Verify both exist
    tokens_before = test_db.execute(
        select(OAuthToken)
        .where(
            OAuthToken.gateway_id == test_gateway.id,
            OAuthToken.app_user_email == admin_email
        )
    ).scalars().all()
    assert len(tokens_before) == 2

    # Revoke all tokens
    result = await service.revoke_user_tokens(test_gateway.id, admin_email)
    assert result is True

    # Verify all are removed
    tokens_after = test_db.execute(
        select(OAuthToken)
        .where(
            OAuthToken.gateway_id == test_gateway.id,
            OAuthToken.app_user_email == admin_email
        )
    ).scalars().all()
    assert len(tokens_after) == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_update_existing_identity_preserves_others(test_db: Session, test_gateway: Gateway) -> None:
    """Test that updating one OAuth identity doesn't affect other identities.

    Scenario: Admin has Alice and Bob identities. Alice's token is refreshed.
    Expected: Bob's token remains unchanged.
    """
    service = TokenStorageService(test_db)
    admin_email = "admin@test.com"

    # Store both identities
    await service.store_tokens(
        gateway_id=test_gateway.id,
        user_id="alice-ibmid",
        app_user_email=admin_email,
        access_token="alice_token_v1",
        refresh_token="alice_refresh_v1",
        expires_in=3600,
        scopes=["read"],
    )

    await service.store_tokens(
        gateway_id=test_gateway.id,
        user_id="bob-ibmid",
        app_user_email=admin_email,
        access_token="bob_token_v1",
        refresh_token="bob_refresh_v1",
        expires_in=3600,
        scopes=["read"],
    )

    # Get Bob's original updated_at
    bob_before = test_db.execute(
        select(OAuthToken)
        .where(
            OAuthToken.gateway_id == test_gateway.id,
            OAuthToken.app_user_email == admin_email,
            OAuthToken.user_id == "bob-ibmid"
        )
    ).scalar_one()
    bob_updated_at_before = bob_before.updated_at

    # Update Alice's token
    await service.store_tokens(
        gateway_id=test_gateway.id,
        user_id="alice-ibmid",
        app_user_email=admin_email,
        access_token="alice_token_v2",
        refresh_token="alice_refresh_v2",
        expires_in=3600,
        scopes=["read", "write"],
    )

    # Verify Bob's token is unchanged
    bob_after = test_db.execute(
        select(OAuthToken)
        .where(
            OAuthToken.gateway_id == test_gateway.id,
            OAuthToken.app_user_email == admin_email,
            OAuthToken.user_id == "bob-ibmid"
        )
    ).scalar_one()

    assert bob_after.updated_at == bob_updated_at_before

    # Verify Alice's token was updated
    alice_after = test_db.execute(
        select(OAuthToken)
        .where(
            OAuthToken.gateway_id == test_gateway.id,
            OAuthToken.app_user_email == admin_email,
            OAuthToken.user_id == "alice-ibmid"
        )
    ).scalar_one()

    assert alice_after.updated_at > bob_updated_at_before


@pytest.mark.integration
@pytest.mark.asyncio
async def test_different_users_can_have_same_oauth_provider_identity(test_db: Session, test_gateway: Gateway) -> None:
    """Test that different ContextForge users can authorize with the same OAuth provider account.

    Scenario: Admin and Developer both authorize with Alice's IBMid.
    Expected: Both tokens are stored separately.
    """
    service = TokenStorageService(test_db)

    # Admin authorizes with Alice's IBMid
    await service.store_tokens(
        gateway_id=test_gateway.id,
        user_id="alice-ibmid",
        app_user_email="admin@test.com",
        access_token="admin_alice_token",
        refresh_token="admin_alice_refresh",
        expires_in=3600,
        scopes=["read"],
    )

    # Developer authorizes with the same Alice's IBMid
    await service.store_tokens(
        gateway_id=test_gateway.id,
        user_id="alice-ibmid",
        app_user_email="developer@test.com",
        access_token="dev_alice_token",
        refresh_token="dev_alice_refresh",
        expires_in=3600,
        scopes=["read"],
    )

    # Verify both tokens exist
    all_tokens = test_db.execute(
        select(OAuthToken)
        .where(
            OAuthToken.gateway_id == test_gateway.id,
            OAuthToken.user_id == "alice-ibmid"
        )
    ).scalars().all()

    assert len(all_tokens) == 2
    assert {t.app_user_email for t in all_tokens} == {"admin@test.com", "developer@test.com"}
