# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_dataplane_publisher.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for DataplanePublisherService.
"""

import asyncio
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

USER1_ID = "11111111-1111-1111-1111-111111111111"
USER2_ID = "22222222-2222-2222-2222-222222222222"
USER3_ID = "33333333-3333-3333-3333-333333333333"


@pytest.fixture(autouse=True)
def plugins_disabled_by_default(monkeypatch):
    """Isolate publisher tests from process-global toggles in other modules."""
    monkeypatch.setattr("mcpgateway.services.dataplane_publisher.are_plugins_enabled_shared", AsyncMock(return_value=False))


@pytest.fixture
async def plugin_publication(tmp_path, monkeypatch):
    """Use the real config loader, binding resolver and Redis mode handling."""
    import fakeredis.aioredis
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from mcpgateway.db import Base
    from mcpgateway.plugins.gateway_plugin_manager import TenantPluginManagerFactory
    from mcpgateway.plugins.policy import HOOK_PAYLOAD_POLICIES
    from mcpgateway.services import dataplane_publisher

    config_path = tmp_path / "plugins.yaml"
    config_path.write_text(
        """plugins:
  - name: Guard
    kind: plugins.regex_filter.search_replace.SearchReplacePlugin
    hooks: [tool_pre_invoke, tool_post_invoke, prompt_pre_fetch, prompt_post_fetch,
            resource_pre_fetch, resource_post_fetch, http_pre_request, http_post_request]
    mode: sequential
    on_error: fail
    priority: 31
    capabilities: [read_headers]
    conditions:
      - tools: [gateway-echo]
        tenant_ids: [team-a]
        server_ids: [gateway]
        user_patterns: ['.*@example.com']
    config:
      words: []
      retained: base
      nested: {base: true}
  - name: Disabled
    kind: unavailable.Plugin
    hooks: [tool_post_invoke]
    mode: disabled
