# -*- coding: utf-8 -*-
# pylint: disable=import-outside-toplevel,no-name-in-module
"""Location: ./mcpgateway/services/import_service.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Import Service Implementation.
This module implements comprehensive configuration import functionality according to the import specification.
It handles:
- Import file validation and schema compliance
- Entity creation and updates with conflict resolution
- Dependency resolution and processing order
- Credential omission and reconfiguration reporting
- Dry-run functionality for validation
- Import status tracking and progress reporting
"""

# Standard
from collections import defaultdict
from collections.abc import Callable
from contextlib import AsyncExitStack
from datetime import datetime, timedelta, timezone
from enum import Enum
from inspect import isawaitable
import logging
from types import SimpleNamespace
from typing import Any, cast, Dict, List, Optional
from urllib.parse import urlsplit
import uuid

# Third-Party
from sqlalchemy import and_, false, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

# First-Party
from mcpgateway import __version__
from mcpgateway.common.models import Root
from mcpgateway.config import settings
from mcpgateway.db import EmailTeam, EmailTeamMember, EmailUser, Gateway, Prompt, Resource, Server, Tool
from mcpgateway.schemas import GatewayCreate, GatewayUpdate, PromptCreate, PromptUpdate, ResourceCreate, ResourceUpdate, ServerCreate, ServerUpdate, ToolCreate, ToolUpdate
from mcpgateway.services.gateway_service import GatewayDuplicateConflictError, GatewayError, GatewayNameConflictError, gateway_requires_credentials, GatewayToolNameConflictError
from mcpgateway.services.import_effects import pending_import_effects
from mcpgateway.services.prompt_service import PromptError, PromptNameConflictError
from mcpgateway.services.resource_service import ResourceError, ResourceURIConflictError
from mcpgateway.services.root_service import RootServiceValidationError
from mcpgateway.services.server_service import ServerError, ServerNameConflictError
from mcpgateway.services.tool_service import ToolError, ToolNameConflictError, ToolValidationError
from mcpgateway.services.tool_validation_policy import admit_tool, check_policy_permission, policy_changed, policy_text
from mcpgateway.utils.create_slug import build_gateway_tool_invocation_name, slugify
from mcpgateway.utils.header_filtering import is_tool_credential_header_name
from mcpgateway.utils.portable_credentials import without_file_credentials
from mcpgateway.utils.services_auth import decode_auth

logger = logging.getLogger(__name__)

REKEY_SECRET_REMOVED = "Import does not support rekey_secret. Use python -m mcpgateway.scripts.migrate_enc_secret to rotate the encryption secret."
_DESTINATION_TEAM_REQUIRED = "Team-visible entities require a destination team. Specify team_name or set up a personal team."


EntityData = dict[str, Any]
SelectedEntities = dict[str, list[EntityData]]
DestinationIndexes = dict[str, defaultdict[str | None, list[Any]]]
ImportMappings = dict[str, dict[str, Any]]
CatalogSchema = ToolCreate | ToolUpdate | GatewayCreate | GatewayUpdate | ResourceCreate | ResourceUpdate | PromptCreate | PromptUpdate
RegistryModel = type[Tool] | type[Gateway] | type[Server] | type[Prompt] | type[Resource]
REGISTRY_MODELS: dict[str, RegistryModel] = {"tools": Tool, "gateways": Gateway, "servers": Server, "prompts": Prompt, "resources": Resource}


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


