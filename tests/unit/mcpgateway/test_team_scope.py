# -*- coding: utf-8 -*-
# Copyright contributors to the MCP-CONTEXT-FORGE project
# SPDX-License-Identifier: Apache-2.0
"""Location: ./tests/unit/mcpgateway/test_team_scope.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Regression tests for team management scope boundaries.
"""

# Standard
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
import logging
import secrets
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi import HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import Base, EmailTeam, EmailTeamInvitation, EmailTeamMember, EmailUser
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
async def test_scope_denial_logs_sanitized_identity_without_credentials(caplog: pytest.LogCaptureFixture) -> None:
    """Denials log canonical sanitized fields before protected service access."""
    user_id = "caller\r\n\x1b[31midentity"
    team_id = "foreign\n\x00team"
    material = secrets.token_urlsafe(32)
    request = make_test_scope_request(["a"])
    request.scope["headers"] = [(b"authorization", f"Bearer {material}".encode())]
    user = {"email": "owner@example.com", "user_id": user_id, "token": material}
    handler = getattr(teams.get_team, "__wrapped__", teams.get_team)
    with caplog.at_level(logging.WARNING, logger=rbac.__name__), patch.object(teams, "TeamManagementService") as service:
        with pytest.raises(HTTPException) as error:
            await handler(team_id, current_user=user, db=MagicMock(), http_request=request)
    assert error.value.status_code == 403
    service.assert_not_called()
    records = [record for record in caplog.records if record.name == rbac.__name__]
    assert len(records) == 1
    message = records[0].getMessage()
    assert "user_id=caller  identity" in message
    assert "team_id=foreign team" in message
    assert all(value not in message for value in (material, "owner@example.com", "\n", "\r", "\x1b", "\x00"))