""",
        encoding="utf-8",
    )
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    redis = fakeredis.aioredis.FakeRedis()
    monkeypatch.setattr("mcpgateway.plugins.gateway_plugin_manager._redis", AsyncMock(return_value=redis))
    monkeypatch.setattr("mcpgateway.plugins.gateway_plugin_manager.active_local_mode_overrides", lambda _now: {})
    factory = TenantPluginManagerFactory(str(config_path), timeout=17, db_factory=session_factory, hook_policies=HOOK_PAYLOAD_POLICIES)
    monkeypatch.setattr(dataplane_publisher, "are_plugins_enabled_shared", AsyncMock(return_value=True))
    monkeypatch.setattr(dataplane_publisher, "get_plugin_manager_factory", lambda: factory)
    session = session_factory()
    try:
        yield dataplane_publisher.DataplanePublisherService(), factory, session, redis
    finally:
        await factory.shutdown()
        await redis.aclose()
        session.close()
        engine.dispose()


def _policy_payload(*context_ids):
    """Make routing data whose targets point to the requested policy contexts."""
    return {
        USER1_ID: {
            "virtual_hosts": {"server": {"backends": {"gateway": {"tool_policy_contexts": {str(i): {"context_id": context_id} for i, context_id in enumerate(context_ids)}}}}},
        }
    }


@pytest.mark.asyncio
async def test_plugin_publication_preserves_builtin_config_and_settings(plugin_publication):
    """The wire document preserves all configured hooks and execution settings."""
    import msgpack

    service, factory, _db, _redis = plugin_publication
    document = await service.fetch_plugin_config(_policy_payload("team-a::gateway-echo", "server"))

    assert msgpack.unpackb(msgpack.packb(document), raw=False) == document
    assert document["enabled"] is True
    assert document["global"] == (await factory.get_manager()).config.model_dump(mode="json")
    assert document["contexts"]["server"] == document["global"]
    plugin = document["global"]["plugins"][0]
    assert plugin["name"] == "Guard"
    assert plugin["kind"] == "plugins.regex_filter.search_replace.SearchReplacePlugin"
    assert len(plugin["hooks"]) == 8
    assert plugin["capabilities"] == ["read_headers"]
    assert plugin["conditions"][0]["tools"] == ["gateway-echo"]
    assert plugin["on_error"] == "fail"
    assert plugin["priority"] == 31
    assert document["global"]["plugins"][1]["mode"] == "disabled"
    assert document["settings"]["plugin_timeout"] == 17
    assert document["settings"]["hook_policies"]["resource_pre_fetch"] == {"writable_fields": ["metadata", "uri"]}
    assert document["settings"]["plugins_can_override_rbac"] is False


@pytest.mark.asyncio
async def test_plugin_publication_tracks_override_lifecycle_and_specificity(plugin_publication):
    """Exact overrides replace wildcard rows; removing them restores the fallback."""
    from mcpgateway.db import ToolPluginBinding

    service, factory, db, redis = plugin_publication
    payload = _policy_payload("team-a::gateway-echo", "team-b::gateway-echo")
    wildcard = ToolPluginBinding(team_id="team-a", tool_name="*", plugin_id="Guard", created_by="admin@example.com", updated_by="admin@example.com", mode="permissive", config={"nested": {"wildcard": True}}, priority=12)
    exact = ToolPluginBinding(team_id="team-a", tool_name="gateway-echo", plugin_id="Guard", created_by="admin@example.com", updated_by="admin@example.com", mode="enforce_ignore_error", config={"nested": {"exact": True}}, priority=0)
    db.add_all([exact, wildcard])
    db.commit()
    await factory.invalidate_all()

    document = await service.fetch_plugin_config(payload)
    scoped = document["contexts"]["team-a::gateway-echo"]
    assert scoped == (await factory.get_manager("team-a::gateway-echo")).config.model_dump(mode="json")
    assert scoped["plugins"][0]["config"] == {"words": [], "retained": "base", "nested": {"exact": True}}
    assert scoped["plugins"][0]["mode"] == "sequential"
    assert scoped["plugins"][0]["on_error"] == "ignore"
    assert scoped["plugins"][0]["priority"] == 0
    assert document["contexts"]["team-b::gateway-echo"] == document["global"]

    exact.mode = "disabled"
    exact.on_error = "disable"
    exact.config = {"nested": {"updated": True}}
    db.commit()
    await factory.invalidate_all()
    document = await service.fetch_plugin_config(payload)
    assert document["contexts"]["team-a::gateway-echo"]["plugins"][0]["mode"] == "disabled"
    assert document["contexts"]["team-a::gateway-echo"]["plugins"][0]["on_error"] == "disable"
    assert document["contexts"]["team-a::gateway-echo"]["plugins"][0]["config"] == {"words": [], "retained": "base", "nested": {"updated": True}}

    # Runtime mode overrides win over DB overrides, including legacy error policy.
    await redis.set("plugin:Guard:mode", "enforce_ignore_error")
    await factory.invalidate_all()
    document = await service.fetch_plugin_config(payload)
    assert document["contexts"]["team-a::gateway-echo"]["plugins"][0]["on_error"] == "ignore"
    await redis.delete("plugin:Guard:mode")
    db.delete(exact)
    db.commit()
    await factory.invalidate_all()
    document = await service.fetch_plugin_config(payload)
    assert document["contexts"]["team-a::gateway-echo"]["plugins"][0]["mode"] == "transform"
    assert document["contexts"]["team-a::gateway-echo"]["plugins"][0]["config"]["nested"] == {"wildcard": True}
    db.delete(wildcard)
    db.commit()
    await factory.invalidate_all()
    document = await service.fetch_plugin_config(payload)
    assert document["contexts"]["team-a::gateway-echo"] == document["global"]


@pytest.mark.asyncio
async def test_plugin_publication_uses_loaded_yaml_and_only_published_contexts(plugin_publication):
    """Publication neither rereads YAML nor leaks cached, unpublished scopes."""
    service, factory, _db, _redis = plugin_publication
    with patch.object(factory, "get_manager", wraps=factory.get_manager) as resolve, patch("cpex.framework.ConfigLoader.load_config", side_effect=AssertionError("YAML reread")):
        document = await service.fetch_plugin_config(_policy_payload("team-a::gateway-echo", "team-a::gateway-echo"))
    assert list(document["contexts"]) == ["team-a::gateway-echo"]
    assert resolve.await_count == 2  # global plus one unique context
    assert (await service.fetch_plugin_config({}))["contexts"] == {}


@pytest.mark.asyncio
async def test_invalid_binding_config_fails_like_builtin_resolution(plugin_publication):
    """Malformed DB config cannot silently replace a required scoped override."""
    from pydantic import ValidationError

    from mcpgateway.db import ToolPluginBinding

    service, factory, db, _redis = plugin_publication
    db.add(ToolPluginBinding(team_id="team-a", tool_name="*", plugin_id="Guard", config=["invalid"], created_by="admin@example.com", updated_by="admin@example.com"))
    db.commit()
    with pytest.raises(ValidationError, match="valid dictionary"):
        await factory.get_manager("team-a::gateway-echo")
    with pytest.raises(ValidationError, match="valid dictionary"):
        await service.fetch_plugin_config(_policy_payload("team-a::gateway-echo"))


def test_plugin_condition_serialization_is_stable_without_reordering_hooks():
    """Sort unordered selection sets while preserving ordered hooks and plugins."""
    from cpex.framework.models import Config, PluginConfig, PluginCondition

    from mcpgateway.services.dataplane_publisher import _serialize_plugin_config

    config = Config(plugins=[PluginConfig(name="Guard", kind="test.Plugin", hooks=["tool_pre_invoke", "resource_pre_fetch"], conditions=[PluginCondition(tools={"z", "a"}, tenant_ids=set())])])
    serialized = _serialize_plugin_config(config)
    assert serialized["plugins"][0]["conditions"][0]["tools"] == ["a", "z"]
    assert serialized["plugins"][0]["conditions"][0]["tenant_ids"] is None
    assert serialized["plugins"][0]["hooks"] == ["tool_pre_invoke", "resource_pre_fetch"]
    assert config.plugins[0].conditions[0].tools == {"z", "a"}


@pytest.mark.asyncio
async def test_plugin_publication_rejects_missing_tool_context(plugin_publication):
    """A routed tool without its policy scope cannot silently use global policy."""
    service, _factory, _db, _redis = plugin_publication
    with pytest.raises(ValueError, match="missing its plugin policy context"):
        await service.fetch_plugin_config(_policy_payload(""))


@pytest.mark.asyncio
async def test_plugin_publication_distinguishes_disabled_from_missing_factory(plugin_publication, monkeypatch):
    """An unavailable enabled factory cannot become an empty policy document."""
    from mcpgateway.services import dataplane_publisher

    service, _factory, _db, _redis = plugin_publication
    monkeypatch.setattr(dataplane_publisher, "get_plugin_manager_factory", lambda: None)
    with pytest.raises(RuntimeError, match="initialized plugin manager"):
        await service.fetch_plugin_config({})
    monkeypatch.setattr(dataplane_publisher, "are_plugins_enabled_shared", AsyncMock(return_value=False))
    assert await service.fetch_plugin_config({}) == {"enabled": False, "global": None, "contexts": {}}


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RuntimeError("DB unavailable"), TypeError("invalid binding config")])
async def test_policy_failure_does_not_publish_or_refresh_routing(plugin_publication, monkeypatch, failure):
    """A failed resolution leaves both existing keys untouched and releases the lock."""
    import msgpack

    from mcpgateway.services import dataplane_publisher

    service, factory, _db, redis = plugin_publication
    routing_key = msgpack.packb((dataplane_publisher.USER_CONFIG_KEY, USER1_ID))
    await redis.set(routing_key, b"old-routing", ex=100)
    await redis.set(dataplane_publisher.RUNTIME_PLUGIN_CONFIG_KEY, b"old-policy", ex=100)
    monkeypatch.setattr(dataplane_publisher, "get_redis_client", AsyncMock(return_value=redis))
    monkeypatch.setattr(service, "fetch_payload", AsyncMock(return_value=_policy_payload("team-a::gateway-echo")))

    async def fail_resolution(_context_id):
        service._shutdown_event.set()
        raise failure

    monkeypatch.setattr(factory, "get_config_from_db", fail_resolution)
    await service.publish_to_redis()
    assert await redis.get(routing_key) == b"old-routing"
    assert await redis.get(dataplane_publisher.RUNTIME_PLUGIN_CONFIG_KEY) == b"old-policy"
    assert await redis.get(dataplane_publisher.PUBLISHER_LOCK_KEY) is None


@pytest.mark.asyncio
async def test_plugin_and_routing_documents_share_publish_cycle_and_ttl(plugin_publication, monkeypatch):
    """Real MessagePack bytes reach Redis together with the existing routing payload."""
    import msgpack

    from mcpgateway.services import dataplane_publisher

    service, _factory, _db, redis = plugin_publication
    payload = _policy_payload("team-a::gateway-echo")
    monkeypatch.setattr(dataplane_publisher, "get_redis_client", AsyncMock(return_value=redis))

    async def fetch_once():
        service._shutdown_event.set()
        return payload

    monkeypatch.setattr(service, "fetch_payload", fetch_once)
    await service.publish_to_redis()
    routing_key = msgpack.packb((dataplane_publisher.USER_CONFIG_KEY, USER1_ID))
    assert msgpack.unpackb(await redis.get(routing_key), raw=False) == payload[USER1_ID]
    document = msgpack.unpackb(await redis.get(dataplane_publisher.RUNTIME_PLUGIN_CONFIG_KEY), raw=False)
    assert document == await service.fetch_plugin_config(payload)
    assert await redis.ttl(routing_key) == await redis.ttl(dataplane_publisher.RUNTIME_PLUGIN_CONFIG_KEY)


async def _wait_forever():
    """Block until cancelled by the test cleanup."""
    await asyncio.Event().wait()


def test_worker_id_is_computed_per_service_instance():
    """Each publisher instance gets the current worker PID."""
    from mcpgateway.services import dataplane_publisher

    with patch.object(dataplane_publisher.os, "getpid", side_effect=[11111, 22222]):
        first_service = dataplane_publisher.DataplanePublisherService()
        second_service = dataplane_publisher.DataplanePublisherService()

    assert first_service.worker_id != second_service.worker_id
    assert first_service.worker_id.endswith(":11111")
    assert second_service.worker_id.endswith(":22222")


# ============================================================================
# Lifecycle Management Tests
# ============================================================================


@pytest.mark.asyncio
async def test_start_creates_background_task():
    """start() creates and schedules the background publisher task."""
    from mcpgateway.services.dataplane_publisher import DataplanePublisherService

    service = DataplanePublisherService()
    assert service.task is None

    with patch.object(service, "publish_to_redis", new_callable=AsyncMock) as mock_publish:
        mock_publish.side_effect = _wait_forever

        await service.start()

        assert service.task is not None
        assert not service.task.done()

        # Cleanup
        service.task.cancel()
        try:
            await service.task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_start_is_idempotent():
    """Calling start() twice doesn't create duplicate tasks."""
    from mcpgateway.services.dataplane_publisher import DataplanePublisherService

    service = DataplanePublisherService()

    with patch.object(service, "publish_to_redis", new_callable=AsyncMock) as mock_publish:
        mock_publish.side_effect = _wait_forever

        await service.start()
        first_task = service.task

        await service.start()
        second_task = service.task

        assert first_task is second_task

        # Cleanup
        service.task.cancel()
        try:
            await service.task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_shutdown_stops_running_task():
    """shutdown() gracefully stops the background task."""
    from mcpgateway.services.dataplane_publisher import DataplanePublisherService

    service = DataplanePublisherService()

    with patch.object(service, "publish_to_redis", new_callable=AsyncMock) as mock_publish:

        async def _wait_for_shutdown():
            await service._shutdown_event.wait()

        mock_publish.side_effect = _wait_for_shutdown

        await service.start()
        assert service.task is not None

        await service.shutdown()

        assert service.task is None
        assert service._shutdown_event.is_set()


