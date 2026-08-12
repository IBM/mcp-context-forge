# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_reverse_proxy_discovery.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Reverse-proxy MCP discovery and catalog reconciliation tests.
"""

from collections import deque
from dataclasses import dataclass
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock
import uuid

import pytest
from pydantic import JsonValue

from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import Prompt as DbPrompt
from mcpgateway.db import Resource as DbResource
from mcpgateway.db import Server as DbServer
from mcpgateway.db import Tool as DbTool
from mcpgateway.services.gateway_service import GatewayService
from mcpgateway.services.reverse_proxy_discovery import (
    ReverseProxyDiscoveryError,
    ReverseProxyDiscoveryResult,
    ReverseProxyDiscoveryService,
)
from mcpgateway.services.reverse_proxy_protocol import (
    JsonRpcError,
    JsonRpcErrorResponse,
    JsonRpcNotification,
    JsonRpcRequest,
    JsonRpcSuccessResponse,
    ResponseMessage,
)
from mcpgateway.services.reverse_proxy_sessions import ConnectionClosedError, ConnectionId
from mcpgateway.services.server_service import ServerService


@dataclass(frozen=True)
class _RpcErrorReply:
    """Scripted JSON-RPC error reply for one request."""

    code: int
    message: str


class _ScriptedSessionManager:
    """Fake session manager recording outgoing frames and replaying scripted replies."""

    def __init__(self) -> None:
        """Initialize an empty frame log and reply script."""
        self.sent: list[JsonRpcRequest | JsonRpcNotification] = []
        self._script: deque[object] = deque()

    def script_result(self, result: JsonValue) -> None:
        """Queue a success result for the next request."""
        self._script.append(result)

    def script_error(self, code: int, message: str) -> None:
        """Queue a JSON-RPC error reply for the next request."""
        self._script.append(_RpcErrorReply(code=code, message=message))

    def script_exception(self, exc: BaseException) -> None:
        """Queue a transport-level failure for the next request."""
        self._script.append(exc)

    async def send_request(self, connection_id: ConnectionId, payload: JsonRpcRequest, timeout_seconds: float) -> ResponseMessage:
        """Record the request and replay the next scripted reply."""
        self.sent.append(payload)
        reply = self._script.popleft()
        if isinstance(reply, BaseException):
            raise reply
        if isinstance(reply, _RpcErrorReply):
            return ResponseMessage(type="response", payload=JsonRpcErrorResponse(jsonrpc="2.0", id=payload.id, error=JsonRpcError(code=reply.code, message=reply.message)))
        return ResponseMessage(type="response", payload=JsonRpcSuccessResponse(jsonrpc="2.0", id=payload.id, result=cast(JsonValue, reply)))

    async def send_notification(self, connection_id: ConnectionId, payload: JsonRpcNotification, timeout_seconds: float) -> None:
        """Record the notification without producing a reply."""
        self.sent.append(payload)

    def methods(self) -> list[str]:
        """Return the recorded frame methods in send order."""
        return [frame.method for frame in self.sent]


def _initialize_result(capabilities: dict) -> dict:
    """Build a negotiated initialize result with an arbitrary protocol version."""
    return {"protocolVersion": "2025-03-26", "capabilities": capabilities, "serverInfo": {"name": "fake-client", "version": "0.0.1"}}


@pytest.fixture
def discovery(test_db, monkeypatch):
    """Discovery service wired to spy caches and an injected server-service spy."""
    test_db.query(DbTool).delete()
    test_db.query(DbResource).delete()
    test_db.query(DbPrompt).delete()
    test_db.query(DbServer).delete()
    test_db.query(DbGateway).delete()
    test_db.commit()
    registry_cache = SimpleNamespace(invalidate_tools=AsyncMock(), invalidate_resources=AsyncMock(), invalidate_prompts=AsyncMock(), invalidate_servers=AsyncMock())
    tool_lookup_cache = SimpleNamespace(invalidate_gateway=AsyncMock())
    monkeypatch.setattr("mcpgateway.services.reverse_proxy_discovery._get_registry_cache", lambda: registry_cache)
    monkeypatch.setattr("mcpgateway.services.reverse_proxy_discovery._get_tool_lookup_cache", lambda: tool_lookup_cache)
    server_service = cast(ServerService, SimpleNamespace(_notify_server_updated=AsyncMock()))
    service = ReverseProxyDiscoveryService(gateway_service=GatewayService(), server_service=server_service)
    yield SimpleNamespace(service=service, registry_cache=registry_cache, tool_lookup_cache=tool_lookup_cache, server_service=server_service)
    test_db.query(DbTool).delete()
    test_db.query(DbResource).delete()
    test_db.query(DbPrompt).delete()
    test_db.query(DbServer).delete()
    test_db.query(DbGateway).delete()
    test_db.commit()


@pytest.fixture
def proxy_pair(test_db):
    """Persisted PROXIED gateway/server pair sharing one stable ID."""
    stable_id = uuid.uuid4().hex
    gateway = DbGateway(
        id=stable_id,
        name="discovered-proxy",
        slug="discovered-proxy",
        url=f"reverse-proxy://catalog/{stable_id}",
        transport="PROXIED",
        capabilities={},
        tags=[],
        owner_email="owner@example.com",
        visibility="public",
        created_via="reverse_proxy",
        reachable=False,
    )
    server = DbServer(id=stable_id, name="discovered-proxy", owner_email="owner@example.com", visibility="public", created_via="reverse_proxy")
    test_db.add_all([gateway, server])
    test_db.commit()
    return stable_id


async def _discover(discovery, test_db, fake: _ScriptedSessionManager, stable_id: str) -> ReverseProxyDiscoveryResult:
    """Run discovery for the persisted pair through the scripted connection."""
    gateway = test_db.get(DbGateway, stable_id)
    server = test_db.get(DbServer, stable_id)
    assert gateway is not None and server is not None
    return await discovery.service.discover_and_reconcile(test_db, fake, ConnectionId("conn-1"), gateway, server, timeout_seconds=5.0)


async def _publish(discovery, test_db, stable_id: str) -> None:
    """Publish post-commit effects explicitly, as the router does after promotion."""
    gateway = test_db.get(DbGateway, stable_id)
    server = test_db.get(DbServer, stable_id)
    assert gateway is not None and server is not None
    await discovery.service.publish_post_commit_effects(gateway, server)


@pytest.mark.asyncio
async def test_initialize_precedes_initialized_and_lists(discovery, test_db, proxy_pair):
    # Given
    fake = _ScriptedSessionManager()
    fake.script_result(_initialize_result({"tools": {}}))
    fake.script_result({"tools": [{"name": "tool-a", "inputSchema": {"type": "object"}}]})

    # When
    await _discover(discovery, test_db, fake, proxy_pair)

    # Then
    methods = fake.methods()
    assert methods[0] == "initialize"
    initialize = fake.sent[0]
    assert isinstance(initialize, JsonRpcRequest)
    assert initialize.params == {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "mcp-context-forge"}}
    initialized_at = methods.index("notifications/initialized")
    assert initialized_at == 1
    assert isinstance(fake.sent[initialized_at], JsonRpcNotification)
    list_positions = [index for index, method in enumerate(methods) if method.endswith("/list")]
    assert list_positions and all(index > initialized_at for index in list_positions)


@pytest.mark.asyncio
async def test_absent_capabilities_skip_all_list_calls(discovery, test_db, proxy_pair):
    # Given
    fake = _ScriptedSessionManager()
    fake.script_result(_initialize_result({}))

    # When
    result = await _discover(discovery, test_db, fake, proxy_pair)

    # Then
    assert fake.methods() == ["initialize", "notifications/initialized"]
    assert result.tools_added == 0 and result.tools_removed == 0
    assert result.resources_added == 0 and result.prompts_added == 0
    assert result.validation_errors == ()
    assert test_db.query(DbTool).count() == 0


@pytest.mark.asyncio
async def test_missing_tools_capability_sends_no_tools_list(discovery, test_db, proxy_pair):
    # Given
    fake = _ScriptedSessionManager()
    fake.script_result(_initialize_result({"prompts": {}}))
    fake.script_result({"prompts": [{"name": "greet", "description": "Greeting"}]})

    # When
    await _discover(discovery, test_db, fake, proxy_pair)

    # Then
    assert "tools/list" not in fake.methods()
    assert "prompts/list" in fake.methods()
    assert test_db.query(DbTool).count() == 0
    assert test_db.query(DbPrompt).count() == 1


@pytest.mark.asyncio
async def test_resources_capability_sends_resources_and_templates_lists(discovery, test_db, proxy_pair):
    # Given
    fake = _ScriptedSessionManager()
    fake.script_result(_initialize_result({"resources": {}}))
    fake.script_result({"resources": [{"uri": "file:///readme.txt", "name": "readme", "mimeType": "text/plain"}]})
    fake.script_result({"resourceTemplates": [{"uriTemplate": "file:///logs/{date}", "name": "log-template"}]})

    # When
    result = await _discover(discovery, test_db, fake, proxy_pair)

    # Then
    methods = fake.methods()
    assert "resources/list" in methods
    assert "resources/templates/list" in methods
    assert "tools/list" not in methods and "prompts/list" not in methods
    assert result.resources_added == 2
    assert test_db.query(DbResource).count() == 2


@pytest.mark.asyncio
async def test_tools_list_pagination_aggregates_all_pages(discovery, test_db, proxy_pair):
    # Given
    fake = _ScriptedSessionManager()
    fake.script_result(_initialize_result({"tools": {}}))
    fake.script_result({"tools": [{"name": "tool-a"}], "nextCursor": "cursor-2"})
    fake.script_result({"tools": [{"name": "tool-b"}]})

    # When
    result = await _discover(discovery, test_db, fake, proxy_pair)

    # Then
    list_requests = [frame for frame in fake.sent if frame.method == "tools/list"]
    assert len(list_requests) == 2
    assert list_requests[0].params == {}
    assert list_requests[1].params == {"cursor": "cursor-2"}
    assert {row.original_name for row in test_db.query(DbTool)} == {"tool-a", "tool-b"}
    assert result.tools_added == 2


@pytest.mark.asyncio
async def test_pagination_beyond_page_bound_raises(discovery, test_db, proxy_pair):
    # Given
    fake = _ScriptedSessionManager()
    fake.script_result(_initialize_result({"tools": {}}))
    for index in range(101):
        fake.script_result({"tools": [{"name": f"tool-{index}"}], "nextCursor": f"cursor-{index + 1}"})

    # When / Then
    with pytest.raises(ReverseProxyDiscoveryError, match="pages"):
        await _discover(discovery, test_db, fake, proxy_pair)
    assert test_db.query(DbTool).count() == 0


@pytest.mark.asyncio
async def test_tools_list_non_object_item_raises_and_leaves_catalog_unchanged(discovery, test_db, proxy_pair):
    # Given
    fake = _ScriptedSessionManager()
    fake.script_result(_initialize_result({"tools": {}}))
    fake.script_result({"tools": [{"name": "tool-a"}, None]})

    # When / Then
    with pytest.raises(ReverseProxyDiscoveryError, match="non-object item"):
        await _discover(discovery, test_db, fake, proxy_pair)
    assert test_db.query(DbTool).count() == 0


@pytest.mark.asyncio
async def test_resources_list_non_object_item_raises(discovery, test_db, proxy_pair):
    # Given
    fake = _ScriptedSessionManager()
    fake.script_result(_initialize_result({"resources": {}}))
    fake.script_result({"resources": [None]})

    # When / Then
    with pytest.raises(ReverseProxyDiscoveryError, match="non-object item"):
        await _discover(discovery, test_db, fake, proxy_pair)


@pytest.mark.asyncio
async def test_non_string_next_cursor_raises(discovery, test_db, proxy_pair):
    # Given
    fake = _ScriptedSessionManager()
    fake.script_result(_initialize_result({"tools": {}}))
    fake.script_result({"tools": [{"name": "tool-a"}], "nextCursor": 123})

    # When / Then
    with pytest.raises(ReverseProxyDiscoveryError, match="non-string nextCursor"):
        await _discover(discovery, test_db, fake, proxy_pair)
    assert test_db.query(DbTool).count() == 0


@pytest.mark.asyncio
async def test_missing_tools_member_raises_and_leaves_catalog_unchanged(discovery, test_db, proxy_pair):
    # Given: a populated tools catalog from a first successful pass
    first = _ScriptedSessionManager()
    first.script_result(_initialize_result({"tools": {}}))
    first.script_result({"tools": [{"name": "tool-a"}, {"name": "tool-b"}]})
    await _discover(discovery, test_db, first, proxy_pair)
    second = _ScriptedSessionManager()
    second.script_result(_initialize_result({"tools": {}}))
    second.script_result({})

    # When / Then: a result with no "tools" member is not a valid empty page, so nothing is pruned
    with pytest.raises(ReverseProxyDiscoveryError, match="tools/list returned a result missing required member 'tools'"):
        await _discover(discovery, test_db, second, proxy_pair)
    test_db.expire_all()
    assert {row.original_name for row in test_db.query(DbTool)} == {"tool-a", "tool-b"}


@pytest.mark.asyncio
async def test_missing_resources_member_raises_and_leaves_catalog_unchanged(discovery, test_db, proxy_pair):
    # Given: a populated resources catalog from a first successful pass
    first = _ScriptedSessionManager()
    first.script_result(_initialize_result({"resources": {}}))
    first.script_result({"resources": [{"uri": "file:///readme.txt", "name": "readme"}]})
    first.script_result({"resourceTemplates": []})
    await _discover(discovery, test_db, first, proxy_pair)
    second = _ScriptedSessionManager()
    second.script_result(_initialize_result({"resources": {}}))
    second.script_result({})

    # When / Then: a result with no "resources" member is not a valid empty page, so nothing is pruned
    with pytest.raises(ReverseProxyDiscoveryError, match="resources/list returned a result missing required member 'resources'"):
        await _discover(discovery, test_db, second, proxy_pair)
    test_db.expire_all()
    assert {row.uri for row in test_db.query(DbResource)} == {"file:///readme.txt"}


@pytest.mark.asyncio
async def test_missing_prompts_member_raises_and_leaves_catalog_unchanged(discovery, test_db, proxy_pair):
    # Given: a populated prompts catalog from a first successful pass
    first = _ScriptedSessionManager()
    first.script_result(_initialize_result({"prompts": {}}))
    first.script_result({"prompts": [{"name": "greet"}]})
    await _discover(discovery, test_db, first, proxy_pair)
    second = _ScriptedSessionManager()
    second.script_result(_initialize_result({"prompts": {}}))
    second.script_result({})

    # When / Then: a result with no "prompts" member is not a valid empty page, so nothing is pruned
    with pytest.raises(ReverseProxyDiscoveryError, match="prompts/list returned a result missing required member 'prompts'"):
        await _discover(discovery, test_db, second, proxy_pair)
    test_db.expire_all()
    assert {row.original_name for row in test_db.query(DbPrompt)} == {"greet"}


@pytest.mark.asyncio
async def test_discovered_tools_land_with_stable_gateway_and_reverse_proxy_origin(discovery, test_db, proxy_pair):
    # Given
    fake = _ScriptedSessionManager()
    fake.script_result(_initialize_result({"tools": {}}))
    fake.script_result({"tools": [{"name": "tool-a", "description": "Upstream tool"}]})

    # When
    result = await _discover(discovery, test_db, fake, proxy_pair)

    # Then
    rows = test_db.query(DbTool).all()
    assert len(rows) == 1
    assert rows[0].gateway_id == proxy_pair
    assert rows[0].original_name == "tool-a"
    assert rows[0].created_via == "reverse_proxy"
    assert result.tools_added == 1 and result.tools_removed == 0
    assert result.capabilities == {"tools": {}}


@pytest.mark.asyncio
async def test_reconcile_prunes_only_reverse_proxy_rows(discovery, test_db, proxy_pair):
    # Given
    gateway = test_db.get(DbGateway, proxy_pair)
    assert gateway is not None
    decoy = DbTool(
        original_name="decoy-tool",
        name="decoy-tool",
        custom_name="decoy-tool",
        custom_name_slug="decoy-tool",
        url=gateway.url,
        input_schema={},
        gateway_id=gateway.id,
        owner_email="owner@example.com",
        visibility="public",
        created_via="api",
    )
    test_db.add(decoy)
    test_db.commit()
    first = _ScriptedSessionManager()
    first.script_result(_initialize_result({"tools": {}}))
    first.script_result({"tools": [{"name": "tool-a"}, {"name": "tool-b"}]})
    await _discover(discovery, test_db, first, proxy_pair)
    second = _ScriptedSessionManager()
    second.script_result(_initialize_result({"tools": {}}))
    second.script_result({"tools": [{"name": "tool-a"}]})

    # When
    result = await _discover(discovery, test_db, second, proxy_pair)

    # Then
    test_db.expire_all()
    rows = {row.original_name: row.created_via for row in test_db.query(DbTool)}
    assert rows == {"tool-a": "reverse_proxy", "decoy-tool": "api"}
    assert result.tools_removed == 1


@pytest.mark.asyncio
async def test_server_association_mirrors_reconciled_gateway_sets(discovery, test_db, proxy_pair):
    # Given
    fake = _ScriptedSessionManager()
    fake.script_result(_initialize_result({"tools": {}, "resources": {}, "prompts": {}}))
    fake.script_result({"tools": [{"name": "tool-a"}]})
    fake.script_result({"resources": [{"uri": "file:///readme.txt", "name": "readme"}]})
    fake.script_result({"resourceTemplates": []})
    fake.script_result({"prompts": [{"name": "greet"}]})

    # When
    await _discover(discovery, test_db, fake, proxy_pair)

    # Then
    test_db.expire_all()
    gateway = test_db.get(DbGateway, proxy_pair)
    server = test_db.get(DbServer, proxy_pair)
    assert gateway is not None and server is not None
    assert {tool.id for tool in server.tools} == {tool.id for tool in gateway.tools}
    assert {resource.id for resource in server.resources} == {resource.id for resource in gateway.resources}
    assert {prompt.id for prompt in server.prompts} == {prompt.id for prompt in gateway.prompts}
    assert len(server.tools) == 1 and len(server.resources) == 1 and len(server.prompts) == 1


@pytest.mark.asyncio
async def test_gateway_row_capabilities_last_seen_and_reachable_updated(discovery, test_db, proxy_pair):
    # Given
    capabilities = {"tools": {"listChanged": True}}
    fake = _ScriptedSessionManager()
    fake.script_result(_initialize_result(capabilities))
    fake.script_result({"tools": [{"name": "tool-a"}]})

    # When
    await _discover(discovery, test_db, fake, proxy_pair)

    # Then
    test_db.expire_all()
    gateway = test_db.get(DbGateway, proxy_pair)
    assert gateway is not None
    assert gateway.capabilities == capabilities
    assert gateway.reachable is True
    assert gateway.last_seen is not None


@pytest.mark.asyncio
async def test_malformed_tool_skipped_and_reported_in_validation_errors(discovery, test_db, proxy_pair):
    # Given
    fake = _ScriptedSessionManager()
    fake.script_result(_initialize_result({"tools": {}}))
    fake.script_result({"tools": [{"name": "good-tool"}, {"description": "missing name"}]})

    # When
    result = await _discover(discovery, test_db, fake, proxy_pair)

    # Then
    assert len(result.validation_errors) == 1
    assert {row.original_name for row in test_db.query(DbTool)} == {"good-tool"}
    assert result.tools_added == 1


@pytest.mark.asyncio
async def test_valid_pages_still_aggregate_after_list_hardening(discovery, test_db, proxy_pair):
    # Given
    fake = _ScriptedSessionManager()
    fake.script_result(_initialize_result({"tools": {}}))
    fake.script_result({"tools": [{"name": "tool-a"}], "nextCursor": "cursor-2"})
    fake.script_result({"tools": [{"name": "tool-b"}]})

    # When
    result = await _discover(discovery, test_db, fake, proxy_pair)

    # Then
    assert {row.original_name for row in test_db.query(DbTool)} == {"tool-a", "tool-b"}
    assert result.tools_added == 2


@pytest.mark.asyncio
async def test_object_but_invalid_tool_still_reports_validation_error_not_raised(discovery, test_db, proxy_pair):
    # Given
    fake = _ScriptedSessionManager()
    fake.script_result(_initialize_result({"tools": {}}))
    fake.script_result({"tools": [{"name": "tool-a"}, {"description": "missing name"}]})

    # When
    result = await _discover(discovery, test_db, fake, proxy_pair)

    # Then
    assert {row.original_name for row in test_db.query(DbTool)} == {"tool-a"}
    assert result.tools_added == 1
    assert len(result.validation_errors) == 1


@pytest.mark.asyncio
async def test_all_malformed_tools_raise(discovery, test_db, proxy_pair):
    # Given
    fake = _ScriptedSessionManager()
    fake.script_result(_initialize_result({"tools": {}}))
    fake.script_result({"tools": [{"description": "missing name"}, {"description": "also missing"}]})

    # When / Then
    with pytest.raises(ReverseProxyDiscoveryError):
        await _discover(discovery, test_db, fake, proxy_pair)
    assert test_db.query(DbTool).count() == 0


@pytest.mark.asyncio
async def test_initialize_timeout_raises(discovery, test_db, proxy_pair):
    # Given
    fake = _ScriptedSessionManager()
    fake.script_exception(TimeoutError("initialize timed out"))

    # When / Then
    with pytest.raises(ReverseProxyDiscoveryError, match="timed out"):
        await _discover(discovery, test_db, fake, proxy_pair)
    test_db.expire_all()
    gateway = test_db.get(DbGateway, proxy_pair)
    assert gateway is not None and gateway.capabilities == {}


@pytest.mark.asyncio
async def test_connection_closed_mid_discovery_raises_and_commits_nothing(discovery, test_db, proxy_pair):
    # Given
    fake = _ScriptedSessionManager()
    fake.script_result(_initialize_result({"tools": {}}))
    fake.script_exception(ConnectionClosedError(ConnectionId("conn-1")))

    # When / Then
    with pytest.raises(ReverseProxyDiscoveryError):
        await _discover(discovery, test_db, fake, proxy_pair)
    test_db.expire_all()
    assert test_db.query(DbTool).count() == 0
    gateway = test_db.get(DbGateway, proxy_pair)
    assert gateway is not None and gateway.capabilities == {}


@pytest.mark.asyncio
async def test_initialize_error_response_raises(discovery, test_db, proxy_pair):
    # Given
    fake = _ScriptedSessionManager()
    fake.script_error(-32600, "unsupported protocol version")

    # When / Then
    with pytest.raises(ReverseProxyDiscoveryError, match="unsupported protocol version"):
        await _discover(discovery, test_db, fake, proxy_pair)
    assert test_db.query(DbTool).count() == 0


@pytest.mark.asyncio
async def test_post_commit_cache_invalidations_and_server_notification(discovery, test_db, proxy_pair):
    # Given
    fake = _ScriptedSessionManager()
    fake.script_result(_initialize_result({"tools": {}}))
    fake.script_result({"tools": [{"name": "tool-a"}]})

    # When
    await _discover(discovery, test_db, fake, proxy_pair)
    await _publish(discovery, test_db, proxy_pair)

    # Then
    discovery.registry_cache.invalidate_tools.assert_awaited_once()
    discovery.registry_cache.invalidate_servers.assert_awaited_once()
    discovery.tool_lookup_cache.invalidate_gateway.assert_awaited_once_with(proxy_pair)
    discovery.server_service._notify_server_updated.assert_awaited_once()


def test_init_uses_process_singleton_without_constructing_server_service(monkeypatch):
    # Given: the discovery module's ServerService import site and the process-level lazy singleton
    mock_server_service_class = MagicMock()
    singleton = cast(ServerService, SimpleNamespace(_notify_server_updated=AsyncMock()))
    monkeypatch.setattr("mcpgateway.services.reverse_proxy_discovery.ServerService", mock_server_service_class)
    monkeypatch.setattr("mcpgateway.services.server_service.server_service", singleton, raising=False)

    # When
    service = ReverseProxyDiscoveryService()

    # Then: no fresh ServerService is constructed; the process singleton is used
    mock_server_service_class.assert_not_called()
    assert service._server_service is singleton


@pytest.mark.asyncio
async def test_metadata_only_rediscovery_still_invalidates_tools_cache(discovery, test_db, proxy_pair):
    # Given: an existing tool whose description changes between passes, with no adds or removes
    first = _ScriptedSessionManager()
    first.script_result(_initialize_result({"tools": {}}))
    first.script_result({"tools": [{"name": "tool-a", "description": "v1"}]})
    await _discover(discovery, test_db, first, proxy_pair)
    discovery.registry_cache.invalidate_tools.reset_mock()
    second = _ScriptedSessionManager()
    second.script_result(_initialize_result({"tools": {}}))
    second.script_result({"tools": [{"name": "tool-a", "description": "v2"}]})

    # When
    result = await _discover(discovery, test_db, second, proxy_pair)
    await _publish(discovery, test_db, proxy_pair)
    # Then: the in-place metadata update still invalidates the tools catalog cache
    assert result.tools_added == 0 and result.tools_removed == 0
    test_db.expire_all()
    row = test_db.query(DbTool).filter_by(original_name="tool-a").one()
    assert row.original_description == "v2"
    discovery.registry_cache.invalidate_tools.assert_awaited_once()


@pytest.mark.asyncio
async def test_zero_delta_rediscovery_invalidates_all_catalog_caches(discovery, test_db, proxy_pair):
    # Given: a fully populated catalog rediscovered with an identical payload
    first = _ScriptedSessionManager()
    first.script_result(_initialize_result({"tools": {}, "resources": {}, "prompts": {}}))
    first.script_result({"tools": [{"name": "tool-a"}]})
    first.script_result({"resources": [{"uri": "file:///readme.txt", "name": "readme"}]})
    first.script_result({"resourceTemplates": []})
    first.script_result({"prompts": [{"name": "greet"}]})
    await _discover(discovery, test_db, first, proxy_pair)
    discovery.registry_cache.invalidate_tools.reset_mock()
    discovery.registry_cache.invalidate_resources.reset_mock()
    discovery.registry_cache.invalidate_prompts.reset_mock()
    discovery.registry_cache.invalidate_servers.reset_mock()
    second = _ScriptedSessionManager()
    second.script_result(_initialize_result({"tools": {}, "resources": {}, "prompts": {}}))
    second.script_result({"tools": [{"name": "tool-a"}]})
    second.script_result({"resources": [{"uri": "file:///readme.txt", "name": "readme"}]})
    second.script_result({"resourceTemplates": []})
    second.script_result({"prompts": [{"name": "greet"}]})

    # When
    result = await _discover(discovery, test_db, second, proxy_pair)
    await _publish(discovery, test_db, proxy_pair)
    # Then: zero delta still re-publishes the full catalog state to every registry cache
    assert result.tools_added == 0 and result.tools_removed == 0
    assert result.resources_added == 0 and result.resources_removed == 0
    assert result.prompts_added == 0 and result.prompts_removed == 0
    discovery.registry_cache.invalidate_tools.assert_awaited_once()
    discovery.registry_cache.invalidate_resources.assert_awaited_once()
    discovery.registry_cache.invalidate_prompts.assert_awaited_once()
    discovery.registry_cache.invalidate_servers.assert_awaited_once()


@pytest.mark.asyncio
async def test_discover_and_reconcile_alone_performs_no_post_commit_effects(discovery, test_db, proxy_pair):
    # Given
    fake = _ScriptedSessionManager()
    fake.script_result(_initialize_result({"tools": {}}))
    fake.script_result({"tools": [{"name": "tool-a"}]})

    # When: discovery runs without the caller's explicit post-promotion publish
    result = await _discover(discovery, test_db, fake, proxy_pair)

    # Then: the catalog is committed but nothing is published yet
    assert result.tools_added == 1
    assert test_db.query(DbTool).count() == 1
    discovery.registry_cache.invalidate_tools.assert_not_awaited()
    discovery.registry_cache.invalidate_resources.assert_not_awaited()
    discovery.registry_cache.invalidate_prompts.assert_not_awaited()
    discovery.registry_cache.invalidate_servers.assert_not_awaited()
    discovery.tool_lookup_cache.invalidate_gateway.assert_not_awaited()
    discovery.server_service._notify_server_updated.assert_not_awaited()
