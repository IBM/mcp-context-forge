# -*- coding: utf-8 -*-
"""Tests for IP access control router endpoints."""

# Standard
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import pytest

# Local
from tests.utils.rbac_mocks import patch_rbac_decorators, restore_rbac_decorators


_originals = patch_rbac_decorators()
# First-Party
from mcpgateway.routers import ip_control_router as router_mod  # noqa: E402
from mcpgateway.schemas import IPBlockCreate, IPRuleCreate, IPRuleUpdate, IPTestRequest  # noqa: E402

restore_rbac_decorators(_originals)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rule(rule_id="r1", ip_pattern="10.0.0.0/8", rule_type="deny", priority=100):
    now = datetime.now(tz=timezone.utc)
    return SimpleNamespace(
        id=rule_id,
        ip_pattern=ip_pattern,
        rule_type=rule_type,
        priority=priority,
        path_pattern=None,
        description="test rule",
        is_active=True,
        created_by="admin@example.com",
        updated_by="admin@example.com",
        created_at=now,
        updated_at=now,
        expires_at=None,
        hit_count=0,
        last_hit_at=None,
        metadata_json=None,
    )


def _make_block(block_id="b1", ip_address="1.2.3.4"):
    now = datetime.now(tz=timezone.utc)
    return SimpleNamespace(
        id=block_id,
        ip_address=ip_address,
        reason="suspicious activity",
        blocked_at=now,
        expires_at=now + timedelta(hours=1),
        blocked_by="admin@example.com",
        is_active=True,
        unblocked_at=None,
        unblocked_by=None,
    )


def _mock_user():
    return {"email": "admin@example.com", "is_admin": True}


# ---------------------------------------------------------------------------
# get_db
# ---------------------------------------------------------------------------


def test_get_db_commits_on_success(monkeypatch):
    db = MagicMock()
    monkeypatch.setattr(router_mod, "SessionLocal", lambda: db)

    gen = router_mod.get_db()
    yielded_db = next(gen)
    assert yielded_db is db

    with pytest.raises(StopIteration):
        gen.send(None)

    db.commit.assert_called_once()
    db.close.assert_called_once()


# ---------------------------------------------------------------------------
# Rule CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_rule_success(monkeypatch):
    rule = _make_rule("r1")
    mock_service = MagicMock()
    mock_service.create_rule.return_value = rule
    monkeypatch.setattr(router_mod, "get_ip_control_service", lambda: mock_service)

    request = IPRuleCreate(ip_pattern="10.0.0.0/8", rule_type="deny", priority=100)
    result = await router_mod.create_rule(request, user=_mock_user(), db=MagicMock())
    assert result.id == "r1"


@pytest.mark.asyncio
async def test_list_rules_success(monkeypatch):
    rules = [_make_rule("r1"), _make_rule("r2")]
    mock_service = MagicMock()
    mock_service.list_rules.return_value = (rules, 2)
    monkeypatch.setattr(router_mod, "get_ip_control_service", lambda: mock_service)

    result = await router_mod.list_rules(user=_mock_user(), db=MagicMock(), limit=50, offset=0, is_active=None, rule_type=None)
    assert result.total == 2
    assert len(result.rules) == 2


@pytest.mark.asyncio
async def test_get_rule_success(monkeypatch):
    rule = _make_rule("r1")
    mock_service = MagicMock()
    mock_service.get_rule.return_value = rule
    monkeypatch.setattr(router_mod, "get_ip_control_service", lambda: mock_service)

    result = await router_mod.get_rule("r1", user=_mock_user(), db=MagicMock())
    assert result.id == "r1"