@pytest.mark.asyncio
async def test_shutdown_handles_timeout():
    """shutdown() cancels task if it doesn't stop within timeout."""
    from mcpgateway.services.dataplane_publisher import DataplanePublisherService

    service = DataplanePublisherService()

    with (
        patch.object(service, "publish_to_redis", new_callable=AsyncMock) as mock_publish,
        patch("mcpgateway.services.dataplane_publisher.asyncio.wait_for", new_callable=AsyncMock) as mock_wait_for,
    ):
        mock_publish.side_effect = _wait_forever
        mock_wait_for.side_effect = asyncio.TimeoutError

        await service.start()
        assert service.task is not None

        await service.shutdown()

        assert service.task is None


@pytest.mark.asyncio
async def test_shutdown_is_idempotent():
    """Calling shutdown() when not started is a no-op."""
    from mcpgateway.services.dataplane_publisher import DataplanePublisherService

    service = DataplanePublisherService()
    assert service.task is None

    await service.shutdown()

    assert service.task is None


# ============================================================================
# Integration Test with Mock Database
# ============================================================================


@pytest.mark.asyncio
async def test_full_payload_generation_with_mock_db():
    """Integration test: fetch_payload() with mock database covering main code paths."""
    from mcpgateway.services.dataplane_publisher import DataplanePublisherService
    from unittest.mock import Mock

    service = DataplanePublisherService()

    # Mock database session and queries
    mock_db = MagicMock()

    # Create properly configured mocks
    server1 = Mock()
    server1.id = "s1"
    server1.owner_email = "user1@example.com"
    server1.team_id = "team1"
    server1.visibility = "public"
    server1.enabled = True

    server2 = Mock()
    server2.id = "s2"
    server2.owner_email = "user2@example.com"
    server2.team_id = "team2"
    server2.visibility = "private"
    server2.enabled = True

    gateway1 = Mock()
    gateway1.id = "g1"
    gateway1.name = "Gateway 1"
    gateway1.url = "http://localhost:9000"
    gateway1.transport = "STREAMABLEHTTP"
    gateway1.passthrough_headers = ["Authorization"]
    gateway1.add_headers = {"X-Tenant": "acme"}
    gateway1.remove_headers = ["Cookie"]
    gateway1.capabilities = {"resources": {"subscribe": True}}
    gateway1.owner_email = "user1@example.com"
    gateway1.team_id = "team1"
    gateway1.visibility = "public"
    gateway1.enabled = True

    prompt1 = Mock()
    prompt1.id = "p1"
    prompt1.name = "Prompt 1"
    prompt1.owner_email = "user1@example.com"
    prompt1.team_id = "team1"
    prompt1.visibility = "public"
    prompt1.enabled = True

    resource1 = Mock()
    resource1.id = "r1"
    resource1.name = "Resource 1"
    resource1.uri = "resource://one"
    resource1.owner_email = "user1@example.com"
    resource1.team_id = "team1"
    resource1.visibility = "public"
    resource1.enabled = True

    tool1 = Mock()
    tool1.id = "t1"
    tool1.name = "gw1-public_tool"
    tool1.original_name = "public_tool"
    tool1.input_schema = {
        "type": "object",
        "properties": {"region": {"type": "string", "x-mcp-header": "Region"}},
    }
    tool1.owner_email = "user1@example.com"
    tool1.team_id = "team1"
    tool1.visibility = "public"
    tool1.enabled = True

    tool2 = Mock()
    tool2.id = "t2"
    tool2.name = "gw1-private_tool"
    tool2.original_name = "private_tool"
    tool2.input_schema = {}
    tool2.owner_email = "user1@example.com"
    tool2.team_id = "team1"
    tool2.visibility = "private"
    tool2.enabled = True

    tool3 = Mock()
    tool3.id = "t3"
    tool3.name = "gw1-team2_tool"
    tool3.original_name = "team2_tool"
    tool3.input_schema = {"type": "object", "properties": {"count": {"type": "integer"}}}
    tool3.owner_email = "user2@example.com"
    tool3.team_id = "team2"
    tool3.visibility = "team"
    tool3.enabled = True

    malformed_tool = Mock()
    malformed_tool.id = "bad-tool"
    malformed_tool.name = "gw1-bad_tool"
    malformed_tool.original_name = "bad_tool"
    malformed_tool.input_schema = None
    malformed_tool.owner_email = "user1@example.com"
    malformed_tool.team_id = "team1"
    malformed_tool.visibility = "private"
    malformed_tool.enabled = True

    # Mock active users and user-team memberships
    mock_db.execute.return_value.all.side_effect = [
        # Active users query
        [(USER1_ID, "user1@example.com", False), (USER2_ID, "user2@example.com", False), (USER3_ID, "user3@example.com", False)],
        # User-team query
        [("user1@example.com", "team1"), ("user2@example.com", "team2")],
        # Server query
        [server1, server2],
        # Gateway query
        [gateway1],
        # Prompt query
        [prompt1],
        # Resource query
        [resource1],
        # Tool query
        [tool1, tool2, tool3, malformed_tool],
        # Tool associations
        [("s1", "t1", "g1"), ("s1", "t2", "g1"), ("s1", "t3", "g1"), ("s1", "bad-tool", "g1")],
        # Resource associations
        [("s1", "r1", "g1")],
        # Prompt associations
        [("s1", "p1", "g1")],
    ]

    with patch("mcpgateway.services.dataplane_publisher.fresh_db_session") as mock_session:
        mock_session.return_value.__enter__.return_value = mock_db

        payload = await service.fetch_payload()

        # Verify payload structure
        assert payload is not None
        assert set(payload) == {USER1_ID, USER2_ID, USER3_ID}

        # Verify user1 payload (has access to public server)
        user1_config = payload[USER1_ID]
        assert "virtual_hosts" in user1_config
        assert "s1" in user1_config["virtual_hosts"]

        # Verify backend configuration
        server1 = user1_config["virtual_hosts"]["s1"]
        assert "backends" in server1
        assert "g1" in server1["backends"]

        backend = server1["backends"]["g1"]
        assert backend == {
            "name": "Gateway 1",
            "url": "http://localhost:9000",
            "passthrough_headers": ["Authorization"],
            "add_headers": {"X-Tenant": "acme"},
            "remove_headers": ["Cookie"],
            "capabilities": {"resources": {"subscribe": True}},
            "allowed_tool_names": ["public_tool", "private_tool"],
            "tool_policy_contexts": {
                "public_tool": {"id": "t1", "name": "gw1-public_tool", "team_id": "team1", "context_id": "team1::gw1-public_tool"},
                "private_tool": {"id": "t2", "name": "gw1-private_tool", "team_id": "team1", "context_id": "team1::gw1-private_tool"},
            },
            "tool_schemas": {
                "public_tool": tool1.input_schema,
                "private_tool": {},
            },
            "allowed_resource_names": ["Resource 1"],
            "allowed_resource_uris": ["resource://one"],
            "allowed_prompt_names": ["Prompt 1"],
        }
        assert "bad_tool" not in backend["allowed_tool_names"]
        assert "bad_tool" not in backend["tool_schemas"]

        # Verify the gateway SELECT projection actually includes the new columns
        # (guards against getattr-on-Row silently returning None when columns are missing from SELECT)
        gateway_execute_call = mock_db.execute.call_args_list[3]
        stmt = gateway_execute_call[0][0]
        selected_keys = {col.key for col in stmt.selected_columns}
        assert "add_headers" in selected_keys, "Gateway SELECT must include add_headers"
        assert "remove_headers" in selected_keys, "Gateway SELECT must include remove_headers"

        tool_execute_call = mock_db.execute.call_args_list[6]
        tool_stmt = tool_execute_call[0][0]
        selected_tool_keys = {col.key for col in tool_stmt.selected_columns}
        assert "input_schema" in selected_tool_keys, "Tool SELECT must include input_schema"

        # Verify user2 sees public server but not private server from user1
        user2_config = payload[USER2_ID]
        assert "s1" in user2_config["virtual_hosts"]  # public
        # Own private server exists but has no backend associations, so it
        # is omitted from the payload (no publishable backends).
        assert "s2" not in user2_config["virtual_hosts"]
        user2_backend = user2_config["virtual_hosts"]["s1"]["backends"]["g1"]
        assert user2_backend["allowed_tool_names"] == ["public_tool", "team2_tool"]
        assert user2_backend["tool_schemas"] == {
            "public_tool": tool1.input_schema,
            "team2_tool": tool3.input_schema,
        }

        # Verify active users with no team membership still get public-only config.
        user3_config = payload[USER3_ID]
        assert "s1" in user3_config["virtual_hosts"]
        assert "s2" not in user3_config["virtual_hosts"]
        user3_backend = user3_config["virtual_hosts"]["s1"]["backends"]["g1"]
        assert user3_backend["allowed_tool_names"] == ["public_tool"]
        assert user3_backend["tool_schemas"] == {"public_tool": tool1.input_schema}
        assert list(user3_backend["tool_policy_contexts"]) == ["public_tool"]
        assert user3_backend["tool_policy_contexts"]["public_tool"]["context_id"] == "team1::gw1-public_tool"
        assert "user_email" not in payload[USER3_ID]


