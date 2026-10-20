# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/mcp_catalog_service.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Serve bounded MCP catalogs with current visibility checks.
"""

# Transport serializers load after initialization to avoid eager circular imports.
# pylint: disable=cyclic-import

# Standard
import asyncio
from collections.abc import Sequence
import logging
import time
from typing import Any

# Third-Party
import mcp_types as types
import orjson
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import Gateway, Prompt, Resource, server_prompt_association, server_resource_association, server_tool_association, Tool
from mcpgateway.observability import create_span, set_span_attribute
from mcpgateway.services.prompt_service import PromptService
from mcpgateway.services.resource_service import ResourceService
from mcpgateway.services.tool_service import ToolService
from mcpgateway.utils.gateway_access import check_gateway_access, extract_gateway_id_from_headers
from mcpgateway.utils.correlation_id import get_correlation_id
from mcpgateway.utils.mcp_catalog_snapshot import publish_snapshot, read_snapshot, reserve_collection
from mcpgateway.utils.mcp_cursor import catalog_session_id, decode_cursor, encode_cursor, proxy_scope_fingerprint, scope_fingerprint
from mcpgateway.utils.redis_client import get_redis_client
from mcpgateway.validation.jsonrpc import JSONRPCError

logger = logging.getLogger(__name__)
# These headers carry tracing context, never catalog selection or authorization.
_TRACING_HEADERS = frozenset({"traceparent", "tracestate", "x-trace-id", "x-request-id", "x-correlation-id", "b3", "x-b3-traceid", "x-b3-spanid", "x-b3-parentspanid", "x-b3-sampled", "x-b3-flags"})
_CATALOGS: dict[str, tuple[type[Tool] | type[Resource] | type[Prompt], type[ToolService] | type[ResourceService] | type[PromptService], Any, str, str]] = {
    "tools/list": (Tool, ToolService, server_tool_association, "tool_id", "tools"),
    "resources/list": (Resource, ResourceService, server_resource_association, "resource_id", "resources"),
    "prompts/list": (Prompt, PromptService, server_prompt_association, "prompt_id", "prompts"),
    "resources/templates/list": (Resource, ResourceService, server_resource_association, "resource_id", "resourceTemplates"),
}


def _serialize(method: str, row: Any, *, model_items: bool = False) -> Any:
    """Convert one database row into its MCP descriptor.

    Args:
        method: MCP list method.
        row: Catalog database row.
        model_items: Return SDK models for transport adapters.

    Returns:
        SDK model or wire representation, or None for a model-hidden tool.
    """
    # Import after transport initialization to reuse its canonical MCP serializers.
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import _to_mcp_resource, _tools_for_client  # pylint: disable=import-outside-toplevel

    item: types.Tool | types.Resource | types.Prompt | types.ResourceTemplate | None
    if method == "tools/list":
        tools = _tools_for_client([row])
        item = tools[0] if tools else None
    elif method == "resources/list":
        item = _to_mcp_resource(row)
    elif method == "prompts/list":
        schema = row.argument_schema or {}
        item = types.Prompt(
            name=row.name,
            title=row.title,
            description=row.description,
            arguments=[types.PromptArgument(name=name, description=prop.get("description") or "", required=name in schema.get("required", [])) for name, prop in schema.get("properties", {}).items()],
        )
    else:
        item = types.ResourceTemplate(uri_template=row.uri_template, name=row.name, title=row.title, description=row.description, mime_type=row.mime_type)
    if model_items or item is None:
        return item
    return item.model_dump(by_alias=True, exclude_none=True, mode="json")


async def collect_proxy_catalog(client: Any, method: str, meta: Any, serialized_items: dict[str, dict[str, Any]] | None = None) -> list[Any]:
    """Collect an upstream catalog within one client session.

    Args:
        client: Initialized upstream MCP client.
        method: MCP list method.
        meta: Original request metadata.
        serialized_items: Optional output cache for wire descriptors keyed by identifier.

    Returns:
        Complete upstream catalog.

    Raises:
        JSONRPCError: If the upstream repeats cursors, duplicates items, or exceeds collection limits.
    """
    list_method = client.list_tools if method == "tools/list" else client.list_resources
    key = _CATALOGS[method][4]
    cursor = None
    seen_cursors: set[str] = set()
    seen_items: set[str] = set()
    result = []
    byte_count = 2
    async with asyncio.timeout(settings.mcpgateway_direct_proxy_timeout):
        for _ in range(10000):
            kwargs = {"meta": meta} if meta is not None else {}
            if cursor is not None:
                kwargs["cursor"] = cursor
            page = await list_method(**kwargs)
            for item in getattr(page, key):
                identity = item.name if method == "tools/list" else str(item.uri)
                if identity in seen_items:
                    raise JSONRPCError(-32000, "Upstream MCP catalog contains duplicate identifiers")
                seen_items.add(identity)
                wire_item = item.model_dump(by_alias=True, mode="json", exclude_none=True)
                byte_count += len(orjson.dumps(wire_item)) + 1
                if serialized_items is not None:
                    serialized_items[identity] = wire_item
                if byte_count > settings.mcp_proxy_list_max_snapshot_bytes:
                    raise JSONRPCError(-32000, "Direct-proxy MCP catalog exceeds the snapshot byte limit")
                result.append(item)
            cursor = page.next_cursor
            if cursor is None:
                return result
            if not cursor or cursor in seen_cursors:
                raise JSONRPCError(-32000, "Upstream MCP server repeats an invalid pagination cursor")
            seen_cursors.add(cursor)
    raise JSONRPCError(-32000, "Upstream MCP catalog exceeds the pagination page limit")


async def _proxy_page(gateway: Gateway, method: str, cursor: Any, scope: str, headers: dict[str, str], meta: Any, *, model_items: bool = False) -> dict[str, Any]:
    """Serve an immutable, authorization-bound Redis proxy snapshot.

    Args:
        gateway: Authorized direct-proxy gateway.
        method: MCP list method.
        cursor: Client continuation cursor.
        scope: Effective visibility fingerprint.
        headers: Incoming request headers.
        meta: Original request metadata.
        model_items: Return SDK models for newly collected items.

    Returns:
        Bounded MCP list result.

    Raises:
        JSONRPCError: If snapshot storage or continuation fails.
    """
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import (  # pylint: disable=import-outside-toplevel
        _build_proxy_list_headers,
        _proxy_list_resources_to_gateway,
        _proxy_list_tools_to_gateway,
    )

    upstream_headers = _build_proxy_list_headers(gateway, headers)
    bound_headers = sorted((name.lower(), value) for name, value in upstream_headers.items() if name.lower() not in _TRACING_HEADERS)
    binding = orjson.dumps([scope, gateway.id, gateway.url, str(gateway.updated_at), bound_headers])
    scope = proxy_scope_fingerprint(binding)
    key = _CATALOGS[method][4]
    redis = await get_redis_client()
    if cursor is not None:
        position = decode_cursor(cursor, scope)
        snapshot, page_index = position.get("snapshot"), position.get("page")
        if not isinstance(snapshot, str) or len(snapshot) != 32 or not isinstance(page_index, int) or isinstance(page_index, bool) or page_index < 1:
            raise JSONRPCError(-32602, "Invalid MCP snapshot cursor")
        if redis is None:
            raise JSONRPCError(-32000, "MCP proxy pagination requires Redis")
        try:
            manifest, page = await read_snapshot(redis, snapshot, page_index)
        except RedisError as exc:
            log_proxy_catalog_failure(gateway.id, method, exc)
            raise JSONRPCError(-32000, "MCP proxy snapshot storage is unavailable") from exc
        if manifest is None or page is None:
            raise JSONRPCError(-32602, "Invalid or expired MCP snapshot cursor")
        manifest = orjson.loads(manifest)
        if manifest["scope"] != scope or page_index >= manifest["pages"]:
            raise JSONRPCError(-32602, "Invalid MCP snapshot cursor")
        result = {key: orjson.loads(page)}
        if page_index + 1 < manifest["pages"]:
            result["nextCursor"] = encode_cursor(scope, position["expires"], {"snapshot": snapshot, "page": page_index + 1})
        return result

    proxy = _proxy_list_tools_to_gateway if method == "tools/list" else _proxy_list_resources_to_gateway
    try:
        async with reserve_collection(redis, scope) as (snapshot, reused):
            if reused:
                manifest, page = await read_snapshot(redis, snapshot, 0)
                if manifest is not None and page is not None:
                    stored = orjson.loads(manifest)
                    return {key: orjson.loads(page), "nextCursor": encode_cursor(scope, stored["expires"], {"snapshot": snapshot, "page": 1})}
                raise JSONRPCError(-32000, "MCP proxy snapshot expired during reuse; restart traversal")
            async with asyncio.timeout(settings.mcpgateway_direct_proxy_timeout):
                serialized_items: dict[str, dict[str, Any]] = {}
                upstream_items = await proxy(gateway, headers, {}, meta, paginate=True, serialized_items=serialized_items)
            items = []
            for item in upstream_items:
                identity = item.name if isinstance(item, types.Tool) else str(item.uri)
                wire_item = serialized_items.get(identity)
                items.append(wire_item if wire_item is not None else item.model_dump(by_alias=True, exclude_none=True, mode="json"))
            size = settings.mcp_list_page_size
            if len(upstream_items) <= size:
                return {key: upstream_items if model_items else items}
            if redis is None:
                raise JSONRPCError(-32000, "Multi-page MCP proxy catalogs require Redis")
            expires = int(time.time()) + settings.mcp_list_cursor_ttl_seconds
            next_cursor = encode_cursor(scope, expires, {"snapshot": snapshot, "page": 1})
            pages = [orjson.dumps(items[start : start + size]) for start in range(0, len(items), size)]
            await publish_snapshot(redis, snapshot, scope, pages)
            return {key: upstream_items[:size] if model_items else items[:size], "nextCursor": next_cursor}
    except RedisError as exc:
        log_proxy_catalog_failure(gateway.id, method, exc)
        raise JSONRPCError(-32000, "MCP proxy snapshot storage is unavailable") from exc


def log_proxy_catalog_failure(gateway_id: str, method: str, error: Exception) -> None:
    """Record sanitized catalog diagnostics without exception contents.

    Args:
        gateway_id: Gateway identifier.
        method: MCP list method.
        error: Failure used only for its exception category.
    """
    diagnostic = {"gateway_id": gateway_id, "method": method, "correlation_id": get_correlation_id(), "category": type(error).__name__}
    logger.warning("MCP proxy catalog failed: %s", orjson.dumps(diagnostic).decode())


async def list_catalog_page(
    db: Session,
    method: str,
    *,
    cursor: Any = None,
    server_id: str | None = None,
    user_email: str | None,
    token_teams: list[str] | None,
    request_headers: dict[str, str] | None = None,
    meta: Any = None,
    model_items: bool = False,
) -> dict[str, Any]:
    """List one MCP catalog page after the caller enforces method authorization.

    Args:
        db: Request database session.
        method: Supported MCP list method.
        cursor: Optional opaque continuation.
        server_id: Authorized virtual server scope.
        user_email: Canonical authenticated identity.
        token_teams: Canonical Layer-1 visibility scope.
        request_headers: Incoming request headers.
        meta: Original request metadata for direct proxy.
        model_items: Preserve SDK models for transport adapters.

    Returns:
        MCP result with items and an optional nextCursor.

    Raises:
        JSONRPCError: If the cursor or direct-proxy operation is invalid.
    """
    operation = {"tools/list": "tool.list", "prompts/list": "prompt.list"}.get(method, "resource.list")
    with create_span(operation, {"mcp.method": method, "mcp.catalog.page_size": settings.mcp_list_page_size, "mcp.catalog.continuation": cursor is not None}) as span:
        headers = {name.lower(): value for name, value in (request_headers or {}).items()}
        scope = scope_fingerprint(method, server_id, user_email, token_teams, catalog_session_id(headers))
        model, service_type, association, association_key, result_key = _CATALOGS[method]
        if server_id and method in ("tools/list", "resources/list"):
            gateway_id = extract_gateway_id_from_headers(headers)
            gateway = db.get(Gateway, gateway_id) if gateway_id else None
            if gateway is not None and gateway.gateway_mode == "direct_proxy":
                if not settings.mcpgateway_direct_proxy_enabled:
                    raise JSONRPCError(-32003, "Direct proxy is disabled")
                if not await check_gateway_access(db, gateway, user_email, token_teams):
                    raise JSONRPCError(-32003, "Access denied to direct-proxy gateway")
                result: dict[str, Any] = await _proxy_page(gateway, method, cursor, scope, headers, meta, model_items=model_items)
                set_span_attribute(span, "mcp.catalog.count", len(result[result_key]))
                set_span_attribute(span, "mcp.catalog.has_more", "nextCursor" in result)
                return result

        expires = int(time.time()) + settings.mcp_list_cursor_ttl_seconds
        after = None
        if cursor is not None:
            position = decode_cursor(cursor, scope)
            after = position.get("after")
            if not isinstance(after, str) or not after or len(after) > 36:
                raise JSONRPCError(-32602, "Invalid MCP database cursor")
            expires = position["expires"]
        service = service_type()
        query = select(model).where(model.enabled.is_(True))
        if server_id:
            query = query.join(association, model.id == association.c[association_key]).where(association.c.server_id == server_id)
        if model is Resource:
            query = query.where(Resource.uri_template.isnot(None) if method == "resources/templates/list" else Resource.uri_template.is_(None))
        query = await service._apply_access_control(query, db, user_email, token_teams)  # pylint: disable=protected-access
        size = settings.mcp_list_page_size
        items: list[tuple[str, Any]] = []
        while len(items) <= size:
            batch_query = query.where(model.id > after) if after is not None else query
            rows: Sequence[Tool | Resource | Prompt] = db.execute(batch_query.order_by(model.id.asc()).limit(size + 1)).scalars().all()
            if not rows:
                break
            for row in rows:
                after = row.id
                item = _serialize(method, row, model_items=model_items)
                if item is not None:
                    items.append((row.id, item))
                if len(items) > size:
                    break
            if len(rows) < size + 1:
                break
        result = {result_key: [item for _, item in items[:size]]}
        if len(items) > size:
            result["nextCursor"] = encode_cursor(scope, expires, {"after": items[size - 1][0]})
        set_span_attribute(span, "mcp.catalog.count", len(result[result_key]))
        set_span_attribute(span, "mcp.catalog.has_more", "nextCursor" in result)
        return result
