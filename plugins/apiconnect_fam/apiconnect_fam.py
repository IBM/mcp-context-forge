"""Location: ./plugins/apiconnect_fam/apiconnect_fam.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Shankar N

IBM API Connect Federated API Management Plugin for ContextForge.

Integrates ContextForge with IBM API Connect Federated API Management.
Syncs servers, tools, and metrics to IBM API Connect Federated API Management Asset Catalog API.

Features:
- Runtime registration with IBM API Connect Federated API Management
- Periodic heartbeat to maintain connection
- Server and tool synchronization with change detection
- Metrics synchronization
"""

# Standard
import logging
from typing import List, Optional

# Third-Party
from cpex.framework import Plugin, PluginConfig
from pydantic import BaseModel, Field

# Local
from .activity_orchestrator import ActivityOrchestrator
from .fam import FAMAssetCatalogClient

logger = logging.getLogger(__name__)


class APIConnectFAMConfig(BaseModel):
    """Configuration for IBM API Connect Federated API Management plugin.

    Attributes:
        interval_seconds: How often to sync servers (in seconds).
        log_details: Whether to log detailed server information.
        fam_enabled: Whether to sync servers to IBM API Connect Federated API Management.
        fam_base_url: Base URL for IBM API Connect Federated API Management API (e.g., https://fam.example.com).
        fam_runtime_id: Runtime ID to use when syncing to IBM API Connect Federated API Management (REQUIRED when fam_enabled is true).
        fam_auth_type: Authentication type - 'basic' or 'apikey' (default: 'basic').
        fam_username: IBM API Connect Federated API Management username for Basic Authentication.
        fam_password: IBM API Connect Federated API Management password for Basic Authentication.
        fam_api_key: IBM API Connect Federated API Management API key for API Key Authentication.
        fam_client_id: IBM API Connect Federated API Management client ID for API Key Authentication.
        fam_timeout: HTTP request timeout in seconds.
        fam_verify_ssl: Whether to verify SSL certificates (set False for self-signed certs).
        fam_asset_sync_enabled: Whether to sync assets (servers/tools) to IBM API Connect Federated API Management.
        fam_asset_sync_interval: How often to sync assets (in seconds).
        metrics_sync_enabled: Whether to sync metrics to IBM API Connect Federated API Management.
        metrics_sync_interval: How often to sync metrics (in seconds). Also used as time window for metrics collection.
        fam_runtime_name: Runtime display name (for reference only).
        fam_runtime_description: Runtime description (for reference only).
        fam_runtime_deployment_type: Deployment type (for reference only).
        fam_runtime_region: Region identifier (for reference only).
        fam_runtime_location: Location description (for reference only).
        fam_runtime_host: Host identifier (for reference only).
        fam_runtime_tags: List of tags for the runtime (for reference only).
        fam_runtime_capacity_value: Capacity value (for reference only).
        fam_runtime_capacity_unit: Capacity unit (for reference only).
        fam_runtime_heartbeat_interval: Heartbeat sync interval in milliseconds (for reference only).
        fam_heartbeat_interval_seconds: How often to send heartbeats (in seconds, mandatory when IBM API Connect Federated API Management enabled).

    Note:
        Runtime type is hardcoded to 'MCP_CONTEXT_FORGE' and will be auto-created if it doesn't exist in FAM.
        Authentication: Either use Basic Auth (username/password) or API Key (api_key/client_id).
    """

    interval_seconds: int = 60
    log_details: bool = True
    fam_enabled: bool = False
    fam_base_url: Optional[str] = Field(default=None, description="IBM API Connect Federated API Management API base URL")
    fam_runtime_id: Optional[str] = Field(default=None, description="IBM API Connect Federated API Management runtime ID (REQUIRED when fam_enabled is true)")
    fam_auth_type: str = Field(default="basic", description="Authentication type: 'basic' or 'apikey'")
    fam_username: Optional[str] = Field(default=None, description="IBM API Connect Federated API Management username for Basic Authentication")
    fam_password: Optional[str] = Field(default=None, description="IBM API Connect Federated API Management password for Basic Authentication")
    fam_api_key: Optional[str] = Field(default=None, description="IBM API Connect Federated API Management API key for API Key Authentication")
    fam_client_id: Optional[str] = Field(default=None, description="IBM API Connect Federated API Management client ID for API Key Authentication")
    fam_timeout: int = 30
    fam_verify_ssl: bool = True  # Verify SSL certificates by default
    fam_asset_sync_enabled: bool = True
    fam_asset_sync_interval: int = 60  # Sync assets every 60 seconds
    metrics_sync_enabled: bool = False
    metrics_sync_interval: int = 300  # 5 minutes default

    # Runtime metadata (for reference only, not used after initial registration)
    fam_runtime_name: str = "ContextForge Gateway"
    fam_runtime_description: str = "ContextForge MCP Gateway Runtime"
    # Note: fam_runtime_type removed - hardcoded to MCP_CONTEXT_FORGE in models.py
    fam_runtime_deployment_type: str = "ON_PREMISE"
    fam_runtime_region: Optional[str] = Field(default=None, description="Runtime region")
    fam_runtime_location: Optional[str] = Field(default=None, description="Runtime location")
    fam_runtime_host: Optional[str] = Field(default=None, description="Runtime host identifier")
    fam_runtime_tags: List[str] = Field(default_factory=lambda: ["contextforge", "mcp"])
    fam_runtime_capacity_value: str = "100"
    fam_runtime_capacity_unit: str = "per minute"
    fam_runtime_heartbeat_interval_seconds: int = 60  # Heartbeat interval in seconds (converted to ms for FAM, also used for activity interval)


