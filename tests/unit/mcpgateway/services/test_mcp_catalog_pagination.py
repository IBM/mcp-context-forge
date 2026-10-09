# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_mcp_catalog_pagination.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Verify complete MCP catalog traversal and authorization-bound continuation.
"""

# Standard
import base64
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

# Third-Party
from fakeredis.aioredis import FakeRedis
import mcp_types as types
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import Base, Prompt, Resource, Server, Tool
from mcpgateway.services import mcp_catalog_service as catalog
from mcpgateway.transports import streamablehttp_transport as transport
from mcpgateway.utils import mcp_cursor
from mcpgateway.utils import mcp_catalog_snapshot as snapshots
from mcpgateway.validation.jsonrpc import JSONRPCError

METHODS = [("tools/list", "tools", Tool), ("resources/list", "resources", Resource), ("prompts/list", "prompts", Prompt), ("resources/templates/list", "resourceTemplates", Resource)]


@pytest.fixture
def snapshot_redis(monkeypatch):
    """Supply fake Redis with deterministic memory information for Lua admission."""
    # FakeRedis does not implement INFO; integration tests use real memory information.
    for name in ("_ADMIT", "_PUBLISH"):
        script = getattr(snapshots, name).replace("redis.call('INFO', 'memory')", "'\\r\\nused_memory:0\\r\\nmaxmemory:0\\r\\n'")
        monkeypatch.setattr(snapshots, name, script)
    return FakeRedis()


@pytest.fixture
def catalog_db(monkeypatch):
    """Create an isolated catalog database with a small page size."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(settings, "mcp_list_page_size", 3)
    monkeypatch.setattr("mcpgateway.services.base_service.is_user_admin", lambda _db, email: email == "admin@example.com")
    with Session(engine) as db:
        yield db
    engine.dispose()


def _row(method, index, **kwargs):
    """Build a catalog item with a deterministic ID."""
    name = f"item-{index:03d}"
    common = {"id": f"{index:032x}", "name": name, "visibility": "public", **kwargs}
    if method == "tools/list":
        return Tool(**common, original_name=name, custom_name=name, custom_name_slug=name, input_schema={"type": "object", "properties": {}})
    if method == "prompts/list":
        return Prompt(**common, original_name=name, custom_name=name, custom_name_slug=name, template="Example", argument_schema={"type": "object", "properties": {}})
    return Resource(**common, uri=f"test://{name}", uri_template=f"test://{name}/{{id}}" if method == "resources/templates/list" else None)


async def _traverse(db, method, key, **kwargs):
    """Collect pages and reject a non-advancing server cursor."""
    cursor = None
    seen = set()
    result = []
    while True:
        page = await catalog.list_catalog_page(db, method, cursor=cursor, **kwargs)
        assert len(page[key]) <= settings.mcp_list_page_size
        result.extend(page[key])
        cursor = page.get("nextCursor")
        if cursor is None:
            return result
        assert cursor not in seen
        seen.add(cursor)


