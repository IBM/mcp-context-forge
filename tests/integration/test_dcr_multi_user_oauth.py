# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_dcr_multi_user_oauth.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Regression coverage for multi-user OAuth token storage on one DCR gateway.
"""

# Standard
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.db import EmailUser, Gateway, OAuthToken
from mcpgateway.services.oauth_manager import OAuthManager
from mcpgateway.services.token_storage_service import TokenStorageService


@pytest.mark.integration
class TestDcrMultiUserOAuth:
    """Regression coverage for Issue #5191."""

    @pytest.mark.asyncio
    async def test_two_contextforge_users_can_store_same_provider_user_on_one_gateway(self, test_db):
        """Two app users may authorize the same gateway even when the provider user_id matches."""

        def mock_get_db():
            yield test_db

        gateway = Gateway(
            id="dcr-shared-user-gateway",
            name="Shared User DCR Gateway",
            slug="shared-user-dcr-gateway",
            description="Regression gateway for multi-user OAuth storage",
            url="https://mcp.example.com/sse",
            transport="SSE",
            capabilities={},
            auth_type="oauth",
            oauth_config={
                "grant_type": "authorization_code",
                "issuer": "https://issuer.example.com",
                "redirect_uri": "http://localhost:4444/oauth/callback",
                "client_id": "dcr-client-id",
                "token_url": "https://issuer.example.com/token",
                "authorization_url": "https://issuer.example.com/authorize",
            },
        )
        user_one = EmailUser(
            email="alice@example.com",
            password_hash="dummy_hash",
            full_name="Alice",
            is_active=True,
            email_verified_at=datetime.now(timezone.utc),
        )
        user_two = EmailUser(
            email="bob@example.com",
            password_hash="dummy_hash",
            full_name="Bob",
            is_active=True,
            email_verified_at=datetime.now(timezone.utc),
        )
        test_db.add_all([gateway, user_one, user_two])
        test_db.commit()

        token_storage = TokenStorageService(test_db)
        oauth_manager = OAuthManager(token_storage=token_storage)
        credentials = {
            "client_id": "dcr-client-id",
            "authorization_url": "https://issuer.example.com/authorize",
            "token_url": "https://issuer.example.com/token",
            "redirect_uri": "http://localhost:4444/oauth/callback",
            "scopes": ["mcp:read"],
        }
        provider_user_id = "provider-user-123"

        with (
            patch("mcpgateway.db.get_db", mock_get_db),
            patch("mcpgateway.config.get_settings") as mock_settings,
            patch.object(oauth_manager, "_exchange_code_for_tokens", new=AsyncMock(return_value={"access_token": "access-token", "refresh_token": "refresh-token", "expires_in": 3600, "scope": "mcp:read"})),
            patch.object(oauth_manager, "_extract_user_id", return_value=provider_user_id),
        ):
            mock_settings.return_value.cache_type = "database"

            first_flow = await oauth_manager.initiate_authorization_code_flow(
                gateway_id=gateway.id,
                credentials=credentials,
                app_user_email=user_one.email,
            )
            second_flow = await oauth_manager.initiate_authorization_code_flow(
                gateway_id=gateway.id,
                credentials=credentials,
                app_user_email=user_two.email,
            )

            first_result = await oauth_manager.complete_authorization_code_flow(
                gateway_id=gateway.id,
                code="code-for-alice",
                state=first_flow["state"],
                credentials=credentials,
            )
            second_result = await oauth_manager.complete_authorization_code_flow(
                gateway_id=gateway.id,
                code="code-for-bob",
                state=second_flow["state"],
                credentials=credentials,
            )

        assert first_result["success"] is True
        assert second_result["success"] is True
        assert first_result["user_id"] == provider_user_id
        assert second_result["user_id"] == provider_user_id

        rows = test_db.query(OAuthToken).filter(OAuthToken.gateway_id == gateway.id).order_by(OAuthToken.app_user_email.asc()).all()

        assert len(rows) == 2
        assert [row.app_user_email for row in rows] == [user_one.email, user_two.email]
        assert [row.user_id for row in rows] == [provider_user_id, provider_user_id]
