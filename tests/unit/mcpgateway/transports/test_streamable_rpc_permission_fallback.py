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
import contextlib
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
    assert call_kwargs.get("check_any_team") is True, "Expected check_any_team=True to be threaded through to PermissionService"


@pytest.mark.asyncio
async def test_check_streamable_permission_api_token_check_any_team_true():
    """API tokens in MCP transport must use check_any_team=True (no team_id available).

    The MCP transport has no route-level team_id, so callers must pass
    check_any_team=True for all token types (both session and API).
    Layer 1 (token scope cap) already restricts what the token can do.
    """
    user_ctx = _make_user_ctx(token_use="api")
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
                check_any_team=True,  # MCP transport: always True (no team_id)
            )

    call_kwargs = mock_ps.check_permission.call_args.kwargs
    assert call_kwargs.get("check_any_team") is True


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
async def test_servers_use_check_passes_check_any_team_for_session_token():
    """servers.use in handle_streamable_http must pass check_any_team=True for session tokens.

    The servers.use check at the ASGI handler level gates access to /servers/{id}/mcp.
    Since developer and team_admin roles grant servers.use as a team-scoped permission,
    session tokens must use check_any_team=True — otherwise they are denied at the
    transport level before even reaching call_tool.
    """
    # Third-Party
    import orjson

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import SessionManagerWrapper, user_context_var

    class DummySessionManager:
        @contextlib.asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            pass

    dummy_manager = DummySessionManager()
    dummy_manager.handle_request = AsyncMock()

    session_user_ctx = {
        "email": "dev@example.com",
        "teams": ["team-abc"],
        "is_admin": False,
        "is_authenticated": True,
        "token_use": "session",
    }

    mock_perm = AsyncMock(return_value=True)

    with patch("mcpgateway.transports.streamablehttp_transport.StreamableHTTPSessionManager", lambda **kwargs: dummy_manager):
        with patch("mcpgateway.transports.streamablehttp_transport.settings") as mock_settings:
            mock_settings.mcpgateway_session_affinity_enabled = False
            mock_settings.use_stateful_sessions = False
            wrapper = SessionManagerWrapper()
            await wrapper.initialize()

            token = user_context_var.set(session_user_ctx)
            try:
                with patch("mcpgateway.transports.streamablehttp_transport._check_streamable_permission", mock_perm):
                    path = "/servers/abc123def456/mcp"
                    scope = {
                        "type": "http",
                        "method": "POST",
                        "path": path,
                        "modified_path": path,
                        "scheme": "https",
                        "server": ("localhost", 4444),
                        "client": ("127.0.0.1", 0),
                        "headers": [(b"mcp-session-id", b"sess-1")],
                    }
                    body = orjson.dumps({"jsonrpc": "2.0", "method": "tools/list", "params": {}, "id": "1"})

                    async def receive():
                        return {"type": "http.request", "body": body}

                    sent = []

                    async def send(msg):
                        sent.append(msg)

                    await wrapper.handle_streamable_http(scope, receive, send)

                    # Verify _check_streamable_permission was called with check_any_team=True
                    mock_perm.assert_called_once()
                    call_kwargs = mock_perm.call_args.kwargs
                    assert call_kwargs.get("check_any_team") is True, f"servers.use check must pass check_any_team=True for session tokens; got {call_kwargs}"
                    assert call_kwargs.get("permission") == "servers.use"
            finally:
                user_context_var.reset(token)
                await wrapper.shutdown()


@pytest.mark.asyncio
async def test_call_tool_raises_permission_error_when_session_token_denied():
    """call_tool must raise PermissionError when _check_streamable_permission returns False.

    Deny-path regression test: even with check_any_team=True for a session token,
    if PermissionService denies the request, call_tool must raise PermissionError
    and not proceed to tool execution.
    """
    # First-Party
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
                    with pytest.raises(PermissionError, match="Access denied"):
                        await call_tool("some_tool", {})
