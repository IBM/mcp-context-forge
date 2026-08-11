# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/praxis_config_directives.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Immutable Praxis rollout directive, cohort, cursor, and report contracts.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum, unique
import hashlib
from typing import Annotated, Final, Literal, assert_never

from pydantic import AwareDatetime, Field, TypeAdapter, ValidationError, field_serializer, field_validator, model_validator

from mcpgateway.services._praxis_config_core import PraxisConfigContractError, PraxisContractErrorCode, PraxisStrictModel, SafeIdentifier, Sha256Hex, length_frame_utf8, utc_datetime_text

DIRECTIVE_SCHEMA_V1: Final = "praxis-directive/v1"
REPORT_SCHEMA_V1: Final = "praxis-replica-report/v1"


@unique
class DirectiveAction(StrEnum):
    """Server-issued action variants understood by a launcher."""

    ACTIVATE = "activate"
    RETRY = "retry"
    ROLLBACK = "rollback"
    STOP = "stop"


@unique
class ReportState(StrEnum):
    """Ordered launcher observations accepted for one stable directive."""

    PREPARED = "prepared"
    CANARY_PASSED = "canary_passed"
    ACTIVE = "active"
    FAILED = "failed"


@unique
class ReplicaFailureCategory(StrEnum):
    """Sanitized launcher failure categories safe for reports."""

    SPAWN = "spawn"
    EARLY_EXIT = "early_exit"
    CONFIG_VALIDATION = "config_validation"
    LISTENER = "listener"
    POLICY_CANARY = "policy_canary"
    TIMEOUT = "timeout"


class PraxisDirectiveIdentity(PraxisStrictModel):
    """Exact fields in the stable directive-ID preimage."""

    target_id: SafeIdentifier
    rollout_id: SafeIdentifier
    policy_epoch: int = Field(ge=0)
    action: DirectiveAction
    generation_id: Sha256Hex | None
    eligibility_deadline: AwareDatetime

    @field_validator("eligibility_deadline")
    @classmethod
    def validate_deadline(cls, value: datetime) -> datetime:
        """Require and normalize a UTC-aware eligibility deadline."""
        utc_datetime_text(value)
        return value.astimezone(timezone.utc)

    @field_serializer("eligibility_deadline", when_used="json")
    def serialize_deadline(self, value: datetime) -> str:
        """Serialize the deadline in canonical UTC RFC 3339 form."""
        return utc_datetime_text(value)

    @model_validator(mode="after")
    def validate_generation_action(self) -> PraxisDirectiveIdentity:
        """Require a generation for content actions and forbid one for stop."""
        match self.action:
            case DirectiveAction.ACTIVATE | DirectiveAction.RETRY | DirectiveAction.ROLLBACK:
                if self.generation_id is None:
                    raise PraxisConfigContractError(PraxisContractErrorCode.INVALID_CANONICAL_VALUE, "generation action requires a generation")
            case DirectiveAction.STOP:
                if self.generation_id is not None:
                    raise PraxisConfigContractError(PraxisContractErrorCode.INVALID_CANONICAL_VALUE, "stop action cannot reference a generation")
            case unreachable:
                assert_never(unreachable)
        return self


def compute_directive_id(identity: PraxisDirectiveIdentity) -> str:
    """Hash the exact stable directive identity preimage."""
    fields = (
        identity.target_id,
        identity.rollout_id,
        str(identity.policy_epoch),
        identity.action.value,
        identity.generation_id or "",
        utc_datetime_text(identity.eligibility_deadline),
    )
    return hashlib.sha256(length_frame_utf8(fields)).hexdigest()


class _PraxisDirectiveBase(PraxisStrictModel):
    """Fields shared by each explicit directive variant."""

    directive_schema: Literal["praxis-directive/v1"] = DIRECTIVE_SCHEMA_V1
    target_id: SafeIdentifier
    rollout_id: SafeIdentifier
    directive_id: Sha256Hex
    policy_epoch: int = Field(ge=0)
    eligibility_deadline: AwareDatetime

    @field_validator("eligibility_deadline")
    @classmethod
    def validate_deadline(cls, value: datetime) -> datetime:
        """Require the deadline to round-trip as UTC text."""
        utc_datetime_text(value)
        return value.astimezone(timezone.utc)

    @field_serializer("eligibility_deadline", when_used="json")
    def serialize_deadline(self, value: datetime) -> str:
        """Serialize the deadline as canonical UTC text."""
        return utc_datetime_text(value)

    @model_validator(mode="after")
    def validate_directive_id(self) -> _PraxisDirectiveBase:
        """Recompute the directive identity from its canonical fields."""
        identity = PraxisDirectiveIdentity.model_validate(self.model_dump(include={"target_id", "rollout_id", "policy_epoch", "action", "generation_id", "eligibility_deadline"}))
        if self.directive_id != compute_directive_id(identity):
            raise PraxisConfigContractError(PraxisContractErrorCode.INVALID_CANONICAL_VALUE, "directive identity does not match directive fields")
        return self


