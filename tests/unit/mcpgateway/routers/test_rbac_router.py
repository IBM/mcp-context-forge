# -*- coding: utf-8 -*-
"""Tests for RBAC router endpoints."""

# Standard
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import pytest

# Local
from tests.utils.rbac_mocks import patch_rbac_decorators, restore_rbac_decorators

_originals = patch_rbac_decorators()
# First-Party
from mcpgateway.routers import rbac as rbac_router  # noqa: E402
from mcpgateway.schemas import PermissionCheckRequest, RoleCreateRequest, RoleUpdateRequest, UserRoleAssignRequest  # noqa: E402

restore_rbac_decorators(_originals)


def _make_role(role_id: str = "r1") -> SimpleNamespace:
    return SimpleNamespace(
        id=role_id,
        name="role",
        description="desc",
        scope="global",
        permissions=["p1"],
        effective_permissions=["p1"],
        inherits_from=None,
        created_by="admin@example.com",
        is_system_role=False,
        is_active=True,
        created_at=datetime.now(tz=timezone.utc),
        updated_at=datetime.now(tz=timezone.utc),
    )


def _make_user_role(role_id: str = "r1") -> SimpleNamespace:
    return SimpleNamespace(
        id="ur1",
        user_email="user@example.com",
        role_id=role_id,
        role_name="role",
        scope="global",
        scope_id=None,
        granted_by="admin@example.com",
        granted_at=datetime.now(tz=timezone.utc),
        expires_at=None,
        is_active=True,
    )


def test_get_db_commits_on_success(monkeypatch):
    db = MagicMock()
    monkeypatch.setattr(rbac_router, "SessionLocal", lambda: db)

    gen = rbac_router.get_db()
    yielded_db = next(gen)
    assert yielded_db is db

    # Resume generator normally to trigger the post-yield commit.
    with pytest.raises(StopIteration):
        gen.send(None)

    db.commit.assert_called_once()
    db.close.assert_called_once()


def test_get_db_rollback_invalidate_best_effort(monkeypatch):
    db = MagicMock()
    db.rollback.side_effect = RuntimeError("rollback failed")
    db.invalidate.side_effect = RuntimeError("invalidate failed")
    monkeypatch.setattr(rbac_router, "SessionLocal", lambda: db)

    gen = rbac_router.get_db()
    yielded_db = next(gen)
    assert yielded_db is db

    with pytest.raises(RuntimeError, match="boom"):
        gen.throw(RuntimeError("boom"))

    db.rollback.assert_called_once()
    db.invalidate.assert_called_once()
    db.close.assert_called_once()


@pytest.mark.asyncio
async def test_create_role_success(monkeypatch):
    role = _make_role("r1")
    service = MagicMock()
    service.create_role = AsyncMock(return_value=role)
    monkeypatch.setattr(rbac_router, "RoleService", lambda db: service)

    request = RoleCreateRequest(name="role", description="desc", scope="global", permissions=["p1"])
    result = await rbac_router.create_role(request, user={"email": "admin@example.com", "permissions": ["*"]}, db=MagicMock())
    assert result.id == "r1"


@pytest.mark.asyncio
async def test_create_role_validation_error(monkeypatch):
    service = MagicMock()
    service.create_role = AsyncMock(side_effect=ValueError("bad"))
    monkeypatch.setattr(rbac_router, "RoleService", lambda db: service)

    request = RoleCreateRequest(name="role", description="desc", scope="global", permissions=["p1"])
    with pytest.raises(rbac_router.HTTPException) as excinfo:
        await rbac_router.create_role(request, user={"email": "admin@example.com", "permissions": ["*"]}, db=MagicMock())
    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_create_role_generic_error(monkeypatch):
    service = MagicMock()
    service.create_role = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(rbac_router, "RoleService", lambda db: service)

    request = RoleCreateRequest(name="role", description="desc", scope="global", permissions=["p1"])
    with pytest.raises(rbac_router.HTTPException) as excinfo:
        await rbac_router.create_role(request, user={"email": "admin@example.com", "permissions": ["*"]}, db=MagicMock())
    assert excinfo.value.status_code == 500


@pytest.mark.asyncio
async def test_list_roles(monkeypatch):
    role = _make_role("r1")
    service = MagicMock()
    service.list_roles = AsyncMock(return_value=[role])
    monkeypatch.setattr(rbac_router, "RoleService", lambda db: service)

    result = await rbac_router.list_roles(scope=None, active_only=True, user={"email": "admin@example.com", "permissions": ["*"]}, db=MagicMock())
    assert result[0].id == "r1"


