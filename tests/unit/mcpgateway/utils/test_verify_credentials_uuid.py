# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_verify_credentials_uuid.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Integration tests for UUID resolution in verify_credentials.
"""

import pytest
from unittest.mock import patch, MagicMock
from tests.helpers.auth import make_test_jwt
from mcpgateway.utils.verify_credentials import verify_credentials
from mcpgateway.db import EmailUser


class TestVerifyCredentialsUuidCoverage:
    """Tests targeting missing coverage lines in verify_credentials.py."""

    @pytest.mark.asyncio
    async def test_uuid_resolution_in_user_status_check_lines_520_525(self):
        """Cover lines 520-525: UUID resolution in user status check."""
        uuid_sub = "550e8400-e29b-41d4-a716-446655440000"

        token = make_test_jwt(email=uuid_sub, expires_in_minutes=10, extra_payload={"token_use": "session"})

        mock_user = MagicMock(spec=EmailUser)
        mock_user.email = "user@example.com"
        mock_user.is_active = True
        mock_user.is_admin = False

        # Patch at the source module where functions are defined
        with patch("mcpgateway.auth._get_user_by_email_sync", side_effect=[None, mock_user]):
            with patch("mcpgateway.auth._get_email_by_id_sync", return_value="user@example.com"):
                with patch("mcpgateway.auth._check_token_revoked_sync", return_value=False):
                    result = await verify_credentials(token)

        assert result is not None
        assert result.get("sub") == uuid_sub

    @pytest.mark.asyncio
    async def test_uuid_resolution_returns_none_lines_520_525(self):
        """Cover lines 520-525: UUID resolution returns None."""
        uuid_sub = "550e8400-e29b-41d4-a716-446655440000"

        token = make_test_jwt(email=uuid_sub, expires_in_minutes=10, extra_payload={"token_use": "session"})

        # Both lookups return None
        with patch("mcpgateway.auth._get_user_by_email_sync", return_value=None):
            with patch("mcpgateway.auth._get_email_by_id_sync", return_value=None):
                with patch("mcpgateway.auth._check_token_revoked_sync", return_value=False):
                    result = await verify_credentials(token)

        # Should return payload even without user in DB (when require_user_in_db=False)
        assert result is not None

    @pytest.mark.asyncio
    async def test_uuid_resolution_in_require_admin_auth_lines_1409_1414(self):
        """Cover lines 1409-1414: UUID resolution in require_admin_auth."""
        from fastapi import Request, HTTPException
        from mcpgateway.utils.verify_credentials import require_admin_auth
        from mcpgateway.db import EmailUser
        from unittest.mock import AsyncMock

        uuid_sub = "550e8400-e29b-41d4-a716-446655440000"
        token = make_test_jwt(email=uuid_sub, expires_in_minutes=10, extra_payload={"token_use": "session"})

        mock_user = MagicMock(spec=EmailUser)
        mock_user.email = "admin@example.com"
        mock_user.is_active = True
        mock_user.is_admin = True
        mock_user.id = uuid_sub

        mock_request = MagicMock(spec=Request)
        mock_request.headers.get.return_value = "application/json"

        mock_db_session = MagicMock()
        mock_db_session.query.return_value.filter.return_value.first.return_value = mock_user

        mock_auth_service = MagicMock()
        mock_auth_service.get_user_by_email = AsyncMock(return_value=None)

        with patch("mcpgateway.utils.verify_credentials.settings.email_auth_enabled", True):
            with patch("mcpgateway.db.get_db", return_value=iter([mock_db_session])):
                with patch("mcpgateway.utils.verify_credentials.verify_jwt_token_cached", return_value={"sub": uuid_sub, "token_use": "session"}):
                    with patch("mcpgateway.utils.verify_credentials._enforce_revocation_and_active_user", return_value=None):
                        with patch("mcpgateway.services.email_auth_service.EmailAuthService", return_value=mock_auth_service):
                            result = await require_admin_auth(request=mock_request, jwt_token=token)

        assert result == "admin@example.com"

    @pytest.mark.asyncio
    async def test_uuid_resolution_no_user_in_require_admin_auth_lines_1409_1414(self):
        """Cover lines 1409-1414: UUID resolution returns None in require_admin_auth."""
        from fastapi import Request, HTTPException
        from mcpgateway.utils.verify_credentials import require_admin_auth
        from unittest.mock import AsyncMock

        uuid_sub = "550e8400-e29b-41d4-a716-446655440000"
        token = make_test_jwt(email=uuid_sub, expires_in_minutes=10, extra_payload={"token_use": "session"})

        mock_request = MagicMock(spec=Request)
        mock_request.headers.get.return_value = "application/json"

        mock_db_session = MagicMock()
        mock_db_session.query.return_value.filter.return_value.first.return_value = None

        mock_auth_service = MagicMock()
        mock_auth_service.get_user_by_email = AsyncMock(return_value=None)

        with patch("mcpgateway.utils.verify_credentials.settings.email_auth_enabled", True):
            with patch("mcpgateway.db.get_db", return_value=iter([mock_db_session])):
                with patch("mcpgateway.utils.verify_credentials.verify_jwt_token_cached", return_value={"sub": uuid_sub, "token_use": "session"}):
                    with patch("mcpgateway.utils.verify_credentials._enforce_revocation_and_active_user", return_value=None):
                        with patch("mcpgateway.services.email_auth_service.EmailAuthService", return_value=mock_auth_service):
                            with pytest.raises(HTTPException) as exc_info:
                                await require_admin_auth(request=mock_request, jwt_token=token)

        assert exc_info.value.status_code == 401
