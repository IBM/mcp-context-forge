"""Location: ./plugins/apiconnect_fam/activities/sync_tools.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Shankar N

Sync Tools Activity.

Syncs MCP tools to FAM Asset Catalog using bulk operations.
"""

# Standard
from collections import defaultdict
import json
from typing import Any, Dict, List, Optional, Set, TYPE_CHECKING

# Third-Party
from sqlalchemy.orm import joinedload

# First-Party
from mcpgateway.db import Server, SessionLocal, Tool

# Local
from ..fam import FAMAssetCatalogClient
from ..models import ActivityContext
from ..utils import RetryConfig, SyncError, with_retry
from .base import AbstractScheduledActivity
from .state_tracker import AbstractStateTracker

if TYPE_CHECKING:
    # Local
    from ..activity_orchestrator import ActivityOrchestrator


class ToolStateTracker(AbstractStateTracker):
    """Tracks tool state for change detection using content hashing.

    Since we use bulk operations that return job IDs, we only need to track
    content hashes. Once a bulk job is submitted successfully, all tools in
    that batch are considered synced.

    Extends AbstractStateTracker with tool-specific hash computation.
    """

    @staticmethod
    def compute_hash(entity: Any) -> str:
        """Compute SHA-256 hash of tool content.

        Includes: name, description, enabled, tags, request_type, input_schema, output_schema

        Args:
            entity: ContextForge Tool ORM object

        Returns:
            SHA-256 hash string
        """
        tool_data = {
            "name": entity.original_name or entity.custom_name,
            "description": entity.description or entity.original_description,
            "enabled": entity.enabled,
            "tags": sorted(entity.tags) if entity.tags else [],
            "request_type": entity.request_type,
            "input_schema": json.dumps(entity.input_schema, sort_keys=True) if entity.input_schema else "",
            "output_schema": json.dumps(entity.output_schema, sort_keys=True) if entity.output_schema else "",
        }
        return AbstractStateTracker._compute_hash_from_dict(tool_data)

    def is_new_tool(self, tool_id: str) -> bool:
        """Check if tool is new (not yet synced to FAM).

        Convenience method that delegates to base class is_new().

        Args:
            tool_id: Tool identifier

        Returns:
            True if tool is new (no hash in cache)
        """
        return self.is_new(tool_id)

    def get_deleted_tools(self, current_tool_ids: Set[str]) -> Set[str]:
        """Get tools that were synced to FAM but no longer exist in DB.

        Convenience method that delegates to base class get_deleted_entities().

        Args:
            current_tool_ids: Set of current tool IDs from database

        Returns:
            Set of tool IDs that were deleted
        """
        return self.get_deleted_entities(current_tool_ids)