def test_build_user_data_excludes_non_object_tool_schema(caplog):
    """A malformed tool is excluded without dropping valid tools from the snapshot."""
    from unittest.mock import Mock

    from mcpgateway.services.dataplane_publisher import BackendItemsByServer, DataplanePublisherService

    bad_tool = Mock(id="bad-tool", original_name="bad", input_schema=None, visibility="public")
    good_tool = Mock(id="good-tool", original_name="good", input_schema={"type": "object"}, visibility="public", team_id=None)
    good_tool.name = "gw-good"
    server = Mock(id="server", visibility="public")
    backend_items_by_server: BackendItemsByServer = {
        "server": {
            "gateway": {
                "tools": ["bad-tool", "good-tool"],
                "resources": [],
                "prompts": [],
            }
        }
    }

    result = DataplanePublisherService()._build_user_data("user@example.com", set(), False, [server], [], [], [], [bad_tool, good_tool], backend_items_by_server)

    backend_items = result["servers"][0]["backend_items"]["gateway"]
    assert backend_items["tools"] == ["good"]
    assert backend_items["tool_schemas"] == {"good": {"type": "object"}}
    assert "Excluding tool bad-tool" in caplog.text


# ============================================================================
# Edge Cases
# ============================================================================


@pytest.mark.asyncio
async def test_fetch_payload_handles_db_error():
    """fetch_payload() returns None when database query fails."""
    from mcpgateway.services.dataplane_publisher import DataplanePublisherService

    service = DataplanePublisherService()

    mock_db = MagicMock()
    mock_db.execute.side_effect = Exception("Database error")

    with patch("mcpgateway.services.dataplane_publisher.fresh_db_session") as mock_session:
        mock_session.return_value.__enter__.return_value = mock_db

        result = await service.fetch_payload()

        assert result is None


