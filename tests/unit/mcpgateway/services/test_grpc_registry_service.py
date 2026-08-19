# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_grpc_registry_service.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Read-only gRPC registry views: services → schema versions → methods → tool state.
"""

# Standard
from datetime import datetime, timezone
import itertools

# Third-Party
from fastapi import HTTPException, Request
import pytest

# First-Party
from mcpgateway.db import APISQLTableBinding, GrpcSchemaArtifact
from mcpgateway.db import GrpcService as DbGrpcService
from mcpgateway.db import Server as DbServer
from mcpgateway.db import SQLDataSource, SQLTable
from mcpgateway.db import Tool as DbTool
from mcpgateway.routers.grpc_schema import _require_service_access, _require_sql_lineage_enabled, data_lineage
from mcpgateway.services.grpc_registry_service import GrpcRegistryService

_UNIQUE = itertools.count(1)

CATALOG = {
    "demo.Greeter": {
        "name": "demo.Greeter",
        "package": "demo",
        "methods": [
            {
                "name": "SayHello",
                "input_type": ".demo.HelloRequest",
                "output_type": ".demo.HelloReply",
                "client_streaming": False,
                "server_streaming": False,
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
                "request_example": {},
            },
            {
                "name": "Subscribe",
                "input_type": ".demo.SubRequest",
                "output_type": ".demo.SubReply",
                "client_streaming": False,
                "server_streaming": True,
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
                "request_example": {},
            },
        ],
    }
}

CLIENT_STREAMING_CATALOG = {
    "demo.Greeter": {
        "name": "demo.Greeter",
        "package": "demo",
        "methods": [
            {
                "name": "Upload",
                "input_type": ".demo.Chunk",
                "output_type": ".demo.Status",
                "client_streaming": True,
                "server_streaming": False,
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
                "request_example": {},
            },
        ],
    }
}


def _service(**overrides):
    n = next(_UNIQUE)
    defaults = {
        "name": f"demo-svc-{n}",
        "slug": f"demo-svc-{n}",
        "target": "grpc.example.com:443",
        "visibility": "private",
        "enabled": True,
        "reachable": True,
        "health_status": "unknown",
        "service_count": 1,
        "method_count": 2,
        "active_schema_hash": "hash-1",
        "schema_drift": False,
        "discovered_services": dict(CATALOG),
    }
    defaults.update(overrides)
    return DbGrpcService(**defaults)


def _artifact(service, *, version=1, active=True, catalog=None, source_type="proto"):
    return GrpcSchemaArtifact(
        grpc_service_id=service.id,
        version=version,
        source_type=source_type,
        content_hash=f"hash-{version}",
        descriptor_set=b"\x00\x01",
        source_info={"filename": "schema.protoset", "catalog": catalog if catalog is not None else dict(CATALOG)},
        is_active=active,
        created_by="admin@example.com",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        activated_at=datetime(2026, 1, 1, tzinfo=timezone.utc) if active else None,
    )


def _tool(service, tool_name, *, enabled=True, deprecated=False, reachable=True):
    return DbTool(
        original_name=tool_name,
        custom_name=tool_name,
        custom_name_slug="demo-greeter-sayhello",
        display_name="Say Hello",
        url=service.target,
        original_description="gRPC method",
        description="gRPC method",
        integration_type="gRPC",
        input_schema={"type": "object"},
        annotations={},
        created_by="system",
        visibility=service.visibility,
        grpc_service_id=service.id,
        enabled=enabled,
        deprecated=deprecated,
        reachable=reachable,
    )


def test_registry_view_builds_hierarchy(test_db):
    service = _service()
    test_db.add(service)
    test_db.flush()
    test_db.add(_artifact(service, version=1, active=False))
    test_db.add(_artifact(service, version=2, active=True))
    test_db.add(_tool(service, "demo.Greeter.SayHello"))
    test_db.add(_tool(service, "demo.Greeter.Subscribe", enabled=False))
    test_db.commit()

    view = GrpcRegistryService.build_registry_view(test_db, service_ids=[service.id])
    assert view.total_services == 1
    assert view.total_schema_versions == 2
    assert view.total_methods == 2
    assert view.total_exposed_tools == 1
    service_view = view.services[0]
    assert service_view.name.startswith("demo-svc-")
    assert service_view.method_count == 2
    assert service_view.tool_count == 2
    assert service_view.exposed_tool_count == 1
    assert [v.version for v in service_view.schema_versions] == [1, 2]
    assert service_view.schema_versions[0].is_active is False
    assert service_view.schema_versions[1].is_active is True


def test_registry_view_exposes_no_descriptor_bytes(test_db):
    service = _service()
    test_db.add(service)
    test_db.flush()
    test_db.add(_artifact(service, version=1, active=True))
    test_db.commit()

    view = GrpcRegistryService.build_registry_view(test_db)
    payload = view.model_dump()

    assert "descriptor_set" not in payload["services"][0]["schema_versions"][0]
    assert "source_info" not in payload["services"][0]["schema_versions"][0]


def test_registry_view_respects_service_id_filter(test_db):
    service_a = _service(name="svc-a", slug="svc-a")
    service_b = _service(name="svc-b", slug="svc-b")
    test_db.add_all([service_a, service_b])
    test_db.flush()
    test_db.add(_artifact(service_a, version=1, active=True))
    test_db.add(_artifact(service_b, version=1, active=True))
    test_db.commit()

    view = GrpcRegistryService.build_registry_view(test_db, service_ids=[service_a.id])

    assert view.total_services == 1
    assert view.services[0].id == service_a.id


def test_registry_view_empty_when_no_services(test_db):
    view = GrpcRegistryService.build_registry_view(test_db, service_ids=[])
    assert view.total_services == 0
    assert view.services == []
    assert view.total_schema_versions == 0


def test_service_detail_maps_methods_to_tool_state(test_db):
    service = _service()
    test_db.add(service)
    test_db.flush()
    test_db.add(_artifact(service, version=1, active=True))
    test_db.add(_tool(service, "demo.Greeter.SayHello"))
    test_db.add(_tool(service, "demo.Greeter.Subscribe", enabled=False, deprecated=True))
    test_db.commit()

    view = GrpcRegistryService.build_service_detail(test_db, service.id)

    assert view is not None
    assert view.id == service.id
    assert view.exposed_tool_count == 1
    assert len(view.schema_versions) == 1
    assert view.schema_versions[0].method_count == 2


def test_data_lineage_flattens_grpc_mcp_binding_and_table(test_db):
    service = _service(visibility="public")
    test_db.add(service)
    test_db.flush()
    tool = _tool(service, "demo.Greeter.SayHello")
    server = DbServer(name="Customer MCP", enabled=True, visibility="public")
    source = SQLDataSource(
        name="Customer DB",
        slug="customer-db",
        dialect="sqlite",
        connection_url="sqlite+pysqlite:///:memory:",
        masked_url="sqlite+pysqlite:///:memory:",
        enabled=True,
        reachable=True,
    )
    test_db.add_all([tool, server, source])
    test_db.flush()
    table = SQLTable(
        source_id=source.id,
        schema_name="main",
        schema_slug="main",
        table_name="customers",
        table_slug="customers",
        object_type="table",
        columns=[],
        primary_key=["id"],
        unique_keys=[],
        schema_hash="table-hash",
        exposed=True,
        visibility="public",
    )
    server.tools.append(tool)
    test_db.add(table)
    test_db.flush()
    binding = APISQLTableBinding(
        tool_id=tool.id,
        sql_table_id=table.id,
        access_mode="read",
        binding_type="manual",
    )
    test_db.add(binding)
    test_db.commit()

    view = GrpcRegistryService.build_data_lineage(
        test_db,
        user_email="viewer@example.com",
        token_teams=[],
        service_id=service.id,
    )

    path = next(path for path in view.paths if path.method_name == "demo.Greeter.SayHello")
    assert [stage.kind for stage in path.stages] == [
        "grpc_service",
        "grpc_method",
        "mcp_tool",
        "mcp_server",
        "data_binding",
        "sql_source",
        "sql_table",
    ]
    assert path.has_mcp_exposure is True
    assert path.has_data_binding is True
    assert path.stages[-1].label == "main.customers"
    assert path.stages[3].attributes["endpoint"] == f"/servers/{server.id}/mcp"
    assert view.summary.data_bound_tool_count == 1
    assert view.relationship_semantics.startswith("API/SQL bindings")

    limited = GrpcRegistryService.build_data_lineage(
        test_db,
        user_email="viewer@example.com",
        token_teams=[],
        service_id=service.id,
        limit=1,
    )
    assert len(limited.paths) == 1
    assert limited.summary.path_count == 2
    assert limited.truncated is True

    complete_only = GrpcRegistryService.build_data_lineage(
        test_db,
        user_email="viewer@example.com",
        token_teams=[],
        service_id=service.id,
        include_unbound=False,
    )
    assert [item.method_name for item in complete_only.paths] == ["demo.Greeter.SayHello"]

    tool.enabled = False
    test_db.commit()
    inactive_tool_view = GrpcRegistryService.build_data_lineage(
        test_db,
        user_email="viewer@example.com",
        token_teams=[],
        service_id=service.id,
    )
    inactive_path = next(path for path in inactive_tool_view.paths if path.method_name == "demo.Greeter.SayHello")
    assert inactive_path.has_mcp_exposure is False
    assert inactive_tool_view.summary.mcp_exposed_tool_count == 0

    tool.enabled = True
    test_db.commit()

    server.tools.remove(tool)
    test_db.commit()
    no_complete_path = GrpcRegistryService.build_data_lineage(
        test_db,
        user_email="viewer@example.com",
        token_teams=[],
        service_id=service.id,
        include_unbound=False,
    )
    assert no_complete_path.paths == []


def test_data_lineage_shows_missing_stages_without_leaking_private_tables(test_db):
    service = _service(visibility="public")
    test_db.add(service)
    test_db.flush()
    tool = _tool(service, "demo.Greeter.SayHello")
    source = SQLDataSource(
        name="Private DB",
        slug="private-db",
        dialect="sqlite",
        connection_url="sqlite+pysqlite:///:memory:",
        masked_url="sqlite+pysqlite:///:memory:",
        enabled=True,
        reachable=True,
    )
    test_db.add_all([tool, source])
    test_db.flush()
    table = SQLTable(
        source_id=source.id,
        schema_name="main",
        schema_slug="main",
        table_name="secret_rows",
        table_slug="secret-rows",
        object_type="table",
        columns=[],
        primary_key=["id"],
        unique_keys=[],
        schema_hash="private-table-hash",
        exposed=True,
        visibility="private",
        owner_email="owner@example.com",
    )
    test_db.add(table)
    test_db.flush()
    test_db.add(APISQLTableBinding(tool_id=tool.id, sql_table_id=table.id, access_mode="read", binding_type="manual"))
    test_db.commit()

    view = GrpcRegistryService.build_data_lineage(
        test_db,
        user_email="owner@example.com",
        token_teams=[],
        service_id=service.id,
        include_unbound=True,
    )

    path = next(path for path in view.paths if path.method_name == "demo.Greeter.SayHello")
    assert path.has_data_binding is False
    assert path.stages[4].state == "missing"
    assert path.stages[-1].label == "Data table unavailable"
    assert "secret_rows" not in view.model_dump_json()


def test_data_lineage_route_requires_grpc_and_sql_read_permissions():
    """The composite endpoint must enforce every contributing RBAC domain."""
    assert data_lineage._required_permission == "admin.grpc"  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert data_lineage.__wrapped__._required_permission == "sql.tables.read"  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert data_lineage.__wrapped__.__wrapped__._required_permission == "admin.sql_sources"  # type: ignore[attr-defined]  # pylint: disable=protected-access


def test_data_lineage_is_hidden_when_sql_feature_is_disabled(monkeypatch):
    """The composite endpoint must honor the governed SQL feature flag."""
    monkeypatch.setattr("mcpgateway.routers.grpc_schema.settings.mcpgateway_sql_api_enabled", False)

    with pytest.raises(HTTPException) as exc_info:
        _require_sql_lineage_enabled()

    assert exc_info.value.status_code == 404


def test_grpc_service_access_uses_public_only_scope_even_for_owner(test_db):
    """An owner cannot recover a private service through a public-only token."""
    service = _service(visibility="private", owner_email="owner@example.com")
    test_db.add(service)
    test_db.commit()
    request = Request({"type": "http", "method": "GET", "path": f"/admin/grpc/{service.id}", "headers": []})
    request.state.token_teams = []

    with pytest.raises(HTTPException) as exc_info:
        _require_service_access(request, {"email": "owner@example.com", "is_admin": False}, test_db, service.id)

    assert exc_info.value.status_code == 404


def test_service_detail_returns_none_for_missing_service(test_db):
    assert GrpcRegistryService.build_service_detail(test_db, "missing") is None


def test_schema_detail_rejects_artifact_from_another_service(test_db):
    """A pre-validated service ID must not authorize another service's artifact."""
    service = _service(visibility="public")
    other_service = _service(visibility="public")
    test_db.add_all([service, other_service])
    test_db.flush()
    artifact = _artifact(other_service)
    test_db.add(artifact)
    test_db.commit()

    assert GrpcRegistryService.build_schema_detail(test_db, artifact.id, service_id=service.id) is None