class SyncToolsActivity(AbstractScheduledActivity):
    """Activity for syncing MCP tools to FAM.


    IMPORTANT: This activity depends on SyncServersActivity completing first,
    because tools need the FAM server ID as mcpServerId.

    Attributes:
        context: Shared activity context
        fam_client: FAM API client
        sync_interval: Interval in seconds
        orchestrator: Reference to orchestrator for getting server ID mapping
    """

    def __init__(self, context: ActivityContext, fam_client: FAMAssetCatalogClient, sync_interval: int = 60, orchestrator: Optional["ActivityOrchestrator"] = None):
        """Initialize sync tools activity.

        Args:
            context: Shared activity context
            fam_client: FAM API client
            sync_interval: Sync interval in seconds
            orchestrator: Reference to orchestrator (for getting server ID mapping)
        """
        super().__init__(context)
        self._fam_client = fam_client
        self._sync_interval = sync_interval
        self._orchestrator = orchestrator
        self._state_tracker = ToolStateTracker()
        self._total_tools_synced = 0

    def get_interval_seconds(self) -> int:
        """Get the sync interval.

        Returns:
            Interval in seconds
        """
        return self._sync_interval

    async def perform(self) -> None:
        """Sync tools to FAM.

        Raises:
            SyncError: If sync fails
        """

        try:
            # Query and sync tools
            tools_synced = await with_retry(self._query_and_sync_tools, retry_config=RetryConfig(max_attempts=2, initial_delay=1.0), operation_name="Sync Tools")

            # Track success
            self._total_tools_synced += tools_synced

            self.logger.info(f"Synced {tools_synced} tools to FAM (total: {self._total_tools_synced})")

        except Exception as e:
            error_msg = f"Failed to sync tools: {e}"
            self.logger.error(error_msg, exc_info=True)
            raise SyncError(error_msg, e)

    async def _query_and_sync_tools(self) -> int:
        """Query tools from database and sync to FAM using bulk operations.

        Returns:
            Number of tools synced

        Raises:
            Exception: If query or sync fails
        """
        with SessionLocal() as db:
            # Eager load the servers relationship to avoid N+1 queries
            tools = db.query(Tool).options(joinedload(Tool.servers)).all()
            servers = db.query(Server).all()

            if not tools:
                self.logger.debug("No tools to sync")
                return 0

            # Get set of registered servers from orchestrator
            registered_servers = set()
            if self._orchestrator:
                registered_servers = self._orchestrator.get_registered_servers()

            # Build tool-to-server mapping (only for registered servers)
            tool_to_server = self._build_tool_server_mapping(servers, registered_servers)

            # Detect changes and group by server and operation
            tools_by_server = self._group_tools_by_server_and_operation(tools, tool_to_server)

            # Process bulk operations per server
            total_synced = 0
            for server_id, operations in tools_by_server.items():
                # Check if server is registered to FAM
                if server_id not in registered_servers:
                    self.logger.debug(f"Skipping tools for server {server_id} - server not yet registered to FAM")
                    continue

                self.logger.debug(f"Processing tools for server {server_id}...")

                # Bulk create new tools
                if operations["create"]:
                    self.logger.debug(f"{len(operations['create'])} NEW tools to create")
                    self.logger.debug(f"Calling FAM API: POST /api/assetcatalog/v1/runtimes/.../mcp-servers/{server_id}/mcp-tools/bulk/create")
                    job_id = await self._fam_client.bulk_create_tools(operations["create"], server_id)
                    if job_id:
                        self.logger.debug(f"Bulk create job submitted: {job_id}")
                        # Mark all as synced
                        for tool in operations["create"]:
                            tool_id = str(tool.id)
                            current_hash = self._state_tracker.compute_hash(tool)
                            self._state_tracker.mark_synced(tool_id, current_hash)
                        total_synced += len(operations["create"])
                    else:
                        self.logger.warning("Bulk create failed")

                # Bulk update changed tools
                if operations["update"]:
                    self.logger.debug(f"{len(operations['update'])} CHANGED tools to update")
                    self.logger.debug(f"Calling FAM API: POST /api/assetcatalog/v1/runtimes/.../mcp-servers/{server_id}/mcp-tools/bulk/update")
                    job_id = await self._fam_client.bulk_update_tools(operations["update"], server_id)
                    if job_id:
                        self.logger.debug(f"Bulk update job submitted: {job_id}")
                        # Mark all as synced
                        for tool in operations["update"]:
                            tool_id = str(tool.id)
                            current_hash = self._state_tracker.compute_hash(tool)
                            self._state_tracker.mark_synced(tool_id, current_hash)
                        total_synced += len(operations["update"])
                    else:
                        self.logger.warning("Bulk update failed")

                # Bulk delete removed tools
                if operations["delete"]:
                    self.logger.debug(f"{len(operations['delete'])} tools to delete")
                    self.logger.debug(f"Calling FAM API: POST /api/assetcatalog/v1/runtimes/.../mcp-servers/{server_id}/mcp-tools/bulk/delete")
                    job_id = await self._fam_client.bulk_delete_tools(operations["delete"], server_id)
                    if job_id:
                        self.logger.debug(f"Bulk delete job submitted: {job_id}")
                        # Mark all as deleted
                        for tool_id in operations["delete"]:
                            self._state_tracker.mark_deleted(tool_id)
                        total_synced += len(operations["delete"])
                    else:
                        self.logger.warning("Bulk delete failed")

            self.logger.info(f"Synced {total_synced} tools to FAM using bulk operations")
            return total_synced

    def _build_tool_server_mapping(self, servers: List[Any], registered_servers: Set[str]) -> Dict[str, str]:
        """Build mapping from tool ID to server ID.

        Args:
            servers: List of Server ORM objects
            registered_servers: Set of server IDs that have been synced to FAM

        Returns:
            Dict mapping tool_id to server_id (only for registered servers)
        """
        tool_to_server = {}
        for server in servers:
            server_id = str(server.id)

            # Skip servers that haven't been synced to FAM yet
            if server_id not in registered_servers:
                continue

            if hasattr(server, "tools") and server.tools:
                for tool in server.tools:
                    tool_to_server[str(tool.id)] = server_id

        return tool_to_server

    def _group_tools_by_server_and_operation(self, tools: List[Any], tool_to_server: Dict[str, str]) -> Dict[str, Dict[str, List]]:
        """Group tools by server and operation type (create/update/delete).

        Args:
            tools: List of Tool ORM objects
            tool_to_server: Mapping from tool ID to FAM server ID

        Returns:
            Dict mapping server_id to operations dict with create/update/delete lists
        """
        # Initialize structure: {server_id: {create: [], update: [], delete: []}}
        tools_by_server: Dict[str, Dict[str, List]] = defaultdict(lambda: {"create": [], "update": [], "delete": []})

        current_tool_ids = {str(tool.id) for tool in tools}

        # Detect deleted tools
        deleted_ids = self._state_tracker.get_deleted_tools(current_tool_ids)
        for tool_id in deleted_ids:
            server_id = tool_to_server.get(tool_id)
            if server_id:
                tools_by_server[server_id]["delete"].append(tool_id)

        # Classify current tools
        for tool in tools:
            tool_id = str(tool.id)
            server_id = tool_to_server.get(tool_id)

            if not server_id:
                # Tool not associated with any synced server, skip
                continue

            current_hash = self._state_tracker.compute_hash(tool)

            if self._state_tracker.is_new_tool(tool_id):
                tools_by_server[server_id]["create"].append(tool)
            elif self._state_tracker.has_changed(tool_id, current_hash):
                tools_by_server[server_id]["update"].append(tool)

        return dict(tools_by_server)