@pytest.mark.asyncio
async def test_fetch_payload_empty_database():
    """fetch_payload() handles empty database (no active users)."""
    from mcpgateway.services.dataplane_publisher import DataplanePublisherService

    service = DataplanePublisherService()

    mock_db = MagicMock()
    mock_db.execute.return_value.all.return_value = []  # No users

    with patch("mcpgateway.services.dataplane_publisher.fresh_db_session") as mock_session:
        mock_session.return_value.__enter__.return_value = mock_db

        result = await service.fetch_payload()

        assert result == {}


def test_filter_for_user_visibility_rules():
    """_filter_for_user() correctly applies visibility rules."""
    from mcpgateway.services.dataplane_publisher import DataplanePublisherService
    from unittest.mock import Mock

    admin_only_row = Mock(visibility="private", owner_email="owner@example.com", team_id="team1")
    assert DataplanePublisherService._filter_for_user(admin_only_row, "admin@example.com", set(), is_admin=True)

    # Public: visible to all
    public_row = Mock(visibility="public", owner_email="owner@example.com", team_id="team1")
    assert DataplanePublisherService._filter_for_user(public_row, "anyone@example.com", set())

    # Private: only owner
    private_row = Mock(visibility="private", owner_email="owner@example.com", team_id="team1")
    assert DataplanePublisherService._filter_for_user(private_row, "owner@example.com", set())
    assert not DataplanePublisherService._filter_for_user(private_row, "other@example.com", {"team1"})

    # Team: team members only
    team_row = Mock(visibility="team", owner_email="owner@example.com", team_id="team1")
    assert DataplanePublisherService._filter_for_user(team_row, "member@example.com", {"team1"})
    assert not DataplanePublisherService._filter_for_user(team_row, "outsider@example.com", {"team2"})