@pytest.fixture
def invitation_scope_database() -> Iterator[Session]:
    """Provide persisted invitation state for visibility and revocation checks."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([EmailUser(email=email, password_hash="", full_name="Invitation Scope") for email in ("owner@example.com", "other@example.com")])
        db.flush()
        db.add(EmailTeam(id="b", name="Private Team", slug="private-team", created_by="owner@example.com", visibility="private"))
        db.flush()
        db.add(EmailTeamMember(team_id="b", user_email="owner@example.com", role="owner"))
        db.add(
            EmailTeamInvitation(
                id="invitation-b",
                team_id="b",
                email="invitee@example.com",
                invited_by="owner@example.com",
                token=secrets.token_urlsafe(32),
                expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            )
        )
        db.commit()
        yield db
    engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", [["a"], []])
async def test_cancel_invitation_hides_excluded_and_missing_ids(invitation_scope_database: Session, scope: list[str], caplog: pytest.LogCaptureFixture) -> None:
    """Scoped SQL lookup hides foreign existence and preserves invitation state."""
    db = invitation_scope_database
    handler = getattr(teams.cancel_team_invitation, "__wrapped__", teams.cancel_team_invitation)
    failures = []
    with patch.object(teams, "TeamInvitationService") as service:
        for invitation_id in ("invitation-b", "missing"):
            with pytest.raises(HTTPException) as error:
                await handler(invitation_id, current_user={"email": "owner@example.com"}, db=db, http_request=make_test_scope_request(scope))
            failures.append((error.value.status_code, error.value.detail))
        service.return_value.revoke_invitation.assert_not_called()
    assert failures == [(404, "Invitation not found")] * 2
    assert "invitation-b" not in caplog.text
    with Session(db.get_bind()) as independent:
        stored = independent.get(EmailTeamInvitation, "invitation-b")
        assert stored is not None and stored.is_active


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", [["b"], None])
async def test_cancel_invitation_preserves_in_scope_owner(invitation_scope_database: Session, scope: list[str] | None) -> None:
    """In-scope owners and canonical scope bypass can revoke stored invitations."""
    db = invitation_scope_database
    handler = getattr(teams.cancel_team_invitation, "__wrapped__", teams.cancel_team_invitation)
    response = await handler("invitation-b", current_user={"email": "owner@example.com"}, db=db, http_request=make_test_scope_request(scope))
    assert response.success
    with Session(db.get_bind()) as independent:
        stored = independent.get(EmailTeamInvitation, "invitation-b")
        assert stored is not None and not stored.is_active


@pytest.mark.asyncio
async def test_cancel_invitation_retains_owner_or_inviter_check(invitation_scope_database: Session) -> None:
    """Scope alone cannot authorize a caller without ownership or inviter authority."""
    db = invitation_scope_database
    handler = getattr(teams.cancel_team_invitation, "__wrapped__", teams.cancel_team_invitation)
    with pytest.raises(HTTPException) as error:
        await handler("invitation-b", current_user={"email": "other@example.com"}, db=db, http_request=make_test_scope_request(["b"]))
    assert error.value.status_code == 403
    with Session(db.get_bind()) as independent:
        stored = independent.get(EmailTeamInvitation, "invitation-b")
        assert stored is not None and stored.is_active


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


_UI_TEAM_ID = "b" * 32

_UI_MANAGEMENT_HANDLERS = (
    "admin_add_team_members_view",
    "admin_get_team_edit",
    "admin_update_team",
    "admin_delete_team",
    "admin_update_team_member_role",
    "admin_remove_team_member",
    "admin_leave_team",
    "admin_list_join_requests",
    "admin_approve_join_request",
    "admin_reject_join_request",
    "admin_team_members_partial_html",
    "admin_team_non_members_partial_html",
)


async def _call_ui_handler(name: str, request: Request, user: dict[str, Any], db: Any) -> Any:
    """Call a team UI handler with its production scope guard.

    Args:
        name: Handler name in the Admin UI module.
        request: Request carrying canonical authentication scope.
        user: Authenticated principal.
        db: Mocked database session.

    Returns:
        The handler response when authorization permits access.
    """
    import inspect
    from mcpgateway import admin

    handler = getattr(admin, name)
    handler = getattr(handler, "__wrapped__", handler)
    parameters = inspect.signature(handler).parameters
    kwargs: dict[str, Any] = {"team_id": _UI_TEAM_ID, "db": db}
    kwargs["_request" if "_request" in parameters else "request"] = request
    kwargs["_user" if "_user" in parameters else "user"] = user
    if "request_id" in parameters:
        kwargs["request_id"] = "request-b"
    return await handler(**kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", _UI_MANAGEMENT_HANDLERS)
@pytest.mark.parametrize("scope", [["a"], []])
async def test_remaining_ui_handlers_deny_scope(name: str, scope: list[str]) -> None:
    """Each remaining handler rejects excluded teams before service access."""
    from mcpgateway import admin

    db = MagicMock()
    with patch.object(admin, "TeamManagementService") as service, pytest.raises(HTTPException) as error:
        await _call_ui_handler(name, make_test_scope_request(scope), {"email": "owner@example.com"}, db)
    assert error.value.status_code == 403
    service.assert_not_called()
    db.commit.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("name", _UI_MANAGEMENT_HANDLERS)
async def test_remaining_ui_handlers_preserve_disabled_feature(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Disabled email authentication prevents team data access and mutation."""
    from mcpgateway import admin

    monkeypatch.setattr(settings, "email_auth_enabled", False)
    with patch.object(admin, "TeamManagementService") as service:
        response = await _call_ui_handler(name, make_test_scope_request([_UI_TEAM_ID]), {"email": "owner@example.com"}, MagicMock())
    assert response.status_code == (200 if name.endswith("partial_html") else 403)
    assert b"disabled" in response.body.lower()
    service.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["admin_get_team_edit", "admin_update_team", "admin_delete_team"])
