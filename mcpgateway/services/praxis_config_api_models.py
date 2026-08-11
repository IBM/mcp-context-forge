"""Typed request and response contracts for the Praxis configuration API."""

from datetime import datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field


class PraxisApiModel(BaseModel):
    """Strict immutable API boundary model."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class TargetCreate(PraxisApiModel):
    """Create one enabled administrative target."""
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None


class TargetUpdate(PraxisApiModel):
    """Update mutable target metadata."""
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None


class AssignmentReplace(PraxisApiModel):
    """Replace a target's complete server assignment set."""
    server_ids: tuple[str, ...] = Field(max_length=1024)
    reassign: bool = False


class ReplicaCreate(PraxisApiModel):
    """Register one target-bound replica."""
    name: str = Field(min_length=1, max_length=255)


class CredentialCreate(PraxisApiModel):
    """Request a bounded machine credential lifetime."""
    expires_in_seconds: int = Field(default=3600, ge=60, le=86400)

    def expires_at(self, now: datetime) -> datetime:
        """Return the requested absolute expiration."""
        return now + timedelta(seconds=self.expires_in_seconds)


class TargetView(PraxisApiModel):
    """Redacted administrative target state."""
    id: str
    name: str
    description: str | None
    enabled: bool
    source_epoch: int
    policy_epoch: int
    fence: int
    desired_rollout_id: str | None


class AssignmentView(PraxisApiModel):
    """Canonical target assignment response."""
    target_id: str
    server_ids: tuple[str, ...]


class ReplicaView(PraxisApiModel):
    """Redacted replica lifecycle state."""
    id: str
    target_id: str
    name: str
    enabled: bool
    credential_epoch: int
    last_heartbeat_at: datetime | None


class CredentialView(PraxisApiModel):
    """One credential returned only to its provisioning caller."""
    jti: str
    token: str
    target_id: str
    replica_id: str
    credential_epoch: int
    expires_at: datetime


class RolloutView(PraxisApiModel):
    """Redacted desired rollout state."""
    rollout_id: str
    directive_id: str
    generation_id: str | None
    action: str
    status: str
    rollback_eligible: bool
    eligibility_reason: str | None
    eligibility_deadline: datetime


class ConvergenceStatus(PraxisApiModel):
    """Bounded aggregate rollout progress without replica identifiers."""
    state: str
    cohort_size: int
    prepared_replicas: int
    canary_passed_replicas: int
    active_replicas: int
    stale_replica_count: int
    generation_age_seconds: float
    convergence_ratio: float
    schema_version: str
    renderer_version: str


class TargetStatus(PraxisApiModel):
    """Target convergence status without artifact history."""
    target: TargetView
    assignments: tuple[str, ...]
    replicas: tuple[ReplicaView, ...]
    desired: RolloutView | None
    convergence: ConvergenceStatus


class DesiredResponse(PraxisApiModel):
    """Machine directive plus cursor-sensitive response identity."""
    directive_id: str
    response_etag: str
    action: str
    rollout_id: str
    generation_id: str | None
    policy_epoch: int
    status: str
    eligible: bool
    eligibility_reason: str | None
    eligibility_deadline: datetime
    freshness_deadline: datetime
    cohort_replica_ids: tuple[str, ...]
    last_report_sequence: int
    next_report_sequence: int


class ReportResponse(PraxisApiModel):
    """Current report cursor after one submission."""
    disposition: str
    directive_id: str
    response_etag: str
    last_report_sequence: int
    next_report_sequence: int


__all__ = (
    "AssignmentReplace",
    "AssignmentView",
    "CredentialCreate",
    "CredentialView",
    "ConvergenceStatus",
    "DesiredResponse",
    "ReplicaCreate",
    "ReplicaView",
    "ReportResponse",
    "RolloutView",
    "TargetCreate",
    "TargetStatus",
    "TargetUpdate",
    "TargetView",
)
