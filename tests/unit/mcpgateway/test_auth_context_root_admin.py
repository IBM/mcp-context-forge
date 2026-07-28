# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_auth_context_root_admin.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Root-specific unrestricted platform-admin helper tests.
"""

# Standard
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import pytest

# First-Party
from mcpgateway.auth_context import is_unrestricted_platform_admin


def _request_with_teams(token_teams):
    request = MagicMock()
    request.state = SimpleNamespace(token_teams=token_teams)
    return request


@pytest.mark.asyncio
async def test_unrestricted_admin_checks_platform_admin_permission(monkeypatch):
    check = AsyncMock(return_value=True)
    service = MagicMock()
    service.check_platform_admin_permission = check
    monkeypatch.setattr("mcpgateway.services.permission_service.PermissionService", lambda db: service)

    allowed = await is_unrestricted_platform_admin(_request_with_teams(None), {"email": "admin@example.com"}, MagicMock())

    assert allowed is True
    check.assert_awaited_once_with("admin@example.com", token_teams=None)


@pytest.mark.asyncio
@pytest.mark.parametrize("token_teams", [[], ["team-a"]])
async def test_narrowed_or_public_only_tokens_fail_closed(monkeypatch, token_teams):
    check = AsyncMock(return_value=True)
    service = MagicMock()
    service.check_platform_admin_permission = check
    monkeypatch.setattr("mcpgateway.services.permission_service.PermissionService", lambda db: service)

    allowed = await is_unrestricted_platform_admin(_request_with_teams(token_teams), {"email": "admin@example.com"}, MagicMock())

    assert allowed is False
    check.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_identity_or_request_fails_closed(monkeypatch):
    check = AsyncMock(return_value=True)
    service = MagicMock()
    service.check_platform_admin_permission = check
    monkeypatch.setattr("mcpgateway.services.permission_service.PermissionService", lambda db: service)

    assert await is_unrestricted_platform_admin(None, {"email": "admin@example.com"}, MagicMock()) is False
    assert await is_unrestricted_platform_admin(_request_with_teams(None), {}, MagicMock()) is False
    check.assert_not_awaited()