async def test_ui_nonowner_denial_survives_error_boundaries(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """In-scope non-owners retain 403 independently of action permissions."""
    from mcpgateway import admin

    monkeypatch.setattr(settings, "email_auth_enabled", True)
    service = MagicMock()
    service.get_team_by_id = AsyncMock(return_value=SimpleNamespace(is_personal=False))
    service.get_user_role_in_team = AsyncMock(return_value="member")
    permission = MagicMock()
    permission.check_platform_admin_permission = AsyncMock(return_value=False)
    with patch.object(admin, "TeamManagementService", return_value=service), patch.object(admin, "PermissionService", return_value=permission):
        with pytest.raises(HTTPException) as error:
            await _call_ui_handler(name, make_test_scope_request([_UI_TEAM_ID]), {"email": "member@example.com", "token_teams": ["b"]}, MagicMock())
    assert error.value.status_code == 403
    service.update_team.assert_not_called()
    service.delete_team.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("role,is_admin,allowed", [("owner", False, True), ("member", False, False), (None, False, False), (None, True, True)])
async def test_ui_owner_or_admin_contract(role: str | None, is_admin: bool, allowed: bool) -> None:
    """Owner and platform-administrator authority remain distinct from ordinary membership."""
    from mcpgateway import admin

    service = MagicMock()
    service.get_user_role_in_team = AsyncMock(return_value=role)
    permission = MagicMock()
    permission.check_platform_admin_permission = AsyncMock(return_value=is_admin)
    with patch.object(admin, "TeamManagementService", return_value=service), patch.object(admin, "PermissionService", return_value=permission):
        if allowed:
            assert await admin._require_team_owner_or_admin("b", {"email": "actor@example.com", "token_teams": ["b"]}, MagicMock()) is is_admin
        else:
            with pytest.raises(HTTPException) as error:
                await admin._require_team_owner_or_admin("b", {"email": "actor@example.com", "token_teams": ["b"]}, MagicMock())
            assert error.value.status_code == 403
    permission.check_platform_admin_permission.assert_awaited_once_with("actor@example.com", token_teams=["b"])


@pytest.mark.asyncio
@pytest.mark.parametrize("is_admin", [False, True])
@pytest.mark.parametrize("scope", [["a"], [], None])
async def test_ui_id_collection_applies_canonical_scope(is_admin: bool, scope: list[str] | None) -> None:
    """Administrator and ordinary branches filter IDs and counts by canonical scope."""
    from mcpgateway import admin

    service = MagicMock()
    all_ids = ["a", "b"]
    expected = all_ids if scope is None else [value for value in all_ids if value in scope]
    service.get_all_team_ids = AsyncMock(return_value=expected)
    service.get_user_teams = AsyncMock(return_value=[SimpleNamespace(id=value, name=value, slug=value, is_active=True, visibility="private") for value in all_ids])
    auth = MagicMock()
    auth.get_user_by_email = AsyncMock(return_value=SimpleNamespace(is_admin=is_admin))
    handler = getattr(admin.admin_get_all_team_ids, "__wrapped__", admin.admin_get_all_team_ids)
    with patch.object(admin, "TeamManagementService", return_value=service), patch.object(admin, "EmailAuthService", return_value=auth):
        result = await handler(request=make_test_scope_request(scope), include_inactive=False, visibility=None, q=None, db=MagicMock(), user={"email": "actor@example.com"})
    assert result == {"team_ids": expected, "count": len(expected)}
    if is_admin:
        recorded_call = service.get_all_team_ids.await_args
        assert recorded_call is not None
        assert recorded_call.kwargs["team_ids"] == scope


@pytest.mark.asyncio
async def test_user_selector_denies_before_directory_or_roster_access() -> None:
    """A narrowed administrator cannot render foreign team membership annotations."""
    from mcpgateway import admin

    handler = getattr(admin.admin_users_partial_html, "__wrapped__", admin.admin_users_partial_html)
    with patch.object(admin, "EmailAuthService") as auth, patch.object(admin, "TeamManagementService") as service:
        with pytest.raises(HTTPException) as error:
            await handler(request=make_test_scope_request(["a"]), render="selector", team_id="b", db=MagicMock(), user={"email": "admin@example.com", "is_admin": True})
    assert error.value.status_code == 403
    auth.assert_not_called()
    service.assert_not_called()


@pytest.mark.asyncio
async def test_requester_cancellation_forwards_authoritative_team(monkeypatch: pytest.MonkeyPatch) -> None:
    """Requester cancellation binds the URL team without requiring team membership."""
    from mcpgateway import admin

    monkeypatch.setattr(settings, "email_auth_enabled", True)
    service = MagicMock()
    service.cancel_join_request = AsyncMock(return_value=False)
    handler = getattr(admin.admin_cancel_join_request, "__wrapped__", admin.admin_cancel_join_request)
    with patch.object(admin, "TeamManagementService", return_value=service):
        response = await handler("a", "request-b", db=MagicMock(), user={"email": "requester@example.com", "sub": "ignored@example.com"})
    assert response.status_code == 404
    service.cancel_join_request.assert_awaited_once_with("request-b", "requester@example.com", "a")
    service.get_user_role_in_team.assert_not_called()
