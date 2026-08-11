# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_grpc_tool_sync_preview.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for the read-only Tool Sync Preview (GrpcRegistryService.build_sync_preview).
"""

# Standard
import json
import uuid

# Third-Party
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import GrpcSchemaArtifact, GrpcService as DbGrpcService, Tool as DbTool
from mcpgateway.services.grpc_registry_service import GrpcRegistryService
from mcpgateway.services.grpc_service import _expected_input_schema
from mcpgateway.utils.grpc_validation import GrpcServiceError

# Check if gRPC is available
try:
    # Third-Party
    import grpc  # noqa: F401

    GRPC_AVAILABLE = True
except ImportError:
    GRPC_AVAILABLE = False

# Skip all tests in this module if gRPC is not available
pytestmark = pytest.mark.skipif(not GRPC_AVAILABLE, reason="gRPC packages not installed")


def _method(
    name: str,
    input_type: str = ".testpkg.Req",
    output_type: str = ".testpkg.Resp",
    client_streaming: bool = False,
    server_streaming: bool = False,
    input_schema: dict | None = None,
    output_schema: dict | None = None,
) -> dict:
    """Build a catalog method entry in the shape produced by _build_catalog."""
    return {
        "name": name,
        "input_type": input_type,
        "output_type": output_type,
        "client_streaming": client_streaming,
        "server_streaming": server_streaming,
        "input_schema": input_schema if input_schema is not None else {"type": "object", "properties": {}},
        "output_schema": output_schema,
        "request_example": {},
    }


def _catalog(*methods: dict) -> dict:
    """Wrap method entries into the service-catalog shape."""
    return {
        "testpkg.TestService": {
            "name": "testpkg.TestService",
            "package": "testpkg",
            "methods": list(methods),
        }
    }


def _find_method(service: DbGrpcService, original_name: str) -> dict:
    """Locate a method entry inside a service's discovered catalog."""
    for svc_name, svc_desc in (service.discovered_services or {}).items():
        if svc_name.startswith("_"):
            continue
        for method in svc_desc.get("methods", []):
            if f"{svc_name}.{method.get('name', '')}" == original_name:
                return method
    raise KeyError(f"method {original_name} not in discovered catalog")


def _make_service(test_db, *, name=None, target="old-host:50051", discovered=None) -> DbGrpcService:
    name = name or f"preview-svc-{uuid.uuid4().hex[:8]}"
    service = DbGrpcService(name=name, slug=name, target=target, discovered_services=discovered or {})
    test_db.add(service)
    test_db.flush()
    return service


def _make_candidate(test_db, service: DbGrpcService, catalog: dict, *, version: int = 1) -> GrpcSchemaArtifact:
    artifact = GrpcSchemaArtifact(
        grpc_service_id=service.id,
        version=version,
        source_type="proto",
        content_hash=f"hash-{version}",
        descriptor_set=b"\0",
        source_info={"filename": "schema.proto", "catalog": catalog},
        created_by=None,
    )
    test_db.add(artifact)
    test_db.flush()
    return artifact


def _make_tool(
    test_db,
    service: DbGrpcService,
    original_name: str,
    *,
    url: str | None = None,
    input_schema: dict | None = None,
    enabled: bool = True,
    deprecated: bool = False,
    reachable: bool = True,
) -> DbTool:
    """Create an existing tool as if produced by _sync_tools_from_reflection.

    Fields that the sync always writes are derived from the service's discovered
    catalog method so the preview sees a no-change baseline. Only state that the
    sync never touches (url, enabled/deprecated/reachable) can be overridden.
    """
    method = _find_method(service, original_name)
    tool = DbTool(
        original_name=original_name,
        custom_name=original_name,
        custom_name_slug=original_name,
        display_name=original_name,
        url=url if url is not None else service.target,
        original_description=f"gRPC method {original_name}",
        description=f"gRPC method {original_name}",
        integration_type="gRPC",
        input_schema=input_schema if input_schema is not None else _expected_input_schema(method),
        output_schema=method.get("output_schema"),
        annotations={},
        created_via="grpc-schema-sync",
        grpc_service_id=service.id,
        visibility=service.visibility,
        team_id=service.team_id,
        owner_email=service.owner_email,
        enabled=enabled,
        deprecated=deprecated,
        reachable=reachable,
        version=1,
    )
    test_db.add(tool)
    test_db.flush()
    return tool


