# -*- coding: utf-8 -*-
"""Tests for the A/B Testing Framework.

Covers:
- Experiment lifecycle: create, start, pause, complete, delete
- Consistent hash-based user assignment (stable across sessions)
- Variant metric tracking: impressions, clicks, adoptions
- Statistical significance: two-proportion z-test
- Multiple concurrent experiments (10+)
- Edge cases: traffic splits, zero impressions, insufficient data

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

# Standard
import math
from datetime import datetime, timezone

# Third-Party
import pytest

# First-Party
from mcpgateway.services.ab_testing_service import (
    MAX_CONCURRENT_EXPERIMENTS,
    MIN_IMPRESSIONS_FOR_SIGNIFICANCE,
    P_VALUE_THRESHOLD,
    ABTestingService,
    ExperimentConfig,
    ExperimentCreateRequest,
    ExperimentReport,
    ExperimentStatus,
    SignificanceResult,
    VariantConfig,
    VariantMetrics,
    _normal_cdf,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def ab_service():
    """Create an ABTestingService."""
    return ABTestingService()


@pytest.fixture
def basic_experiment_request():
    """Create a basic two-variant experiment request."""
    return ExperimentCreateRequest(
        name="Test Experiment",
        description="A basic A/B test",
        variants=[
            VariantConfig(name="control", traffic_percentage=50, weight_overrides={}),
            VariantConfig(name="treatment", traffic_percentage=50, weight_overrides={"semantic": 0.50}),
        ],
    )


@pytest.fixture
def three_variant_request():
    """Create a three-variant experiment."""
    return ExperimentCreateRequest(
        name="Three Way Test",
        variants=[
            VariantConfig(name="control", traffic_percentage=34),
            VariantConfig(name="treatment_a", traffic_percentage=33),
            VariantConfig(name="treatment_b", traffic_percentage=33),
        ],
    )


@pytest.fixture
def running_experiment(ab_service, basic_experiment_request):
    """Create and start an experiment."""
    exp = ab_service.create_experiment(basic_experiment_request)
    ab_service.start_experiment(exp.experiment_id)
    return exp


# ============================================================================
# Constants tests
# ============================================================================


class TestConstants:
    """Tests for A/B testing constants."""

    def test_min_impressions(self):
        assert MIN_IMPRESSIONS_FOR_SIGNIFICANCE == 1000

    def test_p_value_threshold(self):
        assert P_VALUE_THRESHOLD == 0.05

    def test_max_concurrent(self):
        assert MAX_CONCURRENT_EXPERIMENTS == 20


# ============================================================================
# Experiment lifecycle tests
# ============================================================================


class TestExperimentLifecycle:
    """Tests for experiment creation, status transitions, and deletion."""

    def test_create_experiment(self, ab_service, basic_experiment_request):
        exp = ab_service.create_experiment(basic_experiment_request)
        assert exp.experiment_id
        assert exp.name == "Test Experiment"
        assert exp.status == ExperimentStatus.DRAFT
        assert len(exp.variants) == 2

    def test_create_generates_unique_ids(self, ab_service):
        ids = set()
        for i in range(5):
            req = ExperimentCreateRequest(
                name=f"Exp {i}",
                variants=[
                    VariantConfig(name="a", traffic_percentage=50),
                    VariantConfig(name="b", traffic_percentage=50),
                ],
            )
            exp = ab_service.create_experiment(req)
            ids.add(exp.experiment_id)
        assert len(ids) == 5

    def test_create_invalid_traffic_sum(self, ab_service):
        req = ExperimentCreateRequest(
            name="Bad Traffic",
            variants=[
                VariantConfig(name="a", traffic_percentage=40),
                VariantConfig(name="b", traffic_percentage=40),
            ],
        )
        with pytest.raises(ValueError, match="sum to 100"):
            ab_service.create_experiment(req)

    def test_start_experiment(self, ab_service, basic_experiment_request):
        exp = ab_service.create_experiment(basic_experiment_request)
        started = ab_service.start_experiment(exp.experiment_id)
        assert started.status == ExperimentStatus.RUNNING
        assert started.started_at is not None

    def test_start_already_running(self, ab_service, running_experiment):
        with pytest.raises(ValueError, match="Cannot start"):
            ab_service.start_experiment(running_experiment.experiment_id)

    def test_pause_experiment(self, ab_service, running_experiment):
        paused = ab_service.pause_experiment(running_experiment.experiment_id)
        assert paused.status == ExperimentStatus.PAUSED

    def test_pause_not_running(self, ab_service, basic_experiment_request):
        exp = ab_service.create_experiment(basic_experiment_request)
        with pytest.raises(ValueError, match="Cannot pause"):
            ab_service.pause_experiment(exp.experiment_id)

    def test_resume_paused_experiment(self, ab_service, running_experiment):
        ab_service.pause_experiment(running_experiment.experiment_id)
        resumed = ab_service.start_experiment(running_experiment.experiment_id)
        assert resumed.status == ExperimentStatus.RUNNING

    def test_complete_experiment(self, ab_service, running_experiment):
        completed = ab_service.complete_experiment(running_experiment.experiment_id)
        assert completed.status == ExperimentStatus.COMPLETED
        assert completed.ended_at is not None

    def test_delete_experiment(self, ab_service, basic_experiment_request):
        exp = ab_service.create_experiment(basic_experiment_request)
        ab_service.delete_experiment(exp.experiment_id)
        assert ab_service.list_experiments() == []

    def test_delete_nonexistent(self, ab_service):
        with pytest.raises(KeyError):
            ab_service.delete_experiment("nonexistent")

    def test_start_nonexistent(self, ab_service):
        with pytest.raises(KeyError):
            ab_service.start_experiment("nonexistent")

    def test_list_experiments(self, ab_service, basic_experiment_request):
        ab_service.create_experiment(basic_experiment_request)
        experiments = ab_service.list_experiments()
        assert len(experiments) == 1

    def test_list_experiments_by_status(self, ab_service, running_experiment):
        running = ab_service.list_experiments(status=ExperimentStatus.RUNNING)
        assert len(running) == 1
        draft = ab_service.list_experiments(status=ExperimentStatus.DRAFT)
        assert len(draft) == 0


# ============================================================================
# User assignment tests
# ============================================================================


class TestUserAssignment:
    """Tests for consistent hash-based user assignment."""

    def test_assign_returns_variant(self, ab_service, running_experiment):
        variant = ab_service.assign_variant(running_experiment.experiment_id, "user1")
        assert variant in ["control", "treatment"]

    def test_assign_consistent_across_calls(self, ab_service, running_experiment):
        """Same user always gets same variant (deterministic)."""
        v1 = ab_service.assign_variant(running_experiment.experiment_id, "user1")
        v2 = ab_service.assign_variant(running_experiment.experiment_id, "user1")
        v3 = ab_service.assign_variant(running_experiment.experiment_id, "user1")
        assert v1 == v2 == v3

    def test_assign_different_users_get_distribution(self, ab_service, running_experiment):
        """With many users, both variants should get assignments."""
        variants = set()
        for i in range(100):
            v = ab_service.assign_variant(running_experiment.experiment_id, f"user-{i}")
            variants.add(v)
        assert len(variants) == 2, "Expected both variants to be assigned"

    def test_assign_not_running(self, ab_service, basic_experiment_request):
        exp = ab_service.create_experiment(basic_experiment_request)
        variant = ab_service.assign_variant(exp.experiment_id, "user1")
        assert variant is None

    def test_assign_nonexistent(self, ab_service):
        variant = ab_service.assign_variant("nonexistent", "user1")
        assert variant is None

    def test_assign_three_variants(self, ab_service, three_variant_request):
        exp = ab_service.create_experiment(three_variant_request)
        ab_service.start_experiment(exp.experiment_id)

        variants = set()
        for i in range(200):
            v = ab_service.assign_variant(exp.experiment_id, f"user-{i}")
            variants.add(v)
        assert len(variants) == 3

    def test_get_variant_weights(self, ab_service, running_experiment):
        weights = ab_service.get_variant_weights(running_experiment.experiment_id, "user1")
        # One variant has overrides, the other doesn't
        # The result depends on assignment
        variant = ab_service.assign_variant(running_experiment.experiment_id, "user1")
        if variant == "treatment":
            assert weights == {"semantic": 0.50}
        else:
            assert weights is None  # Control has no overrides

    def test_get_variant_weights_not_running(self, ab_service, basic_experiment_request):
        exp = ab_service.create_experiment(basic_experiment_request)
        weights = ab_service.get_variant_weights(exp.experiment_id, "user1")
        assert weights is None


# ============================================================================
# Metric tracking tests
# ============================================================================


class TestMetricTracking:
    """Tests for per-variant metric tracking."""

    def test_record_impression(self, ab_service, running_experiment):
        ab_service.record_impression(running_experiment.experiment_id, "user1")
        report = ab_service.get_report(running_experiment.experiment_id)
        total = sum(m.impressions for m in report.variant_metrics.values())
        assert total == 1

    def test_record_click(self, ab_service, running_experiment):
        ab_service.record_impression(running_experiment.experiment_id, "user1")
        ab_service.record_click(running_experiment.experiment_id, "user1")
        report = ab_service.get_report(running_experiment.experiment_id)
        total_clicks = sum(m.clicks for m in report.variant_metrics.values())
        assert total_clicks == 1

    def test_record_adoption(self, ab_service, running_experiment):
        ab_service.record_impression(running_experiment.experiment_id, "user1")
        ab_service.record_adoption(running_experiment.experiment_id, "user1")
        report = ab_service.get_report(running_experiment.experiment_id)
        total_adoptions = sum(m.adoptions for m in report.variant_metrics.values())
        assert total_adoptions == 1

    def test_record_dismissal(self, ab_service, running_experiment):
        ab_service.record_impression(running_experiment.experiment_id, "user1")
        ab_service.record_dismissal(running_experiment.experiment_id, "user1")
        report = ab_service.get_report(running_experiment.experiment_id)
        total_dismissals = sum(m.dismissals for m in report.variant_metrics.values())
        assert total_dismissals == 1

    def test_ctr_computation(self, ab_service, running_experiment):
        # Generate 10 impressions and 3 clicks for same user -> same variant
        for _ in range(10):
            ab_service.record_impression(running_experiment.experiment_id, "user1")
        for _ in range(3):
            ab_service.record_click(running_experiment.experiment_id, "user1")

        report = ab_service.get_report(running_experiment.experiment_id)
        variant = ab_service.assign_variant(running_experiment.experiment_id, "user1")
        metrics = report.variant_metrics[variant]
        assert metrics.impressions == 10
        assert metrics.clicks == 3
        assert abs(metrics.ctr - 30.0) < 0.01

    def test_metrics_not_running(self, ab_service, basic_experiment_request):
        exp = ab_service.create_experiment(basic_experiment_request)
        ab_service.record_impression(exp.experiment_id, "user1")
        # Should be no-op since experiment is not running

    def test_variant_metrics_model(self):
        m = VariantMetrics(variant_name="test", impressions=100, clicks=15, adoptions=5)
        m.compute_rates()
        assert m.ctr == 15.0
        assert m.adoption_rate == 5.0

    def test_variant_metrics_zero_impressions(self):
        m = VariantMetrics(variant_name="test")
        m.compute_rates()
        assert m.ctr == 0.0
        assert m.adoption_rate == 0.0


# ============================================================================
# Statistical significance tests
# ============================================================================


class TestStatisticalSignificance:
    """Tests for two-proportion z-test significance calculation."""

    def test_normal_cdf_values(self):
        assert abs(_normal_cdf(0) - 0.5) < 0.001
        assert _normal_cdf(3) > 0.998
        assert _normal_cdf(-3) < 0.002

    def test_significance_insufficient_data(self, ab_service, running_experiment):
        # Only a few impressions
        for i in range(10):
            ab_service.record_impression(running_experiment.experiment_id, f"u{i}")
        results = ab_service.calculate_significance(running_experiment.experiment_id)
        for r in results:
            assert not r.significant
            assert not r.sample_size_sufficient

    def test_significance_with_large_difference(self, ab_service):
        """Simulate a clear winner with enough data."""
        req = ExperimentCreateRequest(
            name="Significance Test",
            variants=[
                VariantConfig(name="control", traffic_percentage=50),
                VariantConfig(name="treatment", traffic_percentage=50),
            ],
            min_impressions=100,
        )
        exp = ab_service.create_experiment(req)
        ab_service.start_experiment(exp.experiment_id)

        # Manually set metrics
        metrics = ab_service._metrics[exp.experiment_id]
        metrics["control"].impressions = 2000
        metrics["control"].clicks = 100  # 5% CTR
        metrics["treatment"].impressions = 2000
        metrics["treatment"].clicks = 300  # 15% CTR

        results = ab_service.calculate_significance(exp.experiment_id)
        assert len(results) == 1
        assert results[0].significant
        assert results[0].winner == "treatment"
        assert results[0].p_value < 0.05

    def test_significance_no_difference(self, ab_service):
        req = ExperimentCreateRequest(
            name="No Diff Test",
            variants=[
                VariantConfig(name="a", traffic_percentage=50),
                VariantConfig(name="b", traffic_percentage=50),
            ],
            min_impressions=100,
        )
        exp = ab_service.create_experiment(req)
        ab_service.start_experiment(exp.experiment_id)

        metrics = ab_service._metrics[exp.experiment_id]
        metrics["a"].impressions = 1000
        metrics["a"].clicks = 100  # 10% CTR
        metrics["b"].impressions = 1000
        metrics["b"].clicks = 100  # 10% CTR

        results = ab_service.calculate_significance(exp.experiment_id)
        assert len(results) == 1
        assert not results[0].significant
        assert results[0].z_score == 0.0

    def test_significance_adoption_rate(self, ab_service):
        req = ExperimentCreateRequest(
            name="Adoption Test",
            variants=[
                VariantConfig(name="a", traffic_percentage=50),
                VariantConfig(name="b", traffic_percentage=50),
            ],
            min_impressions=100,
        )
        exp = ab_service.create_experiment(req)
        ab_service.start_experiment(exp.experiment_id)

        metrics = ab_service._metrics[exp.experiment_id]
        metrics["a"].impressions = 2000
        metrics["a"].adoptions = 50  # 2.5%
        metrics["b"].impressions = 2000
        metrics["b"].adoptions = 200  # 10%

        results = ab_service.calculate_significance(exp.experiment_id, metric="adoption_rate")
        assert len(results) == 1
        assert results[0].metric == "adoption_rate"
        assert results[0].significant
        assert results[0].winner == "b"

    def test_significance_zero_impressions(self, ab_service, running_experiment):
        results = ab_service.calculate_significance(running_experiment.experiment_id)
        for r in results:
            assert r.p_value == 1.0
            assert not r.significant

    def test_significance_all_zero_clicks(self, ab_service):
        """Both variants have 0 clicks — pooled proportion is 0."""
        req = ExperimentCreateRequest(
            name="Zero Clicks",
            variants=[
                VariantConfig(name="a", traffic_percentage=50),
                VariantConfig(name="b", traffic_percentage=50),
            ],
            min_impressions=100,
        )
        exp = ab_service.create_experiment(req)
        ab_service.start_experiment(exp.experiment_id)

        metrics = ab_service._metrics[exp.experiment_id]
        metrics["a"].impressions = 1000
        metrics["a"].clicks = 0
        metrics["b"].impressions = 1000
        metrics["b"].clicks = 0

        results = ab_service.calculate_significance(exp.experiment_id)
        assert not results[0].significant


# ============================================================================
# Concurrent experiments tests
# ============================================================================


class TestConcurrentExperiments:
    """Tests for multiple concurrent experiments."""

    def test_ten_concurrent_experiments(self, ab_service):
        """Should support 10+ concurrent experiments."""
        experiments = []
        for i in range(12):
            req = ExperimentCreateRequest(
                name=f"Exp {i}",
                variants=[
                    VariantConfig(name="a", traffic_percentage=50),
                    VariantConfig(name="b", traffic_percentage=50),
                ],
            )
            exp = ab_service.create_experiment(req)
            ab_service.start_experiment(exp.experiment_id)
            experiments.append(exp)

        running = ab_service.list_experiments(status=ExperimentStatus.RUNNING)
        assert len(running) == 12

    def test_max_concurrent_limit(self, ab_service):
        """Should enforce maximum concurrent experiments."""
        for i in range(MAX_CONCURRENT_EXPERIMENTS):
            req = ExperimentCreateRequest(
                name=f"Exp {i}",
                variants=[
                    VariantConfig(name="a", traffic_percentage=50),
                    VariantConfig(name="b", traffic_percentage=50),
                ],
            )
            exp = ab_service.create_experiment(req)
            ab_service.start_experiment(exp.experiment_id)

        # 21st running experiment should fail
        req = ExperimentCreateRequest(
            name="One Too Many",
            variants=[
                VariantConfig(name="a", traffic_percentage=50),
                VariantConfig(name="b", traffic_percentage=50),
            ],
        )
        with pytest.raises(ValueError, match="concurrent"):
            ab_service.create_experiment(req)

    def test_users_tracked_per_experiment(self, ab_service):
        exp1_req = ExperimentCreateRequest(
            name="Exp 1",
            variants=[
                VariantConfig(name="a", traffic_percentage=50),
                VariantConfig(name="b", traffic_percentage=50),
            ],
        )
        exp2_req = ExperimentCreateRequest(
            name="Exp 2",
            variants=[
                VariantConfig(name="x", traffic_percentage=50),
                VariantConfig(name="y", traffic_percentage=50),
            ],
        )
        exp1 = ab_service.create_experiment(exp1_req)
        exp2 = ab_service.create_experiment(exp2_req)
        ab_service.start_experiment(exp1.experiment_id)
        ab_service.start_experiment(exp2.experiment_id)

        v1 = ab_service.assign_variant(exp1.experiment_id, "user1")
        v2 = ab_service.assign_variant(exp2.experiment_id, "user1")

        assert v1 in ["a", "b"]
        assert v2 in ["x", "y"]


# ============================================================================
# Report tests
# ============================================================================


class TestExperimentReport:
    """Tests for experiment reporting."""

    def test_report_running(self, ab_service, running_experiment):
        report = ab_service.get_report(running_experiment.experiment_id)
        assert report.experiment_id == running_experiment.experiment_id
        assert report.status == ExperimentStatus.RUNNING

    def test_report_with_metrics(self, ab_service, running_experiment):
        for i in range(20):
            ab_service.record_impression(running_experiment.experiment_id, f"u{i}")
            if i % 3 == 0:
                ab_service.record_click(running_experiment.experiment_id, f"u{i}")

        report = ab_service.get_report(running_experiment.experiment_id)
        assert report.total_impressions == 20

    def test_report_recommendation_insufficient_data(self, ab_service, running_experiment):
        report = ab_service.get_report(running_experiment.experiment_id)
        assert "more data" in report.recommendation.lower() or "no statistically" in report.recommendation.lower()

    def test_report_nonexistent(self, ab_service):
        with pytest.raises(KeyError):
            ab_service.get_report("nonexistent")

    def test_report_duration(self, ab_service, running_experiment):
        report = ab_service.get_report(running_experiment.experiment_id)
        assert report.duration_hours is not None
        assert report.duration_hours >= 0

    def test_report_completed_experiment(self, ab_service, running_experiment):
        ab_service.complete_experiment(running_experiment.experiment_id)
        report = ab_service.get_report(running_experiment.experiment_id)
        assert report.status == ExperimentStatus.COMPLETED


# ============================================================================
# Pydantic model tests
# ============================================================================


class TestPydanticModels:
    """Tests for A/B testing Pydantic models."""

    def test_experiment_config(self):
        config = ExperimentConfig(
            experiment_id="exp1",
            name="Test",
            variants=[
                VariantConfig(name="a", traffic_percentage=50),
                VariantConfig(name="b", traffic_percentage=50),
            ],
        )
        assert config.status == ExperimentStatus.DRAFT
        assert config.created_at is not None

    def test_variant_config(self):
        v = VariantConfig(
            name="treatment",
            traffic_percentage=60,
            weight_overrides={"semantic": 0.5},
            description="60% traffic",
        )
        assert v.traffic_percentage == 60

    def test_significance_result(self):
        r = SignificanceResult(
            variant_a="a",
            variant_b="b",
            metric="ctr",
            z_score=2.5,
            p_value=0.012,
            significant=True,
            confidence_level=98.8,
            winner="b",
            sample_size_sufficient=True,
        )
        assert r.significant
        assert r.winner == "b"

    def test_experiment_status_enum(self):
        assert ExperimentStatus.DRAFT == "draft"
        assert ExperimentStatus.RUNNING == "running"
        assert ExperimentStatus.PAUSED == "paused"
        assert ExperimentStatus.COMPLETED == "completed"
