# -*- coding: utf-8 -*-
"""Runtime API schemas for secure MCP runtime deployment."""

# Standard
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

# Third-Party
from pydantic import BaseModel, ConfigDict, Field, model_validator

RuntimeBackendName = Literal["docker", "ibm_code_engine"]
RuntimeSourceType = Literal["docker", "github", "compose"]
RuntimeDeploymentStatus = Literal["pending", "pending_approval", "deploying", "running", "connected", "stopped", "error", "deleted"]
RuntimeApprovalStatus = Literal["not_required", "pending", "approved", "rejected", "expired"]


class RuntimeBackendCapabilitiesRead(BaseModel):
    """Backend capability matrix returned by runtime backends."""

    backend: RuntimeBackendName
    supports_compose: bool = False
    supports_github_build: bool = False
    supports_allowed_hosts: bool = False
    supports_readonly_fs: bool = False
    supports_custom_capabilities: bool = False
    supports_pids_limit: bool = False
    supports_network_egress_toggle: bool = True
    max_cpu: Optional[float] = None
    max_memory_gb: Optional[float] = None
    max_timeout_seconds: Optional[int] = None
    notes: List[str] = Field(default_factory=list)


class RuntimeSource(BaseModel):
    """Deployment source descriptor."""

    type: RuntimeSourceType
    image: Optional[str] = None
    repo: Optional[str] = None
    branch: str = "main"
    dockerfile: str = "Dockerfile"
    build_args: Dict[str, str] = Field(default_factory=dict)
    compose_file: Optional[str] = None
    main_service: Optional[str] = None
    push_to_registry: bool = False
    registry: Optional[str] = None

    @model_validator(mode="after")
    def validate_source(self):
        """Enforce required fields based on source type.

        Returns:
            RuntimeSource: Validated source model.

        Raises:
            ValueError: If required source fields are missing for selected type.
        """
        if self.type == "docker":
            if not self.image:
                raise ValueError("Runtime source type 'docker' requires 'image'")
        elif self.type == "github":
            if not self.repo:
                raise ValueError("Runtime source type 'github' requires 'repo'")
        elif self.type == "compose":
            if not self.compose_file:
                raise ValueError("Runtime source type 'compose' requires 'compose_file'")
            if not self.main_service:
                raise ValueError("Runtime source type 'compose' requires 'main_service'")
        return self


class RuntimeResourceLimits(BaseModel):
    """Resource limits requested for a runtime deployment."""

    cpu: Optional[str] = Field(default=None, description="CPU limit (e.g., '0.5', '1')")
    memory: Optional[str] = Field(default=None, description="Memory limit (e.g., '256m', '1g')")
    max_pids: Optional[int] = Field(default=None, ge=1)
    min_scale: Optional[int] = Field(default=None, ge=0)
    max_scale: Optional[int] = Field(default=None, ge=1)
    timeout_seconds: Optional[int] = Field(default=None, ge=1)


class RuntimeNetworkGuardrails(BaseModel):
    """Network guardrails."""

    egress_allowed: bool = True
    ingress_ports: List[int] = Field(default_factory=list)
    allowed_hosts: List[str] = Field(default_factory=list)


class RuntimeFilesystemGuardrails(BaseModel):
    """Filesystem guardrails."""

    read_only_root: bool = False
    allowed_mounts: List[str] = Field(default_factory=list)


class RuntimeCapabilitiesGuardrails(BaseModel):
    """Linux capability guardrails."""

    drop_all: bool = True
    add: List[str] = Field(default_factory=list)


class RuntimeSecurityGuardrails(BaseModel):
    """Runtime guardrails requested on deployment."""

    network: RuntimeNetworkGuardrails = Field(default_factory=RuntimeNetworkGuardrails)
    filesystem: RuntimeFilesystemGuardrails = Field(default_factory=RuntimeFilesystemGuardrails)
    capabilities: RuntimeCapabilitiesGuardrails = Field(default_factory=RuntimeCapabilitiesGuardrails)
    resources: RuntimeResourceLimits = Field(default_factory=RuntimeResourceLimits)
    seccomp: Optional[str] = None
    apparmor: Optional[str] = None


class RuntimeGuardrailProfileCreate(BaseModel):
    """Create request for custom guardrail profile."""

    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field("", max_length=500)
    recommended_backends: List[RuntimeBackendName] = Field(default_factory=list)
    config: RuntimeSecurityGuardrails = Field(default_factory=RuntimeSecurityGuardrails)