class TestToolSyncPreviewAdded:
    """新增Tool: candidate-only methods are reported as additions."""

    def test_new_method_reported_as_added(self, test_db: Session):
        service = _make_service(test_db, discovered=_catalog(_method("GetItem")))
        _make_tool(test_db, service, "testpkg.TestService.GetItem")
        candidate = _make_candidate(
            test_db,
            service,
            _catalog(_method("GetItem"), _method("CreateItem")),
        )
        test_db.commit()

        preview = GrpcRegistryService.build_sync_preview(test_db, service.id, candidate.id)

        assert preview.added_tools == ["testpkg.TestService.CreateItem"]
        assert preview.modified_tools == []
        assert preview.disabled_tools == []
        assert preview.methods_needing_reapproval == []

    def test_client_streaming_method_not_added(self, test_db: Session):
        service = _make_service(test_db, discovered=_catalog(_method("GetItem")))
        _make_tool(test_db, service, "testpkg.TestService.GetItem")
        candidate = _make_candidate(
            test_db,
            service,
            _catalog(_method("GetItem"), _method("WatchStream", client_streaming=True)),
        )
        test_db.commit()

        preview = GrpcRegistryService.build_sync_preview(test_db, service.id, candidate.id)

        assert preview.added_tools == []
        assert preview.disabled_tools == []


class TestToolSyncPreviewModified:
    """修改Tool: a would-be field update on an existing tool is reported."""

    def test_url_change_marks_modified_not_reapproval(self, test_db: Session):
        service = _make_service(test_db, discovered=_catalog(_method("GetItem")), target="new-host:50051")
        _make_tool(test_db, service, "testpkg.TestService.GetItem", url="old-host:50051")
        candidate = _make_candidate(test_db, service, _catalog(_method("GetItem")))
        test_db.commit()

        preview = GrpcRegistryService.build_sync_preview(test_db, service.id, candidate.id)

        assert preview.modified_tools == ["testpkg.TestService.GetItem"]
        assert preview.methods_needing_reapproval == []
        assert preview.added_tools == []

    def test_input_schema_change_marks_modified(self, test_db: Session):
        service = _make_service(test_db, discovered=_catalog(_method("GetItem", input_schema={"type": "object", "properties": {"id": {"type": "string"}}})))
        _make_tool(test_db, service, "testpkg.TestService.GetItem")
        candidate = _make_candidate(test_db, service, _catalog(_method("GetItem", input_schema={"type": "object", "properties": {}})))
        test_db.commit()

        preview = GrpcRegistryService.build_sync_preview(test_db, service.id, candidate.id)

        assert preview.modified_tools == ["testpkg.TestService.GetItem"]

    def test_reenable_marks_modified(self, test_db: Session):
        service = _make_service(test_db, discovered=_catalog(_method("GetItem")))
        _make_tool(test_db, service, "testpkg.TestService.GetItem", enabled=False, deprecated=True, reachable=False)
        candidate = _make_candidate(test_db, service, _catalog(_method("GetItem")))
        test_db.commit()

        preview = GrpcRegistryService.build_sync_preview(test_db, service.id, candidate.id)

        assert preview.modified_tools == ["testpkg.TestService.GetItem"]


class TestToolSyncPreviewDisabled:
    """禁用Tool: methods that vanish or become client-streaming are reported."""

    def test_missing_method_reported_disabled(self, test_db: Session):
        service = _make_service(test_db, discovered=_catalog(_method("GetItem"), _method("OldMethod")))
        _make_tool(test_db, service, "testpkg.TestService.GetItem")
        _make_tool(test_db, service, "testpkg.TestService.OldMethod")
        candidate = _make_candidate(test_db, service, _catalog(_method("GetItem")))
        test_db.commit()

        preview = GrpcRegistryService.build_sync_preview(test_db, service.id, candidate.id)

        assert preview.disabled_tools == ["testpkg.TestService.OldMethod"]
        assert preview.added_tools == []

    def test_method_becoming_client_streaming_disabled(self, test_db: Session):
        service = _make_service(test_db, discovered=_catalog(_method("Watch")))
        _make_tool(test_db, service, "testpkg.TestService.Watch")
        candidate = _make_candidate(test_db, service, _catalog(_method("Watch", client_streaming=True)))
        test_db.commit()

        preview = GrpcRegistryService.build_sync_preview(test_db, service.id, candidate.id)

        assert preview.disabled_tools == ["testpkg.TestService.Watch"]


