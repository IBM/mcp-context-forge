# -*- coding: utf-8 -*-
"""Location: ./plugins/policy_templates/models.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Security Team

Pydantic models for the Policy Templates Library plugin.

Defines all domain types used across the template registry, instantiator,
test runner, and recommender subsystems.
"""

# Standard
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

# Third-Party
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RiskLevel(str, Enum):
    """Risk classification for policy templates.

    Attributes:
        LOW: Low risk — applies to non-sensitive resources.
        MEDIUM: Medium risk — applies to internal or semi-sensitive resources.
        HIGH: High risk — applies to sensitive or regulated data.
        CRITICAL: Critical risk — applies to the most sensitive assets.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PolicyEngine(str, Enum):
    """Supported policy engines for template rendering.

    Attributes:
        CEDAR: Amazon Cedar policy language.
        OPA: Open Policy Agent Rego language.
        NATIVE: Built-in native rule format.
    """

    CEDAR = "cedar"
    OPA = "opa"
    NATIVE = "native"


class TestExpectation(str, Enum):
    """Expected outcome for a template test case.

    Attributes:
        ALLOW: The policy should permit the action.
        DENY: The policy should deny the action.
    """

    ALLOW = "allow"
    DENY = "deny"


class ParameterType(str, Enum):
    """Data type for a template parameter.

    Attributes:
        STRING: A single string value.
        LIST: A list of string values.
        BOOLEAN: A boolean flag.
        INTEGER: An integer value.
        DICT: A key-value mapping.
    """

    STRING = "string"
    LIST = "list"
    BOOLEAN = "boolean"
    INTEGER = "integer"
    DICT = "dict"


# ---------------------------------------------------------------------------
# Template structure models
# ---------------------------------------------------------------------------


class TemplateParameter(BaseModel):
    """Definition of a single parameter that can be supplied to a template.

    Attributes:
        name: Machine-readable parameter identifier.
        type: Data type of the parameter value.
        description: Human-readable description of the parameter purpose.
        default: Default value used when the parameter is not supplied.
        required: Whether the parameter must be provided at instantiation time.
    """

    name: str
    type: ParameterType
    description: str
    default: Optional[Any] = None
    required: bool = False


class ValidationRule(BaseModel):
    """A declarative validation rule applied to template parameters.

    Attributes:
        rule: Human-readable description of the rule constraint.
        check: Python expression that evaluates to True when the rule passes.
    """

    rule: str
    check: str


class TestPrincipal(BaseModel):
    """Principal context for a template test case.

    Attributes:
        role: The role assigned to the principal.
        attributes: Additional attributes on the principal (e.g., clearance flags).
    """

    role: str
    attributes: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


class TestGiven(BaseModel):
    """Input context for a template test case.

    Attributes:
        principal: The principal making the access request.
        action: The action being requested.
        resource: The target resource identifier.
        context: Additional environmental context for the request.
    """

    principal: TestPrincipal
    action: str
    resource: str
    context: Dict[str, Any] = Field(default_factory=dict)


class TemplateTest(BaseModel):
    """A single test case asserting expected policy behavior.

    Attributes:
        name: Descriptive name for the test scenario.
        given: Input context for the test evaluation.
        expect: The expected policy decision (allow or deny).
    """

    name: str
    given: TestGiven
    expect: TestExpectation


class PolicyTemplateMetadata(BaseModel):
    """Metadata section of a policy template YAML file.

    Attributes:
        name: Unique template identifier (slug form, e.g. hipaa-phi-protection).
        version: Semantic version string (e.g., 1.0.0).
        description: Human-readable summary of what the template enforces.
        category: Hierarchical category path (e.g., compliance/hipaa).
        compliance_frameworks: List of compliance standards this template addresses.
        risk_level: Assessed risk level for resources covered by this template.
        author: Name or team responsible for the template.
        last_reviewed: ISO date string indicating the last review date.
        tags: Optional free-form tags for search and discovery.
    """

    name: str
    version: str
    description: str
    category: str
    compliance_frameworks: List[str] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.MEDIUM
    author: str = ""
    last_reviewed: str = ""
    tags: List[str] = Field(default_factory=list)


class PolicyTemplateSpec(BaseModel):
    """Specification section of a policy template YAML file.

    Attributes:
        engine: Target policy engine for the rendered policy output.
        parameters: Ordered list of parameter definitions.
        template: Raw policy template string using {param_name} substitution.
        validation: List of declarative validation rules for parameters.
        tests: List of test cases that verify template behavior.
    """

    engine: PolicyEngine
    parameters: List[TemplateParameter] = Field(default_factory=list)
    template: str
    validation: List[ValidationRule] = Field(default_factory=list)
    tests: List[TemplateTest] = Field(default_factory=list)


class PolicyTemplate(BaseModel):
    """Complete policy template combining metadata and specification.

    This is the top-level model loaded from a YAML template file.

    Attributes:
        api_version: API version string (e.g., contextforge.io/v1).
        kind: Resource kind (always "PolicyTemplate").
        metadata: Template metadata including name, version, and compliance info.
        spec: Template specification including parameters, body, and tests.
        source_path: Filesystem path from which this template was loaded.
    """

    api_version: str = Field(alias="apiVersion", default="contextforge.io/v1")
    kind: str = "PolicyTemplate"
    metadata: PolicyTemplateMetadata
    spec: PolicyTemplateSpec
    source_path: Optional[str] = None

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Instantiation models
# ---------------------------------------------------------------------------


class InstantiatedPolicy(BaseModel):
    """The result of instantiating a policy template with concrete parameters.

    Attributes:
        template_name: Name of the source template.
        template_version: Version of the source template.
        engine: Target policy engine for this policy.
        parameters: Resolved parameter values used during instantiation.
        policy_content: Rendered policy text ready for deployment.
        instantiated_at: ISO timestamp of when the policy was generated.
    """

    template_name: str
    template_version: str
    engine: PolicyEngine
    parameters: Dict[str, Any]
    policy_content: str
    instantiated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


# ---------------------------------------------------------------------------
# Test runner models
# ---------------------------------------------------------------------------


class TestResult(BaseModel):
    """Result of executing a single template test case.

    Attributes:
        test_name: Name of the test case.
        passed: Whether the test produced the expected outcome.
        expected: The expected policy decision.
        actual: The actual decision returned by the mock evaluator.
        reason: Explanatory message for the result.
    """

    test_name: str
    passed: bool
    expected: TestExpectation
    actual: TestExpectation
    reason: str = ""


class TestReport(BaseModel):
    """Aggregated report of all test results for a template.

    Attributes:
        template_name: Name of the template under test.
        total: Total number of test cases executed.
        passed: Number of test cases that passed.
        failed: Number of test cases that failed.
        results: Detailed results for each test case.
        success: True when all tests passed.
    """

    template_name: str
    total: int
    passed: int
    failed: int
    results: List[TestResult] = Field(default_factory=list)

    @property
    def success(self) -> bool:
        """Return True when every test in the report passed.

        Returns:
            Boolean indicating overall test suite success.
        """
        return self.failed == 0


# ---------------------------------------------------------------------------
# Recommendation engine models
# ---------------------------------------------------------------------------


class RequirementsSpec(BaseModel):
    """Caller-supplied specification describing their policy requirements.

    Attributes:
        compliance_frameworks: Compliance standards the caller must satisfy.
        categories: Policy categories of interest (e.g., rbac, abac).
        risk_levels: Acceptable risk levels for recommended templates.
        industry: Optional industry vertical (e.g., healthcare, finance).
        use_cases: Free-form list of intended use cases for policy selection.
    """

    compliance_frameworks: List[str] = Field(default_factory=list)
    categories: List[str] = Field(default_factory=list)
    risk_levels: List[RiskLevel] = Field(default_factory=list)
    industry: Optional[str] = None
    use_cases: List[str] = Field(default_factory=list)


class TemplateRecommendation(BaseModel):
    """A single template recommendation returned by the recommender.

    Attributes:
        template_name: Name of the recommended template.
        category: Category of the recommended template.
        score: Relevance score between 0.0 and 1.0.
        reason: Human-readable explanation of why this template was recommended.
        compliance_frameworks: Compliance frameworks the template addresses.
        risk_level: Risk level of the recommended template.
    """

    template_name: str
    category: str
    score: float
    reason: str
    compliance_frameworks: List[str] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.MEDIUM


class PolicyGap(BaseModel):
    """An identified gap between required compliance coverage and existing policies.

    Attributes:
        framework: Compliance framework with the coverage gap.
        missing_categories: Policy categories not yet covered for this framework.
        recommended_templates: Template names that would close the gap.
        severity: Assessed severity of the gap (mirrors risk level vocabulary).
    """

    framework: str
    missing_categories: List[str] = Field(default_factory=list)
    recommended_templates: List[str] = Field(default_factory=list)
    severity: RiskLevel = RiskLevel.MEDIUM


class GapAnalysis(BaseModel):
    """Full gap analysis comparing requirements against deployed policies.

    Attributes:
        requirements: The input requirements specification used for analysis.
        covered_frameworks: Compliance frameworks with adequate policy coverage.
        gaps: List of identified coverage gaps.
        coverage_score: Overall coverage percentage (0.0–1.0).
        recommendations: Ordered list of template recommendations to close gaps.
    """

    requirements: RequirementsSpec
    covered_frameworks: List[str] = Field(default_factory=list)
    gaps: List[PolicyGap] = Field(default_factory=list)
    coverage_score: float = 0.0
    recommendations: List[TemplateRecommendation] = Field(default_factory=list)