class PraxisActivateDirective(_PraxisDirectiveBase):
    """Activate one immutable generation."""

    action: Literal[DirectiveAction.ACTIVATE] = DirectiveAction.ACTIVATE
    generation_id: Sha256Hex


class PraxisRetryDirective(_PraxisDirectiveBase):
    """Retry one immutable generation under a fresh rollout."""

    action: Literal[DirectiveAction.RETRY] = DirectiveAction.RETRY
    generation_id: Sha256Hex


class PraxisRollbackDirective(_PraxisDirectiveBase):
    """Activate an eligible predecessor under a fresh rollback rollout."""

    action: Literal[DirectiveAction.ROLLBACK] = DirectiveAction.ROLLBACK
    generation_id: Sha256Hex


class PraxisStopDirective(_PraxisDirectiveBase):
    """Stop Praxis without referencing a generation."""

    action: Literal[DirectiveAction.STOP] = DirectiveAction.STOP
    generation_id: None = None


PraxisDirective = Annotated[PraxisActivateDirective | PraxisRetryDirective | PraxisRollbackDirective | PraxisStopDirective, Field(discriminator="action")]


def build_directive(identity: PraxisDirectiveIdentity) -> PraxisDirective:
    """Construct the explicit directive variant and computed stable ID."""
    directive_id = compute_directive_id(identity)
    generation_id = identity.generation_id
    match identity.action:
        case DirectiveAction.ACTIVATE:
            if generation_id is None:
                raise PraxisConfigContractError(PraxisContractErrorCode.INVALID_CANONICAL_VALUE, "activation directive requires a generation")
            return PraxisActivateDirective(
                target_id=identity.target_id,
                rollout_id=identity.rollout_id,
                directive_id=directive_id,
                policy_epoch=identity.policy_epoch,
                eligibility_deadline=identity.eligibility_deadline,
                generation_id=generation_id,
            )
        case DirectiveAction.RETRY:
            if generation_id is None:
                raise PraxisConfigContractError(PraxisContractErrorCode.INVALID_CANONICAL_VALUE, "retry directive requires a generation")
            return PraxisRetryDirective(
                target_id=identity.target_id,
                rollout_id=identity.rollout_id,
                directive_id=directive_id,
                policy_epoch=identity.policy_epoch,
                eligibility_deadline=identity.eligibility_deadline,
                generation_id=generation_id,
            )
        case DirectiveAction.ROLLBACK:
            if generation_id is None:
                raise PraxisConfigContractError(PraxisContractErrorCode.INVALID_CANONICAL_VALUE, "rollback directive requires a generation")
            return PraxisRollbackDirective(
                target_id=identity.target_id,
                rollout_id=identity.rollout_id,
                directive_id=directive_id,
                policy_epoch=identity.policy_epoch,
                eligibility_deadline=identity.eligibility_deadline,
                generation_id=generation_id,
            )
        case DirectiveAction.STOP:
            return PraxisStopDirective(
                target_id=identity.target_id,
                rollout_id=identity.rollout_id,
                directive_id=directive_id,
                policy_epoch=identity.policy_epoch,
                eligibility_deadline=identity.eligibility_deadline,
            )
        case unreachable:
            assert_never(unreachable)


def compute_response_etag(directive_id: Sha256Hex, last_accepted_report_cursor: int, next_report_cursor: int) -> str:
    """Hash directive identity plus mutable report cursors for HTTP caching."""
    if last_accepted_report_cursor < 0 or next_report_cursor < 0:
        raise PraxisConfigContractError(PraxisContractErrorCode.INVALID_CANONICAL_VALUE, "report cursors cannot be negative")
    return hashlib.sha256(length_frame_utf8((directive_id, str(last_accepted_report_cursor), str(next_report_cursor)))).hexdigest()


