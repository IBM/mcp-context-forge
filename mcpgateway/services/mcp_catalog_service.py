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
import hashlib
import logging
import time
from typing import Any
import uuid

# Third-Party
import mcp_types as types
import orjson
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
from mcpgateway.utils.mcp_cursor import decode_cursor, encode_cursor, scope_fingerprint
from mcpgateway.utils.redis_client import get_redis_client
from mcpgateway.validation.jsonrpc import JSONRPCError

logger = logging.getLogger(__name__)
_CATALOGS: dict[str, tuple[type[Tool] | type[Resource] | type[Prompt], type[ToolService] | type[ResourceService] | type[PromptService], Any, str, str]] = {
    "tools/list": (Tool, ToolService, server_tool_association, "tool_id", "tools"),
    "resources/list": (Resource, ResourceService, server_resource_association, "resource_id", "resources"),
    "prompts/list": (Prompt, PromptService, server_prompt_association, "prompt_id", "prompts"),
    "resources/templates/list": (Resource, ResourceService, server_resource_association, "resource_id", "resourceTemplates"),
}


def _serialize(method: str, row: Any, service: Any) -> dict[str, Any] | None:
    """Convert one database row into its MCP wire representation.

    Args:
        method: MCP list method.
        row: Catalog database row.
        service: Resource service used for conversion.

    Returns:
        Wire representation, or None for a model-hidden tool.
    """
    # Import after transport initialization to reuse its canonical MCP serializers.
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import _to_mcp_prompt, _to_mcp_resource, _tools_for_client  # pylint: disable=import-outside-toplevel

    item: types.Tool | types.Resource | types.Prompt | types.ResourceTemplate | None
    if method == "tools/list":
        tools = _tools_for_client([row])
        item = tools[0] if tools else None
    elif method == "resources/list":
        item = _to_mcp_resource(row)
    elif method == "prompts/list":
        item = _to_mcp_prompt(service.convert_prompt_to_read(row, include_metrics=False))
    else:
        item = types.ResourceTemplate(uri_template=row.uri_template, name=row.name, title=row.title, description=row.description, mime_type=row.mime_type)
    return item.model_dump(by_alias=True, exclude_none=True, mode="json") if item is not None else None


async def collect_proxy_catalog(client: Any, method: str, meta: Any) -> list[Any]:
    """Collect an upstream catalog within one client session.

    Args:
        client: Initialized upstream MCP client.
        method: MCP list method.
        meta: Original request metadata.

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
    byte_count = 0
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
                byte_count += len(orjson.dumps(item.model_dump(by_alias=True, mode="json", exclude_none=True)))
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


async def _proxy_page(gateway: Gateway, method: str, cursor: Any, scope: str, headers: dict[str, str], meta: Any) -> dict[str, Any]:
    """Serve an immutable, authorization-bound Redis proxy snapshot.

    Args:
        gateway: Authorized direct-proxy gateway.
        method: MCP list method.
        cursor: Client continuation cursor.
        scope: Effective visibility fingerprint.
        headers: Incoming request headers.
        meta: Original request metadata.

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
    binding = orjson.dumps([scope, gateway.id, gateway.url, str(gateway.updated_at), sorted(upstream_headers.items())])
    scope = hashlib.sha256(binding).hexdigest()
    key = _CATALOGS[method][4]
    redis = await get_redis_client()
    prefix = f"{settings.cache_prefix}mcp-list:"
    if cursor is not None:
        position = decode_cursor(cursor, scope)
        snapshot, page_index = position.get("snapshot"), position.get("page")
        if not isinstance(snapshot, str) or len(snapshot) != 32 or not isinstance(page_index, int) or isinstance(page_index, bool) or page_index < 1:
            raise JSONRPCError(-32602, "Invalid MCP snapshot cursor")
        if redis is None:
            raise JSONRPCError(-32000, "MCP proxy pagination requires Redis")
        try:
            manifest, page = await redis.mget(f"{prefix}{snapshot}:manifest", f"{prefix}{snapshot}:{page_index}")
        except Exception as exc:
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
    upstream_items = await proxy(gateway, headers, {}, meta, paginate=True)
    items = [item.model_dump(by_alias=True, exclude_none=True, mode="json") for item in upstream_items]
    size = settings.mcp_list_page_size
    if len(items) <= size:
        return {key: items}
    if redis is None:
        raise JSONRPCError(-32000, "Multi-page MCP proxy catalogs require Redis")
    snapshot = uuid.uuid4().hex
    expires = int(time.time()) + settings.mcp_list_cursor_ttl_seconds
    next_cursor = encode_cursor(scope, expires, {"snapshot": snapshot, "page": 1})
    pages = [items[start : start + size] for start in range(0, len(items), size)]
    try:
        async with redis.pipeline(transaction=True) as pipeline:
            for index, page in enumerate(pages):
                pipeline.set(f"{prefix}{snapshot}:{index}", orjson.dumps(page), ex=settings.mcp_list_cursor_ttl_seconds)
            pipeline.set(f"{prefix}{snapshot}:manifest", orjson.dumps({"scope": scope, "pages": len(pages)}), ex=settings.mcp_list_cursor_ttl_seconds)
            await pipeline.execute()
    except Exception as exc:
        raise JSONRPCError(-32000, "MCP proxy snapshot storage is unavailable") from exc
    return {key: pages[0], "nextCursor": next_cursor}


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

    Returns:
        MCP result with items and an optional nextCursor.

    Raises:
        JSONRPCError: If the cursor or direct-proxy operation is invalid.
    """
    operation = {"tools/list": "tool.list", "prompts/list": "prompt.list"}.get(method, "resource.list")
    with create_span(operation, {"mcp.method": method, "mcp.catalog.page_size": settings.mcp_list_page_size, "mcp.catalog.continuation": cursor is not None}) as span:
        headers = {name.lower(): value for name, value in (request_headers or {}).items()}
        scope = scope_fingerprint(method, server_id, user_email, token_teams, headers.get("mcp-session-id"))
        model, service_type, association, association_key, result_key = _CATALOGS[method]
        if server_id and method in ("tools/list", "resources/list"):
            gateway_id = extract_gateway_id_from_headers(headers)
            gateway = db.get(Gateway, gateway_id) if gateway_id else None
            if gateway is not None and gateway.gateway_mode == "direct_proxy":
                if not settings.mcpgateway_direct_proxy_enabled:
                    raise JSONRPCError(-32003, "Direct proxy is disabled")
                if not await check_gateway_access(db, gateway, user_email, token_teams):
                    raise JSONRPCError(-32003, "Access denied to direct-proxy gateway")
                result: dict[str, Any] = await _proxy_page(gateway, method, cursor, scope, headers, meta)
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
        items: list[tuple[str, dict[str, Any]]] = []
        while len(items) <= size:
            batch_query = query.where(model.id > after) if after is not None else query
            rows: Sequence[Tool | Resource | Prompt] = db.execute(batch_query.order_by(model.id.asc()).limit(size + 1)).scalars().all()
            if not rows:
                break
            for row in rows:
                after = row.id
                item = _serialize(method, row, service)
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
