# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_tool_preview_handler.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for server authorization in the tool preview handler.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock

# Third-Party
from fastapi import HTTPException, Request
import pytest

# First-Party
import mcpgateway.main as main_mod
from mcpgateway.middleware.rbac import get_current_user_with_permissions
from mcpgateway.schemas import ToolAnnotations, ToolPreviewRequest, ToolPreviewResponse, ToolPreviewTarget
from mcpgateway.services.server_service import ServerNotFoundError


@pytest.fixture
def preview_context(monkeypatch):
    """Supply a request with verified claims and isolated server/tool services."""
    monkeypatch.setattr(main_mod.settings, "mcpgateway_tool_preview_enabled", True)
    request = Request({"type": "http", "method": "POST", "path": "/tools/preview/echo", "headers": []})
    request.state._jwt_verified_payload = ("test-token", {"sub": "user@example.com", "scopes": {}})
    ensure_access = AsyncMock()
    preview = AsyncMock(return_value=ToolPreviewResponse(validated=True, resolved_arguments={}, target=ToolPreviewTarget(kind="local"), annotations=ToolAnnotations()))
    monkeypatch.setattr(main_mod.server_service, "ensure_server_access", ensure_access)
    monkeypatch.setattr(main_mod.tool_service, "preview_tool_invocation", preview)
    return request, MagicMock(), ensure_access, preview


@pytest.mark.asyncio
async def test_preview_handler_rejects_cross_server_token(preview_context):
    """The handler's own scope check denies a mismatch before either service runs."""
    request, db, ensure_access, preview = preview_context
    request.state._jwt_verified_payload = ("test-token", {"scopes": {"server_id": "server-allowed"}})

    with pytest.raises(HTTPException) as exc_info:
        await main_mod.preview_tool.__wrapped__("echo", request, body=ToolPreviewRequest(server_id="server-denied"), db=db, user={"email": "user@example.com"})

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Token not authorized for server: server-denied"
    ensure_access.assert_not_awaited()
    preview.assert_not_awaited()


@pytest.mark.asyncio
async def test_preview_handler_preserves_trusted_proxy_auth(preview_context, monkeypatch):
    """An authenticated proxy user may carry an opaque bearer token without JWT claims."""
    request, db, ensure_access, preview = preview_context
    request.state._jwt_verified_payload = None
    monkeypatch.setattr(main_mod.settings, "mcp_client_auth_enabled", False)
    monkeypatch.setattr(main_mod.settings, "trust_proxy_auth", True)
    monkeypatch.setattr(main_mod.settings, "trust_proxy_auth_dangerously", True)
    monkeypatch.setattr(main_mod.settings, "proxy_user_header", "X-Authenticated-User")
    request.scope["headers"] = [
        (b"x-authenticated-user", main_mod.settings.platform_admin_email.encode()),
        (b"authorization", b"Bearer opaque-idp-token"),
    ]

    user = await get_current_user_with_permissions(request, credentials=None, jwt_token=None)
    assert user["auth_method"] == "proxy"
    assert request.state._jwt_verified_payload is None

    response = await main_mod.preview_tool.__wrapped__("echo", request, body=ToolPreviewRequest(server_id="server-allowed"), db=db, user=user)

    assert response.validated is True
    ensure_access.assert_awaited_once()
    assert ensure_access.await_args.kwargs["server_id"] == "server-allowed"
    assert ensure_access.await_args.kwargs["user_email"] == user["email"]
    assert preview.await_args.kwargs["server_id"] == "server-allowed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cached",
    [
        "not-a-cache-tuple",
        ("test-token",),
        ("test-token", None),
        ("test-token", {"scopes": None}),
        ("test-token", {"scopes": []}),
        ("test-token", {"scopes": "unreadable"}),
    ],
)
async def test_preview_handler_rejects_malformed_cached_scopes(preview_context, cached):
    """Malformed cached authorization data must not fall back to global scope."""
    request, db, ensure_access, preview = preview_context
    request.state._jwt_verified_payload = cached

    with pytest.raises(HTTPException) as exc_info:
        await main_mod.preview_tool.__wrapped__("echo", request, body=ToolPreviewRequest(server_id="server-allowed"), db=db, user={"email": "user@example.com"})

    assert exc_info.value.status_code == 403
    ensure_access.assert_not_awaited()
    preview.assert_not_awaited()


@pytest.mark.asyncio
async def test_preview_handler_maps_hidden_server_to_404(preview_context):
    """A denied or missing server has the generic 404 and never reaches tool preview."""
    request, db, ensure_access, preview = preview_context
    ensure_access.side_effect = ServerNotFoundError("Server not found: server-hidden")

    with pytest.raises(HTTPException) as exc_info:
        await main_mod.preview_tool.__wrapped__("echo", request, body=ToolPreviewRequest(server_id="server-hidden"), db=db, user={"email": "user@example.com"})

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Server not found: server-hidden"
    ensure_access.assert_awaited_once()
    preview.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"token_use": "session"}, {"scopes": {}}, {"scopes": {"server_id": "server-allowed"}}])
async def test_preview_handler_uses_verified_payload(preview_context, payload):
    """Legacy, session, global, and matching server scopes use the verified cache."""
    request, db, ensure_access, preview = preview_context
    request.state._jwt_verified_payload = ("test-token", payload)

    response = await main_mod.preview_tool.__wrapped__("echo", request, body=ToolPreviewRequest(server_id="server-allowed", arguments={"message": "hello"}), db=db, user={"email": "user@example.com"})

    assert response.validated is True
    ensure_access.assert_awaited_once()
    assert preview.await_args.kwargs["server_id"] == "server-allowed"
    assert preview.await_args.kwargs["arguments"] == {"message": "hello"}


@pytest.mark.asyncio
async def test_preview_handler_preserves_non_jwt_authentication(preview_context):
    """Authenticated non-JWT callers still undergo the server visibility check."""
    request, db, ensure_access, preview = preview_context
    request.state._jwt_verified_payload = None

    response = await main_mod.preview_tool.__wrapped__("echo", request, body=ToolPreviewRequest(server_id="server-allowed"), db=db, user={"email": "user@example.com"})

    assert response.validated is True
    ensure_access.assert_awaited_once()
    preview.assert_awaited_once()


@pytest.mark.asyncio
async def test_preview_handler_unscoped_request_skips_server_checks(preview_context):
    """Omitting server_id preserves the global preview path."""
    request, db, ensure_access, preview = preview_context
    request.state._jwt_verified_payload = None
    request.scope["headers"] = [(b"authorization", b"Bearer test-token")]

    response = await main_mod.preview_tool.__wrapped__("echo", request, body=ToolPreviewRequest(), db=db, user={"email": "user@example.com"})

    assert response.validated is True
    ensure_access.assert_not_awaited()
    assert preview.await_args.kwargs["server_id"] is None
