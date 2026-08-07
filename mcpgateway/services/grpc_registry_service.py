# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/grpc_registry_service.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Read-only registry views over gRPC services, their schema artifacts, methods,
and the exposure status of the tools derived from those methods.

These queries never mutate rows: no writes, no tool synchronization, no schema
activation. They join the immutable schema artifacts with the tool table so
administrators can see which methods of which schema version are actually
served to clients.
"""

# Standard
from typing import Any, Optional

# Third-Party
from sqlalchemy import select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import GrpcSchemaArtifact, GrpcService as DbGrpcService, Tool as DbTool
from mcpgateway.schemas import (
    GrpcRegistryMethodRead,
    GrpcRegistrySchemaVersionRead,
    GrpcRegistrySchemaViewRead,
    GrpcRegistryServiceRead,
    GrpcRegistryViewRead,
)


class GrpcRegistryService:
    """Read-only queries that assemble the gRPC registry hierarchy."""

    @staticmethod
    def _methods_for_catalog(catalog: dict[str, Any]) -> list[dict[str, Any]]:
        """Flatten the stored catalog into ordered method records."""
        methods: list[dict[str, Any]] = []
        for service_name, service_desc in catalog.items():
            if service_name.startswith("_"):
                continue
            for method in service_desc.get("methods", []):
                methods.append(
                    {
                        "name": f"{service_name}.{method.get('name', '')}",
                        "input_type": method.get("input_type", ""),
                        "output_type": method.get("output_type", ""),
                        "client_streaming": bool(method.get("client_streaming", False)),
                        "server_streaming": bool(method.get("server_streaming", False)),
                    }
                )
        return methods

    @staticmethod
    def _tool_state_for(
        tool_map: dict[str, DbTool],
        tool_name: str,
        client_streaming: bool,
    ) -> dict[str, Any]:
        """Describe the exposure of one method from its derived tool row."""
        tool = tool_map.get(tool_name)
        if tool is None:
            return {
                "tool_id": None,
                "tool_enabled": False,
                "tool_deprecated": False,
                "tool_reachable": False,
                "exposed": False,
            }
        # Client-streaming and bidi methods are catalogued but intentionally not
        # executable MCP tools, so they are never "exposed" regardless of the row.
        live = bool(tool.enabled) and not bool(tool.deprecated) and bool(tool.reachable)
        exposed = live and not client_streaming
        return {
            "tool_id": tool.id,
            "tool_enabled": bool(tool.enabled),
            "tool_deprecated": bool(tool.deprecated),
            "tool_reachable": bool(tool.reachable),
            "exposed": exposed,
        }

    @staticmethod
    def _schema_version_summary(
        artifact: GrpcSchemaArtifact,
        catalog: dict[str, Any],
    ) -> GrpcRegistrySchemaVersionRead:
        """Summarize one artifact without emitting descriptor bytes."""
        methods = GrpcRegistryService._methods_for_catalog(catalog)
        return GrpcRegistrySchemaVersionRead(
            artifact_id=artifact.id,
            version=artifact.version,
            source_type=artifact.source_type,
            content_hash=artifact.content_hash,
            is_active=artifact.is_active,
            created_by=artifact.created_by,
            created_at=artifact.created_at,
            activated_at=artifact.activated_at,
            method_count=len(methods),
        )

    @staticmethod
    def _service_view(
        service: DbGrpcService,
        artifacts: list[GrpcSchemaArtifact],
        tool_map: dict[str, DbTool],
    ) -> GrpcRegistryServiceRead:
        """Assemble a single service-level registry view."""
        catalog = service.discovered_services or {}
        schema_versions: list[GrpcRegistrySchemaVersionRead] = []
        exposed_tool_count = 0
        for artifact in artifacts:
            artifact_catalog = (artifact.source_info or {}).get("catalog", {})
            schema_versions.append(GrpcRegistryService._schema_version_summary(artifact, artifact_catalog))
        for service_name, svc_desc in catalog.items():
            if service_name.startswith("_"):
                continue
            for method in svc_desc.get("methods", []):
                tool_name = f"{service_name}.{method.get('name', '')}"
                tool_state = GrpcRegistryService._tool_state_for(
                    tool_map, tool_name, bool(method.get("client_streaming", False))
                )
                if tool_state["exposed"]:
                    exposed_tool_count += 1
        total_tools = len(tool_map)
        return GrpcRegistryServiceRead(
            id=service.id,
            name=service.name,
            slug=service.slug,
            target=service.target,
            description=service.description,
            enabled=bool(service.enabled),
            reachable=bool(service.reachable),
            health_status=service.health_status or "unknown",
            service_count=service.service_count or 0,
            method_count=service.method_count or 0,
            active_schema_hash=service.active_schema_hash,
            schema_drift=bool(service.schema_drift),
            team_id=service.team_id,
            owner_email=service.owner_email,
            visibility=service.visibility or "public",
            schema_versions=schema_versions,
            tool_count=total_tools,
            exposed_tool_count=exposed_tool_count,
        )

    @staticmethod
    def build_registry_view(
        db: Session,
        service_ids: Optional[list[str]] = None,
    ) -> GrpcRegistryViewRead:
        """Build the full read-only registry across the given services.

        Args:
            db: Database session.
            service_ids: Restrict the view to these service IDs. An empty list
                yields an empty view; None means every service.

        Returns:
            A nested view of services, schema versions, methods, and tool state.
        """
        service_statement = select(DbGrpcService)
        if service_ids is not None:
            if not service_ids:
                return GrpcRegistryViewRead(services=[], total_services=0)
            service_statement = service_statement.where(DbGrpcService.id.in_(service_ids))
        services = list(db.execute(service_statement.order_by(DbGrpcService.name)).scalars().all())
        if not services:
            return GrpcRegistryViewRead(services=[], total_services=0)

        artifact_statement = (
            select(GrpcSchemaArtifact)
            .where(GrpcSchemaArtifact.grpc_service_id.in_([service.id for service in services]))
            .order_by(GrpcSchemaArtifact.grpc_service_id, GrpcSchemaArtifact.version)
        )
        artifacts = list(db.execute(artifact_statement).scalars().all())
        artifacts_by_service: dict[str, list[GrpcSchemaArtifact]] = {}
        for artifact in artifacts:
            artifacts_by_service.setdefault(artifact.grpc_service_id, []).append(artifact)

        tool_statement = select(DbTool).where(DbTool.grpc_service_id.in_([service.id for service in services]))
        tools = list(db.execute(tool_statement).scalars().all())
        tools_by_service: dict[str, dict[str, DbTool]] = {}
        for tool in tools:
            tools_by_service.setdefault(tool.grpc_service_id, {})[tool.original_name] = tool

        views = [
            GrpcRegistryService._service_view(
                service,
                artifacts_by_service.get(service.id, []),
                tools_by_service.get(service.id, {}),
            )
            for service in services
        ]

        total_schema_versions = sum(len(view.schema_versions) for view in views)
        return GrpcRegistryViewRead(
            services=views,
            total_services=len(views),
            total_schema_versions=total_schema_versions,
            total_methods=sum(view.method_count for view in views),
            total_exposed_tools=sum(view.exposed_tool_count for view in views),
        )

    @staticmethod
    def build_service_detail(
        db: Session,
        service_id: str,
    ) -> Optional[GrpcRegistryServiceRead]:
        """Build the schema-version and method detail view for one service."""
        service = db.get(DbGrpcService, service_id)
        if service is None:
            return None

        artifact_statement = (
            select(GrpcSchemaArtifact)
            .where(GrpcSchemaArtifact.grpc_service_id == service_id)
            .order_by(GrpcSchemaArtifact.version)
        )
        artifacts = list(db.execute(artifact_statement).scalars().all())

        tool_statement = select(DbTool).where(DbTool.grpc_service_id == service_id)
        tools = list(db.execute(tool_statement).scalars().all())
        tools_by_name: dict[str, DbTool] = {tool.original_name: tool for tool in tools}

        return GrpcRegistryService._service_view(
            service,
            artifacts,
            tools_by_name,
        )

    @staticmethod
    def build_schema_detail(
        db: Session,
        artifact_id: str,
    ) -> Optional[GrpcRegistrySchemaViewRead]:
        """Build one schema version with per-method tool/exposure state.

        Returns None when the artifact does not exist or its owning service is
        not visible to the caller; callers are expected to pre-validate access.
        """
        artifact = db.get(GrpcSchemaArtifact, artifact_id)
        if artifact is None:
            return None
        catalog = (artifact.source_info or {}).get("catalog", {})
        methods = GrpcRegistryService._methods_for_catalog(catalog)

        tools = list(
            db.execute(select(DbTool).where(DbTool.grpc_service_id == artifact.grpc_service_id)).scalars().all()
        )
        tool_map = {tool.original_name: tool for tool in tools}

        method_views = [
            GrpcRegistryMethodRead(
                name=method["name"],
                input_type=method["input_type"],
                output_type=method["output_type"],
                client_streaming=method["client_streaming"],
                server_streaming=method["server_streaming"],
                **GrpcRegistryService._tool_state_for(
                    tool_map, method["name"], method["client_streaming"]
                ),
            )
            for method in methods
        ]
        return GrpcRegistrySchemaViewRead(
            version=artifact.version,
            artifact_id=artifact.id,
            source_type=artifact.source_type,
            content_hash=artifact.content_hash,
            is_active=artifact.is_active,
            created_by=artifact.created_by,
            created_at=artifact.created_at,
            activated_at=artifact.activated_at,
            methods=method_views,
        )