def test_create_payload_filters_empty_backends():
    """create_payload() excludes backends with no items."""
    from mcpgateway.services.dataplane_publisher import DataplanePublisherService

    service = DataplanePublisherService()
    data = {
        USER1_ID: {
            "servers": [
                {
                    "id": "server1",
                    "backend_items": {
                        "gateway1": {"tools": [], "tool_schemas": {}, "tool_policy_contexts": {}, "resources": [], "prompts": []},
                    },
                }
            ],
            "gateways": [{"id": "gateway1", "name": "Gateway 1", "url": "http://localhost:9000", "transport": "STREAMABLEHTTP", "passthrough_headers": None}],
            "prompts": [],
            "resources": [],
        }
    }

    result = service.create_payload(data)

    # A server with no publishable backends is omitted entirely so the
    # dataplane 404s it instead of serving an empty tool list.
    assert "server1" not in result[USER1_ID]["virtual_hosts"]


@pytest.mark.parametrize("transport", ["SSE", "STDIO"])
def test_create_payload_excludes_non_streamable_gateways(transport: str):
    """create_payload() drops backends whose transport the dataplane cannot serve."""
    from mcpgateway.services.dataplane_publisher import DataplanePublisherService

    service = DataplanePublisherService()
    data = {
        USER1_ID: {
            "servers": [
                {
                    "id": "server1",
                    "backend_items": {
                        "gateway_non_streamable": {
                            "tools": ["tool1"],
                            "tool_schemas": {},
                            "tool_policy_contexts": {},
                            "resources": [],
                            "prompts": [],
                        },
                    },
                }
            ],
            "gateways": [{"id": "gateway_non_streamable", "name": "Unsupported Gateway", "url": "http://localhost:9000/mcp", "transport": transport, "passthrough_headers": None}],
            "prompts": [],
            "resources": [],
        }
    }

    result = service.create_payload(data)

    # The unsupported backend is excluded and the now-backendless server is omitted.
    assert result[USER1_ID]["virtual_hosts"] == {}


def test_create_payload_normalizes_null_passthrough_headers():
    """create_payload() emits an empty list for gateways without passthrough headers."""
    from mcpgateway.services.dataplane_publisher import DataplanePublisherService

    service = DataplanePublisherService()
    data = {
        USER1_ID: {
            "servers": [
                {
                    "id": "server1",
                    "backend_items": {
                        "gateway1": {"tools": ["tool1"], "tool_schemas": {}, "tool_policy_contexts": {"tool1": {"id": "t1", "name": "gateway-tool1", "team_id": None, "context_id": ""}}, "resources": [], "prompts": []},
                    },
                }
            ],
            "gateways": [{"id": "gateway1", "name": "Gateway 1", "url": "http://localhost:9000", "transport": "STREAMABLEHTTP", "passthrough_headers": None}],
            "prompts": [],
            "resources": [],
        }
    }

    result = service.create_payload(data)

    backend = result[USER1_ID]["virtual_hosts"]["server1"]["backends"]["gateway1"]
    assert backend["passthrough_headers"] == []
    assert backend["add_headers"] == {}
    assert backend["remove_headers"] == []
    assert backend["capabilities"] == {}
    assert backend["tool_policy_contexts"]["tool1"] == {"id": "t1", "name": "gateway-tool1", "team_id": None, "context_id": "server1"}
    assert data[USER1_ID]["servers"][0]["backend_items"]["gateway1"]["tool_policy_contexts"]["tool1"]["context_id"] == ""


def test_create_payload_handles_missing_references():
    """create_payload() handles missing gateway/resource/prompt references."""
    from mcpgateway.services.dataplane_publisher import DataplanePublisherService

    service = DataplanePublisherService()
    data = {
        USER1_ID: {
            "servers": [
                {
                    "id": "server1",
                    "backend_items": {
                        "missing_gateway": {
                            "tools": ["tool1"],
                            "tool_schemas": {},
                            "tool_policy_contexts": {},
                            "resources": ["missing_res"],
                            "prompts": ["missing_prompt"],
                        },
                    },
                }
            ],
            "gateways": [],  # Gateway not in list
            "prompts": [],  # Prompt not in list
            "resources": [],  # Resource not in list
        }
    }

    result = service.create_payload(data)

    # Server exists but has no backends (gateway missing)
    # With its only gateway missing, the server has no publishable backends
    # and is omitted from the payload.
    assert "server1" not in result[USER1_ID]["virtual_hosts"]


