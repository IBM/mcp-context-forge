# -*- coding: utf-8 -*-
# Copyright contributors to the MCP-CONTEXT-FORGE project
# SPDX-License-Identifier: Apache-2.0
"""Location: ./tests/unit/mcpgateway/test_team_scope.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Regression tests for team management scope boundaries.
"""

# Standard
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi import HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
import pytest

# First-Party
from mcpgateway.config import settings
from mcpgateway.middleware import rbac
from mcpgateway.routers import teams
from mcpgateway.schemas import TeamInviteRequest, TeamMemberAddRequest, TeamMemberUpdateRequest, TeamUpdateRequest

# Local
from tests.helpers.auth import make_test_scope_request


@pytest.mark.asyncio
@pytest.mark.parametrize("claim", [{}, {"teams": None}, {"teams": []}, {"teams": ["a"]}, {"teams": ["a"], "is_admin": True}])
async def test_guard_denies_excluded_team(claim: dict[str, Any]) -> None:
    """Missing, public-only, and narrowed administrator claims exclude Team B."""
    request = Request({"type": "http", "headers": [], "state": {"_jwt_verified_payload": ("signed", {"sub": "owner@example.com", **claim})}})
    with pytest.raises(HTTPException) as error:
        await rbac.require_team_scope(request, {"email": "owner@example.com", "is_admin": True}, "b", MagicMock())
    assert error.value.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", [["b"], None])
async def test_guard_allows_canonical_scope(scope: list[str] | None) -> None:
    """In-scope tokens and canonical administrator bypass pass the scope check."""
    await rbac.require_team_scope(make_test_scope_request(scope), {"email": "owner@example.com"}, "b", MagicMock())


@pytest.mark.asyncio
async def test_unknown_context_denied() -> None:
    """Unknown identity receives no implicit administrator scope."""
    with pytest.raises(HTTPException) as error:
        await rbac.require_team_scope(make_test_scope_request(), {}, "b", MagicMock())
    assert error.value.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,body",
    [
        ("get_team", {}),
        ("update_team", {"request": TeamUpdateRequest(name="Changed")}),
        ("delete_team", {}),
        ("list_team_members", {}),
        ("add_team_member", {"request": TeamMemberAddRequest(email="outsider@example.com", role="owner")}),
        ("update_team_member", {"user_email": "member@example.com", "request": TeamMemberUpdateRequest(role="owner")}),
        ("remove_team_member", {"user_email": "member@example.com"}),
        ("invite_team_member", {"request": TeamInviteRequest(email="invitee@example.com", role="member")}),
        ("list_team_invitations", {}),
        ("leave_team", {}),
        ("list_team_join_requests", {}),
        ("approve_join_request", {"request_id": "join-b"}),
        ("reject_join_request", {"request_id": "join-b"}),
    ],
)
async def test_management_handlers_deny_before_services(name: str, body: dict[str, Any]) -> None:
    """Every named management handler rejects cross-team access before service calls."""
    handler = getattr(teams, name)
    handler = getattr(handler, "__wrapped__", handler)
    db = MagicMock()
    with patch.object(teams, "TeamManagementService") as service, pytest.raises(HTTPException) as error:
        await handler(team_id="b", current_user={"email": "owner@example.com"}, db=db, http_request=make_test_scope_request(["a"]), **body)
    assert error.value.status_code == 403
    service.assert_not_called()
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_uses_stored_team() -> None:
    """Cancellation checks the stored invitation team before revocation."""
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(team_id="b")
    handler = getattr(teams.cancel_team_invitation, "__wrapped__", teams.cancel_team_invitation)
    with patch.object(teams, "TeamInvitationService") as service, pytest.raises(HTTPException) as error:
        await handler("invitation-b", current_user={"email": "owner@example.com"}, db=db, http_request=make_test_scope_request(["a"]))
    assert error.value.status_code == 403
    service.return_value.revoke_invitation.assert_not_called()
    db.commit.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["admin_view_team_members", "admin_add_team_members"])
async def test_admin_equivalents_deny_scope(name: str) -> None:
    """Admin roster and member forms reject cross-team scope before service access."""
    from mcpgateway import admin

    handler = getattr(admin, name)
    handler = getattr(handler, "__wrapped__", handler)
    with patch.object(admin, "TeamManagementService") as service, pytest.raises(HTTPException) as error:
        await handler("b", request=make_test_scope_request(["a"]), user={"email": "owner@example.com"}, db=MagicMock())
    assert error.value.status_code == 403
    service.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("is_admin", [False, True])
@pytest.mark.parametrize("target", ["a", "b"])
async def test_proxy_selected_identity_retains_local_scope(monkeypatch: pytest.MonkeyPatch, is_admin: bool, target: str) -> None:
    """Real proxy authentication retains its scope despite conflicting JWT state."""
    monkeypatch.setattr(settings, "mcp_client_auth_enabled", False)
    monkeypatch.setattr(settings, "trust_proxy_auth", True)
    monkeypatch.setattr(settings, "trust_proxy_auth_dangerously", True)
    email = "proxy@example.com"
    request = Request(
        {
            "type": "http",
            "headers": [(settings.proxy_user_header.lower().encode(), email.encode()), (b"cookie", b"jwt_token=conflicting")],
            "state": {
                "token_teams": [],
                "_jwt_verified_payload": ("conflicting", {"teams": [], "is_admin": False}),
            },
        }
    )
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = SimpleNamespace(is_admin=is_admin, full_name="Proxy User")
    conflicting_token = request.state._jwt_verified_payload[0]
    with patch.object(rbac, "fresh_db_session") as session:
        session.return_value.__enter__.return_value = db
        user = await rbac.get_current_user_with_permissions(request, credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials=conflicting_token), jwt_token=conflicting_token)
    with patch("mcpgateway.services.team_management_service.TeamManagementService") as service:
        service.return_value.get_user_teams = AsyncMock(return_value=[SimpleNamespace(id="a")])
        if not is_admin and target == "b":
            with pytest.raises(HTTPException) as error:
                await rbac.require_team_scope(request, user, target, db)
            assert error.value.status_code == 403
        else:
            await rbac.require_team_scope(request, user, target, db)
    assert user["token_teams"] == (None if is_admin else ["a"])


@pytest.mark.asyncio
async def test_untrusted_header_grants_no_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    """An untrusted proxy header cannot expand verified JWT scope."""
    monkeypatch.setattr(settings, "trust_proxy_auth", False)
    request = make_test_scope_request(["a"])
    request.scope["headers"] = [(settings.proxy_user_header.lower().encode(), b"owner@example.com")]
    with pytest.raises(HTTPException):
        await rbac.require_team_scope(request, {"email": "owner@example.com", "auth_method": "proxy"}, "b", MagicMock())