class PraxisActivationCohort(PraxisStrictModel):
    """Frozen rollout cohort bound to one server-issued directive."""

    target_id: SafeIdentifier
    rollout_id: SafeIdentifier
    directive_id: Sha256Hex
    replica_ids: tuple[SafeIdentifier, ...] = Field(max_length=1024)

    @model_validator(mode="after")
    def validate_replicas(self) -> PraxisActivationCohort:
        """Require deterministic unique cohort member ordering."""
        if self.replica_ids != tuple(sorted(self.replica_ids)) or len(self.replica_ids) != len(set(self.replica_ids)):
            raise PraxisConfigContractError(PraxisContractErrorCode.INVALID_CANONICAL_VALUE, "cohort replica IDs must be unique and sorted")
        return self


class PraxisDirectiveResponseInput(PraxisStrictModel):
    """Inputs that determine one desired-directive HTTP response."""

    directive: PraxisDirective
    cohort: PraxisActivationCohort
    last_accepted_report_cursor: int = Field(ge=0)
    next_report_cursor: int = Field(ge=0)


class PraxisDirectiveResponse(PraxisDirectiveResponseInput):
    """Desired directive response with cursor-sensitive HTTP identity."""

    response_etag: Sha256Hex

    @classmethod
    def create(cls, response: PraxisDirectiveResponseInput) -> PraxisDirectiveResponse:
        """Create a response with its cursor-sensitive ETag."""
        return cls(
            directive=response.directive,
            cohort=response.cohort,
            last_accepted_report_cursor=response.last_accepted_report_cursor,
            next_report_cursor=response.next_report_cursor,
            response_etag=compute_response_etag(response.directive.directive_id, response.last_accepted_report_cursor, response.next_report_cursor),
        )

    @model_validator(mode="after")
    def validate_bindings(self) -> PraxisDirectiveResponse:
        """Bind cohort, cursors, and response ETag to one directive."""
        if self.next_report_cursor != self.last_accepted_report_cursor + 1:
            raise PraxisConfigContractError(PraxisContractErrorCode.INVALID_CANONICAL_VALUE, "next report cursor must follow the accepted cursor")
        if (self.cohort.target_id, self.cohort.rollout_id, self.cohort.directive_id) != (self.directive.target_id, self.directive.rollout_id, self.directive.directive_id):
            raise PraxisConfigContractError(PraxisContractErrorCode.INVALID_CANONICAL_VALUE, "cohort does not bind to directive")
        expected_etag = compute_response_etag(self.directive.directive_id, self.last_accepted_report_cursor, self.next_report_cursor)
        if self.response_etag != expected_etag:
            raise PraxisConfigContractError(PraxisContractErrorCode.INVALID_CANONICAL_VALUE, "response ETag does not match directive cursors")
        return self


class _PraxisReplicaReportBase(PraxisStrictModel):
    """Caller payload fields shared by all report variants."""

    report_schema: Literal["praxis-replica-report/v1"] = REPORT_SCHEMA_V1
    directive_id: Sha256Hex
    sequence: int = Field(ge=1)


class PraxisPreparedReport(_PraxisReplicaReportBase):
    """Replica staged and verified the directive generation."""

    state: Literal[ReportState.PREPARED] = ReportState.PREPARED


class PraxisCanaryPassedReport(_PraxisReplicaReportBase):
    """Replica passed the policy canary for the directive."""

    state: Literal[ReportState.CANARY_PASSED] = ReportState.CANARY_PASSED


class PraxisActiveReport(_PraxisReplicaReportBase):
    """Replica made the directive generation locally active."""

    state: Literal[ReportState.ACTIVE] = ReportState.ACTIVE


class PraxisFailedReport(_PraxisReplicaReportBase):
    """Replica failed with one sanitized machine-readable category."""

    state: Literal[ReportState.FAILED] = ReportState.FAILED
    failure_category: ReplicaFailureCategory

    @field_validator("failure_category", mode="before")
    @classmethod
    def parse_failure_category(cls, value: object) -> object:
        """Parse the JSON string at the strict HTTP model boundary."""
        return ReplicaFailureCategory(value) if isinstance(value, str) else value


PraxisReplicaReport = Annotated[PraxisPreparedReport | PraxisCanaryPassedReport | PraxisActiveReport | PraxisFailedReport, Field(discriminator="state")]
_PRAXIS_REPLICA_REPORT_ADAPTER: Final = TypeAdapter(PraxisReplicaReport)


def parse_replica_report(payload: str | bytes) -> PraxisReplicaReport:
    """Parse a strict discriminated replica report JSON payload."""
    try:
        return _PRAXIS_REPLICA_REPORT_ADAPTER.validate_json(payload, strict=True)
    except ValidationError:
        contract_error = PraxisConfigContractError(PraxisContractErrorCode.INVALID_CANONICAL_VALUE, "replica report is invalid")
    raise contract_error from None
