# -*- coding: utf-8 -*-
"""Tests for versioned Proto descriptor artifacts."""

# Standard
from io import BytesIO
import zipfile

# Third-Party
from google.protobuf.descriptor_pb2 import FieldDescriptorProto, FileDescriptorProto, FileDescriptorSet
import pytest

# First-Party
from mcpgateway.services.grpc_schema_service import GrpcSchemaService
from mcpgateway.utils.grpc_validation import GrpcServiceError


def _descriptor_set() -> bytes:
    file_proto = FileDescriptorProto(name="catalog.proto", package="example.catalog", syntax="proto3")

    state = file_proto.enum_type.add(name="State")
    state.value.add(name="STATE_UNSPECIFIED", number=0)
    state.value.add(name="ACTIVE", number=1)

    request = file_proto.message_type.add(name="GetRequest")
    request.field.add(name="id", number=1, type=FieldDescriptorProto.TYPE_STRING)
    request.field.add(name="state", number=2, type=FieldDescriptorProto.TYPE_ENUM, type_name=".example.catalog.State")
    request.oneof_decl.add(name="selector")
    request.field.add(name="slug", number=3, type=FieldDescriptorProto.TYPE_STRING, oneof_index=0)
    request.field.add(name="legacy_id", number=4, type=FieldDescriptorProto.TYPE_INT64, oneof_index=0)

    node = file_proto.message_type.add(name="Node")
    node.field.add(name="name", number=1, type=FieldDescriptorProto.TYPE_STRING)
    node.field.add(name="child", number=2, type=FieldDescriptorProto.TYPE_MESSAGE, type_name=".example.catalog.Node")

    labels = node.nested_type.add(name="LabelsEntry")
    labels.options.map_entry = True
    labels.field.add(name="key", number=1, type=FieldDescriptorProto.TYPE_STRING)
    labels.field.add(name="value", number=2, type=FieldDescriptorProto.TYPE_STRING)
    node.field.add(
        name="labels",
        number=3,
        type=FieldDescriptorProto.TYPE_MESSAGE,
        type_name=".example.catalog.Node.LabelsEntry",
        label=FieldDescriptorProto.LABEL_REPEATED,
    )

    service = file_proto.service.add(name="Catalog")
    method = service.method.add(name="Get", input_type=".example.catalog.GetRequest", output_type=".example.catalog.Node")
    method.server_streaming = True
    descriptor_set = FileDescriptorSet()
    descriptor_set.file.append(file_proto)
    return descriptor_set.SerializeToString()


def test_normalize_builds_real_recursive_map_enum_and_oneof_schemas():
    normalized, catalog = GrpcSchemaService.normalize_descriptor_set(_descriptor_set())

    assert normalized
    method = catalog["example.catalog.Catalog"]["methods"][0]
    assert method["server_streaming"] is True
    assert method["input_schema"]["properties"]["state"]["enum"] == ["STATE_UNSPECIFIED", "ACTIVE"]
    assert method["input_schema"]["x-protobuf-oneof"] == {"selector": ["slug", "legacy_id"]}
    assert method["output_schema"]["properties"]["child"] == {"$ref": "#/$defs/example.catalog.Node"}
    assert method["output_schema"]["properties"]["labels"] == {"type": "object", "additionalProperties": {"type": "string"}}
    assert method["request_example"]["slug"] == ""
    assert "legacy_id" not in method["request_example"]


def test_normalize_rejects_conflicting_duplicate_file_names():
    first = FileDescriptorProto(name="duplicate.proto", package="one")
    second = FileDescriptorProto(name="duplicate.proto", package="two")
    descriptor_set = FileDescriptorSet()
    descriptor_set.file.extend([first, second])

    with pytest.raises(GrpcServiceError, match="Conflicting duplicate"):
        GrpcSchemaService.normalize_descriptor_set(descriptor_set.SerializeToString())


def test_compile_rejects_zip_traversal():
    payload = BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("../escape.proto", 'syntax = "proto3";')

    with pytest.raises(GrpcServiceError, match="Unsafe Proto ZIP entry"):
        GrpcSchemaService.compile_proto_artifact(payload.getvalue(), "schema.zip")


def test_normalize_rejects_missing_import():
    file_proto = FileDescriptorProto(name="missing.proto", dependency=["not-present.proto"])
    descriptor_set = FileDescriptorSet()
    descriptor_set.file.append(file_proto)

    with pytest.raises(GrpcServiceError, match="Invalid descriptor dependency"):
        GrpcSchemaService.normalize_descriptor_set(descriptor_set.SerializeToString())


