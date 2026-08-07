# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/grpc_schema_service.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Versioned gRPC descriptor artifacts and safe Proto compilation.
"""

# Standard
import base64
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
from importlib import resources
from io import BytesIO
import json
from pathlib import Path, PurePosixPath
import stat
import tempfile
from typing import Any, Iterable, Optional
import zipfile

# Third-Party
from google.protobuf import descriptor as pb_descriptor
from google.protobuf import descriptor_pool
from google.protobuf.descriptor_pb2 import FileDescriptorProto, FileDescriptorSet  # pylint: disable=no-name-in-module
from google.protobuf.message import DecodeError
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import GrpcSchemaArtifact, GrpcService
from mcpgateway.schemas import GrpcSchemaDiff
from mcpgateway.utils.grpc_validation import GrpcServiceError

_MAX_DESCRIPTOR_COUNT = 1024
_MAX_DESCRIPTOR_BYTES = 8 * 1024 * 1024
_MAX_ZIP_RATIO = 100


class GrpcSchemaService:
    """Normalize, version, compare, and activate gRPC descriptor sets."""

    @staticmethod
    def _topological_files(files: Iterable[FileDescriptorProto]) -> list[FileDescriptorProto]:
        """Order descriptors with dependencies first and reject duplicate file names."""
        by_name: dict[str, FileDescriptorProto] = {}
        for file_proto in files:
            if not file_proto.name:
                raise GrpcServiceError("Descriptor contains an unnamed file")
            previous = by_name.get(file_proto.name)
            if previous is not None and previous.SerializeToString(deterministic=True) != file_proto.SerializeToString(deterministic=True):
                raise GrpcServiceError(f"Conflicting duplicate descriptor file: {file_proto.name}")
            by_name[file_proto.name] = file_proto

        ordered: list[FileDescriptorProto] = []
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(name: str) -> None:
            """Visit one descriptor after recursively visiting its dependencies."""
            if name in visited:
                return
            if name in visiting:
                raise GrpcServiceError(f"Descriptor dependency cycle includes {name}")
            visiting.add(name)
            file_proto = by_name[name]
            for dependency in file_proto.dependency:
                if dependency in by_name:
                    visit(dependency)
            visiting.remove(name)
            visited.add(name)
            ordered.append(file_proto)

        for descriptor_name in sorted(by_name):
            visit(descriptor_name)
        return ordered

    @classmethod
    def normalize_descriptor_set(cls, payload: bytes) -> tuple[bytes, dict[str, Any]]:
        """Validate and deterministically serialize a FileDescriptorSet."""
        if not payload or len(payload) > _MAX_DESCRIPTOR_BYTES:
            raise GrpcServiceError("Descriptor set is empty or exceeds the 8 MiB limit")
        descriptor_set = FileDescriptorSet()
        try:
            descriptor_set.ParseFromString(payload)
        except DecodeError as exc:
            raise GrpcServiceError("Unable to parse FileDescriptorSet") from exc
        if not descriptor_set.file:
            raise GrpcServiceError("FileDescriptorSet contains no files")
        if len(descriptor_set.file) > _MAX_DESCRIPTOR_COUNT:
            raise GrpcServiceError("FileDescriptorSet contains too many files")

        ordered = cls._topological_files(descriptor_set.file)
        normalized = FileDescriptorSet()
        normalized.file.extend(ordered)

        pool = descriptor_pool.DescriptorPool()
        try:
            for file_proto in ordered:
                pool.Add(file_proto)
        except Exception as exc:
            raise GrpcServiceError(f"Invalid descriptor dependency or duplicate symbol: {exc}") from exc

        catalog = cls._build_catalog(pool, ordered)
        return normalized.SerializeToString(deterministic=True), catalog

    @staticmethod
    def _field_schema(field: pb_descriptor.FieldDescriptor, build_message) -> dict[str, Any]:
        """Convert a protobuf field descriptor into JSON Schema."""
        scalar_types = {
            pb_descriptor.FieldDescriptor.TYPE_DOUBLE: {"type": "number", "format": "double"},
            pb_descriptor.FieldDescriptor.TYPE_FLOAT: {"type": "number", "format": "float"},
            pb_descriptor.FieldDescriptor.TYPE_INT64: {"type": "integer", "format": "int64"},
            pb_descriptor.FieldDescriptor.TYPE_UINT64: {"type": "integer", "minimum": 0},
            pb_descriptor.FieldDescriptor.TYPE_INT32: {"type": "integer", "format": "int32"},
            pb_descriptor.FieldDescriptor.TYPE_FIXED64: {"type": "integer", "minimum": 0},
            pb_descriptor.FieldDescriptor.TYPE_FIXED32: {"type": "integer", "minimum": 0},
            pb_descriptor.FieldDescriptor.TYPE_BOOL: {"type": "boolean"},
            pb_descriptor.FieldDescriptor.TYPE_STRING: {"type": "string"},
            pb_descriptor.FieldDescriptor.TYPE_BYTES: {"type": "string", "contentEncoding": "base64"},
            pb_descriptor.FieldDescriptor.TYPE_UINT32: {"type": "integer", "minimum": 0},
            pb_descriptor.FieldDescriptor.TYPE_SFIXED32: {"type": "integer"},
            pb_descriptor.FieldDescriptor.TYPE_SFIXED64: {"type": "integer"},
            pb_descriptor.FieldDescriptor.TYPE_SINT32: {"type": "integer"},
            pb_descriptor.FieldDescriptor.TYPE_SINT64: {"type": "integer"},
        }
        if field.type == pb_descriptor.FieldDescriptor.TYPE_ENUM:
            schema: dict[str, Any] = {"type": "string", "enum": [value.name for value in field.enum_type.values]}
        elif field.type == pb_descriptor.FieldDescriptor.TYPE_MESSAGE:
            well_known = {
                "google.protobuf.Timestamp": {"type": "string", "format": "date-time"},
                "google.protobuf.Duration": {"type": "string", "pattern": r"^-?[0-9]+(?:\\.[0-9]+)?s$"},
                "google.protobuf.Any": {"type": "object", "additionalProperties": True},
                "google.protobuf.Struct": {"type": "object", "additionalProperties": True},
                "google.protobuf.Value": {},
            }
            schema = well_known.get(field.message_type.full_name, build_message(field.message_type))
        else:
            schema = dict(scalar_types.get(field.type, {"type": "string"}))

        if field.message_type is not None and field.message_type.GetOptions().map_entry:
            value_field = field.message_type.fields_by_name["value"]
            return {"type": "object", "additionalProperties": GrpcSchemaService._field_schema(value_field, build_message)}
        if field.is_repeated:
            return {"type": "array", "items": schema}
        return schema

    @classmethod
    def _message_schema(cls, root: pb_descriptor.Descriptor) -> dict[str, Any]:
        """Build recursive JSON Schema with shared definitions and oneof hints."""
        definitions: dict[str, Any] = {}
        building: set[str] = set()

        def build(message: pb_descriptor.Descriptor) -> dict[str, Any]:
            """Build or reference one message definition without infinite recursion."""
            reference = {"$ref": f"#/$defs/{message.full_name}"}
            if message.full_name in definitions or message.full_name in building:
                return reference
            building.add(message.full_name)
            schema: dict[str, Any] = {"type": "object", "properties": {}, "additionalProperties": False}
            required: list[str] = []
            oneofs: dict[str, list[str]] = defaultdict(list)
            definitions[message.full_name] = schema
            for field in message.fields:
                schema["properties"][field.name] = cls._field_schema(field, build)
                if field.is_required:
                    required.append(field.name)
                if field.containing_oneof is not None:
                    oneofs[field.containing_oneof.name].append(field.name)
            if required:
                schema["required"] = required
            if oneofs:
                schema["x-protobuf-oneof"] = oneofs
            building.remove(message.full_name)
            return reference

        build(root)
        result = dict(definitions[root.full_name])
        result["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        result["$defs"] = definitions
        return result

    @classmethod
    def _example(cls, message: pb_descriptor.Descriptor, seen: Optional[set[str]] = None) -> dict[str, Any]:
        """Generate a finite example from a protobuf message descriptor."""
        seen = set(seen or ())
        if message.full_name in seen:
            return {}
        seen.add(message.full_name)
        result: dict[str, Any] = {}
        for field in message.fields:
            if field.containing_oneof is not None and field is not field.containing_oneof.fields[0]:
                continue
            if field.type == pb_descriptor.FieldDescriptor.TYPE_MESSAGE:
                value: Any = cls._example(field.message_type, seen)
            elif field.type == pb_descriptor.FieldDescriptor.TYPE_ENUM:
                value = field.enum_type.values[0].name if field.enum_type.values else ""
            elif field.type == pb_descriptor.FieldDescriptor.TYPE_BOOL:
                value = False
            elif field.type in {
                pb_descriptor.FieldDescriptor.TYPE_DOUBLE,
                pb_descriptor.FieldDescriptor.TYPE_FLOAT,
                pb_descriptor.FieldDescriptor.TYPE_INT64,
                pb_descriptor.FieldDescriptor.TYPE_UINT64,
                pb_descriptor.FieldDescriptor.TYPE_INT32,
                pb_descriptor.FieldDescriptor.TYPE_UINT32,
            }:
                value = 0
            else:
                value = ""
            result[field.name] = [value] if field.is_repeated else value
        return result

    @classmethod
    def _build_catalog(cls, pool: descriptor_pool.DescriptorPool, files: Iterable[FileDescriptorProto]) -> dict[str, Any]:
        """Build service catalog and real input/output schemas from descriptors."""
        catalog: dict[str, Any] = {}
        for file_proto in files:
            package_prefix = f"{file_proto.package}." if file_proto.package else ""
            for service_proto in file_proto.service:
                service_name = f"{package_prefix}{service_proto.name}"
                service_desc = pool.FindServiceByName(service_name)
                methods: list[dict[str, Any]] = []
                for method in service_desc.methods:
                    methods.append(
                        {
                            "name": method.name,
                            "input_type": f".{method.input_type.full_name}",
                            "output_type": f".{method.output_type.full_name}",
                            "client_streaming": method.client_streaming,
                            "server_streaming": method.server_streaming,
                            "input_schema": cls._message_schema(method.input_type),
                            "output_schema": cls._message_schema(method.output_type),
                            "request_example": cls._example(method.input_type),
                        }
                    )
                catalog[service_name] = {"name": service_name, "package": file_proto.package, "methods": methods}
        return catalog

    @staticmethod
    def _safe_zip_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
        """Validate ZIP paths, expansion size, entry count, and compression ratio."""
        members = archive.infolist()
        if len(members) > settings.mcpgateway_proto_max_zip_entries:
            raise GrpcServiceError("Proto ZIP contains too many entries")
        expanded = 0
        safe: list[zipfile.ZipInfo] = []
        for member in members:
            path = PurePosixPath(member.filename)
            mode = member.external_attr >> 16
            if path.is_absolute() or ".." in path.parts or not path.parts or stat.S_ISLNK(mode):
                raise GrpcServiceError(f"Unsafe Proto ZIP entry: {member.filename}")
            expanded += member.file_size
            if expanded > settings.mcpgateway_proto_max_uncompressed_bytes:
                raise GrpcServiceError("Proto ZIP expanded size exceeds the configured limit")
            if member.compress_size == 0 and member.file_size > 0:
                raise GrpcServiceError("Proto ZIP contains an invalid compressed entry")
            if member.compress_size and member.file_size / member.compress_size > _MAX_ZIP_RATIO:
                raise GrpcServiceError("Proto ZIP compression ratio exceeds the safety limit")
            if not member.is_dir():
                safe.append(member)
        return safe

    @classmethod
    def compile_proto_artifact(cls, payload: bytes, filename: str) -> tuple[bytes, dict[str, Any]]:
        """Compile a .proto or safe ZIP into a normalized FileDescriptorSet."""
        if not payload or len(payload) > settings.mcpgateway_proto_max_upload_bytes:
            raise GrpcServiceError("Proto artifact is empty or exceeds the upload limit")
        with tempfile.TemporaryDirectory(prefix="contextforge-proto-") as temp_name:
            root = Path(temp_name)
            suffix = Path(filename).suffix.lower()
            if suffix == ".zip":
                with zipfile.ZipFile(BytesIO(payload)) as archive:
                    members = cls._safe_zip_members(archive)
                    for member in members:
                        destination = root.joinpath(*PurePosixPath(member.filename).parts)
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination.write_bytes(archive.read(member))
            elif suffix == ".proto":
                root.joinpath(Path(filename).name).write_bytes(payload)
            else:
                return cls.normalize_descriptor_set(payload)

            proto_files = sorted(path for path in root.rglob("*.proto") if path.is_file())
            if not proto_files:
                raise GrpcServiceError("Proto artifact contains no .proto files")
            output = root / "schema.protoset"
            try:
                # Third-Party
                from grpc_tools import protoc  # pylint: disable=import-outside-toplevel

                include_root = resources.files("grpc_tools").joinpath("_proto")
                arguments = [
                    "grpc_tools.protoc",
                    f"-I{root}",
                    f"-I{include_root}",
                    f"--descriptor_set_out={output}",
                    "--include_imports",
                    "--include_source_info",
                    *[str(path.relative_to(root)) for path in proto_files],
                ]
                result = protoc.main(arguments)
            except ImportError as exc:
                raise GrpcServiceError("grpcio-tools is required to compile .proto files") from exc
            if result != 0 or not output.exists():
                raise GrpcServiceError("Proto compilation failed; check imports and syntax")
            normalized, catalog = cls.normalize_descriptor_set(output.read_bytes())
            return normalized, catalog

    @classmethod
    def import_artifact(
        cls,
        db: Session,
        service: GrpcService,
        payload: bytes,
        filename: str,
        created_by: Optional[str],
        activate: bool = True,
        source_type: Optional[str] = None,
    ) -> GrpcSchemaArtifact:
        """Create or reuse an immutable descriptor version and optionally activate it."""
        normalized, catalog = cls.compile_proto_artifact(payload, filename)
        content_hash = hashlib.sha256(normalized).hexdigest()
        existing = db.execute(select(GrpcSchemaArtifact).where(GrpcSchemaArtifact.grpc_service_id == service.id, GrpcSchemaArtifact.content_hash == content_hash)).scalar_one_or_none()
        if existing is None:
            next_version = (db.execute(select(func.max(GrpcSchemaArtifact.version)).where(GrpcSchemaArtifact.grpc_service_id == service.id)).scalar_one_or_none() or 0) + 1
            detected_type = source_type or ("zip" if filename.lower().endswith(".zip") else "proto" if filename.lower().endswith(".proto") else "protoset")
            existing = GrpcSchemaArtifact(
                grpc_service_id=service.id,
                version=next_version,
                source_type=detected_type,
                content_hash=content_hash,
                descriptor_set=normalized,
                source_info={"filename": Path(filename).name, "catalog": catalog},
                created_by=created_by,
            )
            db.add(existing)
            db.flush()
        if source_type == "reflection":
            service.reflected_schema_hash = content_hash
        if activate:
            cls.activate_artifact(db, service, existing, catalog=catalog)
        else:
            service.candidate_artifact_id = existing.id
            service.schema_drift = bool(service.active_schema_hash and service.active_schema_hash != content_hash)
        db.commit()
        db.refresh(existing)
        return existing

    @classmethod
    def activate_artifact(
        cls,
        db: Session,
        service: GrpcService,
        artifact: GrpcSchemaArtifact,
        catalog: Optional[dict[str, Any]] = None,
    ) -> None:
        """Activate one descriptor artifact without changing tool identities."""
        if artifact.grpc_service_id != service.id:
            raise GrpcServiceError("Schema artifact belongs to another gRPC service")
        if catalog is None:
            _normalized, catalog = cls.normalize_descriptor_set(artifact.descriptor_set)
        method_count = sum(len(item.get("methods", [])) for item in catalog.values())
        if method_count == 0 and service.active_artifact_id and (service.method_count or 0) > 0:
            raise GrpcServiceError("Refusing to activate empty schema while an active schema with methods exists")
        db.execute(update(GrpcSchemaArtifact).where(GrpcSchemaArtifact.grpc_service_id == service.id).values(is_active=False, activated_at=None))
        artifact.is_active = True
        artifact.activated_at = datetime.now(timezone.utc)
        service.active_artifact_id = artifact.id
        service.active_schema_hash = artifact.content_hash
        service.candidate_artifact_id = None
        service.schema_drift = bool(service.reflected_schema_hash and service.reflected_schema_hash != artifact.content_hash)
        service.discovered_services = catalog
        service.service_count = len(catalog)
        service.method_count = method_count
        service.updated_at = datetime.now(timezone.utc)

    @classmethod
    def migrate_legacy_descriptors(cls, db: Session, service: GrpcService) -> Optional[GrpcSchemaArtifact]:
        """Convert legacy _file_descriptors JSON into a binary artifact once."""
        legacy = (service.discovered_services or {}).get("_file_descriptors", [])
        if not legacy:
            return None
        descriptor_set = FileDescriptorSet()
        try:
            for encoded in legacy:
                file_proto = descriptor_set.file.add()
                file_proto.ParseFromString(base64.b64decode(encoded, validate=True))
        except Exception as exc:
            raise GrpcServiceError("Legacy descriptor data is corrupt") from exc
        return cls.import_artifact(db, service, descriptor_set.SerializeToString(), "legacy.protoset", "system", activate=True, source_type="legacy")

    @classmethod
    def descriptors_for_service(cls, db: Session, service: GrpcService) -> list[bytes]:
        """Return dependency-ordered FileDescriptorProto payloads for invocation."""
        artifact = None
        active_artifact_id = getattr(service, "active_artifact_id", None)
        if isinstance(active_artifact_id, str) and active_artifact_id:
            artifact = db.get(GrpcSchemaArtifact, active_artifact_id)
        if artifact is None:
            artifact = cls.migrate_legacy_descriptors(db, service)
        if artifact is None:
            return []
        descriptor_bytes = getattr(artifact, "descriptor_set", None)
        if not isinstance(descriptor_bytes, bytes):
            return []
        descriptor_set = FileDescriptorSet()
        descriptor_set.ParseFromString(descriptor_bytes)
        return [file_proto.SerializeToString(deterministic=True) for file_proto in descriptor_set.file]

    @staticmethod
    def _method_fingerprints(artifact: GrpcSchemaArtifact) -> dict[str, str]:
        """Hash normalized method definitions for deterministic schema diffs."""
        catalog = (artifact.source_info or {}).get("catalog", {})
        methods: dict[str, str] = {}
        for service_name, service in catalog.items():
            for method in service.get("methods", []):
                name = f"{service_name}.{method['name']}"
                methods[name] = hashlib.sha256(json.dumps(method, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return methods

    @classmethod
    def diff(cls, left: GrpcSchemaArtifact, right: GrpcSchemaArtifact) -> GrpcSchemaDiff:
        """Compare two artifacts at service/method signature level."""
        left_catalog = (left.source_info or {}).get("catalog", {})
        right_catalog = (right.source_info or {}).get("catalog", {})
        left_methods = cls._method_fingerprints(left)
        right_methods = cls._method_fingerprints(right)
        return GrpcSchemaDiff(
            from_artifact_id=left.id,
            to_artifact_id=right.id,
            added_services=sorted(set(right_catalog) - set(left_catalog)),
            removed_services=sorted(set(left_catalog) - set(right_catalog)),
            added_methods=sorted(set(right_methods) - set(left_methods)),
            removed_methods=sorted(set(left_methods) - set(right_methods)),
            changed_methods=sorted(name for name in set(left_methods) & set(right_methods) if left_methods[name] != right_methods[name]),
        )