@pytest.mark.asyncio
async def test_get_role_not_found(monkeypatch):
    service = MagicMock()
    service.get_role_by_id = AsyncMock(return_value=None)
    monkeypatch.setattr(rbac_router, "RoleService", lambda db: service)

    with pytest.raises(rbac_router.HTTPException) as excinfo:
        await rbac_router.get_role("missing", user={"email": "admin@example.com", "permissions": ["*"]}, db=MagicMock())
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_get_role_success(monkeypatch):
    role = _make_role("r1")
    service = MagicMock()
    service.get_role_by_id = AsyncMock(return_value=role)
    monkeypatch.setattr(rbac_router, "RoleService", lambda db: service)

    db = MagicMock()
    result = await rbac_router.get_role("r1", user={"email": "admin@example.com", "permissions": ["*"]}, db=db)
    assert result.id == "r1"
    db.commit.assert_called_once()
    db.close.assert_called_once()


@pytest.mark.asyncio
async def test_get_role_generic_error(monkeypatch):
    service = MagicMock()
    service.get_role_by_id = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(rbac_router, "RoleService", lambda db: service)

    with pytest.raises(rbac_router.HTTPException) as excinfo:
        await rbac_router.get_role("r1", user={"email": "admin@example.com", "permissions": ["*"]}, db=MagicMock())
    assert excinfo.value.status_code == 500


@pytest.mark.asyncio
async def test_update_role_success(monkeypatch):
    role = _make_role("r1")
    role.description = "updated"
    service = MagicMock()
    service.update_role = AsyncMock(return_value=role)
    monkeypatch.setattr(rbac_router, "RoleService", lambda db: service)

    request = RoleUpdateRequest(description="updated", permissions=["p1"])
    result = await rbac_router.update_role("r1", request, user={"email": "admin@example.com", "permissions": ["*"]}, db=MagicMock())
    assert result.description == "updated"


@pytest.mark.asyncio
async def test_update_role_generic_error(monkeypatch):
    service = MagicMock()
    service.update_role = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(rbac_router, "RoleService", lambda db: service)

    request = RoleUpdateRequest(description="updated")
    with pytest.raises(rbac_router.HTTPException) as excinfo:
        await rbac_router.update_role("r1", request, user={"email": "admin@example.com", "permissions": ["*"]}, db=MagicMock())
    assert excinfo.value.status_code == 500


@pytest.mark.asyncio
async def test_delete_role_success(monkeypatch):
    service = MagicMock()
    service.delete_role = AsyncMock(return_value=True)
    monkeypatch.setattr(rbac_router, "RoleService", lambda db: service)

    result = await rbac_router.delete_role("r1", user={"email": "admin@example.com", "permissions": ["*"]}, db=MagicMock())
    assert result["message"] == "Role deleted successfully"


@pytest.mark.asyncio
async def test_delete_role_value_error(monkeypatch):
    service = MagicMock()
    service.delete_role = AsyncMock(side_effect=ValueError("Cannot delete system role"))
    monkeypatch.setattr(rbac_router, "RoleService", lambda db: service)

    with pytest.raises(rbac_router.HTTPException) as excinfo:
        await rbac_router.delete_role("r1", user={"email": "admin@example.com", "permissions": ["*"]}, db=MagicMock())
    assert excinfo.value.status_code == 400
    assert "Cannot delete system role" in excinfo.value.detail


@pytest.mark.asyncio
async def test_delete_role_generic_error(monkeypatch):
    service = MagicMock()
    service.delete_role = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(rbac_router, "RoleService", lambda db: service)

    with pytest.raises(rbac_router.HTTPException) as excinfo:
        await rbac_router.delete_role("r1", user={"email": "admin@example.com", "permissions": ["*"]}, db=MagicMock())
    assert excinfo.value.status_code == 500


@pytest.mark.asyncio
async def test_assign_and_revoke_role(monkeypatch):
    service = MagicMock()
    user_role = _make_user_role("r1")
    service.assign_role_to_user = AsyncMock(return_value=user_role)
    service.revoke_role_from_user = AsyncMock(return_value=True)
    monkeypatch.setattr(rbac_router, "RoleService", lambda db: service)

    assign_request = UserRoleAssignRequest(role_id="r1", scope="global", scope_id=None)
    result = await rbac_router.assign_role_to_user("user@example.com", assign_request, user={"email": "admin@example.com", "permissions": ["*"]}, db=MagicMock())
    assert result.user_email == "user@example.com"

    result = await rbac_router.revoke_user_role("user@example.com", "r1", scope="global", scope_id=None, user={"email": "admin@example.com", "permissions": ["*"]}, db=MagicMock())
    assert result["message"] == "Role revoked successfully"


@pytest.mark.asyncio
async def test_assign_role_generic_error(monkeypatch):
    service = MagicMock()
    service.assign_role_to_user = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(rbac_router, "RoleService", lambda db: service)

    assign_request = UserRoleAssignRequest(role_id="r1", scope="global", scope_id=None)
    with pytest.raises(rbac_router.HTTPException) as excinfo:
        await rbac_router.assign_role_to_user("user@example.com", assign_request, user={"email": "admin@example.com", "permissions": ["*"]}, db=MagicMock())
    assert excinfo.value.status_code == 500


