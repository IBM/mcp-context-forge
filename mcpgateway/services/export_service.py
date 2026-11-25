# -*- coding: utf-8 -*-
# pylint: disable=import-outside-toplevel,no-name-in-module
"""Location: ./mcpgateway/services/export_service.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Export Service Implementation.
This module implements comprehensive configuration export functionality according to the export specification.
It handles:
- Entity collection from all entity types (Tools, Gateways, Servers, Prompts, Resources, Roots)
- Credential omission and reconfiguration indicators
- Dependency resolution and inclusion
- Filtering by entity types, tags, and active/inactive status
- Export format validation and schema compliance
- Portable references to authorized federated associations
"""

# Standard
from collections import defaultdict
from datetime import datetime, timezone
import logging
from typing import Any, cast, Dict, Iterable, List, Optional, Sequence, TypedDict

# Third-Party
from sqlalchemy import and_, false, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

# First-Party
from mcpgateway import __version__
from mcpgateway.common.validators import SecurityValidator
from mcpgateway.config import settings
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import Prompt as DbPrompt
from mcpgateway.db import Resource as DbResource
from mcpgateway.db import Server as DbServer
from mcpgateway.db import Tool as DbTool
from mcpgateway.db import server_tool_association
from mcpgateway.schemas import GatewayRead, ResourceRead
from mcpgateway.services.gateway_service import gateway_requires_credentials
from mcpgateway.services.tool_service import _decrypt_tool_header_value
from mcpgateway.utils.portable_credentials import without_file_credentials
from mcpgateway.utils.error_formatter import unexpected_error_detail
from mcpgateway.utils.header_filtering import is_sensitive_tool_header_name, is_tool_credential_header_name

# Service singletons are imported lazily in __init__ to avoid circular imports

logger = logging.getLogger(__name__)