class TestToolSyncPreviewReapproval:
    """需要重新审批Method: signature changes on methods present in both schemas."""

    def test_signature_change_marks_reapproval(self, test_db: Session):
        service = _make_service(test_db, discovered=_catalog(_method("GetItem", input_type=".testpkg.OldReq")))
        _make_tool(test_db, service, "testpkg.TestService.GetItem")
        candidate = _make_candidate(test_db, service, _catalog(_method("GetItem", input_type=".testpkg.NewReq")))
        test_db.commit()

        preview = GrpcRegistryService.build_sync_preview(test_db, service.id, candidate.id)

        assert preview.methods_needing_reapproval == ["testpkg.TestService.GetItem"]

    def test_streaming_flag_change_marks_reapproval(self, test_db: Session):
        service = _make_service(test_db, discovered=_catalog(_method("GetItem", server_streaming=False)))
        _make_tool(test_db, service, "testpkg.TestService.GetItem")
        candidate = _make_candidate(test_db, service, _catalog(_method("GetItem", server_streaming=True)))
        test_db.commit()

        preview = GrpcRegistryService.build_sync_preview(test_db, service.id, candidate.id)

        assert preview.methods_needing_reapproval == ["testpkg.TestService.GetItem"]

    def test_output_schema_change_marks_reapproval(self, test_db: Session):
        service = _make_service(test_db, discovered=_catalog(_method("GetItem", output_schema={"type": "object", "properties": {}})))
        _make_tool(test_db, service, "testpkg.TestService.GetItem")
        candidate = _make_candidate(test_db, service, _catalog(_method("GetItem", output_schema={"type": "object", "properties": {"id": {"type": "string"}}})))
        test_db.commit()

        preview = GrpcRegistryService.build_sync_preview(test_db, service.id, candidate.id)

        assert preview.methods_needing_reapproval == ["testpkg.TestService.GetItem"]

    def test_new_method_not_reapproval(self, test_db: Session):
        service = _make_service(test_db, discovered=_catalog(_method("GetItem")))
        _make_tool(test_db, service, "testpkg.TestService.GetItem")
        candidate = _make_candidate(test_db, service, _catalog(_method("GetItem"), _method("CreateItem")))
        test_db.commit()

        preview = GrpcRegistryService.build_sync_preview(test_db, service.id, candidate.id)

        assert preview.methods_needing_reapproval == []


class TestToolSyncPreviewEmptyCandidate:
    """空候选保护: an empty candidate over published tools warns instead of mass-disabling."""

    def test_empty_candidate_warns_and_plans_nothing(self, test_db: Session):
        service = _make_service(test_db, discovered=_catalog(_method("GetItem")))
        _make_tool(test_db, service, "testpkg.TestService.GetItem")
        candidate = _make_candidate(test_db, service, {})
        test_db.commit()

        preview = GrpcRegistryService.build_sync_preview(test_db, service.id, candidate.id)

        assert preview.warning is not None
        assert preview.added_tools == []
        assert preview.modified_tools == []
        assert preview.disabled_tools == []
        assert preview.methods_needing_reapproval == []

    def test_empty_candidate_no_tools_no_warning(self, test_db: Session):
        service = _make_service(test_db, discovered={})
        candidate = _make_candidate(test_db, service, {})
        test_db.commit()

        preview = GrpcRegistryService.build_sync_preview(test_db, service.id, candidate.id)

        assert preview.warning is None
        assert preview.added_tools == []


class TestToolSyncPreviewReadOnly:
    """只读性: build_sync_preview never mutates the database."""

    def test_no_database_mutation(self, test_db: Session):
        service = _make_service(test_db, discovered=_catalog(_method("GetItem"), _method("OldMethod")))
        keep = _make_tool(test_db, service, "testpkg.TestService.GetItem")
        stale = _make_tool(test_db, service, "testpkg.TestService.OldMethod")
        candidate = _make_candidate(
            test_db,
            service,
            _catalog(_method("GetItem"), _method("CreateItem", input_type=".testpkg.NewReq")),
        )
        test_db.commit()

        tools_before = test_db.query(DbTool).filter_by(grpc_service_id=service.id).count()
        artifacts_before = test_db.query(GrpcSchemaArtifact).filter_by(grpc_service_id=service.id).count()
        discovered_before = json.dumps(service.discovered_services, sort_keys=True)

        GrpcRegistryService.build_sync_preview(test_db, service.id, candidate.id)

        test_db.commit()
        test_db.refresh(keep)
        test_db.refresh(stale)

        assert test_db.query(DbTool).filter_by(grpc_service_id=service.id).count() == tools_before
        assert test_db.query(GrpcSchemaArtifact).filter_by(grpc_service_id=service.id).count() == artifacts_before
        assert json.dumps(service.discovered_services, sort_keys=True) == discovered_before
        # Existing tool rows must be untouched (still enabled, not soft-disabled).
        assert keep.enabled is True and keep.deprecated is False
        assert stale.enabled is True and stale.deprecated is False


class TestToolSyncPreviewOwnership:
    """归属校验: a candidate from another service is rejected."""

    def test_candidate_belongs_to_another_service(self, test_db: Session):
        service = _make_service(test_db, discovered=_catalog(_method("GetItem")))
        other = _make_service(test_db, name="other-svc")
        candidate = _make_candidate(test_db, other, _catalog(_method("GetItem")))
        test_db.commit()

        with pytest.raises(GrpcServiceError, match="not found"):
            GrpcRegistryService.build_sync_preview(test_db, service.id, candidate.id)

    def test_missing_service_raises(self, test_db: Session):
        candidate = _make_candidate(test_db, _make_service(test_db), _catalog(_method("GetItem")))
        test_db.commit()

        with pytest.raises(GrpcServiceError, match="not found"):
            GrpcRegistryService.build_sync_preview(test_db, "no-such-service", candidate.id)
