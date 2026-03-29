# -*- coding: utf-8 -*-
"""Policy Templates Library Plugin — public API.

Location: ./plugins/policy_templates/__init__.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Security Team

Pre-built compliance-ready policy template library for MCP Context Forge.
Provides templates for HIPAA, PCI-DSS, SOX, GDPR, RBAC, ABAC, MCP-specific,
and industry-vertical access control scenarios.

Typical usage::

    from plugins.policy_templates import PolicyTemplateLibraryPlugin
    from plugins.policy_templates.models import RequirementsSpec

    plugin = PolicyTemplateLibraryPlugin(config)
    await plugin.initialize()

    template = plugin.get_registry().get("hipaa-phi-protection")
    policy = plugin.instantiate("hipaa-phi-protection", {"phi_resource_pattern": "phi-*"})
    report = plugin.run_tests("hipaa-phi-protection")
"""

from .models import (
    GapAnalysis,
    InstantiatedPolicy,
    ParameterType,
    PolicyEngine,
    PolicyGap,
    PolicyTemplate,
    PolicyTemplateMetadata,
    PolicyTemplateSpec,
    RequirementsSpec,
    RiskLevel,
    TemplateParameter,
    TemplateRecommendation,
    TemplateTest,
    TestExpectation,
    TestReport,
    TestResult,
)
from .registry import PolicyTemplateRegistry
from .instantiator import TemplateInstantiator
from .test_runner import TemplateTestRunner
from .recommender import TemplateRecommender
from .policy_templates import PolicyTemplateLibraryPlugin

__all__ = [
    # Plugin entry point
    "PolicyTemplateLibraryPlugin",
    # Registry
    "PolicyTemplateRegistry",
    # Instantiator
    "TemplateInstantiator",
    # Test runner
    "TemplateTestRunner",
    # Recommender
    "TemplateRecommender",
    # Models
    "GapAnalysis",
    "InstantiatedPolicy",
    "ParameterType",
    "PolicyEngine",
    "PolicyGap",
    "PolicyTemplate",
    "PolicyTemplateMetadata",
    "PolicyTemplateSpec",
    "RequirementsSpec",
    "RiskLevel",
    "TemplateParameter",
    "TemplateRecommendation",
    "TemplateTest",
    "TestExpectation",
    "TestReport",
    "TestResult",
]
