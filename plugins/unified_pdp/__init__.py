# -*- coding: utf-8 -*-
"""Unified Policy Decision Point (PDP) – public API.

Typical usage::

    from mcpgateway.plugins.unified_pdp import PolicyDecisionPoint, PDPConfig, Subject, Resource, Context

    config = PDPConfig(...)
    pdp = PolicyDecisionPoint(config)

    decision = await pdp.check_access(
        subject=Subject(email="user@example.com", roles=["developer"]),
        action="tools.invoke",
        resource=Resource(type="tool", id="db-query"),
        context=Context(ip="10.0.0.1"),
    )
"""

from .pdp_models import (
    AccessDecision,
    CacheConfig,
    CombinationMode,
    Context,
    Decision,
    DecisionExplanation,
    EngineConfig,
    EngineDecision,
    EngineHealthReport,
    EngineStatus,
    EngineType,
    PDPConfig,
    PDPHealthReport,
    PerformanceConfig,
    Permission,
    Resource,
    Subject,
)
from .pdp import PolicyDecisionPoint

__all__ = [
    # Orchestrator
    "PolicyDecisionPoint",
    # Config
    "PDPConfig",
    "EngineConfig",
    "CacheConfig",
    "PerformanceConfig",
    # Enums
    "Decision",
    "CombinationMode",
    "EngineType",
    "EngineStatus",
    # Request
    "Subject",
    "Resource",
    "Context",
    # Response
    "AccessDecision",
    "EngineDecision",
    "DecisionExplanation",
    "Permission",
    # Health
    "PDPHealthReport",
    "EngineHealthReport",
]