def test_schema_detail_lists_methods_with_exposure(test_db):
    service = _service()
    test_db.add(service)
    test_db.flush()
    artifact = _artifact(service, version=1, active=True)
    test_db.add(artifact)
    test_db.add(_tool(service, "demo.Greeter.SayHello"))
    test_db.commit()

    view = GrpcRegistryService.build_schema_detail(test_db, artifact.id)

    assert view is not None
    assert view.version == 1
    assert view.is_active is True
    assert len(view.methods) == 2
    by_name = {m.name: m for m in view.methods}
    assert by_name["demo.Greeter.SayHello"].exposed is True
    assert by_name["demo.Greeter.SayHello"].tool_enabled is True
    assert by_name["demo.Greeter.Subscribe"].exposed is False
    assert by_name["demo.Greeter.Subscribe"].tool_id is None


def test_schema_detail_marks_server_streaming_exposed(test_db):
    """Server-streaming methods backed by a live tool are still exposed."""
    service = _service()
    test_db.add(service)
    test_db.flush()
    artifact = _artifact(service, version=1, active=True)
    test_db.add(artifact)
    test_db.add(_tool(service, "demo.Greeter.Subscribe"))
    test_db.commit()

    view = GrpcRegistryService.build_schema_detail(test_db, artifact.id)
    by_name = {m.name: m for m in view.methods}
    assert by_name["demo.Greeter.Subscribe"].server_streaming is True
    assert by_name["demo.Greeter.Subscribe"].exposed is True