@pytest.mark.asyncio
async def test_publish_skips_when_redis_unavailable():
    """publish_to_redis() continues gracefully when Redis is unavailable."""
    from mcpgateway.services.dataplane_publisher import DataplanePublisherService, get_publisher_interval

    service = DataplanePublisherService()
    real_sleep = asyncio.sleep

    async def _sleep_until_shutdown(_timeout):
        await service._shutdown_event.wait()

    with (
        patch("mcpgateway.services.dataplane_publisher.get_redis_client", new_callable=AsyncMock) as mock_redis,
        patch("mcpgateway.services.dataplane_publisher.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        mock_redis.return_value = None
        mock_sleep.side_effect = _sleep_until_shutdown

        await service.start()
        await real_sleep(0)
        await service.shutdown()

        # Should not raise, just log and continue
        mock_sleep.assert_awaited_once_with(get_publisher_interval())


@pytest.mark.asyncio
async def test_publish_skips_when_fetch_fails():
    """publish_to_redis() skips publish when fetch_payload returns None."""
    from mcpgateway.services.dataplane_publisher import DataplanePublisherService

    service = DataplanePublisherService()

    mock_redis = MagicMock()
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.pipeline.return_value.execute = AsyncMock()
    mock_redis.eval = AsyncMock()

    with (
        patch("mcpgateway.services.dataplane_publisher.get_redis_client", new_callable=AsyncMock) as mock_get_redis,
        patch.object(service, "fetch_payload", new_callable=AsyncMock) as mock_fetch,
    ):
        mock_get_redis.return_value = mock_redis
        mock_fetch.return_value = None

        await service.start()
        await asyncio.sleep(0.01)
        await service.shutdown()

        # Pipeline should not be called when fetch returns None
        mock_redis.pipeline.assert_not_called()


@pytest.mark.asyncio
async def test_publish_continues_when_lock_acquisition_raises():
    """publish_to_redis() keeps running when Redis lock acquisition fails."""
    from mcpgateway.services.dataplane_publisher import DataplanePublisherService

    service = DataplanePublisherService()

    mock_redis = MagicMock()
    mock_redis.set = AsyncMock(side_effect=Exception("redis unavailable"))
    mock_redis.pipeline.return_value.execute = AsyncMock()
    mock_redis.eval = AsyncMock()

    with patch("mcpgateway.services.dataplane_publisher.get_redis_client", new_callable=AsyncMock) as mock_get_redis:
        mock_get_redis.return_value = mock_redis

        await service.start()
        await asyncio.sleep(0)
        await service.shutdown()

        mock_redis.set.assert_awaited_once()
        mock_redis.pipeline.assert_not_called()
        mock_redis.eval.assert_not_awaited()


@pytest.mark.asyncio
async def test_publish_skips_when_lock_not_acquired():
    """publish_to_redis() skips publishing when another worker holds the lock."""
    from mcpgateway.services.dataplane_publisher import DataplanePublisherService, get_publisher_interval

    service = DataplanePublisherService()
    real_sleep = asyncio.sleep

    async def _sleep_until_shutdown(_timeout):
        await service._shutdown_event.wait()

    mock_redis = MagicMock()
    mock_redis.set = AsyncMock(return_value=False)
    mock_redis.pipeline.return_value.execute = AsyncMock()
    mock_redis.eval = AsyncMock()

    with (
        patch("mcpgateway.services.dataplane_publisher.get_redis_client", new_callable=AsyncMock) as mock_get_redis,
        patch("mcpgateway.services.dataplane_publisher.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        patch.object(service, "fetch_payload", new_callable=AsyncMock) as mock_fetch,
    ):
        mock_get_redis.return_value = mock_redis
        mock_sleep.side_effect = _sleep_until_shutdown

        await service.start()
        await real_sleep(0)
        await service.shutdown()

        mock_redis.set.assert_awaited_once()
        mock_sleep.assert_awaited_once_with(get_publisher_interval())
        mock_fetch.assert_not_awaited()
        mock_redis.pipeline.assert_not_called()
        mock_redis.eval.assert_not_awaited()


@pytest.mark.asyncio
async def test_publish_writes_payload_releases_lock_and_exits_when_shutdown_wait_returns():
    """publish_to_redis() writes msgpack payloads and releases the worker lock."""
    import msgpack

    from mcpgateway.services.dataplane_publisher import PUBLISHER_LOCK_KEY, USER_CONFIG_KEY, DataplanePublisherService, get_publisher_interval, get_publisher_ttl

    service = DataplanePublisherService()
    payload = {USER1_ID: {"virtual_hosts": {"server1": {"backends": {}}}}}

    pipe = MagicMock()
    pipe.execute = AsyncMock()
    mock_redis = MagicMock()
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.pipeline.return_value = pipe
    mock_redis.eval = AsyncMock()

    async def _finish_cycle(awaitable, timeout):
        del timeout
        awaitable.close()

    with (
        patch("mcpgateway.services.dataplane_publisher.get_redis_client", new_callable=AsyncMock) as mock_get_redis,
        patch("mcpgateway.services.dataplane_publisher.asyncio.wait_for", new_callable=AsyncMock, side_effect=_finish_cycle) as mock_wait_for,
        patch.object(service, "fetch_payload", new_callable=AsyncMock, return_value=payload),
    ):
        mock_get_redis.return_value = mock_redis

        await service.publish_to_redis()

    assert pipe.set.call_count == 2
    key_arg, value_arg = pipe.set.call_args.args
    assert msgpack.unpackb(key_arg, raw=False) == [USER_CONFIG_KEY, USER1_ID]
    assert msgpack.unpackb(value_arg, raw=False) == payload[USER1_ID]
    assert pipe.set.call_args.kwargs == {"ex": get_publisher_ttl()}
    pipe.execute.assert_awaited_once()
    mock_redis.set.assert_awaited_once_with(PUBLISHER_LOCK_KEY, service.worker_id, nx=True, ex=get_publisher_interval() + 30)
    mock_redis.eval.assert_awaited_once()
    assert mock_redis.eval.await_args.args[1:] == (1, PUBLISHER_LOCK_KEY, service.worker_id)
    mock_wait_for.assert_awaited_once()


@pytest.mark.asyncio
async def test_publish_uses_configured_interval_for_ttl_lock_and_wait():
    """A runtime interval override propagates to every publisher timeout."""
    from mcpgateway.services import dataplane_publisher

    service = dataplane_publisher.DataplanePublisherService()
    payload = {USER1_ID: {"virtual_hosts": {}}}

    pipe = MagicMock()
    pipe.execute = AsyncMock()
    mock_redis = MagicMock()
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.pipeline.return_value = pipe
    mock_redis.eval = AsyncMock()

    async def _finish_cycle(awaitable, timeout):
        del timeout
        awaitable.close()

    with (
        patch.object(dataplane_publisher.settings, "dataplane_publisher_interval_seconds", 2),
        patch.object(dataplane_publisher, "get_redis_client", new_callable=AsyncMock, return_value=mock_redis),
        patch.object(dataplane_publisher.asyncio, "wait_for", new_callable=AsyncMock, side_effect=_finish_cycle) as mock_wait_for,
        patch.object(service, "fetch_payload", new_callable=AsyncMock, return_value=payload),
    ):
        await service.publish_to_redis()

    assert pipe.set.call_args.kwargs == {"ex": 14}
    mock_redis.set.assert_awaited_once_with(dataplane_publisher.PUBLISHER_LOCK_KEY, service.worker_id, nx=True, ex=32)
    mock_wait_for.assert_awaited_once_with(ANY, timeout=2)


@pytest.mark.asyncio
async def test_publish_releases_lock_when_pipeline_execute_fails():
    """publish_to_redis() logs pipeline failures but still releases the lock."""
    from mcpgateway.services.dataplane_publisher import DataplanePublisherService

    service = DataplanePublisherService()

    pipe = MagicMock()
    pipe.execute = AsyncMock(side_effect=Exception("pipeline boom"))
    mock_redis = MagicMock()
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.pipeline.return_value = pipe
    mock_redis.eval = AsyncMock()

    async def _finish_cycle(awaitable, timeout):
        del timeout
        awaitable.close()

    with (
        patch("mcpgateway.services.dataplane_publisher.get_redis_client", new_callable=AsyncMock) as mock_get_redis,
        patch("mcpgateway.services.dataplane_publisher.asyncio.wait_for", new_callable=AsyncMock, side_effect=_finish_cycle),
        patch.object(service, "fetch_payload", new_callable=AsyncMock, return_value={USER1_ID: {"virtual_hosts": {}}}),
    ):
        mock_get_redis.return_value = mock_redis

        await service.publish_to_redis()

    assert pipe.set.call_count == 2
    pipe.execute.assert_awaited_once()
    mock_redis.eval.assert_awaited_once()


@pytest.mark.asyncio
async def test_publish_logs_lock_release_failure():
    """publish_to_redis() handles Redis errors while releasing the lock."""
    from mcpgateway.services.dataplane_publisher import DataplanePublisherService

    service = DataplanePublisherService()

    mock_redis = MagicMock()
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.pipeline.return_value.execute = AsyncMock()
    mock_redis.eval = AsyncMock(side_effect=Exception("eval boom"))

    async def _finish_cycle(awaitable, timeout):
        del timeout
        awaitable.close()

    with (
        patch("mcpgateway.services.dataplane_publisher.get_redis_client", new_callable=AsyncMock) as mock_get_redis,
        patch("mcpgateway.services.dataplane_publisher.asyncio.wait_for", new_callable=AsyncMock, side_effect=_finish_cycle),
        patch.object(service, "fetch_payload", new_callable=AsyncMock, return_value={USER1_ID: {"virtual_hosts": {}}}),
    ):
        mock_get_redis.return_value = mock_redis

        await service.publish_to_redis()

    mock_redis.eval.assert_awaited_once()


@pytest.mark.asyncio
async def test_publish_continues_after_cycle_timeout():
    """publish_to_redis() continues after the inter-cycle wait times out."""
    from mcpgateway.services.dataplane_publisher import DataplanePublisherService

    service = DataplanePublisherService()

    mock_redis = MagicMock()
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.pipeline.return_value.execute = AsyncMock()
    mock_redis.eval = AsyncMock()

    async def _timeout_and_stop(awaitable, timeout):
        del timeout
        awaitable.close()
        service._shutdown_event.set()
        raise asyncio.TimeoutError

    with (
        patch("mcpgateway.services.dataplane_publisher.get_redis_client", new_callable=AsyncMock) as mock_get_redis,
        patch("mcpgateway.services.dataplane_publisher.asyncio.wait_for", new_callable=AsyncMock, side_effect=_timeout_and_stop),
        patch.object(service, "fetch_payload", new_callable=AsyncMock, return_value={USER1_ID: {"virtual_hosts": {}}}),
    ):
        mock_get_redis.return_value = mock_redis

        await service.publish_to_redis()

    mock_redis.set.assert_awaited_once()
    mock_redis.eval.assert_awaited_once()


def test_backend_item_helpers_add_items_and_skip_missing_gateway():
    """Backend item helper methods group rows by gateway and skip gateway-less rows."""
    from collections import defaultdict

    from mcpgateway.services.dataplane_publisher import DataplanePublisherService

    service = DataplanePublisherService()
    backend_items_by_server = defaultdict(dict)

    db = MagicMock()
    db.execute.return_value.all.return_value = [("server1", "tool1", None), ("server1", "tool2", "gateway1")]
    service._add_tools_to_backends(db, backend_items_by_server)  # pylint: disable=protected-access

    db.execute.return_value.all.return_value = [("server1", "resource1", None), ("server1", "resource2", "gateway1")]
    service._add_resources_to_backends(db, backend_items_by_server)  # pylint: disable=protected-access

    db.execute.return_value.all.return_value = [("server1", "prompt1", None), ("server1", "prompt2", "gateway1")]
    service._add_prompts_to_backends(db, backend_items_by_server)  # pylint: disable=protected-access

    assert dict(backend_items_by_server) == {
        "server1": {
            "gateway1": {
                "tools": ["tool2"],
                "resources": ["resource2"],
                "prompts": ["prompt2"],
            }
        }
    }
