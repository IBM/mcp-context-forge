# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_version_scope.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Layer-1 scope enforcement on the diagnostics endpoint.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock

# Third-Party
from fastapi import HTTPException
import pytest

# First-Party
from mcpgateway.version import version_endpoint
from tests.helpers.scope import scoped_request


@pytest.mark.asyncio
@pytest.mark.parametrize("token_teams", [[], ["team-a"]])
async def test_narrowed_admin_denied(monkeypatch, token_teams):
    monkeypatch.setattr("mcpgateway.auth_context.is_unrestricted_platform_admin", AsyncMock(return_value=False))

    with pytest.raises(HTTPException) as exc:
        await version_endpoint(scoped_request(token_teams, path="/version"), _user="admin@example.com")

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_unrestricted_admin_allowed(monkeypatch):
    monkeypatch.setattr("mcpgateway.auth_context.is_unrestricted_platform_admin", AsyncMock(return_value=True))
    monkeypatch.setattr("mcpgateway.version._build_payload", MagicMock(return_value={"ok": True}))

    response = await version_endpoint(scoped_request(None, path="/version"), _user="admin@example.com")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_basic_auth_string_identity_is_still_accepted(monkeypatch):
    """require_admin_auth returns a bare email for basic auth; that path must keep working."""
    monkeypatch.setattr("mcpgateway.auth_context.is_unrestricted_platform_admin", AsyncMock(return_value=True))
    monkeypatch.setattr("mcpgateway.version._build_payload", MagicMock(return_value={"ok": True}))

    response = await version_endpoint(scoped_request(None, path="/version"), _user="basic-auth-user@example.com")

    assert response.status_code == 200