def test_schema_detail_marks_client_streaming_not_exposed(test_db):
    """Client-streaming methods are never exposed even with a live tool row."""
    service = _service(discovered_services=dict(CLIENT_STREAMING_CATALOG), method_count=1)
    test_db.add(service)
    test_db.flush()
    artifact = _artifact(service, version=1, active=True, catalog=CLIENT_STREAMING_CATALOG)
    test_db.add(artifact)
    test_db.add(_tool(service, "demo.Greeter.Upload"))
    test_db.commit()

    view = GrpcRegistryService.build_schema_detail(test_db, artifact.id)

    assert len(view.methods) == 1
    method = view.methods[0]
    assert method.client_streaming is True
    assert method.tool_enabled is True
    assert method.exposed is False


def test_schema_detail_returns_none_for_missing_artifact(test_db):
    assert GrpcRegistryService.build_schema_detail(test_db, "missing") is None


def test_tool_state_tracks_disabled_and_deprecated(test_db):
    service = _service()
    test_db.add(service)
    test_db.flush()
    test_db.add(_artifact(service, version=1, active=True))
    test_db.add(_tool(service, "demo.Greeter.SayHello", enabled=False, deprecated=True, reachable=False))
    test_db.commit()

    view = GrpcRegistryService.build_service_detail(test_db, service.id)

    assert view.exposed_tool_count == 0
    assert view.tool_count == 1


def test_schema_detail_tool_id_absent_when_row_missing(test_db):
    service = _service()
    test_db.add(service)
    test_db.flush()
    artifact = _artifact(service, version=1, active=True)
    test_db.add(artifact)
    test_db.commit()

    view = GrpcRegistryService.build_schema_detail(test_db, artifact.id)

    assert view.methods[0].tool_id is None
    assert view.methods[0].exposed is False
