# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/export_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Export Service Implementation.
This module implements comprehensive configuration export functionality according to the export specification.
It handles:
- Entity collection from all entity types (Tools, Gateways, Servers, Prompts, Resources, Roots)
- Secure authentication data encryption using AES-256-GCM
- Dependency resolution and inclusion
- Filtering by entity types, tags, and active/inactive status
- Export format validation and schema compliance
- Only exports locally configured entities (not federated content)
"""

# Standard
from datetime import datetime, timezone
import logging
from typing import Any, cast, Dict, List, Optional, TypedDict

# Third-Party
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import Prompt as DbPrompt
from mcpgateway.db import Resource as DbResource
from mcpgateway.db import Server as DbServer
from mcpgateway.db import Tool as DbTool
from mcpgateway.services.gateway_service import GatewayService
from mcpgateway.services.prompt_service import PromptService
from mcpgateway.services.resource_service import ResourceService
from mcpgateway.services.root_service import RootService
from mcpgateway.services.server_service import ServerService
from mcpgateway.services.tool_service import ToolService

logger = logging.getLogger(__name__)


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
    """Service for exporting MCP Gateway configuration and data.

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

    def __init__(self):
        """Initialize the export service with required dependencies."""
        self.gateway_service = GatewayService()
        self.tool_service = ToolService()
        self.resource_service = ResourceService()
        self.prompt_service = PromptService()
        self.server_service = ServerService()
        self.root_service = RootService()

    async def initialize(self) -> None:
        """Initialize the export service."""
        logger.info("Export service initialized")

    async def shutdown(self) -> None:
        """Shutdown the export service."""
        logger.info("Export service shutdown")

    async def _fetch_all_tools(self, db: Session, tags: Optional[List[str]], include_inactive: bool) -> List[Any]:
        """Fetch all tools by following pagination cursors.

        Args:
            db: Database session
            tags: Filter by tags
            include_inactive: Include inactive tools

        Returns:
            List of all tools across all pages
        """
        all_tools = []
        cursor = None
        while True:
            tools, next_cursor = await self.tool_service.list_tools(db, tags=tags, include_inactive=include_inactive, cursor=cursor)
            all_tools.extend(tools)
            if not next_cursor:
                break
            cursor = next_cursor
        return all_tools

    async def _fetch_all_prompts(self, db: Session, tags: Optional[List[str]], include_inactive: bool) -> List[Any]:
        """Fetch all prompts by following pagination cursors.

        Args:
            db: Database session
            tags: Filter by tags
            include_inactive: Include inactive prompts

        Returns:
            List of all prompts across all pages
        """
        all_prompts = []
        cursor = None
        while True:
            prompts, next_cursor = await self.prompt_service.list_prompts(db, tags=tags, include_inactive=include_inactive, cursor=cursor)
            all_prompts.extend(prompts)
            if not next_cursor:
                break
            cursor = next_cursor
        return all_prompts

    async def _fetch_all_resources(self, db: Session, tags: Optional[List[str]], include_inactive: bool) -> List[Any]:
        """Fetch all resources by following pagination cursors.

        Args:
            db: Database session
            tags: Filter by tags
            include_inactive: Include inactive resources

        Returns:
            List of all resources across all pages
        """
        all_resources = []
        cursor = None
        while True:
            resources, next_cursor = await self.resource_service.list_resources(db, tags=tags, include_inactive=include_inactive, cursor=cursor)
            all_resources.extend(resources)
            if not next_cursor:
                break
            cursor = next_cursor
        return all_resources

    async def _fetch_all_gateways(self, db: Session, tags: Optional[List[str]], include_inactive: bool) -> List[Any]:
        """Fetch all gateways by following pagination cursors.

        Args:
            db: Database session
            tags: Filter by tags
            include_inactive: Include inactive gateways

        Returns:
            List of all gateways across all pages
        """
        all_gateways = []
        cursor = None
        while True:
            gateways, next_cursor = await self.gateway_service.list_gateways(db, tags=tags, include_inactive=include_inactive, cursor=cursor)
            all_gateways.extend(gateways)
            if not next_cursor:
                break
            cursor = next_cursor
        return all_gateways

    async def _fetch_all_servers(self, db: Session, tags: Optional[List[str]], include_inactive: bool) -> List[Any]:
        """Fetch all servers by following pagination cursors.

        Args:
            db: Database session
            tags: Filter by tags
            include_inactive: Include inactive servers

        Returns:
            List of all servers across all pages
        """
        all_servers = []
        cursor = None
        while True:
            servers, next_cursor = await self.server_service.list_servers(db, tags=tags, include_inactive=include_inactive, cursor=cursor)
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

        Returns:
            Dict containing the complete export data in the specified schema format

        Raises:
            ExportError: If export fails
            ExportValidationError: If validation fails
        """
        try:
            logger.info(f"Starting configuration export by {exported_by}")

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
                "exported_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "exported_by": exported_by,
                "source_gateway": f"http://{settings.host}:{settings.port}",
                "encryption_method": "AES-256-GCM",
                "entities": entities,
                "metadata": metadata,
            }

            # Export each entity type
            if "tools" in entity_types:
                export_data["entities"]["tools"] = await self._export_tools(db, tags, include_inactive)

            if "gateways" in entity_types:
                export_data["entities"]["gateways"] = await self._export_gateways(db, tags, include_inactive)

            if "servers" in entity_types:
                export_data["entities"]["servers"] = await self._export_servers(db, tags, include_inactive, root_path)

            if "prompts" in entity_types:
                export_data["entities"]["prompts"] = await self._export_prompts(db, tags, include_inactive)

            if "resources" in entity_types:
                export_data["entities"]["resources"] = await self._export_resources(db, tags, include_inactive)

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

            logger.info(f"Export completed successfully with {sum(export_data['metadata']['entity_counts'].values())} total entities")
            return cast(Dict[str, Any], export_data)

        except Exception as e:
            logger.error(f"Export failed: {str(e)}")
            raise ExportError(f"Failed to export configuration: {str(e)}")

    async def _export_tools(self, db: Session, tags: Optional[List[str]], include_inactive: bool) -> List[Dict[str, Any]]:
        """Export tools with encrypted authentication data.

        Uses batch queries to fetch auth data efficiently, avoiding N+1 query patterns.

        Args:
            db: Database session
            tags: Filter by tags
            include_inactive: Include inactive tools

        Returns:
            List of exported tool dictionaries
        """
        # Fetch all tools across all pages (bypasses pagination limit)
        tools = await self._fetch_all_tools(db, tags, include_inactive)

        # Filter to only exportable tools (local REST tools, not MCP tools from gateways)
        exportable_tools = [t for t in tools if not (t.integration_type == "MCP" and t.gateway_id)]

        # Batch fetch auth data for tools with masked values (single query instead of N queries)
        tool_ids_needing_auth = [
            tool.id for tool in exportable_tools if hasattr(tool, "auth") and tool.auth and hasattr(tool.auth, "auth_value") and tool.auth.auth_value == settings.masked_auth_value
        ]

        auth_data_map: Dict[Any, tuple] = {}
        if tool_ids_needing_auth:
            db_tools_with_auth = db.execute(select(DbTool.id, DbTool.auth_type, DbTool.auth_value).where(DbTool.id.in_(tool_ids_needing_auth))).all()
            auth_data_map = {row[0]: (row[1], row[2]) for row in db_tools_with_auth}

        exported_tools = []
        for tool in exportable_tools:
            tool_data = {
                "name": tool.original_name,  # Use original name, not the slugified version
                "displayName": tool.displayName,  # Export displayName field from ToolRead
                "url": str(tool.url),
                "integration_type": tool.integration_type,
                "request_type": tool.request_type,
                "description": tool.description,
                "headers": tool.headers or {},
                "input_schema": tool.input_schema or {"type": "object", "properties": {}},
                "output_schema": tool.output_schema,
                "annotations": tool.annotations or {},
                "jsonpath_filter": tool.jsonpath_filter,
                "tags": tool.tags or [],
                "rate_limit": getattr(tool, "rate_limit", None),
                "timeout": getattr(tool, "timeout", None),
                "is_active": tool.enabled,
                "created_at": tool.created_at.isoformat() if hasattr(tool.created_at, "isoformat") and tool.created_at else None,
                "updated_at": tool.updated_at.isoformat() if hasattr(tool.updated_at, "isoformat") and tool.updated_at else None,
            }

            # Handle authentication data securely - use batch-fetched values
            if hasattr(tool, "auth") and tool.auth:
                auth = tool.auth
                if hasattr(auth, "auth_type") and hasattr(auth, "auth_value"):
                    if auth.auth_value == settings.masked_auth_value:
                        # Use batch-fetched auth data
                        if tool.id in auth_data_map:
                            auth_type, auth_value = auth_data_map[tool.id]
                            if auth_value:
                                tool_data["auth_type"] = auth_type
                                tool_data["auth_value"] = auth_value
                    else:
                        # Auth value is not masked, use as-is
                        tool_data["auth_type"] = auth.auth_type
                        tool_data["auth_value"] = auth.auth_value

            exported_tools.append(tool_data)

        return exported_tools

    async def _export_gateways(self, db: Session, tags: Optional[List[str]], include_inactive: bool) -> List[Dict[str, Any]]:
        """Export gateways with encrypted authentication data.

        Uses batch queries to fetch auth data efficiently, avoiding N+1 query patterns.

        Args:
            db: Database session
            tags: Filter by tags
            include_inactive: Include inactive gateways

        Returns:
            List of exported gateway dictionaries
        """
        # Fetch all gateways across all pages (bypasses pagination limit)
        gateways = await self._fetch_all_gateways(db, tags, include_inactive)

        # Batch fetch auth data for gateways with masked values (single query instead of N queries)
        gateway_ids_needing_auth = [g.id for g in gateways if g.auth_type and g.auth_value == settings.masked_auth_value]

        auth_data_map: Dict[Any, tuple] = {}
        if gateway_ids_needing_auth:
            db_gateways_with_auth = db.execute(select(DbGateway.id, DbGateway.auth_type, DbGateway.auth_value).where(DbGateway.id.in_(gateway_ids_needing_auth))).all()
            auth_data_map = {row[0]: (row[1], row[2]) for row in db_gateways_with_auth}

        exported_gateways = []
        for gateway in gateways:
            gateway_data = {
                "name": gateway.name,
                "url": str(gateway.url),
                "description": gateway.description,
                "transport": gateway.transport,
                "capabilities": gateway.capabilities or {},
                "health_check": {"url": f"{gateway.url}/health", "interval": 30, "timeout": 10, "retries": 3},
                "is_active": gateway.enabled,
                "federation_enabled": True,
                "tags": gateway.tags or [],
                "passthrough_headers": gateway.passthrough_headers or [],
            }

            # Handle authentication data securely - use batch-fetched values
            if gateway.auth_type and gateway.auth_value:
                if gateway.auth_value == settings.masked_auth_value:
                    # Use batch-fetched auth data
                    if gateway.id in auth_data_map:
                        auth_type, auth_value = auth_data_map[gateway.id]
                        if auth_value:
                            gateway_data["auth_type"] = auth_type
                            gateway_data["auth_value"] = auth_value
                else:
                    # Auth value is not masked, use as-is
                    gateway_data["auth_type"] = gateway.auth_type
                    gateway_data["auth_value"] = gateway.auth_value

            exported_gateways.append(gateway_data)

        return exported_gateways

    async def _export_servers(self, db: Session, tags: Optional[List[str]], include_inactive: bool, root_path: str = "") -> List[Dict[str, Any]]:
        """Export virtual servers with their tool associations.

        Args:
            db: Database session
            tags: Filter by tags
            include_inactive: Include inactive servers
            root_path: Root path for constructing API endpoints

        Returns:
            List of exported server dictionaries
        """
        # Fetch all servers across all pages (bypasses pagination limit)
        servers = await self._fetch_all_servers(db, tags, include_inactive)
        exported_servers = []

        for server in servers:
            server_data = {
                "name": server.name,
                "description": server.description,
                "tool_ids": list(server.associated_tools),
                "sse_endpoint": f"{root_path}/servers/{server.id}/sse",
                "websocket_endpoint": f"{root_path}/servers/{server.id}/ws",
                "jsonrpc_endpoint": f"{root_path}/servers/{server.id}/jsonrpc",
                "capabilities": {"tools": {"list_changed": True}, "prompts": {"list_changed": True}},
                "is_active": getattr(server, "enabled", getattr(server, "is_active", False)),
                "tags": server.tags or [],
            }

            exported_servers.append(server_data)

        return exported_servers

    async def _export_prompts(self, db: Session, tags: Optional[List[str]], include_inactive: bool) -> List[Dict[str, Any]]:
        """Export prompts with their templates and schemas.

        Args:
            db: Database session
            tags: Filter by tags
            include_inactive: Include inactive prompts

        Returns:
            List of exported prompt dictionaries
        """
        # Fetch all prompts across all pages (bypasses pagination limit)
        prompts = await self._fetch_all_prompts(db, tags, include_inactive)
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

            exported_prompts.append(prompt_data)

        return exported_prompts

    async def _export_resources(self, db: Session, tags: Optional[List[str]], include_inactive: bool) -> List[Dict[str, Any]]:
        """Export resources with their content metadata.

        Args:
            db: Database session
            tags: Filter by tags
            include_inactive: Include inactive resources

        Returns:
            List of exported resource dictionaries
        """
        # Fetch all resources across all pages (bypasses pagination limit)
        resources = await self._fetch_all_resources(db, tags, include_inactive)
        exported_resources = []

        for resource in resources:
            resource_data = {
                "name": resource.name,
                "uri": resource.uri,
                "description": resource.description,
                "mime_type": resource.mime_type,
                "tags": resource.tags or [],
                "is_active": getattr(resource, "enabled", getattr(resource, "is_active", False)),
                "last_modified": resource.updated_at.isoformat() if resource.updated_at else None,
            }

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
        dependencies = {"servers_to_tools": {}, "servers_to_resources": {}, "servers_to_prompts": {}}

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

    async def export_selective(self, db: Session, entity_selections: Dict[str, List[str]], include_dependencies: bool = True, exported_by: str = "system", root_path: str = "") -> Dict[str, Any]:
        """Export specific entities by their IDs/names.

        Args:
            db: Database session
            entity_selections: Dict mapping entity types to lists of IDs/names to export
            include_dependencies: Whether to include dependent entities
            exported_by: Username of the person performing the export
            root_path: Root path for constructing API endpoints

        Returns:
            Dict containing the selective export data

        Example:
            entity_selections = {
                "tools": ["tool1", "tool2"],
                "servers": ["server1"],
                "prompts": ["prompt1"]
            }
        """
        logger.info(f"Starting selective export by {exported_by}")

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
                export_data["entities"]["tools"] = await self._export_selected_tools(db, selected_ids)
            elif entity_type == "gateways":
                export_data["entities"]["gateways"] = await self._export_selected_gateways(db, selected_ids)
            elif entity_type == "servers":
                export_data["entities"]["servers"] = await self._export_selected_servers(db, selected_ids, root_path)
            elif entity_type == "prompts":
                export_data["entities"]["prompts"] = await self._export_selected_prompts(db, selected_ids)
            elif entity_type == "resources":
                export_data["entities"]["resources"] = await self._export_selected_resources(db, selected_ids)
            elif entity_type == "roots":
                export_data["entities"]["roots"] = await self._export_selected_roots(selected_ids)

        # Add dependencies if requested
        if include_dependencies:
            export_data["metadata"]["dependencies"] = await self._extract_dependencies(db, export_data["entities"])

        # Calculate entity counts
        for entity_type, entities_list in export_data["entities"].items():
            export_data["metadata"]["entity_counts"][entity_type] = len(entities_list)

        self._validate_export_data(cast(Dict[str, Any], export_data))

        logger.info(f"Selective export completed with {sum(export_data['metadata']['entity_counts'].values())} entities")
        return cast(Dict[str, Any], export_data)

    async def _export_selected_tools(self, db: Session, tool_ids: List[str]) -> List[Dict[str, Any]]:
        """Export specific tools by their IDs using batch queries.

        Uses a single batch query instead of fetching all tools N times.

        Args:
            db: Database session
            tool_ids: List of tool IDs to export

        Returns:
            List of exported tool dictionaries
        """
        if not tool_ids:
            return []

        # Batch query for selected tools only
        db_tools = db.execute(select(DbTool).where(DbTool.id.in_(tool_ids))).scalars().all()

        exported_tools = []
        for db_tool in db_tools:
            # Only export local REST tools, not MCP tools from gateways
            if db_tool.integration_type == "MCP" and db_tool.gateway_id:
                continue

            tool_data = {
                "name": db_tool.original_name or db_tool.custom_name,
                "displayName": db_tool.display_name,
                "url": str(db_tool.url) if db_tool.url else None,
                "integration_type": db_tool.integration_type,
                "request_type": db_tool.request_type,
                "description": db_tool.description,
                "headers": db_tool.headers or {},
                "input_schema": db_tool.input_schema or {"type": "object", "properties": {}},
                "output_schema": db_tool.output_schema,
                "annotations": db_tool.annotations or {},
                "jsonpath_filter": db_tool.jsonpath_filter,
                "tags": db_tool.tags or [],
                "rate_limit": db_tool.rate_limit,
                "timeout": db_tool.timeout,
                "is_active": db_tool.is_active,
                "created_at": db_tool.created_at.isoformat() if db_tool.created_at else None,
                "updated_at": db_tool.updated_at.isoformat() if db_tool.updated_at else None,
            }

            # Include auth data directly from DB (already have raw values)
            if db_tool.auth_type and db_tool.auth_value:
                tool_data["auth_type"] = db_tool.auth_type
                tool_data["auth_value"] = db_tool.auth_value

            exported_tools.append(tool_data)

        return exported_tools

    async def _export_selected_gateways(self, db: Session, gateway_ids: List[str]) -> List[Dict[str, Any]]:
        """Export specific gateways by their IDs using batch queries.

        Uses a single batch query instead of fetching all gateways N times.

        Args:
            db: Database session
            gateway_ids: List of gateway IDs to export

        Returns:
            List of exported gateway dictionaries
        """
        if not gateway_ids:
            return []

        # Batch query for selected gateways only
        db_gateways = db.execute(select(DbGateway).where(DbGateway.id.in_(gateway_ids))).scalars().all()

        exported_gateways = []
        for db_gateway in db_gateways:
            gateway_data = {
                "name": db_gateway.name,
                "url": str(db_gateway.url) if db_gateway.url else None,
                "description": db_gateway.description,
                "transport": db_gateway.transport,
                "capabilities": db_gateway.capabilities or {},
                "health_check": {"url": f"{db_gateway.url}/health", "interval": 30, "timeout": 10, "retries": 3},
                "is_active": db_gateway.is_active,
                "federation_enabled": True,
                "tags": db_gateway.tags or [],
                "passthrough_headers": db_gateway.passthrough_headers or [],
            }

            # Include auth data directly from DB (already have raw values)
            if db_gateway.auth_type and db_gateway.auth_value:
                gateway_data["auth_type"] = db_gateway.auth_type
                gateway_data["auth_value"] = db_gateway.auth_value

            exported_gateways.append(gateway_data)

        return exported_gateways

    async def _export_selected_servers(self, db: Session, server_ids: List[str], root_path: str = "") -> List[Dict[str, Any]]:
        """Export specific servers by their IDs using batch queries.

        Uses a single batch query instead of fetching all servers N times.

        Args:
            db: Database session
            server_ids: List of server IDs to export
            root_path: Root path for constructing API endpoints

        Returns:
            List of exported server dictionaries
        """
        if not server_ids:
            return []

        # Batch query for selected servers only
        db_servers = db.execute(select(DbServer).where(DbServer.id.in_(server_ids))).scalars().all()

        exported_servers = []
        for db_server in db_servers:
            # Get associated tool IDs
            tool_ids = [str(tool.id) for tool in db_server.tools] if db_server.tools else []

            server_data = {
                "name": db_server.name,
                "description": db_server.description,
                "tool_ids": tool_ids,
                "sse_endpoint": f"{root_path}/servers/{db_server.id}/sse",
                "websocket_endpoint": f"{root_path}/servers/{db_server.id}/ws",
                "jsonrpc_endpoint": f"{root_path}/servers/{db_server.id}/jsonrpc",
                "capabilities": {"tools": {"list_changed": True}, "prompts": {"list_changed": True}},
                "is_active": db_server.is_active,
                "tags": db_server.tags or [],
            }

            exported_servers.append(server_data)

        return exported_servers

    async def _export_selected_prompts(self, db: Session, prompt_names: List[str]) -> List[Dict[str, Any]]:
        """Export specific prompts by their identifiers using batch queries.

        Uses a single batch query instead of fetching all prompts N times.

        Args:
            db: Database session
            prompt_names: List of prompt IDs or names to export

        Returns:
            List of exported prompt dictionaries
        """
        if not prompt_names:
            return []

        # Batch query for selected prompts only
        db_prompts = db.execute(select(DbPrompt).where(or_(DbPrompt.id.in_(prompt_names), DbPrompt.name.in_(prompt_names)))).scalars().all()

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
                "tags": db_prompt.tags or [],
                "is_active": getattr(db_prompt, "enabled", getattr(db_prompt, "is_active", False)),
            }

            exported_prompts.append(prompt_data)

        return exported_prompts

    async def _export_selected_resources(self, db: Session, resource_uris: List[str]) -> List[Dict[str, Any]]:
        """Export specific resources by their URIs using batch queries.

        Uses a single batch query instead of fetching all resources N times.

        Args:
            db: Database session
            resource_uris: List of resource URIs to export

        Returns:
            List of exported resource dictionaries
        """
        if not resource_uris:
            return []

        # Batch query for selected resources only
        db_resources = db.execute(select(DbResource).where(DbResource.uri.in_(resource_uris))).scalars().all()

        exported_resources = []
        for db_resource in db_resources:
            resource_data = {
                "name": db_resource.name,
                "uri": db_resource.uri,
                "description": db_resource.description,
                "mime_type": db_resource.mime_type,
                "tags": db_resource.tags or [],
                "is_active": db_resource.is_active,
                "last_modified": db_resource.updated_at.isoformat() if db_resource.updated_at else None,
            }

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
