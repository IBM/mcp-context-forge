"""Strict public contracts for versioned Praxis configuration delivery."""

from enum import StrEnum, unique

from cpex.framework.models import Config
from pydantic import Field, JsonValue

from mcpgateway.services._praxis_config_core import (
    GENERATION_ENVELOPE_SCHEMA_V1,
    MANIFEST_PATH,
    MANIFEST_SCHEMA_V1,
    MAX_ARCHIVE_BYTES,
    MAX_EXTRACTED_BYTES,
    MAX_PATH_BYTES,
    MAX_REGULAR_FILES,
    ContractVersion,
    PraxisBundleArtifact,
    PraxisBundleBuildRequest,
    PraxisCompatibilityContract,
    PraxisConfigContractError,
    PraxisContractErrorCode,
    PraxisDocumentDescriptor,
    PraxisGenerationEncryptionMetadata,
    PraxisGenerationEnvelope,
    PraxisRenderedDocument,
    PraxisRenderManifestV1,
    PraxisSourceSnapshot,
    PraxisStrictModel,
    SafeIdentifier,
    Sha256Hex,
    compute_generation_id,
    length_frame_utf8,
    utc_datetime_text,
)
from mcpgateway.services.praxis_config_archive import (
    build_praxis_bundle,
    canonical_json_bytes,
    validate_canonical_archive,
)
from mcpgateway.services.praxis_config_directives import (
    DIRECTIVE_SCHEMA_V1,
    REPORT_SCHEMA_V1,
    DirectiveAction,
    PraxisActivateDirective,
    PraxisActivationCohort,
    PraxisActiveReport,
    PraxisCanaryPassedReport,
    PraxisDirective,
    PraxisDirectiveIdentity,
    PraxisDirectiveResponse,
    PraxisDirectiveResponseInput,
    PraxisFailedReport,
    PraxisPreparedReport,
    PraxisReplicaReport,
    PraxisRetryDirective,
    PraxisRollbackDirective,
    PraxisStopDirective,
    ReplicaFailureCategory,
    ReportState,
    build_directive,
    compute_directive_id,
    compute_response_etag,
    parse_replica_report,
)
from mcpgateway.plugins.binding_compiler import RuntimeModeOverride


@unique
class PraxisSourceErrorCode(StrEnum):
    """Fixed sanitized reasons that make source state nonrepresentable."""

    TARGET_NOT_FOUND = "target_not_found"
    OWNER_PRIVATE = "owner_private"
    SCOPE_MISMATCH = "scope_mismatch"
    DANGLING_ASSOCIATION = "dangling_association"
    URL_USERINFO = "url_userinfo"
    CREDENTIAL_QUERY = "credential_query"
    AUTH_MATERIAL = "auth_material"
    OAUTH_MATERIAL = "oauth_material"
    KEY_MATERIAL = "key_material"
    SECRET_HEADER = "secret_header"
    RUNTIME_OVERRIDE = "runtime_override"
    INVALID_BINDING = "invalid_binding"
    INVALID_SOURCE = "invalid_source"


class PraxisSourceError(ValueError):
    """Sanitized source refusal that never retains rejected state."""

    __slots__ = ("code",)

    def __init__(self, code: PraxisSourceErrorCode) -> None:
        """Retain only the fixed reason code."""
        super().__init__(code.value)
        self.code = code

    def __str__(self) -> str:
        """Return a fixed operator-facing message."""
        return f"Praxis source is not representable: {self.code.value}"


class PraxisGatewaySource(PraxisStrictModel):
    """Publishable upstream gateway fields safe for a rendered bundle."""

    id: str
    name: str
    url: str
    transport: str
    passthrough_headers: tuple[str, ...] = ()
    add_headers: dict[str, str] = Field(default_factory=dict)
    remove_headers: tuple[str, ...] = ()
    capabilities: dict[str, JsonValue] = Field(default_factory=dict)


