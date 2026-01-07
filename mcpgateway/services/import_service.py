# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/import_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Import Service Implementation.
This module implements comprehensive configuration import functionality according to the import specification.
It handles:
- Import file validation and schema compliance
- Entity creation and updates with conflict resolution
- Dependency resolution and processing order
- Authentication data decryption and re-encryption
- Dry-run functionality for validation
- Cross-environment key rotation support
- Import status tracking and progress reporting
"""

# Standard
import base64
from datetime import datetime, timedelta, timezone
from enum import Enum
import logging
from typing import Any, Dict, List, Optional
import uuid

# Third-Party
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import A2AAgent, EmailUser, Gateway, Prompt, Resource, Server, Tool
from mcpgateway.schemas import AuthenticationValues, GatewayCreate, GatewayUpdate, PromptCreate, PromptUpdate, ResourceCreate, ResourceUpdate, ServerCreate, ServerUpdate, ToolCreate, ToolUpdate
from mcpgateway.services.gateway_service import GatewayNameConflictError, GatewayService
from mcpgateway.services.prompt_service import PromptNameConflictError, PromptService
from mcpgateway.services.resource_service import ResourceService, ResourceURIConflictError
from mcpgateway.services.root_service import RootService
from mcpgateway.services.server_service import ServerNameConflictError, ServerService
from mcpgateway.services.tool_service import ToolNameConflictError, ToolService
from mcpgateway.utils.services_auth import decode_auth, encode_auth

logger = logging.getLogger(__name__)


class ConflictStrategy(str, Enum):
    """Strategies for handling conflicts during import.

    Examples:
        >>> ConflictStrategy.SKIP.value
        'skip'
        >>> ConflictStrategy.UPDATE.value
        'update'
        >>> ConflictStrategy.RENAME.value
        'rename'
        >>> ConflictStrategy.FAIL.value
        'fail'
        >>> ConflictStrategy("update")
        <ConflictStrategy.UPDATE: 'update'>
    """

    SKIP = "skip"
    UPDATE = "update"
    RENAME = "rename"
    FAIL = "fail"


class ImportError(Exception):  # pylint: disable=redefined-builtin
    """Base class for import-related errors.

    Examples:
        >>> error = ImportError("Something went wrong")
        >>> str(error)
        'Something went wrong'
        >>> isinstance(error, Exception)
        True
    """


class ImportValidationError(ImportError):
    """Raised when import data validation fails.

    Examples:
        >>> error = ImportValidationError("Invalid schema")
        >>> str(error)
        'Invalid schema'
        >>> isinstance(error, ImportError)
        True
    """


class ImportConflictError(ImportError):
    """Raised when import conflicts cannot be resolved.

    Examples:
        >>> error = ImportConflictError("Name conflict: tool_name")
        >>> str(error)
        'Name conflict: tool_name'
        >>> isinstance(error, ImportError)
        True
    """


class ImportStatus:
    """Tracks the status of an import operation."""

    def __init__(self, import_id: str):
        """Initialize import status tracking.

        Args:
            import_id: Unique identifier for the import operation

        Examples:
            >>> status = ImportStatus("import_123")
            >>> status.import_id
            'import_123'
            >>> status.status
            'pending'
            >>> status.total_entities
            0
        """
        self.import_id = import_id
        self.status = "pending"
        self.total_entities = 0
        self.processed_entities = 0
        self.created_entities = 0
        self.updated_entities = 0
        self.skipped_entities = 0
        self.failed_entities = 0
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.started_at = datetime.now(timezone.utc)
        self.completed_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert status to dictionary for API responses.

        Returns:
            Dictionary representation of import status
        """
        return {
            "import_id": self.import_id,
            "status": self.status,
            "progress": {
                "total": self.total_entities,
                "processed": self.processed_entities,
                "created": self.created_entities,
                "updated": self.updated_entities,
                "skipped": self.skipped_entities,
                "failed": self.failed_entities,
            },
            "errors": self.errors,
            "warnings": self.warnings,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class ImportService:
    """Service for importing MCP Gateway configuration and data.

    This service provides comprehensive import functionality including:
    - Import file validation and schema compliance
    - Entity creation and updates with conflict resolution
    - Dependency resolution and correct processing order
    - Secure authentication data handling with re-encryption
    - Dry-run capabilities for validation without changes
    - Progress tracking and status reporting
    - Cross-environment key rotation support
    """

    def __init__(self):
        """Initialize the import service with required dependencies.

        Creates instances of all entity services and initializes the active imports tracker.

        Examples:
            >>> service = ImportService()
            >>> service.active_imports
            {}
            >>> hasattr(service, 'tool_service')
            True
            >>> hasattr(service, 'gateway_service')
            True
        """
        self.gateway_service = GatewayService()
        self.tool_service = ToolService()
        self.resource_service = ResourceService()
        self.prompt_service = PromptService()
        self.server_service = ServerService()
        self.root_service = RootService()
        self.active_imports: Dict[str, ImportStatus] = {}

    async def initialize(self) -> None:
        """Initialize the import service."""
        logger.info("Import service initialized")

    async def shutdown(self) -> None:
        """Shutdown the import service."""
        logger.info("Import service shutdown")

    def validate_import_data(self, import_data: Dict[str, Any]) -> None:
        """Validate import data against the expected schema.

        Args:
            import_data: The import data to validate

        Raises:
            ImportValidationError: If validation fails

        Examples:
            >>> service = ImportService()
            >>> valid_data = {
            ...     "version": "2025-03-26",
            ...     "exported_at": "2025-01-01T00:00:00Z",
            ...     "entities": {"tools": []}
            ... }
            >>> service.validate_import_data(valid_data)  # Should not raise

            >>> invalid_data = {"missing": "version"}
            >>> try:
            ...     service.validate_import_data(invalid_data)
            ... except ImportValidationError as e:
            ...     "Missing required field" in str(e)
            True
        """
        logger.debug("Validating import data structure")

        # Check required top-level fields
        required_fields = ["version", "exported_at", "entities"]
        for field in required_fields:
            if field not in import_data:
                raise ImportValidationError(f"Missing required field: {field}")

        # Validate version compatibility
        if not import_data.get("version"):
            raise ImportValidationError("Version field cannot be empty")

        # Validate entities structure
        entities = import_data.get("entities", {})
        if not isinstance(entities, dict):
            raise ImportValidationError("Entities must be a dictionary")

        # Validate each entity type
        valid_entity_types = ["tools", "gateways", "servers", "prompts", "resources", "roots"]
        for entity_type, entity_list in entities.items():
            if entity_type not in valid_entity_types:
                raise ImportValidationError(f"Unknown entity type: {entity_type}")

            if not isinstance(entity_list, list):
                raise ImportValidationError(f"Entity type '{entity_type}' must be a list")

            # Validate individual entities
            for i, entity in enumerate(entity_list):
                if not isinstance(entity, dict):
                    raise ImportValidationError(f"Entity {i} in '{entity_type}' must be a dictionary")

                # Check required fields based on entity type
                self._validate_entity_fields(entity_type, entity, i)

        logger.debug("Import data validation passed")

    def _validate_entity_fields(self, entity_type: str, entity: Dict[str, Any], index: int) -> None:
        """Validate required fields for a specific entity type.

        Args:
            entity_type: Type of entity (tools, gateways, etc.)
            entity: Entity data dictionary
            index: Index of entity in list for error messages

        Raises:
            ImportValidationError: If required fields are missing
        """
        required_fields = {
            "tools": ["name", "url", "integration_type"],
            "gateways": ["name", "url"],
            "servers": ["name"],
            "prompts": ["name", "template"],
            "resources": ["name", "uri"],
            "roots": ["uri", "name"],
        }

        if entity_type in required_fields:
            for field in required_fields[entity_type]:
                if field not in entity:
                    raise ImportValidationError(f"Entity {index} in '{entity_type}' missing required field: {field}")

    async def import_configuration(
        self,
        db: Session,
        import_data: Dict[str, Any],
        conflict_strategy: ConflictStrategy = ConflictStrategy.UPDATE,
        dry_run: bool = False,
        rekey_secret: Optional[str] = None,
        imported_by: str = "system",
        selected_entities: Optional[Dict[str, List[str]]] = None,
    ) -> ImportStatus:
        """Import configuration data with conflict resolution.

        Args:
            db: Database session
            import_data: The validated import data
            conflict_strategy: How to handle naming conflicts
            dry_run: If True, validate but don't make changes
            rekey_secret: New encryption secret for cross-environment imports
            imported_by: Username of the person performing the import
            selected_entities: Dict of entity types to specific entity names/ids to import

        Returns:
            ImportStatus: Status object tracking import progress and results

        Raises:
            ImportError: If import fails
        """
        import_id = str(uuid.uuid4())
        status = ImportStatus(import_id)
        self.active_imports[import_id] = status

        try:
            logger.info(f"Starting configuration import {import_id} by {imported_by} (dry_run={dry_run})")

            # Validate import data
            self.validate_import_data(import_data)

            # Calculate total entities to process
            entities = import_data.get("entities", {})
            status.total_entities = self._calculate_total_entities(entities, selected_entities)

            status.status = "running"

            # Process entities in dependency order
            processing_order = ["roots", "gateways", "tools", "resources", "prompts", "servers"]

            for entity_type in processing_order:
                if entity_type in entities:
                    await self._process_entities(db, entity_type, entities[entity_type], conflict_strategy, dry_run, rekey_secret, status, selected_entities, imported_by)
                    # Flush after each entity type to make records visible for associations
                    if not dry_run:
                        db.flush()

            # Assign all imported items to user's team with public visibility (after all entities processed)
            if not dry_run:
                await self._assign_imported_items_to_team(db, imported_by)

            # Mark as completed
            status.status = "completed"
            status.completed_at = datetime.now(timezone.utc)

            logger.info(f"Import {import_id} completed: created={status.created_entities}, updated={status.updated_entities}, skipped={status.skipped_entities}, failed={status.failed_entities}")

            return status

        except Exception as e:
            status.status = "failed"
            status.completed_at = datetime.now(timezone.utc)
            status.errors.append(f"Import failed: {str(e)}")
            logger.error(f"Import {import_id} failed: {str(e)}")
            raise ImportError(f"Import failed: {str(e)}")

    def _get_entity_identifier(self, entity_type: str, entity: Dict[str, Any]) -> str:
        """Get the unique identifier for an entity based on its type.

        Args:
            entity_type: Type of entity
            entity: Entity data dictionary

        Returns:
            Unique identifier string for the entity

        Examples:
            >>> service = ImportService()
            >>> tool_entity = {"name": "my_tool", "url": "https://example.com"}
            >>> service._get_entity_identifier("tools", tool_entity)
            'my_tool'

            >>> resource_entity = {"name": "my_resource", "uri": "/api/data"}
            >>> service._get_entity_identifier("resources", resource_entity)
            '/api/data'

            >>> root_entity = {"name": "workspace", "uri": "file:///workspace"}
            >>> service._get_entity_identifier("roots", root_entity)
            'file:///workspace'

            >>> unknown_entity = {"data": "test"}
            >>> service._get_entity_identifier("unknown", unknown_entity)
            ''
        """
        if entity_type in ["tools", "gateways", "servers", "prompts"]:
            return entity.get("name", "")
        if entity_type == "resources":
            return entity.get("uri", "")
        if entity_type == "roots":
            return entity.get("uri", "")
        return ""

    def _calculate_total_entities(self, entities: Dict[str, List[Dict[str, Any]]], selected_entities: Optional[Dict[str, List[str]]]) -> int:
        """Calculate total entities to process based on selection criteria.

        Args:
            entities: Dictionary of entities from import data
            selected_entities: Optional entity selection filter

        Returns:
            Total number of entities to process

        Examples:
            No selection counts all entities:
            >>> svc = ImportService()
            >>> entities = {
            ...     'tools': [{"name": "t1"}, {"name": "t2"}],
            ...     'resources': [{"uri": "/r1"}],
            ... }
            >>> svc._calculate_total_entities(entities, selected_entities=None)
            3

            Selection for a subset by name/identifier:
            >>> selected = {'tools': ['t2'], 'resources': ['/r1']}
            >>> svc._calculate_total_entities(entities, selected)
            2

            Selection for only a type (empty list means all of that type):
            >>> selected = {'tools': []}
            >>> svc._calculate_total_entities(entities, selected)
            2
        """
        if selected_entities:
            total = 0
            for entity_type, entity_list in entities.items():
                if entity_type in selected_entities:
                    selected_names = selected_entities[entity_type]
                    if selected_names:
                        # Count entities that match selection
                        for entity in entity_list:
                            entity_name = self._get_entity_identifier(entity_type, entity)
                            if entity_name in selected_names:
                                total += 1
                    else:
                        total += len(entity_list)
            return total
        return sum(len(entity_list) for entity_list in entities.values())

    async def _process_entities(
        self,
        db: Session,
        entity_type: str,
        entity_list: List[Dict[str, Any]],
        conflict_strategy: ConflictStrategy,
        dry_run: bool,
        rekey_secret: Optional[str],
        status: ImportStatus,
        selected_entities: Optional[Dict[str, List[str]]],
        imported_by: str,
    ) -> None:
        """Process a list of entities of a specific type using bulk operations.

        This method now uses bulk registration for tools, resources, and prompts
        to achieve 10-50x performance improvements over individual processing.

        Args:
            db: Database session
            entity_type: Type of entities being processed
            entity_list: List of entity data dictionaries
            conflict_strategy: How to handle naming conflicts
            dry_run: Whether this is a dry run
            rekey_secret: New encryption secret if re-keying
            status: Import status tracker
            selected_entities: Optional entity selection filter
            imported_by: Username of the person performing the import
        """
        logger.debug(f"Processing {len(entity_list)} {entity_type} entities")

        # Filter entities based on selection
        filtered_entities = []
        for entity_data in entity_list:
            # Check if this entity is selected for import
            if selected_entities and entity_type in selected_entities:
                selected_names = selected_entities[entity_type]
                if selected_names:  # If specific entities are selected
                    entity_name = self._get_entity_identifier(entity_type, entity_data)
                    if entity_name not in selected_names:
                        continue  # Skip this entity

            # Handle authentication re-encryption if needed
            if rekey_secret and self._has_auth_data(entity_data):
                entity_data = self._rekey_auth_data(entity_data, rekey_secret)

            filtered_entities.append(entity_data)

        if not filtered_entities:
            logger.debug(f"No {entity_type} entities to process after filtering")
            return

        # Use bulk operations for tools, resources, and prompts
        if entity_type == "tools":
            await self._process_tools_bulk(db, filtered_entities, conflict_strategy, dry_run, status, imported_by)
        elif entity_type == "resources":
            await self._process_resources_bulk(db, filtered_entities, conflict_strategy, dry_run, status, imported_by)
        elif entity_type == "prompts":
            await self._process_prompts_bulk(db, filtered_entities, conflict_strategy, dry_run, status, imported_by)
        else:
            # Fall back to individual processing for other entity types
            for entity_data in filtered_entities:
                try:
                    await self._process_single_entity(db, entity_type, entity_data, conflict_strategy, dry_run, status, imported_by)
                    status.processed_entities += 1
                except Exception as e:
                    status.failed_entities += 1
                    status.errors.append(f"Failed to process {entity_type} entity: {str(e)}")
                    logger.error(f"Failed to process {entity_type} entity: {str(e)}")

    def _has_auth_data(self, entity_data: Dict[str, Any]) -> bool:
        """Check if entity has authentication data that needs re-encryption.

        Args:
            entity_data: Entity data dictionary

        Returns:
            True if entity has auth data, False otherwise

        Examples:
            >>> service = ImportService()
            >>> entity_with_auth = {"name": "test", "auth_value": "encrypted_data"}
            >>> bool(service._has_auth_data(entity_with_auth))
            True

            >>> entity_without_auth = {"name": "test"}
            >>> service._has_auth_data(entity_without_auth)
            False

            >>> entity_empty_auth = {"name": "test", "auth_value": ""}
            >>> bool(service._has_auth_data(entity_empty_auth))
            False

            >>> entity_none_auth = {"name": "test", "auth_value": None}
            >>> bool(service._has_auth_data(entity_none_auth))
            False
        """
        return "auth_value" in entity_data and entity_data.get("auth_value")

    def _rekey_auth_data(self, entity_data: Dict[str, Any], new_secret: str) -> Dict[str, Any]:
        """Re-encrypt authentication data with a new secret key.

        Args:
            entity_data: Entity data dictionary
            new_secret: New encryption secret

        Returns:
            Updated entity data with re-encrypted auth

        Raises:
            ImportError: If re-encryption fails

        Examples:
            Returns original entity when no auth data present:
            >>> svc = ImportService()
            >>> svc._has_auth_data({'name': 'x'})
            False
            >>> svc._rekey_auth_data({'name': 'x'}, 'new')
            {'name': 'x'}

            Rekeys when auth data is present (encode/decode patched):
            >>> from unittest.mock import patch
            >>> data = {'name': 'x', 'auth_value': 'enc_old'}
            >>> with patch('mcpgateway.services.import_service.decode_auth', return_value='plain'):
            ...     with patch('mcpgateway.services.import_service.encode_auth', return_value='enc_new'):
            ...         result = svc._rekey_auth_data(dict(data), 'new-secret')
            >>> result['auth_value']
            'enc_new'
        """
        if not self._has_auth_data(entity_data):
            return entity_data

        try:
            # Decrypt with old key
            old_auth_value = entity_data["auth_value"]
            decrypted_auth = decode_auth(old_auth_value)

            # Re-encrypt with new key (temporarily change settings)
            old_secret = settings.auth_encryption_secret
            settings.auth_encryption_secret = new_secret
            try:
                new_auth_value = encode_auth(decrypted_auth)
                entity_data["auth_value"] = new_auth_value
            finally:
                settings.auth_encryption_secret = old_secret

            logger.debug("Successfully re-keyed authentication data")
            return entity_data

        except Exception as e:
            raise ImportError(f"Failed to re-key authentication data: {str(e)}")

    async def _process_single_entity(
        self, db: Session, entity_type: str, entity_data: Dict[str, Any], conflict_strategy: ConflictStrategy, dry_run: bool, status: ImportStatus, imported_by: str
    ) -> None:
        """Process a single entity with conflict resolution.

        Args:
            db: Database session
            entity_type: Type of entity
            entity_data: Entity data dictionary
            conflict_strategy: How to handle conflicts
            dry_run: Whether this is a dry run
            status: Import status tracker
            imported_by: Username of the person performing the import

        Raises:
            ImportError: If processing fails
        """
        try:
            if entity_type == "tools":
                await self._process_tool(db, entity_data, conflict_strategy, dry_run, status)
            elif entity_type == "gateways":
                await self._process_gateway(db, entity_data, conflict_strategy, dry_run, status)
            elif entity_type == "servers":
                await self._process_server(db, entity_data, conflict_strategy, dry_run, status, imported_by)
            elif entity_type == "prompts":
                await self._process_prompt(db, entity_data, conflict_strategy, dry_run, status)
            elif entity_type == "resources":
                await self._process_resource(db, entity_data, conflict_strategy, dry_run, status)
            elif entity_type == "roots":
                await self._process_root(entity_data, conflict_strategy, dry_run, status)

        except Exception as e:
            raise ImportError(f"Failed to process {entity_type}: {str(e)}")

    async def _process_tool(self, db: Session, tool_data: Dict[str, Any], conflict_strategy: ConflictStrategy, dry_run: bool, status: ImportStatus) -> None:
        """Process a tool entity.

        Args:
            db: Database session
            tool_data: Tool data dictionary
            conflict_strategy: How to handle conflicts
            dry_run: Whether this is a dry run
            status: Import status tracker

        Raises:
            ImportError: If processing fails
            ImportConflictError: If conflict cannot be resolved
        """
        tool_name = tool_data["name"]

        if dry_run:
            status.warnings.append(f"Would import tool: {tool_name}")
            return

        try:
            # Convert to ToolCreate schema
            create_data = self._convert_to_tool_create(tool_data)

            # Try to create the tool
            try:
                await self.tool_service.register_tool(db, create_data)
                status.created_entities += 1
                logger.debug(f"Created tool: {tool_name}")

            except ToolNameConflictError:
                # Handle conflict based on strategy
                if conflict_strategy == ConflictStrategy.SKIP:
                    status.skipped_entities += 1
                    status.warnings.append(f"Skipped existing tool: {tool_name}")
                elif conflict_strategy == ConflictStrategy.UPDATE:
                    # For conflict resolution, we need to find existing tool ID
                    # This is a simplified approach - in practice you'd query the database
                    try:
                        # Try to get tools and find by name
                        tools, _ = await self.tool_service.list_tools(db, include_inactive=True)
                        existing_tool = next((t for t in tools if t.original_name == tool_name), None)
                        if existing_tool:
                            update_data = self._convert_to_tool_update(tool_data)
                            await self.tool_service.update_tool(db, existing_tool.id, update_data)
                            status.updated_entities += 1
                            logger.debug(f"Updated tool: {tool_name}")
                        else:
                            status.warnings.append(f"Could not find existing tool to update: {tool_name}")
                            status.skipped_entities += 1
                    except Exception as update_error:
                        logger.warning(f"Failed to update tool {tool_name}: {str(update_error)}")
                        status.warnings.append(f"Could not update tool {tool_name}: {str(update_error)}")
                        status.skipped_entities += 1
                elif conflict_strategy == ConflictStrategy.RENAME:
                    # Rename and create
                    new_name = f"{tool_name}_imported_{int(datetime.now().timestamp())}"
                    create_data.name = new_name
                    await self.tool_service.register_tool(db, create_data)
                    status.created_entities += 1
                    status.warnings.append(f"Renamed tool {tool_name} to {new_name}")
                elif conflict_strategy == ConflictStrategy.FAIL:
                    raise ImportConflictError(f"Tool name conflict: {tool_name}")

        except Exception as e:
            raise ImportError(f"Failed to process tool {tool_name}: {str(e)}")

    async def _process_gateway(self, db: Session, gateway_data: Dict[str, Any], conflict_strategy: ConflictStrategy, dry_run: bool, status: ImportStatus) -> None:
        """Process a gateway entity.

        Args:
            db: Database session
            gateway_data: Gateway data dictionary
            conflict_strategy: How to handle conflicts
            dry_run: Whether this is a dry run
            status: Import status tracker

        Raises:
            ImportError: If processing fails
            ImportConflictError: If conflict cannot be resolved
        """
        gateway_name = gateway_data["name"]

        if dry_run is True:
            status.warnings.append(f"Would import gateway: {gateway_name}")
            return

        try:
            # Convert to GatewayCreate schema
            create_data = self._convert_to_gateway_create(gateway_data)

            try:
                await self.gateway_service.register_gateway(db, create_data)
                status.created_entities += 1
                logger.debug(f"Created gateway: {gateway_name}")

            except GatewayNameConflictError:
                if conflict_strategy == ConflictStrategy.SKIP:
                    status.skipped_entities += 1
                    status.warnings.append(f"Skipped existing gateway: {gateway_name}")
                elif conflict_strategy == ConflictStrategy.UPDATE:
                    try:
                        # Find existing gateway by name
                        gateways = await self.gateway_service.list_gateways(db, include_inactive=True)
                        existing_gateway = next((g for g in gateways if g.name == gateway_name), None)
                        if existing_gateway:
                            update_data = self._convert_to_gateway_update(gateway_data)
                            await self.gateway_service.update_gateway(db, existing_gateway.id, update_data)
                            status.updated_entities += 1
                            logger.debug(f"Updated gateway: {gateway_name}")
                        else:
                            status.warnings.append(f"Could not find existing gateway to update: {gateway_name}")
                            status.skipped_entities += 1
                    except Exception as update_error:
                        logger.warning(f"Failed to update gateway {gateway_name}: {str(update_error)}")
                        status.warnings.append(f"Could not update gateway {gateway_name}: {str(update_error)}")
                        status.skipped_entities += 1
                elif conflict_strategy == ConflictStrategy.RENAME:
                    new_name = f"{gateway_name}_imported_{int(datetime.now().timestamp())}"
                    create_data.name = new_name
                    await self.gateway_service.register_gateway(db, create_data)
                    status.created_entities += 1
                    status.warnings.append(f"Renamed gateway {gateway_name} to {new_name}")
                elif conflict_strategy == ConflictStrategy.FAIL:
                    raise ImportConflictError(f"Gateway name conflict: {gateway_name}")

        except Exception as e:
            raise ImportError(f"Failed to process gateway {gateway_name}: {str(e)}")

    async def _process_server(self, db: Session, server_data: Dict[str, Any], conflict_strategy: ConflictStrategy, dry_run: bool, status: ImportStatus, imported_by: str) -> None:
        """Process a server entity.

        Args:
            db: Database session
            server_data: Server data dictionary
            conflict_strategy: How to handle conflicts
            dry_run: Whether this is a dry run
            status: Import status tracker
            imported_by: Username of the person performing the import

        Raises:
            ImportError: If processing fails
            ImportConflictError: If conflict cannot be resolved
        """
        server_name = server_data["name"]

        if dry_run:
            status.warnings.append(f"Would import server: {server_name}")
            return

        try:
            create_data = await self._convert_to_server_create(db, server_data)

            try:
                await self.server_service.register_server(db, create_data)
                status.created_entities += 1
                logger.debug(f"Created server: {server_name}")

            except ServerNameConflictError:
                if conflict_strategy == ConflictStrategy.SKIP:
                    status.skipped_entities += 1
                    status.warnings.append(f"Skipped existing server: {server_name}")
                elif conflict_strategy == ConflictStrategy.UPDATE:
                    try:
                        # Find existing server by name
                        servers = await self.server_service.list_servers(db, include_inactive=True)
                        existing_server = next((s for s in servers if s.name == server_name), None)
                        if existing_server:
                            update_data = await self._convert_to_server_update(db, server_data)
                            await self.server_service.update_server(db, existing_server.id, update_data, imported_by)
                            status.updated_entities += 1
                            logger.debug(f"Updated server: {server_name}")
                        else:
                            status.warnings.append(f"Could not find existing server to update: {server_name}")
                            status.skipped_entities += 1
                    except Exception as update_error:
                        logger.warning(f"Failed to update server {server_name}: {str(update_error)}")
                        status.warnings.append(f"Could not update server {server_name}: {str(update_error)}")
                        status.skipped_entities += 1
                elif conflict_strategy == ConflictStrategy.RENAME:
                    new_name = f"{server_name}_imported_{int(datetime.now().timestamp())}"
                    create_data.name = new_name
                    await self.server_service.register_server(db, create_data)
                    status.created_entities += 1
                    status.warnings.append(f"Renamed server {server_name} to {new_name}")
                elif conflict_strategy == ConflictStrategy.FAIL:
                    raise ImportConflictError(f"Server name conflict: {server_name}")

        except Exception as e:
            raise ImportError(f"Failed to process server {server_name}: {str(e)}")

    async def _process_prompt(self, db: Session, prompt_data: Dict[str, Any], conflict_strategy: ConflictStrategy, dry_run: bool, status: ImportStatus) -> None:
        """Process a prompt entity.

        Args:
            db: Database session
            prompt_data: Prompt data dictionary
            conflict_strategy: How to handle conflicts
            dry_run: Whether this is a dry run
            status: Import status tracker

        Raises:
            ImportError: If processing fails
            ImportConflictError: If conflict cannot be resolved
        """
        prompt_name = prompt_data["name"]

        if dry_run:
            status.warnings.append(f"Would import prompt: {prompt_name}")
            return

        try:
            create_data = self._convert_to_prompt_create(prompt_data)

            try:
                await self.prompt_service.register_prompt(db, create_data)
                status.created_entities += 1
                logger.debug(f"Created prompt: {prompt_name}")

            except PromptNameConflictError:
                if conflict_strategy == ConflictStrategy.SKIP:
                    status.skipped_entities += 1
                    status.warnings.append(f"Skipped existing prompt: {prompt_name}")
                elif conflict_strategy == ConflictStrategy.UPDATE:
                    update_data = self._convert_to_prompt_update(prompt_data)
                    await self.prompt_service.update_prompt(db, prompt_name, update_data)
                    status.updated_entities += 1
                    logger.debug(f"Updated prompt: {prompt_name}")
                elif conflict_strategy == ConflictStrategy.RENAME:
                    new_name = f"{prompt_name}_imported_{int(datetime.now().timestamp())}"
                    create_data.name = new_name
                    await self.prompt_service.register_prompt(db, create_data)
                    status.created_entities += 1
                    status.warnings.append(f"Renamed prompt {prompt_name} to {new_name}")
                elif conflict_strategy == ConflictStrategy.FAIL:
                    raise ImportConflictError(f"Prompt name conflict: {prompt_name}")

        except Exception as e:
            raise ImportError(f"Failed to process prompt {prompt_name}: {str(e)}")

    async def _process_resource(self, db: Session, resource_data: Dict[str, Any], conflict_strategy: ConflictStrategy, dry_run: bool, status: ImportStatus) -> None:
        """Process a resource entity.

        Args:
            db: Database session
            resource_data: Resource data dictionary
            conflict_strategy: How to handle conflicts
            dry_run: Whether this is a dry run
            status: Import status tracker

        Raises:
            ImportError: If processing fails
            ImportConflictError: If conflict cannot be resolved
        """
        resource_uri = resource_data["uri"]

        if dry_run:
            status.warnings.append(f"Would import resource: {resource_uri}")
            return

        try:
            create_data = self._convert_to_resource_create(resource_data)

            try:
                await self.resource_service.register_resource(db, create_data)
                status.created_entities += 1
                logger.debug(f"Created resource: {resource_uri}")

            except ResourceURIConflictError:
                if conflict_strategy == ConflictStrategy.SKIP:
                    status.skipped_entities += 1
                    status.warnings.append(f"Skipped existing resource: {resource_uri}")
                elif conflict_strategy == ConflictStrategy.UPDATE:
                    update_data = self._convert_to_resource_update(resource_data)
                    await self.resource_service.update_resource(db, resource_uri, update_data)
                    status.updated_entities += 1
                    logger.debug(f"Updated resource: {resource_uri}")
                elif conflict_strategy == ConflictStrategy.RENAME:
                    new_uri = f"{resource_uri}_imported_{int(datetime.now().timestamp())}"
                    create_data.uri = new_uri
                    await self.resource_service.register_resource(db, create_data)
                    status.created_entities += 1
                    status.warnings.append(f"Renamed resource {resource_uri} to {new_uri}")
                elif conflict_strategy == ConflictStrategy.FAIL:
                    raise ImportConflictError(f"Resource URI conflict: {resource_uri}")

        except Exception as e:
            raise ImportError(f"Failed to process resource {resource_uri}: {str(e)}")

    async def _process_tools_bulk(self, db: Session, tools_data: List[Dict[str, Any]], conflict_strategy: ConflictStrategy, dry_run: bool, status: ImportStatus, imported_by: str) -> None:
        """Process multiple tools using bulk operations.

        Args:
            db: Database session
            tools_data: List of tool data dictionaries
            conflict_strategy: How to handle conflicts
            dry_run: Whether this is a dry run
            status: Import status tracker
            imported_by: Username of the person performing the import
        """
        if dry_run:
            for tool_data in tools_data:
                status.warnings.append(f"Would import tool: {tool_data.get('name', 'unknown')}")
            return

        try:
            # Convert all tool data to ToolCreate schemas
            tools_to_register = []
            for tool_data in tools_data:
                try:
                    create_data = self._convert_to_tool_create(tool_data)
                    tools_to_register.append(create_data)
                except Exception as e:
                    status.failed_entities += 1
                    status.errors.append(f"Failed to convert tool {tool_data.get('name', 'unknown')}: {str(e)}")
                    logger.warning(f"Failed to convert tool data: {str(e)}")

            if not tools_to_register:
                return

            # Use bulk registration
            result = await self.tool_service.register_tools_bulk(
                db=db,
                tools=tools_to_register,
                created_by=imported_by,
                created_via="import",
                conflict_strategy=conflict_strategy.value,
            )

            # Update status based on results
            status.created_entities += result["created"]
            status.updated_entities += result["updated"]
            status.skipped_entities += result["skipped"]
            status.failed_entities += result["failed"]
            status.processed_entities += result["created"] + result["updated"] + result["skipped"]

            # Add any errors to status
            for error in result.get("errors", []):
                status.errors.append(error)

            logger.info(f"Bulk processed {len(tools_data)} tools: {result['created']} created, {result['updated']} updated, {result['skipped']} skipped, {result['failed']} failed")

        except Exception as e:
            status.failed_entities += len(tools_data)
            status.errors.append(f"Bulk tool processing failed: {str(e)}")
            logger.error(f"Failed to bulk process tools: {str(e)}")
            # Don't raise - allow import to continue with other entities

    async def _process_resources_bulk(self, db: Session, resources_data: List[Dict[str, Any]], conflict_strategy: ConflictStrategy, dry_run: bool, status: ImportStatus, imported_by: str) -> None:
        """Process multiple resources using bulk operations.

        Args:
            db: Database session
            resources_data: List of resource data dictionaries
            conflict_strategy: How to handle conflicts
            dry_run: Whether this is a dry run
            status: Import status tracker
            imported_by: Username of the person performing the import
        """
        if dry_run:
            for resource_data in resources_data:
                status.warnings.append(f"Would import resource: {resource_data.get('uri', 'unknown')}")
            return

        try:
            # Convert all resource data to ResourceCreate schemas
            resources_to_register = []
            for resource_data in resources_data:
                try:
                    create_data = self._convert_to_resource_create(resource_data)
                    resources_to_register.append(create_data)
                except Exception as e:
                    status.failed_entities += 1
                    status.errors.append(f"Failed to convert resource {resource_data.get('uri', 'unknown')}: {str(e)}")
                    logger.warning(f"Failed to convert resource data: {str(e)}")

            if not resources_to_register:
                return

            # Use bulk registration
            result = await self.resource_service.register_resources_bulk(
                db=db,
                resources=resources_to_register,
                created_by=imported_by,
                created_via="import",
                conflict_strategy=conflict_strategy.value,
            )

            # Update status based on results
            status.created_entities += result["created"]
            status.updated_entities += result["updated"]
            status.skipped_entities += result["skipped"]
            status.failed_entities += result["failed"]
            status.processed_entities += result["created"] + result["updated"] + result["skipped"]

            # Add any errors to status
            for error in result.get("errors", []):
                status.errors.append(error)

            logger.info(f"Bulk processed {len(resources_data)} resources: {result['created']} created, {result['updated']} updated, {result['skipped']} skipped, {result['failed']} failed")

        except Exception as e:
            status.failed_entities += len(resources_data)
            status.errors.append(f"Bulk resource processing failed: {str(e)}")
            logger.error(f"Failed to bulk process resources: {str(e)}")
            # Don't raise - allow import to continue with other entities

    async def _process_prompts_bulk(self, db: Session, prompts_data: List[Dict[str, Any]], conflict_strategy: ConflictStrategy, dry_run: bool, status: ImportStatus, imported_by: str) -> None:
        """Process multiple prompts using bulk operations.

        Args:
            db: Database session
            prompts_data: List of prompt data dictionaries
            conflict_strategy: How to handle conflicts
            dry_run: Whether this is a dry run
            status: Import status tracker
            imported_by: Username of the person performing the import
        """
        if dry_run:
            for prompt_data in prompts_data:
                status.warnings.append(f"Would import prompt: {prompt_data.get('name', 'unknown')}")
            return

        try:
            # Convert all prompt data to PromptCreate schemas
            prompts_to_register = []
            for prompt_data in prompts_data:
                try:
                    create_data = self._convert_to_prompt_create(prompt_data)
                    prompts_to_register.append(create_data)
                except Exception as e:
                    status.failed_entities += 1
                    status.errors.append(f"Failed to convert prompt {prompt_data.get('name', 'unknown')}: {str(e)}")
                    logger.warning(f"Failed to convert prompt data: {str(e)}")

            if not prompts_to_register:
                return

            # Use bulk registration
            result = await self.prompt_service.register_prompts_bulk(
                db=db,
                prompts=prompts_to_register,
                created_by=imported_by,
                created_via="import",
                conflict_strategy=conflict_strategy.value,
            )

            # Update status based on results
            status.created_entities += result["created"]
            status.updated_entities += result["updated"]
            status.skipped_entities += result["skipped"]
            status.failed_entities += result["failed"]
            status.processed_entities += result["created"] + result["updated"] + result["skipped"]

            # Add any errors to status
            for error in result.get("errors", []):
                status.errors.append(error)

            logger.info(f"Bulk processed {len(prompts_data)} prompts: {result['created']} created, {result['updated']} updated, {result['skipped']} skipped, {result['failed']} failed")

        except Exception as e:
            status.failed_entities += len(prompts_data)
            status.errors.append(f"Bulk prompt processing failed: {str(e)}")
            logger.error(f"Failed to bulk process prompts: {str(e)}")
            # Don't raise - allow import to continue with other entities

    async def _process_root(self, root_data: Dict[str, Any], conflict_strategy: ConflictStrategy, dry_run: bool, status: ImportStatus) -> None:
        """Process a root entity.

        Args:
            root_data: Root data dictionary
            conflict_strategy: How to handle conflicts
            dry_run: Whether this is a dry run
            status: Import status tracker

        Raises:
            ImportError: If processing fails
            ImportConflictError: If conflict cannot be resolved
        """
        root_uri = root_data["uri"]

        if dry_run:
            status.warnings.append(f"Would import root: {root_uri}")
            return

        try:
            await self.root_service.add_root(root_uri, root_data.get("name"))
            status.created_entities += 1
            logger.debug(f"Created root: {root_uri}")

        except Exception as e:
            if conflict_strategy == ConflictStrategy.SKIP:
                status.skipped_entities += 1
                status.warnings.append(f"Skipped existing root: {root_uri}")
            elif conflict_strategy == ConflictStrategy.FAIL:
                raise ImportConflictError(f"Root URI conflict: {root_uri}")
            else:
                raise ImportError(f"Failed to process root {root_uri}: {str(e)}")

    def _convert_to_tool_create(self, tool_data: Dict[str, Any]) -> ToolCreate:
        """Convert import data to ToolCreate schema.

        Args:
            tool_data: Tool data dictionary from import

        Returns:
            ToolCreate schema object
        """
        # Extract auth information if present
        auth_info = None
        if tool_data.get("auth_type") and tool_data.get("auth_value"):
            auth_info = AuthenticationValues(auth_type=tool_data["auth_type"], auth_value=tool_data["auth_value"])

        return ToolCreate(
            name=tool_data["name"],
            displayName=tool_data.get("displayName"),
            url=tool_data["url"],
            description=tool_data.get("description"),
            integration_type=tool_data.get("integration_type", "REST"),
            request_type=tool_data.get("request_type", "GET"),
            headers=tool_data.get("headers"),
            input_schema=tool_data.get("input_schema"),
            output_schema=tool_data.get("output_schema"),
            annotations=tool_data.get("annotations"),
            jsonpath_filter=tool_data.get("jsonpath_filter"),
            auth=auth_info,
            tags=tool_data.get("tags", []),
        )

    def _convert_to_tool_update(self, tool_data: Dict[str, Any]) -> ToolUpdate:
        """Convert import data to ToolUpdate schema.

        Args:
            tool_data: Tool data dictionary from import

        Returns:
            ToolUpdate schema object
        """
        auth_info = None
        if tool_data.get("auth_type") and tool_data.get("auth_value"):
            auth_info = AuthenticationValues(auth_type=tool_data["auth_type"], auth_value=tool_data["auth_value"])

        return ToolUpdate(
            name=tool_data.get("name"),
            displayName=tool_data.get("displayName"),
            url=tool_data.get("url"),
            description=tool_data.get("description"),
            integration_type=tool_data.get("integration_type"),
            request_type=tool_data.get("request_type"),
            headers=tool_data.get("headers"),
            input_schema=tool_data.get("input_schema"),
            output_schema=tool_data.get("output_schema"),
            annotations=tool_data.get("annotations"),
            jsonpath_filter=tool_data.get("jsonpath_filter"),
            auth=auth_info,
            tags=tool_data.get("tags"),
        )

    def _convert_to_gateway_create(self, gateway_data: Dict[str, Any]) -> GatewayCreate:
        """Convert import data to GatewayCreate schema.

        Args:
            gateway_data: Gateway data dictionary from import

        Returns:
            GatewayCreate schema object
        """
        # Handle auth data
        auth_kwargs = {}
        if gateway_data.get("auth_type"):
            auth_kwargs["auth_type"] = gateway_data["auth_type"]

            # Decode auth_value to get original credentials
            if gateway_data.get("auth_value"):
                try:
                    decoded_auth = decode_auth(gateway_data["auth_value"])
                    if gateway_data["auth_type"] == "basic":
                        # Extract username and password from Basic auth
                        auth_header = decoded_auth.get("Authorization", "")
                        if auth_header.startswith("Basic "):
                            creds = base64.b64decode(auth_header[6:]).decode("utf-8")
                            username, password = creds.split(":", 1)
                            auth_kwargs.update({"auth_username": username, "auth_password": password})
                    elif gateway_data["auth_type"] == "bearer":
                        # Extract token from Bearer auth
                        auth_header = decoded_auth.get("Authorization", "")
                        if auth_header.startswith("Bearer "):
                            auth_kwargs["auth_token"] = auth_header[7:]
                    elif gateway_data["auth_type"] == "authheaders":
                        # Handle custom headers
                        if len(decoded_auth) == 1:
                            key, value = next(iter(decoded_auth.items()))
                            auth_kwargs.update({"auth_header_key": key, "auth_header_value": value})
                        else:
                            # Multiple headers - use the new format
                            headers_list = [{"key": k, "value": v} for k, v in decoded_auth.items()]
                            auth_kwargs["auth_headers"] = headers_list
                except Exception as e:
                    logger.warning(f"Failed to decode auth data for gateway: {str(e)}")

        return GatewayCreate(
            name=gateway_data["name"],
            url=gateway_data["url"],
            description=gateway_data.get("description"),
            transport=gateway_data.get("transport", "SSE"),
            passthrough_headers=gateway_data.get("passthrough_headers"),
            tags=gateway_data.get("tags", []),
            **auth_kwargs,
        )

    def _convert_to_gateway_update(self, gateway_data: Dict[str, Any]) -> GatewayUpdate:
        """Convert import data to GatewayUpdate schema.

        Args:
            gateway_data: Gateway data dictionary from import

        Returns:
            GatewayUpdate schema object
        """
        # Similar to create but all fields optional
        auth_kwargs = {}
        if gateway_data.get("auth_type"):
            auth_kwargs["auth_type"] = gateway_data["auth_type"]

            if gateway_data.get("auth_value"):
                try:
                    decoded_auth = decode_auth(gateway_data["auth_value"])
                    if gateway_data["auth_type"] == "basic":
                        auth_header = decoded_auth.get("Authorization", "")
                        if auth_header.startswith("Basic "):
                            creds = base64.b64decode(auth_header[6:]).decode("utf-8")
                            username, password = creds.split(":", 1)
                            auth_kwargs.update({"auth_username": username, "auth_password": password})
                    elif gateway_data["auth_type"] == "bearer":
                        auth_header = decoded_auth.get("Authorization", "")
                        if auth_header.startswith("Bearer "):
                            auth_kwargs["auth_token"] = auth_header[7:]
                    elif gateway_data["auth_type"] == "authheaders":
                        if len(decoded_auth) == 1:
                            key, value = next(iter(decoded_auth.items()))
                            auth_kwargs.update({"auth_header_key": key, "auth_header_value": value})
                        else:
                            headers_list = [{"key": k, "value": v} for k, v in decoded_auth.items()]
                            auth_kwargs["auth_headers"] = headers_list
                except Exception as e:
                    logger.warning(f"Failed to decode auth data for gateway update: {str(e)}")

        return GatewayUpdate(
            name=gateway_data.get("name"),
            url=gateway_data.get("url"),
            description=gateway_data.get("description"),
            transport=gateway_data.get("transport"),
            passthrough_headers=gateway_data.get("passthrough_headers"),
            tags=gateway_data.get("tags"),
            **auth_kwargs,
        )

    async def _convert_to_server_create(self, db: Session, server_data: Dict[str, Any]) -> ServerCreate:
        """Convert import data to ServerCreate schema, resolving tool references.

        Args:
            db: Database session
            server_data: Server data dictionary from import

        Returns:
            ServerCreate schema object with resolved tool IDs
        """
        # Resolve tool references (could be names or IDs) to current tool IDs
        tool_references = server_data.get("tool_ids", []) or server_data.get("associated_tools", [])
        resolved_tool_ids = []

        if tool_references:
            # Get all tools to resolve references
            all_tools, _ = await self.tool_service.list_tools(db, include_inactive=True)

            for tool_ref in tool_references:
                # Try to find tool by ID first, then by name
                found_tool = None

                # Try exact ID match
                found_tool = next((t for t in all_tools if t.id == tool_ref), None)

                # If not found, try by original_name or name
                if not found_tool:
                    found_tool = next((t for t in all_tools if t.original_name == tool_ref), None)

                if not found_tool:
                    found_tool = next((t for t in all_tools if hasattr(t, "name") and t.name == tool_ref), None)

                if found_tool:
                    resolved_tool_ids.append(found_tool.id)
                    logger.debug(f"Resolved tool reference '{tool_ref}' to ID {found_tool.id}")
                else:
                    logger.warning(f"Could not resolve tool reference: {tool_ref}")
                    # Don't include unresolvable references

        return ServerCreate(name=server_data["name"], description=server_data.get("description"), associated_tools=resolved_tool_ids, tags=server_data.get("tags", []))

    async def _convert_to_server_update(self, db: Session, server_data: Dict[str, Any]) -> ServerUpdate:
        """Convert import data to ServerUpdate schema, resolving tool references.

        Args:
            db: Database session
            server_data: Server data dictionary from import

        Returns:
            ServerUpdate schema object with resolved tool IDs
        """
        # Resolve tool references same as create method
        tool_references = server_data.get("tool_ids", []) or server_data.get("associated_tools", [])
        resolved_tool_ids = []

        if tool_references:
            all_tools, _ = await self.tool_service.list_tools(db, include_inactive=True)

            for tool_ref in tool_references:
                found_tool = next((t for t in all_tools if t.id == tool_ref), None)
                if not found_tool:
                    found_tool = next((t for t in all_tools if t.original_name == tool_ref), None)
                if not found_tool:
                    found_tool = next((t for t in all_tools if hasattr(t, "name") and t.name == tool_ref), None)

                if found_tool:
                    resolved_tool_ids.append(found_tool.id)
                else:
                    logger.warning(f"Could not resolve tool reference for update: {tool_ref}")

        return ServerUpdate(name=server_data.get("name"), description=server_data.get("description"), associated_tools=resolved_tool_ids if resolved_tool_ids else None, tags=server_data.get("tags"))

    def _convert_to_prompt_create(self, prompt_data: Dict[str, Any]) -> PromptCreate:
        """Convert import data to PromptCreate schema.

        Args:
            prompt_data: Prompt data dictionary from import

        Returns:
            PromptCreate schema object
        """
        # Convert input_schema back to arguments format
        arguments = []
        input_schema = prompt_data.get("input_schema", {})
        if isinstance(input_schema, dict):
            properties = input_schema.get("properties", {})
            required_fields = input_schema.get("required", [])

            for prop_name, prop_data in properties.items():
                arguments.append({"name": prop_name, "description": prop_data.get("description", ""), "required": prop_name in required_fields})

        original_name = prompt_data.get("original_name") or prompt_data["name"]
        return PromptCreate(
            name=original_name,
            custom_name=prompt_data.get("custom_name"),
            display_name=prompt_data.get("display_name"),
            template=prompt_data["template"],
            description=prompt_data.get("description"),
            arguments=arguments,
            tags=prompt_data.get("tags", []),
        )

    def _convert_to_prompt_update(self, prompt_data: Dict[str, Any]) -> PromptUpdate:
        """Convert import data to PromptUpdate schema.

        Args:
            prompt_data: Prompt data dictionary from import

        Returns:
            PromptUpdate schema object
        """
        arguments = []
        input_schema = prompt_data.get("input_schema", {})
        if isinstance(input_schema, dict):
            properties = input_schema.get("properties", {})
            required_fields = input_schema.get("required", [])

            for prop_name, prop_data in properties.items():
                arguments.append({"name": prop_name, "description": prop_data.get("description", ""), "required": prop_name in required_fields})

        original_name = prompt_data.get("original_name") or prompt_data.get("name")
        return PromptUpdate(
            name=original_name,
            custom_name=prompt_data.get("custom_name"),
            display_name=prompt_data.get("display_name"),
            template=prompt_data.get("template"),
            description=prompt_data.get("description"),
            arguments=arguments if arguments else None,
            tags=prompt_data.get("tags"),
        )

    def _convert_to_resource_create(self, resource_data: Dict[str, Any]) -> ResourceCreate:
        """Convert import data to ResourceCreate schema.

        Args:
            resource_data: Resource data dictionary from import

        Returns:
            ResourceCreate schema object
        """
        return ResourceCreate(
            uri=resource_data["uri"],
            name=resource_data["name"],
            description=resource_data.get("description"),
            mime_type=resource_data.get("mime_type"),
            content=resource_data.get("content", ""),  # Default empty content
            tags=resource_data.get("tags", []),
        )

    def _convert_to_resource_update(self, resource_data: Dict[str, Any]) -> ResourceUpdate:
        """Convert import data to ResourceUpdate schema.

        Args:
            resource_data: Resource data dictionary from import

        Returns:
            ResourceUpdate schema object
        """
        return ResourceUpdate(
            name=resource_data.get("name"), description=resource_data.get("description"), mime_type=resource_data.get("mime_type"), content=resource_data.get("content"), tags=resource_data.get("tags")
        )

    def get_import_status(self, import_id: str) -> Optional[ImportStatus]:
        """Get the status of an import operation.

        Args:
            import_id: Import operation ID

        Returns:
            Import status object or None if not found
        """
        return self.active_imports.get(import_id)

    def list_import_statuses(self) -> List[ImportStatus]:
        """List all import statuses.

        Returns:
            List of all import status objects
        """
        return list(self.active_imports.values())

    def cleanup_completed_imports(self, max_age_hours: int = 24) -> int:
        """Clean up completed import statuses older than max_age_hours.

        Args:
            max_age_hours: Maximum age in hours for keeping completed imports

        Returns:
            Number of import statuses removed
        """
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        removed = 0

        to_remove = []
        for import_id, status in self.active_imports.items():
            if status.status in ["completed", "failed"] and status.completed_at and status.completed_at < cutoff_time:
                to_remove.append(import_id)

        for import_id in to_remove:
            del self.active_imports[import_id]
            removed += 1

        return removed

    async def preview_import(self, db: Session, import_data: Dict[str, Any]) -> Dict[str, Any]:
        """Preview import file to show what would be imported with smart categorization.

        Args:
            db: Database session
            import_data: The validated import data

        Returns:
            Dictionary with categorized items for selective import UI

        Examples:
            >>> service = ImportService()
            >>> # This would return a structure for the UI to build selection interface
        """
        self.validate_import_data(import_data)

        entities = import_data.get("entities", {})
        preview = {
            "summary": {"total_items": sum(len(items) for items in entities.values()), "by_type": {entity_type: len(items) for entity_type, items in entities.items()}},
            "items": {},
            "bundles": {},
            "conflicts": {},
            "dependencies": {},
        }

        # Categorize each entity type
        for entity_type, entity_list in entities.items():
            preview["items"][entity_type] = []

            for entity in entity_list:
                item_info = await self._analyze_import_item(db, entity_type, entity)
                preview["items"][entity_type].append(item_info)

        # Find gateway bundles (gateways + their tools/resources/prompts)
        if "gateways" in entities:
            preview["bundles"] = self._find_gateway_bundles(entities)

        # Find server dependencies
        if "servers" in entities:
            preview["dependencies"] = self._find_server_dependencies(entities)

        # Detect conflicts with existing items
        preview["conflicts"] = await self._detect_import_conflicts(db, entities)

        return preview

    async def _analyze_import_item(self, db: Session, entity_type: str, entity: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze a single import item for the preview.

        Args:
            db: Database session
            entity_type: Type of entity
            entity: Entity data

        Returns:
            Item analysis with metadata for UI selection
        """
        item_name = self._get_entity_identifier(entity_type, entity)

        # Basic item info
        item_info = {
            "id": item_name,
            "name": entity.get("name", item_name),
            "type": entity_type,
            "is_gateway_item": bool(entity.get("gateway_name") or entity.get("gateway_id")),
            "is_custom": not bool(entity.get("gateway_name") or entity.get("gateway_id")),
            "description": entity.get("description", ""),
        }

        # Check if it conflicts with existing items
        try:
            if entity_type == "tools":
                existing, _ = await self.tool_service.list_tools(db)
                item_info["conflicts_with"] = any(t.original_name == item_name for t in existing)
            elif entity_type == "gateways":
                existing = await self.gateway_service.list_gateways(db)
                item_info["conflicts_with"] = any(g.name == item_name for g in existing)
            elif entity_type == "servers":
                existing = await self.server_service.list_servers(db)
                item_info["conflicts_with"] = any(s.name == item_name for s in existing)
            elif entity_type == "prompts":
                existing, _ = await self.prompt_service.list_prompts(db)
                item_info["conflicts_with"] = any(p.name == item_name for p in existing)
            elif entity_type == "resources":
                existing, _ = await self.resource_service.list_resources(db)
                item_info["conflicts_with"] = any(r.uri == item_name for r in existing)
            else:
                item_info["conflicts_with"] = False
        except Exception:
            item_info["conflicts_with"] = False

        # Add metadata for smart selection
        if entity_type == "servers":
            item_info["dependencies"] = {"tools": entity.get("associated_tools", []), "resources": entity.get("associated_resources", []), "prompts": entity.get("associated_prompts", [])}

        return item_info

    def _find_gateway_bundles(self, entities: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        """Find gateway bundles (gateway + associated tools/resources/prompts).

        Args:
            entities: All entities from import data

        Returns:
            Gateway bundle information for UI
        """
        bundles = {}

        if "gateways" not in entities:
            return bundles

        for gateway in entities["gateways"]:
            gateway_name = gateway.get("name", "")
            bundle_items = {"tools": [], "resources": [], "prompts": []}

            # Find items that belong to this gateway
            for entity_type in ["tools", "resources", "prompts"]:
                if entity_type in entities:
                    for item in entities[entity_type]:
                        item_gateway = item.get("gateway_name") or item.get("gateway_id")
                        if item_gateway == gateway_name:
                            item_name = self._get_entity_identifier(entity_type, item)
                            bundle_items[entity_type].append({"id": item_name, "name": item.get("name", item_name), "description": item.get("description", "")})

            if any(bundle_items.values()):  # Only add if gateway has items
                bundles[gateway_name] = {
                    "gateway": {"name": gateway_name, "description": gateway.get("description", "")},
                    "items": bundle_items,
                    "total_items": sum(len(items) for items in bundle_items.values()),
                }

        return bundles

    def _find_server_dependencies(self, entities: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        """Find server dependencies for smart selection.

        Args:
            entities: All entities from import data

        Returns:
            Server dependency information for UI
        """
        dependencies = {}

        if "servers" not in entities:
            return dependencies

        for server in entities["servers"]:
            server_name = server.get("name", "")
            deps = {"tools": server.get("associated_tools", []), "resources": server.get("associated_resources", []), "prompts": server.get("associated_prompts", [])}

            if any(deps.values()):  # Only add if server has dependencies
                dependencies[server_name] = {
                    "server": {"name": server_name, "description": server.get("description", "")},
                    "requires": deps,
                    "total_dependencies": sum(len(items) for items in deps.values()),
                }

        return dependencies

    async def _detect_import_conflicts(self, db: Session, entities: Dict[str, List[Dict[str, Any]]]) -> Dict[str, List[Dict[str, Any]]]:
        """Detect conflicts between import items and existing database items.

        Args:
            db: Database session
            entities: Import entities

        Returns:
            Dictionary of conflicts by entity type
        """
        conflicts = {}

        try:
            # Check tool conflicts
            if "tools" in entities:
                existing_tools, _ = await self.tool_service.list_tools(db)
                existing_names = {t.original_name for t in existing_tools}

                tool_conflicts = []
                for tool in entities["tools"]:
                    tool_name = tool.get("name", "")
                    if tool_name in existing_names:
                        tool_conflicts.append({"name": tool_name, "type": "name_conflict", "description": tool.get("description", "")})

                if tool_conflicts:
                    conflicts["tools"] = tool_conflicts

            # Check gateway conflicts
            if "gateways" in entities:
                existing_gateways = await self.gateway_service.list_gateways(db)
                existing_names = {g.name for g in existing_gateways}

                gateway_conflicts = []
                for gateway in entities["gateways"]:
                    gateway_name = gateway.get("name", "")
                    if gateway_name in existing_names:
                        gateway_conflicts.append({"name": gateway_name, "type": "name_conflict", "description": gateway.get("description", "")})

                if gateway_conflicts:
                    conflicts["gateways"] = gateway_conflicts

            # Add other entity types as needed...

        except Exception as e:
            logger.warning(f"Could not detect all conflicts: {e}")

        return conflicts

    async def _get_user_context(self, db: Session, imported_by: str) -> Optional[Dict[str, Any]]:
        """Get user context for import team assignment.

        Args:
            db: Database session
            imported_by: Email of importing user

        Returns:
            User context dict or None if not found
        """
        try:
            user = db.query(EmailUser).filter(EmailUser.email == imported_by).first()
            if not user:
                logger.warning(f"Could not find importing user: {imported_by}")
                return None

            personal_team = user.get_personal_team()
            if not personal_team:
                logger.warning(f"User {imported_by} has no personal team")
                return None

            return {"user_email": user.email, "team_id": personal_team.id, "team_name": personal_team.name}
        except Exception as e:
            logger.error(f"Failed to get user context: {e}")
            return None

    def _add_multitenancy_context(self, entity_data: Dict[str, Any], user_context: Dict[str, Any]) -> Dict[str, Any]:
        """Add team and visibility context to entity data for import.

        Args:
            entity_data: Original entity data
            user_context: User context with team information

        Returns:
            Entity data enhanced with multitenancy fields
        """
        # Create copy to avoid modifying original
        enhanced_data = dict(entity_data)

        # Add team assignment (assign to importing user's personal team)
        if not enhanced_data.get("team_id"):
            enhanced_data["team_id"] = user_context["team_id"]

        if not enhanced_data.get("owner_email"):
            enhanced_data["owner_email"] = user_context["user_email"]

        # Set visibility: use export value if present, otherwise default to 'public'
        # This supports pre-0.7.0 exports that don't have visibility field
        if not enhanced_data.get("visibility"):
            enhanced_data["visibility"] = "public"  # Default to public for backward compatibility

        # Add import tracking
        if not enhanced_data.get("federation_source"):
            enhanced_data["federation_source"] = f"imported-by-{user_context['user_email']}"

        logger.debug(f"Enhanced entity with multitenancy: team_id={enhanced_data['team_id']}, visibility={enhanced_data['visibility']}")
        return enhanced_data

    async def _assign_imported_items_to_team(self, db: Session, imported_by: str) -> None:
        """Assign imported items without team assignment to the importer's personal team.

        Args:
            db: Database session
            imported_by: Email of user who performed the import
        """
        try:
            # Find the importing user and their personal team
            user = db.query(EmailUser).filter(EmailUser.email == imported_by).first()
            if not user:
                logger.warning(f"Could not find importing user {imported_by} - skipping team assignment")
                return

            personal_team = user.get_personal_team()
            if not personal_team:
                logger.warning(f"User {imported_by} has no personal team - skipping team assignment")
                return

            logger.info(f"Assigning orphaned imported items to {imported_by}'s team: {personal_team.name}")

            # Resource types to check
            resource_types = [("servers", Server), ("tools", Tool), ("resources", Resource), ("prompts", Prompt), ("gateways", Gateway), ("a2a_agents", A2AAgent)]

            total_assigned = 0

            for resource_name, resource_model in resource_types:
                try:
                    # Find items without team assignment (recently imported)
                    unassigned = db.query(resource_model).filter((resource_model.team_id.is_(None)) | (resource_model.owner_email.is_(None))).all()

                    if unassigned:
                        logger.info(f"Assigning {len(unassigned)} orphaned {resource_name} to user team")

                        for item in unassigned:
                            item.team_id = personal_team.id
                            item.owner_email = user.email
                            # Set imported items to public for better visibility
                            item.visibility = "public"
                            if hasattr(item, "federation_source") and not item.federation_source:
                                item.federation_source = f"imported-by-{imported_by}"

                        total_assigned += len(unassigned)

                except Exception as e:
                    logger.error(f"Failed to assign {resource_name} to team: {e}")
                    continue

            if total_assigned > 0:
                db.commit()
                logger.info(f"Assigned {total_assigned} imported items to {personal_team.name} with public visibility")
            else:
                logger.debug("No orphaned imported items found")

        except Exception as e:
            logger.error(f"Failed to assign imported items to team: {e}")
            # Don't fail the import for team assignment issues
