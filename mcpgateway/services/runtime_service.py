# -*- coding: utf-8 -*-
# ruff: noqa: D102,D107
"""Secure runtime orchestration service."""

# Standard
from copy import deepcopy
from datetime import timedelta, timezone
import logging
from typing import Any, Dict, List, Optional, Tuple
import uuid

# Third-Party
from sqlalchemy import func, select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import RuntimeDeployment, RuntimeDeploymentApproval, RuntimeGuardrailProfile, utc_now
from mcpgateway.runtime_schemas import (
    RuntimeApprovalRead,
    RuntimeBackendCapabilitiesRead,
    RuntimeDeployRequest,
    RuntimeGuardrailCompatibilityResponse,
    RuntimeGuardrailProfileCreate,
    RuntimeGuardrailProfileRead,
    RuntimeGuardrailProfileUpdate,
    RuntimeGuardrailWarning,
    RuntimeRead,
)
from mcpgateway.runtimes import DockerRuntimeBackend, IBMCodeEngineRuntimeBackend
from mcpgateway.runtimes.base import RuntimeBackend, RuntimeBackendCapabilities, RuntimeBackendDeployRequest, RuntimeBackendError
from mcpgateway.schemas import GatewayCreate
from mcpgateway.services.catalog_service import CatalogService
from mcpgateway.services.gateway_service import GatewayService
from mcpgateway.utils.create_slug import slugify

logger = logging.getLogger(__name__)