@pytest.mark.asyncio
@pytest.mark.parametrize("method,key,model", METHODS)
@pytest.mark.parametrize("count", [0, 1, 2, 3, 4, 6, 7, 10])
@pytest.mark.parametrize("server_scoped", [False, True])
async def test_complete_catalog_pages(catalog_db, method, key, model, count, server_scoped):
    """Return every item exactly once across global and server catalogs."""
    rows = [_row(method, index) for index in reversed(range(count))]
    catalog_db.add_all(rows)
    server_id = None
    if server_scoped:
        server = Server(id="server-a", name="Server A")
        setattr(server, "tools" if model is Tool else "prompts" if model is Prompt else "resources", rows)
        catalog_db.add(server)
        server_id = server.id
    catalog_db.commit()
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().startswith("SELECT") and f"FROM {model.__tablename__}" in statement:
            statements.append(statement)

    event.listen(catalog_db.get_bind(), "before_cursor_execute", capture)
    result = await _traverse(catalog_db, method, key, server_id=server_id, user_email="user@example.com", token_teams=[])
    assert [item["name"] for item in result] == [f"item-{index:03d}" for index in range(count)]
    assert statements and all("LIMIT" in statement for statement in statements)


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [None, 0, 4096])
@pytest.mark.parametrize("server_scoped", [False, True])
async def test_resource_serialization_preserves_size(catalog_db, size, server_scoped):
    """Preserve resource descriptors across catalog and SDK serialization."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import _to_mcp_resource

    row = _row("resources/list", 0, size=size, title="Resource title", description="Resource description", mime_type="text/plain")
    catalog_db.add(row)
    server_id = None
    if server_scoped:
        server = Server(id="size-server", name="Resource sizes", resources=[row])
        catalog_db.add(server)
        server_id = server.id
    catalog_db.commit()
    page = await catalog.list_catalog_page(catalog_db, "resources/list", server_id=server_id, user_email="admin@example.com", token_teams=None)
    expected = {"uri": row.uri, "name": row.name, "title": row.title, "description": row.description, "mimeType": row.mime_type}
    if size is not None:
        expected["size"] = size
    assert page["resources"] == [expected]
    assert _to_mcp_resource(row).model_dump(by_alias=True, exclude_none=True, mode="json") == expected
    assert types.ListResourcesResult.model_validate(page).model_dump(by_alias=True, exclude_none=True, mode="json")["resources"] == [expected]


@pytest.mark.asyncio
@pytest.mark.parametrize("method,key,_model", METHODS)
@pytest.mark.parametrize(
    "teams,email,expected", [([], "user@example.com", [0, 3]), ([], "admin@example.com", [0, 3]), (["t1"], "user@example.com", [0, 1, 2, 3]), (None, "admin@example.com", [0, 1, 3])]
)
async def test_visibility_applies_to_every_page(catalog_db, method, key, _model, teams, email, expected):
    """Preserve public, team, owner, and administrator visibility on each page."""
    catalog_db.add_all(
        [
            _row(method, 0),
            _row(method, 1, visibility="team", team_id="t1"),
            _row(method, 2, visibility="private", owner_email="user@example.com"),
            _row(method, 3),
            _row(method, 4, enabled=False),
            _row(method, 5, visibility="private", owner_email="other@example.com"),
        ]
    )
    catalog_db.commit()
    result = await _traverse(catalog_db, method, key, user_email=email, token_teams=teams)
    assert [item["name"] for item in result] == [f"item-{index:03d}" for index in expected]


@pytest.mark.asyncio
async def test_cursor_replay_and_scope_changes(catalog_db):
    """Allow retries and reject continuation across authorization boundaries."""
    catalog_db.add_all(_row("tools/list", index) for index in range(7))
    catalog_db.commit()
    args = {"user_email": "user@example.com", "token_teams": ["t1"], "request_headers": {"mcp-session-id": "session-a"}}
    first = await catalog.list_catalog_page(catalog_db, "tools/list", **args)
    cursor = first["nextCursor"]
    second = await catalog.list_catalog_page(catalog_db, "tools/list", cursor=cursor, **args)
    repeated = await catalog.list_catalog_page(catalog_db, "tools/list", cursor=cursor, **args)
    assert repeated["tools"] == second["tools"]
    for changes in [{"user_email": "other@example.com"}, {"token_teams": []}, {"server_id": "other"}, {"request_headers": {"mcp-session-id": "session-b"}}]:
        with pytest.raises(JSONRPCError) as exc:
            await catalog.list_catalog_page(catalog_db, "tools/list", cursor=cursor, **(args | changes))
        assert exc.value.code == -32602
    with pytest.raises(JSONRPCError) as exc:
        await catalog.list_catalog_page(catalog_db, "prompts/list", cursor=cursor, **args)
    assert exc.value.code == -32602


@pytest.mark.parametrize("cursor", ["", "invalid", "%%%", [], {}, 1, "a" * 8193, base64.urlsafe_b64encode(b"short").decode()])
def test_invalid_cursors(cursor):
    """Reject invalid cursor encodings with the protocol error."""
    with pytest.raises(JSONRPCError) as exc:
        mcp_cursor.decode_cursor(cursor, "scope")
    assert exc.value.code == -32602


def test_expired_and_tampered_cursors(monkeypatch):
    """Reject expired and modified authenticated cursor payloads."""
    cursor = mcp_cursor.encode_cursor("scope", 100, {"after": "a"})
    monkeypatch.setattr(mcp_cursor.time, "time", lambda: 99)
    assert mcp_cursor.decode_cursor(cursor, "scope")["after"] == "a"
    with pytest.raises(JSONRPCError):
        mcp_cursor.decode_cursor(cursor[:-3] + "ABC", "scope")
    monkeypatch.setattr(mcp_cursor.time, "time", lambda: 100)
    with pytest.raises(JSONRPCError):
        mcp_cursor.decode_cursor(cursor, "scope")


@pytest.mark.asyncio
async def test_proxy_collection_tracks_upstream_pages():
    """Forward upstream cursors and reject repeated cursors or duplicate items."""

    def tool(name):
        """Build one upstream tool descriptor."""
        return types.Tool(name=name, input_schema={"type": "object"})

    client = SimpleNamespace(list_tools=AsyncMock(side_effect=[types.ListToolsResult(tools=[tool("a")], nextCursor="next"), types.ListToolsResult(tools=[tool("b")])]))
    result = await catalog.collect_proxy_catalog(client, "tools/list", None)
    assert [item.name for item in result] == ["a", "b"]
    assert client.list_tools.call_args_list[1].kwargs["cursor"] == "next"
    client.list_tools.side_effect = [types.ListToolsResult(tools=[], nextCursor="next"), types.ListToolsResult(tools=[], nextCursor="next")]
    with pytest.raises(JSONRPCError):
        await catalog.collect_proxy_catalog(client, "tools/list", None)
    client.list_tools.side_effect = [types.ListToolsResult(tools=[tool("a")], nextCursor="next"), types.ListToolsResult(tools=[tool("a")])]
    with pytest.raises(JSONRPCError):
        await catalog.collect_proxy_catalog(client, "tools/list", None)


@pytest.mark.asyncio
async def test_proxy_snapshot_retry_expiry_and_storage(catalog_db, monkeypatch, snapshot_redis):
    """Share proxy pages through Redis and reject missing snapshots."""
    redis = snapshot_redis
    monkeypatch.setattr(catalog, "get_redis_client", AsyncMock(return_value=redis))
    monkeypatch.setattr(transport, "_build_proxy_list_headers", lambda *_: {})
    proxy = AsyncMock(return_value=[types.Tool(name=f"tool-{index}", input_schema={"type": "object"}) for index in range(7)])
    monkeypatch.setattr(transport, "_proxy_list_tools_to_gateway", proxy)
    gateway = SimpleNamespace(id="gateway", url="http://peer/mcp", updated_at="version-a")
    first = await catalog._proxy_page(gateway, "tools/list", None, "scope", {}, None)
    second = await catalog._proxy_page(gateway, "tools/list", first["nextCursor"], "scope", {}, None)
    assert [tool["name"] for tool in second["tools"]] == ["tool-3", "tool-4", "tool-5"]
    retry = await catalog._proxy_page(gateway, "tools/list", first["nextCursor"], "scope", {}, None)
    assert retry["tools"] == second["tools"]
    assert proxy.await_count == 1
    with pytest.raises(JSONRPCError):
        await catalog._proxy_page(gateway, "tools/list", first["nextCursor"], "other-scope", {}, None)
    await redis.flushall()
    with pytest.raises(JSONRPCError) as exc:
        await catalog._proxy_page(gateway, "tools/list", first["nextCursor"], "scope", {}, None)
    assert exc.value.code == -32602
    monkeypatch.setattr(catalog, "get_redis_client", AsyncMock(return_value=None))
    with pytest.raises(JSONRPCError) as exc:
        await catalog._proxy_page(gateway, "tools/list", None, "scope", {}, None)
    assert exc.value.code == -32000
    await redis.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("method,key,_model", METHODS)
async def test_streamable_adapter_preserves_cursor(catalog_db, monkeypatch, method, key, _model):
    """Traverse the registered Streamable HTTP adapter with real database pages."""
    catalog_db.add_all(_row(method, index) for index in range(7))
    catalog_db.commit()

    @asynccontextmanager
    async def database():
        yield catalog_db

    monkeypatch.setattr(transport, "get_db", database)
    monkeypatch.setattr(transport, "_get_request_context_or_default", AsyncMock(return_value=(None, {}, {"email": "user@example.com", "teams": [], "is_authenticated": True})))
    adapter_name = "resource_templates" if method == "resources/templates/list" else method.removesuffix("/list")
    adapter = getattr(transport, f"_adapt_list_{adapter_name}")
    first = await adapter(None, types.PaginatedRequestParams())
    assert len(first.model_dump(by_alias=True)[key]) == 3
    second = await adapter(None, types.PaginatedRequestParams(cursor=first.next_cursor))
    assert [item["name"] for item in second.model_dump(by_alias=True)[key]] == ["item-003", "item-004", "item-005"]


def test_cursor_encoding_vector(monkeypatch):
    """Preserve the authenticated cursor format across Python workers."""
    # Third-Party
    from pydantic import SecretStr

    # First-Party
    from mcpgateway.utils import mcp_cursor

    monkeypatch.setattr(settings, "auth_encryption_secret", SecretStr("catalog-interoperability-test-passphrase"))
    monkeypatch.setattr(mcp_cursor.os, "urandom", lambda _length: bytes(range(12)))
    scope = mcp_cursor.scope_fingerprint("tools/list", "server-a", "user@example.com", ["t2", "t1", "t1"], "session-a")
    assert scope == "67905f44c8b1d8fb644f39ee8240af91fffe444f0d728060eef93d39d5b50379"  # pragma: allowlist secret
    cursor = mcp_cursor.encode_cursor(scope, 4102444800, {"after": "00000000000000000000000000000003"})
    assert (
        cursor
        == "AAECAwQFBgcICQoLutexFwpyh0lu8oBYycZkvhCS1wszGPqr9p73_K_qbTARxdzIGpgaKknqjMRY2rHRqD86Y41Q0pvzjjckJtSviBTDgatoeqCo7sIVVVOykEufWO1PwRNnUzBkUWqo2fAp2BAhl-yTKcM_1W3XrL4c9RgT2zj-IjEKhCCteeCvkRmWMAwlR3zZJSnnWW-lXDGYVZaQs0u2WTU10ph9yFKFxmmp"  # pragma: allowlist secret
    )
    assert mcp_cursor.decode_cursor(cursor, scope)["after"] == "00000000000000000000000000000003"


@pytest.mark.asyncio
@pytest.mark.parametrize("method,_key,_model", METHODS)
async def test_adapter_denies_insufficient_permissions(monkeypatch, method, _key, _model):
    """Reject excluded permissions before the catalog service runs."""
    monkeypatch.setattr(transport, "_get_request_context_or_default", AsyncMock(return_value=(None, {}, {"email": "user@example.com", "is_authenticated": True})))
    monkeypatch.setattr(transport, "_should_enforce_streamable_rbac", lambda _context: True)
    monkeypatch.setattr(transport, "_check_scoped_permission", lambda _context, _permission: False)
    service = AsyncMock()
    monkeypatch.setattr(transport, "list_catalog_page", service)
    with pytest.raises(PermissionError):
        await transport._list_catalog_page(method, types.PaginatedRequestParams(cursor="some-cursor"))
    service.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["tools/list", "resources/list"])
@pytest.mark.parametrize("enabled,allowed", [(False, True), (True, False)])
async def test_proxy_denies_disabled_feature_and_wrong_scope(catalog_db, monkeypatch, method, enabled, allowed):
    """Reject disabled proxy routing and inaccessible gateways before snapshot access."""
    gateway = SimpleNamespace(gateway_mode="direct_proxy")
    monkeypatch.setattr(catalog_db, "get", lambda _model, _identity: gateway)
    monkeypatch.setattr(settings, "mcpgateway_direct_proxy_enabled", enabled)
    monkeypatch.setattr(catalog, "check_gateway_access", AsyncMock(return_value=allowed))
    proxy = AsyncMock()
    monkeypatch.setattr(catalog, "_proxy_page", proxy)
    with pytest.raises(JSONRPCError) as error:
        await catalog.list_catalog_page(
            catalog_db, method, cursor="some-cursor", server_id="server-a", user_email="outsider@example.com", token_teams=[], request_headers={"X-Context-Forge-Gateway-Id": "gateway-a"}
        )
    assert error.value.code == -32003
    proxy.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("method,key,_model", METHODS)
async def test_visibility_revocation_applies_before_continuation(catalog_db, method, key, _model):
    """Remove revoked and disabled rows from subsequent pages."""
    rows = [_row(method, index) for index in range(7)]
    catalog_db.add_all(rows)
    catalog_db.commit()
    first = await catalog.list_catalog_page(catalog_db, method, user_email="user@example.com", token_teams=[])
    rows[3].visibility = "private"
    rows[3].owner_email = "other@example.com"
    rows[4].enabled = False
    catalog_db.commit()
    rest = await catalog.list_catalog_page(catalog_db, method, cursor=first["nextCursor"], user_email="user@example.com", token_teams=[])
    assert [item["name"] for item in rest[key]] == ["item-005", "item-006"]
    assert "nextCursor" not in rest


@pytest.mark.asyncio
async def test_proxy_collection_rejects_byte_limit(monkeypatch):
    """Reject oversized upstream catalogs without returning partial items."""
    monkeypatch.setattr(settings, "mcp_proxy_list_max_snapshot_bytes", 1)
    client = SimpleNamespace(list_tools=AsyncMock(return_value=types.ListToolsResult(tools=[types.Tool(name="tool-a", input_schema={"type": "object"})])))
    with pytest.raises(JSONRPCError) as error:
        await catalog.collect_proxy_catalog(client, "tools/list", None)
    assert error.value.code == -32000


@pytest.mark.asyncio
async def test_adapter_reports_invalid_cursor_and_preserves_oauth_requirement(catalog_db, monkeypatch):
    """Reject invalid continuation and unauthenticated OAuth-protected catalogs."""
    # Third-Party
    from mcp import MCPError

    @asynccontextmanager
    async def database():
        yield catalog_db

    monkeypatch.setattr(transport, "get_db", database)
    monkeypatch.setattr(transport, "_get_request_context_or_default", AsyncMock(return_value=(None, {}, {"email": "user@example.com", "teams": [], "is_authenticated": True})))
    with pytest.raises(MCPError) as error:
        await transport._list_catalog_page("tools/list", types.PaginatedRequestParams(cursor="invalid"))
    assert error.value.code == -32602
    monkeypatch.setattr(settings, "mcp_require_auth", False)
    enforcement = AsyncMock(side_effect=PermissionError("OAuth authentication required"))
    monkeypatch.setattr(transport, "_check_server_oauth_enforcement", enforcement)
    with pytest.raises(PermissionError, match="OAuth authentication required"):
        await transport._list_catalog_page("tools/list", None)
    enforcement.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["tools/list", "resources/list"])
@pytest.mark.parametrize("failure", [JSONRPCError(-32000, "Repeated upstream cursor"), TimeoutError("upstream timeout")])
async def test_proxy_helpers_fail_without_partial_results(monkeypatch, method, failure):
    """Preserve protocol failures and translate upstream timeouts."""

    @asynccontextmanager
    async def upstream(**_kwargs):
        yield SimpleNamespace()

    monkeypatch.setattr(transport, "mcp_proxy_client", upstream)
    monkeypatch.setattr(transport, "_build_proxy_list_headers", lambda *_: {})
    monkeypatch.setattr(transport, "collect_proxy_catalog", AsyncMock(side_effect=failure))
    helper = transport._proxy_list_tools_to_gateway if method == "tools/list" else transport._proxy_list_resources_to_gateway
    with pytest.raises(JSONRPCError) as error:
        await helper(SimpleNamespace(id="gateway-a", url="http://peer/mcp"), {}, {}, paginate=True)
    assert error.value.code == -32000


@pytest.mark.asyncio
async def test_hidden_tools_do_not_shorten_pages(catalog_db, monkeypatch):
    """Scan bounded batches past app-only tools to fill model-visible pages."""
    # First-Party
    from mcpgateway.services.mcp_apps import MCP_UI_EXTENSION

    monkeypatch.setattr(settings, "mcpgateway_mcp_apps_enabled", True)
    rows = [_row("tools/list", index) for index in range(12)]
    for row in rows[:7]:
        row.extension_metadata = {MCP_UI_EXTENSION: {"resourceUri": "ui://pagination/app", "visibility": ["app"]}}
    catalog_db.add_all(rows)
    catalog_db.commit()
    first = await catalog.list_catalog_page(catalog_db, "tools/list", user_email="user@example.com", token_teams=[])
    assert [item["name"] for item in first["tools"]] == ["item-007", "item-008", "item-009"]
    second = await catalog.list_catalog_page(catalog_db, "tools/list", cursor=first["nextCursor"], user_email="user@example.com", token_teams=[])
    assert [item["name"] for item in second["tools"]] == ["item-010", "item-011"]
    assert "nextCursor" not in second


@pytest.mark.asyncio
@pytest.mark.parametrize("method,result_key", [("tools/list", "tools"), ("resources/list", "resources")])
async def test_proxy_helpers_collect_all_pages(monkeypatch, method, result_key):
    """Collect complete proxy catalogs before returning descriptors."""
    item = types.Tool(name="tool-a", input_schema={"type": "object"}) if method == "tools/list" else types.Resource(name="resource-a", uri="test://resource-a")
    collected = AsyncMock(return_value=[item])
    monkeypatch.setattr(transport, "collect_proxy_catalog", collected)
    monkeypatch.setattr(transport, "_build_proxy_list_headers", lambda *_: {})
    client = SimpleNamespace()

    @asynccontextmanager
    async def upstream(**_kwargs):
        yield client

    monkeypatch.setattr(transport, "mcp_proxy_client", upstream)
    helper = getattr(transport, f"_proxy_list_{result_key}_to_gateway")
    result = await helper(SimpleNamespace(id="gateway-a", url="http://peer/mcp"), {}, {}, {"key": "value"}, paginate=True)
    assert result == [item]
    collected.assert_awaited_once_with(client, method, {"key": "value"})


@pytest.mark.asyncio
@pytest.mark.parametrize("method,key,_model", METHODS)
@pytest.mark.parametrize("first_header", ["Mcp-Session-Id", "X-Mcp-Session-Id"])
async def test_session_header_route_parity(catalog_db, method, key, _model, first_header):
    """Accept equivalent forwarded sessions and reject different session identities."""
    catalog_db.add_all(_row(method, index) for index in range(7))
    catalog_db.commit()
    args = {"user_email": "user@example.com", "token_teams": []}
    first = await catalog.list_catalog_page(catalog_db, method, request_headers={first_header: "session-a"}, **args)
    for header in ("mcp-session-id", "x-mcp-session-id"):
        page = await catalog.list_catalog_page(catalog_db, method, cursor=first["nextCursor"], request_headers={header: "session-a"}, **args)
        assert len(page[key]) == 3
        with pytest.raises(JSONRPCError) as error:
            await catalog.list_catalog_page(catalog_db, method, cursor=first["nextCursor"], request_headers={header: "session-b"}, **args)
        assert error.value.code == -32602
    page = await catalog.list_catalog_page(catalog_db, method, cursor=first["nextCursor"], request_headers={"x-mcp-session-id": "session-a", "mcp-session-id": "session-b"}, **args)
    assert len(page[key]) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("header,allowed", [("X-Trace-Id", True), ("Traceparent", True), ("Authorization", False), ("X-Tenant-Id", False), ("Baggage", False)])
async def test_proxy_header_binding(catalog_db, monkeypatch, snapshot_redis, header, allowed):
    """Permit tracing changes while binding authorization and catalog-selection headers."""
    monkeypatch.setattr(catalog, "get_redis_client", AsyncMock(return_value=snapshot_redis))
    monkeypatch.setattr(transport, "_build_proxy_list_headers", lambda _gateway, headers: headers)
    proxy = AsyncMock(return_value=[types.Tool(name=f"tool-{index}", input_schema={"type": "object"}) for index in range(7)])
    monkeypatch.setattr(transport, "_proxy_list_tools_to_gateway", proxy)
    gateway = SimpleNamespace(id="gateway", url="http://peer/mcp", updated_at="version-a")
    first = await catalog._proxy_page(gateway, "tools/list", None, "scope", {header: "value-a"}, None)
    same = await catalog._proxy_page(gateway, "tools/list", first["nextCursor"], "scope", {header.lower(): "value-a"}, None)
    assert len(same["tools"]) == 3
    if allowed:
        changed = await catalog._proxy_page(gateway, "tools/list", first["nextCursor"], "scope", {header: "value-b"}, None)
        assert changed["tools"] == same["tools"]
    else:
        with pytest.raises(JSONRPCError) as error:
            await catalog._proxy_page(gateway, "tools/list", first["nextCursor"], "scope", {header: "value-b"}, None)
        assert error.value.code == -32602
    assert proxy.await_count == 1
    await snapshot_redis.aclose()


@pytest.mark.asyncio
async def test_prompt_page_avoids_gateway_queries(catalog_db):
    """Serialize gateway-backed prompts without loading gateways or lookahead relationships."""
    # First-Party
    from mcpgateway.db import Gateway
    from tests.helpers.query_counter import count_queries

    rows = []
    for index in range(4):
        gateway = Gateway(id=f"gateway-{index}", name=f"Gateway {index}", url=f"https://example.com/{index}", capabilities={})
        row = _row("prompts/list", index, gateway=gateway)
        row.argument_schema = {"type": "object", "properties": {"question": {"type": "string", "description": "Question"}}, "required": ["question"]}
        rows.append(row)
    catalog_db.add_all(rows)
    catalog_db.commit()
    catalog_db.expunge_all()
    with count_queries(catalog_db.get_bind()) as counter:
        page = await catalog.list_catalog_page(catalog_db, "prompts/list", user_email="user@example.com", token_teams=[])
    assert counter.count == 1
    assert len(page["prompts"]) == 3 and page["nextCursor"]
    assert page["prompts"][0]["arguments"] == [{"name": "question", "description": "Question", "required": True}]


@pytest.mark.asyncio
async def test_proxy_diagnostics_exclude_exception_contents(monkeypatch, caplog):
    """Record failure categories without leaking exception text or catalog contents."""
    # First-Party
    from mcpgateway.utils.correlation_id import _correlation_id_context

    @asynccontextmanager
    async def upstream(**_kwargs):
        raise TimeoutError("sensitive-token-and-catalog")
        yield  # pragma: no cover

    monkeypatch.setattr(transport, "mcp_proxy_client", upstream)
    monkeypatch.setattr(transport, "_build_proxy_list_headers", lambda *_: {})
    token = _correlation_id_context.set("request-a")
    try:
        with pytest.raises(JSONRPCError):
            await transport._proxy_list_tools_to_gateway(SimpleNamespace(id="gateway-a", url="https://peer/mcp"), {}, {}, paginate=True)
    finally:
        _correlation_id_context.reset(token)
    assert '"category":"TimeoutError"' in caplog.text
    assert '"correlation_id":"request-a"' in caplog.text
    assert "sensitive-token-and-catalog" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("method,key,_model", METHODS)
async def test_registered_adapter_session_header_parity(catalog_db, monkeypatch, method, key, _model):
    """Continue registered adapter traversals across protocol and forwarded session headers."""
    # Third-Party
    from mcp import MCPError

    catalog_db.add_all(_row(method, index) for index in range(7))
    catalog_db.commit()
    headers = {"mcp-session-id": "session-a"}

    @asynccontextmanager
    async def database():
        """Supply the catalog database to the registered adapter."""
        yield catalog_db

    monkeypatch.setattr(transport, "get_db", database)
    monkeypatch.setattr(transport, "_get_request_context_or_default", AsyncMock(return_value=(None, headers, {"email": "user@example.com", "teams": [], "is_authenticated": True})))
    adapter_name = "resource_templates" if method == "resources/templates/list" else method.removesuffix("/list")
    adapter = getattr(transport, f"_adapt_list_{adapter_name}")
    first = await adapter(None, types.PaginatedRequestParams())
    headers.clear()
    headers["x-mcp-session-id"] = "session-a"
    second = await adapter(None, types.PaginatedRequestParams(cursor=first.next_cursor))
    assert len(second.model_dump(by_alias=True)[key]) == 3
    headers["x-mcp-session-id"] = "session-b"
    with pytest.raises(MCPError) as rejected:
        await adapter(None, types.PaginatedRequestParams(cursor=first.next_cursor))
    assert rejected.value.code == -32602


@pytest.mark.asyncio
async def test_proxy_admission_precedes_collection(catalog_db, monkeypatch, snapshot_redis):
    """Reject exhausted snapshot capacity before an upstream catalog request."""
    monkeypatch.setattr(settings, "mcp_proxy_list_max_total_bytes", 1)
    monkeypatch.setattr(catalog, "get_redis_client", AsyncMock(return_value=snapshot_redis))
    monkeypatch.setattr(transport, "_build_proxy_list_headers", lambda *_: {})
    proxy = AsyncMock()
    monkeypatch.setattr(transport, "_proxy_list_tools_to_gateway", proxy)
    gateway = SimpleNamespace(id="gateway", url="http://peer/mcp", updated_at="version-a")
    with pytest.raises(JSONRPCError, match="capacity"):
        await catalog._proxy_page(gateway, "tools/list", None, "scope", {}, None)
    proxy.assert_not_awaited()
    await snapshot_redis.aclose()


@pytest.mark.asyncio
async def test_single_page_proxy_releases_reservation(catalog_db, monkeypatch, snapshot_redis):
    """Release successful single-page collections without retaining snapshot fields."""
    monkeypatch.setattr(catalog, "get_redis_client", AsyncMock(return_value=snapshot_redis))
    monkeypatch.setattr(transport, "_build_proxy_list_headers", lambda *_: {})
    monkeypatch.setattr(transport, "_proxy_list_tools_to_gateway", AsyncMock(return_value=[types.Tool(name="only", input_schema={})]))
    gateway = SimpleNamespace(id="gateway", url="http://peer/mcp", updated_at="version-a")
    page = await catalog._proxy_page(gateway, "tools/list", None, "scope", {}, None)
    assert len(page["tools"]) == 1 and "nextCursor" not in page
    assert not snapshots.orjson.loads(await snapshot_redis.hget(snapshots.snapshot_key(), "leases"))
    assert await snapshot_redis.hlen(snapshots.snapshot_key()) == 1
    monkeypatch.setattr(catalog, "get_redis_client", AsyncMock(return_value=None))
    assert await catalog._proxy_page(gateway, "tools/list", None, "scope", {}, None) == page
    await snapshot_redis.aclose()


@pytest.mark.asyncio
async def test_proxy_storage_diagnostics_are_sanitized(catalog_db, monkeypatch, caplog):
    """Report Redis exception categories without disclosing exception text."""
    redis = SimpleNamespace(eval=AsyncMock(side_effect=ConnectionError("sensitive-redis-url")))
    monkeypatch.setattr(catalog, "get_redis_client", AsyncMock(return_value=redis))
    monkeypatch.setattr(transport, "_build_proxy_list_headers", lambda *_: {})
    gateway = SimpleNamespace(id="gateway-a", url="http://peer/mcp", updated_at="version-a")
    with pytest.raises(JSONRPCError, match="storage is unavailable"):
        await catalog._proxy_page(gateway, "tools/list", None, "scope", {}, None)
    assert '"category":"ConnectionError"' in caplog.text
    assert "sensitive-redis-url" not in caplog.text