class APIConnectFAMPlugin(Plugin):
    """IBM API Connect Federated API Management integration plugin - syncs servers, tools, and metrics to IBM API Connect Federated API Management.

    The plugin delegates all sync operations to the orchestrator, which
    manages activity execution, scheduling, statistics, and recovery.
    """

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the server monitor plugin.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        self._cfg = APIConnectFAMConfig(**(config.config or {}))

        # FAM client and orchestrator
        self._fam_client: Optional[FAMAssetCatalogClient] = None
        self._orchestrator: Optional[ActivityOrchestrator] = None
        self._runtime_id: Optional[str] = None

    async def initialize(self) -> None:
        """Start the activity orchestrator and HTTP client."""
        logger.info(f"Initializing APIConnectFAMPlugin with interval={self._cfg.interval_seconds}s")

        # Initialize IBM API Connect Federated API Management client if sync is enabled
        if self._cfg.fam_enabled:
            # Validate required base fields
            if not self._cfg.fam_base_url or not self._cfg.fam_runtime_id:
                error_msg = "IBM API Connect Federated API Management sync enabled but required fields missing (base_url or runtime_id). Plugin initialization failed."
                logger.error(error_msg)
                raise ValueError(error_msg)

            # Validate authentication configuration based on auth_type
            auth_type = self._cfg.fam_auth_type.lower()
            if auth_type == "basic":
                if not self._cfg.fam_username or not self._cfg.fam_password:
                    error_msg = "Basic authentication selected but username or password is missing. Plugin initialization failed."
                    logger.error(error_msg)
                    raise ValueError(error_msg)
            elif auth_type == "apikey":
                if not self._cfg.fam_api_key or not self._cfg.fam_client_id:
                    error_msg = "API Key authentication selected but api_key or client_id is missing. Plugin initialization failed."
                    logger.error(error_msg)
                    raise ValueError(error_msg)
            else:
                error_msg = f"Invalid authentication type '{auth_type}'. Must be 'basic' or 'apikey'. Plugin initialization failed."
                logger.error(error_msg)
                raise ValueError(error_msg)

            # Store runtime ID
            self._runtime_id = self._cfg.fam_runtime_id

            # Create FAM client with runtime ID (type assertions safe due to validation above)
            assert self._cfg.fam_base_url is not None
            assert self._runtime_id is not None

            self._fam_client = FAMAssetCatalogClient(
                base_url=self._cfg.fam_base_url,
                runtime_id=self._runtime_id,
                auth_type=auth_type,
                username=self._cfg.fam_username,
                password=self._cfg.fam_password,
                api_key=self._cfg.fam_api_key,
                client_id=self._cfg.fam_client_id,
                timeout=self._cfg.fam_timeout,
                verify_ssl=self._cfg.fam_verify_ssl,
            )

            logger.info(f"IBM API Connect Federated API Management sync enabled - HTTP client initialized with runtime_id={self._runtime_id}")
            logger.info(f"IBM API Connect Federated API Management Base URL: {self._cfg.fam_base_url}")
            logger.info(f"Runtime ID: {self._runtime_id}")
            logger.info(f"Asset Sync: {'Enabled' if self._cfg.fam_asset_sync_enabled else 'Disabled'}")
            logger.info(f"Metrics Sync: {'Enabled' if self._cfg.metrics_sync_enabled else 'Disabled'}")
            logger.info("Circuit Breaker: Enabled (default)")

            # Initialize activity orchestrator
            self._orchestrator = ActivityOrchestrator(
                fam_client=self._fam_client,
                runtime_id=self._runtime_id,
                fam_base_url=self._cfg.fam_base_url,
                config=self._cfg.model_dump(),
                heartbeat_interval=self._cfg.fam_runtime_heartbeat_interval_seconds,
                metrics_interval=self._cfg.metrics_sync_interval if self._cfg.metrics_sync_enabled else 0,
                server_sync_interval=self._cfg.fam_asset_sync_interval if self._cfg.fam_asset_sync_enabled else 0,
                tool_sync_interval=self._cfg.fam_asset_sync_interval if self._cfg.fam_asset_sync_enabled else 0,
            )

            # Start orchestrator (will perform registration first, then start activities)
            logger.info("Starting activity orchestrator...")
            await self._orchestrator.start()
            logger.info("Activity orchestrator started - plugin ready")

    async def shutdown(self) -> None:
        """Stop the activity orchestrator and close HTTP client."""
        logger.info("Shutting down APIConnectFAMPlugin")

        # Stop orchestrator
        if self._orchestrator:
            await self._orchestrator.stop()
            logger.info("Activity orchestrator stopped")

        # Close IBM API Connect Federated API Management client
        if self._fam_client:
            await self._fam_client.close()
            self._fam_client = None
            logger.info("IBM API Connect Federated API Management client closed")