class _ImportDestinationTeamRequired(ImportValidationError):
    """A team-visible create has no destination team."""


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
        self.unknown_entities = 0
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.credentials_required: List[Dict[str, str]] = []
        self.imported_by: Optional[str] = None
        self.team_id: Optional[str] = None
        self.request_team_ids: Optional[frozenset[str]] = None
        self.platform_scope = False
        self.items: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
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
                **({"unknown": self.unknown_entities} if self.unknown_entities else {}),
            },
            "credentials_required": self.credentials_required,
            "errors": self.errors,
            "warnings": self.warnings,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class ImportService:
    """Service for importing ContextForge configuration and data.

    This service provides comprehensive import functionality including:
    - Import file validation and schema compliance
    - Entity creation and updates with conflict resolution
    - Dependency resolution and correct processing order
    - Secure authentication data handling with re-encryption
    - Dry-run capabilities for validation without changes
    - Progress tracking and status reporting
    """

    def __init__(self) -> None:
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
        # Prefer globally-initialized singletons from mcpgateway.main to ensure
        # services share initialized EventService/Redis clients. Import lazily
        # to avoid circular import at module load time. Fall back to local
        # instances if singletons are not available (tests, isolated usage).
        # Use globally-exported singletons from service modules so they
        # share initialized EventService/Redis clients created at app startup.
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
            source_ids = set()
            for i, entity in enumerate(entity_list):
                if not isinstance(entity, dict):
                    raise ImportValidationError(f"Entity {i} in '{entity_type}' must be a dictionary")

                if entity_type in {"tools", "gateways"} and entity.get("id"):
                    source_id = str(entity["id"])
                    if source_id in source_ids:
                        raise ImportValidationError(f"Duplicate file identifier in '{entity_type}'")
                    source_ids.add(source_id)

                # Check required fields based on entity type
                self._validate_entity_fields(entity_type, entity, i)
                if entity_type == "roots":
                    try:
                        self.root_service.validate_root_input(entity["uri"], entity.get("name"))
                    except RootServiceValidationError as exc:
                        raise ImportValidationError(f"Entity {i} in 'roots' failed root URI policy: {exc.reason_code}") from exc

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
        *,
        team_name: Optional[str] = None,
        token_teams: Optional[List[str]] = None,
        unrestricted_admin: bool = False,
    ) -> ImportStatus:
        """Import selected configuration or calculate its local outcomes.

        Args:
            db: Request database session.
            import_data: Configuration file envelope.
            conflict_strategy: Action for matched entities.
            dry_run: Calculate local outcomes without changing configuration.
            rekey_secret: Removed option. Import rejects it.
            imported_by: Verified actor identity.
            selected_entities: File entity identifiers grouped by type.
            team_name: Optional destination team name.
            token_teams: Verified request team scope.
            unrestricted_admin: Verified unrestricted platform administrator.

        Returns:
            Import status and outcomes.
        """
        if rekey_secret is not None:
            raise ImportValidationError(REKEY_SECRET_REMOVED)
        status = ImportStatus(str(uuid.uuid4()))
        await self._run_import(db, import_data, conflict_strategy, dry_run, imported_by, selected_entities, team_name, token_teams, unrestricted_admin, status)
        if dry_run:
            self.active_imports[status.import_id] = status
        return status

    async def _run_import(
        self,
        db: Session,
        import_data: EntityData,
        strategy: ConflictStrategy,
        dry_run: bool,
        actor: str,
        selection: dict[str, list[str]] | None,
        team_name: str | None,
        token_teams: list[str] | None,
        admin: bool,
        status: ImportStatus,
    ) -> None:
        """Process the selected entries and publish registry effects after commit."""
        self.validate_import_data(import_data)
        status.imported_by = actor
        status.platform_scope = admin and team_name is None
        status.team_id = self._destination_team(db, actor, team_name, token_teams, admin)
        status.request_team_ids = frozenset({status.team_id}) if team_name and status.team_id else (frozenset(token_teams) if token_teams is not None else None)
        export_version = import_data.get("contextforge_version")
        if export_version is not None and export_version != __version__:
            status.warnings.append("Export ContextForge version differs from this instance")
        order = ("roots", "gateways", "tools", "resources", "prompts", "servers")
        entities = import_data["entities"]
        selected = {kind: self._select_entity_list(kind, entities[kind], selection) for kind in order if kind in entities}
        status.total_entities = sum(map(len, selected.values()))
        status.status = "running"
        if not dry_run:
            self.active_imports[status.import_id] = status
        root_events: list[EntityData] = []
        pending_effects: list[Callable[[], Any]] = []
        effect_token = pending_import_effects.set(pending_effects)
        try:
            async with AsyncExitStack() as stack:
                if selected.get("roots"):
                    await stack.enter_async_context(self.root_service.mutation_lock)
                root_state = {str(root.uri): root for root in await self.root_service.list_roots()} if selected.get("roots") else {}
                indexes = self._destination_index(db, selected, token_teams, actor)
                mappings: ImportMappings = {"tools": {}, "gateways": {}, "source_tools": {}, "source_gateways": {}, "gateway_names": {}}
                if not dry_run and status.total_entities:
                    connection = db.connection()
                    # SQLite legacy mode does not put the first SAVEPOINT inside an outer transaction.
                    if connection.dialect.name == "sqlite":
                        driver = connection.connection.driver_connection
                        if driver is None:
                            raise RuntimeError("SQLite connection has no driver connection")
                        if not driver.in_transaction:
                            connection.exec_driver_sql("BEGIN")
                for kind, rows in selected.items():
                    for row in rows:
                        effect_count = len(pending_effects)
                        failed = status.failed_entities
                        await self._apply_import_entry(db, kind, row, indexes, mappings, root_state, root_events, strategy, dry_run, actor, team_name, token_teams, admin, status)
                        if status.failed_entities > failed:
                            del pending_effects[effect_count:]
                    if kind == "gateways" and rows and not dry_run:
                        self._add_discovered_rows(db, selected, indexes, mappings, actor, token_teams)
                if not dry_run and status.total_entities:
                    db.commit()
                    if root_events:
                        self.root_service.publish_import_roots(root_state)
            status.status = "completed"
        except BaseException as exc:
            status.status = "failed"
            status.errors.append(f"Import stopped: {type(exc).__name__}")
            if not dry_run:
                status.created_entities = status.updated_entities = 0
                status.credentials_required.clear()
                for items in status.items.values():
                    for item in items:
                        if item.get("outcome") in {"created", "updated"}:
                            item["outcome"] = "rolled_back"
                db.rollback()
            raise
        finally:
            pending_import_effects.reset(effect_token)
            status.completed_at = datetime.now(timezone.utc)
        if not dry_run:
            for action in pending_effects:
                try:
                    result = action()
                    if isawaitable(result):
                        await result
                except Exception:
                    status.warnings.append("Registry notification or cache update failed after commit")
                    logger.exception("Registry side effect failed after import commit")
            for event in root_events:
                try:
                    await self.root_service.notify_import_root(event)
                except Exception:
                    status.warnings.append("Root change notification failed after commit")
                    logger.exception("Root notification failed after import commit")

    def _destination_team(self, db: Session, actor: str, team_name: str | None, token_teams: list[str] | None, admin: bool) -> str | None:
        """Resolve the requested or personal team within the caller's scope."""
        if team_name is None:
            user = db.scalar(select(EmailUser).where(EmailUser.email == actor))
            team = user.get_personal_team() if user else None
            return team.id if team else None
        query = select(EmailTeam).where(EmailTeam.name == team_name, EmailTeam.is_active.is_(True))
        if not admin:
            query = query.join(EmailTeamMember, EmailTeamMember.team_id == EmailTeam.id).where(EmailTeamMember.user_email == actor, EmailTeamMember.is_active.is_(True))
            if token_teams is not None:
                query = query.where(EmailTeam.id.in_(token_teams))
        matches = db.scalars(query).all()
        if len(matches) != 1:
            if not admin:
                raise PermissionError("Import is not permitted in the destination team")
            raise ImportValidationError("Destination team is unavailable or ambiguous")
        return matches[0].id

    @staticmethod
    def _visible(row: Any, actor: str, token_teams: list[str] | None) -> bool:
        """Check whether the request scope permits reading the destination row."""
        if row.visibility == "public":
            return True
        if token_teams is None:
            return bool(row.visibility == "team" or row.owner_email == actor)
        if not token_teams:
            return False
        return bool((row.visibility == "private" and row.owner_email == actor) or (row.visibility == "team" and row.team_id in token_teams))

    def _destination_index(self, db: Session, selected: SelectedEntities, token_teams: list[str] | None, actor: str) -> DestinationIndexes:
        """Index visible destination records by entity type and match key."""
        kinds = set(selected)
        if selected.get("servers"):
            kinds.update(("tools", "gateways"))
        if any(row.get("gateway_id") or row.get("gateway_name") for kind in ("tools", "resources", "prompts") for row in selected.get(kind, [])):
            kinds.add("gateways")
        indexes: DestinationIndexes = {kind: defaultdict(list) for kind in REGISTRY_MODELS}
        for kind in kinds & REGISTRY_MODELS.keys():
            model = REGISTRY_MODELS[kind]
            if token_teams is None:
                visible = or_(model.visibility != "private", and_(model.visibility == "private", model.owner_email == actor))
            else:
                visible = or_(
                    model.visibility == "public",
                    and_(model.visibility == "team", model.team_id.in_(token_teams)),
                    and_(model.visibility == "private", model.owner_email == actor) if token_teams else false(),
                )
            for row in db.scalars(select(model).where(visible)).unique():
                indexes[kind][self._destination_key(kind, row)].append(row)
        return indexes

    def _add_discovered_rows(self, db: Session, selected: SelectedEntities, indexes: DestinationIndexes, mappings: ImportMappings, actor: str, token_teams: list[str] | None) -> None:
        """Index visible catalog items discovered by gateways in this import."""
        gateway_ids = {gateway.id for bucket in (mappings["gateways"], mappings["gateway_names"]) for gateway in bucket.values() if gateway is not None}
        if not gateway_ids:
            return
        catalog_models: tuple[tuple[str, type[Tool] | type[Resource] | type[Prompt]], ...] = (("tools", Tool), ("resources", Resource), ("prompts", Prompt))
        for kind, model in catalog_models:
            if kind not in selected and not (kind == "tools" and selected.get("servers")):
                continue
            for record in db.scalars(select(model).where(model.gateway_id.in_(gateway_ids)).execution_options(populate_existing=True)).unique():
                row = cast(Tool | Resource | Prompt, record)
                if not self._visible(row, actor, token_teams):
                    continue
                bucket = indexes[kind][self._destination_key(kind, row)]
                if all(other.id != row.id for other in bucket):
                    bucket.append(row)

    @staticmethod
    def _mapped_gateway(data: EntityData, indexes: DestinationIndexes, mappings: ImportMappings) -> Gateway | SimpleNamespace | None:
        """Resolve a file reference to an unambiguous destination gateway."""
        source_gateway_id = str(data.get("gateway_id") or "")
        gateway_name = data.get("gateway_name")
        gateway_url = data.get("gateway_url")
        if source_gateway_id in mappings["gateways"]:
            source = mappings["source_gateways"][source_gateway_id]
            if (gateway_name is not None and source["name"] != gateway_name) or (gateway_url is not None and source["url"] != gateway_url):
                return None
            return cast(Gateway | SimpleNamespace | None, mappings["gateways"][source_gateway_id])
        if not gateway_name:
            return None
        if gateway_name in mappings["gateway_names"]:
            mapped = mappings["gateway_names"][gateway_name]
            if mapped is None or gateway_url is not None and mapped.url != gateway_url:
                return None
            return cast(Gateway | SimpleNamespace, mapped)
        if not gateway_url:
            return None
        candidates = [gateway for gateway in indexes["gateways"].get(slugify(gateway_name), ()) if getattr(gateway, "url", None) == gateway_url]
        return cast(Gateway | SimpleNamespace, candidates[0]) if len(candidates) == 1 else None

    @staticmethod
    def _destination_key(kind: str, row: Any) -> str | None:
        """Return the match key for an existing destination record."""
        if kind == "gateways":
            return cast(str, row.slug)
        if kind == "resources":
            return cast(str, row.uri)
        if kind == "tools":
            return cast(str, row.original_name)
        return cast(str | None, row.original_name if kind == "prompts" and getattr(row, "gateway_id", None) is not None else row.name)

    @staticmethod
    def _federated_prompt_key(row: EntityData) -> str:
        """Return the upstream prompt name used for a federated match."""
        return cast(str, row.get("original_name") or row["name"])

    @staticmethod
    def _file_key(kind: str, row: EntityData) -> str:
        """Return the match key for a configuration file entry."""
        if kind in {"roots", "resources"}:
            return cast(str, row["uri"])
        if kind == "gateways":
            return slugify(row["name"])
        if kind == "prompts":
            return slugify(row.get("custom_name") or row.get("original_name") or row["name"])
        return cast(str, row["name"])

    async def _apply_import_entry(
        self,
        db: Session,
        kind: str,
        row: EntityData,
        indexes: DestinationIndexes,
        mappings: ImportMappings,
        root_state: dict[str, Root],
        root_events: list[EntityData],
        strategy: ConflictStrategy,
        dry_run: bool,
        actor: str,
        team_name: str | None,
        token_teams: list[str] | None,
        admin: bool,
        status: ImportStatus,
    ) -> None:
        """Process one entry and record its outcome in the import status."""
        status.processed_entities += 1
        identifier = self._get_entity_identifier(kind, row)
        is_gateway_item = bool(row.get("gateway_name") or row.get("gateway_id"))
        item: EntityData = {
            "id": str(row.get("id") or identifier),
            "identifier": identifier,
            "name": row.get("name") or identifier,
            "type": kind,
            "conflicts_with": None,
            "is_gateway_item": is_gateway_item,
            "is_custom": not is_gateway_item,
            "description": row.get("description", ""),
        }
        if kind == "servers":
            item["dependencies"] = self._preview_server_dependencies(row)
        status.items[kind].append(item)
        local_warnings: list[str] = []
        try:
            clean, ignored = without_file_credentials(row, validate_headers=True) if kind in {"tools", "gateways"} else (dict(row), ())
            if clean.get("visibility") is None:
                clean.pop("visibility", None)
            if ignored:
                logger.info("Ignored portable configuration credential fields: %s", ", ".join(ignored))
            source_identity = dict(clean)
            file_id = str(clean.get("id") or "")
            if kind in {"tools", "gateways"} and file_id and file_id in mappings[f"source_{kind}"]:
                raise ImportValidationError("Duplicate file entity identifier")
            key = self._file_key(kind, clean)
            mapped_gateway = None
            candidates: list[Any]
            if kind == "roots":
                uri, name = self.root_service.validate_root_input(key, clean.get("name"))
                candidates = [root_state[uri]] if uri in root_state else []
            else:
                federated = kind in {"tools", "resources", "prompts"} and is_gateway_item
                if federated and kind == "tools" and clean.get("integration_type") == "A2A":
                    raise ImportValidationError("Derived A2A tools use local agent bindings")
                mapped_gateway = self._mapped_gateway(clean, indexes, mappings) if federated else None
                if federated and mapped_gateway is None:
                    raise ImportValidationError("Federated file item has no matching destination gateway")
                gateway_id = mapped_gateway.id if mapped_gateway is not None else None
                if federated and kind == "prompts":
                    key = self._federated_prompt_key(clean)
                candidates = [
                    candidate
                    for candidate in indexes[kind][key]
                    if (team_name is None or candidate.team_id == status.team_id) and (kind not in {"tools", "resources", "prompts"} or candidate.gateway_id == gateway_id)
                ]
                if federated and strategy == ConflictStrategy.RENAME:
                    raise ImportValidationError("Federated file items do not support rename")
                if federated and not candidates:
                    planned_gateway = dry_run and isinstance(mapped_gateway, SimpleNamespace)
                    blocked_gateway = isinstance(mapped_gateway, Gateway) and gateway_requires_credentials(mapped_gateway)
                    if not (planned_gateway or blocked_gateway):
                        raise ImportValidationError("Federated file item does not match a discovered entity")
                    if kind == "resources":
                        ResourceCreate.validate_uri(key)
                    self._catalog_import_schema(kind, clean, create=False)
                    self._record_mapping(mappings, kind, source_identity, None)
                    if planned_gateway:
                        item["outcome"] = "unknown"
                        item["upstream_check"] = "unknown"
                        status.unknown_entities += 1
                        local_warnings.append(f"{kind} item {identifier}: match depends on upstream discovery")
                    else:
                        item["outcome"] = "skipped"
                        status.skipped_entities += 1
                        local_warnings.append(f"{kind} item {identifier}: skipped until the destination gateway has credentials")
                    return
                if not admin and (not federated or strategy == ConflictStrategy.UPDATE):
                    eligible = [candidate for candidate in candidates if self._can_update_import_candidate(candidate, actor, token_teams)]
                    if federated and not eligible:
                        raise PermissionError("Caller cannot update this entity")
                    candidates = eligible
            if len(candidates) > 1:
                if strategy == ConflictStrategy.FAIL:
                    raise ImportConflictError(f"Ambiguous match for {kind} item: {item['identifier']}")
                raise ImportValidationError("Import match is ambiguous")
            existing = candidates[0] if candidates else None
            item["conflicts_with"] = existing is not None
            if existing is not None and strategy == ConflictStrategy.FAIL:
                raise ImportConflictError(f"Conflict for {kind} item: {item['identifier']}")
            if existing is not None and strategy == ConflictStrategy.SKIP:
                item["outcome"] = "skipped"
                status.skipped_entities += 1
                self._record_mapping(mappings, kind, source_identity, existing)
                return
            if existing is not None and strategy == ConflictStrategy.RENAME:
                if kind == "roots":
                    raise ImportValidationError("Root URIs do not support rename")
                field = "uri" if kind == "resources" else "name"
                stem = clean[field]
                suffix = 1
                while True:
                    clean[field] = f"{stem}_imported_{suffix}"
                    if kind == "prompts":
                        clean.pop("original_name", None)
                        clean.pop("custom_name", None)
                    key = self._file_key(kind, clean)
                    if not indexes[kind][key]:
                        break
                    suffix += 1
                existing = None
            if kind == "roots":
                prepared = Root(uri=uri, name=name if name is not None else getattr(existing, "name", None) or uri)
                root_state[str(prepared.uri)] = prepared
                if not dry_run:
                    root_events.append({"type": "root_updated" if existing else "root_added", "data": {"uri": prepared.uri, "name": prepared.name}})
            else:
                if kind == "gateways" and self._is_token_exchange(existing) and not admin:
                    raise PermissionError("Caller cannot update a token-exchange gateway")
                if existing is None and not admin and token_teams is not None and status.team_id not in token_teams:
                    raise PermissionError("Caller cannot create this entity in the destination team")
                if existing is None and status.team_id is None and clean.get("visibility", "team") == "team":
                    raise _ImportDestinationTeamRequired(_DESTINATION_TEAM_REQUIRED)
                if dry_run:
                    if kind == "gateways":
                        item["upstream_check"] = "unknown"
                    schema, needs_credentials = self._prepare_import_schema(
                        db, kind, clean, existing, indexes, mappings, local_warnings, actor, token_teams, dry_run, status.team_id if team_name is not None else None
                    )
                    if isinstance(schema, (ToolCreate, ToolUpdate, GatewayCreate, GatewayUpdate)):
                        await self._preview_validation_policy(db, kind, schema, existing, actor, status.team_id)
                    if existing is None:
                        self._check_preview_create_conflict(kind, key, schema, indexes, clean.get("visibility", "team"), status.team_id)
                    if isinstance(schema, ToolUpdate) and existing is not None:
                        duplicate = self._preview_tool_name_conflict(schema, existing, mapped_gateway, indexes[kind], clean.get("visibility"))
                        if duplicate is not None:
                            item["conflicts_with"] = True
                            raise ToolNameConflictError(duplicate.name, enabled=getattr(duplicate, "enabled", True), tool_id=duplicate.id, visibility=duplicate.visibility)
                    if isinstance(schema, (GatewayCreate, GatewayUpdate)):
                        duplicate_gateway = self._preview_gateway_duplicate(schema, existing, indexes, clean, actor, status.team_id, needs_credentials)
                        if duplicate_gateway is not None:
                            item["conflicts_with"] = True
                            raise GatewayDuplicateConflictError(duplicate_gateway)
                    result = existing or self._planned_entry(kind, key, clean, status)
                else:
                    connection = db.connection()
                    # PostgreSQL holds row locks from successful items through discovery until the outer commit.
                    with connection.begin_nested():
                        # Keep service commits and rollbacks inside the current item savepoint.
                        with Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False) as item_db:
                            if mapped_gateway is not None:
                                locked_gateway = item_db.scalar(select(Gateway).where(Gateway.id == mapped_gateway.id).with_for_update())
                                if (
                                    locked_gateway is None
                                    or not self._visible(locked_gateway, actor, token_teams)
                                    or locked_gateway.name != mapped_gateway.name
                                    or locked_gateway.url != mapped_gateway.url
                                ):
                                    raise PermissionError("Caller cannot update this gateway entity")
                            if existing is not None:
                                locked = item_db.scalar(select(type(existing)).where(type(existing).id == existing.id).with_for_update())
                                if (
                                    locked is None
                                    or not self._visible(locked, actor, token_teams)
                                    or (mapped_gateway is not None and locked.gateway_id != mapped_gateway.id)
                                    or (team_name is not None and locked.team_id != status.team_id)
                                    or (not admin and not self._can_update_import_candidate(locked, actor, token_teams))
                                ):
                                    raise PermissionError("Caller cannot update this entity")
                                existing = locked
                                if kind == "gateways" and self._is_token_exchange(locked) and not admin:
                                    raise PermissionError("Caller cannot update a token-exchange gateway")
                            schema, needs_credentials = self._prepare_import_schema(
                                item_db, kind, clean, existing, indexes, mappings, local_warnings, actor, token_teams, dry_run, status.team_id if team_name is not None else None
                            )
                            result = await self._write_import_entity(item_db, kind, schema, existing, clean, actor, status.team_id, needs_credentials, admin, token_teams)
                            model = REGISTRY_MODELS[kind]
                            result = item_db.get(model, result.id)
                            if result is None:
                                raise RuntimeError("Registry service did not persist the import item")
                            if isinstance(result, Tool) and existing is None and isinstance(clean.get("original_description"), str):
                                result.original_description = clean["original_description"]
                            needs_credentials |= isinstance(result, Gateway) and gateway_requires_credentials(result)
                            item_db.commit()
                if existing is None:
                    indexes[kind][key].append(result)
                else:
                    indexes[kind][key] = [result if candidate.id == result.id else candidate for candidate in indexes[kind][key]]
                self._record_mapping(mappings, kind, source_identity, result)
                if needs_credentials:
                    status.credentials_required.append({"type": kind, "identifier": item["identifier"]})
            outcome = "updated" if existing is not None else "created"
            item["outcome"] = outcome
            if outcome == "created":
                status.created_entities += 1
            else:
                status.updated_entities += 1
        except (
            ToolNameConflictError,
            GatewayNameConflictError,
            GatewayDuplicateConflictError,
            GatewayToolNameConflictError,
            ServerNameConflictError,
            PromptNameConflictError,
            ResourceURIConflictError,
        ) as exc:
            if strategy == ConflictStrategy.FAIL:
                raise ImportConflictError(f"Conflict for {kind} item: {item['identifier']}") from exc
            item["outcome"] = "failed"
            item["conflicts_with"] = True
            status.failed_entities += 1
            status.errors.append(f"{kind} item {item['identifier']}: configuration conflict")
            logger.warning("Import %s item %d (%s): %s", status.import_id, status.processed_entities, kind, type(exc).__name__)
        except (ValueError, TypeError, PermissionError, ImportValidationError, GatewayError, ServerError, ToolError, ResourceError, PromptError, IntegrityError) as exc:
            cause = exc.__cause__ or exc.__context__
            if isinstance(cause, SQLAlchemyError) and not isinstance(cause, IntegrityError):
                raise
            item["outcome"] = "failed"
            status.failed_entities += 1
            reason = _DESTINATION_TEAM_REQUIRED if isinstance(exc, _ImportDestinationTeamRequired) else type(exc).__name__
            status.errors.append(f"{kind} item {item['identifier']}: {reason}")
            logger.warning("Import %s item %d (%s): %s", status.import_id, status.processed_entities, kind, type(exc).__name__)
        finally:
            status.warnings.extend(local_warnings)

    @staticmethod
    def _can_update_import_candidate(candidate: Any, actor: str, token_teams: list[str] | None) -> bool:
        """Check whether the caller owns a candidate within their token scope."""
        return bool(candidate.owner_email == actor) and (token_teams is None or candidate.team_id in token_teams)

    @staticmethod
    def _planned_entry(kind: str, key: str, data: EntityData, status: ImportStatus) -> SimpleNamespace:
        """Represent a proposed create for subsequent matches during dry run."""
        return SimpleNamespace(
            id=f"planned:{kind}:{key}",
            original_name=data.get("name"),
            custom_name=data.get("name"),
            gateway_id=None,
            name=data.get("name"),
            team_id=status.team_id,
            owner_email=status.imported_by,
            url=data.get("url"),
            visibility=data.get("visibility", "team"),
            auth_type=None,
            auth_value=None,
            oauth_config=None,
            sigv4_config=None,
            enabled=True,
        )

    @staticmethod
    def _record_mapping(mappings: ImportMappings, kind: str, data: EntityData, result: Any) -> None:
        """Record how file identifiers and names resolve to destination records."""
        if kind in mappings and data.get("id"):
            source_id = str(data["id"])
            mappings[kind][source_id] = result
            mappings[f"source_{kind}"][source_id] = data
        if kind == "gateways":
            name = data["name"]
            previous = mappings["gateway_names"].get(name)
            if name in mappings["gateway_names"] and (previous is None or previous.id != result.id):
                mappings["gateway_names"][name] = None
            else:
                mappings["gateway_names"][name] = result

    def _catalog_import_schema(self, kind: str, data: EntityData, *, create: bool) -> CatalogSchema:
        """Build a catalog write schema from local file data."""
        to_schema: dict[str, tuple[Callable[[EntityData], CatalogSchema], Callable[[EntityData], CatalogSchema]]] = {
            "tools": (self._convert_to_tool_create, self._convert_to_tool_update),
            "gateways": (self._convert_to_gateway_create, self._convert_to_gateway_update),
            "prompts": (self._convert_to_prompt_create, self._convert_to_prompt_update),
            "resources": (self._convert_to_resource_create, self._convert_to_resource_update),
        }
        visibility = data.get("visibility")
        if visibility is not None and visibility not in {"public", "team", "private"}:
            raise ImportValidationError("Invalid visibility")
        schema = to_schema[kind][0 if create else 1](data)
        if not create and visibility is not None:
            schema.visibility = visibility
        return schema

    def _prepare_import_schema(
        self,
        db: Session,
        kind: str,
        data: EntityData,
        existing: Any,
        indexes: DestinationIndexes,
        mappings: ImportMappings,
        warnings: list[str],
        actor: str,
        token_teams: list[str] | None,
        dry_run: bool,
        explicit_team_id: str | None,
    ) -> tuple[CatalogSchema | ServerCreate | ServerUpdate, bool]:
        """Build a write schema and report whether the entity needs credentials."""
        create = existing is None
        if kind == "servers":
            names = ("tool_refs", "tool_ids", "associated_tools")
            references = next((data[key] for key in names if key in data), None)
            payload: EntityData = {key: data[key] for key in ("name", "description", "instructions", "tags", "visibility") if key in data}
            complete = data.get("tool_refs_complete", True)
            if not isinstance(complete, bool):
                raise ImportValidationError("tool_refs_complete must be a boolean")
            if not complete:
                warnings.append(f"Export omitted some tool bindings for server {data['name']}")
            if references is not None:
                ids, unresolved = self._resolve_import_bindings(db, references, indexes, mappings, actor, token_teams, dry_run, explicit_team_id)
                if unresolved:
                    warnings.append(f"Unresolved tool references for server {data['name']}: {', '.join(unresolved)}")
                if create or (complete and not unresolved):
                    payload["associated_tools"] = ids
            return (ServerCreate if create else ServerUpdate)(**payload), False
        needs_credentials = bool(data.get("credentials_required")) and create
        schema = self._catalog_import_schema(kind, data, create=create)
        existing_type = getattr(existing, "integration_type", None)
        if isinstance(schema, ToolUpdate) and "A2A" in (schema.integration_type, existing_type):
            if schema.integration_type != existing_type:
                raise ImportValidationError("Cannot change A2A tool integration type")
            if schema.annotations is not None:
                if not isinstance(existing.annotations, dict) or schema.annotations.get("a2a_agent_id") != existing.annotations.get("a2a_agent_id"):
                    raise ImportValidationError("Cannot change A2A tool binding")
            # Portable files cannot replace the endpoint or credentials of an agent's derived tool.
            stored_transport, _ = without_file_credentials({"url": existing.url, "headers": existing.headers})
            if (
                data["url"] != stored_transport["url"]
                or schema.request_type not in (None, existing.request_type)
                or (schema.headers is not None and schema.headers != stored_transport.get("headers"))
                or schema.visibility not in (None, existing.visibility)
            ):
                raise ImportValidationError("Import can only update metadata for a derived A2A tool")
            return schema.model_copy(update={"url": None, "request_type": None, "headers": None}), False
        if isinstance(schema, (GatewayCreate, GatewayUpdate)) and schema.gateway_mode == "direct_proxy" and not settings.mcpgateway_direct_proxy_enabled:
            raise ImportValidationError("Direct-proxy gateways are disabled")
        if not isinstance(schema, (GatewayUpdate, ToolUpdate)):
            return schema, needs_credentials
        credential_headers = {key: value for key, value in (getattr(existing, "headers", None) or {}).items() if is_tool_credential_header_name(key)}
        credential_material = self._has_destination_credentials(existing, credential_headers)
        origin_changed = schema.url is not None and self._origin(str(schema.url)) != self._origin(existing.url)
        if isinstance(schema, ToolUpdate) and schema.headers is not None and not origin_changed:
            schema.headers = {**schema.headers, **credential_headers}
        return schema, bool(origin_changed and credential_material or data.get("credentials_required") and not credential_material or kind == "gateways" and gateway_requires_credentials(existing))

    @staticmethod
    def _has_destination_credentials(entity: Any, header_credentials: dict[str, Any]) -> bool:
        """Check whether the destination entity has credential material."""
        return bool(
            getattr(entity, "auth_value", None)
            or any(header_credentials.values())
            or getattr(entity, "auth_query_params", None)
            or getattr(entity, "add_headers", None)
            or getattr(entity, "client_key", None)
            or getattr(entity, "oauth_config", None)
            or getattr(entity, "auth_type", None) == "sigv4"
            or getattr(entity, "sigv4_config", None)
            or without_file_credentials({"url": entity.url})[1]
        )

    @staticmethod
    def _origin(url: str) -> tuple[str, str | None, int | None]:
        """Return the scheme, host, and effective port of a URL."""
        parsed = urlsplit(url)
        return parsed.scheme, parsed.hostname, parsed.port or {"http": 80, "https": 443, "ws": 80, "wss": 443}.get(parsed.scheme)

    def _resolve_import_bindings(
        self, db: Session, references: Any, indexes: DestinationIndexes, mappings: ImportMappings, actor: str, token_teams: list[str] | None, dry_run: bool, explicit_team_id: str | None
    ) -> tuple[list[str], list[str]]:
        """Resolve tool references and return labels for unresolved entries."""
        by_id = {str(tool.id): tool for group in indexes["tools"].values() for tool in group}
        gateways_by_id = {str(gateway.id): gateway for group in indexes["gateways"].values() for gateway in group}
        expected = {}
        unresolved = []
        labels = {}
        if not isinstance(references, list):
            raise ImportValidationError("Server tool references must be a list")
        for index, reference in enumerate(references):
            gateway = None
            if isinstance(reference, str):
                tool = mappings["tools"].get(reference, by_id.get(reference))
            elif isinstance(reference, dict):
                source_id = str(reference.get("id", ""))
                original_name = reference.get("original_name")
                source_tool = mappings["source_tools"].get(source_id)
                tool = mappings["tools"].get(source_id, by_id.get(source_id))
                if (reference.get("gateway_id") or reference.get("gateway_name")) and not (source_id in mappings["tools"] and tool is None):
                    gateway = self._mapped_gateway(reference, indexes, mappings)
                    matching = [candidate for candidate in indexes["tools"].get(original_name, ()) if gateway is not None and candidate.gateway_id == gateway.id]
                    tool = matching[0] if len(matching) == 1 else None
                elif source_tool is not None:
                    if tool is None or tool.gateway_id is not None or source_tool.get("name") != original_name:
                        tool = None
                elif tool is None or tool.gateway_id is not None or tool.original_name != original_name:
                    matched = [
                        candidate
                        for candidate in indexes["tools"].get(original_name, ())
                        if candidate.gateway_id is None and (explicit_team_id is None or candidate.team_id == explicit_team_id) and (explicit_team_id is not None or candidate.owner_email == actor)
                    ]
                    tool = matched[0] if len(matched) == 1 else None
            else:
                tool = None
            if tool is not None:
                if tool.gateway_id is not None:
                    gateway = gateway or gateways_by_id.get(str(tool.gateway_id))
                    if not gateway or not self._visible(gateway, actor, token_teams):
                        tool = None
                elif explicit_team_id is not None and tool.team_id != explicit_team_id:
                    tool = None
            label = f"reference {index + 1}"
            if isinstance(reference, dict) and isinstance(reference.get("original_name"), str):
                label += f" ({reference['original_name']})"
            if tool is None:
                unresolved.append(label)
            else:
                tool_id = str(tool.id)
                labels[tool_id] = label
                expected[tool_id] = (tool, gateway)
        if expected and not dry_run:
            actual = self._lock_import_bindings(db, expected, actor, token_teams, explicit_team_id)
            unresolved.extend(labels[tool_id] for tool_id in expected if tool_id not in actual)
            expected = {tool_id: reference for tool_id, reference in expected.items() if tool_id in actual}
        return list(expected), unresolved

    def _lock_import_bindings(self, db: Session, expected: dict[str, tuple[Any, Any]], actor: str, token_teams: list[str] | None, explicit_team_id: str | None) -> set[str]:
        """Lock candidate bindings and recheck visibility and identity."""
        gateway_ids = {gateway.id for _, gateway in expected.values() if gateway is not None}
        gateways = {}
        if gateway_ids:
            gateways = {
                gateway.id: gateway
                for gateway in db.scalars(select(Gateway).where(Gateway.id.in_(gateway_ids)).order_by(Gateway.id).with_for_update()).unique()
                if self._visible(gateway, actor, token_teams)
            }
        actual = set()
        for row in db.scalars(select(Tool).where(Tool.id.in_(expected)).order_by(Tool.id).with_for_update()).unique():
            tool, gateway = expected[str(row.id)]
            if not self._visible(row, actor, token_teams) or row.gateway_id != tool.gateway_id or row.original_name != tool.original_name:
                continue
            if gateway is not None:
                locked = gateways.get(gateway.id)
                if locked is None or locked.name != gateway.name or locked.url != gateway.url:
                    continue
            elif explicit_team_id is not None and row.team_id != explicit_team_id:
                continue
            actual.add(str(row.id))
        return actual

    def _preview_gateway_duplicate(
        self, schema: GatewayCreate | GatewayUpdate, existing: Any, indexes: DestinationIndexes, data: EntityData, actor: str, team_id: str | None, needs_credentials: bool
    ) -> Gateway | None:
        """Check for a gateway URL and authentication conflict during dry run."""
        url = self.gateway_service.normalize_url(str(schema.url or getattr(existing, "url", "")))
        visibility = data.get("visibility") or getattr(existing, "visibility", None) or "team"
        owner = getattr(existing, "owner_email", actor)
        target_team = getattr(existing, "team_id", team_id)
        reset = existing is not None and self._origin(url) != self._origin(existing.url) and needs_credentials
        auth_value = None if reset else getattr(existing, "auth_value", None)
        if isinstance(auth_value, str):
            auth_value = decode_auth(auth_value)
        oauth_config = None if reset else getattr(existing, "oauth_config", None)
        sigv4_config = None if reset else getattr(existing, "sigv4_config", None)
        eligible = [
            gateway
            for rows in indexes["gateways"].values()
            for gateway in rows
            if gateway.id != getattr(existing, "id", None)
            and gateway.url == url
            and gateway.visibility == visibility
            and (visibility == "public" or visibility == "private" and gateway.owner_email == owner or visibility == "team" and target_team and gateway.team_id == target_team)
        ]
        return cast(Gateway | None, self.gateway_service.find_duplicate_gateway(eligible, auth_value, oauth_config, sigv4_config))

    @staticmethod
    def _check_preview_create_conflict(kind: str, key: str, schema: CatalogSchema | ServerCreate | ServerUpdate, indexes: DestinationIndexes, visibility: str, team_id: str | None) -> None:
        """Check visibility conflicts with rows outside the update candidates."""
        errors = {"tools": ToolNameConflictError, "gateways": GatewayNameConflictError, "resources": ResourceURIConflictError, "prompts": PromptNameConflictError}
        if kind not in errors or visibility not in {"public", "team"}:
            return
        if kind in {"tools", "gateways"} and visibility == "team" and not team_id:
            return
        buckets = indexes[kind].values() if kind == "tools" and visibility == "public" else (indexes[kind][key],)
        rows = (row for bucket in buckets for row in bucket)
        if kind == "tools":
            rows = (row for row in rows if row.name == schema.name)
        for row in rows:
            if kind in {"prompts", "resources"} and row.gateway_id is not None:
                continue
            if row.visibility == visibility and (visibility == "public" or row.team_id == team_id):
                raise errors[kind](key)

    @staticmethod
    def _preview_tool_name_conflict(schema: ToolUpdate, existing: Any, gateway: Gateway | SimpleNamespace | None, tools: dict[str | None, list[Any]], visibility: str | None) -> Any:
        """Check for a conflicting public tool name during a planned update."""
        target_visibility = visibility or existing.visibility
        if target_visibility != "public":
            return None
        name_changed = schema.name is not None and schema.name != existing.name
        if not name_changed and target_visibility == existing.visibility:
            return None
        if gateway is not None and target_visibility != existing.visibility:
            name = build_gateway_tool_invocation_name(gateway.name, existing.custom_name)
            return next((row for group in tools.values() for row in group if row.id != existing.id and row.name == name and row.visibility == "public"), None)
        custom_name = schema.name if name_changed and existing.name == existing.custom_name else existing.custom_name
        return next((row for group in tools.values() for row in group if row.id != existing.id and row.custom_name == custom_name and row.visibility == "public"), None)

    @staticmethod
    async def _preview_validation_policy(db: Session, kind: str, schema: GatewayCreate | GatewayUpdate | ToolCreate | ToolUpdate, existing: Any, actor: str, team_id: str | None) -> None:
        """Apply local validation policy and permission checks during dry run."""
        policy = schema.tool_validation_policy
        if existing is None:
            if policy_text(policy):
                await check_policy_permission(db, actor, resource_type=kind, team_id=team_id)
            if isinstance(schema, ToolCreate) and admit_tool(description=schema.description, tool_name=schema.name, tool_policy=policy, gateway_policy=None, context="register_tool"):
                raise ToolValidationError("Tool does not meet its validation policy")
        elif "tool_validation_policy" in schema.model_fields_set and policy_changed(getattr(existing, "tool_validation_policy", None), policy):
            await check_policy_permission(db, actor, resource_type=kind, team_id=existing.team_id)

    @staticmethod
    def _is_token_exchange(gateway: Any) -> bool:
        """Check whether the gateway uses the OAuth token exchange grant."""
        oauth_config = getattr(gateway, "oauth_config", None)
        return isinstance(oauth_config, dict) and oauth_config.get("grant_type") == "token-exchange"

    async def _write_import_entity(
        self,
        db: Session,
        kind: str,
        schema: CatalogSchema | ServerCreate | ServerUpdate,
        existing: Any,
        data: EntityData,
        actor: str,
        team_id: str | None,
        needs_credentials: bool,
        admin: bool,
        token_teams: list[str] | None,
    ) -> Any:
        """Create or update an entity through its registry service."""
        services = {
            "tools": (self.tool_service, "tool"),
            "gateways": (self.gateway_service, "gateway"),
            "servers": (self.server_service, "server"),
            "resources": (self.resource_service, "resource"),
            "prompts": (self.prompt_service, "prompt"),
        }
        service, name = services[kind]
        if existing is None:
            kwargs: dict[str, Any] = {"created_by": actor, "created_via": "import", "team_id": team_id, "owner_email": actor, "visibility": data.get("visibility", "team")}
            if kind == "gateways":
                kwargs["import_requires_credentials"] = needs_credentials
            elif kind == "tools":
                kwargs["token_teams"] = token_teams
            return await getattr(service, f"register_{name}")(db, schema, **kwargs)
        kwargs = {"modified_by": actor, "modified_via": "import", "user_email": actor, "import_platform_admin": admin}
        if isinstance(schema, (ToolUpdate, GatewayUpdate)) and schema.url is not None and self._origin(str(schema.url)) != self._origin(existing.url) and needs_credentials:
            kwargs["import_clear_credentials"] = True
        if kind == "gateways":
            kwargs["import_requires_credentials"] = needs_credentials
        elif kind == "tools":
            kwargs["token_teams"] = token_teams
        return await getattr(service, f"update_{name}")(db, existing.id, schema, **kwargs)

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
            return cast(str, entity.get("name", ""))
        if entity_type == "resources":
            return cast(str, entity.get("uri", ""))
        if entity_type == "roots":
            return cast(str, entity.get("uri", ""))
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
        return sum(len(self._select_entity_list(entity_type, entity_list, selected_entities)) for entity_type, entity_list in entities.items())

    def _select_entity_list(self, entity_type: str, entity_list: List[Dict[str, Any]], selection: Optional[Dict[str, List[str]]]) -> List[Dict[str, Any]]:
        """Return the file entries selected for one entity type.

        Args:
            entity_type: File entity type.
            entity_list: Available file entries.
            selection: Requested identifiers by entity type.

        Returns:
            Selected file entries in file order.
        """
        if selection is None:
            return entity_list
        if entity_type not in selection:
            return []
        identifiers = set(selection[entity_type])
        if not identifiers:
            return entity_list
        return [entity for entity in entity_list if self._get_entity_identifier(entity_type, entity) in identifiers or entity.get("id") in identifiers]

    def _convert_to_tool_create(self, tool_data: Dict[str, Any]) -> ToolCreate:
        """Convert import data to ToolCreate schema.

        Args:
            tool_data: Tool data dictionary from import

        Returns:
            ToolCreate schema object
        """
        return ToolCreate(
            name=tool_data["name"],
            displayName=tool_data.get("displayName"),
            url=tool_data["url"],
            description=tool_data.get("description"),
            original_description=tool_data.get("original_description"),
            integration_type=tool_data.get("integration_type", "REST"),
            request_type=tool_data.get("request_type", "GET"),
            headers=tool_data.get("headers"),
            input_schema=tool_data.get("input_schema"),
            output_schema=tool_data.get("output_schema"),
            annotations=tool_data.get("annotations"),
            jsonpath_filter=tool_data.get("jsonpath_filter"),
            tool_validation_policy=tool_data.get("tool_validation_policy"),
            tags=tool_data.get("tags", []),
        )

    def _convert_to_tool_update(self, tool_data: Dict[str, Any]) -> ToolUpdate:
        """Convert import data to ToolUpdate schema.

        Args:
            tool_data: Tool data dictionary from import

        Returns:
            ToolUpdate schema object
        """
        discovered_mcp = tool_data.get("integration_type") == "MCP" and bool(tool_data.get("gateway_id") or tool_data.get("gateway_name"))
        transport = {} if discovered_mcp else {"integration_type": tool_data.get("integration_type"), "request_type": tool_data.get("request_type")}
        return ToolUpdate(
            name=tool_data.get("name"),
            displayName=tool_data.get("displayName"),
            url=tool_data.get("url"),
            description=tool_data.get("description"),
            headers=tool_data.get("headers"),
            input_schema=tool_data.get("input_schema"),
            output_schema=tool_data.get("output_schema"),
            annotations=tool_data.get("annotations"),
            jsonpath_filter=tool_data.get("jsonpath_filter"),
            tags=tool_data.get("tags"),
            **transport,
            **({"tool_validation_policy": tool_data["tool_validation_policy"]} if "tool_validation_policy" in tool_data else {}),
        )

    def _convert_to_gateway_create(self, gateway_data: Dict[str, Any]) -> GatewayCreate:
        """Convert import data to GatewayCreate schema.

        Args:
            gateway_data: Gateway data dictionary from import

        Returns:
            GatewayCreate schema object
        """
        return GatewayCreate(
            name=gateway_data["name"],
            url=gateway_data["url"],
            description=gateway_data.get("description"),
            transport=gateway_data.get("transport", "SSE"),
            passthrough_headers=gateway_data.get("passthrough_headers"),
            tool_validation_policy=gateway_data.get("tool_validation_policy"),
            tags=gateway_data.get("tags", []),
            gateway_mode=gateway_data.get("gateway_mode") or "cache",
        )

    def _convert_to_gateway_update(self, gateway_data: Dict[str, Any]) -> GatewayUpdate:
        """Convert import data to GatewayUpdate schema.

        Args:
            gateway_data: Gateway data dictionary from import

        Returns:
            GatewayUpdate schema object
        """
        return GatewayUpdate(
            name=gateway_data.get("name"),
            url=gateway_data.get("url"),
            description=gateway_data.get("description"),
            transport=gateway_data.get("transport"),
            passthrough_headers=gateway_data.get("passthrough_headers"),
            tags=gateway_data.get("tags"),
            gateway_mode=gateway_data.get("gateway_mode"),
            **({"tool_validation_policy": gateway_data["tool_validation_policy"]} if "tool_validation_policy" in gateway_data else {}),
        )

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
        # Naming provenance is export metadata; name remains the literal import value.
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
        # As with creation, do not restore the exported upstream/base provenance.
        return ResourceUpdate(
            name=resource_data.get("name"), description=resource_data.get("description"), mime_type=resource_data.get("mime_type"), content=resource_data.get("content"), tags=resource_data.get("tags")
        )

    @staticmethod
    def _can_access_status(status: ImportStatus, imported_by: str | None, token_teams: list[str] | None, unrestricted_admin: bool) -> bool:
        """Check whether the caller may access the import status."""
        if not imported_by:
            return False
        if unrestricted_admin:
            return True
        return not status.platform_scope and status.imported_by == imported_by and (token_teams is None or status.request_team_ids is not None and status.request_team_ids.issubset(token_teams))

    def get_import_status(self, import_id: str, *, imported_by: str | None, token_teams: list[str] | None, unrestricted_admin: bool = False) -> Optional[ImportStatus]:
        """Get one import status within the verified request scope.

        Args:
            import_id: Import identifier.
            imported_by: Verified actor identity.
            token_teams: Verified request team scope.
            unrestricted_admin: Verified unrestricted platform administrator.

        Returns:
            Authorized import status, if present.
        """
        status = self.active_imports.get(import_id)
        if status and self._can_access_status(status, imported_by, token_teams, unrestricted_admin):
            return status
        return None

    def list_import_statuses(self, *, imported_by: str | None, token_teams: list[str] | None, unrestricted_admin: bool = False) -> List[ImportStatus]:
        """List import statuses within the verified request scope.

        Args:
            imported_by: Verified actor identity.
            token_teams: Verified request team scope.
            unrestricted_admin: Verified unrestricted platform administrator.

        Returns:
            Authorized import statuses.
        """
        return [status for status in self.active_imports.values() if self._can_access_status(status, imported_by, token_teams, unrestricted_admin)]

    def cleanup_completed_imports(self, max_age_hours: int = 24, *, imported_by: str | None, token_teams: list[str] | None, unrestricted_admin: bool = False) -> int:
        """Remove terminal statuses within the verified request scope.

        Args:
            max_age_hours: Age threshold.
            imported_by: Verified actor identity.
            token_teams: Verified request team scope.
            unrestricted_admin: Verified unrestricted platform administrator.

        Returns:
            Number of removed statuses.
        """
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        expired = [
            status.import_id
            for status in self.list_import_statuses(imported_by=imported_by, token_teams=token_teams, unrestricted_admin=unrestricted_admin)
            if status.status in {"completed", "failed"} and status.completed_at and status.completed_at < cutoff_time
        ]
        for import_id in expired:
            del self.active_imports[import_id]
        return len(expired)

    async def preview_import(
        self,
        db: Session,
        import_data: Dict[str, Any],
        *,
        conflict_strategy: ConflictStrategy = ConflictStrategy.UPDATE,
        imported_by: str = "system",
        selected_entities: Optional[Dict[str, List[str]]] = None,
        team_name: Optional[str] = None,
        token_teams: Optional[List[str]] = None,
        unrestricted_admin: bool = False,
    ) -> Dict[str, Any]:
        """Calculate local import outcomes for selective import.

        Args:
            db: Request database session.
            import_data: Configuration file envelope.
            conflict_strategy: Action for matched entities.
            imported_by: Verified actor identity.
            selected_entities: File entity identifiers grouped by type.
            team_name: Optional destination team name.
            token_teams: Verified request team scope.
            unrestricted_admin: Verified unrestricted platform administrator.

        Returns:
            Preview items, dependencies, conflicts, and estimated outcomes.
        """
        status = ImportStatus(str(uuid.uuid4()))
        await self._run_import(db, import_data, conflict_strategy, True, imported_by, selected_entities, team_name, token_teams, unrestricted_admin, status)
        entities = {kind: self._select_entity_list(kind, rows, selected_entities) for kind, rows in import_data["entities"].items()}
        return {
            "summary": {"total_items": status.total_entities, "by_type": {kind: len(rows) for kind, rows in entities.items()}},
            "items": dict(status.items),
            "bundles": self._find_gateway_bundles(entities),
            "conflicts": {kind: [item for item in items if item["conflicts_with"]] for kind, items in status.items.items()},
            "dependencies": self._find_server_dependencies(entities),
            "outcomes": status.to_dict(),
        }

    def _find_gateway_bundles(self, entities: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        """Find gateway bundles (gateway + associated tools/resources/prompts).

        Args:
            entities: All entities from import data

        Returns:
            Gateway bundle information for UI
        """
        bundles: dict[str, Any] = {}

        if "gateways" not in entities:
            return bundles

        for gateway in entities["gateways"]:
            gateway_name = gateway["name"]
            gateway_id = str(gateway.get("id") or gateway_name)
            bundle_items: dict[str, list[EntityData]] = {"tools": [], "resources": [], "prompts": []}
            for entity_type, items in bundle_items.items():
                for item in entities.get(entity_type, []):
                    item_gateway = str(item.get("gateway_id") or item.get("gateway_name") or "")
                    if item_gateway not in {gateway_id, gateway_name}:
                        continue
                    item_name = self._get_entity_identifier(entity_type, item)
                    items.append({"id": str(item.get("id") or item_name), "name": item.get("name", item_name), "description": item.get("description", "")})
            if any(bundle_items.values()):
                bundles[gateway_id] = {
                    "gateway": {"name": gateway_name, "description": gateway.get("description", "")},
                    "items": bundle_items,
                    "total_items": sum(len(items) for items in bundle_items.values()),
                }

        return bundles

    @staticmethod
    def _preview_server_dependencies(server: Dict[str, Any]) -> Dict[str, list[Any]]:
        """Collate the file's visible server dependencies for preview."""
        refs: Any = next((server[key] for key in ("tool_refs", "tool_ids", "associated_tools") if key in server), [])
        tool_ids = [ref.get("id") if isinstance(ref, dict) else ref for ref in refs] if isinstance(refs, list) else []
        resources = server.get("associated_resources")
        prompts = server.get("associated_prompts")
        return {
            "tools": [tool_id for tool_id in tool_ids if isinstance(tool_id, str)],
            "resources": resources if isinstance(resources, list) else [],
            "prompts": prompts if isinstance(prompts, list) else [],
        }

    def _find_server_dependencies(self, entities: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        """Find server dependencies for smart selection.

        Args:
            entities: All entities from import data

        Returns:
            Server dependency information for UI
        """
        dependencies: dict[str, Any] = {}

        if "servers" not in entities:
            return dependencies

        for server in entities["servers"]:
            server_name = server.get("name", "")
            deps = self._preview_server_dependencies(server)

            if any(deps.values()):  # Only add if server has dependencies
                dependencies[server_name] = {
                    "server": {"name": server_name, "description": server.get("description", "")},
                    "requires": deps,
                    "total_dependencies": sum(len(items) for items in deps.values()),
                }

        return dependencies


import_service = ImportService()