@pytest.mark.asyncio
async def test_get_rule_not_found(monkeypatch):
    mock_service = MagicMock()
    mock_service.get_rule.return_value = None
    monkeypatch.setattr(router_mod, "get_ip_control_service", lambda: mock_service)

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await router_mod.get_rule("missing", user=_mock_user(), db=MagicMock())
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_update_rule_success(monkeypatch):
    rule = _make_rule("r1")
    rule.priority = 50
    mock_service = MagicMock()
    mock_service.update_rule.return_value = rule
    monkeypatch.setattr(router_mod, "get_ip_control_service", lambda: mock_service)

    update = IPRuleUpdate(priority=50)
    result = await router_mod.update_rule("r1", update, user=_mock_user(), db=MagicMock())
    assert result.priority == 50


@pytest.mark.asyncio
async def test_update_rule_not_found(monkeypatch):
    mock_service = MagicMock()
    mock_service.update_rule.return_value = None
    monkeypatch.setattr(router_mod, "get_ip_control_service", lambda: mock_service)

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await router_mod.update_rule("missing", IPRuleUpdate(priority=50), user=_mock_user(), db=MagicMock())
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_rule_success(monkeypatch):
    mock_service = MagicMock()
    mock_service.delete_rule.return_value = True
    monkeypatch.setattr(router_mod, "get_ip_control_service", lambda: mock_service)

    # Should not raise
    await router_mod.delete_rule("r1", user=_mock_user(), db=MagicMock())


@pytest.mark.asyncio
async def test_delete_rule_not_found(monkeypatch):
    mock_service = MagicMock()
    mock_service.delete_rule.return_value = False
    monkeypatch.setattr(router_mod, "get_ip_control_service", lambda: mock_service)

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await router_mod.delete_rule("missing", user=_mock_user(), db=MagicMock())
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Block CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_block_success(monkeypatch):
    block = _make_block("b1")
    mock_service = MagicMock()
    mock_service.create_block.return_value = block
    monkeypatch.setattr(router_mod, "get_ip_control_service", lambda: mock_service)

    request = IPBlockCreate(ip_address="1.2.3.4", reason="test", duration_minutes=60)
    result = await router_mod.create_block(request, user=_mock_user(), db=MagicMock())
    assert result.id == "b1"


@pytest.mark.asyncio
async def test_remove_block_not_found(monkeypatch):
    mock_service = MagicMock()
    mock_service.remove_block.return_value = False
    monkeypatch.setattr(router_mod, "get_ip_control_service", lambda: mock_service)

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await router_mod.remove_block("missing", user=_mock_user(), db=MagicMock())
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Diagnostic endpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_test_ip_endpoint(monkeypatch):
    mock_service = MagicMock()
    mock_service.test_ip.return_value = {
        "ip_address": "10.0.0.1",
        "path": "/api/tools",
        "allowed": False,
        "matched_rule_id": "r1",
        "matched_rule_type": "deny",
        "blocked_by_temp_block": False,
        "mode": "blocklist",
    }
    monkeypatch.setattr(router_mod, "get_ip_control_service", lambda: mock_service)

    request = IPTestRequest(ip_address="10.0.0.1", path="/api/tools")
    result = await router_mod.test_ip(request, user=_mock_user(), db=MagicMock())
    assert result.allowed is False
    assert result.matched_rule_id == "r1"


@pytest.mark.asyncio
async def test_get_status_endpoint(monkeypatch):
    mock_service = MagicMock()
    mock_service.get_status.return_value = {
        "enabled": True,
        "mode": "blocklist",
        "log_only": False,
        "total_rules": 5,
        "active_rules": 3,
        "total_blocks": 2,
        "active_blocks": 1,
        "cache_size": 100,
        "cache_ttl": 300,
        "skip_paths": ["/health"],
    }
    monkeypatch.setattr(router_mod, "get_ip_control_service", lambda: mock_service)

    result = await router_mod.get_status(user=_mock_user(), db=MagicMock())
    assert result.enabled is True
    assert result.active_rules == 3


@pytest.mark.asyncio
async def test_clear_cache_endpoint(monkeypatch):
    mock_service = MagicMock()
    monkeypatch.setattr(router_mod, "get_ip_control_service", lambda: mock_service)

    await router_mod.clear_cache(user=_mock_user())
    mock_service.invalidate_cache.assert_called_once()
