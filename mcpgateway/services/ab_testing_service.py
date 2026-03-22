# -*- coding: utf-8 -*-
"""A/B Testing Framework for Recommendation Experiments.

Supports concurrent experiments with consistent hash-based user assignment,
per-variant metric tracking, and statistical significance calculation using
two-proportion z-test.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

# Standard
import hashlib
import logging
import math
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

# Third-Party
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIN_IMPRESSIONS_FOR_SIGNIFICANCE = 1000
P_VALUE_THRESHOLD = 0.05
MAX_CONCURRENT_EXPERIMENTS = 20


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ExperimentStatus(str, Enum):
    """Status of an experiment."""

    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class VariantConfig(BaseModel):
    """Configuration for a single experiment variant."""

    name: str = Field(..., description="Variant name (e.g. 'control', 'treatment_a')")
    traffic_percentage: float = Field(..., ge=0, le=100, description="Percentage of traffic")
    weight_overrides: Dict[str, float] = Field(default_factory=dict, description="Strategy weight overrides")
    description: str = Field("", description="Variant description")


class VariantMetrics(BaseModel):
    """Tracked metrics for a single variant."""

    variant_name: str
    impressions: int = 0
    clicks: int = 0
    adoptions: int = 0
    dismissals: int = 0
    ctr: float = Field(0.0, description="Click-through rate")
    adoption_rate: float = Field(0.0, description="Adoption rate")

    def compute_rates(self) -> None:
        """Recompute CTR and adoption rate from counts."""
        self.ctr = (self.clicks / self.impressions * 100) if self.impressions > 0 else 0.0
        self.adoption_rate = (self.adoptions / self.impressions * 100) if self.impressions > 0 else 0.0


class ExperimentConfig(BaseModel):
    """Configuration for an A/B test experiment."""

    experiment_id: str = Field(..., description="Unique experiment identifier")
    name: str = Field(..., description="Human-readable name")
    description: str = Field("", description="Experiment description")
    variants: List[VariantConfig] = Field(..., min_length=2, description="At least 2 variants")
    status: ExperimentStatus = Field(ExperimentStatus.DRAFT)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    min_impressions: int = Field(MIN_IMPRESSIONS_FOR_SIGNIFICANCE, description="Min impressions for significance")
    p_value_threshold: float = Field(P_VALUE_THRESHOLD, description="Significance threshold")


class SignificanceResult(BaseModel):
    """Statistical significance calculation result."""

    variant_a: str
    variant_b: str
    metric: str
    z_score: float
    p_value: float
    significant: bool
    confidence_level: float = Field(0.0, description="1 - p_value as percentage")
    winner: Optional[str] = None
    sample_size_sufficient: bool = False


class ExperimentReport(BaseModel):
    """Full experiment report with metrics and significance."""

    experiment_id: str
    name: str
    status: ExperimentStatus
    variant_metrics: Dict[str, VariantMetrics] = Field(default_factory=dict)
    significance_results: list[SignificanceResult] = Field(default_factory=lambda: list[SignificanceResult]())  # pyright: ignore[reportUnknownMemberType]
    total_impressions: int = 0
    duration_hours: Optional[float] = None
    recommendation: Optional[str] = None


class ExperimentCreateRequest(BaseModel):
    """Request to create an experiment."""

    name: str = Field(..., description="Experiment name")
    description: str = Field("", description="Experiment description")
    variants: List[VariantConfig] = Field(..., min_length=2)
    min_impressions: int = Field(MIN_IMPRESSIONS_FOR_SIGNIFICANCE, ge=100)
    p_value_threshold: float = Field(P_VALUE_THRESHOLD, gt=0, lt=1)


# ---------------------------------------------------------------------------
# A/B Testing Service
# ---------------------------------------------------------------------------


class ABTestingService:
    """A/B testing framework for recommendation experiments.

    Features:
    - Consistent hash-based user assignment (stable across sessions)
    - Up to 20 concurrent experiments
    - Per-variant metric tracking
    - Two-proportion z-test for statistical significance
    - Admin APIs for experiment lifecycle

    Attributes:
        experiments: Active experiments indexed by ID.
        metrics: Per-experiment variant metrics.
    """

    def __init__(self) -> None:
        self._experiments: Dict[str, ExperimentConfig] = {}
        self._metrics: Dict[str, Dict[str, VariantMetrics]] = {}
        self._user_assignments: Dict[str, Dict[str, str]] = {}  # experiment_id -> {user_id: variant}

    # ------------------------------------------------------------------
    # Experiment management
    # ------------------------------------------------------------------

    def create_experiment(self, request: ExperimentCreateRequest) -> ExperimentConfig:
        """Create a new experiment.

        Args:
            request: Experiment configuration.

        Returns:
            Created ExperimentConfig.

        Raises:
            ValueError: If max concurrent experiments exceeded or traffic
                percentages don't sum to 100.
        """
        running = sum(1 for e in self._experiments.values() if e.status == ExperimentStatus.RUNNING)
        if running >= MAX_CONCURRENT_EXPERIMENTS:
            raise ValueError(f"Maximum {MAX_CONCURRENT_EXPERIMENTS} concurrent experiments exceeded")

        total_traffic = sum(v.traffic_percentage for v in request.variants)
        if abs(total_traffic - 100.0) > 0.01:
            raise ValueError(f"Variant traffic must sum to 100%, got {total_traffic}%")

        exp_id = hashlib.sha256(f"{request.name}:{time.monotonic()}".encode()).hexdigest()[:12]

        config = ExperimentConfig(
            experiment_id=exp_id,
            name=request.name,
            description=request.description,
            variants=request.variants,
            status=ExperimentStatus.DRAFT,
            min_impressions=request.min_impressions,
            p_value_threshold=request.p_value_threshold,
        )

        self._experiments[exp_id] = config
        self._metrics[exp_id] = {v.name: VariantMetrics(variant_name=v.name, ctr=0.0, adoption_rate=0.0) for v in request.variants}

        logger.info("Created experiment %s: %s", exp_id, request.name)
        return config

    def start_experiment(self, experiment_id: str) -> ExperimentConfig:
        """Start an experiment.

        Args:
            experiment_id: Experiment to start.

        Returns:
            Updated ExperimentConfig.

        Raises:
            KeyError: If experiment not found.
            ValueError: If experiment not in DRAFT or PAUSED status.
        """
        exp = self._get_experiment(experiment_id)
        if exp.status not in (ExperimentStatus.DRAFT, ExperimentStatus.PAUSED):
            raise ValueError(f"Cannot start experiment in {exp.status} status")

        exp.status = ExperimentStatus.RUNNING
        exp.started_at = exp.started_at or datetime.now(timezone.utc)
        return exp

    def pause_experiment(self, experiment_id: str) -> ExperimentConfig:
        """Pause a running experiment.

        Args:
            experiment_id: Experiment to pause.

        Returns:
            Updated ExperimentConfig.
        """
        exp = self._get_experiment(experiment_id)
        if exp.status != ExperimentStatus.RUNNING:
            raise ValueError(f"Cannot pause experiment in {exp.status} status")
        exp.status = ExperimentStatus.PAUSED
        return exp

    def complete_experiment(self, experiment_id: str) -> ExperimentConfig:
        """Mark an experiment as completed.

        Args:
            experiment_id: Experiment to complete.

        Returns:
            Updated ExperimentConfig.
        """
        exp = self._get_experiment(experiment_id)
        exp.status = ExperimentStatus.COMPLETED
        exp.ended_at = datetime.now(timezone.utc)
        return exp

    def delete_experiment(self, experiment_id: str) -> None:
        """Delete an experiment.

        Args:
            experiment_id: Experiment to delete.

        Raises:
            KeyError: If experiment not found.
        """
        self._get_experiment(experiment_id)  # Validates existence
        del self._experiments[experiment_id]
        self._metrics.pop(experiment_id, None)
        self._user_assignments.pop(experiment_id, None)

    def list_experiments(self, status: Optional[ExperimentStatus] = None) -> List[ExperimentConfig]:
        """List experiments, optionally filtered by status.

        Args:
            status: Optional status filter.

        Returns:
            List of matching experiments.
        """
        experiments = list(self._experiments.values())
        if status is not None:
            experiments = [e for e in experiments if e.status == status]
        return experiments

    # ------------------------------------------------------------------
    # User assignment
    # ------------------------------------------------------------------

    def assign_variant(self, experiment_id: str, user_id: str) -> Optional[str]:
        """Assign a user to a variant using consistent hashing.

        The assignment is deterministic: the same user always gets the same
        variant for a given experiment, ensuring consistency across sessions.

        Args:
            experiment_id: Experiment ID.
            user_id: User ID.

        Returns:
            Variant name, or None if experiment is not running.
        """
        exp = self._experiments.get(experiment_id)
        if not exp or exp.status != ExperimentStatus.RUNNING:
            return None

        # Check cached assignment
        if experiment_id in self._user_assignments:
            cached = self._user_assignments[experiment_id].get(user_id)
            if cached:
                return cached

        # Consistent hash assignment
        hash_input = f"{experiment_id}:{user_id}"
        hash_value = int(hashlib.md5(hash_input.encode()).hexdigest(), 16)  # nosec B324 - not for security
        bucket = hash_value % 10000  # 0.01% granularity

        cumulative = 0.0
        assigned_variant = exp.variants[-1].name  # fallback

        for variant in exp.variants:
            cumulative += variant.traffic_percentage * 100  # Scale to 10000
            if bucket < cumulative:
                assigned_variant = variant.name
                break

        # Cache the assignment
        if experiment_id not in self._user_assignments:
            self._user_assignments[experiment_id] = {}
        self._user_assignments[experiment_id][user_id] = assigned_variant

        return assigned_variant

    def get_variant_weights(self, experiment_id: str, user_id: str) -> Optional[Dict[str, float]]:
        """Get the strategy weight overrides for a user's assigned variant.

        Args:
            experiment_id: Experiment ID.
            user_id: User ID.

        Returns:
            Weight overrides dict, or None if no active experiment.
        """
        variant_name = self.assign_variant(experiment_id, user_id)
        if not variant_name:
            return None

        exp = self._experiments.get(experiment_id)
        if not exp:
            return None

        for variant in exp.variants:
            if variant.name == variant_name:
                return variant.weight_overrides if variant.weight_overrides else None

        return None

    # ------------------------------------------------------------------
    # Metric tracking
    # ------------------------------------------------------------------

    def record_impression(self, experiment_id: str, user_id: str) -> None:
        """Record that a user saw recommendations.

        Args:
            experiment_id: Experiment ID.
            user_id: User ID.
        """
        variant = self.assign_variant(experiment_id, user_id)
        if not variant:
            return

        metrics = self._metrics.get(experiment_id, {}).get(variant)
        if metrics:
            metrics.impressions += 1
            metrics.compute_rates()

    def record_click(self, experiment_id: str, user_id: str) -> None:
        """Record that a user clicked a recommendation.

        Args:
            experiment_id: Experiment ID.
            user_id: User ID.
        """
        variant = self.assign_variant(experiment_id, user_id)
        if not variant:
            return

        metrics = self._metrics.get(experiment_id, {}).get(variant)
        if metrics:
            metrics.clicks += 1
            metrics.compute_rates()

    def record_adoption(self, experiment_id: str, user_id: str) -> None:
        """Record that a user adopted/used a recommended tool.

        Args:
            experiment_id: Experiment ID.
            user_id: User ID.
        """
        variant = self.assign_variant(experiment_id, user_id)
        if not variant:
            return

        metrics = self._metrics.get(experiment_id, {}).get(variant)
        if metrics:
            metrics.adoptions += 1
            metrics.compute_rates()

    def record_dismissal(self, experiment_id: str, user_id: str) -> None:
        """Record that a user dismissed a recommendation.

        Args:
            experiment_id: Experiment ID.
            user_id: User ID.
        """
        variant = self.assign_variant(experiment_id, user_id)
        if not variant:
            return

        metrics = self._metrics.get(experiment_id, {}).get(variant)
        if metrics:
            metrics.dismissals += 1
            metrics.compute_rates()

    # ------------------------------------------------------------------
    # Statistical significance
    # ------------------------------------------------------------------

    def calculate_significance(
        self,
        experiment_id: str,
        metric: str = "ctr",
    ) -> List[SignificanceResult]:
        """Calculate statistical significance between all variant pairs.

        Uses two-proportion z-test comparing the specified metric
        between each pair of variants.

        Args:
            experiment_id: Experiment ID.
            metric: Metric to compare ('ctr' or 'adoption_rate').

        Returns:
            List of SignificanceResult for each pair.

        Raises:
            KeyError: If experiment not found.
        """
        exp = self._get_experiment(experiment_id)
        exp_metrics = self._metrics.get(experiment_id, {})

        results: List[SignificanceResult] = []
        variant_names = [v.name for v in exp.variants]

        for i, name_a in enumerate(variant_names):
            for name_b in variant_names[i + 1 :]:
                m_a = exp_metrics.get(name_a)
                m_b = exp_metrics.get(name_b)

                if not m_a or not m_b:
                    continue

                result = self._two_proportion_z_test(
                    m_a, m_b, metric, exp.min_impressions, exp.p_value_threshold
                )
                results.append(result)

        return results

    def get_report(self, experiment_id: str) -> ExperimentReport:
        """Generate a full experiment report.

        Args:
            experiment_id: Experiment ID.

        Returns:
            ExperimentReport with metrics and significance.
        """
        exp = self._get_experiment(experiment_id)
        exp_metrics = self._metrics.get(experiment_id, {})

        # Compute rates
        for m in exp_metrics.values():
            m.compute_rates()

        total_impressions = sum(m.impressions for m in exp_metrics.values())
        duration = None
        if exp.started_at:
            end = exp.ended_at or datetime.now(timezone.utc)
            duration = (end - exp.started_at).total_seconds() / 3600

        significance = self.calculate_significance(experiment_id)

        recommendation = None
        if significance:
            for sig in significance:
                if sig.significant and sig.winner:
                    recommendation = f"Variant '{sig.winner}' shows significant improvement in {sig.metric}"
                    break
            if not recommendation:
                if total_impressions < exp.min_impressions:
                    recommendation = f"Need more data: {total_impressions}/{exp.min_impressions} impressions"
                else:
                    recommendation = "No statistically significant difference found"

        return ExperimentReport(
            experiment_id=experiment_id,
            name=exp.name,
            status=exp.status,
            variant_metrics=exp_metrics,
            significance_results=significance,
            total_impressions=total_impressions,
            duration_hours=round(duration, 2) if duration else None,
            recommendation=recommendation,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_experiment(self, experiment_id: str) -> ExperimentConfig:
        """Get experiment by ID or raise KeyError."""
        exp = self._experiments.get(experiment_id)
        if not exp:
            raise KeyError(f"Experiment {experiment_id} not found")
        return exp

    @staticmethod
    def _two_proportion_z_test(
        metrics_a: VariantMetrics,
        metrics_b: VariantMetrics,
        metric: str,
        min_impressions: int,
        p_value_threshold: float,
    ) -> SignificanceResult:
        """Perform two-proportion z-test between two variants.

        Args:
            metrics_a: Metrics for variant A.
            metrics_b: Metrics for variant B.
            metric: Which rate to compare.
            min_impressions: Minimum sample size.
            p_value_threshold: Significance threshold.

        Returns:
            SignificanceResult with z-score, p-value, and winner.
        """
        n_a = metrics_a.impressions
        n_b = metrics_b.impressions

        sufficient = n_a >= min_impressions and n_b >= min_impressions

        if metric == "adoption_rate":
            x_a = metrics_a.adoptions
            x_b = metrics_b.adoptions
        else:  # default to CTR
            x_a = metrics_a.clicks
            x_b = metrics_b.clicks
            metric = "ctr"

        if n_a == 0 or n_b == 0:
            return SignificanceResult(
                variant_a=metrics_a.variant_name,
                variant_b=metrics_b.variant_name,
                metric=metric,
                z_score=0.0,
                p_value=1.0,
                significant=False,
                confidence_level=0.0,
                sample_size_sufficient=False,
            )

        p_a = x_a / n_a
        p_b = x_b / n_b

        # Pooled proportion
        p_pool = (x_a + x_b) / (n_a + n_b)

        # Standard error
        if p_pool == 0 or p_pool == 1:
            return SignificanceResult(
                variant_a=metrics_a.variant_name,
                variant_b=metrics_b.variant_name,
                metric=metric,
                z_score=0.0,
                p_value=1.0,
                significant=False,
                confidence_level=0.0,
                sample_size_sufficient=sufficient,
            )

        se = math.sqrt(p_pool * (1 - p_pool) * (1 / n_a + 1 / n_b))

        if se == 0:
            z_score = 0.0
        else:
            z_score = (p_a - p_b) / se

        # Two-tailed p-value using normal approximation
        p_value = 2 * (1 - _normal_cdf(abs(z_score)))

        significant = sufficient and p_value < p_value_threshold

        winner = None
        if significant:
            winner = metrics_a.variant_name if p_a > p_b else metrics_b.variant_name

        confidence = (1 - p_value) * 100 if p_value < 1 else 0.0

        return SignificanceResult(
            variant_a=metrics_a.variant_name,
            variant_b=metrics_b.variant_name,
            metric=metric,
            z_score=round(z_score, 4),
            p_value=round(p_value, 6),
            significant=significant,
            confidence_level=round(confidence, 2),
            winner=winner,
            sample_size_sufficient=sufficient,
        )


def _normal_cdf(x: float) -> float:
    """Approximate the standard normal CDF using the error function.

    Args:
        x: Z-score value.

    Returns:
        Cumulative probability.
    """
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2)))
