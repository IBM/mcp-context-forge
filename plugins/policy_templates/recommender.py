# -*- coding: utf-8 -*-
"""Location: ./plugins/policy_templates/recommender.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Security Team

Recommendation engine and gap analysis for the Policy Templates Library plugin.

Given a RequirementsSpec describing the caller's compliance, category, and
industry needs, the TemplateRecommender ranks available templates by relevance
and identifies coverage gaps where no suitable template exists.
"""

# Standard
import logging
from typing import Dict, List, Optional, Set

# Local
from .models import (
    GapAnalysis,
    PolicyGap,
    PolicyTemplate,
    RequirementsSpec,
    RiskLevel,
    TemplateRecommendation,
)
from .registry import PolicyTemplateRegistry

logger = logging.getLogger(__name__)

# Mapping from compliance framework to the policy categories that should
# typically be covered to satisfy that framework's requirements.
_FRAMEWORK_REQUIRED_CATEGORIES: Dict[str, List[str]] = {
    "HIPAA": ["compliance/hipaa", "rbac", "abac"],
    "HITECH": ["compliance/hipaa"],
    "PCI-DSS": ["compliance/pci-dss", "rbac"],
    "SOX": ["compliance/sox", "rbac"],
    "GDPR": ["compliance/gdpr", "rbac", "abac"],
    "NIST": ["rbac", "abac"],
    "ISO27001": ["rbac", "abac"],
    "CCPA": ["compliance/gdpr", "rbac"],
    "FedRAMP": ["rbac", "abac", "government"],
    "FISMA": ["rbac", "abac", "government"],
}

# Mapping from industry vertical to recommended category prefixes.
_INDUSTRY_CATEGORY_MAP: Dict[str, List[str]] = {
    "healthcare": ["industry/healthcare", "compliance/hipaa"],
    "finance": ["industry/finance", "compliance/pci-dss", "compliance/sox"],
    "government": ["industry/government"],
    "retail": ["compliance/pci-dss", "rbac"],
    "technology": ["rbac", "abac", "mcp-specific"],
}

# Risk level ordinal for comparison (higher = more severe).
_RISK_ORDINAL: Dict[RiskLevel, int] = {
    RiskLevel.LOW: 1,
    RiskLevel.MEDIUM: 2,
    RiskLevel.HIGH: 3,
    RiskLevel.CRITICAL: 4,
}


