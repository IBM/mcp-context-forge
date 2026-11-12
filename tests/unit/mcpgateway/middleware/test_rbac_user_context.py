# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/middleware/test_rbac_user_context.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests that the RBAC user context carries the canonical user_id.

The authenticated context built by get_current_user_with_permissions must
expose the canonical user_id (resolving user_id -> email -> sub -> "unknown"
via mcpgateway.auth_context.get_user_id), not only the e-mail attribute, so
live RBAC checks can key on the stable identity.
"""

# Standard
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.middleware.rbac import get_current_user_with_permissions


def _mock_request():
    """Build a minimal browser-style request for the JWT auth path."""

    class MockState:
        pass

    mock_request = MagicMock()
    mock_request.state = MockState()
    mock_request.state.auth_method = "simple_token"
    mock_request.state.request_id = "test-request-id"
    mock_request.client = MagicMock()
    mock_request.client.host = "127.0.0.1"
    mock_request.headers = {"user-agent": "TestAgent", "accept": "text/html"}  # Browser request allows cookie auth
    mock_request.cookies = {"jwt_token": "test-token"}
    return mock_request


@pytest.mark.asyncio
async def test_user_context_carries_canonical_user_id():
    """The authenticated context must expose the canonical user_id, not only email."""
    # Minimal principal whose user_id diverges from email — the F8 case.
    principal = SimpleNamespace(
        email="alice@example.com",
        user_id="entra-sub-123",
        full_name="Alice",
        is_admin=False,
        teams=[],
    )

    with patch("mcpgateway.auth.validate_token_user", new_callable=AsyncMock) as mock_validate:
        mock_validate.return_value = principal

        ctx = await get_current_user_with_permissions(
            request=_mock_request(),
            credentials=None,
            jwt_token="test-token",
        )

    assert ctx["email"] == "alice@example.com"
    assert ctx["user_id"] == "entra-sub-123"


@pytest.mark.asyncio
async def test_user_context_user_id_falls_back_to_email():
    """A principal without an explicit user_id resolves user_id to its email."""
    principal = SimpleNamespace(
        email="bob@example.com",
        full_name="Bob",
        is_admin=False,
    )

    with patch("mcpgateway.auth.validate_token_user", new_callable=AsyncMock) as mock_validate:
        mock_validate.return_value = principal

        ctx = await get_current_user_with_permissions(
            request=_mock_request(),
            credentials=None,
            jwt_token="test-token",
        )

    assert ctx["user_id"] == "bob@example.com"
