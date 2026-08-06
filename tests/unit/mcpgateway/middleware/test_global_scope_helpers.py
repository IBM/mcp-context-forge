# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/middleware/test_global_scope_helpers.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Shared global-record scope helper tests.
"""

# Standard
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# Third-Party
from fastapi import HTTPException
import pytest

# First-Party
from mcpgateway.middleware.rbac import require_global_admin_permission, require_unrestricted_platform_admin


def _request(token_teams, path="/compliance/reports"):
    request = MagicMock()
    request.state = SimpleNamespace(token_teams=token_teams)
    request.url = SimpleNamespace(path=path)
    return request


@pytest.mark.asyncio
async def test_raise_helper_allows_unrestricted_admin(monkeypatch):
    monkeypatch.setattr("mcpgateway.auth_context.is_unrestricted_platform_admin", AsyncMock(return_value=True))

    assert await require_unrestricted_platform_admin(_request(None), {"email": "a@x.com"}, MagicMock()) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("token_teams", [[], ["team-a"]])
async def test_raise_helper_denies_narrowed_and_public_only(monkeypatch, token_teams, caplog):
    monkeypatch.setattr("mcpgateway.auth_context.is_unrestricted_platform_admin", AsyncMock(return_value=False))

    with pytest.raises(HTTPException) as exc:
        await require_unrestricted_platform_admin(_request(token_teams), {"email": "a@x.com"}, MagicMock())

    assert exc.value.status_code == 403
    # Denial must be self-diagnosing: identity, route, resolved scope, remediation.
    assert "a@x.com" in caplog.text
    assert "/compliance/reports" in caplog.text
    assert repr(token_teams) in caplog.text
    assert "--admin" in caplog.text
    # Detail carries remediation but never a permission name.
    assert "--admin" in exc.value.detail


@pytest.mark.asyncio
async def test_decorator_allows_unrestricted_admin(monkeypatch):
    monkeypatch.setattr("mcpgateway.auth_context.is_unrestricted_platform_admin", AsyncMock(return_value=True))

    @require_global_admin_permission()
    async def endpoint(request=None, user=None, db=None):
        return "ok"

    assert await endpoint(request=_request(None), user={"email": "a@x.com"}, db=MagicMock()) == "ok"


@pytest.mark.asyncio
async def test_decorator_denies_narrowed_admin(monkeypatch):
    monkeypatch.setattr("mcpgateway.auth_context.is_unrestricted_platform_admin", AsyncMock(return_value=False))

    @require_global_admin_permission()
    async def endpoint(request=None, user=None, db=None):
        return "ok"

    with pytest.raises(HTTPException) as exc:
        await endpoint(request=_request(["team-a"]), user={"email": "a@x.com"}, db=MagicMock())
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_decorator_rejects_missing_user_context():
    @require_global_admin_permission()
    async def endpoint(request=None, user=None, db=None):
        return "ok"

    with pytest.raises(HTTPException) as exc:
        await endpoint(request=_request(None), user=None, db=MagicMock())
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_decorator_creates_session_when_endpoint_has_no_db(monkeypatch):
    """list_frameworks has neither request nor db today; the decorator must cope."""
    predicate = AsyncMock(return_value=True)
    monkeypatch.setattr("mcpgateway.auth_context.is_unrestricted_platform_admin", predicate)
    fake_cm = MagicMock()
    fake_cm.__enter__ = MagicMock(return_value="session")
    fake_cm.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr("mcpgateway.middleware.rbac.fresh_db_session", lambda: fake_cm)

    @require_global_admin_permission()
    async def endpoint(request=None, user=None):
        return "ok"

    assert await endpoint(request=_request(None), user={"email": "a@x.com"}) == "ok"
    assert predicate.await_args.args[2] == "session"


def test_decorator_sets_scope_class_marker():
    """The drift guard inspects this marker instead of parsing source."""

    @require_global_admin_permission()
    async def endpoint(request=None, user=None, db=None):
        return "ok"

    assert endpoint.__mcpgateway_scope_class__ == "global_only"