def test_migrate_legacy_descriptors_creates_artifact_and_sets_active(test_db):
    import base64
    from mcpgateway.db import GrpcSchemaArtifact, GrpcService
    import base64
    from google.protobuf.descriptor_pb2 import FileDescriptorSet
    descriptor_set_bytes = _descriptor_set()
    fds = FileDescriptorSet()
    fds.ParseFromString(descriptor_set_bytes)
    encoded = [base64.b64encode(f.SerializeToString()).decode() for f in fds.file]
    service = GrpcService(
        name="legacy-svc",
        slug="legacy-svc",
        target="legacy.example.com:443",
        discovered_services={"_file_descriptors": encoded},
        active_artifact_id=None,
    )
    test_db.add(service)
    test_db.commit()

    artifact = GrpcSchemaService.migrate_legacy_descriptors(test_db, service)
    assert artifact is not None
    assert artifact.source_type == "legacy"
    assert artifact.is_active is True
    test_db.commit()

    test_db.refresh(service)
    assert service.active_artifact_id == artifact.id
    assert service.active_schema_hash == artifact.content_hash
    assert isinstance(service.discovered_services, dict)
    assert "example.catalog.Catalog" in service.discovered_services

    descriptors = GrpcSchemaService.descriptors_for_service(test_db, service)
    assert len(descriptors) == 1
    assert b"catalog.proto" in descriptors[0]

    artifact2 = GrpcSchemaService.descriptors_for_service(test_db, service)
    assert artifact2 == descriptors
    assert test_db.query(GrpcSchemaArtifact).filter(
        GrpcSchemaArtifact.grpc_service_id == service.id
    ).count() == 1


def _new_service(test_db, name=None):
    import uuid

    from mcpgateway.db import GrpcService

    if name is None:
        name = f"candidate-svc-{uuid.uuid4().hex[:8]}"
    service = GrpcService(name=name, slug=name, target="candidate.example.com:443")
    test_db.add(service)
    test_db.commit()
    return service


def test_import_artifact_as_candidate_sets_candidate_pointer(test_db):
    from mcpgateway.db import GrpcSchemaArtifact

    service = _new_service(test_db)
    artifact = GrpcSchemaService.import_artifact(
        test_db, service, _descriptor_set(), "candidate.protoset", created_by="system", activate=False, source_type="reflection"
    )
    test_db.commit()
    test_db.refresh(service)
    assert artifact.is_active is False
    assert service.candidate_artifact_id == artifact.id
    assert service.active_artifact_id is None
    assert test_db.query(GrpcSchemaArtifact).filter(GrpcSchemaArtifact.grpc_service_id == service.id).count() == 1


def _empty_descriptor_set() -> bytes:
    file_proto = FileDescriptorProto(name="empty.proto", package="example.empty", syntax="proto3")
    descriptor_set = FileDescriptorSet()
    descriptor_set.file.append(file_proto)
    return descriptor_set.SerializeToString()


def test_activate_artifact_refuses_empty_catalog_when_methods_exist(test_db):
    service = _new_service(test_db)
    active = GrpcSchemaService.import_artifact(
        test_db, service, _descriptor_set(), "active.protoset", created_by="system", activate=True
    )
    test_db.commit()
    test_db.refresh(service)
    assert active.is_active is True
    assert service.method_count > 0

    empty = GrpcSchemaService.import_artifact(
        test_db, service, _empty_descriptor_set(), "empty.protoset", created_by="system", activate=False
    )
    test_db.commit()
    test_db.refresh(service)
    assert service.candidate_artifact_id == empty.id

    with pytest.raises(GrpcServiceError, match="Refusing to activate empty schema"):
        GrpcSchemaService.activate_artifact(test_db, service, empty, catalog={})
    test_db.rollback()

    test_db.refresh(service)
    test_db.refresh(active)
    assert service.active_artifact_id == active.id
    assert active.is_active is True


def _variant_descriptor_set() -> bytes:
    """Same catalog as _descriptor_set but with an extra message so the hash differs."""
    base = FileDescriptorSet()
    base.ParseFromString(_descriptor_set())
    extra = base.file[0].message_type.add(name="ExtraMessage")
    extra.field.add(name="note", number=1, type=FieldDescriptorProto.TYPE_STRING)
    return base.SerializeToString()


def test_activate_artifact_promotes_candidate_and_clears_pointer(test_db):
    service = _new_service(test_db)
    active = GrpcSchemaService.import_artifact(
        test_db, service, _descriptor_set(), "active.protoset", created_by="system", activate=True
    )
    test_db.commit()
    test_db.refresh(service)
    assert active.is_active is True
    assert service.active_artifact_id == active.id

    candidate = GrpcSchemaService.import_artifact(
        test_db, service, _variant_descriptor_set(), "candidate.protoset", created_by="system", activate=False
    )
    test_db.commit()
    test_db.refresh(service)
    assert candidate.id != active.id
    assert candidate.is_active is False
    assert service.candidate_artifact_id == candidate.id

    GrpcSchemaService.activate_artifact(test_db, service, candidate, catalog=candidate.source_info["catalog"])
    test_db.commit()

    test_db.refresh(service)
    test_db.refresh(candidate)
    test_db.refresh(active)
    assert candidate.is_active is True
    assert active.is_active is False
    assert service.candidate_artifact_id is None
    assert service.active_artifact_id == candidate.id
    assert service.active_schema_hash == candidate.content_hash
