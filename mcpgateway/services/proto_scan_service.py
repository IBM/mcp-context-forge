# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/proto_scan_service.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Primary-worker manifest scanner for local Proto service trees.
"""

# Standard
import asyncio
from hashlib import sha256
from io import BytesIO
import logging
import os
from pathlib import Path
from typing import Any
import zipfile

# Third-Party
from sqlalchemy import or_, select
from sqlalchemy.orm import Session
import yaml

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import EmailTeam, fresh_db_session
from mcpgateway.db import GrpcService as DbGrpcService
from mcpgateway.schemas import GrpcServiceCreate, GrpcServiceUpdate
from mcpgateway.services.grpc_service import _decrypt_metadata, GrpcService
from mcpgateway.utils.grpc_validation import _validate_grpc_target, GrpcServiceError
from mcpgateway.utils.primary_worker import is_primary_worker

_MANIFEST_FIELDS = {
    "service_name",
    "target",
    "reflection_mode",
    "proto_root",
    "entry",
    "tls_cert_path",
    "tls_key_path",
    "metadata_env",
    "tags",
    "team",
    "visibility",
}
logger = logging.getLogger(__name__)


class ProtoScanService:
    """Scan only configured roots and idempotently import service manifests."""

    def __init__(self) -> None:
        """Initialize the descriptor manager and scanner lifecycle state."""
        self.grpc = GrpcService()
        self._task: asyncio.Task | None = None
        self._shutdown = asyncio.Event()

    async def start(self) -> None:
        """Start the primary-worker scan loop when explicitly enabled."""
        if not settings.mcpgateway_proto_scan_enabled or not is_primary_worker():
            return
        if self._task is None or self._task.done():
            self._shutdown.clear()
            self._task = asyncio.create_task(self._scan_loop())

    async def shutdown(self) -> None:
        """Stop the scan loop without interrupting an in-flight import."""
        self._shutdown.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _scan_loop(self) -> None:
        """Run an immediate scan, then rescan at the configured interval."""
        while not self._shutdown.is_set():
            try:
                with fresh_db_session() as db:
                    result = await self.scan(db)
                if result["errors"]:
                    logger.warning("Proto scan completed with %d manifest errors", len(result["errors"]))
            except Exception:  # pylint: disable=broad-except
                logger.exception("Proto manifest scan failed")
            try:
                await asyncio.wait_for(self._shutdown.wait(), timeout=settings.mcpgateway_proto_scan_interval)
            except asyncio.TimeoutError:
                pass

    @staticmethod
    def _resolve_roots() -> list[Path]:
        """Resolve and validate the explicitly configured scan roots."""
        roots: list[Path] = []
        for configured in settings.mcpgateway_proto_scan_roots:
            root = Path(configured).resolve()
            if not root.is_dir():
                raise GrpcServiceError(f"Configured Proto scan root is not a directory: {configured}")
            roots.append(root)
        return roots

    @staticmethod
    def _load_manifest(manifest_path: Path) -> dict[str, Any]:
        """Load one strict secret-free gRPC service manifest."""
        try:
            data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise GrpcServiceError(f"Unable to read manifest {manifest_path.name}") from exc
        if not isinstance(data, dict):
            raise GrpcServiceError("grpc-service.yaml must contain a mapping")
        unknown = set(data) - _MANIFEST_FIELDS
        if unknown:
            raise GrpcServiceError(f"Unknown grpc-service.yaml fields: {', '.join(sorted(unknown))}")
        for required in ("service_name", "target", "proto_root", "entry"):
            if not data.get(required):
                raise GrpcServiceError(f"grpc-service.yaml is missing {required}")
        if "grpc_metadata" in data or "metadata" in data:
            raise GrpcServiceError("Plaintext metadata is forbidden; use metadata_env")
        mode = data.get("reflection_mode", "auto")
        if mode not in {"auto", "reflection", "artifact"}:
            raise GrpcServiceError("reflection_mode must be auto, reflection, or artifact")
        visibility = data.get("visibility", "private")
        if visibility not in {"private", "team", "public"}:
            raise GrpcServiceError("visibility must be private, team, or public")
        return data

    @staticmethod
    def _proto_tree(manifest_path: Path, manifest: dict[str, Any], allowed_root: Path) -> tuple[Path, list[Path]]:
        """Validate a manifest's Proto root and return safe source files."""
        service_dir = manifest_path.parent.resolve()
        proto_root = service_dir.joinpath(str(manifest["proto_root"])).resolve()
        if not proto_root.is_relative_to(service_dir) or not proto_root.is_relative_to(allowed_root) or not proto_root.is_dir():
            raise GrpcServiceError("Proto root escapes its service directory or allowed scan root")
        entries = manifest["entry"] if isinstance(manifest["entry"], list) else [manifest["entry"]]
        for entry in entries:
            entry_path = proto_root.joinpath(str(entry)).resolve()
            if not entry_path.is_relative_to(proto_root) or not entry_path.is_file() or entry_path.suffix != ".proto":
                raise GrpcServiceError(f"Invalid Proto entry: {entry}")
        proto_files = sorted(path for path in proto_root.rglob("*.proto") if path.is_file() and not path.is_symlink())
        if not proto_files:
            raise GrpcServiceError("Proto root contains no .proto files")
        return proto_root, proto_files

    @staticmethod
    def _artifact(manifest_path: Path, proto_root: Path, proto_files: list[Path]) -> tuple[bytes, str]:
        """Build a deterministic ZIP payload and manifest/source content hash."""
        digest = sha256(manifest_path.read_bytes())
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for proto_file in proto_files:
                relative = proto_file.relative_to(proto_root).as_posix()
                content = proto_file.read_bytes()
                digest.update(relative.encode())
                digest.update(b"\0")
                digest.update(content)
                archive.writestr(relative, content)
        return buffer.getvalue(), digest.hexdigest()

    @staticmethod
    def _metadata_from_environment(manifest: dict[str, Any]) -> dict[str, str]:
        """Resolve metadata values through environment references only."""
        references = manifest.get("metadata_env") or {}
        if not isinstance(references, dict):
            raise GrpcServiceError("metadata_env must map metadata names to environment variable names")
        metadata: dict[str, str] = {}
        for key, env_name in references.items():
            if not isinstance(key, str) or not isinstance(env_name, str) or not env_name:
                raise GrpcServiceError("metadata_env keys and values must be non-empty strings")
            value = os.environ.get(env_name)
            if value is None:
                raise GrpcServiceError(f"Required metadata environment variable is missing: {env_name}")
            metadata[key] = value
        return metadata

    @staticmethod
    def _matches_managed_state(service: DbGrpcService | None, content_hash: str, metadata: dict[str, str]) -> bool:
        """Return whether managed files and resolved metadata are unchanged."""
        return bool(service and service.manifest_hash == content_hash and _decrypt_metadata(service.grpc_metadata or {}) == metadata)

    @staticmethod
    def _resolve_team(db: Session, value: Any) -> str | None:
        """Resolve an active team by ID or display name."""
        if value in (None, ""):
            return None
        team = db.execute(select(EmailTeam).where(or_(EmailTeam.id == str(value), EmailTeam.name == str(value)), EmailTeam.is_active.is_(True))).scalar_one_or_none()
        if team is None:
            raise GrpcServiceError("Manifest team does not exist or is inactive")
        return team.id

    async def scan(self, db: Session) -> dict[str, Any]:
        """Run one primary-worker scan and return a credential-free summary."""
        if not settings.mcpgateway_proto_scan_enabled:
            raise GrpcServiceError("Proto directory scanning is disabled")
        if not is_primary_worker():
            raise GrpcServiceError("Proto scanning may only run on the primary worker")
        roots = self._resolve_roots()
        result: dict[str, Any] = {"created": [], "updated": [], "skipped": [], "errors": []}
        for root in roots:
            for manifest_path in sorted(root.rglob("grpc-service.yaml")):
                resolved_manifest = manifest_path.resolve()
                if not resolved_manifest.is_relative_to(root) or manifest_path.is_symlink():
                    continue
                try:
                    manifest = self._load_manifest(resolved_manifest)
                    _validate_grpc_target(str(manifest["target"]))
                    proto_root, proto_files = self._proto_tree(resolved_manifest, manifest, root)
                    artifact_payload, content_hash = self._artifact(resolved_manifest, proto_root, proto_files)
                    metadata = self._metadata_from_environment(manifest)
                    team_id = self._resolve_team(db, manifest.get("team"))
                    name = str(manifest["service_name"])
                    service = db.execute(select(DbGrpcService).where(DbGrpcService.name == name)).scalar_one_or_none()
                    if service and service.manifest_path and service.manifest_path != str(resolved_manifest):
                        raise GrpcServiceError("Service name is already managed by another manifest")
                    if self._matches_managed_state(service, content_hash, metadata):
                        result["skipped"].append(name)
                        continue
                    mode = str(manifest.get("reflection_mode", "auto"))
                    if service is None:
                        created = await self.grpc.register_service(
                            db,
                            GrpcServiceCreate(
                                name=name,
                                target=str(manifest["target"]),
                                reflection_enabled=False,
                                discovery_mode=mode,
                                tls_enabled=bool(manifest.get("tls_cert_path")),
                                tls_cert_path=manifest.get("tls_cert_path"),
                                tls_key_path=manifest.get("tls_key_path"),
                                grpc_metadata=metadata,
                                tags=list(manifest.get("tags") or []),
                                team_id=team_id,
                                visibility=manifest.get("visibility", "private"),
                            ),
                            user_email="system",
                            metadata={"created_via": "proto-scan"},
                        )
                        service = db.get(DbGrpcService, created.id)
                        action = "created"
                    else:
                        await self.grpc.update_service(
                            db,
                            service.id,
                            GrpcServiceUpdate(
                                target=str(manifest["target"]),
                                reflection_enabled=mode != "artifact",
                                discovery_mode=mode,
                                tls_enabled=bool(manifest.get("tls_cert_path")),
                                tls_cert_path=manifest.get("tls_cert_path"),
                                tls_key_path=manifest.get("tls_key_path"),
                                grpc_metadata=metadata,
                                tags=list(manifest.get("tags") or []),
                                visibility=manifest.get("visibility", "private"),
                            ),
                            user_email="system",
                            metadata={"modified_via": "proto-scan"},
                        )
                        service = db.get(DbGrpcService, service.id)
                        action = "updated"
                    if service is None:
                        raise GrpcServiceError("Unable to load scanned gRPC service")
                    service.team_id = team_id
                    service.manifest_path = str(resolved_manifest)
                    service.manifest_hash = content_hash
                    service.reflection_enabled = mode != "artifact"
                    await self.grpc.import_schema(db, service.id, artifact_payload, "manifest.zip", "system", activate=True)
                    db.commit()
                    result[action].append(name)
                except Exception as exc:  # pylint: disable=broad-except
                    db.rollback()
                    result["errors"].append({"manifest": str(resolved_manifest), "error": str(exc)[:1000]})
        return result


_proto_scan_service = ProtoScanService()


def get_proto_scan_service() -> ProtoScanService:
    """Return the process-local manifest scanner singleton."""
    return _proto_scan_service
