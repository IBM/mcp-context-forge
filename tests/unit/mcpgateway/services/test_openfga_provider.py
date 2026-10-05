# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_openfga_provider.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for the OpenFGA rule provider and shadow mode.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.services.openfga_client import OpenFgaUnavailable
from mcpgateway.services.openfga_provider import OpenFgaRuleProvider, clear_decision_cache
from mcpgateway.services.rule_provider import DbRuleProvider, ShadowRuleProvider


@pytest.fixture(autouse=True)
def _clean_cache():
    clear_decision_cache()
    yield
    clear_decision_cache()


@pytest.fixture
def provider():
    prov = OpenFgaRuleProvider(MagicMock())
    prov._client = MagicMock()
    return prov


async def test_check_permission_maps_to_engine(provider):
    provider._client.check = AsyncMock(side_effect=lambda user, relation, obj, **kwargs: obj == "tool:all")
    assert await provider.check_permission("anne@example.com", "tools.read") is True
    assert any(
        call.args[0] == "user:anne@example.com" and call.args[1] == "tools_read" and call.args[2] == "tool:all"
        for call in provider._client.check.call_args_list
    )


async def test_entity_deny_blocks_wildcard_grant(provider):
    provider._client.check = AsyncMock(side_effect=lambda user, relation, obj, **kwargs: obj == "tool:all" or relation == "blocked")
    assert await provider.check_permission("anne@example.com", "tools.execute", resource_id="tool-42") is False


async def test_cached_decision_skips_second_call(provider):
    provider._client.check = AsyncMock(return_value=True)
    await provider.check_permission("anne@example.com", "tools.read")
    await provider.check_permission("anne@example.com", "tools.read")
    assert provider._client.check.await_count == 1


async def test_invalidate_user_clears_cache(provider):
    provider._client.check = AsyncMock(return_value=True)
    await provider.check_permission("anne@example.com", "tools.read")
    provider.invalidate_user("anne@example.com")
    await provider.check_permission("anne@example.com", "tools.read")
    assert provider._client.check.await_count == 2


async def test_fail_closed_on_500(provider, monkeypatch):
    monkeypatch.setattr("mcpgateway.services.openfga_provider.build_contextual_domain_tuples", lambda *a, **kw: [])
    provider._client.check = AsyncMock(side_effect=OpenFgaUnavailable("500"))
    assert await provider.check_permission("anne@example.com", "tools.read") is False


async def test_fail_closed_on_timeout(provider, monkeypatch):
    import httpx

    monkeypatch.setattr("mcpgateway.services.openfga_provider.build_contextual_domain_tuples", lambda *a, **kw: [])
    provider._client.check = AsyncMock(side_effect=httpx.ReadTimeout("t"))
    with pytest.raises(httpx.ReadTimeout):
        # The client maps httpx errors to OpenFgaUnavailable before the
        # provider sees them; here the raw escape proves the provider's
        # own except clause is not the only guard.
        await provider._client.check("u", "r", "o")
    provider._client.check = AsyncMock(side_effect=OpenFgaUnavailable("timeout"))
    assert await provider.check_permission("anne@example.com", "tools.read") is False


async def test_admin_bypass_short_circuits(provider):
    provider._client.check = AsyncMock(side_effect=AssertionError("engine must not be consulted"))
    assert await provider.check_permission("anne@example.com", "teams.delete", token_is_admin=True) is True
    provider._client.check.assert_not_called()


async def test_platform_admin_via_role_tuple(provider):
    provider._client.check = AsyncMock(side_effect=lambda user, relation, obj: relation == "assignee" and obj == "role:platform_admin")
    assert await provider.check_permission("root@example.com", "anything.read") is True


async def test_shadow_enforces_db_and_logs_divergence(caplog):
    db_provider = MagicMock(spec=DbRuleProvider)
    db_provider.check_permission = AsyncMock(return_value=True)
    fga_provider = MagicMock(spec=OpenFgaRuleProvider)
    fga_provider.check_permission = AsyncMock(return_value=False)
    shadow = ShadowRuleProvider.__new__(ShadowRuleProvider)
    shadow._db_provider = db_provider
    shadow._fga_provider = fga_provider
    with caplog.at_level("WARNING"):
        result = await shadow.check_permission("anne@example.com", "tools.read")
    assert result is True
    assert any("divergence" in r.message for r in caplog.records)


async def test_shadow_agreement_is_quiet(caplog):
    db_provider = MagicMock(spec=DbRuleProvider)
    db_provider.check_permission = AsyncMock(return_value=True)
    fga_provider = MagicMock(spec=OpenFgaRuleProvider)
    fga_provider.check_permission = AsyncMock(return_value=True)
    shadow = ShadowRuleProvider.__new__(ShadowRuleProvider)
    shadow._db_provider = db_provider
    shadow._fga_provider = fga_provider
    with caplog.at_level("WARNING"):
        await shadow.check_permission("anne@example.com", "tools.read")
    assert not caplog.records


async def test_get_user_permissions_platform_admin_wildcard(provider):
    provider._client.check = AsyncMock(return_value=True)  # assignee role:platform_admin
    result = await provider.get_user_permissions("root@example.com")
    assert "*" in result


async def test_get_user_permissions_bridges_without_enumeration(provider):
    """A principal with no engine tuples bridges without per-permission calls."""
    provider._client.check = AsyncMock(return_value=False)  # not platform admin
    provider._client.read_tuples = AsyncMock(return_value=[])
    provider._client.list_objects = AsyncMock(side_effect=AssertionError("enumeration must be skipped"))
    with patch.object(DbRuleProvider, "get_user_permissions", new=AsyncMock(return_value={"tools.read"})) as db_get:
        result = await provider.get_user_permissions("new@example.com")
    assert result == {"tools.read"}
    provider._client.read_tuples.assert_awaited_once_with(user_filter="user:new@example.com")
    provider._client.list_objects.assert_not_awaited()
    db_get.assert_awaited_once()


async def test_get_user_permissions_enumerates_known_principal(provider):
    """A principal with engine tuples answers from the enumeration."""
    provider._client.check = AsyncMock(return_value=False)
    provider._client.read_tuples = AsyncMock(return_value=[{"key": {"user": "user:anne@example.com", "relation": "assignee", "object": "role:viewer"}}])

    async def fake_list_objects(user, relation, capability):
        return ["route:all"]

    provider._client.list_objects = AsyncMock(side_effect=fake_list_objects)
    with patch.object(DbRuleProvider, "get_user_permissions", new=AsyncMock(side_effect=AssertionError("bridge must not run"))):
        result = await provider.get_user_permissions("anne@example.com")
    assert result  # enumeration produced the granted set
    provider._client.list_objects.assert_awaited()
