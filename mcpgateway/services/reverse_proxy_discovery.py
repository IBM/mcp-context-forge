# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/reverse_proxy_discovery.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

MCP discovery and catalog reconciliation over reverse-proxy sessions.

The reverse-proxy client is a maintained MCP server reached through its
registration WebSocket. After catalog registration the gateway drives the
legacy MCP lifecycle itself: ``initialize`` -> ``notifications/initialized``
-> capability-gated list calls -> catalog sync/reconcile -> virtual-server
association -> commit. The caller then publishes cache invalidations and
subscriber notification while the stable ID is still unmapped, and promotes
routing last.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Any, Final, Mapping, cast
import uuid

from pydantic import ValidationError
from sqlalchemy.orm import Session

from mcpgateway import __version__
from mcpgateway.config import settings
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import Server as DbServer
from mcpgateway.schemas import PromptCreate, ResourceCreate, ToolCreate
from mcpgateway.services.gateway_service import (
    GatewayConnectionError,
    GatewayService,
    _get_registry_cache,
    _get_tool_lookup_cache,
)
from mcpgateway.services.mcp_apps import merge_mcp_protocol_meta
from mcpgateway.services.reverse_proxy_protocol import JsonObject, JsonRpcErrorResponse, JsonRpcNotification, JsonRpcRequest, REVERSE_PROXY_CREATED_VIA
from mcpgateway.services.reverse_proxy_sessions import ConnectionClosedError, ConnectionId, ConnectionNotFoundError, ReverseProxySessionManager
from mcpgateway.services.server_service import ServerService

logger = logging.getLogger(__name__)

MCP_CLIENT_PROTOCOL_VERSION: Final = "2025-11-25"
MCP_CLIENT_NAME: Final = "mcp-context-forge"
MAX_LIST_PAGES: Final = 100
PEER_AUTHORITY_FIELDS: Final = ("visibility", "team_id", "teamId", "owner_email", "ownerEmail", "gateway_id", "gatewayId")


def _strip_peer_authority_fields(data: dict[str, Any]) -> None:
    """Drop peer-selected ownership and visibility keys from one upstream item.

    The reverse-proxy peer is a user-controlled connection, so a team-scoped
    client advertising ``"visibility": "public"`` (or someone else's
    ``team_id``/``owner_email``) on a listed tool, resource, or prompt would
    otherwise widen that catalog row past its own authenticated scope. Team
    ownership and visibility are always derived from the registration-time
    gateway row instead. Both the snake_case field names and the camelCase
    aliases are removed, since the prompt schema accepts either spelling.

    Args:
        data: One raw upstream catalog item, mutated in place.
    """
    for field in PEER_AUTHORITY_FIELDS:
        data.pop(field, None)


class ReverseProxyDiscoveryError(Exception):
    """Raised when reverse-proxy discovery cannot be completed or applied."""


@dataclass(frozen=True, slots=True)
class ReverseProxyDiscoveryResult:
    """Outcome of one reverse-proxy discovery and reconciliation pass."""

    capabilities: Mapping[str, Any]
    tools_added: int
    tools_removed: int
    resources_added: int
    resources_removed: int
    prompts_added: int
    prompts_removed: int
    validation_errors: tuple[str, ...]


