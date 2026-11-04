# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_dataplane_publisher.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for DataplanePublisherService.
"""

# Standard
import asyncio
from contextlib import nullcontext
import msgpack
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock, Mock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.db import EmailUser, Gateway, Prompt, Resource, Server, Tool
from mcpgateway.services.dataplane_publisher import dataplane_publisher as dp_module
from mcpgateway.services.dataplane_publisher.dataplane_publisher import (
    DataplanePublisherService,
    PUBLISHER_RETRY_RAND_SECONDS,
    get_publisher_interval,
)
from mcpgateway.services.dataplane_publisher.db_loader import (
    UserConfigBuilder,
    add_unique_route,
    get_user_configs,
    load_backend_items,
)
from mcpgateway.services.dataplane_publisher.models import (
    ControlPlaneData,
    UserScope,
    VisibilityIndex,
)
from mcpgateway.services.dataplane_publisher.redis_store import PUBLISHER_LOCK_KEY

USER1_ID = "11111111-1111-1111-1111-111111111111"
USER2_ID = "22222222-2222-2222-2222-222222222222"
USER3_ID = "33333333-3333-3333-3333-333333333333"


async def _wait_forever():
    """Block until cancelled by the test cleanup."""
    await asyncio.Event().wait()


@pytest.mark.asyncio
async def test_update_notification_publishes_without_waiting_for_schedule():
    """Publish updated configuration after notification without waiting for the periodic deadline."""
    service = DataplanePublisherService()
    first_write = asyncio.Event()
    second_write = asyncio.Event()
    payloads = [{USER1_ID: {"virtual_hosts": {}}}, {USER2_ID: {"virtual_hosts": {}}}]
    redis = MagicMock()
    redis.set = AsyncMock(return_value=True)
    redis.eval = AsyncMock()
    writes = 0

    async def record_write():
        """Signal completed Redis writes."""
        nonlocal writes
        writes += 1
        (first_write if writes == 1 else second_write).set()

    redis.pipeline.return_value.execute = AsyncMock(side_effect=record_write)
    with (
        patch.object(dp_module, "get_publisher_interval", return_value=3600),
        patch("mcpgateway.services.dataplane_publisher.redis_store.get_redis_client", new_callable=AsyncMock, return_value=redis),
        patch.object(service, "fetch_payload", new_callable=AsyncMock, side_effect=payloads) as fetch,
    ):
        await service.start()
        try:
            await asyncio.wait_for(first_write.wait(), timeout=2)
            dp_module.notify_dataplane()
            await asyncio.wait_for(second_write.wait(), timeout=3)
            assert fetch.await_count == 2
            key, value = redis.pipeline.return_value.set.call_args.args
            assert msgpack.unpackb(key, raw=False) == ["UserConfig", USER2_ID]
            assert msgpack.unpackb(value, raw=False) == payloads[1][USER2_ID]
        finally:
            await service.shutdown()


@pytest.fixture(params=[False, True], ids=["regular-reader", "admin-reader"])
def gateway_owner_setup(test_db, request):
    """Create public routes through owned, active, ownerless, and disabled gateways."""
    owner = EmailUser(email="publisher-owner@example.com", is_active=True)
    reader = EmailUser(email="publisher-reader@example.com", is_active=True, is_admin=request.param)
    server = Server(name="publisher-server", visibility="public", enabled=True)
    test_db.add_all([owner, reader, server])
    test_db.flush()

    gateways = {}
    route_names = {}
    for label, owner_email, enabled in (
        ("owned", owner.email, True),
        ("active", reader.email, True),
        ("ownerless", None, True),
        ("disabled", reader.email, False),
    ):
        gateway = Gateway(
            name=label,
            slug=label,
            url=f"https://{label}.example.com/mcp",
            capabilities={},
            transport="STREAMABLEHTTP",
            visibility="public",
            owner_email=owner_email,
            enabled=enabled,
        )
        test_db.add(gateway)
        test_db.flush()
        gateways[label] = gateway.id
        item_fields = {"gateway_id": gateway.id, "visibility": "public", "enabled": True}
        named_fields = {"name": label, "original_name": label, "custom_name": label, "custom_name_slug": label}
        server.tools.append(Tool(**item_fields, **named_fields, input_schema={"type": "object"}))
        server.prompts.append(Prompt(**item_fields, **named_fields, template="Hello", argument_schema={}))
        server.resources.append(Resource(**item_fields, name=label, uri=f"resource://{label}"))
        test_db.flush()
        route_names[label] = {"tools": server.tools[-1].name, "prompts": server.prompts[-1].name, "resources": f"resource://{label}"}
    test_db.flush()

    with patch("mcpgateway.services.dataplane_publisher.db_loader.fresh_db_session", side_effect=lambda: nullcontext(test_db)):
        yield SimpleNamespace(owner=owner, reader=reader, server=server, gateways=gateways, route_names=route_names)


def _assert_published_gateway_routes(payload, setup, expected_labels):
    """Check the exact backend and route sets visible to the reader."""
    host = payload[str(setup.reader.id)]["virtual_hosts"][setup.server.id]
    assert set(host["backends"]) == {setup.gateways[label] for label in expected_labels}
    assert host["tools"] == {
        setup.route_names[label]["tools"]: {"backend_name": setup.gateways[label], "upstream_name": label} for label in expected_labels
    }
    assert host["prompts"] == {
        setup.route_names[label]["prompts"]: {"backend_name": setup.gateways[label], "upstream_name": label} for label in expected_labels
    }
    assert host["resources"] == {
        setup.route_names[label]["resources"]: {"backend_name": setup.gateways[label], "upstream_name": f"resource://{label}"} for label in expected_labels
    }


def test_deactivating_gateway_owner_removes_published_routes(test_db, gateway_owner_setup):
    """Deactivation removes the owner configuration and owned routes while preserving other eligible routes."""
    setup = gateway_owner_setup
    payload = get_user_configs()
    assert str(setup.owner.id) in payload
    _assert_published_gateway_routes(payload, setup, {"owned", "active", "ownerless"})

    setup.owner.is_active = False
    test_db.flush()

    payload = get_user_configs()
    assert str(setup.owner.id) not in payload
    _assert_published_gateway_routes(payload, setup, {"active", "ownerless"})


def test_reactivating_gateway_owner_restores_published_routes(test_db, gateway_owner_setup):
    """Reactivation restores the owner configuration and owned routes while keeping disabled gateways excluded."""
    setup = gateway_owner_setup
    setup.owner.is_active = False
    test_db.flush()
    payload = get_user_configs()
    assert str(setup.owner.id) not in payload
    _assert_published_gateway_routes(payload, setup, {"active", "ownerless"})

    setup.owner.is_active = True
    test_db.flush()

    payload = get_user_configs()
    assert str(setup.owner.id) in payload
    _assert_published_gateway_routes(payload, setup, {"owned", "active", "ownerless"})


def test_worker_id_is_computed_per_service_instance():
    """Each publisher instance gets the current worker PID."""
    with patch.object(dp_module.os, "getpid", side_effect=[11111, 22222]):
        first_service = DataplanePublisherService()
        second_service = DataplanePublisherService()

    assert first_service.worker_id != second_service.worker_id
    assert first_service.worker_id.endswith(":11111")
    assert second_service.worker_id.endswith(":22222")


# ============================================================================
# Lifecycle Management Tests
# ============================================================================


@pytest.mark.asyncio
async def test_start_creates_background_task():
    """start() creates and schedules the background publisher task."""
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
async def test_shutdown_stops_running_task():
    """shutdown() gracefully stops the background task."""
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
    service = DataplanePublisherService()

    with (
        patch.object(service, "publish_to_redis", new_callable=AsyncMock) as mock_publish,
        patch("mcpgateway.services.dataplane_publisher.dataplane_publisher.asyncio.wait_for", new_callable=AsyncMock) as mock_wait_for,
    ):
        mock_publish.side_effect = _wait_forever
        mock_wait_for.side_effect = asyncio.TimeoutError

        await service.start()
        assert service.task is not None

        await service.shutdown()

        assert service.task is None


# ============================================================================
# Integration Test with Mock Database
# ============================================================================


@pytest.mark.asyncio
async def test_full_payload_generation_with_mock_db():
    """Integration test: fetch_payload() with mock database covering main code paths."""
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
    prompt1.original_name = "upstream_prompt"
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

    with patch("mcpgateway.services.dataplane_publisher.db_loader.fresh_db_session") as mock_session:
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
        assert set(server1["backends"]) == {"g1"}

        backend = server1["backends"]["g1"]
        assert backend == {
            "name": "Gateway 1",
            "url": "http://localhost:9000",
            "mcp_protocol_version": "",
            "passthrough_headers": ["Authorization"],
            "add_headers": {"X-Tenant": "acme"},
            "remove_headers": ["Cookie"],
            "completion": {},
            "capabilities": gateway1.capabilities,
            "tool_schemas": {
                "public_tool": tool1.input_schema,
                "private_tool": {},
            },
        }
        assert server1["tools"] == {
            "gw1-public_tool": {"backend_name": "g1", "upstream_name": "public_tool"},
            "gw1-private_tool": {"backend_name": "g1", "upstream_name": "private_tool"},
        }
        assert server1["prompts"] == {"Prompt 1": {"backend_name": "g1", "upstream_name": "upstream_prompt"}}
        assert server1["resources"] == {"resource://one": {"backend_name": "g1", "upstream_name": "resource://one"}}
        assert server1["resource_templates"] == {}
        assert set(server1) == {"backends", "tools", "prompts", "resources", "resource_templates"}
        assert "bad_tool" not in backend["tool_schemas"]
        assert msgpack.unpackb(msgpack.packb(payload, use_bin_type=True), raw=False) == payload

        # Verify the gateway SELECT projection actually includes the new columns
        # (guards against getattr-on-Row silently returning None when columns are missing from SELECT)
        gateway_execute_call = mock_db.execute.call_args_list[3]
        stmt = gateway_execute_call[0][0]
        selected_keys = {col.key for col in stmt.selected_columns}
        assert "add_headers" in selected_keys, "Gateway SELECT must include add_headers"
        assert "remove_headers" in selected_keys, "Gateway SELECT must include remove_headers"
        assert "capabilities" in selected_keys

        tool_execute_call = mock_db.execute.call_args_list[6]
        tool_stmt = tool_execute_call[0][0]
        selected_tool_keys = {col.key for col in tool_stmt.selected_columns}
        assert "input_schema" in selected_tool_keys, "Tool SELECT must include input_schema"
        assert {"name", "original_name"} <= selected_tool_keys
        assert {"name", "original_name"} <= {col.key for col in mock_db.execute.call_args_list[4].args[0].selected_columns}

        # Verify user2 sees public server but not private server from user1
        user2_config = payload[USER2_ID]
        assert "s1" in user2_config["virtual_hosts"]  # public
        # Own private server exists but has no backend associations, so it
        # is omitted from the payload (no publishable backends).
        assert "s2" not in user2_config["virtual_hosts"]
        user2_backend = user2_config["virtual_hosts"]["s1"]["backends"]["g1"]
        assert user2_config["virtual_hosts"]["s1"]["tools"] == {
            "gw1-public_tool": {"backend_name": "g1", "upstream_name": "public_tool"},
            "gw1-team2_tool": {"backend_name": "g1", "upstream_name": "team2_tool"},
        }
        assert user2_backend["tool_schemas"] == {
            "public_tool": tool1.input_schema,
            "team2_tool": tool3.input_schema,
        }

        # Verify active users with no team membership still get public-only config.
        user3_config = payload[USER3_ID]
        assert "s1" in user3_config["virtual_hosts"]
        assert "s2" not in user3_config["virtual_hosts"]
        user3_backend = user3_config["virtual_hosts"]["s1"]["backends"]["g1"]
        assert user3_config["virtual_hosts"]["s1"]["tools"] == {"gw1-public_tool": {"backend_name": "g1", "upstream_name": "public_tool"}}
        assert user3_backend["tool_schemas"] == {"public_tool": tool1.input_schema}


@pytest.mark.parametrize("teams", [set(), {"team1"}])
@pytest.mark.parametrize("duplicate_names", [False, True])
def test_named_routes_preserve_backend_identity_and_visibility(teams, duplicate_names):
    """Gateway IDs preserve distinct backends even when names match, respecting visibility."""
    def _row(item_id, visibility="public", **fields):
        return SimpleNamespace(id=item_id, visibility=visibility, owner_email="owner@example.com", team_id="team1", **fields)

    server = _row("s1")
    gateways = [
        _row(
            gateway_id,
            name="shared-backend" if duplicate_names else f"backend-{gateway_id}",
            url=f"http://{gateway_id}:9000/mcp",
            transport="STREAMABLEHTTP",
            passthrough_headers=[],
            add_headers={},
            remove_headers=[],
            capabilities=None,
        )
        for gateway_id in ("g1", "g2")
    ]
    tools = [_row(gw.id, name=f"{gw.id}-search", original_name="search", input_schema={"type": "object"}) for gw in gateways]
    prompt = _row("p1", "team", name="gw-prompt", original_name="prompt")
    resource = _row("r1", "team", name="Resource", uri="resource://one")
    associations = {"s1": {gw.id: {"tools": [gw.id], "resources": [], "prompts": []} for gw in gateways}}
    associations["s1"]["g1"].update(resources=["r1", "missing"], prompts=["p1", "missing"])

    user = UserScope(id=USER1_ID, email="reader@example.com", is_admin=False, team_ids=frozenset(teams))
    data = ControlPlaneData(
        users=(user,),
        servers=VisibilityIndex.build([server]),
        gateways=VisibilityIndex.build(gateways),
        tools=VisibilityIndex.build(tools),
        prompts=VisibilityIndex.build([prompt]),
        resources=VisibilityIndex.build([resource]),
        backend_items=associations,
    )
    host = UserConfigBuilder(data).build_payload()[USER1_ID]["virtual_hosts"]["s1"]

    assert set(host["backends"]) == {"g1", "g2"}
    assert host["tools"] == {f"{gw.id}-search": {"backend_name": gw.id, "upstream_name": "search"} for gw in gateways}
    for gw in gateways:
        backend = host["backends"][gw.id]
        assert backend["name"] == gw.name
        assert backend["url"] == gw.url
        assert backend["tool_schemas"] == {"search": {"type": "object"}}
        assert backend["mcp_protocol_version"] == ""
        assert backend["capabilities"] == {}

    assert host["prompts"] == ({"gw-prompt": {"backend_name": "g1", "upstream_name": "prompt"}} if teams else {})
    assert host["resources"] == ({"resource://one": {"backend_name": "g1", "upstream_name": "resource://one"}} if teams else {})


# ============================================================================
# Edge Cases
# ============================================================================


@pytest.mark.asyncio
async def test_fetch_payload_handles_db_error():
    """fetch_payload() returns None when database query fails."""
    service = DataplanePublisherService()

    mock_db = MagicMock()
    mock_db.execute.side_effect = Exception("Database error")

    with patch("mcpgateway.services.dataplane_publisher.db_loader.fresh_db_session") as mock_session:
        mock_session.return_value.__enter__.return_value = mock_db

        result = await service.fetch_payload()

        assert result is None


@pytest.mark.parametrize("transport", ["SSE", "STDIO"])
def test_create_payload_excludes_non_streamable_gateways(transport: str):
    """Builder drops backends whose transport the dataplane cannot serve."""
    def _row(item_id, **fields):
        return SimpleNamespace(id=item_id, visibility="public", owner_email=None, team_id=None, **fields)

    tool = _row("tool1", name="gw-tool1", original_name="tool1", input_schema={"type": "object"})
    user = UserScope(id=USER1_ID, email="u@example.com", is_admin=False, team_ids=frozenset())
    data = ControlPlaneData(
        users=(user,),
        servers=VisibilityIndex.build([_row("server1")]),
        gateways=VisibilityIndex.build([_row("gateway_ns", name="Unsupported Gateway", url="http://localhost:9000/mcp", transport=transport, passthrough_headers=None, add_headers={}, remove_headers=[])]),
        tools=VisibilityIndex.build([tool]),
        prompts=VisibilityIndex.build([]),
        resources=VisibilityIndex.build([]),
        backend_items={"server1": {"gateway_ns": {"tools": ["tool1"], "resources": [], "prompts": []}}},
    )
    result = UserConfigBuilder(data).build_payload()

    # The unsupported backend is excluded and the now-backendless server is omitted.
    assert result[USER1_ID]["virtual_hosts"] == {}


@pytest.mark.asyncio
async def test_publish_skips_when_redis_unavailable():
    """publish_to_redis() continues gracefully when Redis is unavailable."""
    service = DataplanePublisherService()
    real_sleep = asyncio.sleep

    async def _sleep_until_shutdown(_timeout):
        await service._shutdown_event.wait()

    with (
        patch("mcpgateway.services.dataplane_publisher.redis_store.get_redis_client", new_callable=AsyncMock) as mock_redis,
        patch.object(service, "_wait_for_next_publish", new_callable=AsyncMock, side_effect=_sleep_until_shutdown) as mock_wait,
    ):
        mock_redis.return_value = None

        await service.start()
        await real_sleep(0)
        await service.shutdown()

        # Should not raise, just log and continue — the wait was called once
        mock_wait.assert_awaited_once_with(get_publisher_interval())


@pytest.mark.asyncio
async def test_publish_skips_when_fetch_fails():
    """publish_to_redis() skips publish when fetch_payload returns None."""
    service = DataplanePublisherService()

    mock_redis = MagicMock()
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.pipeline.return_value.execute = AsyncMock()
    mock_redis.eval = AsyncMock()

    with (
        patch("mcpgateway.services.dataplane_publisher.redis_store.get_redis_client", new_callable=AsyncMock) as mock_get_redis,
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
async def test_publish_skips_when_lock_not_acquired():
    """publish_to_redis() skips publishing when another worker holds the lock."""
    service = DataplanePublisherService()
    real_sleep = asyncio.sleep

    async def _sleep_until_shutdown(_timeout):
        await service._shutdown_event.wait()

    mock_redis = MagicMock()
    mock_redis.set = AsyncMock(return_value=False)
    mock_redis.pipeline.return_value.execute = AsyncMock()
    mock_redis.eval = AsyncMock()

    with (
        patch("mcpgateway.services.dataplane_publisher.redis_store.get_redis_client", new_callable=AsyncMock) as mock_get_redis,
        patch.object(service, "_wait_for_next_publish", new_callable=AsyncMock, side_effect=_sleep_until_shutdown) as mock_wait,
        patch.object(service, "fetch_payload", new_callable=AsyncMock) as mock_fetch,
    ):
        mock_get_redis.return_value = mock_redis

        await service.start()
        await real_sleep(0)
        await service.shutdown()

        mock_redis.set.assert_awaited_once()
        mock_wait.assert_awaited_once_with(get_publisher_interval())
        mock_fetch.assert_not_awaited()
        mock_redis.pipeline.assert_not_called()
        mock_redis.eval.assert_not_awaited()


@pytest.mark.asyncio
async def test_publish_writes_payload_releases_lock_and_exits_when_shutdown_wait_returns():
    """publish_to_redis() writes msgpack payloads and releases the worker lock."""
    service = DataplanePublisherService()
    payload = {USER1_ID: {"virtual_hosts": {"server1": {"backends": {}}}}}

    pipe = MagicMock()
    pipe.execute = AsyncMock()
    mock_redis = MagicMock()
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.pipeline.return_value = pipe
    mock_redis.eval = AsyncMock()

    with (
        patch("mcpgateway.services.dataplane_publisher.redis_store.get_redis_client", new_callable=AsyncMock) as mock_get_redis,
        patch.object(service, "_wait_for_next_publish", new_callable=AsyncMock, return_value=True) as mock_wait_for,
        patch.object(service, "fetch_payload", new_callable=AsyncMock, return_value=payload),
    ):
        mock_get_redis.return_value = mock_redis

        await service.publish_to_redis()

    pipe.set.assert_called_once()
    key_arg, value_arg = pipe.set.call_args.args
    assert msgpack.unpackb(key_arg, raw=False) == ["UserConfig", USER1_ID]
    assert msgpack.unpackb(value_arg, raw=False) == payload[USER1_ID]
    assert pipe.set.call_args.kwargs == {"ex": get_publisher_interval() * 2 + 10}
    pipe.execute.assert_awaited_once()
    mock_redis.set.assert_awaited_once_with(PUBLISHER_LOCK_KEY, service.worker_id, nx=True, ex=get_publisher_interval() + 30)
    mock_redis.eval.assert_awaited_once()
    assert mock_redis.eval.await_args.args[1:] == (1, PUBLISHER_LOCK_KEY, service.worker_id)
    mock_wait_for.assert_awaited_once()


@pytest.mark.asyncio
async def test_publish_uses_configured_interval_for_ttl_lock_and_wait():
    """A runtime interval override propagates to every publisher timeout."""
    service = DataplanePublisherService()
    payload = {USER1_ID: {"virtual_hosts": {}}}

    pipe = MagicMock()
    pipe.execute = AsyncMock()
    mock_redis = MagicMock()
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.pipeline.return_value = pipe
    mock_redis.eval = AsyncMock()

    with (
        patch.object(dp_module.settings, "dataplane_publisher_interval_seconds", 2),
        patch("mcpgateway.services.dataplane_publisher.redis_store.get_redis_client", new_callable=AsyncMock, return_value=mock_redis),
        patch.object(service, "_wait_for_next_publish", new_callable=AsyncMock, return_value=True) as mock_wait_for,
        patch.object(service, "fetch_payload", new_callable=AsyncMock, return_value=payload),
    ):
        await service.publish_to_redis()

    assert pipe.set.call_args.kwargs == {"ex": 14}
    mock_redis.set.assert_awaited_once_with(PUBLISHER_LOCK_KEY, service.worker_id, nx=True, ex=32)
    mock_wait_for.assert_awaited_once_with(2)


@pytest.mark.asyncio
async def test_publish_releases_lock_when_pipeline_execute_fails():
    """publish_to_redis() logs pipeline failures but still releases the lock."""
    service = DataplanePublisherService()

    pipe = MagicMock()
    pipe.execute = AsyncMock(side_effect=Exception("pipeline boom"))
    mock_redis = MagicMock()
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.pipeline.return_value = pipe
    mock_redis.eval = AsyncMock()

    with (
        patch("mcpgateway.services.dataplane_publisher.redis_store.get_redis_client", new_callable=AsyncMock) as mock_get_redis,
        patch.object(service, "_wait_for_next_publish", new_callable=AsyncMock, return_value=True),
        patch.object(service, "fetch_payload", new_callable=AsyncMock, return_value={USER1_ID: {"virtual_hosts": {}}}),
    ):
        mock_get_redis.return_value = mock_redis

        await service.publish_to_redis()

    pipe.set.assert_called_once()
    pipe.execute.assert_awaited_once()
    mock_redis.eval.assert_awaited_once()


def test_backend_item_helpers_add_items_and_skip_missing_gateway():
    """load_backend_items() groups rows by gateway and skips gateway-less rows."""
    db = MagicMock()
    # tools: one without gateway (skipped), one with gateway
    # resources: one without gateway (skipped), one with gateway
    # prompts: one without gateway (skipped), one with gateway
    db.execute.return_value.all.side_effect = [
        [("server1", "tool1", None), ("server1", "tool2", "gateway1")],
        [("server1", "resource1", None), ("server1", "resource2", "gateway1")],
        [("server1", "prompt1", None), ("server1", "prompt2", "gateway1")],
    ]

    result = load_backend_items(db)

    assert result == {
        "server1": {
            "gateway1": {
                "tools": ["tool2"],
                "resources": ["resource2"],
                "prompts": ["prompt2"],
            }
        }
    }


# ============================================================================
# _add_unique_route Tests
# ============================================================================


def test_add_unique_route_detects_conflict_and_marks_ambiguous(caplog):
    """add_unique_route() removes a route and marks it ambiguous when two different backends claim the same name."""
    routes: dict = {}
    ambiguous: set = set()

    # First call: registers the route normally.
    add_unique_route(routes, ambiguous, "my_tool", "g1", "upstream_tool", "s1", "tool")
    assert routes == {"my_tool": {"backend_name": "g1", "upstream_name": "upstream_tool"}}
    assert ambiguous == set()

    # Second call: different backend — triggers conflict resolution.
    add_unique_route(routes, ambiguous, "my_tool", "g2", "upstream_tool", "s1", "tool")

    assert "my_tool" not in routes
    assert "my_tool" in ambiguous
    assert "my_tool" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("pending_notification", [False, True])
@pytest.mark.parametrize("failure_stage", ["client", "lock"])
async def test_publisher_tries_again_after_redis_error(pending_notification, failure_stage):
    """Retry after a Redis error and remember any update still waiting to be published."""
    service = DataplanePublisherService()
    if pending_notification:
        service._publish_requested.set()
    redis = MagicMock()
    redis.set = AsyncMock(return_value=True)
    redis.eval = AsyncMock()
    redis.pipeline.return_value.execute = AsyncMock(side_effect=service._shutdown_event.set)
    error = ConnectionError("Redis unavailable")
    retry_delay = 3.5
    client_results = [error, redis] if failure_stage == "client" else [redis, redis]
    if failure_stage == "lock":
        redis.set.side_effect = [error, True]

    async def wait_after_failure(timeout):
        """Check retained work and lock ownership before allowing the retry."""
        if service._shutdown_event.is_set():
            return True
        assert timeout == (retry_delay if pending_notification else 60)
        assert service._publish_requested.is_set() is pending_notification
        redis.eval.assert_not_awaited()
        return False

    wait_method = "_wait_for_shutdown" if pending_notification else "_wait_for_next_publish"
    payload = {USER1_ID: {"virtual_hosts": {}}}
    with (
        patch("mcpgateway.services.dataplane_publisher.redis_store.get_redis_client", new_callable=AsyncMock, side_effect=client_results) as get_client,
        patch("mcpgateway.services.dataplane_publisher.dataplane_publisher.get_publisher_interval", return_value=60),
        patch.object(dp_module.random, "uniform", return_value=retry_delay) as random_delay,
        patch.object(service, "fetch_payload", new_callable=AsyncMock, return_value=payload) as fetch_payload,
        patch.object(service, wait_method, new_callable=AsyncMock, side_effect=wait_after_failure) as wait,
    ):
        await asyncio.wait_for(service.publish_to_redis(), timeout=1)

    assert get_client.await_count == 2
    if pending_notification:
        random_delay.assert_called_once_with(*PUBLISHER_RETRY_RAND_SECONDS)
    else:
        random_delay.assert_not_called()
    fetch_payload.assert_awaited_once()
    redis.eval.assert_awaited_once()
    redis.pipeline.return_value.set.assert_called_once_with(ANY, ANY, ex=130)
    assert not service._publish_requested.is_set()
    assert wait.await_count >= 1


@pytest.mark.asyncio
async def test_publisher_stops_when_cancelled():
    """Stop when cancelled, keep the pending update, and leave another worker's lock alone."""
    service = DataplanePublisherService()
    service._publish_requested.set()
    with (
        patch.object(service._store, "try_acquire_lock", new_callable=AsyncMock, side_effect=asyncio.CancelledError),
        patch.object(service._store, "release_lock", new_callable=AsyncMock) as release,
    ):
        with pytest.raises(asyncio.CancelledError):
            await service._publish(60)

    release.assert_not_awaited()
    assert service._publish_requested.is_set()


