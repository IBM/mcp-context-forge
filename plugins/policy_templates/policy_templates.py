# -*- coding: utf-8 -*-
"""Location: ./plugins/policy_templates/policy_templates.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Security Team

Policy Templates Library plugin for MCP Context Forge.

Loads a built-in library of compliance-ready policy templates at gateway
startup and exposes them through an in-process Python API.  The plugin acts
as a registry/library service — it does not intercept tool invocations.

Supported template categories:
- compliance/hipaa  — HIPAA / HITECH PHI protection
- compliance/pci-dss — PCI-DSS cardholder data controls
- compliance/sox    — SOX financial controls
- compliance/gdpr   — GDPR data-subject rights
- rbac              — Role-based access control patterns
- abac              — Attribute-based access control patterns
- mcp-specific      — MCP gateway tool, server, and agent policies
- industry/healthcare — Clinical access controls
- industry/finance  — Trading and financial controls
- industry/government — Clearance-based access
"""

# Standard
import logging
from typing import Any, Dict, List, Optional

# Third-Party
from pydantic import BaseModel, Field

# First-Party
from mcpgateway.plugins.framework import Plugin, PluginConfig

# Local
from .instantiator import TemplateInstantiator
from .models import (
    GapAnalysis,
    InstantiatedPolicy,
    RequirementsSpec,
    TemplateRecommendation,
    TestReport,
)
from .recommender import TemplateRecommender
from .registry import PolicyTemplateRegistry
from .test_runner import TemplateTestRunner

logger = logging.getLogger(__name__)


class PolicyTemplateLibraryConfig(BaseModel):
    """Configuration for the PolicyTemplateLibrary plugin.

    Attributes:
        template_dirs: List of directories to scan for YAML template files.
        validate_on_instantiate: Run parameter validation before rendering.
        run_tests_before_deploy: Run embedded tests when instantiating.
    """

    template_dirs: List[str] = Field(default_factory=lambda: ["plugins/policy_templates/templates"])
    validate_on_instantiate: bool = True
    run_tests_before_deploy: bool = False


class PolicyTemplateLibraryPlugin(Plugin):
    """Policy Templates Library — loads and exposes compliance policy templates.

    On startup the plugin walks all configured template directories, parses
    every YAML file that declares ``kind: PolicyTemplate``, and registers the
    templates in an in-memory registry.

    Consumers can obtain the registry, instantiator, or recommender instances
    via the ``get_registry()``, ``get_instantiator()``, and
    ``get_recommender()`` methods, or call the higher-level convenience
    methods directly on the plugin object.

    Hook: ``startup`` — loads templates when the gateway starts.

    Example::

        plugin = PolicyTemplateLibraryPlugin(config)
        await plugin.initialize()

        registry = plugin.get_registry()
        template = registry.get("hipaa-phi-protection")

        policy = plugin.instantiate("hipaa-phi-protection", {
            "phi_resource_pattern": "phi-*",
            "healthcare_roles": ["physician", "nurse"],
        })
        print(policy.policy_content)
    """

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the plugin from the gateway's PluginConfig.

        Args:
            config: Full PluginConfig as parsed from plugins/config.yaml.
                    ``config.config`` must contain a PolicyTemplateLibraryConfig-
                    compatible dictionary.
        """
        super().__init__(config)
        self._cfg = PolicyTemplateLibraryConfig(**(config.config or {}))
        self._registry = PolicyTemplateRegistry()
        self._instantiator = TemplateInstantiator(validate_on_instantiate=self._cfg.validate_on_instantiate)
        self._test_runner = TemplateTestRunner(instantiator=self._instantiator)
        self._recommender: Optional[TemplateRecommender] = None
        self._initialized = False

    # ------------------------------------------------------------------
    # Plugin lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Load all templates from the configured directories.

        Called by the gateway plugin manager on startup.  Idempotent — calling
        more than once reloads all templates from scratch.
        """
        count = self._registry.load(self._cfg.template_dirs)
        self._recommender = TemplateRecommender(self._registry)
        self._initialized = True
        logger.info(
            "PolicyTemplateLibraryPlugin initialized: %d templates loaded from %s",
            count,
            self._cfg.template_dirs,
        )

    async def shutdown(self) -> None:
        """Release resources held by the plugin."""
        self._initialized = False
        logger.debug("PolicyTemplateLibraryPlugin shutdown complete")

    # ------------------------------------------------------------------
    # Accessor methods
    # ------------------------------------------------------------------

    def get_registry(self) -> PolicyTemplateRegistry:
        """Return the template registry for direct template access.

        Returns:
            The loaded PolicyTemplateRegistry instance.
        """
        return self._registry

    def get_instantiator(self) -> TemplateInstantiator:
        """Return the template instantiator.

        Returns:
            The TemplateInstantiator instance configured for this plugin.
        """
        return self._instantiator

    def get_test_runner(self) -> TemplateTestRunner:
        """Return the template test runner.

        Returns:
            The TemplateTestRunner instance.
        """
        return self._test_runner

    def get_recommender(self) -> TemplateRecommender:
        """Return the recommendation engine.

        Returns:
            The TemplateRecommender instance.

        Raises:
            RuntimeError: If the plugin has not been initialized yet.
        """
        if self._recommender is None:
            raise RuntimeError("PolicyTemplateLibraryPlugin has not been initialized — call initialize() first")
        return self._recommender

    # ------------------------------------------------------------------
    # Convenience API
    # ------------------------------------------------------------------

    def instantiate(
        self,
        template_name: str,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> InstantiatedPolicy:
        """Instantiate a named template with the given parameters.

        Args:
            template_name: Name of the template to instantiate.
            parameters: Caller-supplied parameter values (merged with defaults).

        Returns:
            InstantiatedPolicy containing the rendered policy content.

        Raises:
            KeyError: If no template with ``template_name`` exists in the registry.
            ParameterValidationError: If validation is enabled and parameters fail.
        """
        template = self._registry.get(template_name)
        if template is None:
            raise KeyError(f"Template '{template_name}' not found in registry")
        return self._instantiator.instantiate(template, parameters or {})

    def run_tests(
        self,
        template_name: str,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> TestReport:
        """Run the embedded test suite for a named template.

        Args:
            template_name: Name of the template to test.
            parameters: Optional parameter overrides for test instantiation.

        Returns:
            TestReport with per-case results and summary statistics.

        Raises:
            KeyError: If no template with ``template_name`` exists in the registry.
        """
        template = self._registry.get(template_name)
        if template is None:
            raise KeyError(f"Template '{template_name}' not found in registry")
        return self._test_runner.run_tests(template, parameters or {})

    def recommend(
        self,
        requirements: RequirementsSpec,
        max_results: int = 10,
    ) -> List[TemplateRecommendation]:
        """Recommend templates that match the given requirements.

        Args:
            requirements: RequirementsSpec describing compliance, category, and
                industry needs.
            max_results: Maximum number of recommendations to return.

        Returns:
            Sorted list of TemplateRecommendation objects, highest score first.
        """
        return self.get_recommender().recommend(requirements, max_results=max_results)

    def analyze_gaps(
        self,
        requirements: RequirementsSpec,
        deployed_categories: Optional[List[str]] = None,
    ) -> GapAnalysis:
        """Analyse compliance gaps in the caller's current policy deployment.

        Args:
            requirements: RequirementsSpec describing what the caller needs.
            deployed_categories: List of policy category paths already deployed.

        Returns:
            GapAnalysis with identified gaps and remediation recommendations.
        """
        return self.get_recommender().analyze_gaps(requirements, deployed_categories=deployed_categories)
