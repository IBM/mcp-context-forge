# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/transports/test_streamable_rpc_permission_fallback.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Regression tests for session-token team-permission fallback in the /mcp transport.
Ref: https://github.com/IBM/mcp-context-forge/issues/3515

These tests assert that _check_streamable_permission is called with check_any_team=True
for session tokens, which requires the call_tool handler to detect token_use="session"
from user_context and pass it through. Before the fix (Task 5), token_use is not stored
in auth_user_ctx, so check_any_team is never True.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.transports.streamablehttp_transport import _check_streamable_permission


def _make_user_ctx(token_use: str = "session", teams=None) -> dict:
    """Build a user context dict as produced by the streamablehttp auth middleware."""
    ctx = {
        "email": "user@example.com",
        "is_admin": False,
        "is_authenticated": True,
        "teams": teams if teams is not None else ["team-abc123"],
    }
    if token_use is not None:
        ctx["token_use"] = token_use
    return ctx


@pytest.mark.asyncio
async def test_check_streamable_permission_session_token_passes_check_any_team_true():
    """_check_streamable_permission must forward check_any_team=True for session tokens.

    This test verifies the contract at the PermissionService level.
    The call_tool handler (Task 5) is responsible for detecting session tokens
    and passing check_any_team=True into _check_streamable_permission.
    Here we confirm the function correctly threads check_any_team through.
    """
    user_ctx = _make_user_ctx(token_use="session")
    mock_ps = MagicMock()
    mock_ps.check_permission = AsyncMock(return_value=True)

    with patch("mcpgateway.transports.streamablehttp_transport.PermissionService", return_value=mock_ps):
        with patch("mcpgateway.transports.streamablehttp_transport.get_db") as mock_get_db:
            mock_db_ctx = MagicMock()
            mock_db_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_db_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_get_db.return_value = mock_db_ctx

            result = await _check_streamable_permission(
                user_context=user_ctx,
                permission="tools.execute",
                check_any_team=True,  # call site (Task 5) will pass this for session tokens
            )

    assert result is True
    mock_ps.check_permission.assert_called_once()
    call_kwargs = mock_ps.check_permission.call_args.kwargs
    assert call_kwargs.get("check_any_team") is True, (
        "Expected check_any_team=True to be threaded through to PermissionService"
    )


@pytest.mark.asyncio
async def test_check_streamable_permission_api_token_check_any_team_false():
    """API tokens (not session) must use check_any_team=False."""
    user_ctx = _make_user_ctx(token_use="access")
    mock_ps = MagicMock()
    mock_ps.check_permission = AsyncMock(return_value=True)

    with patch("mcpgateway.transports.streamablehttp_transport.PermissionService", return_value=mock_ps):
        with patch("mcpgateway.transports.streamablehttp_transport.get_db") as mock_get_db:
            mock_db_ctx = MagicMock()
            mock_db_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_db_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_get_db.return_value = mock_db_ctx

            await _check_streamable_permission(
                user_context=user_ctx,
                permission="tools.execute",
                check_any_team=False,  # non-session: False
            )

    call_kwargs = mock_ps.check_permission.call_args.kwargs
    assert call_kwargs.get("check_any_team", False) is False


@pytest.mark.asyncio
async def test_check_streamable_permission_no_token_use_defaults_false():
    """user_context without token_use (older format) must default check_any_team=False."""
    user_ctx = _make_user_ctx(token_use=None)  # no token_use key
    mock_ps = MagicMock()
    mock_ps.check_permission = AsyncMock(return_value=True)

    with patch("mcpgateway.transports.streamablehttp_transport.PermissionService", return_value=mock_ps):
        with patch("mcpgateway.transports.streamablehttp_transport.get_db") as mock_get_db:
            mock_db_ctx = MagicMock()
            mock_db_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_db_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_get_db.return_value = mock_db_ctx

            await _check_streamable_permission(
                user_context=user_ctx,
                permission="tools.execute",
                check_any_team=False,  # no token_use → False
            )

    call_kwargs = mock_ps.check_permission.call_args.kwargs
    assert call_kwargs.get("check_any_team", False) is False


@pytest.mark.asyncio
async def test_call_tool_raises_permission_error_when_session_token_denied():
    """call_tool must raise PermissionError when _check_streamable_permission returns False.

    Deny-path regression test: even with check_any_team=True for a session token,
    if PermissionService denies the request, call_tool must raise PermissionError
    and not proceed to tool execution.
    """
    # Standard
    from mcpgateway.transports.streamablehttp_transport import call_tool

    session_user_ctx = {
        "email": "user@example.com",
        "is_admin": False,
        "is_authenticated": True,
        "token_use": "session",
        "teams": ["team-abc123"],
    }

    with patch(
        "mcpgateway.transports.streamablehttp_transport._get_request_context_or_default",
        new=AsyncMock(return_value=(None, {}, session_user_ctx)),
    ):
        with patch(
            "mcpgateway.transports.streamablehttp_transport._should_enforce_streamable_rbac",
            return_value=True,
        ):
            with patch(
                "mcpgateway.transports.streamablehttp_transport._check_scoped_permission",
                return_value=True,
            ):
                with patch(
                    "mcpgateway.transports.streamablehttp_transport._check_streamable_permission",
                    new=AsyncMock(return_value=False),
                ):
                    with pytest.raises(PermissionError, match="tools.execute"):
                        await call_tool("some_tool", {})