def _portable_tool_headers(headers: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Prepare operational headers for export and leave credentials for removal."""
    portable: Dict[str, Any] = {}
    for name, stored in (headers or {}).items():
        if is_tool_credential_header_name(name):
            portable[name] = stored
        elif not is_sensitive_tool_header_name(name) or name.strip().lower() == "content-type":
            value = _decrypt_tool_header_value(stored)
            if isinstance(value, str):
                portable[name] = value
    return portable


def _exportable_resource_base(resource: DbResource | ResourceRead) -> str:
    """Select a resource export name without changing local names.

    Federated candidates are custom_name_slug, original_name, then name. Each
    nonempty candidate is capped at the smaller of 255 and the configured name
    limit before validation. Invalid candidates are skipped. If none validate,
    warn and return the derived name unchanged. Local names are always returned
    verbatim, with a warning if they fail validation.

    Args:
        resource: Resource to export.

    Returns:
        Validated base, or the unchanged name when no candidate validates.
    """
    if resource.gateway_id is None:
        try:
            SecurityValidator.validate_name(resource.name, "Resource name")
        except ValueError:
            logger.warning("Local resource %s (uri=%s) exports a name invalid under current validation settings", resource.id, resource.uri)
        return resource.name

    cap = min(255, settings.validation_max_name_length)
    for candidate in (resource.custom_name_slug, resource.original_name, resource.name):
        if candidate:
            try:
                return SecurityValidator.validate_name(candidate[:cap], "Resource name")
            except ValueError:
                continue
    logger.warning("Federated resource %s (uri=%s) has no importable name under current validation settings; exporting derived name", resource.id, resource.uri)
    return resource.name


class ExportError(Exception):
    """Base class for export-related errors.

    Examples:
        >>> try:
        ...     raise ExportError("General export error")
        ... except ExportError as e:
        ...     str(e)
        'General export error'
        >>> try:
        ...     raise ExportError("Export failed")
        ... except Exception as e:
        ...     isinstance(e, ExportError)
        True
    """


class ExportValidationError(ExportError):
    """Raised when export data validation fails.

    Examples:
        >>> try:
        ...     raise ExportValidationError("Invalid export format")
        ... except ExportValidationError as e:
        ...     str(e)
        'Invalid export format'
        >>> try:
        ...     raise ExportValidationError("Schema validation failed")
        ... except ExportError as e:
        ...     isinstance(e, ExportError)  # Should inherit from ExportError
        True
        >>> try:
        ...     raise ExportValidationError("Missing required field")
        ... except Exception as e:
        ...     isinstance(e, ExportValidationError)
        True
    """


class ExportService:
    """Service for exporting ContextForge configuration and data.

    This service provides comprehensive export functionality including:
    - Collection of all entity types (tools, gateways, servers, prompts, resources, roots)
    - Secure handling of authentication data with encryption
    - Dependency resolution between entities
    - Filtering options (by type, tags, status)
    - Export format validation

    The service only exports locally configured entities, excluding dynamic content
    from federated sources to ensure exports contain only configuration data.

    Examples:
        >>> service = ExportService()
        >>> hasattr(service, 'gateway_service')
        True
        >>> hasattr(service, 'tool_service')
        True
        >>> hasattr(service, 'resource_service')
        True
        >>> # Test entity type validation
        >>> valid_types = ["tools", "gateways", "servers", "prompts", "resources", "roots"]
        >>> "tools" in valid_types
        True
        >>> "invalid_type" in valid_types
        False
        >>> # Test filtering logic
        >>> include_types = ["tools", "servers"]
        >>> exclude_types = ["gateways"]
        >>> "tools" in include_types and "tools" not in exclude_types
        True
        >>> "gateways" in include_types and "gateways" not in exclude_types
        False
        >>> # Test tag filtering
        >>> entity_tags = ["production", "api"]
        >>> filter_tags = ["production"]
        >>> any(tag in entity_tags for tag in filter_tags)
        True
        >>> filter_tags = ["development"]
        >>> any(tag in entity_tags for tag in filter_tags)
        False
    """

    def __init__(self) -> None:
        """Initialize the export service with required dependencies."""
        # Use globally-exported singletons from service modules so they
        # share initialized EventService/Redis clients created at app startup.
        # Import lazily to avoid circular import at module load time.
        # First-Party
        from mcpgateway.services.gateway_service import gateway_service
        from mcpgateway.services.prompt_service import prompt_service
        from mcpgateway.services.resource_service import resource_service
        from mcpgateway.services.root_service import get_root_service
        from mcpgateway.services.server_service import server_service
        from mcpgateway.services.tool_service import tool_service

        self.gateway_service = gateway_service
        self.tool_service = tool_service
        self.resource_service = resource_service
        self.prompt_service = prompt_service
        self.server_service = server_service
        self.root_service = get_root_service()

    async def initialize(self) -> None:
        """Initialize the export service."""
        logger.info("Export service initialized")

    async def shutdown(self) -> None:
        """Shutdown the export service."""
        logger.info("Export service shutdown")

    async def _fetch_all_tools(self, db: Session, tags: Optional[List[str]], include_inactive: bool, user_email: Optional[str] = None, token_teams: Optional[List[str]] = None) -> List[Any]:
        """Fetch all tools by following pagination cursors with team scoping.

        Args:
            db: Database session
            tags: Filter by tags
            include_inactive: Include inactive tools
            user_email: Requesting user's email for visibility filtering
            token_teams: Token team scope for visibility filtering

        Returns:
            List of all tools across all pages
        """
        all_tools = []
        cursor = None
        while True:
            tools, next_cursor = await self.tool_service.list_tools(db, tags=tags, include_inactive=include_inactive, cursor=cursor, user_email=user_email, token_teams=token_teams)
            all_tools.extend(tools)
            if not next_cursor:
                break
            cursor = next_cursor
        return all_tools

    async def _fetch_all_prompts(self, db: Session, tags: Optional[List[str]], include_inactive: bool, user_email: Optional[str] = None, token_teams: Optional[List[str]] = None) -> List[Any]:
        """Fetch all prompts by following pagination cursors with team scoping.

        Args:
            db: Database session
            tags: Filter by tags
            include_inactive: Include inactive prompts
            user_email: Requesting user's email for visibility filtering
            token_teams: Token team scope for visibility filtering

        Returns:
            List of all prompts across all pages
        """
        all_prompts = []
        cursor = None
        while True:
            prompts, next_cursor = await self.prompt_service.list_prompts(db, tags=tags, include_inactive=include_inactive, cursor=cursor, user_email=user_email, token_teams=token_teams)
            all_prompts.extend(prompts)
            if not next_cursor:
                break
            cursor = next_cursor
        return all_prompts

    async def _fetch_all_resources(self, db: Session, tags: Optional[List[str]], include_inactive: bool, user_email: Optional[str] = None, token_teams: Optional[List[str]] = None) -> List[Any]:
        """Fetch all resources by following pagination cursors with team scoping.

        Args:
            db: Database session
            tags: Filter by tags
            include_inactive: Include inactive resources
            user_email: Requesting user's email for visibility filtering
            token_teams: Token team scope for visibility filtering

        Returns:
            List of all resources across all pages
        """
        all_resources = []
        cursor = None
        while True:
            resources, next_cursor = await self.resource_service.list_resources(db, tags=tags, include_inactive=include_inactive, cursor=cursor, user_email=user_email, token_teams=token_teams)
            all_resources.extend(resources)
            if not next_cursor:
                break
            cursor = next_cursor
        return all_resources

    async def _fetch_all_gateways(self, db: Session, tags: Optional[List[str]], include_inactive: bool, user_email: Optional[str] = None, token_teams: Optional[List[str]] = None) -> List[Any]:
        """Fetch all gateways by following pagination cursors with team scoping.

        Args:
            db: Database session
            tags: Filter by tags
            include_inactive: Include inactive gateways
            user_email: Requesting user's email for visibility filtering
            token_teams: Token team scope for visibility filtering

        Returns:
            List of all gateways across all pages
        """
        all_gateways = []
        cursor = None
        while True:
            gateways, next_cursor = await self.gateway_service.list_gateways(db, tags=tags, include_inactive=include_inactive, cursor=cursor, user_email=user_email, token_teams=token_teams)
            all_gateways.extend(gateways)
            if not next_cursor:
                break
            cursor = next_cursor
        return all_gateways

    async def _fetch_all_servers(self, db: Session, tags: Optional[List[str]], include_inactive: bool, user_email: Optional[str] = None, token_teams: Optional[List[str]] = None) -> List[Any]:
        """Fetch all servers by following pagination cursors with team scoping.

        Args:
            db: Database session
            tags: Filter by tags
            include_inactive: Include inactive servers
            user_email: Requesting user's email for visibility filtering
            token_teams: Token team scope for visibility filtering

        Returns:
            List of all servers across all pages
        """
        all_servers = []
        cursor = None
        while True:
            servers, next_cursor = await self.server_service.list_servers(db, tags=tags, include_inactive=include_inactive, cursor=cursor, user_email=user_email, token_teams=token_teams)
            all_servers.extend(servers)
            if not next_cursor:
                break
            cursor = next_cursor
        return all_servers

    async def export_configuration(
        self,
        db: Session,
        include_types: Optional[List[str]] = None,
        exclude_types: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        include_inactive: bool = False,
        include_dependencies: bool = True,
        exported_by: str = "system",
        root_path: str = "",
        user_email: Optional[str] = None,
        token_teams: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Export complete gateway configuration to a standardized format.

        Args:
            db: Database session
            include_types: List of entity types to include (tools, gateways, servers, prompts, resources, roots)
            exclude_types: List of entity types to exclude
            tags: Filter entities by tags (only export entities with these tags)
            include_inactive: Whether to include inactive entities
            include_dependencies: Whether to include dependent entities automatically
            exported_by: Username of the person performing the export
            root_path: Root path for constructing API endpoints
            user_email: Requesting user's email for team-scoped visibility filtering
            token_teams: Token team scope for visibility filtering (None=admin bypass, []=public-only)

        Returns:
            Dict containing the complete export data in the specified schema format

        Raises:
            ExportError: If export fails
            ExportValidationError: If validation fails
        """
        try:
            logger.info("Starting configuration export by %s", exported_by)

            # Determine which entity types to include
            all_types = ["tools", "gateways", "servers", "prompts", "resources", "roots"]
            if include_types:
                entity_types = [t.lower() for t in include_types if t.lower() in all_types]
            else:
                entity_types = all_types

            if exclude_types:
                entity_types = [t for t in entity_types if t.lower() not in [e.lower() for e in exclude_types]]

            class ExportOptions(TypedDict, total=False):
                """Options that control export behavior (full export)."""

                include_inactive: bool
                include_dependencies: bool
                selected_types: List[str]
                filter_tags: List[str]

            class ExportMetadata(TypedDict):
                """Metadata for full export including counts, dependencies, and options."""

                entity_counts: Dict[str, int]
                dependencies: Dict[str, Any]
                export_options: ExportOptions

            class ExportData(TypedDict):
                """Top-level full export payload shape."""

                version: str
                contextforge_version: str
                exported_at: str
                exported_by: str
                source_gateway: str
                encryption_method: str
                entities: Dict[str, List[Dict[str, Any]]]
                metadata: ExportMetadata

            entities: Dict[str, List[Dict[str, Any]]] = {}
            metadata: ExportMetadata = {
                "entity_counts": {},
                "dependencies": {},
                "export_options": {
                    "include_inactive": include_inactive,
                    "include_dependencies": include_dependencies,
                    "selected_types": entity_types,
                    "filter_tags": tags or [],
                },
            }

            export_data: ExportData = {
                "version": settings.protocol_version,
                "contextforge_version": __version__,
                "exported_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "exported_by": exported_by,
                "source_gateway": f"http://{settings.host}:{settings.port}",
                "encryption_method": "AES-256-GCM",
                "entities": entities,
                "metadata": metadata,
            }

            # Export each entity type (with team-scoped visibility filtering)
            if "tools" in entity_types:
                export_data["entities"]["tools"] = await self._export_tools(db, tags, include_inactive, user_email=user_email, token_teams=token_teams)

            if "gateways" in entity_types:
                export_data["entities"]["gateways"] = await self._export_gateways(db, tags, include_inactive, user_email=user_email, token_teams=token_teams)

            if "servers" in entity_types:
                export_data["entities"]["servers"] = await self._export_servers(db, tags, include_inactive, root_path, user_email=user_email, token_teams=token_teams)

            if "prompts" in entity_types:
                export_data["entities"]["prompts"] = await self._export_prompts(db, tags, include_inactive, user_email=user_email, token_teams=token_teams)

            if "resources" in entity_types:
                export_data["entities"]["resources"] = await self._export_resources(db, tags, include_inactive, user_email=user_email, token_teams=token_teams)

            if "roots" in entity_types:
                export_data["entities"]["roots"] = await self._export_roots()

            # Add dependency information
            if include_dependencies:
                export_data["metadata"]["dependencies"] = await self._extract_dependencies(db, export_data["entities"])

            # Calculate entity counts
            for entity_type, entities_list in export_data["entities"].items():
                export_data["metadata"]["entity_counts"][entity_type] = len(entities_list)

            # Validate export data
            self._validate_export_data(cast(Dict[str, Any], export_data))

            logger.info("Export completed successfully with %s total entities", sum(export_data["metadata"]["entity_counts"].values()))
            return cast(Dict[str, Any], export_data)

        except Exception as e:
            logger.error("Export failed: %s", str(e))
            raise ExportError(f"Failed to export configuration: {unexpected_error_detail(e)}")

    async def _export_tools(self, db: Session, tags: Optional[List[str]], include_inactive: bool, user_email: Optional[str] = None, token_teams: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Export tools without credentials.

        Args:
            db: Database session
            tags: Filter by tags
            include_inactive: Include inactive tools
            user_email: Requesting user's email for visibility filtering
            token_teams: Token team scope for visibility filtering

        Returns:
            List of exported tool dictionaries
        """
        # Fetch all tools across all pages (with team-scoped visibility)
        tools = await self._fetch_all_tools(db, tags, include_inactive, user_email=user_email, token_teams=token_teams)

        # Filter to only exportable tools (local REST tools, not MCP tools from gateways)
        exportable_tools = [t for t in tools if not (t.integration_type == "MCP" and t.gateway_id)]
        stored_headers = {}
        if exportable_tools:
            stored_headers = {str(tool_id): headers for tool_id, headers in db.execute(select(DbTool.id, DbTool.headers).where(DbTool.id.in_([str(tool.id) for tool in exportable_tools])))}

        exported_tools = []
        for tool in exportable_tools:
            if getattr(getattr(tool, "auth", None), "auth_type", None) == "sigv4":
                logger.warning("Tool %s uses SigV4 authentication and is not exported: signing credentials are never written to export files", tool.id)
                continue
            tool_data = {
                "id": str(tool.id),
                "visibility": getattr(tool, "visibility", None) or "public",
                "name": tool.original_name,  # Use original name, not the slugified version
                "displayName": tool.displayName,  # Export displayName field from ToolRead
                "url": str(tool.url),
                "integration_type": tool.integration_type,
                "request_type": tool.request_type,
                "description": tool.description,
                "original_description": tool.original_description,
                "headers": _portable_tool_headers(stored_headers.get(str(tool.id), tool.headers)),
                "input_schema": tool.input_schema or {"type": "object", "properties": {}},
                "output_schema": tool.output_schema,
                "annotations": tool.annotations or {},
                "jsonpath_filter": tool.jsonpath_filter,
                "tool_validation_policy": tool.tool_validation_policy,
                "tags": tool.tags or [],
                "rate_limit": getattr(tool, "rate_limit", None),
                "timeout": getattr(tool, "timeout", None),
                "is_active": tool.enabled,
                "created_at": tool.created_at.isoformat() if hasattr(tool.created_at, "isoformat") and tool.created_at else None,
                "updated_at": tool.updated_at.isoformat() if hasattr(tool.updated_at, "isoformat") and tool.updated_at else None,
            }

            tool_data["auth_type"] = getattr(getattr(tool, "auth", None), "auth_type", None)
            exported_tools.append(without_file_credentials(tool_data)[0])

        return exported_tools

    async def _export_gateways(self, db: Session, tags: Optional[List[str]], include_inactive: bool, user_email: Optional[str] = None, token_teams: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Export gateways without credentials.

        Args:
            db: Database session
            tags: Filter by tags
            include_inactive: Include inactive gateways
            user_email: Requesting user's email for visibility filtering
            token_teams: Token team scope for visibility filtering

        Returns:
            List of exported gateway dictionaries
        """
        # Fetch all gateways across all pages (with team-scoped visibility)
        gateways = await self._fetch_all_gateways(db, tags, include_inactive, user_email=user_email, token_teams=token_teams)

        gateway_ids = [str(gateway.id) for gateway in gateways]
        query_auth = {}
        if gateway_ids:
            stmt = select(DbGateway.id, DbGateway.auth_query_params).where(DbGateway.id.in_(gateway_ids))
            query_auth = {gateway_id: params for gateway_id, params in db.execute(stmt)}  # pylint: disable=R1721
        return [entry for gateway in gateways if (entry := self._gateway_export_entry(gateway, query_auth.get(str(gateway.id)))) is not None]

    @staticmethod
    def _gateway_export_entry(gateway: DbGateway | GatewayRead, query_auth: dict[str, Any] | None) -> dict[str, Any] | None:
        """Serialize a gateway without credentials for either export form."""
        if gateway.auth_type == "sigv4":
            logger.warning("Gateway %s uses SigV4 authentication and is not exported", gateway.id)
            return None
        gateway_data: dict[str, Any] = {
            "id": str(gateway.id),
            "visibility": getattr(gateway, "visibility", None) or "public",
            "name": gateway.name,
            "auth_type": gateway.auth_type,
            "gateway_mode": getattr(gateway, "gateway_mode", None),
            "url": str(gateway.url),
            "description": gateway.description,
            "transport": gateway.transport,
            "capabilities": gateway.capabilities or {},
            "is_active": gateway.enabled,
            "tags": gateway.tags or [],
            "passthrough_headers": gateway.passthrough_headers or [],
            "tool_validation_policy": gateway.tool_validation_policy,
        }
        if isinstance(query_auth, dict) and query_auth:
            gateway_data["auth_query_params"] = dict.fromkeys(query_auth)
        elif getattr(gateway, "auth_query_param_key", None):
            gateway_data["auth_query_param_key"] = getattr(gateway, "auth_query_param_key")
        if getattr(gateway, "client_cert", None) or getattr(gateway, "client_key", None) or gateway_requires_credentials(gateway):
            gateway_data["credentials_required"] = True
        gateway_data, _ = without_file_credentials(gateway_data)
        gateway_data["health_check"] = {"url": f"{gateway_data['url']}/health", "interval": 30, "timeout": 10, "retries": 3}
        return gateway_data

    @staticmethod
    def _export_tool_refs(
        db: Session, server_ids: List[str], user_email: Optional[str], token_teams: Optional[List[str]], *, include_inactive: bool = True
    ) -> tuple[Dict[str, List[Dict[str, Any]]], set[str]]:
        """Return visible tool references and server IDs with omitted bindings."""
        refs: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
        incomplete: set[str] = set()
        if not server_ids:
            return refs, incomplete
        assoc = server_tool_association

        def visible(model: type[DbTool] | type[DbGateway]) -> ColumnElement[bool]:
            """Build the visibility predicate for the tool or gateway join."""
            if token_teams is None:
                return or_(model.visibility != "private", and_(model.visibility == "private", model.owner_email == user_email) if user_email else false())
            return or_(
                model.visibility == "public",
                and_(model.visibility == "team", model.team_id.in_(token_teams)),
                and_(model.visibility == "private", model.owner_email == user_email) if token_teams and user_email else false(),
            )

        tool_filter = and_(DbTool.id == assoc.c.tool_id, visible(DbTool))
        if not include_inactive:
            tool_filter = and_(tool_filter, DbTool.enabled.is_(True))
        stmt = (
            select(assoc.c.server_id, DbTool.id, DbTool.original_name, DbTool.gateway_id, DbGateway.name, DbGateway.url, DbGateway.auth_query_params)
            .select_from(assoc)
            .outerjoin(DbTool, tool_filter)
            .outerjoin(DbGateway, and_(DbGateway.id == DbTool.gateway_id, visible(DbGateway)))
            .where(assoc.c.server_id.in_(server_ids))
            .order_by(assoc.c.server_id, DbTool.id)
        )
        for server_id, tool_id, name, gateway_id, gateway_name, gateway_url, gateway_query in db.execute(stmt):
            if tool_id is None or (gateway_id is not None and gateway_name is None):
                incomplete.add(str(server_id))
                continue
            ref: dict[str, Any] = {"id": str(tool_id), "original_name": name}
            if gateway_id is not None:
                safe_gateway, _ = without_file_credentials({"url": gateway_url, "auth_query_params": gateway_query})
                ref.update(gateway_id=str(gateway_id), gateway_name=gateway_name, gateway_url=safe_gateway["url"])
            refs[str(server_id)].append(ref)
        return refs, incomplete

    async def _export_servers(
        self, db: Session, tags: Optional[List[str]], include_inactive: bool, root_path: str = "", user_email: Optional[str] = None, token_teams: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """Export virtual servers with their tool associations.

        Args:
            db: Database session
            tags: Filter by tags
            include_inactive: Include inactive servers
            root_path: Root path for constructing API endpoints
            user_email: Requesting user's email for visibility filtering
            token_teams: Token team scope for visibility filtering

        Returns:
            List of exported server dictionaries
        """
        # Fetch all servers across all pages (with team-scoped visibility)
        servers = await self._fetch_all_servers(db, tags, include_inactive, user_email=user_email, token_teams=token_teams)
        exported_servers = []

        refs, incomplete = self._export_tool_refs(db, [str(server.id) for server in servers], user_email, token_teams, include_inactive=include_inactive)
        for server in servers:
            tool_refs = refs.get(str(server.id), [])
            server_data = {
                "name": server.name,
                "description": server.description,
                "instructions": getattr(server, "instructions", None),
                "visibility": getattr(server, "visibility", None) or "public",
                "tool_refs": tool_refs,
                "sse_endpoint": f"{root_path}/servers/{server.id}/sse",
                "websocket_endpoint": f"{root_path}/servers/{server.id}/ws",
                "jsonrpc_endpoint": f"{root_path}/servers/{server.id}/jsonrpc",
                "capabilities": {"tools": {"list_changed": True}, "prompts": {"list_changed": True}},
                "is_active": getattr(server, "enabled", getattr(server, "is_active", False)),
                "tags": server.tags or [],
            }

            if str(server.id) in incomplete:
                server_data["tool_refs_complete"] = False
            else:
                server_data["tool_ids"] = [ref["id"] for ref in tool_refs]
            exported_servers.append(server_data)

        return exported_servers

    async def _export_prompts(self, db: Session, tags: Optional[List[str]], include_inactive: bool, user_email: Optional[str] = None, token_teams: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Export prompts with their templates and schemas.

        Args:
            db: Database session
            tags: Filter by tags
            include_inactive: Include inactive prompts
            user_email: Requesting user's email for visibility filtering
            token_teams: Token team scope for visibility filtering

        Returns:
            List of exported prompt dictionaries
        """
        # Fetch all prompts across all pages (with team-scoped visibility)
        prompts = await self._fetch_all_prompts(db, tags, include_inactive, user_email=user_email, token_teams=token_teams)
        exported_prompts = []

        for prompt in prompts:
            input_schema: Dict[str, Any] = {"type": "object", "properties": {}, "required": []}
            prompt_data: Dict[str, Any] = {
                "name": getattr(prompt, "original_name", None) or prompt.name,
                "original_name": getattr(prompt, "original_name", None) or prompt.name,
                "custom_name": getattr(prompt, "custom_name", None) or getattr(prompt, "original_name", None) or prompt.name,
                "display_name": getattr(prompt, "display_name", None) or getattr(prompt, "custom_name", None) or getattr(prompt, "original_name", None) or prompt.name,
                "template": prompt.template,
                "description": prompt.description,
                "input_schema": input_schema,
                "id": str(prompt.id),
                "visibility": getattr(prompt, "visibility", None) or "public",
                "tags": prompt.tags or [],
                # Use the new `enabled` attribute on prompt objects but keep export key `is_active` for compatibility
                "is_active": getattr(prompt, "enabled", getattr(prompt, "is_active", False)),
            }

            # Convert arguments to input schema format
            if prompt.arguments:
                properties: Dict[str, Any] = {}
                required = []
                for arg in prompt.arguments:
                    properties[arg.name] = {"type": "string", "description": arg.description or ""}
                    if arg.required:
                        required.append(arg.name)
                input_schema["properties"] = properties
                input_schema["required"] = required

            if getattr(prompt, "gateway_id", None):
                prompt_data["gateway_id"] = str(prompt.gateway_id)
            exported_prompts.append(prompt_data)

        return exported_prompts

    async def _export_resources(
        self, db: Session, tags: Optional[List[str]], include_inactive: bool, user_email: Optional[str] = None, token_teams: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """Export resources with their content metadata.

        Args:
            db: Database session
            tags: Filter by tags
            include_inactive: Include inactive resources
            user_email: Requesting user's email for visibility filtering
            token_teams: Token team scope for visibility filtering

        Returns:
            List of exported resource dictionaries
        """
        # Fetch all resources across all pages (with team-scoped visibility)
        resources = await self._fetch_all_resources(db, tags, include_inactive, user_email=user_email, token_teams=token_teams)
        exported_resources = []

        for resource in resources:
            resource_data = {
                "name": _exportable_resource_base(resource),
                "uri": resource.uri,
                "description": resource.description,
                "mime_type": resource.mime_type,
                "id": str(resource.id),
                "visibility": getattr(resource, "visibility", None) or "public",
                "tags": resource.tags or [],
                "is_active": getattr(resource, "enabled", getattr(resource, "is_active", False)),
                "last_modified": resource.updated_at.isoformat() if resource.updated_at else None,
            }

            if resource.gateway_id is not None:
                resource_data.update(original_name=resource.original_name, custom_name_slug=resource.custom_name_slug, gateway_id=str(resource.gateway_id))
            exported_resources.append(resource_data)

        return exported_resources

    async def _export_roots(self) -> List[Dict[str, Any]]:
        """Export filesystem roots.

        Returns:
            List of exported root dictionaries
        """
        roots = await self.root_service.list_roots()
        exported_roots = []

        for root in roots:
            root_data = {"uri": str(root.uri), "name": root.name}
            exported_roots.append(root_data)

        return exported_roots

    async def _extract_dependencies(self, db: Session, entities: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:  # pylint: disable=unused-argument
        """Extract dependency relationships between entities.

        Args:
            db: Database session
            entities: Dictionary of exported entities

        Returns:
            Dictionary containing dependency mappings
        """
        dependencies: dict[str, dict[str, Any]] = {"servers_to_tools": {}, "servers_to_resources": {}, "servers_to_prompts": {}}

        # Extract server-to-tool dependencies
        if "servers" in entities and "tools" in entities:
            for server in entities["servers"]:
                if server.get("tool_ids"):
                    dependencies["servers_to_tools"][server["name"]] = server["tool_ids"]

        return dependencies

    def _validate_export_data(self, export_data: Dict[str, Any]) -> None:
        """Validate export data against the schema.

        Args:
            export_data: The export data to validate

        Raises:
            ExportValidationError: If validation fails
        """
        required_fields = ["version", "exported_at", "exported_by", "entities", "metadata"]

        for field in required_fields:
            if field not in export_data:
                raise ExportValidationError(f"Missing required field: {field}")

        # Validate version format
        if not export_data["version"]:
            raise ExportValidationError("Version cannot be empty")

        # Validate entities structure
        if not isinstance(export_data["entities"], dict):
            raise ExportValidationError("Entities must be a dictionary")

        # Validate metadata structure
        metadata = export_data["metadata"]
        if not isinstance(metadata.get("entity_counts"), dict):
            raise ExportValidationError("Metadata entity_counts must be a dictionary")

        logger.debug("Export data validation passed")

    async def export_selective(
        self,
        db: Session,
        entity_selections: Dict[str, List[str]],
        include_dependencies: bool = True,
        exported_by: str = "system",
        root_path: str = "",
        user_email: Optional[str] = None,
        token_teams: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Export specific entities by their IDs/names.

        Args:
            db: Database session
            entity_selections: Dict mapping entity types to lists of IDs/names to export
            include_dependencies: Whether to include dependent entities
            exported_by: Username of the person performing the export
            root_path: Root path for constructing API endpoints
            user_email: Requesting user's email for team-scoped visibility filtering
            token_teams: Token team scope for visibility filtering (None=admin bypass, []=public-only)

        Returns:
            Dict containing the selective export data

        Example:
            entity_selections = {
                "tools": ["tool1", "tool2"],
                "servers": ["server1"],
                "prompts": ["prompt1"]
            }
        """
        logger.info("Starting selective export by %s", exported_by)

        class SelExportOptions(TypedDict, total=False):
            """Options that control behavior for selective export."""

            selective: bool
            include_dependencies: bool
            selections: Dict[str, List[str]]

        class SelExportMetadata(TypedDict):
            """Metadata for selective export including counts, dependencies, and options."""

            entity_counts: Dict[str, int]
            dependencies: Dict[str, Any]
            export_options: SelExportOptions

        class SelExportData(TypedDict):
            """Top-level selective export payload shape."""

            version: str
            contextforge_version: str
            exported_at: str
            exported_by: str
            source_gateway: str
            encryption_method: str
            entities: Dict[str, List[Dict[str, Any]]]
            metadata: SelExportMetadata

        sel_entities: Dict[str, List[Dict[str, Any]]] = {}
        sel_metadata: SelExportMetadata = {
            "entity_counts": {},
            "dependencies": {},
            "export_options": {"selective": True, "include_dependencies": include_dependencies, "selections": entity_selections},
        }
        export_data: SelExportData = {
            "version": settings.protocol_version,
            "contextforge_version": __version__,
            "exported_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "exported_by": exported_by,
            "source_gateway": f"http://{settings.host}:{settings.port}",
            "encryption_method": "AES-256-GCM",
            "entities": sel_entities,
            "metadata": sel_metadata,
        }

        # Export selected entities for each type
        for entity_type, selected_ids in entity_selections.items():
            if entity_type == "tools":
                export_data["entities"]["tools"] = await self._export_selected_tools(db, selected_ids, user_email=user_email, token_teams=token_teams)
            elif entity_type == "gateways":
                export_data["entities"]["gateways"] = await self._export_selected_gateways(db, selected_ids, user_email=user_email, token_teams=token_teams)
            elif entity_type == "servers":
                export_data["entities"]["servers"] = await self._export_selected_servers(db, selected_ids, root_path, user_email=user_email, token_teams=token_teams)
            elif entity_type == "prompts":
                export_data["entities"]["prompts"] = await self._export_selected_prompts(db, selected_ids, user_email=user_email, token_teams=token_teams)
            elif entity_type == "resources":
                export_data["entities"]["resources"] = await self._export_selected_resources(db, selected_ids, user_email=user_email, token_teams=token_teams)
            elif entity_type == "roots":
                export_data["entities"]["roots"] = await self._export_selected_roots(selected_ids)

        # Add dependencies if requested
        if include_dependencies:
            export_data["metadata"]["dependencies"] = await self._extract_dependencies(db, export_data["entities"])

        # Calculate entity counts
        for entity_type, entities_list in export_data["entities"].items():
            export_data["metadata"]["entity_counts"][entity_type] = len(entities_list)

        self._validate_export_data(cast(Dict[str, Any], export_data))

        logger.info("Selective export completed with %s entities", sum(export_data["metadata"]["entity_counts"].values()))
        return cast(Dict[str, Any], export_data)

    @staticmethod
    def _is_scoped_selective_export(user_email: Optional[str], token_teams: Optional[List[str]]) -> bool:
        """Return whether selective export should apply visibility filtering.

        Args:
            user_email: Requesting user's email.
            token_teams: Token team scope for visibility filtering.

        Returns:
            ``True`` when selective export should apply team/public filtering.
        """
        return user_email is not None or token_teams is not None

    async def _export_selected_tools(self, db: Session, tool_ids: List[str], user_email: Optional[str] = None, token_teams: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Export specific tools by their IDs using batch queries.

        Uses a single batch query instead of fetching all tools N times.

        Args:
            db: Database session
            tool_ids: List of tool IDs to export
            user_email: Requesting user's email for visibility filtering
            token_teams: Token team scope for visibility filtering

        Returns:
            List of exported tool dictionaries
        """
        if not tool_ids:
            return []

        visible_tool_ids: Optional[set[str]] = None
        if self._is_scoped_selective_export(user_email, token_teams):
            visible_tools = await self._fetch_all_tools(db, tags=None, include_inactive=True, user_email=user_email, token_teams=token_teams)
            visible_tool_ids = {str(tool.id) for tool in visible_tools}
            tool_ids = [tool_id for tool_id in tool_ids if tool_id in visible_tool_ids]
            if not tool_ids:
                return []

        # Batch query for selected tools only
        db_tools = db.execute(select(DbTool).where(DbTool.id.in_(tool_ids))).scalars().all()
        if visible_tool_ids is not None:
            db_tools = [db_tool for db_tool in db_tools if str(db_tool.id) in visible_tool_ids]

        exported_tools = []
        for db_tool in db_tools:
            # Only export local REST tools, not MCP tools from gateways
            if db_tool.integration_type == "MCP" and db_tool.gateway_id:
                continue
            if db_tool.auth_type == "sigv4":
                logger.warning("Tool %s uses SigV4 authentication and is not exported: signing credentials are never written to export files", db_tool.id)
                continue

            tool_data = {
                "id": str(db_tool.id),
                "visibility": getattr(db_tool, "visibility", None) or "public",
                "auth_type": db_tool.auth_type,
                "name": db_tool.original_name or db_tool.custom_name,
                "displayName": db_tool.display_name,
                "url": str(db_tool.url) if db_tool.url else None,
                "integration_type": db_tool.integration_type,
                "request_type": db_tool.request_type,
                "description": db_tool.description,
                "headers": _portable_tool_headers(db_tool.headers),
                "input_schema": db_tool.input_schema or {"type": "object", "properties": {}},
                "output_schema": db_tool.output_schema,
                "annotations": db_tool.annotations or {},
                "jsonpath_filter": db_tool.jsonpath_filter,
                "tool_validation_policy": db_tool.tool_validation_policy,
                "tags": db_tool.tags or [],
                "rate_limit": getattr(db_tool, "rate_limit", None),
                "timeout": getattr(db_tool, "timeout", None),
                "is_active": db_tool.enabled,
                "created_at": db_tool.created_at.isoformat() if db_tool.created_at else None,
                "updated_at": db_tool.updated_at.isoformat() if db_tool.updated_at else None,
            }

            exported_tools.append(without_file_credentials(tool_data)[0])

        return exported_tools

    async def _export_selected_gateways(self, db: Session, gateway_ids: List[str], user_email: Optional[str] = None, token_teams: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Export specific gateways by their IDs using batch queries.

        Uses a single batch query instead of fetching all gateways N times.

        Args:
            db: Database session
            gateway_ids: List of gateway IDs to export
            user_email: Requesting user's email for visibility filtering
            token_teams: Token team scope for visibility filtering

        Returns:
            List of exported gateway dictionaries
        """
        if not gateway_ids:
            return []

        visible_gateway_ids: Optional[set[str]] = None
        if self._is_scoped_selective_export(user_email, token_teams):
            visible_gateways = await self._fetch_all_gateways(db, tags=None, include_inactive=True, user_email=user_email, token_teams=token_teams)
            visible_gateway_ids = {str(gateway.id) for gateway in visible_gateways}
            gateway_ids = [gateway_id for gateway_id in gateway_ids if gateway_id in visible_gateway_ids]
            if not gateway_ids:
                return []

        # Batch query for selected gateways only
        db_gateways = db.execute(select(DbGateway).where(DbGateway.id.in_(gateway_ids))).scalars().all()
        if visible_gateway_ids is not None:
            db_gateways = [db_gateway for db_gateway in db_gateways if str(db_gateway.id) in visible_gateway_ids]

        return [entry for gateway in db_gateways if (entry := self._gateway_export_entry(gateway, getattr(gateway, "auth_query_params", None))) is not None]

    async def _export_selected_servers(
        self, db: Session, server_ids: List[str], root_path: str = "", user_email: Optional[str] = None, token_teams: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """Export specific servers by their IDs using batch queries.

        Uses a single batch query instead of fetching all servers N times.

        Args:
            db: Database session
            server_ids: List of server IDs to export
            root_path: Root path for constructing API endpoints
            user_email: Requesting user's email for visibility filtering
            token_teams: Token team scope for visibility filtering

        Returns:
            List of exported server dictionaries
        """
        if not server_ids:
            return []

        visible_server_ids: Optional[set[str]] = None
        if self._is_scoped_selective_export(user_email, token_teams):
            visible_servers = await self._fetch_all_servers(db, tags=None, include_inactive=True, user_email=user_email, token_teams=token_teams)
            visible_server_ids = {str(server.id) for server in visible_servers}
            server_ids = [server_id for server_id in server_ids if server_id in visible_server_ids]
            if not server_ids:
                return []

        db_servers = db.execute(select(DbServer).where(DbServer.id.in_(server_ids))).scalars().all()
        if visible_server_ids is not None:
            db_servers = [db_server for db_server in db_servers if str(db_server.id) in visible_server_ids]

        exported_servers = []
        refs, incomplete = self._export_tool_refs(db, [str(server.id) for server in db_servers], user_email, token_teams, include_inactive=False)
        for db_server in db_servers:
            tool_refs = refs.get(str(db_server.id), [])
            server_data = {
                "name": db_server.name,
                "description": db_server.description,
                "instructions": getattr(db_server, "instructions", None),
                "visibility": getattr(db_server, "visibility", None) or "public",
                "tool_refs": tool_refs,
                "sse_endpoint": f"{root_path}/servers/{db_server.id}/sse",
                "websocket_endpoint": f"{root_path}/servers/{db_server.id}/ws",
                "jsonrpc_endpoint": f"{root_path}/servers/{db_server.id}/jsonrpc",
                "capabilities": {"tools": {"list_changed": True}, "prompts": {"list_changed": True}},
                "is_active": db_server.enabled,
                "tags": db_server.tags or [],
            }

            if str(db_server.id) in incomplete:
                server_data["tool_refs_complete"] = False
            else:
                server_data["tool_ids"] = [ref["id"] for ref in tool_refs]
            exported_servers.append(server_data)

        return exported_servers

    @staticmethod
    def _filter_visible_ids(visible_items: Iterable[Any], requested: Iterable[str], key_attrs: Sequence[str]) -> List[str]:
        """Return the IDs of visible items whose ``key_attrs`` match a requested identifier.

        Args:
            visible_items: Items the requesting principal may see.
            requested: Identifiers named in the selective export request.
            key_attrs: Item attributes compared against the requested identifiers.

        Returns:
            IDs of the visible items that match, as strings.
        """
        requested_set = set(requested)
        return [str(item.id) for item in visible_items if any(str(getattr(item, attr)) in requested_set for attr in key_attrs)]

    async def _export_selected_prompts(self, db: Session, prompt_names: List[str], user_email: Optional[str] = None, token_teams: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Export specific prompts by their identifiers using batch queries.

        Uses a single batch query instead of fetching all prompts N times.

        Args:
            db: Database session
            prompt_names: List of prompt IDs or names to export
            user_email: Requesting user's email for visibility filtering
            token_teams: Token team scope for visibility filtering

        Returns:
            List of exported prompt dictionaries
        """
        if not prompt_names:
            return []

        if self._is_scoped_selective_export(user_email, token_teams):
            visible_prompts = await self._fetch_all_prompts(db, tags=None, include_inactive=True, user_email=user_email, token_teams=token_teams)
            selected_ids = self._filter_visible_ids(visible_prompts, prompt_names, ("id", "name"))
            if not selected_ids:
                return []
            prompt_query = select(DbPrompt).where(DbPrompt.id.in_(selected_ids))
        else:
            prompt_query = select(DbPrompt).where(or_(DbPrompt.id.in_(prompt_names), DbPrompt.name.in_(prompt_names)))

        # Batch query for selected prompts only
        db_prompts = db.execute(prompt_query).scalars().all()

        exported_prompts = []
        for db_prompt in db_prompts:
            # Build input schema from argument_schema
            input_schema: Dict[str, Any] = {"type": "object", "properties": {}, "required": []}
            if db_prompt.argument_schema:
                input_schema = db_prompt.argument_schema

            prompt_data: Dict[str, Any] = {
                "name": db_prompt.original_name or db_prompt.name,
                "original_name": db_prompt.original_name or db_prompt.name,
                "custom_name": db_prompt.custom_name or db_prompt.original_name or db_prompt.name,
                "display_name": db_prompt.display_name or db_prompt.custom_name or db_prompt.original_name or db_prompt.name,
                "template": db_prompt.template,
                "description": db_prompt.description,
                "input_schema": input_schema,
                "id": str(db_prompt.id),
                "visibility": getattr(db_prompt, "visibility", None) or "public",
                "tags": db_prompt.tags or [],
                "is_active": getattr(db_prompt, "enabled", getattr(db_prompt, "is_active", False)),
            }

            if getattr(db_prompt, "gateway_id", None) and isinstance(db_prompt.gateway_id, str):
                prompt_data["gateway_id"] = db_prompt.gateway_id
            exported_prompts.append(prompt_data)

        return exported_prompts

    async def _export_selected_resources(self, db: Session, resource_uris: List[str], user_email: Optional[str] = None, token_teams: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Export specific resources by their URIs using batch queries.

        Uses a single batch query instead of fetching all resources N times.

        Args:
            db: Database session
            resource_uris: List of resource URIs to export
            user_email: Requesting user's email for visibility filtering
            token_teams: Token team scope for visibility filtering

        Returns:
            List of exported resource dictionaries
        """
        if not resource_uris:
            return []

        if self._is_scoped_selective_export(user_email, token_teams):
            visible_resources = await self._fetch_all_resources(db, tags=None, include_inactive=True, user_email=user_email, token_teams=token_teams)
            selected_ids = self._filter_visible_ids(visible_resources, resource_uris, ("uri",))
            if not selected_ids:
                return []
            resource_query = select(DbResource).where(DbResource.id.in_(selected_ids))
        else:
            resource_query = select(DbResource).where(DbResource.uri.in_(resource_uris))

        # Batch query for selected resources only
        db_resources = db.execute(resource_query).scalars().all()

        exported_resources = []
        for db_resource in db_resources:
            resource_data = {
                "name": _exportable_resource_base(db_resource),
                "uri": db_resource.uri,
                "description": db_resource.description,
                "mime_type": db_resource.mime_type,
                "id": str(db_resource.id),
                "visibility": getattr(db_resource, "visibility", None) or "public",
                "tags": db_resource.tags or [],
                "is_active": db_resource.enabled,
                "last_modified": db_resource.updated_at.isoformat() if db_resource.updated_at else None,
            }

            if db_resource.gateway_id is not None:
                resource_data.update(original_name=db_resource.original_name, custom_name_slug=db_resource.custom_name_slug, gateway_id=str(db_resource.gateway_id))
            exported_resources.append(resource_data)

        return exported_resources

    async def _export_selected_roots(self, root_uris: List[str]) -> List[Dict[str, Any]]:
        """Export specific roots by their URIs.

        Args:
            root_uris: List of root URIs to export

        Returns:
            List of exported root dictionaries
        """
        all_roots = await self._export_roots()
        return [r for r in all_roots if r["uri"] in root_uris]
