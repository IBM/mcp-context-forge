# -*- coding: utf-8 -*-
"""Pydantic models for the Unified Policy Decision Point (PDP).

All domain types used across engines, the PDP orchestrator, caching,
hooks, and the REST API are defined here so the rest of the codebase
has a single, unambiguous import target.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Decision(str, Enum):
    """Final binary outcome returned to the gateway."""

    ALLOW = "allow"
    DENY = "deny"


class CombinationMode(str, Enum):
    """How multiple engine decisions are merged into one."""

    ALL_MUST_ALLOW = "all_must_allow"  # AND – every enabled engine must allow
    ANY_ALLOW = "any_allow"  # OR  – at least one engine must allow
    FIRST_MATCH = "first_match"  # first engine (by priority) that isn't SKIP decides


class EngineType(str, Enum):
    """Supported policy-engine back-ends."""

    OPA = "opa"
    CEDAR = "cedar"
    NATIVE = "native"
    MAC = "mac"


class EngineStatus(str, Enum):
    """Health-check result for a single engine."""

    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    DISABLED = "disabled"


# ---------------------------------------------------------------------------
# Request primitives  (what the caller hands the PDP)
# ---------------------------------------------------------------------------


class Subject(BaseModel):
    """The entity requesting access."""

    email: str
    roles: List[str] = Field(default_factory=list)
    team_id: Optional[str] = None
    mfa_verified: bool = False
    clearance_level: Optional[int] = None  # used by MAC engine
    attributes: Dict[str, Any] = Field(default_factory=dict)


class Resource(BaseModel):
    """The thing being accessed."""

    type: str  # "tool" | "resource" | "prompt" | "server"
    id: str
    server: Optional[str] = None
    classification_level: Optional[int] = None  # used by MAC engine
    annotations: Dict[str, Any] = Field(default_factory=dict)


class Context(BaseModel):
    """Ambient information about the request."""

    ip: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    user_agent: Optional[str] = None
    session_id: Optional[str] = None
    extra: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Engine-level decision  (what each adapter returns internally)
# ---------------------------------------------------------------------------


class EngineDecision(BaseModel):
    """Raw verdict from a single policy engine."""

    engine: EngineType
    decision: Decision
    reason: str = ""
    matching_policies: List[str] = Field(default_factory=list)
    duration_ms: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Aggregate decision  (what the PDP returns to the caller)
# ---------------------------------------------------------------------------


class AccessDecision(BaseModel):
    """Unified decision returned by the PDP after combination logic."""

    decision: Decision
    reason: str = ""
    matching_policies: List[str] = Field(default_factory=list)
    engine_decisions: List[EngineDecision] = Field(default_factory=list)
    duration_ms: float = 0.0
    cached: bool = False
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Explanation  (verbose, for auditing / debugging)
# ---------------------------------------------------------------------------


class DecisionExplanation(BaseModel):
    """Human-readable breakdown of why a decision was reached."""

    decision: Decision
    summary: str
    engine_explanations: List[Dict[str, Any]] = Field(default_factory=list)
    combination_mode: CombinationMode
    evaluated_engines: List[EngineType] = Field(default_factory=list)
    skipped_engines: List[EngineType] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Permissions  (for get_effective_permissions)
# ---------------------------------------------------------------------------


class Permission(BaseModel):
    """A single permission the subject holds."""

    action: str
    resource_type: str
    resource_id: Optional[str] = None  # None means wildcard
    granted_by: str  # engine name or policy id
    conditions: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Configuration models  (loaded from YAML / env at startup)
# ---------------------------------------------------------------------------


class EngineConfig(BaseModel):
    """Per-engine block inside the top-level PDP config."""

    name: EngineType
    enabled: bool = True
    priority: int = 1  # lower number = evaluated first
    # engine-specific settings live here
    settings: Dict[str, Any] = Field(default_factory=dict)


class CacheConfig(BaseModel):
    """Cache tuning knobs."""

    enabled: bool = True
    ttl_seconds: int = 60
    max_entries: int = 10_000


class PerformanceConfig(BaseModel):
    """Latency / concurrency knobs."""

    timeout_ms: int = 1000
    parallel_evaluation: bool = True


class PDPConfig(BaseModel):
    """Top-level PDP configuration – mirrors the YAML block in the issue spec."""

    engines: List[EngineConfig] = Field(default_factory=list)
    combination_mode: CombinationMode = CombinationMode.ALL_MUST_ALLOW
    default_decision: Decision = Decision.DENY
    cache: CacheConfig = Field(default_factory=CacheConfig)
    performance: PerformanceConfig = Field(default_factory=PerformanceConfig)


# ---------------------------------------------------------------------------
# Health-check response
# ---------------------------------------------------------------------------


class EngineHealthReport(BaseModel):
    """Health status of one engine."""

    engine: EngineType
    status: EngineStatus
    latency_ms: Optional[float] = None
    detail: Optional[str] = None


class PDPHealthReport(BaseModel):
    """Aggregate health of the whole PDP."""

    healthy: bool
    engines: List[EngineHealthReport] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