class ReverseProxyDiscoveryService:
    """Drive MCP discovery and catalog reconciliation for one reverse-proxy connection."""

    def __init__(self, gateway_service: GatewayService | None = None, server_service: ServerService | None = None) -> None:
        """Initialize with the shared gateway catalog and server services.

        When ``server_service`` is not injected, the process-level lazy
        singleton from ``mcpgateway.services.server_service`` is used; a fresh
        ``ServerService`` is never constructed here, since that would leak an
        ``httpx.AsyncClient`` and publish events with no process subscribers.
        """
        self._gateway_service = gateway_service or GatewayService()
        if server_service is not None:
            self._server_service = server_service
        else:
            from mcpgateway.services.server_service import server_service as process_server_service  # pylint: disable=import-outside-toplevel,no-name-in-module

            self._server_service = process_server_service

    async def discover_and_reconcile(
        self,
        db: Session,
        session_manager: ReverseProxySessionManager,
        connection_id: ConnectionId,
        db_gateway: DbGateway,
        db_server: DbServer,
        timeout_seconds: float | None = None,
        *,
        commit: bool = True,
        mark_reachable: bool = True,
    ) -> ReverseProxyDiscoveryResult:
        """Run MCP discovery on one connection and reconcile the stable catalog pair.

        The caller's request-scoped ``db`` is reused and committed exactly
        once, after all network interaction has succeeded; any earlier
        failure leaves the catalog untouched. No cache invalidation or
        subscriber notification happens here: after the commit the caller
        invokes :meth:`publish_post_commit_effects` while the stable ID is
        still unmapped, then promotes routing last.

        Args:
            db: Caller-owned request-scoped database session.
            session_manager: Process-local reverse-proxy session registry.
            connection_id: Live connection to run discovery against.
            db_gateway: Stable PROXIED gateway row created at registration.
            db_server: Virtual server row paired with the gateway.
            timeout_seconds: Per-request timeout; defaults to ``settings.tool_timeout``.
            commit: Whether to commit the reconciled catalog transaction.
            mark_reachable: Whether the reconciled gateway should be marked reachable.

        Returns:
            The negotiated capabilities, per-type reconciliation counts, and
            any per-item validation errors.

        Raises:
            ReverseProxyDiscoveryError: On handshake failure, transport loss,
                malformed list payloads, unbounded pagination, or total tool
                validation failure.
        """
        effective_timeout = timeout_seconds if timeout_seconds is not None else float(settings.tool_timeout)
        capabilities = await self._initialize(session_manager, connection_id, effective_timeout)
        await self._notify_initialized(session_manager, connection_id, effective_timeout)

        tool_dicts = await self._list_all(session_manager, connection_id, "tools/list", "tools", effective_timeout) if capabilities.get("tools") is not None else []
        resource_dicts: list[dict[str, Any]] = []
        template_dicts: list[dict[str, Any]] = []
        if capabilities.get("resources") is not None:
            resource_dicts = await self._list_all(session_manager, connection_id, "resources/list", "resources", effective_timeout)
            template_dicts = await self._list_all(session_manager, connection_id, "resources/templates/list", "resourceTemplates", effective_timeout)
        prompt_dicts = await self._list_all(session_manager, connection_id, "prompts/list", "prompts", effective_timeout) if capabilities.get("prompts") is not None else []

        tools, validation_errors = self._build_tools(tool_dicts)
        resources = self._build_resources(resource_dicts, template_dicts)
        prompts = self._build_prompts(prompt_dicts)

        db_gateway.capabilities = dict(capabilities)
        db_gateway.reachable = mark_reachable
        db_gateway.last_seen = datetime.now(timezone.utc)

        catalog_sync = self._gateway_service._sync_gateway_catalog(  # pylint: disable=protected-access
            db,
            gateway=db_gateway,
            tools=tools,
            resources=resources,
            prompts=prompts,
            created_via=REVERSE_PROXY_CREATED_VIA,
        )
        reconcile = self._gateway_service._reconcile_gateway_catalog(  # pylint: disable=protected-access
            db,
            gateway=db_gateway,
            catalog_sync=catalog_sync,
            log_context="reverse-proxy discovery",
            stale_created_via_values={REVERSE_PROXY_CREATED_VIA},
        )

        # Reload the reconciled relationships: the sync path persists some new rows
        # via gateway_id without refreshing the in-memory gateway collections.
        db.flush()
        db.expire(db_gateway, ["tools", "resources", "prompts"])
        db_server.tools = list(db_gateway.tools)
        db_server.resources = list(db_gateway.resources)
        db_server.prompts = list(db_gateway.prompts)
        if commit:
            db.commit()
        else:
            db.flush()

        return ReverseProxyDiscoveryResult(
            capabilities=capabilities,
            tools_added=reconcile.tools_added,
            tools_removed=reconcile.tools_removed,
            resources_added=reconcile.resources_added,
            resources_removed=reconcile.resources_removed,
            prompts_added=reconcile.prompts_added,
            prompts_removed=reconcile.prompts_removed,
            validation_errors=tuple(validation_errors),
        )

    async def _initialize(self, session_manager: ReverseProxySessionManager, connection_id: ConnectionId, timeout_seconds: float) -> dict[str, Any]:
        """Perform the MCP handshake and return the negotiated capabilities."""
        result = await self._rpc_call(
            session_manager,
            connection_id,
            "initialize",
            {"protocolVersion": MCP_CLIENT_PROTOCOL_VERSION, "capabilities": {}, "clientInfo": {"name": MCP_CLIENT_NAME, "version": __version__}},
            timeout_seconds,
        )
        capabilities = result.get("capabilities", {})
        if not isinstance(capabilities, dict):
            raise ReverseProxyDiscoveryError("reverse-proxy initialize returned non-object capabilities")
        logger.debug("Reverse-proxy negotiated protocol version %s", result.get("protocolVersion"))
        return capabilities

    async def _notify_initialized(self, session_manager: ReverseProxySessionManager, connection_id: ConnectionId, timeout_seconds: float) -> None:
        """Send notifications/initialized to complete the MCP handshake."""
        notification = JsonRpcNotification(jsonrpc="2.0", method="notifications/initialized")
        try:
            await session_manager.send_notification(connection_id, notification, timeout_seconds)
        except TimeoutError as exc:
            raise ReverseProxyDiscoveryError(f"reverse-proxy notifications/initialized timed out after {timeout_seconds}s") from exc
        except (ConnectionClosedError, ConnectionNotFoundError) as exc:
            raise ReverseProxyDiscoveryError(f"reverse-proxy connection lost sending notifications/initialized: {exc}") from exc

    async def _rpc_call(
        self,
        session_manager: ReverseProxySessionManager,
        connection_id: ConnectionId,
        method: str,
        params: JsonObject,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        """Send one JSON-RPC request and return its result object."""
        request = JsonRpcRequest(jsonrpc="2.0", id=uuid.uuid4().hex, method=method, params=params)
        try:
            response = await session_manager.send_request(connection_id, request, timeout_seconds)
        except TimeoutError as exc:
            raise ReverseProxyDiscoveryError(f"reverse-proxy {method} timed out after {timeout_seconds}s") from exc
        except (ConnectionClosedError, ConnectionNotFoundError) as exc:
            raise ReverseProxyDiscoveryError(f"reverse-proxy connection lost during {method}: {exc}") from exc
        payload = response.payload
        if isinstance(payload, JsonRpcErrorResponse):
            raise ReverseProxyDiscoveryError(f"reverse-proxy {method} failed: MCP error {payload.error.code}")
        result = payload.result
        if not isinstance(result, dict):
            raise ReverseProxyDiscoveryError(f"reverse-proxy {method} returned a non-object result")
        return result

    async def _list_all(
        self,
        session_manager: ReverseProxySessionManager,
        connection_id: ConnectionId,
        method: str,
        result_key: str,
        timeout_seconds: float,
    ) -> list[dict[str, Any]]:
        """Fetch every page of one list endpoint, bounded against hostile cursors.

        A result object missing the list member is rejected outright: treating
        it as an empty page would let a malformed peer prune the entire
        catalog during reconciliation.
        """
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(MAX_LIST_PAGES):
            params: JsonObject = {"cursor": cursor} if cursor is not None else {}
            result = await self._rpc_call(session_manager, connection_id, method, params, timeout_seconds)
            if result_key not in result:
                raise ReverseProxyDiscoveryError(f"reverse-proxy {method} returned a result missing required member {result_key!r}")
            page = result[result_key]
            if not isinstance(page, list):
                raise ReverseProxyDiscoveryError(f"reverse-proxy {method} returned a non-array {result_key}")
            for page_index, entry in enumerate(page):
                if not isinstance(entry, dict):
                    raise ReverseProxyDiscoveryError(f"reverse-proxy {method} returned non-object item at index {page_index}")
                items.append(cast(dict[str, Any], entry))
            next_cursor = result.get("nextCursor")
            if next_cursor is None:
                return items
            if not isinstance(next_cursor, str):
                raise ReverseProxyDiscoveryError(f"reverse-proxy {method} returned non-string nextCursor")
            cursor = next_cursor
        raise ReverseProxyDiscoveryError(f"reverse-proxy {method} did not finish within {MAX_LIST_PAGES} pages")

    def _build_tools(self, tool_dicts: list[dict[str, Any]]) -> tuple[list[ToolCreate], list[str]]:
        """Validate upstream tool dicts, translating total failure into discovery failure."""
        for data in tool_dicts:
            _strip_peer_authority_fields(data)
        try:
            return self._gateway_service._validate_tools(tool_dicts, context="reverse-proxy")  # pylint: disable=protected-access
        except GatewayConnectionError as exc:
            raise ReverseProxyDiscoveryError(str(exc)) from exc

    def _build_resources(self, resource_dicts: list[dict[str, Any]], template_dicts: list[dict[str, Any]]) -> list[ResourceCreate]:
        """Build resource schemas with the minimal-fallback used for SSE discovery."""
        resources: list[ResourceCreate] = []
        for data in resource_dicts:
            merge_mcp_protocol_meta(data)
            _strip_peer_authority_fields(data)
            if "content" not in data:
                data["content"] = ""
            try:
                resources.append(ResourceCreate.model_validate(data))
            except ValidationError:
                resources.append(
                    ResourceCreate(
                        uri=str(data.get("uri", "")),
                        name=str(data.get("name", "")),
                        description=data.get("description"),
                        mime_type=data.get("mimeType"),
                        uri_template=data.get("uriTemplate") or None,
                        content="",
                        extension_metadata=data.get("extensionMetadata"),
                    )
                )
        for data in template_dicts:
            merge_mcp_protocol_meta(data)
            _strip_peer_authority_fields(data)
            if "uriTemplate" in data:
                data["uri_template"] = str(data["uriTemplate"])
                data["uri"] = str(data["uriTemplate"])
            if "content" not in data:
                data["content"] = ""
            resources.append(ResourceCreate.model_validate(data))
        return resources

    def _build_prompts(self, prompt_dicts: list[dict[str, Any]]) -> list[PromptCreate]:
        """Build prompt schemas with the minimal-fallback used for SSE discovery."""
        prompts: list[PromptCreate] = []
        for data in prompt_dicts:
            _strip_peer_authority_fields(data)
            if "template" not in data:
                data["template"] = ""
            try:
                prompts.append(PromptCreate.model_validate(data))
            except ValidationError:
                prompts.append(PromptCreate(name=str(data.get("name", "")), description=data.get("description"), template=str(data.get("template", ""))))
        return prompts

    async def publish_post_commit_effects(self, db_gateway: DbGateway, db_server: DbServer) -> None:
        """Invalidate caches and notify subscribers after the commit succeeds.

        The advertised catalog categories are invalidated unconditionally:
        registration discovery re-publishes the full catalog state, and a
        metadata-only rediscovery updates rows in place without any add/remove
        counts, so gating on per-type deltas would leave list/catalog APIs stale.

        The caller (the registration router) invokes this after the commit,
        while the stable ID is still unmapped, and promotes routing last:
        once the catalog is committed the stable ID must never route to the
        incompatible predecessor again, so any failure after this point stays
        fail-closed (unrouted).
        """
        cache = _get_registry_cache()
        await cache.invalidate_tools()
        await cache.invalidate_resources()
        await cache.invalidate_prompts()
        await cache.invalidate_servers()
        tool_lookup_cache = _get_tool_lookup_cache()
        await tool_lookup_cache.invalidate_gateway(str(db_gateway.id))
        await self._server_service._notify_server_updated(db_server)  # pylint: disable=protected-access