class RuntimeService:
    """Service implementing secure runtime deployment lifecycle."""

    _BUILTIN_PROFILES: Dict[str, Dict[str, Any]] = {
        "unrestricted": {
            "description": "Full access for development environments",
            "recommended_backends": ["docker"],
            "config": {
                "network": {"egress_allowed": True, "ingress_ports": [8080], "allowed_hosts": ["*"]},
                "filesystem": {"read_only_root": False, "allowed_mounts": ["/"]},
                "capabilities": {"drop_all": False, "add": []},
                "resources": {"cpu": "2", "memory": "2g"},
                "seccomp": None,
                "apparmor": None,
            },
        },
        "standard": {
            "description": "Balanced security defaults",
            "recommended_backends": ["docker", "ibm_code_engine"],
            "config": {
                "network": {"egress_allowed": True, "ingress_ports": [8080], "allowed_hosts": []},
                "filesystem": {"read_only_root": True, "allowed_mounts": ["/data", "/cache"]},
                "capabilities": {"drop_all": True, "add": ["NET_BIND_SERVICE"]},
                "resources": {"cpu": "0.5", "memory": "512m", "max_pids": 100},
                "seccomp": "runtime/default",
                "apparmor": "mcp-standard",
            },
        },
        "restricted": {
            "description": "Minimal capabilities for untrusted workloads",
            "recommended_backends": ["docker", "ibm_code_engine"],
            "config": {
                "network": {"egress_allowed": False, "ingress_ports": [8080], "allowed_hosts": []},
                "filesystem": {"read_only_root": True, "allowed_mounts": []},
                "capabilities": {"drop_all": True, "add": []},
                "resources": {"cpu": "0.25", "memory": "256m", "max_pids": 50},
                "seccomp": "runtime/default",
                "apparmor": "mcp-restricted",
            },
        },
        "airgapped": {
            "description": "No outbound network access",
            "recommended_backends": ["docker", "ibm_code_engine"],
            "config": {
                "network": {"egress_allowed": False, "ingress_ports": [], "allowed_hosts": []},
                "filesystem": {"read_only_root": True, "allowed_mounts": []},
                "capabilities": {"drop_all": True, "add": []},
                "resources": {"cpu": "0.25", "memory": "128m"},
                "seccomp": "runtime/default",
                "apparmor": "mcp-airgapped",
            },
        },
    }

    def __init__(self):
        self.catalog_service = CatalogService()
        self.gateway_service = GatewayService()
        self.backends: Dict[str, RuntimeBackend] = {}

        if settings.runtime_docker_enabled:
            self.backends["docker"] = DockerRuntimeBackend(
                docker_binary=settings.runtime_docker_binary,
                default_network=settings.runtime_docker_network,
                allowed_registries=settings.runtime_docker_allowed_registries,
            )

        if settings.runtime_ibm_code_engine_enabled:
            self.backends["ibm_code_engine"] = IBMCodeEngineRuntimeBackend(
                ibmcloud_binary=settings.runtime_ibm_code_engine_binary,
                project_name=settings.runtime_ibm_code_engine_project,
                region=settings.runtime_ibm_code_engine_region,
                registry_secret=settings.runtime_ibm_code_engine_registry_secret,
            )

    def list_backend_capabilities(self) -> List[RuntimeBackendCapabilitiesRead]:
        """List enabled backends and their capabilities.

        Returns:
            List[RuntimeBackendCapabilitiesRead]: Backend capability payloads.
        """
        result: List[RuntimeBackendCapabilitiesRead] = []
        for backend_name, backend in self.backends.items():
            caps = backend.get_capabilities()
            result.append(self._capabilities_to_schema(backend_name, caps))
        return result

    def _get_backend(self, backend_name: str) -> RuntimeBackend:
        backend = self.backends.get(backend_name)
        if not backend:
            raise RuntimeBackendError(f"Runtime backend '{backend_name}' is not enabled")
        return backend

    async def deploy(self, request: RuntimeDeployRequest, db: Session, requested_by: Optional[str]) -> RuntimeRead:
        """Create runtime deployment, or create a pending approval request.

        Args:
            request: Runtime deployment request payload.
            db: Database session used for persistence.
            requested_by: Requester identity from auth context.

        Returns:
            RuntimeRead: Persisted runtime deployment state.

        Raises:
            RuntimeBackendError: If runtime feature, source, backend, or deployment is invalid.
        """
        if not settings.mcpgateway_runtime_enabled:
            raise RuntimeBackendError("Runtime feature is disabled")

        backend = self._get_backend(request.backend)
        source, catalog_entry = await self._resolve_source(request)
        source_type = str(source.get("type"))

        caps = backend.get_capabilities()
        self._validate_source_backend_compatibility(source_type, caps)
        self._validate_catalog_backend_compatibility(catalog_entry, request.backend)

        profile_override: Optional[str] = None
        if catalog_entry and isinstance(catalog_entry.get("guardrails_profile"), str):
            # Respect catalog guardrails profile when caller kept the default and provided no overrides.
            if request.guardrails_profile == "standard" and not request.guardrails_overrides:
                profile_override = str(catalog_entry["guardrails_profile"])

        profile_name, merged_guardrails = await self._resolve_guardrails(request, db, guardrails_profile_override=profile_override)
        guardrail_warnings = self._guardrail_warnings_for_backend(merged_guardrails, request.backend, caps)
        approval_required, rule_snapshot = self._approval_required(request, source, profile_name, catalog_entry)

        runtime = RuntimeDeployment(
            id=str(uuid.uuid4()),
            name=request.name,
            slug=slugify(request.name),
            backend=request.backend,
            source_type=source_type,
            source_config=source,
            status="pending_approval" if approval_required else "deploying",
            approval_status="pending" if approval_required else "not_required",
            resource_limits=request.resources.model_dump(exclude_none=True),
            environment=request.environment,
            guardrails_profile=profile_name,
            guardrails_config=merged_guardrails,
            guardrails_warnings=[warning.model_dump() for warning in guardrail_warnings],
            runtime_metadata={
                **request.metadata,
                "register_gateway": request.register_gateway,
                "gateway_name": request.gateway_name,
                "gateway_transport": request.gateway_transport,
                "visibility": request.visibility,
                "tags": request.tags,
                "team_id": request.team_id,
            },
            catalog_server_id=request.catalog_server_id,
            team_id=request.team_id,
            created_by=requested_by,
        )
        db.add(runtime)
        db.flush()

        if approval_required:
            requested_reason = runtime.runtime_metadata.get("requested_reason") if isinstance(runtime.runtime_metadata.get("requested_reason"), str) else None
            approval = RuntimeDeploymentApproval(
                id=str(uuid.uuid4()),
                runtime_deployment_id=runtime.id,
                status="pending",
                requested_by=requested_by,
                requested_reason=requested_reason,
                approvers=settings.runtime_approvers,
                rule_snapshot=rule_snapshot,
                expires_at=utc_now() + timedelta(hours=settings.runtime_approval_timeout_hours),
            )
            db.add(approval)
            db.flush()
            return self._to_runtime_read(runtime)

        await self._execute_deployment(runtime, backend, db)
        return self._to_runtime_read(runtime)

    async def list_runtimes(
        self,
        db: Session,
        backend: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[List[RuntimeRead], int]:
        """List runtime deployments with optional filters.

        Args:
            db: Database session used for query execution.
            backend: Optional backend filter.
            status: Optional runtime status filter.
            limit: Maximum number of records to return.
            offset: Pagination offset.

        Returns:
            Tuple[List[RuntimeRead], int]: Runtime list and total count.
        """
        stmt = select(RuntimeDeployment)
        count_stmt = select(func.count(RuntimeDeployment.id))
        if backend:
            stmt = stmt.where(RuntimeDeployment.backend == backend)
            count_stmt = count_stmt.where(RuntimeDeployment.backend == backend)
        if status:
            stmt = stmt.where(RuntimeDeployment.status == status)
            count_stmt = count_stmt.where(RuntimeDeployment.status == status)

        stmt = stmt.order_by(RuntimeDeployment.created_at.desc()).offset(offset).limit(limit)
        rows = db.execute(stmt).scalars().all()
        total = int(db.execute(count_stmt).scalar() or 0)
        return [self._to_runtime_read(row) for row in rows], total

    async def get_runtime(self, runtime_id: str, db: Session) -> RuntimeRead:
        runtime = db.execute(select(RuntimeDeployment).where(RuntimeDeployment.id == runtime_id)).scalar_one_or_none()
        if not runtime:
            raise RuntimeBackendError(f"Runtime deployment '{runtime_id}' not found")
        return self._to_runtime_read(runtime)

    async def refresh_runtime_status(self, runtime_id: str, db: Session) -> RuntimeRead:
        runtime = self._get_runtime_row(runtime_id, db)
        if not runtime.runtime_ref or runtime.status in {"pending_approval", "deleted"}:
            return self._to_runtime_read(runtime)

        backend = self._get_backend(runtime.backend)
        status = await backend.get_status(runtime.runtime_ref, runtime.backend_response or {})
        runtime.status = status.status
        runtime.endpoint_url = status.endpoint_url or runtime.endpoint_url
        runtime.backend_response = self._merge_dicts(runtime.backend_response or {}, status.backend_response or {})
        runtime.last_status_check = utc_now()
        return self._to_runtime_read(runtime)

    async def start_runtime(self, runtime_id: str, db: Session) -> RuntimeRead:
        runtime = self._get_runtime_row(runtime_id, db)
        if runtime.status == "deleted":
            raise RuntimeBackendError("Cannot start deleted runtime")
        if not runtime.runtime_ref:
            raise RuntimeBackendError("Runtime has no backend reference")
        backend = self._get_backend(runtime.backend)
        status = await backend.start(runtime.runtime_ref, runtime.backend_response or {})
        runtime.status = status.status
        runtime.backend_response = self._merge_dicts(runtime.backend_response or {}, status.backend_response or {})
        runtime.last_status_check = utc_now()
        return self._to_runtime_read(runtime)

    async def stop_runtime(self, runtime_id: str, db: Session) -> RuntimeRead:
        runtime = self._get_runtime_row(runtime_id, db)
        if runtime.status == "deleted":
            raise RuntimeBackendError("Cannot stop deleted runtime")
        if not runtime.runtime_ref:
            raise RuntimeBackendError("Runtime has no backend reference")
        backend = self._get_backend(runtime.backend)
        status = await backend.stop(runtime.runtime_ref, runtime.backend_response or {})
        runtime.status = status.status
        runtime.backend_response = self._merge_dicts(runtime.backend_response or {}, status.backend_response or {})
        runtime.last_status_check = utc_now()
        return self._to_runtime_read(runtime)

    async def delete_runtime(self, runtime_id: str, db: Session) -> RuntimeRead:
        runtime = self._get_runtime_row(runtime_id, db)
        if runtime.status != "deleted" and runtime.runtime_ref:
            backend = self._get_backend(runtime.backend)
            await backend.delete(runtime.runtime_ref, runtime.backend_response or {})
        runtime.status = "deleted"
        runtime.last_status_check = utc_now()
        return self._to_runtime_read(runtime)

    async def logs(self, runtime_id: str, db: Session, tail: int = 200) -> List[str]:
        runtime = self._get_runtime_row(runtime_id, db)
        if not runtime.runtime_ref:
            return []
        backend = self._get_backend(runtime.backend)
        return await backend.logs(runtime.runtime_ref, runtime.backend_response or {}, tail=tail)

    async def list_guardrail_profiles(self, db: Session) -> List[RuntimeGuardrailProfileRead]:
        now = utc_now()
        profiles: List[RuntimeGuardrailProfileRead] = []
        for name, value in self._BUILTIN_PROFILES.items():
            profiles.append(
                RuntimeGuardrailProfileRead(
                    id=f"builtin-{name}",
                    name=name,
                    description=str(value.get("description", "")),
                    recommended_backends=value.get("recommended_backends", []),
                    config=value.get("config", {}),
                    built_in=True,
                    created_at=now,
                    updated_at=now,
                )
            )

        rows = db.execute(select(RuntimeGuardrailProfile).order_by(RuntimeGuardrailProfile.name.asc())).scalars().all()
        profiles.extend([self._to_guardrail_profile_read(row) for row in rows])
        return profiles

    async def get_guardrail_profile(self, name: str, db: Session) -> RuntimeGuardrailProfileRead:
        builtin = self._BUILTIN_PROFILES.get(name)
        if builtin:
            now = utc_now()
            return RuntimeGuardrailProfileRead(
                id=f"builtin-{name}",
                name=name,
                description=str(builtin.get("description", "")),
                recommended_backends=builtin.get("recommended_backends", []),
                config=builtin.get("config", {}),
                built_in=True,
                created_at=now,
                updated_at=now,
            )

        row = db.execute(select(RuntimeGuardrailProfile).where(RuntimeGuardrailProfile.name == name)).scalar_one_or_none()
        if not row:
            raise RuntimeBackendError(f"Guardrail profile '{name}' not found")
        return self._to_guardrail_profile_read(row)

    async def create_guardrail_profile(self, payload: RuntimeGuardrailProfileCreate, db: Session, created_by: Optional[str]) -> RuntimeGuardrailProfileRead:
        if payload.name in self._BUILTIN_PROFILES:
            raise RuntimeBackendError(f"Cannot overwrite built-in profile '{payload.name}'")

        existing = db.execute(select(RuntimeGuardrailProfile).where(RuntimeGuardrailProfile.name == payload.name)).scalar_one_or_none()
        if existing:
            raise RuntimeBackendError(f"Guardrail profile '{payload.name}' already exists")

        row = RuntimeGuardrailProfile(
            id=str(uuid.uuid4()),
            name=payload.name,
            description=payload.description,
            recommended_backends=payload.recommended_backends,
            config=payload.config.model_dump(mode="json"),
            built_in=False,
            created_by=created_by,
        )
        db.add(row)
        db.flush()
        return self._to_guardrail_profile_read(row)

    async def update_guardrail_profile(self, name: str, payload: RuntimeGuardrailProfileUpdate, db: Session) -> RuntimeGuardrailProfileRead:
        if name in self._BUILTIN_PROFILES:
            raise RuntimeBackendError("Built-in profiles cannot be updated")

        row = db.execute(select(RuntimeGuardrailProfile).where(RuntimeGuardrailProfile.name == name)).scalar_one_or_none()
        if not row:
            raise RuntimeBackendError(f"Guardrail profile '{name}' not found")

        if payload.description is not None:
            row.description = payload.description
        if payload.recommended_backends is not None:
            row.recommended_backends = payload.recommended_backends
        if payload.config is not None:
            row.config = payload.config.model_dump(mode="json")
        row.updated_at = utc_now()
        return self._to_guardrail_profile_read(row)

    async def delete_guardrail_profile(self, name: str, db: Session) -> None:
        if name in self._BUILTIN_PROFILES:
            raise RuntimeBackendError("Built-in profiles cannot be deleted")
        row = db.execute(select(RuntimeGuardrailProfile).where(RuntimeGuardrailProfile.name == name)).scalar_one_or_none()
        if not row:
            raise RuntimeBackendError(f"Guardrail profile '{name}' not found")
        db.delete(row)

    async def guardrail_compatibility(self, profile_name: str, backend_name: str, db: Session) -> RuntimeGuardrailCompatibilityResponse:
        profile = await self.get_guardrail_profile(profile_name, db)
        backend = self._get_backend(backend_name)
        caps = backend.get_capabilities()
        warnings = self._guardrail_warnings_for_backend(profile.config.model_dump(mode="json"), backend_name, caps)
        return RuntimeGuardrailCompatibilityResponse(profile=profile_name, backend=backend_name, compatible=len(warnings) == 0, warnings=warnings)

    async def list_approvals(self, db: Session, status: Optional[str] = "pending", limit: int = 100, offset: int = 0) -> Tuple[List[RuntimeApprovalRead], int]:
        stmt = select(RuntimeDeploymentApproval)
        count_stmt = select(func.count(RuntimeDeploymentApproval.id))
        if status:
            stmt = stmt.where(RuntimeDeploymentApproval.status == status)
            count_stmt = count_stmt.where(RuntimeDeploymentApproval.status == status)
        stmt = stmt.order_by(RuntimeDeploymentApproval.created_at.desc()).offset(offset).limit(limit)
        rows = db.execute(stmt).scalars().all()
        total = int(db.execute(count_stmt).scalar() or 0)
        return [self._to_approval_read(row) for row in rows], total

    async def get_approval(self, approval_id: str, db: Session) -> RuntimeApprovalRead:
        approval = db.execute(select(RuntimeDeploymentApproval).where(RuntimeDeploymentApproval.id == approval_id)).scalar_one_or_none()
        if not approval:
            raise RuntimeBackendError(f"Approval '{approval_id}' not found")
        return self._to_approval_read(approval)

    async def approve(self, approval_id: str, db: Session, reviewer: Optional[str], reason: Optional[str]) -> RuntimeRead:
        approval = db.execute(select(RuntimeDeploymentApproval).where(RuntimeDeploymentApproval.id == approval_id)).scalar_one_or_none()
        if not approval:
            raise RuntimeBackendError(f"Approval '{approval_id}' not found")
        if approval.status != "pending":
            raise RuntimeBackendError(f"Approval '{approval_id}' is not pending")
        expires_at = approval.expires_at
        now = utc_now()
        if expires_at:
            if now.tzinfo is not None and expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            elif now.tzinfo is None and expires_at.tzinfo is not None:
                now = now.replace(tzinfo=timezone.utc)
        if expires_at and expires_at < now:
            approval.status = "expired"
            runtime = self._get_runtime_row(approval.runtime_deployment_id, db)
            runtime.approval_status = "expired"
            runtime.status = "error"
            runtime.error_message = "Approval request expired"
            raise RuntimeBackendError("Approval request expired")

        runtime = self._get_runtime_row(approval.runtime_deployment_id, db)
        backend = self._get_backend(runtime.backend)

        approval.status = "approved"
        approval.reviewed_by = reviewer
        approval.reviewed_at = utc_now()
        approval.decision_reason = reason
        runtime.approval_status = "approved"
        runtime.approved_by = reviewer
        runtime.approved_at = utc_now()
        runtime.status = "deploying"

        await self._execute_deployment(runtime, backend, db)
        return self._to_runtime_read(runtime)

    async def reject(self, approval_id: str, db: Session, reviewer: Optional[str], reason: Optional[str]) -> RuntimeRead:
        approval = db.execute(select(RuntimeDeploymentApproval).where(RuntimeDeploymentApproval.id == approval_id)).scalar_one_or_none()
        if not approval:
            raise RuntimeBackendError(f"Approval '{approval_id}' not found")
        if approval.status != "pending":
            raise RuntimeBackendError(f"Approval '{approval_id}' is not pending")

        runtime = self._get_runtime_row(approval.runtime_deployment_id, db)
        approval.status = "rejected"
        approval.reviewed_by = reviewer
        approval.reviewed_at = utc_now()
        approval.decision_reason = reason

        runtime.approval_status = "rejected"
        runtime.status = "error"
        runtime.error_message = reason or "Deployment rejected"
        return self._to_runtime_read(runtime)

    async def _execute_deployment(self, runtime: RuntimeDeployment, backend: RuntimeBackend, db: Session) -> None:
        deploy_request = RuntimeBackendDeployRequest(
            runtime_id=runtime.id,
            name=runtime.name,
            source_type=runtime.source_type,
            source=runtime.source_config,
            resources=runtime.resource_limits or {},
            environment=runtime.environment or {},
            guardrails=runtime.guardrails_config or {},
            metadata=runtime.runtime_metadata or {},
        )

        try:
            result = await backend.deploy(deploy_request)
        except RuntimeBackendError as exc:
            runtime.status = "error"
            runtime.error_message = str(exc)
            runtime.last_status_check = utc_now()
            return

        runtime.status = result.status
        runtime.runtime_ref = result.runtime_ref
        runtime.endpoint_url = result.endpoint_url
        runtime.image = result.image
        runtime.error_message = None
        runtime.last_status_check = utc_now()

        runtime.backend_response = self._merge_dicts(runtime.backend_response or {}, result.backend_response or {})
        current_warnings = runtime.guardrails_warnings or []
        result_warnings = result.warnings or []
        runtime.guardrails_warnings = current_warnings + result_warnings

        if runtime.runtime_metadata.get("register_gateway", True) and runtime.endpoint_url:
            await self._register_gateway(runtime, db)

    async def _register_gateway(self, runtime: RuntimeDeployment, db: Session) -> None:
        gateway_name = runtime.runtime_metadata.get("gateway_name") or runtime.name
        gateway_transport = runtime.runtime_metadata.get("gateway_transport") or self._infer_transport(runtime.endpoint_url or "")
        visibility = runtime.runtime_metadata.get("visibility") or "public"
        tags = runtime.runtime_metadata.get("tags") or []

        gateway_request = GatewayCreate(
            name=gateway_name,
            url=runtime.endpoint_url or "",
            description=f"Runtime deployment for {runtime.name}",
            transport=gateway_transport,
            tags=tags,
        )

        try:
            gateway = await self.gateway_service.register_gateway(
                db=db,
                gateway=gateway_request,
                created_via="runtime",
                team_id=runtime.team_id if visibility == "team" else None,
                owner_email=runtime.created_by,
                visibility=visibility,
                initialize_timeout=min(settings.httpx_admin_read_timeout, 30),
            )
            runtime.gateway_id = str(gateway.id)
            runtime.status = "connected"
        except Exception as exc:  # pragma: no cover - integration behavior depends on target server.
            logger.warning("Failed to auto-register runtime %s as gateway: %s", runtime.id, exc)
            runtime.guardrails_warnings = (runtime.guardrails_warnings or []) + [
                RuntimeGuardrailWarning(field="gateway_registration", message=f"Gateway registration failed: {exc}", backend=runtime.backend).model_dump()
            ]

    async def _resolve_source(self, request: RuntimeDeployRequest) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
        if request.source:
            return request.source.model_dump(mode="json"), None

        catalog_data = await self.catalog_service.load_catalog()
        for entry in catalog_data.get("catalog_servers", []):
            if entry.get("id") == request.catalog_server_id:
                source = entry.get("source")
                if source:
                    return source, entry
                raise RuntimeBackendError(
                    f"Catalog entry '{request.catalog_server_id}' does not include deployable source metadata. " "Add source.type/source.image or source.repo details to the catalog."
                )

        raise RuntimeBackendError(f"Catalog server '{request.catalog_server_id}' not found")

    async def _resolve_guardrails(self, request: RuntimeDeployRequest, db: Session, guardrails_profile_override: Optional[str] = None) -> Tuple[str, Dict[str, Any]]:
        profile_name = guardrails_profile_override or request.guardrails_profile
        profile = await self.get_guardrail_profile(profile_name, db)
        profile_config = profile.config.model_dump(mode="json")
        merged = deepcopy(profile_config)
        if request.guardrails_overrides:
            self._deep_merge(merged, request.guardrails_overrides.model_dump(mode="json", exclude_none=True))

        resources = request.resources.model_dump(exclude_none=True)
        if resources:
            merged.setdefault("resources", {})
            merged["resources"].update(resources)

        return profile.name, merged

    def _guardrail_warnings_for_backend(self, guardrails: Dict[str, Any], backend: str, capabilities: RuntimeBackendCapabilities) -> List[RuntimeGuardrailWarning]:
        warnings: List[RuntimeGuardrailWarning] = []
        network = guardrails.get("network", {})
        filesystem = guardrails.get("filesystem", {})
        caps = guardrails.get("capabilities", {})
        resources = guardrails.get("resources", {})

        if network.get("allowed_hosts") and not capabilities.supports_allowed_hosts:
            warnings.append(RuntimeGuardrailWarning(field="network.allowed_hosts", message="Backend ignores host-level egress allowlist", backend=backend))
        if filesystem.get("read_only_root") and not capabilities.supports_readonly_fs:
            warnings.append(RuntimeGuardrailWarning(field="filesystem.read_only_root", message="Backend does not support read-only root filesystem", backend=backend))
        if caps.get("add") and not capabilities.supports_custom_capabilities:
            warnings.append(RuntimeGuardrailWarning(field="capabilities.add", message="Backend ignores custom Linux capabilities", backend=backend))
        if resources.get("max_pids") and not capabilities.supports_pids_limit:
            warnings.append(RuntimeGuardrailWarning(field="resources.max_pids", message="Backend does not support PID limits", backend=backend))
        if guardrails.get("apparmor") and not capabilities.supports_custom_capabilities:
            warnings.append(RuntimeGuardrailWarning(field="apparmor", message="Backend enforces platform profile; custom AppArmor profile is ignored", backend=backend))
        return warnings

    def _approval_required(self, request: RuntimeDeployRequest, source: Dict[str, Any], profile_name: str, catalog_entry: Optional[Dict[str, Any]]) -> Tuple[bool, Dict[str, Any]]:
        if not settings.runtime_approval_enabled:
            return False, {}

        reasons: Dict[str, Any] = {"source_type": source.get("type"), "profile": profile_name}
        required = False

        source_type = str(source.get("type", "")).lower()
        if source_type in {s.lower() for s in settings.runtime_approval_required_source_types}:
            required = True
            reasons["source_type_triggered"] = True

        if profile_name in set(settings.runtime_approval_required_guardrails_profiles):
            required = True
            reasons["guardrails_profile_triggered"] = True

        image = source.get("image")
        if image and not self._image_allowlisted(image):
            required = True
            reasons["registry_triggered"] = True
            reasons["image"] = image

        if catalog_entry and bool(catalog_entry.get("requires_approval")):
            required = True
            reasons["catalog_requires_approval"] = True
            reasons["catalog_server_id"] = catalog_entry.get("id")

        reasons["approvers"] = settings.runtime_approvers
        return required, reasons

    def _image_allowlisted(self, image: str) -> bool:
        allowlist = settings.runtime_approval_registry_allowlist or []
        if not allowlist:
            return False
        image_lower = image.lower()
        return any(image_lower.startswith(prefix.lower()) for prefix in allowlist)

    def _validate_source_backend_compatibility(self, source_type: str, capabilities: RuntimeBackendCapabilities) -> None:
        if source_type == "compose" and not capabilities.supports_compose:
            raise RuntimeBackendError(f"Backend '{capabilities.backend}' does not support compose sources")
        if source_type == "github" and not capabilities.supports_github_build:
            raise RuntimeBackendError(f"Backend '{capabilities.backend}' does not support github build sources")

    @staticmethod
    def _validate_catalog_backend_compatibility(catalog_entry: Optional[Dict[str, Any]], backend_name: str) -> None:
        if not catalog_entry:
            return
        supported_backends = catalog_entry.get("supported_backends")
        if not isinstance(supported_backends, list):
            return
        normalized = {str(backend).strip().lower() for backend in supported_backends if str(backend).strip()}
        if normalized and backend_name.lower() not in normalized:
            entry_name = catalog_entry.get("name") or catalog_entry.get("id") or "catalog entry"
            raise RuntimeBackendError(f"Catalog entry '{entry_name}' does not support runtime backend '{backend_name}'")

    @staticmethod
    def _deep_merge(target: Dict[str, Any], source: Dict[str, Any]) -> None:
        for key, value in source.items():
            if key in target and isinstance(target[key], dict) and isinstance(value, dict):
                RuntimeService._deep_merge(target[key], value)
            else:
                target[key] = value

    @staticmethod
    def _merge_dicts(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        merged = deepcopy(base)
        RuntimeService._deep_merge(merged, override)
        return merged

    @staticmethod
    def _infer_transport(endpoint_url: str) -> str:
        endpoint = endpoint_url.lower()
        if endpoint.startswith("ws://") or endpoint.startswith("wss://"):
            return "SSE"
        if endpoint.endswith("/sse") or "/sse/" in endpoint:
            return "SSE"
        return "STREAMABLEHTTP"

    def _get_runtime_row(self, runtime_id: str, db: Session) -> RuntimeDeployment:
        runtime = db.execute(select(RuntimeDeployment).where(RuntimeDeployment.id == runtime_id)).scalar_one_or_none()
        if not runtime:
            raise RuntimeBackendError(f"Runtime deployment '{runtime_id}' not found")
        return runtime

    @staticmethod
    def _to_runtime_read(runtime: RuntimeDeployment) -> RuntimeRead:
        warning_models = [RuntimeGuardrailWarning.model_validate(item) for item in (runtime.guardrails_warnings or [])]
        return RuntimeRead(
            id=runtime.id,
            name=runtime.name,
            backend=runtime.backend,  # type: ignore[arg-type]
            source_type=runtime.source_type,  # type: ignore[arg-type]
            status=runtime.status,  # type: ignore[arg-type]
            approval_status=runtime.approval_status,  # type: ignore[arg-type]
            runtime_ref=runtime.runtime_ref,
            endpoint_url=runtime.endpoint_url,
            image=runtime.image,
            gateway_id=runtime.gateway_id,
            catalog_server_id=runtime.catalog_server_id,
            guardrails_profile=runtime.guardrails_profile,
            guardrails_warnings=warning_models,
            resource_limits=runtime.resource_limits or {},
            environment=runtime.environment or {},
            backend_response=runtime.backend_response or {},
            error_message=runtime.error_message,
            created_by=runtime.created_by,
            approved_by=runtime.approved_by,
            created_at=runtime.created_at,
            updated_at=runtime.updated_at,
        )

    @staticmethod
    def _to_approval_read(approval: RuntimeDeploymentApproval) -> RuntimeApprovalRead:
        return RuntimeApprovalRead(
            id=approval.id,
            runtime_deployment_id=approval.runtime_deployment_id,
            status=approval.status,  # type: ignore[arg-type]
            requested_by=approval.requested_by,
            reviewed_by=approval.reviewed_by,
            requested_reason=approval.requested_reason,
            decision_reason=approval.decision_reason,
            approvers=approval.approvers or [],
            rule_snapshot=approval.rule_snapshot or {},
            expires_at=approval.expires_at,
            created_at=approval.created_at,
            reviewed_at=approval.reviewed_at,
        )

    @staticmethod
    def _to_guardrail_profile_read(profile: RuntimeGuardrailProfile) -> RuntimeGuardrailProfileRead:
        return RuntimeGuardrailProfileRead(
            id=profile.id,
            name=profile.name,
            description=profile.description,
            recommended_backends=profile.recommended_backends,  # type: ignore[arg-type]
            config=profile.config,
            built_in=profile.built_in,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
        )

    @staticmethod
    def _capabilities_to_schema(backend_name: str, caps: RuntimeBackendCapabilities) -> RuntimeBackendCapabilitiesRead:
        return RuntimeBackendCapabilitiesRead(
            backend=backend_name,  # type: ignore[arg-type]
            supports_compose=caps.supports_compose,
            supports_github_build=caps.supports_github_build,
            supports_allowed_hosts=caps.supports_allowed_hosts,
            supports_readonly_fs=caps.supports_readonly_fs,
            supports_custom_capabilities=caps.supports_custom_capabilities,
            supports_pids_limit=caps.supports_pids_limit,
            supports_network_egress_toggle=caps.supports_network_egress_toggle,
            max_cpu=caps.max_cpu,
            max_memory_gb=caps.max_memory_gb,
            max_timeout_seconds=caps.max_timeout_seconds,
            notes=caps.notes,
        )
