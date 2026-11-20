# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_validation_token_storage.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for validation token storage delegation.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.services.token_backends.base import ValidationToken
from mcpgateway.services.token_storage_service import TokenStorageService


@pytest.mark.asyncio
@pytest.mark.parametrize("team_id", [None, "engineering"])
@pytest.mark.parametrize("token", [None, ValidationToken("expired"), ValidationToken("valid", "validation-value")])
async def test_validation_read_preserves_caller_and_gateway_context(team_id, token):
    """Validation reads use the authenticated team and return backend status unchanged."""
    db = MagicMock()
    settings = MagicMock(oauth_token_backend="database", auth_encryption_secret=None)
    with patch("mcpgateway.services.token_storage_service.get_settings", return_value=settings):
        service = TokenStorageService(db, user_context={"email": "caller@example.com", "teams": [team_id] if team_id else []})
    service._backend.read_validation_token = AsyncMock(return_value=token)
    result = await service.read_validation_token("gw-1", "caller@example.com")
    assert result is token
    service._backend.read_validation_token.assert_awaited_once_with("gw-1", team_id, "caller@example.com")
    db.commit.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("team_id", [None, "engineering"])
async def test_revocation_read_preserves_user_and_gateway_context(team_id):
    """Revocation reads use the authenticated team and return the backend result unchanged."""
    from mcpgateway.services.token_backends.base import RevocationTokens

    db = MagicMock()
    settings = MagicMock(oauth_token_backend="database", auth_encryption_secret=None)
    with patch("mcpgateway.services.token_storage_service.get_settings", return_value=settings):
        service = TokenStorageService(db, user_context={"email": "caller@example.com", "teams": [team_id] if team_id else []})
    tokens = RevocationTokens(access_token="a", refresh_token="r")
    service._backend.read_revocation_tokens = AsyncMock(return_value=tokens)
    assert await service.read_revocation_tokens("gw-1", "caller@example.com") is tokens
    service._backend.read_revocation_tokens.assert_awaited_once_with("gw-1", team_id, "caller@example.com")
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_revocation_read_is_none_on_backends_without_a_read_only_lookup():
    """The base contract reads nothing, so the route deletes without a provider-side revoke."""
    from mcpgateway.services.token_backends.base import AbstractTokenBackend

    assert await AbstractTokenBackend.read_revocation_tokens(MagicMock(), "gw-1", None, "caller@example.com") is None