class RuntimeGuardrailProfileUpdate(BaseModel):
    """Update request for guardrail profile."""

    description: Optional[str] = Field(default=None, max_length=500)
    recommended_backends: Optional[List[RuntimeBackendName]] = None
    config: Optional[RuntimeSecurityGuardrails] = None


class RuntimeGuardrailProfileRead(BaseModel):
    """Guardrail profile response."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    recommended_backends: List[RuntimeBackendName] = Field(default_factory=list)
    config: RuntimeSecurityGuardrails = Field(default_factory=RuntimeSecurityGuardrails)
    built_in: bool = False
    created_at: datetime
    updated_at: datetime


class RuntimeGuardrailWarning(BaseModel):
    """Backend-aware warning when a guardrail cannot be enforced fully."""

    field: str
    message: str
    backend: RuntimeBackendName
    severity: Literal["info", "warning"] = "warning"


class RuntimeGuardrailCompatibilityResponse(BaseModel):
    """Compatibility report for profile vs backend."""

    profile: str
    backend: RuntimeBackendName
    compatible: bool
    warnings: List[RuntimeGuardrailWarning] = Field(default_factory=list)


class RuntimeDeployRequest(BaseModel):
    """Deploy request for runtime API."""

    name: str = Field(..., min_length=1, max_length=255)
    backend: RuntimeBackendName = "docker"
    source: Optional[RuntimeSource] = None
    catalog_server_id: Optional[str] = None
    guardrails_profile: str = "standard"
    guardrails_overrides: Optional[RuntimeSecurityGuardrails] = None
    resources: RuntimeResourceLimits = Field(default_factory=RuntimeResourceLimits)
    environment: Dict[str, str] = Field(default_factory=dict)
    register_gateway: bool = True
    gateway_name: Optional[str] = None
    gateway_transport: Optional[str] = None
    visibility: Literal["public", "team", "private"] = "public"
    team_id: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_deploy_source(self):
        """Require either explicit source or catalog id.

        Returns:
            RuntimeDeployRequest: Validated deploy request model.

        Raises:
            ValueError: If neither explicit source nor catalog server id is provided.
        """
        if not self.source and not self.catalog_server_id:
            raise ValueError("Either 'source' or 'catalog_server_id' is required")
        return self


class RuntimeRead(BaseModel):
    """Runtime deployment response model."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    backend: RuntimeBackendName
    source_type: RuntimeSourceType
    status: RuntimeDeploymentStatus
    approval_status: RuntimeApprovalStatus
    runtime_ref: Optional[str] = None
    endpoint_url: Optional[str] = None
    image: Optional[str] = None
    gateway_id: Optional[str] = None
    catalog_server_id: Optional[str] = None
    guardrails_profile: Optional[str] = None
    guardrails_warnings: List[RuntimeGuardrailWarning] = Field(default_factory=list)
    resource_limits: Dict[str, Any] = Field(default_factory=dict)
    environment: Dict[str, str] = Field(default_factory=dict)
    backend_response: Dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None
    created_by: Optional[str] = None
    approved_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class RuntimeDeployResponse(BaseModel):
    """Deploy API response."""

    runtime: RuntimeRead
    message: str


class RuntimeListResponse(BaseModel):
    """List of runtimes."""

    runtimes: List[RuntimeRead]
    total: int


class RuntimeActionResponse(BaseModel):
    """Start/stop/delete action response."""

    runtime_id: str
    status: RuntimeDeploymentStatus
    message: str


class RuntimeLogsResponse(BaseModel):
    """Runtime logs response."""

    runtime_id: str
    backend: RuntimeBackendName
    logs: List[str]


class RuntimeApprovalRead(BaseModel):
    """Approval item response."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    runtime_deployment_id: str
    status: Literal["pending", "approved", "rejected", "expired"]
    requested_by: Optional[str] = None
    reviewed_by: Optional[str] = None
    requested_reason: Optional[str] = None
    decision_reason: Optional[str] = None
    approvers: List[str] = Field(default_factory=list)
    rule_snapshot: Dict[str, Any] = Field(default_factory=dict)
    expires_at: Optional[datetime] = None
    created_at: datetime
    reviewed_at: Optional[datetime] = None


class RuntimeApprovalListResponse(BaseModel):
    """Approval list response."""

    approvals: List[RuntimeApprovalRead]
    total: int


class RuntimeApprovalDecisionRequest(BaseModel):
    """Approve/reject decision payload."""

    reason: Optional[str] = Field(default=None, max_length=1000)


class RuntimeBackendListResponse(BaseModel):
    """Runtime backend availability response."""

    backends: List[RuntimeBackendCapabilitiesRead]