@pytest.mark.asyncio
async def test_get_user_roles_success(monkeypatch):
    perm_service = MagicMock()
    perm_service.get_user_roles = AsyncMock(return_value=[_make_user_role("r1")])
    monkeypatch.setattr(rbac_router, "PermissionService", lambda db: perm_service)

    db = MagicMock()
    result = await rbac_router.get_user_roles("user@example.com", scope=None, active_only=True, user={"email": "admin@example.com", "permissions": ["*"]}, db=db)
    assert result[0].role_id == "r1"
    db.commit.assert_called_once()
    db.close.assert_called_once()


@pytest.mark.asyncio
async def test_revoke_role_generic_error(monkeypatch):
    service = MagicMock()
    service.revoke_role_from_user = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(rbac_router, "RoleService", lambda db: service)

    with pytest.raises(rbac_router.HTTPException) as excinfo:
        await rbac_router.revoke_user_role("user@example.com", "r1", scope=None, scope_id=None, user={"email": "admin@example.com", "permissions": ["*"]}, db=MagicMock())
    assert excinfo.value.status_code == 500


@pytest.mark.asyncio
async def test_check_permission_and_user_permissions(monkeypatch):
    perm_service = MagicMock()
    perm_service.check_permission = AsyncMock(return_value=True)
    perm_service.get_user_permissions = AsyncMock(return_value={"p1", "p2"})
    monkeypatch.setattr(rbac_router, "PermissionService", lambda db: perm_service)

    check_request = PermissionCheckRequest(user_email="user@example.com", permission="p1")
    result = await rbac_router.check_permission(check_request, user={"email": "admin@example.com", "permissions": ["*"]}, db=MagicMock())
    assert result.granted is True
    assert result.checked_at <= datetime.now(tz=timezone.utc)

    perms = await rbac_router.get_user_permissions("user@example.com", team_id=None, user={"email": "admin@example.com", "permissions": ["*"]}, db=MagicMock())
    assert sorted(perms) == ["p1", "p2"]


@pytest.mark.asyncio
async def test_available_and_my_permissions(monkeypatch):
    monkeypatch.setattr(rbac_router.Permissions, "get_all_permissions", lambda: ["p1"])
    monkeypatch.setattr(rbac_router.Permissions, "get_permissions_by_resource", lambda: {"tools": ["p1"]})

    result = await rbac_router.get_available_permissions(user={"email": "admin@example.com", "permissions": ["*"]})
    assert result.total_count == 1

    perm_service = MagicMock()
    user_role = SimpleNamespace(
        id="ur1",
        user_email="user@example.com",
        role_id="r1",
        role_name="role",
        scope="global",
        scope_id=None,
        granted_by="admin@example.com",
        granted_at=datetime.now(tz=timezone.utc),
        expires_at=None,
        is_active=True,
    )
    perm_service.get_user_roles = AsyncMock(return_value=[user_role])
    perm_service.get_user_permissions = AsyncMock(return_value={"p1"})
    monkeypatch.setattr(rbac_router, "PermissionService", lambda db: perm_service)

    roles = await rbac_router.get_my_roles(
        user={"email": "user@example.com", "permissions": ["admin.*", "a2a.*", "tools.*", "servers.*", "resources.*", "prompts.*", "gateways.*", "teams.*"]}, db=MagicMock()
    )
    assert roles[0].role_name == "role"

    perms = await rbac_router.get_my_permissions(
        team_id=None, user={"email": "user@example.com", "permissions": ["admin.*", "a2a.*", "tools.*", "servers.*", "resources.*", "prompts.*", "gateways.*", "teams.*"]}, db=MagicMock()
    )
    assert perms == ["p1"]


@pytest.mark.asyncio
async def test_list_roles_error(monkeypatch):
    service = MagicMock()
    service.list_roles = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(rbac_router, "RoleService", lambda db: service)

    with pytest.raises(rbac_router.HTTPException) as excinfo:
        await rbac_router.list_roles(scope=None, active_only=True, user={"email": "admin@example.com", "permissions": ["*"]}, db=MagicMock())
    assert excinfo.value.status_code == 500


