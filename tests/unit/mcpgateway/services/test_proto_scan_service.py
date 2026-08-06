# -*- coding: utf-8 -*-
"""Security and idempotency helpers for manifest-based Proto scanning."""

# Standard
from pathlib import Path
from types import SimpleNamespace

# Third-Party
import pytest

# First-Party
from mcpgateway.services.proto_scan_service import ProtoScanService
from mcpgateway.utils.grpc_validation import GrpcServiceError


def _write_manifest(path: Path, extra: str = "") -> Path:
    manifest = path / "grpc-service.yaml"
    manifest.write_text(
        "\n".join(
            [
                "service_name: catalog",
                "target: catalog.example.com:443",
                "reflection_mode: artifact",
                "proto_root: proto",
                "entry: catalog.proto",
                "visibility: private",
                extra,
            ]
        ),
        encoding="utf-8",
    )
    return manifest


def test_manifest_rejects_plaintext_metadata(tmp_path):
    manifest = _write_manifest(tmp_path, "grpc_metadata:\n  authorization: plaintext")

    with pytest.raises(GrpcServiceError, match="Unknown grpc-service.yaml fields"):
        ProtoScanService._load_manifest(manifest)  # pylint: disable=protected-access


def test_proto_root_cannot_escape_service_directory(tmp_path):
    service_dir = tmp_path / "service"
    service_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "catalog.proto").write_text('syntax = "proto3";', encoding="utf-8")
    manifest = _write_manifest(service_dir).resolve()
    data = ProtoScanService._load_manifest(manifest)  # pylint: disable=protected-access
    data["proto_root"] = "../outside"

    with pytest.raises(GrpcServiceError, match="escapes"):
        ProtoScanService._proto_tree(manifest, data, tmp_path.resolve())  # pylint: disable=protected-access


def test_artifact_hash_changes_only_with_manifest_or_proto_content(tmp_path):
    proto_root = tmp_path / "proto"
    proto_root.mkdir()
    proto = proto_root / "catalog.proto"
    proto.write_text('syntax = "proto3";', encoding="utf-8")
    manifest = _write_manifest(tmp_path)

    _first_payload, first_hash = ProtoScanService._artifact(manifest, proto_root, [proto])  # pylint: disable=protected-access
    _second_payload, second_hash = ProtoScanService._artifact(manifest, proto_root, [proto])  # pylint: disable=protected-access
    assert first_hash == second_hash

    proto.write_text('syntax = "proto3"; message Added {}', encoding="utf-8")
    _payload, changed_hash = ProtoScanService._artifact(manifest, proto_root, [proto])  # pylint: disable=protected-access
    assert changed_hash != first_hash



def test_managed_state_changes_when_environment_metadata_rotates(monkeypatch):
    monkeypatch.setenv("CATALOG_TOKEN", "rotated-token")
    manifest = {"metadata_env": {"authorization": "CATALOG_TOKEN"}}
    metadata = ProtoScanService._metadata_from_environment(manifest)  # pylint: disable=protected-access
    service = SimpleNamespace(manifest_hash="same-hash", grpc_metadata={"authorization": "previous-token"})

    assert not ProtoScanService._matches_managed_state(service, "same-hash", metadata)  # pylint: disable=protected-access

    service.grpc_metadata = {"authorization": "rotated-token"}
    assert ProtoScanService._matches_managed_state(service, "same-hash", metadata)  # pylint: disable=protected-access


def test_managed_state_changes_when_manifest_or_proto_changes():
    service = SimpleNamespace(manifest_hash="previous-hash", grpc_metadata={})

    assert not ProtoScanService._matches_managed_state(service, "new-hash", {})  # pylint: disable=protected-access