class TemplateRecommender:
    """Ranks policy templates by relevance and performs compliance gap analysis.

    Typical usage::

        recommender = TemplateRecommender(registry)
        requirements = RequirementsSpec(
            compliance_frameworks=["HIPAA", "SOX"],
            industry="healthcare",
        )
        recommendations = recommender.recommend(requirements)
        gap_analysis = recommender.analyze_gaps(requirements, deployed_categories=[])
    """

    def __init__(self, registry: PolicyTemplateRegistry) -> None:
        """Initialize the recommender with a populated template registry.

        Args:
            registry: A loaded PolicyTemplateRegistry to score templates from.
        """
        self._registry = registry

    def recommend(
        self,
        requirements: RequirementsSpec,
        max_results: int = 10,
    ) -> List[TemplateRecommendation]:
        """Rank and return the most relevant templates for the given requirements.

        Scores each template in the registry against the requirements using:
        - Compliance framework overlap (most heavily weighted).
        - Category overlap with required and requested categories.
        - Industry vertical alignment.
        - Risk level alignment.
        - Use-case keyword matches.

        Args:
            requirements: Caller-supplied requirements specification.
            max_results: Maximum number of recommendations to return.

        Returns:
            Sorted list of TemplateRecommendation objects, highest score first.
        """
        templates = self._registry.list_all()
        scored: List[TemplateRecommendation] = []

        for template in templates:
            score, reason = self._score_template(template, requirements)
            if score > 0.0:
                scored.append(
                    TemplateRecommendation(
                        template_name=template.metadata.name,
                        category=template.metadata.category,
                        score=round(score, 3),
                        reason=reason,
                        compliance_frameworks=list(template.metadata.compliance_frameworks),
                        risk_level=template.metadata.risk_level,
                    )
                )

        # Sort by descending score, then alphabetically by name for stability
        scored.sort(key=lambda r: (-r.score, r.template_name))
        return scored[:max_results]

    def analyze_gaps(
        self,
        requirements: RequirementsSpec,
        deployed_categories: Optional[List[str]] = None,
    ) -> GapAnalysis:
        """Identify compliance coverage gaps relative to the requirements.

        For each compliance framework in the requirements the method determines
        which policy categories are required, checks which are already covered
        by the deployed categories, and reports the remainder as gaps.

        Args:
            requirements: Caller-supplied requirements specification.
            deployed_categories: List of category paths already deployed in the
                caller's environment.  An empty list means nothing is deployed.

        Returns:
            GapAnalysis describing covered frameworks, gaps, and recommendations.
        """
        deployed: Set[str] = set(deployed_categories or [])
        covered_frameworks: List[str] = []
        gaps: List[PolicyGap] = []

        for framework in requirements.compliance_frameworks:
            fw_upper = framework.upper()
            required_cats = _FRAMEWORK_REQUIRED_CATEGORIES.get(fw_upper, [])

            missing: List[str] = []
            for cat in required_cats:
                # A category is covered if any deployed category starts with the required prefix
                if not any(d.startswith(cat) for d in deployed):
                    missing.append(cat)

            if not missing:
                covered_frameworks.append(framework)
                continue

            # Find templates that address the missing categories
            remediation_templates: List[str] = []
            for cat in missing:
                for template in self._registry.filter(category=cat):
                    if template.metadata.name not in remediation_templates:
                        remediation_templates.append(template.metadata.name)

            severity = self._framework_severity(fw_upper)
            gaps.append(
                PolicyGap(
                    framework=framework,
                    missing_categories=missing,
                    recommended_templates=remediation_templates,
                    severity=severity,
                )
            )

        # Compute coverage score
        total_frameworks = len(requirements.compliance_frameworks)
        coverage_score = len(covered_frameworks) / total_frameworks if total_frameworks > 0 else 1.0

        # Generate recommendations to close the gaps
        gap_recommendations = self.recommend(requirements)

        return GapAnalysis(
            requirements=requirements,
            covered_frameworks=covered_frameworks,
            gaps=gaps,
            coverage_score=round(coverage_score, 3),
            recommendations=gap_recommendations,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _score_template(
        self, template: PolicyTemplate, requirements: RequirementsSpec
    ) -> tuple[float, str]:
        """Compute a relevance score for a single template.

        Args:
            template: The candidate template to score.
            requirements: The requirements specification to score against.

        Returns:
            Tuple of (score, reason_string) where score is in the range [0, 1].
        """
        score = 0.0
        reasons: List[str] = []
        meta = template.metadata

        # --- Compliance framework overlap (weight: 0.45) ---
        if requirements.compliance_frameworks:
            req_fw_upper = {fw.upper() for fw in requirements.compliance_frameworks}
            tmpl_fw_upper = {fw.upper() for fw in meta.compliance_frameworks}
            overlap = req_fw_upper & tmpl_fw_upper
            if overlap:
                fw_score = 0.45 * len(overlap) / len(req_fw_upper)
                score += fw_score
                reasons.append(f"covers {', '.join(sorted(overlap))}")

        # --- Category overlap (weight: 0.25) ---
        required_cats: List[str] = []
        for fw in requirements.compliance_frameworks:
            required_cats.extend(_FRAMEWORK_REQUIRED_CATEGORIES.get(fw.upper(), []))
        for cat in requirements.categories:
            required_cats.append(cat)

        if required_cats:
            cat_matches = sum(1 for c in required_cats if meta.category.startswith(c) or c.startswith(meta.category))
            if cat_matches:
                cat_score = 0.25 * min(cat_matches / len(required_cats), 1.0)
                score += cat_score
                reasons.append(f"category '{meta.category}' matches requirements")

        # --- Industry alignment (weight: 0.15) ---
        if requirements.industry:
            industry_cats = _INDUSTRY_CATEGORY_MAP.get(requirements.industry.lower(), [])
            if any(meta.category.startswith(c) for c in industry_cats):
                score += 0.15
                reasons.append(f"aligned with {requirements.industry} industry")

        # --- Risk level alignment (weight: 0.10) ---
        if requirements.risk_levels:
            if meta.risk_level in requirements.risk_levels:
                score += 0.10
                reasons.append(f"risk level '{meta.risk_level.value}' matches")
            elif not requirements.risk_levels:
                score += 0.05

        # --- Use-case keyword matching (weight: 0.05) ---
        if requirements.use_cases:
            haystack = " ".join(
                [meta.name, meta.description, meta.category, " ".join(meta.tags)]
            ).lower()
            matches = sum(1 for uc in requirements.use_cases if uc.lower() in haystack)
            if matches:
                score += 0.05 * min(matches / len(requirements.use_cases), 1.0)
                reasons.append(f"matches use case(s): {', '.join(requirements.use_cases[:3])}")

        reason_str = "; ".join(reasons) if reasons else "general policy template"
        return min(score, 1.0), reason_str

    @staticmethod
    def _framework_severity(framework: str) -> RiskLevel:
        """Return the default severity for a compliance framework gap.

        Args:
            framework: Uppercase compliance framework name.

        Returns:
            RiskLevel appropriate for gaps in that framework.
        """
        high_severity = {"HIPAA", "PCI-DSS", "SOX", "FEDRAMP", "FISMA"}
        critical_severity = {"HITECH"}
        if framework in critical_severity:
            return RiskLevel.CRITICAL
        if framework in high_severity:
            return RiskLevel.HIGH
        return RiskLevel.MEDIUM