@pytest.mark.asyncio
async def test_update_role_not_found(monkeypatch):
    service = MagicMock()
    service.update_role = AsyncMock(return_value=None)
    monkeypatch.setattr(rbac_router, "RoleService", lambda db: service)

    request = RoleUpdateRequest(description="updated")
    with pytest.raises(rbac_router.HTTPException) as excinfo:
        await rbac_router.update_role("missing", request, user={"email": "admin@example.com", "permissions": ["*"]}, db=MagicMock())
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_update_role_validation_error(monkeypatch):
    service = MagicMock()
    service.update_role = AsyncMock(side_effect=ValueError("bad"))
    monkeypatch.setattr(rbac_router, "RoleService", lambda db: service)

    request = RoleUpdateRequest(description="updated")
    with pytest.raises(rbac_router.HTTPException) as excinfo:
        await rbac_router.update_role("r1", request, user={"email": "admin@example.com", "permissions": ["*"]}, db=MagicMock())
    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_delete_role_not_found(monkeypatch):
    service = MagicMock()
    service.delete_role = AsyncMock(return_value=False)
    monkeypatch.setattr(rbac_router, "RoleService", lambda db: service)

    with pytest.raises(rbac_router.HTTPException) as excinfo:
        await rbac_router.delete_role("r1", user={"email": "admin@example.com", "permissions": ["*"]}, db=MagicMock())
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_assign_role_validation_error(monkeypatch):
    service = MagicMock()
    service.assign_role_to_user = AsyncMock(side_effect=ValueError("bad"))
    monkeypatch.setattr(rbac_router, "RoleService", lambda db: service)

    assign_request = UserRoleAssignRequest(role_id="r1", scope="global", scope_id=None)
    with pytest.raises(rbac_router.HTTPException) as excinfo:
        await rbac_router.assign_role_to_user("user@example.com", assign_request, user={"email": "admin@example.com", "permissions": ["*"]}, db=MagicMock())
    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_revoke_role_not_found(monkeypatch):
    service = MagicMock()
    service.revoke_role_from_user = AsyncMock(return_value=False)
    monkeypatch.setattr(rbac_router, "RoleService", lambda db: service)

    with pytest.raises(rbac_router.HTTPException) as excinfo:
        await rbac_router.revoke_user_role("user@example.com", "r1", scope=None, scope_id=None, user={"email": "admin@example.com", "permissions": ["*"]}, db=MagicMock())
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_permission_service_errors(monkeypatch):
    perm_service = MagicMock()
    perm_service.get_user_roles = AsyncMock(side_effect=RuntimeError("fail"))
    perm_service.check_permission = AsyncMock(side_effect=RuntimeError("fail"))
    perm_service.get_user_permissions = AsyncMock(side_effect=RuntimeError("fail"))
    monkeypatch.setattr(rbac_router, "PermissionService", lambda db: perm_service)

    with pytest.raises(rbac_router.HTTPException) as excinfo:
        await rbac_router.get_user_roles("user@example.com", scope=None, active_only=True, user={"email": "admin@example.com", "permissions": ["*"]}, db=MagicMock())
    assert excinfo.value.status_code == 500

    check_request = PermissionCheckRequest(user_email="user@example.com", permission="p1")
    with pytest.raises(rbac_router.HTTPException) as excinfo:
        await rbac_router.check_permission(check_request, user={"email": "admin@example.com", "permissions": ["*"]}, db=MagicMock())
    assert excinfo.value.status_code == 500

    with pytest.raises(rbac_router.HTTPException) as excinfo:
        await rbac_router.get_user_permissions("user@example.com", team_id=None, user={"email": "admin@example.com", "permissions": ["*"]}, db=MagicMock())
    assert excinfo.value.status_code == 500


@pytest.mark.asyncio
async def test_available_permissions_error(monkeypatch):
    monkeypatch.setattr(rbac_router.Permissions, "get_all_permissions", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(rbac_router.Permissions, "get_permissions_by_resource", lambda: {"tools": ["p1"]})

    with pytest.raises(rbac_router.HTTPException) as excinfo:
        await rbac_router.get_available_permissions(user={"email": "admin@example.com", "permissions": ["*"]})
    assert excinfo.value.status_code == 500


@pytest.mark.asyncio
async def test_my_permissions_errors(monkeypatch):
    perm_service = MagicMock()
    perm_service.get_user_roles = AsyncMock(side_effect=RuntimeError("fail"))
    perm_service.get_user_permissions = AsyncMock(side_effect=RuntimeError("fail"))
    monkeypatch.setattr(rbac_router, "PermissionService", lambda db: perm_service)

    with pytest.raises(rbac_router.HTTPException) as excinfo:
        await rbac_router.get_my_roles(
            user={"email": "user@example.com", "permissions": ["admin.*", "a2a.*", "tools.*", "servers.*", "resources.*", "prompts.*", "gateways.*", "teams.*"]}, db=MagicMock()
        )
    assert excinfo.value.status_code == 500

    with pytest.raises(rbac_router.HTTPException) as excinfo:
        await rbac_router.get_my_permissions(
            team_id=None, user={"email": "user@example.com", "permissions": ["admin.*", "a2a.*", "tools.*", "servers.*", "resources.*", "prompts.*", "gateways.*", "teams.*"]}, db=MagicMock()
        )
    assert excinfo.value.status_code == 500
