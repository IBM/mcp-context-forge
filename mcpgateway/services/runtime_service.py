# -*- coding: utf-8 -*-
# ruff: noqa: D102,D107
"""Secure runtime orchestration service."""

# Standard
from copy import deepcopy
from datetime import timedelta, timezone
import logging
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, urlunparse
import uuid

# Third-Party
from sqlalchemy import select
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
                docker_socket=settings.runtime_docker_socket,
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
        """Resolve an enabled runtime backend by name.

        Args:
            backend_name: Runtime backend key.

        Returns:
            RuntimeBackend: Enabled runtime backend implementation.

        Raises:
            RuntimeBackendError: If the backend is not enabled.
        """
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
        endpoint_port, endpoint_path = self._resolve_endpoint_preferences(request, catalog_entry)

        runtime_metadata: Dict[str, Any] = {
            **request.metadata,
            "register_gateway": request.register_gateway,
            "gateway_name": request.gateway_name,
            "gateway_transport": request.gateway_transport,
            "visibility": request.visibility,
            "tags": request.tags,
            "team_id": request.team_id,
        }
        if endpoint_port is not None:
            runtime_metadata["endpoint_port"] = endpoint_port
        if endpoint_path:
            runtime_metadata["endpoint_path"] = endpoint_path

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
            runtime_metadata=runtime_metadata,
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
        total_query = db.query(RuntimeDeployment)
        if backend:
            stmt = stmt.where(RuntimeDeployment.backend == backend)
            total_query = total_query.filter(RuntimeDeployment.backend == backend)
        normalized_status = status.lower() if isinstance(status, str) else None
        if normalized_status and normalized_status != "all":
            stmt = stmt.where(RuntimeDeployment.status == status)
            total_query = total_query.filter(RuntimeDeployment.status == status)

        stmt = stmt.order_by(RuntimeDeployment.created_at.desc()).offset(offset).limit(limit)
        rows = db.execute(stmt).scalars().all()
        total = int(total_query.count())
        return [self._to_runtime_read(row) for row in rows], total

    async def get_runtime(self, runtime_id: str, db: Session) -> RuntimeRead:
        """Get a runtime deployment by identifier.

        Args:
            runtime_id: Runtime deployment identifier.
            db: Database session used for lookup.

        Returns:
            RuntimeRead: Runtime deployment details.

        Raises:
            RuntimeBackendError: If runtime deployment is not found.
        """
        runtime = db.execute(select(RuntimeDeployment).where(RuntimeDeployment.id == runtime_id)).scalar_one_or_none()
        if not runtime:
            raise RuntimeBackendError(f"Runtime deployment '{runtime_id}' not found")
        return self._to_runtime_read(runtime)

    async def refresh_runtime_status(self, runtime_id: str, db: Session) -> RuntimeRead:
        """Refresh and persist runtime status from backend state.

        Args:
            runtime_id: Runtime deployment identifier.
            db: Database session used for lookup and updates.

        Returns:
            RuntimeRead: Updated runtime deployment state.
        """
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
        """Start a runtime deployment in the selected backend.

        Args:
            runtime_id: Runtime deployment identifier.
            db: Database session used for lookup and updates.

        Returns:
            RuntimeRead: Updated runtime deployment state.

        Raises:
            RuntimeBackendError: If runtime cannot be started.
        """
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
        """Stop a runtime deployment in the selected backend.

        Args:
            runtime_id: Runtime deployment identifier.
            db: Database session used for lookup and updates.

        Returns:
            RuntimeRead: Updated runtime deployment state.

        Raises:
            RuntimeBackendError: If runtime cannot be stopped.
        """
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
        """Delete a runtime deployment from backend and local state.

        Args:
            runtime_id: Runtime deployment identifier.
            db: Database session used for lookup and updates.

        Returns:
            RuntimeRead: Updated runtime deployment state.
        """
        runtime = self._get_runtime_row(runtime_id, db)
        if runtime.status != "deleted" and runtime.runtime_ref:
            backend = self._get_backend(runtime.backend)
            await backend.delete(runtime.runtime_ref, runtime.backend_response or {})
        runtime.status = "deleted"
        runtime.last_status_check = utc_now()
        return self._to_runtime_read(runtime)

    async def logs(self, runtime_id: str, db: Session, tail: int = 200) -> List[str]:
        """Fetch runtime log lines from backend.

        Args:
            runtime_id: Runtime deployment identifier.
            db: Database session used for lookup.
            tail: Number of trailing log lines requested.

        Returns:
            List[str]: Runtime log lines.
        """
        runtime = self._get_runtime_row(runtime_id, db)
        if not runtime.runtime_ref:
            return []
        backend = self._get_backend(runtime.backend)
        return await backend.logs(runtime.runtime_ref, runtime.backend_response or {}, tail=tail)

    async def list_guardrail_profiles(self, db: Session) -> List[RuntimeGuardrailProfileRead]:
        """List built-in and custom guardrail profiles.

        Args:
            db: Database session used for custom profile lookup.

        Returns:
            List[RuntimeGuardrailProfileRead]: Available guardrail profiles.
        """
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
        """Get a built-in or custom guardrail profile by name.

        Args:
            name: Guardrail profile name.
            db: Database session used for custom profile lookup.

        Returns:
            RuntimeGuardrailProfileRead: Guardrail profile details.

        Raises:
            RuntimeBackendError: If profile is not found.
        """
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
        """Create a custom guardrail profile.

        Args:
            payload: Guardrail profile create payload.
            db: Database session used for persistence.
            created_by: Identity that created the profile.

        Returns:
            RuntimeGuardrailProfileRead: Created guardrail profile.

        Raises:
            RuntimeBackendError: If profile already exists or conflicts with built-ins.
        """
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
        """Update a persisted custom guardrail profile.

        Args:
            name: Guardrail profile name.
            payload: Partial update payload.
            db: Database session used for persistence.

        Returns:
            RuntimeGuardrailProfileRead: Updated guardrail profile.

        Raises:
            RuntimeBackendError: If profile is missing or built-in.
        """
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
        """Delete a persisted custom guardrail profile.

        Args:
            name: Guardrail profile name.
            db: Database session used for deletion.

        Raises:
            RuntimeBackendError: If profile is missing or built-in.
        """
        if name in self._BUILTIN_PROFILES:
            raise RuntimeBackendError("Built-in profiles cannot be deleted")
        row = db.execute(select(RuntimeGuardrailProfile).where(RuntimeGuardrailProfile.name == name)).scalar_one_or_none()
        if not row:
            raise RuntimeBackendError(f"Guardrail profile '{name}' not found")
        db.delete(row)

    async def guardrail_compatibility(self, profile_name: str, backend_name: str, db: Session) -> RuntimeGuardrailCompatibilityResponse:
        """Evaluate guardrail compatibility for a backend.

        Args:
            profile_name: Guardrail profile name.
            backend_name: Runtime backend name.
            db: Database session used for profile lookup.

        Returns:
            RuntimeGuardrailCompatibilityResponse: Compatibility result with warnings.

        Raises:
            RuntimeBackendError: If profile or backend is invalid.
        """
        profile = await self.get_guardrail_profile(profile_name, db)
        backend = self._get_backend(backend_name)
        caps = backend.get_capabilities()
        warnings = self._guardrail_warnings_for_backend(profile.config.model_dump(mode="json"), backend_name, caps)
        return RuntimeGuardrailCompatibilityResponse(profile=profile_name, backend=backend_name, compatible=len(warnings) == 0, warnings=warnings)

    async def list_approvals(self, db: Session, status: Optional[str] = "pending", limit: int = 100, offset: int = 0) -> Tuple[List[RuntimeApprovalRead], int]:
        """List runtime approval requests.

        Args:
            db: Database session used for query execution.
            status: Optional approval status filter.
            limit: Maximum number of approvals to return.
            offset: Pagination offset.

        Returns:
            Tuple[List[RuntimeApprovalRead], int]: Approval list and total count.
        """
        stmt = select(RuntimeDeploymentApproval)
        total_query = db.query(RuntimeDeploymentApproval)
        normalized_status = status.lower() if isinstance(status, str) else None
        if normalized_status and normalized_status != "all":
            stmt = stmt.where(RuntimeDeploymentApproval.status == status)
            total_query = total_query.filter(RuntimeDeploymentApproval.status == status)
        stmt = stmt.order_by(RuntimeDeploymentApproval.created_at.desc()).offset(offset).limit(limit)
        rows = db.execute(stmt).scalars().all()
        total = int(total_query.count())
        return [self._to_approval_read(row) for row in rows], total

    async def get_approval(self, approval_id: str, db: Session) -> RuntimeApprovalRead:
        """Get a runtime approval request by identifier.

        Args:
            approval_id: Runtime approval identifier.
            db: Database session used for lookup.

        Returns:
            RuntimeApprovalRead: Runtime approval details.

        Raises:
            RuntimeBackendError: If approval request is not found.
        """
        approval = db.execute(select(RuntimeDeploymentApproval).where(RuntimeDeploymentApproval.id == approval_id)).scalar_one_or_none()
        if not approval:
            raise RuntimeBackendError(f"Approval '{approval_id}' not found")
        return self._to_approval_read(approval)

    async def approve(self, approval_id: str, db: Session, reviewer: Optional[str], reason: Optional[str]) -> RuntimeRead:
        """Approve a pending runtime deployment request.

        Args:
            approval_id: Runtime approval identifier.
            db: Database session used for persistence.
            reviewer: Reviewer identity.
            reason: Optional decision reason.

        Returns:
            RuntimeRead: Updated runtime deployment state.

        Raises:
            RuntimeBackendError: If approval is invalid or expired.
        """
        approval = db.execute(
            select(RuntimeDeploymentApproval)
            .where(RuntimeDeploymentApproval.id == approval_id)
            .with_for_update()
        ).scalar_one_or_none()
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
        """Reject a pending runtime deployment request.

        Args:
            approval_id: Runtime approval identifier.
            db: Database session used for persistence.
            reviewer: Reviewer identity.
            reason: Optional decision reason.

        Returns:
            RuntimeRead: Updated runtime deployment state.

        Raises:
            RuntimeBackendError: If approval is invalid.
        """
        approval = db.execute(
            select(RuntimeDeploymentApproval)
            .where(RuntimeDeploymentApproval.id == approval_id)
            .with_for_update()
        ).scalar_one_or_none()
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
        """Execute deployment on backend and persist runtime outcome.

        Args:
            runtime: Runtime deployment row.
            backend: Runtime backend implementation.
            db: Database session used for side effects.
        """
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
        """Register a successful runtime endpoint as a gateway entry.

        Args:
            runtime: Runtime deployment row.
            db: Database session used for gateway registration.
        """
        gateway_name = runtime.runtime_metadata.get("gateway_name") or runtime.name
        endpoint_port = self._normalize_endpoint_port(runtime.runtime_metadata.get("endpoint_port"))
        endpoint_path = self._normalize_endpoint_path(runtime.runtime_metadata.get("endpoint_path"))
        resolved_endpoint_url = runtime.endpoint_url or ""
        if not resolved_endpoint_url and endpoint_port:
            container_name = (runtime.backend_response or {}).get("container_name")
            if container_name:
                resolved_endpoint_url = f"http://{container_name}:{endpoint_port}"
        elif resolved_endpoint_url and endpoint_port:
            resolved_endpoint_url = self._set_url_port(resolved_endpoint_url, endpoint_port)

        transport_hint_url = self._set_url_path(resolved_endpoint_url, endpoint_path) if endpoint_path else resolved_endpoint_url
        gateway_transport = runtime.runtime_metadata.get("gateway_transport") or self._infer_transport(transport_hint_url or resolved_endpoint_url)
        visibility = runtime.runtime_metadata.get("visibility") or "public"
        tags = runtime.runtime_metadata.get("tags") or []
        candidate_urls = self._candidate_gateway_urls(resolved_endpoint_url, gateway_transport, preferred_path=endpoint_path)
        last_error: Optional[Exception] = None

        for candidate_url in candidate_urls:
            gateway_request = GatewayCreate(
                name=gateway_name,
                url=candidate_url,
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
                runtime.endpoint_url = candidate_url
                return
            except Exception as exc:  # pragma: no cover - integration behavior depends on target server.
                last_error = exc
                logger.warning(
                    "Failed to auto-register runtime %s as gateway using %s: %s",
                    runtime.id,
                    candidate_url,
                    exc,
                )

        if last_error:
            runtime.guardrails_warnings = (runtime.guardrails_warnings or []) + [
                RuntimeGuardrailWarning(
                    field="gateway_registration",
                    message=f"Gateway registration failed: {last_error}",
                    backend=runtime.backend,
                ).model_dump()
            ]

    async def _resolve_source(self, request: RuntimeDeployRequest) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
        """Resolve deploy source from request or catalog metadata.

        Args:
            request: Runtime deployment request.

        Returns:
            Tuple[Dict[str, Any], Optional[Dict[str, Any]]]: Source payload and optional catalog entry.

        Raises:
            RuntimeBackendError: If catalog entry is missing or not deployable.
        """
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
        """Resolve effective guardrail profile and merged configuration.

        Args:
            request: Runtime deployment request.
            db: Database session used for profile lookup.
            guardrails_profile_override: Optional profile override.

        Returns:
            Tuple[str, Dict[str, Any]]: Effective profile name and merged guardrail config.

        Raises:
            RuntimeBackendError: If guardrail profile lookup fails.
        """
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
        """Compute backend-specific guardrail compatibility warnings.

        Args:
            guardrails: Effective guardrail configuration.
            backend: Runtime backend name.
            capabilities: Backend capability matrix.

        Returns:
            List[RuntimeGuardrailWarning]: Non-fatal compatibility warnings.
        """
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
        """Evaluate whether deployment must enter approval workflow.

        Args:
            request: Runtime deployment request.
            source: Resolved source payload.
            profile_name: Effective guardrail profile name.
            catalog_entry: Optional catalog entry metadata.

        Returns:
            Tuple[bool, Dict[str, Any]]: Required flag and rule snapshot details.
        """
        if not settings.runtime_approval_enabled:
            return False, {}

        reasons: Dict[str, Any] = {"source_type": source.get("type"), "profile": profile_name, "requested_backend": request.backend}
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
        """Check whether image reference matches approval allowlist prefixes.

        Args:
            image: Container image reference.

        Returns:
            bool: True when image prefix is allowlisted.
        """
        allowlist = settings.runtime_approval_registry_allowlist or []
        if not allowlist:
            return False
        image_lower = image.lower()
        return any(image_lower.startswith(prefix.lower()) for prefix in allowlist)

    def _validate_source_backend_compatibility(self, source_type: str, capabilities: RuntimeBackendCapabilities) -> None:
        """Validate source type is supported by selected backend.

        Args:
            source_type: Runtime source type.
            capabilities: Backend capability matrix.

        Raises:
            RuntimeBackendError: If source type is unsupported by backend.
        """
        if source_type == "compose" and not capabilities.supports_compose:
            raise RuntimeBackendError(f"Backend '{capabilities.backend}' does not support compose sources")
        if source_type == "github" and not capabilities.supports_github_build:
            raise RuntimeBackendError(f"Backend '{capabilities.backend}' does not support github build sources")

    @staticmethod
    def _validate_catalog_backend_compatibility(catalog_entry: Optional[Dict[str, Any]], backend_name: str) -> None:
        """Validate catalog entry backend support constraints.

        Args:
            catalog_entry: Optional catalog entry metadata.
            backend_name: Requested runtime backend name.

        Raises:
            RuntimeBackendError: If catalog entry disallows the requested backend.
        """
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
        """Deep-merge source dictionary into target dictionary.

        Args:
            target: Mutable merge target.
            source: Merge source values.
        """
        for key, value in source.items():
            if key in target and isinstance(target[key], dict) and isinstance(value, dict):
                RuntimeService._deep_merge(target[key], value)
            else:
                target[key] = value

    @staticmethod
    def _merge_dicts(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """Create deep-merged dictionary from base and override payloads.

        Args:
            base: Base dictionary.
            override: Override dictionary.

        Returns:
            Dict[str, Any]: Merged dictionary.
        """
        merged = deepcopy(base)
        RuntimeService._deep_merge(merged, override)
        return merged

    @staticmethod
    def _infer_transport(endpoint_url: str) -> str:
        """Infer gateway transport type from endpoint URL pattern.

        Args:
            endpoint_url: Runtime endpoint URL.

        Returns:
            str: Inferred transport identifier.
        """
        endpoint = endpoint_url.lower()
        if endpoint.startswith("ws://") or endpoint.startswith("wss://"):
            return "SSE"
        if endpoint.endswith("/sse") or "/sse/" in endpoint:
            return "SSE"
        return "STREAMABLEHTTP"

    @staticmethod
    def _normalize_endpoint_port(raw_value: Any) -> Optional[int]:
        """Normalize endpoint port value to an integer within valid TCP range.

        Args:
            raw_value: Raw endpoint port value.

        Returns:
            Optional[int]: Normalized endpoint port or ``None`` when invalid/missing.
        """
        if raw_value is None or isinstance(raw_value, bool):
            return None
        if isinstance(raw_value, int):
            port = raw_value
        elif isinstance(raw_value, str) and raw_value.strip().isdigit():
            port = int(raw_value.strip())
        else:
            return None
        return port if 1 <= port <= 65535 else None

    @staticmethod
    def _normalize_endpoint_path(raw_value: Any) -> Optional[str]:
        """Normalize endpoint path to a slash-prefixed path segment.

        Args:
            raw_value: Raw endpoint path value.

        Returns:
            Optional[str]: Normalized endpoint path, or ``None`` when missing/invalid.
        """
        if raw_value is None:
            return None
        path = str(raw_value).strip()
        if not path:
            return None
        if "://" in path or "?" in path or "#" in path:
            return None
        if not path.startswith("/"):
            path = f"/{path}"
        if len(path) > 1 and path.endswith("/"):
            path = path.rstrip("/")
        return path

    @staticmethod
    def _set_url_port(endpoint_url: str, port: int) -> str:
        """Return a URL with an overridden port while preserving other components.

        Args:
            endpoint_url: Base endpoint URL.
            port: Desired endpoint port.

        Returns:
            str: URL with updated port, or original URL if parsing fails.
        """
        parsed = urlparse(endpoint_url)
        if not parsed.scheme or not parsed.hostname:
            return endpoint_url
        host = parsed.hostname
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        auth_part = ""
        if parsed.username:
            auth_part = parsed.username
            if parsed.password:
                auth_part = f"{auth_part}:{parsed.password}"
            auth_part = f"{auth_part}@"
        return urlunparse(parsed._replace(netloc=f"{auth_part}{host}:{port}"))

    @staticmethod
    def _set_url_path(endpoint_url: str, path: Optional[str]) -> str:
        """Return a URL with an explicit path override.

        Args:
            endpoint_url: Base endpoint URL.
            path: Desired endpoint path.

        Returns:
            str: URL with updated path.
        """
        normalized_path = RuntimeService._normalize_endpoint_path(path)
        if not normalized_path:
            return endpoint_url
        parsed = urlparse(endpoint_url)
        return urlunparse(parsed._replace(path=normalized_path))

    def _resolve_endpoint_preferences(self, request: RuntimeDeployRequest, catalog_entry: Optional[Dict[str, Any]]) -> Tuple[Optional[int], Optional[str]]:
        """Resolve endpoint port/path preferences from request metadata and catalog defaults.

        Args:
            request: Runtime deployment request.
            catalog_entry: Optional catalog entry metadata.

        Returns:
            Tuple[Optional[int], Optional[str]]: Normalized endpoint port and path preferences.
        """
        metadata = request.metadata or {}
        catalog_runtime = catalog_entry.get("runtime", {}) if isinstance(catalog_entry, dict) else {}
        if not isinstance(catalog_runtime, dict):
            catalog_runtime = {}

        endpoint_port = (
            self._normalize_endpoint_port(request.endpoint_port)
            or self._normalize_endpoint_port(metadata.get("endpoint_port"))
            or self._normalize_endpoint_port(catalog_runtime.get("endpoint_port"))
        )
        endpoint_path = (
            self._normalize_endpoint_path(request.endpoint_path)
            or self._normalize_endpoint_path(metadata.get("endpoint_path"))
            or self._normalize_endpoint_path(catalog_runtime.get("endpoint_path"))
        )
        return endpoint_port, endpoint_path

    @staticmethod
    def _append_path(endpoint_url: str, suffix: str) -> str:
        """Append a path suffix to a URL while preserving query/fragment parts.

        Args:
            endpoint_url: Base endpoint URL.
            suffix: Path suffix (for example ``/http``).

        Returns:
            str: URL with appended suffix.
        """
        parsed = urlparse(endpoint_url)
        if not suffix.startswith("/"):
            suffix = f"/{suffix}"
        base_path = parsed.path.rstrip("/")
        merged_path = f"{base_path}{suffix}" if base_path else suffix
        if not merged_path.startswith("/"):
            merged_path = f"/{merged_path}"
        return urlunparse(parsed._replace(path=merged_path))

    @staticmethod
    def _candidate_gateway_urls(endpoint_url: str, transport: str, preferred_path: Optional[str] = None) -> List[str]:
        """Build candidate URLs for gateway auto-registration.

        Args:
            endpoint_url: Runtime-reported endpoint URL.
            transport: Requested or inferred gateway transport.
            preferred_path: Optional preferred path to try first.

        Returns:
            List[str]: Ordered deduplicated candidate URLs.
        """
        if not endpoint_url:
            return []
        parsed = urlparse(endpoint_url)
        has_explicit_path = bool(parsed.path and parsed.path not in {"", "/"})

        candidates: List[str] = []
        normalized_preferred_path = RuntimeService._normalize_endpoint_path(preferred_path)
        if normalized_preferred_path:
            preferred_url = RuntimeService._set_url_path(endpoint_url, normalized_preferred_path)
            if preferred_url not in candidates:
                candidates.append(preferred_url)
        if has_explicit_path:
            if endpoint_url not in candidates:
                candidates.append(endpoint_url)
            return candidates

        normalized_transport = str(transport or "").upper()
        if normalized_transport == "SSE":
            suffixes = ["/sse"]
        elif normalized_transport == "STREAMABLEHTTP":
            suffixes = ["/http", "/mcp"]
        else:
            suffixes = ["/http", "/mcp", "/sse"]

        for suffix in suffixes:
            candidate = RuntimeService._append_path(endpoint_url, suffix)
            if candidate not in candidates:
                candidates.append(candidate)
        if endpoint_url not in candidates:
            candidates.append(endpoint_url)
        return candidates

    def _get_runtime_row(self, runtime_id: str, db: Session) -> RuntimeDeployment:
        """Load runtime deployment row by identifier.

        Args:
            runtime_id: Runtime deployment identifier.
            db: Database session used for lookup.

        Returns:
            RuntimeDeployment: Runtime deployment row.

        Raises:
            RuntimeBackendError: If runtime deployment is not found.
        """
        runtime = db.execute(select(RuntimeDeployment).where(RuntimeDeployment.id == runtime_id)).scalar_one_or_none()
        if not runtime:
            raise RuntimeBackendError(f"Runtime deployment '{runtime_id}' not found")
        return runtime

    @staticmethod
    def _to_runtime_read(runtime: RuntimeDeployment) -> RuntimeRead:
        """Convert runtime ORM row into API response schema.

        Args:
            runtime: Runtime deployment ORM row.

        Returns:
            RuntimeRead: Runtime response schema.
        """
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
        """Convert approval ORM row into API response schema.

        Args:
            approval: Runtime approval ORM row.

        Returns:
            RuntimeApprovalRead: Approval response schema.
        """
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
        """Convert guardrail profile ORM row into API response schema.

        Args:
            profile: Guardrail profile ORM row.

        Returns:
            RuntimeGuardrailProfileRead: Guardrail profile response schema.
        """
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
        """Convert backend capabilities dataclass into API response schema.

        Args:
            backend_name: Runtime backend name.
            caps: Runtime backend capability matrix.

        Returns:
            RuntimeBackendCapabilitiesRead: Backend capability response schema.
        """
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
