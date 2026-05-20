"""Location: ./plugins/apiconnect_fam/activity_orchestrator.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Shankar N

Activity Orchestrator for Server Monitor Plugin.

Coordinates activity execution, statistics tracking, and health monitoring.
"""

# Standard
import asyncio
import logging
from typing import Any, Dict, List, Optional

# Local
from .activities.base import AbstractScheduledActivity
from .activities.register_runtime import RegisterRuntimeActivity
from .activities.send_heartbeat import SendHeartbeatActivity
from .activities.send_metrics import SendMetricsActivity
from .activities.sync_servers import SyncServersActivity
from .activities.sync_tools import SyncToolsActivity
from .fam import FAMAssetCatalogClient
from .models import ActivityContext

logger = logging.getLogger(__name__)


class ActivityOrchestrator:
    """Orchestrates all activities for the Server Monitor Plugin.

    Manages activity lifecycle, execution scheduling, statistics tracking,
    and health monitoring.

    Attributes:
        context: Shared context for all activities
        fam_client: IBM API Connect Federated API Management API client
        activities: List of all managed activities
        _running: Whether orchestrator is running
        _task: Background task for activity execution
    """

    def __init__(
        self,
        fam_client: FAMAssetCatalogClient,
        runtime_id: str,
        fam_base_url: str,
        config: Dict[str, Any],
        heartbeat_interval: int = 60,
        metrics_interval: int = 300,
        server_sync_interval: int = 60,
        tool_sync_interval: int = 60,
    ):
        """Initialize the activity orchestrator.

        Args:
            fam_client: FAM API client
            runtime_id: Runtime ID for this agent
            fam_base_url: Base URL for FAM API
            config: Plugin configuration dictionary
            heartbeat_interval: Heartbeat interval in seconds (default: 60, mandatory)
            metrics_interval: Metrics sync interval in seconds (default: 300, 0 to disable)
            server_sync_interval: Server sync interval in seconds (default: 60, 0 to disable)
            tool_sync_interval: Tool sync interval in seconds (default: 60, 0 to disable)
        """
        # Create shared context
        self.context = ActivityContext(runtime_id=runtime_id, fam_base_url=fam_base_url, config=config)

        self.fam_client = fam_client
        self.runtime_id = runtime_id

        # Extract runtime configuration from plugin config
        runtime_config = {
            "name": config.get("fam_runtime_name", "ContextForge Gateway"),
            "description": config.get("fam_runtime_description", "ContextForge MCP Gateway Runtime"),
            "type": config.get("fam_runtime_type", "MCP_CONTEXT_FORGE"),
            "deployment_type": config.get("fam_runtime_deployment_type", "ON_PREMISE"),
            "region": config.get("fam_runtime_region"),
            "location": config.get("fam_runtime_location"),
            "host": config.get("fam_runtime_host"),
            "tags": config.get("fam_runtime_tags", []),
            "capacity_value": config.get("fam_runtime_capacity_value", "100"),
            "capacity_unit": config.get("fam_runtime_capacity_unit", "per minute"),
            "heartbeat_interval": heartbeat_interval,
        }

        # Create registration activity (executed once during start)
        self.register_activity = RegisterRuntimeActivity(context=self.context, fam_client=fam_client, runtime_config=runtime_config)

        # Initialize scheduled activities
        # Note: Order matters! Servers must sync before tools
        self.activities: List[AbstractScheduledActivity] = []

        # Create heartbeat activity (mandatory)
        self.heartbeat_activity = SendHeartbeatActivity(context=self.context, fam_client=fam_client, heartbeat_interval=heartbeat_interval)
        self.activities.append(self.heartbeat_activity)

        # Create metrics activity (optional, only if interval > 0)
        self.metrics_activity: Optional[SendMetricsActivity] = None
        if metrics_interval > 0:
            self.metrics_activity = SendMetricsActivity(context=self.context, fam_client=fam_client, metrics_interval=metrics_interval)
            self.activities.append(self.metrics_activity)
            logger.info(f"Metrics sync enabled with interval={metrics_interval}s")
        else:
            logger.info("Metrics sync disabled")

        # Create server sync activity (optional, only if interval > 0, must run before tools)
        self.server_sync_activity: Optional[SyncServersActivity] = None
        if server_sync_interval > 0:
            self.server_sync_activity = SyncServersActivity(context=self.context, fam_client=fam_client, sync_interval=server_sync_interval, orchestrator=self)
            self.activities.append(self.server_sync_activity)
            logger.info(f"Server asset sync enabled with interval={server_sync_interval}s")
        else:
            logger.info("Server asset sync disabled")

        # Create tool sync activity (optional, only if interval > 0, depends on servers)
        self.tool_sync_activity: Optional[SyncToolsActivity] = None
        if tool_sync_interval > 0:
            self.tool_sync_activity = SyncToolsActivity(context=self.context, fam_client=fam_client, sync_interval=tool_sync_interval, orchestrator=self)
            self.activities.append(self.tool_sync_activity)
            logger.info(f"Tool asset sync enabled with interval={tool_sync_interval}s")
        else:
            logger.info("Tool asset sync disabled")

        # Track if servers have been synced (for tool sync dependency)
        self._servers_synced_this_cycle = False

        # Track if runtime has been registered to FAM
        # Server and tool sync should only happen AFTER runtime registration
        self._runtime_registered = False

        # Orchestrator state
        self._running = False
        self._task: Optional[asyncio.Task] = None

        # Shared state for activity coordination
        # Track which servers have been registered to FAM
        # Set of server IDs that have been successfully synced to FAM
        self._registered_servers: set[str] = set()

        logger.info(
            f"ActivityOrchestrator initialized with {len(self.activities)} activities: "
            f"heartbeat={heartbeat_interval}s, metrics={metrics_interval if metrics_interval > 0 else 'disabled'}s, "
            f"servers={server_sync_interval if server_sync_interval > 0 else 'disabled'}s, "
            f"tools={tool_sync_interval if tool_sync_interval > 0 else 'disabled'}s"
        )

    def mark_server_synced(self, server_id: str) -> None:
        """Mark a server as synced to FAM.

        Called by server sync activity when a server is successfully synced to FAM.

        Args:
            server_id: ContextForge server ID
        """
        self._registered_servers.add(server_id)
        logger.debug(f"Server {server_id} marked as synced to FAM")

    def is_server_registered(self, server_id: str) -> bool:
        """Check if a server has been registered to FAM.

        Args:
            server_id: ContextForge server ID

        Returns:
            True if server has been synced to FAM
        """
        return server_id in self._registered_servers

    def get_registered_servers(self) -> set[str]:
        """Get set of all registered server IDs.

        Returns:
            Set of ContextForge server IDs that have been registered to FAM
        """
        return self._registered_servers.copy()

    def mark_runtime_registered(self) -> None:
        """Mark runtime as registered to FAM.

        Called after successful runtime registration.
        Enables server and tool sync activities.
        """
        self._runtime_registered = True
        logger.info("Runtime marked as registered - server and tool sync now enabled")

    async def start(self) -> None:
        """Start the orchestrator and begin activity execution.

        Performs runtime registration first, then starts the activity loop.
        """
        if self._running:
            logger.warning("ActivityOrchestrator already running")
            return

        # Execute runtime registration before starting activities
        logger.info("Executing runtime registration activity")

        try:
            await self.register_activity.perform()

            # Mark runtime as registered (enables server and tool sync)
            self._runtime_registered = True
            logger.info("Runtime registration complete - all activities enabled")

        except Exception as e:
            error_msg = f"Runtime registration failed: {e}"
            logger.error(error_msg, exc_info=True)
            raise

        # Start activity execution loop
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("ActivityOrchestrator started")

    async def stop(self) -> None:
        """Stop the orchestrator and cancel all activities."""
        if not self._running:
            logger.warning("ActivityOrchestrator not running")
            return

        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        logger.info("ActivityOrchestrator stopped")

    async def _run_loop(self) -> None:
        """Main execution loop for activities.

        Continuously checks and executes activities that are due.
        Runs every second to check activity schedules.

        IMPORTANT: Enforces dependency that servers must sync before tools,
        because tools need the FAM server ID as mcpServerId.
        """
        logger.info("ActivityOrchestrator execution loop started")

        while self._running:
            try:
                # Reset server sync flag at start of each cycle
                self._servers_synced_this_cycle = False

                # Execute activities in dependency order
                for activity in self.activities:
                    if activity.should_execute():
                        # Special handling for server sync - must wait for runtime registration
                        if activity == self.server_sync_activity:
                            if not self._runtime_registered:
                                logger.debug("Skipping server sync - waiting for runtime registration to complete first")
                                continue

                        # Special handling for tool sync - must wait for runtime registration AND server sync
                        if activity == self.tool_sync_activity:
                            if not self._runtime_registered:
                                logger.debug("Skipping tool sync - waiting for runtime registration to complete first")
                                continue
                            if not self._servers_synced_this_cycle:
                                logger.debug("Skipping tool sync - waiting for server sync to complete first")
                                continue

                        try:
                            await activity.execute()

                            # Track if servers were synced
                            if activity == self.server_sync_activity:
                                self._servers_synced_this_cycle = True
                                logger.debug("Server sync completed - tools can now sync")

                        except Exception as e:
                            logger.error(f"Error executing activity {activity.__class__.__name__}: {e}", exc_info=True)

                # Sleep for 1 second before next check
                await asyncio.sleep(1)

            except asyncio.CancelledError:
                logger.info("ActivityOrchestrator execution loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in orchestrator execution loop: {e}", exc_info=True)
                await asyncio.sleep(5)  # Back off on error

    async def trigger_recovery(self) -> None:
        """Trigger recovery of missed operations.

        Called after runtime registration to recover any missed
        heartbeats, metrics, or asset syncs.

        TODO: Implement recovery handler
        - Recover missed heartbeats (send INACTIVE heartbeats for missed intervals)
        - Recover missed metrics (send historical metrics data)
        - Recover missed asset syncs (perform full server/tool sync)
        See: handlers/recovery_handler.py for implementation reference
        """
        logger.warning("Recovery handler not implemented - skipping recovery")