def test_users_only_get_items_they_can_access():
    """Include accessible items and point each item to the correct backend."""
    def row(item_id, visibility="public", **fields):
        """Build a detached row with explicit visibility metadata."""
        return SimpleNamespace(id=item_id, visibility=visibility, owner_email="owner@example.com", team_id="team1", **fields)

    user = UserScope(id=USER1_ID, email="owner@example.com", is_admin=False, team_ids=frozenset({"team1"}))
    schema = {"type": "object"}
    data = ControlPlaneData(
        users=(user,),
        servers=VisibilityIndex.build([row("server1")]),
        gateways=VisibilityIndex.build(
            [row("gateway1", name="backend", url="https://example.com/mcp", transport="STREAMABLEHTTP", passthrough_headers=[], add_headers={}, remove_headers=[], capabilities={})]
        ),
        tools=VisibilityIndex.build([row("tool1", "team", name="exposed_tool", original_name="upstream_tool", input_schema=schema)]),
        prompts=VisibilityIndex.build([row("prompt1", "private", name="exposed_prompt", original_name="upstream_prompt")]),
        resources=VisibilityIndex.build([row("resource1", uri="resource://one")]),
        backend_items={"server1": {"gateway1": {"tools": ["tool1"], "resources": ["resource1"], "prompts": ["prompt1"]}}},
    )
    builder = UserConfigBuilder(data)
    host = builder.build_payload()[USER1_ID]["virtual_hosts"]["server1"]

    assert host["tools"] == {"exposed_tool": {"backend_name": "gateway1", "upstream_name": "upstream_tool"}}
    assert host["prompts"] == {"exposed_prompt": {"backend_name": "gateway1", "upstream_name": "upstream_prompt"}}
    assert host["resources"] == {"resource://one": {"backend_name": "gateway1", "upstream_name": "resource://one"}}
    assert host["backends"]["gateway1"]["tool_schemas"] == {"upstream_tool": schema}

    outsider = UserScope(id=USER2_ID, email="outsider@example.com", is_admin=False, team_ids=frozenset())
    outsider_host = builder.build_user_config(outsider)["virtual_hosts"]["server1"]
    assert outsider_host["tools"] == {}
    assert outsider_host["prompts"] == {}
    assert outsider_host["resources"] == host["resources"]
