# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/grpc_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: MCP Gateway Contributors

gRPC Service Management

This module implements gRPC service management for the MCP Gateway.
It handles gRPC service registration, reflection-based discovery, listing,
retrieval, updates, activation toggling, and deletion.
"""

# Standard
import asyncio
import base64
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

try:
    # Third-Party
    import grpc
    from grpc_reflection.v1alpha import reflection_pb2, reflection_pb2_grpc

    GRPC_AVAILABLE = True
except ImportError:
    GRPC_AVAILABLE = False
    # grpc module will not be used if not available
    grpc = None  # type: ignore
    reflection_pb2 = None  # type: ignore
    reflection_pb2_grpc = None  # type: ignore

# Third-Party
from pydantic import ValidationError
from sqlalchemy import and_, delete, desc, select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import EmailTeam
from mcpgateway.db import GrpcService as DbGrpcService
from mcpgateway.db import server_tool_association
from mcpgateway.db import Tool as DbTool
from mcpgateway.db import ToolMetric
from mcpgateway.schemas import GrpcServiceCreate, GrpcServiceRead, GrpcServiceUpdate
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.team_management_service import TeamManagementService
from mcpgateway.utils.create_slug import slugify
from mcpgateway.utils.display_name import generate_display_name
from mcpgateway.utils.pagination import unified_paginate

# Initialize logging
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class GrpcServiceError(Exception):
    """Base class for gRPC service-related errors."""


class GrpcServiceNotFoundError(GrpcServiceError):
    """Raised when a requested gRPC service is not found."""


class GrpcServiceNameConflictError(GrpcServiceError):
    """Raised when a gRPC service name conflicts with an existing one."""

    def __init__(self, name: str, is_active: bool = True, service_id: Optional[str] = None):
        """Initialize the GrpcServiceNameConflictError.

        Args:
            name: The conflicting gRPC service name
            is_active: Whether the conflicting service is currently active
            service_id: The ID of the conflicting service, if known
        """
        self.name = name
        self.is_active = is_active
        self.service_id = service_id
        msg = f"gRPC service with name '{name}' already exists"
        if not is_active:
            msg += " (inactive)"
        if service_id:
            msg += f" (ID: {service_id})"
        super().__init__(msg)


class GrpcService:
    """Service for managing gRPC services with reflection-based discovery."""

    def __init__(self):
        """Initialize the gRPC service manager."""

    async def register_service(
        self,
        db: Session,
        service_data: GrpcServiceCreate,
        user_email: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> GrpcServiceRead:
        """Register a new gRPC service.

        Args:
            db: Database session
            service_data: gRPC service creation data
            user_email: Email of the user creating the service
            metadata: Additional metadata (IP, user agent, etc.)

        Returns:
            GrpcServiceRead: The created service

        Raises:
            GrpcServiceNameConflictError: If service name already exists
        """
        # Check for name conflicts
        existing = db.execute(select(DbGrpcService).where(DbGrpcService.name == service_data.name)).scalar_one_or_none()

        if existing:
            raise GrpcServiceNameConflictError(name=service_data.name, is_active=existing.enabled, service_id=existing.id)

        # Create service
        db_service = DbGrpcService(
            name=service_data.name,
            target=service_data.target,
            description=service_data.description,
            reflection_enabled=service_data.reflection_enabled,
            tls_enabled=service_data.tls_enabled,
            tls_cert_path=service_data.tls_cert_path,
            tls_key_path=service_data.tls_key_path,
            grpc_metadata=service_data.grpc_metadata or {},
            tags=service_data.tags or [],
            team_id=service_data.team_id,
            owner_email=user_email or service_data.owner_email,
            visibility=service_data.visibility,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        # Set audit metadata if provided
        if metadata:
            db_service.created_by = user_email
            db_service.created_from_ip = metadata.get("created_from_ip")
            db_service.created_via = metadata.get("created_via")
            db_service.created_user_agent = metadata.get("created_user_agent")

        db.add(db_service)
        db.commit()
        db.refresh(db_service)

        logger.info("Registered gRPC service: %s (target: %s)", db_service.name, db_service.target)

        # Perform initial reflection if enabled
        if db_service.reflection_enabled:
            try:
                await self._perform_reflection(db, db_service)
            except Exception as e:
                logger.warning(f"Initial reflection failed for {db_service.name}: {e}")

        return GrpcServiceRead.model_validate(db_service)

    async def list_services(
        self,
        db: Session,
        cursor: Optional[str] = None,
        include_inactive: bool = False,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        per_page: Optional[int] = None,
        user_email: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> Union[tuple[List[GrpcServiceRead], Optional[str]], Dict[str, Any]]:
        """List gRPC services with pagination and optional filtering.

        Args:
            db: Database session
            cursor: Pagination cursor for keyset pagination
            include_inactive: Include disabled services
            limit: Maximum number of services to return. None for default, 0 for unlimited
            page: Page number for page-based pagination (1-indexed). Mutually exclusive with cursor
            per_page: Items per page for page-based pagination
            user_email: Filter by user email for team access control
            team_id: Filter by team ID

        Returns:
            If page is provided: Dict with {"data": [...], "pagination": {...}, "links": {...}}
            If cursor is provided or neither: tuple of (list of GrpcServiceRead objects, next_cursor)
        """
        # Build base query with ordering
        query = select(DbGrpcService).order_by(desc(DbGrpcService.created_at), desc(DbGrpcService.id))

        # Apply team filtering
        if user_email and team_id:
            team_service = TeamManagementService(db)
            team_filter = await team_service.build_team_filter_clause(DbGrpcService, user_email, team_id)  # pylint: disable=no-member
            if team_filter is not None:
                query = query.where(team_filter)
        elif team_id:
            query = query.where(DbGrpcService.team_id == team_id)

        # Apply active filter
        if not include_inactive:
            query = query.where(DbGrpcService.enabled.is_(True))  # pylint: disable=singleton-comparison

        # Use unified pagination helper - handles both page and cursor pagination
        pag_result = await unified_paginate(
            db=db,
            query=query,
            page=page,
            per_page=per_page,
            cursor=cursor,
            limit=limit,
            base_url="/admin/grpc",
            query_params={"include_inactive": include_inactive} if include_inactive else {},
        )

        next_cursor = None
        # Extract services based on pagination type
        if page is not None:
            # Page-based: pag_result is a dict
            services_db = pag_result["data"]
        else:
            # Cursor-based: pag_result is a tuple
            services_db, next_cursor = pag_result

        # Fetch team names for the services
        team_ids_set = {s.team_id for s in services_db if s.team_id}
        team_map = {}
        if team_ids_set:
            teams = db.execute(select(EmailTeam.id, EmailTeam.name).where(EmailTeam.id.in_(team_ids_set), EmailTeam.is_active.is_(True))).all()
            team_map = {team.id: team.name for team in teams}

        db.commit()  # Release transaction to avoid idle-in-transaction

        # Convert to GrpcServiceRead
        result = []
        for s in services_db:
            try:
                s.team = team_map.get(s.team_id) if s.team_id else None
                result.append(GrpcServiceRead.model_validate(s))
            except (ValidationError, ValueError, KeyError, TypeError) as e:
                logger.exception(f"Failed to convert gRPC service {getattr(s, 'id', 'unknown')} ({getattr(s, 'name', 'unknown')}): {e}")

        # Return appropriate format based on pagination type
        if page is not None:
            # Page-based format
            return {
                "data": result,
                "pagination": pag_result["pagination"],
                "links": pag_result["links"],
            }

        # Cursor-based format (tuple)
        return (result, next_cursor)

    async def get_service(
        self,
        db: Session,
        service_id: str,
        user_email: Optional[str] = None,
    ) -> GrpcServiceRead:
        """Get a specific gRPC service by ID.

        Args:
            db: Database session
            service_id: Service ID
            user_email: Email for team access control

        Returns:
            The gRPC service

        Raises:
            GrpcServiceNotFoundError: If service not found or access denied
        """
        query = select(DbGrpcService).where(DbGrpcService.id == service_id)

        # Apply team access control
        if user_email:
            team_service = TeamManagementService(db)
            team_filter = await team_service.build_team_filter_clause(DbGrpcService, user_email, None)  # pylint: disable=no-member
            if team_filter is not None:
                query = query.where(team_filter)

        service = db.execute(query).scalar_one_or_none()

        if not service:
            raise GrpcServiceNotFoundError(f"gRPC service with ID '{service_id}' not found")

        return GrpcServiceRead.model_validate(service)

    async def update_service(
        self,
        db: Session,
        service_id: str,
        service_data: GrpcServiceUpdate,
        user_email: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> GrpcServiceRead:
        """Update an existing gRPC service.

        Args:
            db: Database session
            service_id: Service ID to update
            service_data: Update data
            user_email: Email of user performing update
            metadata: Audit metadata

        Returns:
            Updated service

        Raises:
            GrpcServiceNotFoundError: If service not found
            GrpcServiceNameConflictError: If new name conflicts
        """
        service = db.execute(select(DbGrpcService).where(DbGrpcService.id == service_id)).scalar_one_or_none()

        if not service:
            raise GrpcServiceNotFoundError(f"gRPC service with ID '{service_id}' not found")

        # Check name conflict if name is being changed
        if service_data.name and service_data.name != service.name:
            existing = db.execute(select(DbGrpcService).where(and_(DbGrpcService.name == service_data.name, DbGrpcService.id != service_id))).scalar_one_or_none()

            if existing:
                raise GrpcServiceNameConflictError(name=service_data.name, is_active=existing.enabled, service_id=existing.id)

        # Update fields
        update_data = service_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(service, field, value)

        service.updated_at = datetime.now(timezone.utc)

        # Set audit metadata
        if metadata and user_email:
            service.modified_by = user_email
            service.modified_from_ip = metadata.get("modified_from_ip")
            service.modified_via = metadata.get("modified_via")
            service.modified_user_agent = metadata.get("modified_user_agent")

        service.version += 1

        db.commit()
        db.refresh(service)

        logger.info("Updated gRPC service: %s", service.name)

        return GrpcServiceRead.model_validate(service)

    async def set_service_state(
        self,
        db: Session,
        service_id: str,
        activate: bool,
    ) -> GrpcServiceRead:
        """Set a gRPC service's enabled status.

        Args:
            db: Database session
            service_id: Service ID
            activate: True to enable, False to disable

        Returns:
            Updated service

        Raises:
            GrpcServiceNotFoundError: If service not found
        """
        service = db.execute(select(DbGrpcService).where(DbGrpcService.id == service_id)).scalar_one_or_none()

        if not service:
            raise GrpcServiceNotFoundError(f"gRPC service with ID '{service_id}' not found")

        service.enabled = activate
        service.updated_at = datetime.now(timezone.utc)

        db.commit()
        db.refresh(service)

        action = "activated" if activate else "deactivated"
        logger.info("gRPC service %s %s", service.name, action)

        return GrpcServiceRead.model_validate(service)

    async def delete_service(
        self,
        db: Session,
        service_id: str,
    ) -> None:
        """Delete a gRPC service and its associated tools.

        Explicitly deletes child tool records (metrics, server associations, tools)
        before deleting the service itself, following the same pattern as
        gateway_service.delete_gateway() to avoid FK constraint violations.

        Args:
            db: Database session
            service_id: Service ID to delete

        Raises:
            GrpcServiceNotFoundError: If service not found
        """
        service = db.execute(select(DbGrpcService).where(DbGrpcService.id == service_id)).scalar_one_or_none()

        if not service:
            raise GrpcServiceNotFoundError(f"gRPC service with ID '{service_id}' not found")

        # Explicitly delete tool children before deleting the service
        # (mirrors gateway_service.delete_gateway pattern)
        tool_ids = [t.id for t in service.tools]
        if tool_ids:
            for i in range(0, len(tool_ids), 500):
                chunk = tool_ids[i : i + 500]
                db.execute(delete(ToolMetric).where(ToolMetric.tool_id.in_(chunk)))
                db.execute(delete(server_tool_association).where(server_tool_association.c.tool_id.in_(chunk)))
                db.execute(delete(DbTool).where(DbTool.id.in_(chunk)))

        db.delete(service)
        db.commit()

        logger.info("Deleted gRPC service: %s (removed %d tools)", service.name, len(tool_ids))

    async def reflect_service(
        self,
        db: Session,
        service_id: str,
    ) -> GrpcServiceRead:
        """Trigger reflection on a gRPC service to discover services and methods.

        Args:
            db: Database session
            service_id: Service ID

        Returns:
            Updated service with reflection results

        Raises:
            GrpcServiceNotFoundError: If service not found
            GrpcServiceError: If reflection fails
        """
        service = db.execute(select(DbGrpcService).where(DbGrpcService.id == service_id)).scalar_one_or_none()

        if not service:
            raise GrpcServiceNotFoundError(f"gRPC service with ID '{service_id}' not found")

        try:
            await self._perform_reflection(db, service)
            logger.info("Reflection completed for %s: %s services, %s methods", service.name, service.service_count, service.method_count)
        except Exception as e:
            logger.error(f"Reflection failed for {service.name}: {e}")
            service.reachable = False
            db.commit()
            raise GrpcServiceError(f"Reflection failed: {str(e)}")

        return GrpcServiceRead.model_validate(service)

    async def get_service_methods(
        self,
        db: Session,
        service_id: str,
    ) -> List[Dict[str, Any]]:
        """Get the list of methods for a gRPC service.

        Args:
            db: Database session
            service_id: Service ID

        Returns:
            List of method descriptors

        Raises:
            GrpcServiceNotFoundError: If service not found
        """
        service = db.execute(select(DbGrpcService).where(DbGrpcService.id == service_id)).scalar_one_or_none()

        if not service:
            raise GrpcServiceNotFoundError(f"gRPC service with ID '{service_id}' not found")

        methods = []
        discovered = service.discovered_services or {}

        for service_name, service_desc in discovered.items():
            if service_name.startswith("_"):
                continue
            for method in service_desc.get("methods", []):
                methods.append(
                    {
                        "service": service_name,
                        "method": method["name"],
                        "full_name": f"{service_name}.{method['name']}",
                        "input_type": method.get("input_type"),
                        "output_type": method.get("output_type"),
                        "client_streaming": method.get("client_streaming", False),
                        "server_streaming": method.get("server_streaming", False),
                    }
                )

        return methods

    async def _perform_reflection(
        self,
        db: Session,
        service: DbGrpcService,
    ) -> None:
        """Perform gRPC server reflection to discover services.

        Args:
            db: Database session
            service: GrpcService model instance

        Raises:
            GrpcServiceError: If TLS certificate files not found
            Exception: If reflection or connection fails
        """
        # Create gRPC channel
        if service.tls_enabled:
            if service.tls_cert_path and service.tls_key_path:
                # Load TLS certificates
                try:
                    cert = await asyncio.to_thread(Path(service.tls_cert_path).read_bytes)
                    key = await asyncio.to_thread(Path(service.tls_key_path).read_bytes)
                    credentials = grpc.ssl_channel_credentials(root_certificates=cert, private_key=key)
                except FileNotFoundError as e:
                    raise GrpcServiceError(f"TLS certificate or key file not found: {e}")
            else:
                # Use default system certificates
                credentials = grpc.ssl_channel_credentials()

            channel = grpc.secure_channel(service.target, credentials)
        else:
            channel = grpc.insecure_channel(service.target)

        try:  # pylint: disable=too-many-nested-blocks
            # Import here to avoid circular dependency
            # Third-Party
            from google.protobuf.descriptor_pb2 import FileDescriptorProto  # pylint: disable=import-outside-toplevel,no-name-in-module

            # Create reflection stub
            stub = reflection_pb2_grpc.ServerReflectionStub(channel)

            # List services
            request = reflection_pb2.ServerReflectionRequest(list_services="")  # pylint: disable=no-member

            response = stub.ServerReflectionInfo(iter([request]))

            service_names = []
            for resp in response:
                if resp.HasField("list_services_response"):
                    for svc in resp.list_services_response.service:
                        service_name = svc.name
                        # Skip reflection service itself
                        if "ServerReflection" in service_name:
                            continue
                        service_names.append(service_name)

            # Get detailed information for each service
            discovered_services = {}
            file_descriptor_bytes_set: set[bytes] = set()  # Deduplicate across services
            service_count = 0
            method_count = 0

            for service_name in service_names:
                try:
                    # Request file descriptor containing this service
                    file_request = reflection_pb2.ServerReflectionRequest(file_containing_symbol=service_name)  # pylint: disable=no-member

                    file_response = stub.ServerReflectionInfo(iter([file_request]))

                    for resp in file_response:
                        if resp.HasField("file_descriptor_response"):
                            # Process file descriptors
                            for file_desc_proto_bytes in resp.file_descriptor_response.file_descriptor_proto:
                                # Store raw bytes for later descriptor pool population
                                file_descriptor_bytes_set.add(file_desc_proto_bytes)

                                file_desc_proto = FileDescriptorProto()
                                file_desc_proto.ParseFromString(file_desc_proto_bytes)

                                # Extract service and method information
                                for service_desc in file_desc_proto.service:
                                    if service_desc.name in service_name or service_name.endswith(service_desc.name):
                                        full_service_name = f"{file_desc_proto.package}.{service_desc.name}" if file_desc_proto.package else service_desc.name

                                        methods = []
                                        for method_desc in service_desc.method:
                                            methods.append(
                                                {
                                                    "name": method_desc.name,
                                                    "input_type": method_desc.input_type,
                                                    "output_type": method_desc.output_type,
                                                    "client_streaming": method_desc.client_streaming,
                                                    "server_streaming": method_desc.server_streaming,
                                                }
                                            )
                                            method_count += 1

                                        discovered_services[full_service_name] = {
                                            "name": full_service_name,
                                            "methods": methods,
                                            "package": file_desc_proto.package,
                                        }
                                        service_count += 1

                except Exception as detail_error:
                    logger.warning(f"Failed to get details for {service_name}: {detail_error}")
                    # Add basic info even if detailed discovery fails
                    discovered_services[service_name] = {
                        "name": service_name,
                        "methods": [],
                    }
                    service_count += 1

            # Store base64-encoded file descriptor protos so invoke_method can
            # populate the descriptor pool without a reflection round-trip.
            discovered_services["_file_descriptors"] = [base64.b64encode(b).decode("ascii") for b in file_descriptor_bytes_set]

            service.discovered_services = discovered_services
            service.service_count = service_count
            service.method_count = method_count
            service.last_reflection = datetime.now(timezone.utc)
            service.reachable = True

            # Sync discovered methods as MCP tools
            self._sync_tools_from_reflection(db, service)

            db.commit()

        except Exception as e:
            logger.error(f"Reflection error for {service.target}: {e}")
            service.reachable = False
            db.commit()
            raise

        finally:
            channel.close()

    def _sync_tools_from_reflection(
        self,
        db: Session,
        service: DbGrpcService,
    ) -> None:
        """Sync MCP tools from discovered gRPC methods.

        Removes stale tools and creates/updates tools for each discovered method.
        This follows the same pattern as gateway_service._update_or_create_tools().

        Args:
            db: Database session
            service: GrpcService model instance with populated discovered_services
        """
        discovered = service.discovered_services or {}

        # Build set of expected tool names from discovered methods
        expected_tool_names: set[str] = set()
        for svc_name, svc_desc in discovered.items():
            if svc_name.startswith("_"):
                continue
            for method in svc_desc.get("methods", []):
                expected_tool_names.add(f"{svc_name}.{method['name']}")

        # Fetch existing tools for this gRPC service
        existing_tools = db.execute(select(DbTool).where(DbTool.grpc_service_id == service.id)).scalars().all()
        existing_tools_map = {tool.original_name: tool for tool in existing_tools}

        # Remove stale tools (tools whose names are no longer in discovered methods)
        stale_tool_ids = [tool.id for tool in existing_tools if tool.original_name not in expected_tool_names]
        if stale_tool_ids:
            for i in range(0, len(stale_tool_ids), 500):
                chunk = stale_tool_ids[i : i + 500]
                db.execute(delete(ToolMetric).where(ToolMetric.tool_id.in_(chunk)))
                db.execute(delete(server_tool_association).where(server_tool_association.c.tool_id.in_(chunk)))
                db.execute(delete(DbTool).where(DbTool.id.in_(chunk)))
            logger.info("Removed %d stale tools for gRPC service %s", len(stale_tool_ids), service.name)

        # Create or update tools for each discovered method
        tools_created = 0
        tools_updated = 0
        for svc_name, svc_desc in discovered.items():
            if svc_name.startswith("_"):
                continue
            for method in svc_desc.get("methods", []):
                tool_name = f"{svc_name}.{method['name']}"
                description = f"gRPC method {tool_name}"
                input_schema = {
                    "type": "object",
                    "properties": {},
                    "x-grpc-input-type": method.get("input_type", ""),
                    "x-grpc-output-type": method.get("output_type", ""),
                    "x-grpc-client-streaming": method.get("client_streaming", False),
                    "x-grpc-server-streaming": method.get("server_streaming", False),
                }

                existing_tool = existing_tools_map.get(tool_name)
                if existing_tool:
                    # Update if description or schema changed
                    changed = False
                    if existing_tool.original_description != description:
                        if existing_tool.description == existing_tool.original_description:
                            existing_tool.description = description
                        existing_tool.original_description = description
                        changed = True
                    if existing_tool.input_schema != input_schema:
                        existing_tool.input_schema = input_schema
                        changed = True
                    if existing_tool.url != service.target:
                        existing_tool.url = service.target
                        changed = True
                    if changed:
                        tools_updated += 1
                else:
                    db_tool = DbTool(
                        original_name=tool_name,
                        custom_name=tool_name,
                        custom_name_slug=slugify(tool_name),
                        display_name=generate_display_name(tool_name),
                        url=service.target,
                        original_description=description,
                        description=description,
                        integration_type="gRPC",
                        input_schema=input_schema,
                        created_by="system",
                        created_via="grpc-reflection",
                        federation_source=service.name,
                        version=1,
                        team_id=service.team_id,
                        owner_email=service.owner_email,
                        visibility="public",
                        grpc_service_id=service.id,
                    )
                    db.add(db_tool)
                    tools_created += 1

        logger.info("Synced tools for gRPC service %s: %d created, %d updated", service.name, tools_created, tools_updated)

    async def invoke_method(
        self,
        db: Session,
        service_id: str,
        method_name: str,
        request_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Invoke a gRPC method on a registered service.

        Args:
            db: Database session
            service_id: Service ID
            method_name: Full method name (service.Method)
            request_data: JSON request data

        Returns:
            JSON response data

        Raises:
            GrpcServiceNotFoundError: If service not found
            GrpcServiceError: If invocation fails
        """
        service = db.execute(select(DbGrpcService).where(DbGrpcService.id == service_id)).scalar_one_or_none()

        if not service:
            raise GrpcServiceNotFoundError(f"gRPC service with ID '{service_id}' not found")

        if not service.enabled:
            raise GrpcServiceError(f"Service '{service.name}' is disabled")

        # Import here to avoid circular dependency
        # First-Party
        from mcpgateway.translate_grpc import GrpcEndpoint  # pylint: disable=import-outside-toplevel

        # Parse method name (service.Method format)
        if "." not in method_name:
            raise GrpcServiceError(f"Invalid method name '{method_name}', expected 'service.Method' format")

        parts = method_name.rsplit(".", 1)
        service_name = ".".join(parts[:-1]) if len(parts) > 1 else parts[0]
        method = parts[-1]

        # Check if we have stored file descriptors from reflection.
        # If so, we can populate the descriptor pool without a reflection
        # round-trip, which avoids per-call overhead.
        discovered = service.discovered_services or {}
        stored_descriptors = discovered.get("_file_descriptors", [])
        has_stored_descriptors = bool(stored_descriptors)

        endpoint = GrpcEndpoint(
            target=service.target,
            reflection_enabled=not has_stored_descriptors,
            tls_enabled=service.tls_enabled,
            tls_cert_path=service.tls_cert_path,
            tls_key_path=service.tls_key_path,
            metadata=service.grpc_metadata or {},
        )

        try:
            # Start connection (reflection only if no stored descriptors)
            await endpoint.start()

            if has_stored_descriptors:
                # Populate descriptor pool from stored file descriptor bytes
                raw_descriptors = [base64.b64decode(b) for b in stored_descriptors]
                endpoint.load_file_descriptors(raw_descriptors)
                # Set service info from stored discovery data
                endpoint._services = {k: v for k, v in discovered.items() if k != "_file_descriptors"}  # pylint: disable=protected-access

            # Invoke method
            response = await endpoint.invoke(service_name, method, request_data)

            return response

        except Exception as e:
            logger.error(f"Failed to invoke {method_name} on {service.name}: {e}")
            raise GrpcServiceError(f"Method invocation failed: {e}")

        finally:
            await endpoint.close()