class PraxisToolSource(PraxisStrictModel):
    """Enabled tool route plus its Task 3 compiled CPEX configuration."""

    id: str
    name: str
    gateway_id: str
    headers: dict[str, str] = Field(default_factory=dict)
    compiled_config: Config


class PraxisResourceSource(PraxisStrictModel):
    """Enabled resource route associated with an assigned virtual server."""

    id: str
    name: str
    uri: str
    gateway_id: str


class PraxisPromptSource(PraxisStrictModel):
    """Enabled prompt route associated with an assigned virtual server."""

    id: str
    name: str
    gateway_id: str


class PraxisServerSource(PraxisStrictModel):
    """One assigned virtual server and its representable source graph."""

    id: str
    name: str
    scope: str
    gateways: tuple[PraxisGatewaySource, ...] = ()
    tools: tuple[PraxisToolSource, ...] = ()
    resources: tuple[PraxisResourceSource, ...] = ()
    prompts: tuple[PraxisPromptSource, ...] = ()


class PraxisConfigSourceSnapshot(PraxisStrictModel):
    """Canonical full source state consumed by the Praxis renderer."""

    target_id: str
    source_fingerprint: Sha256Hex
    servers: tuple[PraxisServerSource, ...] = ()


class PraxisSourceStatus(PraxisStrictModel):
    """Sanitized shadow-mode classification without rejected source values."""

    target_id: str
    representable: bool
    reasons: tuple[PraxisSourceErrorCode, ...] = ()
    source_fingerprint: Sha256Hex | None = None


class PraxisToolRuntimeOverrides(PraxisStrictModel):
    """Runtime mode observations bound to an exact source scope and tool."""

    scope: str
    tool_name: str
    overrides: tuple[RuntimeModeOverride, ...]


__all__ = (
    "DIRECTIVE_SCHEMA_V1",
    "GENERATION_ENVELOPE_SCHEMA_V1",
    "MANIFEST_PATH",
    "MANIFEST_SCHEMA_V1",
    "MAX_ARCHIVE_BYTES",
    "MAX_EXTRACTED_BYTES",
    "MAX_PATH_BYTES",
    "MAX_REGULAR_FILES",
    "REPORT_SCHEMA_V1",
    "ContractVersion",
    "DirectiveAction",
    "PraxisActivateDirective",
    "PraxisActivationCohort",
    "PraxisActiveReport",
    "PraxisBundleArtifact",
    "PraxisBundleBuildRequest",
    "PraxisCanaryPassedReport",
    "PraxisCompatibilityContract",
    "PraxisConfigSourceSnapshot",
    "PraxisConfigContractError",
    "PraxisContractErrorCode",
    "PraxisDirective",
    "PraxisDirectiveIdentity",
    "PraxisDirectiveResponse",
    "PraxisDirectiveResponseInput",
    "PraxisDocumentDescriptor",
    "PraxisFailedReport",
    "PraxisGatewaySource",
    "PraxisGenerationEncryptionMetadata",
    "PraxisGenerationEnvelope",
    "PraxisPreparedReport",
    "PraxisPromptSource",
    "PraxisRenderedDocument",
    "PraxisResourceSource",
    "PraxisRenderManifestV1",
    "PraxisReplicaReport",
    "PraxisRetryDirective",
    "PraxisRollbackDirective",
    "PraxisSourceSnapshot",
    "PraxisServerSource",
    "PraxisSourceError",
    "PraxisSourceErrorCode",
    "PraxisSourceStatus",
    "PraxisStopDirective",
    "PraxisToolRuntimeOverrides",
    "PraxisToolSource",
    "PraxisStrictModel",
    "ReplicaFailureCategory",
    "ReportState",
    "SafeIdentifier",
    "Sha256Hex",
    "build_directive",
    "build_praxis_bundle",
    "canonical_json_bytes",
    "compute_directive_id",
    "compute_generation_id",
    "compute_response_etag",
    "length_frame_utf8",
    "parse_replica_report",
    "utc_datetime_text",
    "validate_canonical_archive",
)
