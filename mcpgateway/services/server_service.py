# -*- coding: utf-8 -*-
"""

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

MCP Gateway Server Service

This module implements server management for the MCP Servers Catalog.
It handles server registration, listing, retrieval, updates, activation toggling, and deletion.
It also publishes event notifications for server changes.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx
from sqlalchemy import delete, func, not_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mcpgateway.config import settings
from mcpgateway.db import Prompt as DbPrompt
from mcpgateway.db import Resource as DbResource
from mcpgateway.db import Server as DbServer
from mcpgateway.db import ServerMetric
from mcpgateway.db import Tool as DbTool
from mcpgateway.schemas import ServerCreate, ServerMetrics, ServerRead, ServerUpdate

logger = logging.getLogger(__name__)


class ServerError(Exception):
    """Base class for server-related errors."""


class ServerNotFoundError(ServerError):
    """Raised when a requested server is not found."""


class ServerNameConflictError(ServerError):
    """Raised when a server name conflicts with an existing one."""

    def __init__(self, name: str, is_active: bool = True, server_id: Optional[int] = None):
        self.name = name
        self.is_active = is_active
        self.server_id = server_id
        message = f"Server already exists with name: {name}"
        if not is_active:
            message += f" (currently inactive, ID: {server_id})"
        super().__init__(message)


class ServerService:
    """Service for managing MCP Servers in the catalog.

    Provides methods to create, list, retrieve, update, toggle status, and delete server records.
    Also supports event notifications for changes in server data.
    """

    def __init__(self) -> None:
        self._event_subscribers: List[asyncio.Queue] = []
        self._http_client = httpx.AsyncClient(timeout=settings.federation_timeout, verify=not settings.skip_ssl_verify)

    async def initialize(self) -> None:
        """Initialize the server service."""
        logger.info("Initializing server service")

    async def shutdown(self) -> None:
        """Shutdown the server service."""
        await self._http_client.aclose()
        logger.info("Server service shutdown complete")

    def _convert_server_to_read(self, server: DbServer) -> ServerRead:
        """
        Converts a DbServer instance into a ServerRead model, including aggregated metrics.

        Args:
            server (DbServer): The ORM instance of the server.

        Returns:
            ServerRead: The Pydantic model representing the server, including aggregated metrics.
        """
        server_dict = server.__dict__.copy()
        server_dict.pop("_sa_instance_state", None)
        # Compute aggregated metrics from server.metrics; default to 0/None when no records exist.
        total = len(server.metrics) if hasattr(server, "metrics") else 0
        successful = sum(1 for m in server.metrics if m.is_success) if total > 0 else 0
        failed = sum(1 for m in server.metrics if not m.is_success) if total > 0 else 0
        failure_rate = (failed / total) if total > 0 else 0.0
        min_rt = min((m.response_time for m in server.metrics), default=None) if total > 0 else None
        max_rt = max((m.response_time for m in server.metrics), default=None) if total > 0 else None
        avg_rt = (sum(m.response_time for m in server.metrics) / total) if total > 0 else None
        last_time = max((m.timestamp for m in server.metrics), default=None) if total > 0 else None

        server_dict["metrics"] = {
            "total_executions": total,
            "successful_executions": successful,
            "failed_executions": failed,
            "failure_rate": failure_rate,
            "min_response_time": min_rt,
            "max_response_time": max_rt,
            "avg_response_time": avg_rt,
            "last_execution_time": last_time,
        }
        # Also update associated IDs (if not already done)
        server_dict["associated_tools"] = [tool.qualified_name for tool in server.tools] if server.tools else []
        server_dict["associated_resources"] = [res.id for res in server.resources] if server.resources else []
        server_dict["associated_prompts"] = [prompt.id for prompt in server.prompts] if server.prompts else []
        return ServerRead.model_validate(server_dict)

    def _assemble_associated_items(
        self,
        tools: Optional[List[str]],
        resources: Optional[List[str]],
        prompts: Optional[List[str]],
    ) -> Dict[str, Any]:
        """
        Assemble the associated items dictionary from the separate fields.

        Args:
            tools: List of tool IDs.
            resources: List of resource IDs.
            prompts: List of prompt IDs.

        Returns:
            A dictionary with keys "tools", "resources", and "prompts".
        """
        return {
            "tools": tools or [],
            "resources": resources or [],
            "prompts": prompts or [],
        }

    async def register_server(self, db: Session, server_in: ServerCreate) -> ServerRead:
        """
        Register a new server in the catalog and validate that all associated items exist.

        This function performs the following steps:
        1. Checks if a server with the same name already exists.
        2. Creates a new server record.
        3. For each ID provided in associated_tools, associated_resources, and associated_prompts,
            verifies that the corresponding item exists. If an item does not exist, an error is raised.
        4. Associates the verified items to the new server.
        5. Commits the transaction, refreshes the ORM instance, and forces the loading of relationship data.
        6. Constructs a response dictionary that includes lists of associated item IDs.
        7. Notifies subscribers of the addition and returns the validated response.

        Args:
            db (Session): The SQLAlchemy database session.
            server_in (ServerCreate): The server creation schema containing server details and lists of
                associated tool, resource, and prompt IDs (as strings).

        Returns:
            ServerRead: The newly created server, with associated item IDs.

        Raises:
            ServerNameConflictError: If a server with the same name already exists.
            ServerError: If any associated tool, resource, or prompt does not exist, or if any other
                        registration error occurs.
        """
        try:
            # Check for an existing server with the same name.
            existing = db.execute(select(DbServer).where(DbServer.name == server_in.name)).scalar_one_or_none()
            if existing:
                raise ServerNameConflictError(server_in.name, is_active=existing.is_active, server_id=existing.id)

            # Create the new server record.
            db_server = DbServer(
                name=server_in.name,
                description=server_in.description,
                icon=server_in.icon,
                is_active=True,
            )
            db.add(db_server)

            # Associate tools, verifying each exists.
            if server_in.associated_tools:
                for tool_id in server_in.associated_tools:
                    if tool_id.strip() == "":
                        continue
                    tool_obj = db.get(DbTool, tool_id)
                    if not tool_obj:
                        raise ServerError(f"Tool with id {tool_id} does not exist.")
                    db_server.tools.append(tool_obj)

            # Associate resources, verifying each exists.
            if server_in.associated_resources:
                for resource_id in server_in.associated_resources:
                    if resource_id.strip() == "":
                        continue
                    resource_obj = db.get(DbResource, int(resource_id))
                    if not resource_obj:
                        raise ServerError(f"Resource with id {resource_id} does not exist.")
                    db_server.resources.append(resource_obj)

            # Associate prompts, verifying each exists.
            if server_in.associated_prompts:
                for prompt_id in server_in.associated_prompts:
                    if prompt_id.strip() == "":
                        continue
                    prompt_obj = db.get(DbPrompt, int(prompt_id))
                    if not prompt_obj:
                        raise ServerError(f"Prompt with id {prompt_id} does not exist.")
                    db_server.prompts.append(prompt_obj)

            # Commit the new record and refresh.
            db.commit()
            db.refresh(db_server)
            # Force load the relationship attributes.
            _ = db_server.tools, db_server.resources, db_server.prompts

            # Assemble response data with associated item IDs.
            server_data = {
                "id": db_server.id,
                "name": db_server.name,
                "description": db_server.description,
                "icon": db_server.icon,
                "created_at": db_server.created_at,
                "updated_at": db_server.updated_at,
                "is_active": db_server.is_active,
                "associated_tools": [str(tool.id) for tool in db_server.tools],
                "associated_resources": [str(resource.id) for resource in db_server.resources],
                "associated_prompts": [str(prompt.id) for prompt in db_server.prompts],
            }
            logger.debug(f"Server Data: {server_data}")
            await self._notify_server_added(db_server)
            logger.info(f"Registered server: {server_in.name}")
            return self._convert_server_to_read(db_server)
        except IntegrityError:
            db.rollback()
            raise ServerError(f"Server already exists: {server_in.name}")
        except Exception as e:
            db.rollback()
            raise ServerError(f"Failed to register server: {str(e)}")

    async def list_servers(self, db: Session, include_inactive: bool = False) -> List[ServerRead]:
        """List all registered servers.

        Args:
            db: Database session.
            include_inactive: Whether to include inactive servers.

        Returns:
            A list of ServerRead objects.
        """
        query = select(DbServer)
        if not include_inactive:
            query = query.where(DbServer.is_active)
        servers = db.execute(query).scalars().all()
        return [self._convert_server_to_read(s) for s in servers]

    async def get_server(self, db: Session, server_id: int) -> ServerRead:
        """Retrieve server details by ID.

        Args:
            db: Database session.
            server_id: The unique identifier of the server.

        Returns:
            The corresponding ServerRead object.

        Raises:
            ServerNotFoundError: If no server with the given ID exists.
        """
        server = db.get(DbServer, server_id)
        if not server:
            raise ServerNotFoundError(f"Server not found: {server_id}")
        server_data = {
            "id": server.id,
            "name": server.name,
            "description": server.description,
            "icon": server.icon,
            "created_at": server.created_at,
            "updated_at": server.updated_at,
            "is_active": server.is_active,
            "associated_tools": [tool.qualified_name for tool in server.tools],
            "associated_resources": [res.id for res in server.resources],
            "associated_prompts": [prompt.id for prompt in server.prompts],
        }
        logger.debug(f"Server Data: {server_data}")
        return self._convert_server_to_read(server)

    async def update_server(self, db: Session, server_id: int, server_update: ServerUpdate) -> ServerRead:
        """Update an existing server.

        Args:
            db: Database session.
            server_id: The unique identifier of the server.
            server_update: Server update schema with new data.

        Returns:
            The updated ServerRead object.

        Raises:
            ServerNotFoundError: If the server is not found.
            ServerNameConflictError: If a new name conflicts with an existing server.
            ServerError: For other update errors.
        """
        try:
            server = db.get(DbServer, server_id)
            if not server:
                raise ServerNotFoundError(f"Server not found: {server_id}")

            # Check for name conflict if name is being changed
            if server_update.name and server_update.name != server.name:
                conflict = db.execute(select(DbServer).where(DbServer.name == server_update.name).where(DbServer.id != server_id)).scalar_one_or_none()
                if conflict:
                    raise ServerNameConflictError(
                        server_update.name,
                        is_active=conflict.is_active,
                        server_id=conflict.id,
                    )

            # Update simple fields
            if server_update.name is not None:
                server.name = server_update.name
            if server_update.description is not None:
                server.description = server_update.description
            if server_update.icon is not None:
                server.icon = server_update.icon

            # Update associated tools if provided
            if server_update.associated_tools is not None:
                server.tools = []
                for tool_id in server_update.associated_tools:
                    tool_obj = db.get(DbTool, tool_id)
                    if tool_obj:
                        server.tools.append(tool_obj)

            # Update associated resources if provided
            if server_update.associated_resources is not None:
                server.resources = []
                for resource_id in server_update.associated_resources:
                    resource_obj = db.get(DbResource, int(resource_id))
                    if resource_obj:
                        server.resources.append(resource_obj)

            # Update associated prompts if provided
            if server_update.associated_prompts is not None:
                server.prompts = []
                for prompt_id in server_update.associated_prompts:
                    prompt_obj = db.get(DbPrompt, int(prompt_id))
                    if prompt_obj:
                        server.prompts.append(prompt_obj)

            server.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(server)
            # Force loading relationships
            _ = server.tools, server.resources, server.prompts

            await self._notify_server_updated(server)
            logger.info(f"Updated server: {server.name}")

            # Build a dictionary with associated IDs
            server_data = {
                "id": server.id,
                "name": server.name,
                "description": server.description,
                "icon": server.icon,
                "created_at": server.created_at,
                "updated_at": server.updated_at,
                "is_active": server.is_active,
                "associated_tools": [tool.id for tool in server.tools],
                "associated_resources": [res.id for res in server.resources],
                "associated_prompts": [prompt.id for prompt in server.prompts],
            }
            logger.debug(f"Server Data: {server_data}")
            return self._convert_server_to_read(server)
        except Exception as e:
            db.rollback()
            raise ServerError(f"Failed to update server: {str(e)}")

    async def toggle_server_status(self, db: Session, server_id: int, activate: bool) -> ServerRead:
        """Toggle the activation status of a server.

        Args:
            db: Database session.
            server_id: The unique identifier of the server.
            activate: True to activate, False to deactivate.

        Returns:
            The updated ServerRead object.

        Raises:
            ServerNotFoundError: If the server is not found.
            ServerError: For other errors.
        """
        try:
            server = db.get(DbServer, server_id)
            if not server:
                raise ServerNotFoundError(f"Server not found: {server_id}")

            if server.is_active != activate:
                server.is_active = activate
                server.updated_at = datetime.utcnow()
                db.commit()
                db.refresh(server)
                if activate:
                    await self._notify_server_activated(server)
                else:
                    await self._notify_server_deactivated(server)
                logger.info(f"Server {server.name} {'activated' if activate else 'deactivated'}")

            server_data = {
                "id": server.id,
                "name": server.name,
                "description": server.description,
                "icon": server.icon,
                "created_at": server.created_at,
                "updated_at": server.updated_at,
                "is_active": server.is_active,
                "associated_tools": [tool.id for tool in server.tools],
                "associated_resources": [res.id for res in server.resources],
                "associated_prompts": [prompt.id for prompt in server.prompts],
            }
            logger.debug(f"Server Data: {server_data}")
            return self._convert_server_to_read(server)
        except Exception as e:
            db.rollback()
            raise ServerError(f"Failed to toggle server status: {str(e)}")

    async def delete_server(self, db: Session, server_id: int) -> None:
        """Permanently delete a server.

        Args:
            db: Database session.
            server_id: The unique identifier of the server.

        Raises:
            ServerNotFoundError: If the server is not found.
            ServerError: For other deletion errors.
        """
        try:
            server = db.get(DbServer, server_id)
            if not server:
                raise ServerNotFoundError(f"Server not found: {server_id}")

            server_info = {"id": server.id, "name": server.name}
            db.delete(server)
            db.commit()

            await self._notify_server_deleted(server_info)
            logger.info(f"Deleted server: {server_info['name']}")
        except Exception as e:
            db.rollback()
            raise ServerError(f"Failed to delete server: {str(e)}")

    async def _publish_event(self, event: Dict[str, Any]) -> None:
        """
        Publish an event to all subscribed queues.

        Args:
            event: Event to publish
        """
        for queue in self._event_subscribers:
            await queue.put(event)

    async def subscribe_events(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Subscribe to server events.

        Yields:
            Server event messages.
        """
        queue: asyncio.Queue = asyncio.Queue()
        self._event_subscribers.append(queue)
        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            self._event_subscribers.remove(queue)

    async def _notify_server_added(self, server: DbServer) -> None:
        """
        Notify subscribers that a new server has been added.

        Args:
            server: Server to add
        """
        associated_tools = [tool.id for tool in server.tools] if server.tools else []
        associated_resources = [res.id for res in server.resources] if server.resources else []
        associated_prompts = [prompt.id for prompt in server.prompts] if server.prompts else []
        event = {
            "type": "server_added",
            "data": {
                "id": server.id,
                "name": server.name,
                "description": server.description,
                "icon": server.icon,
                "associated_tools": associated_tools,
                "associated_resources": associated_resources,
                "associated_prompts": associated_prompts,
                "is_active": server.is_active,
            },
            "timestamp": datetime.utcnow().isoformat(),
        }
        await self._publish_event(event)

    async def _notify_server_updated(self, server: DbServer) -> None:
        """
        Notify subscribers that a server has been updated.

        Args:
            server: Server to update
        """
        associated_tools = [tool.id for tool in server.tools] if server.tools else []
        associated_resources = [res.id for res in server.resources] if server.resources else []
        associated_prompts = [prompt.id for prompt in server.prompts] if server.prompts else []
        event = {
            "type": "server_updated",
            "data": {
                "id": server.id,
                "name": server.name,
                "description": server.description,
                "icon": server.icon,
                "associated_tools": associated_tools,
                "associated_resources": associated_resources,
                "associated_prompts": associated_prompts,
                "is_active": server.is_active,
            },
            "timestamp": datetime.utcnow().isoformat(),
        }
        await self._publish_event(event)

    async def _notify_server_activated(self, server: DbServer) -> None:
        """
        Notify subscribers that a server has been activated.

        Args:
            server: Server to activate
        """
        event = {
            "type": "server_activated",
            "data": {
                "id": server.id,
                "name": server.name,
                "is_active": True,
            },
            "timestamp": datetime.utcnow().isoformat(),
        }
        await self._publish_event(event)

    async def _notify_server_deactivated(self, server: DbServer) -> None:
        """
        Notify subscribers that a server has been deactivated.

        Args:
            server: Server to deactivate
        """
        event = {
            "type": "server_deactivated",
            "data": {
                "id": server.id,
                "name": server.name,
                "is_active": False,
            },
            "timestamp": datetime.utcnow().isoformat(),
        }
        await self._publish_event(event)

    async def _notify_server_deleted(self, server_info: Dict[str, Any]) -> None:
        """
        Notify subscribers that a server has been deleted.

        Args:
            server_info: Dictionary on server to be deleted
        """
        event = {
            "type": "server_deleted",
            "data": server_info,
            "timestamp": datetime.utcnow().isoformat(),
        }
        await self._publish_event(event)

    # --- Metrics ---
    async def aggregate_metrics(self, db: Session) -> ServerMetrics:
        """
        Aggregate metrics for all server invocations across all servers.

        Args:
            db: Database session

        Returns:
            ServerMetrics: Aggregated metrics computed from all ServerMetric records.
        """
        total_executions = db.execute(select(func.count()).select_from(ServerMetric)).scalar() or 0  # pylint: disable=not-callable

        successful_executions = db.execute(select(func.count()).select_from(ServerMetric).where(ServerMetric.is_success)).scalar() or 0  # pylint: disable=not-callable

        failed_executions = db.execute(select(func.count()).select_from(ServerMetric).where(not_(ServerMetric.is_success))).scalar() or 0  # pylint: disable=not-callable

        min_response_time = db.execute(select(func.min(ServerMetric.response_time))).scalar()

        max_response_time = db.execute(select(func.max(ServerMetric.response_time))).scalar()

        avg_response_time = db.execute(select(func.avg(ServerMetric.response_time))).scalar()

        last_execution_time = db.execute(select(func.max(ServerMetric.timestamp))).scalar()

        return ServerMetrics(
            total_executions=total_executions,
            successful_executions=successful_executions,
            failed_executions=failed_executions,
            failure_rate=(failed_executions / total_executions) if total_executions > 0 else 0.0,
            min_response_time=min_response_time,
            max_response_time=max_response_time,
            avg_response_time=avg_response_time,
            last_execution_time=last_execution_time,
        )

    async def reset_metrics(self, db: Session) -> None:
        """
        Reset all server metrics by deleting all records from the server metrics table.

        Args:
            db: Database session
        """
        db.execute(delete(ServerMetric))
        db.commit()
