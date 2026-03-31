# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/crt_router/test_crt_router.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Comprehensive tests for the CRT Router plugin.

Coverage
--------
- models.py  : DifficultyBin, ToolCalibration, CalibrationArtifact, ToolRelevanceScore
- semantic_router.py : CRTRouter (init, factories, rank_tools, all internal primitives)
"""

# Standard
import json
import math
from pathlib import Path

# Third-Party
import numpy as np
import pytest

# First-Party
from plugins.crt_router.models import (
    CalibrationArtifact,
    DifficultyBin,
    ToolCalibration,
    ToolRelevanceScore,
    _is_prime,
)
from plugins.crt_router.semantic_router import DEFAULT_PRIMES, CRTRouter


# ===========================================================================
# Shared fixtures
# ===========================================================================


@pytest.fixture
def simple_primes():
    return [7, 11, 13]


@pytest.fixture
def unit_embeddings():
    """Three 3-dimensional unit vectors pointing along each axis."""
    return {
        "tool_a": [1.0, 0.0, 0.0],
        "tool_b": [0.0, 1.0, 0.0],
        "tool_c": [0.0, 0.0, 1.0],
    }


@pytest.fixture
def tool_calibrations(unit_embeddings):
    return {
        name: ToolCalibration(
            tool_name=name,
            reference_embedding=emb,
            prior=1.0,
            success_rates={0: 0.9, 1: 0.6, 2: 0.3},
        )
        for name, emb in unit_embeddings.items()
    }


@pytest.fixture
def difficulty_bins():
    return [
        DifficultyBin(bin_id=0, label="easy", min_score=0.0, max_score=0.33),
        DifficultyBin(bin_id=1, label="medium", min_score=0.33, max_score=0.67),
        DifficultyBin(bin_id=2, label="hard", min_score=0.67, max_score=1.0),
    ]


@pytest.fixture
def calibration_artifact(tool_calibrations, difficulty_bins, simple_primes):
    return CalibrationArtifact(
        primes=simple_primes,
        alpha=0.6,
        beta=0.4,
        tools=tool_calibrations,
        difficulty_bins=difficulty_bins,
    )


@pytest.fixture
def router(calibration_artifact):
    return CRTRouter(calibration_artifact)


# ===========================================================================
# 1. Helper function: _is_prime
# ===========================================================================


class TestIsPrime:
    def test_small_primes_are_prime(self):
        for p in [2, 3, 5, 7, 11, 13, 17, 19, 23, 29]:
            assert _is_prime(p), f"{p} should be prime"

    def test_composites_are_not_prime(self):
        for n in [1, 4, 6, 8, 9, 10, 12, 15, 100]:
            assert not _is_prime(n), f"{n} should not be prime"

    def test_zero_and_one_are_not_prime(self):
        assert not _is_prime(0)
        assert not _is_prime(1)

    def test_two_is_prime(self):
        assert _is_prime(2)

    def test_large_prime(self):
        assert _is_prime(97)
        assert _is_prime(101)

    def test_large_composite(self):
        assert not _is_prime(100)
        assert not _is_prime(99)


# ===========================================================================
# 2. DifficultyBin model
# ===========================================================================


class TestDifficultyBin:
    def test_valid_creation(self):
        b = DifficultyBin(bin_id=0, label="easy", min_score=0.0, max_score=0.5)
        assert b.bin_id == 0
        assert b.label == "easy"
        assert b.min_score == 0.0
        assert b.max_score == 0.5

    def test_min_equals_max_is_allowed(self):
        b = DifficultyBin(bin_id=1, label="exact", min_score=0.5, max_score=0.5)
        assert b.min_score == b.max_score == 0.5

    def test_min_exceeds_max_raises(self):
        with pytest.raises(ValueError, match="min_score"):
            DifficultyBin(bin_id=0, label="bad", min_score=0.8, max_score=0.2)

    def test_boundary_values(self):
        b = DifficultyBin(bin_id=2, label="full", min_score=0.0, max_score=1.0)
        assert b.min_score == 0.0
        assert b.max_score == 1.0

    def test_bin_id_must_be_non_negative(self):
        with pytest.raises(ValueError):
            DifficultyBin(bin_id=-1, label="x", min_score=0.0, max_score=1.0)

    def test_label_must_not_be_empty(self):
        with pytest.raises(ValueError):
            DifficultyBin(bin_id=0, label="", min_score=0.0, max_score=1.0)

    def test_scores_out_of_range(self):
        with pytest.raises(ValueError):
            DifficultyBin(bin_id=0, label="x", min_score=-0.1, max_score=1.0)
        with pytest.raises(ValueError):
            DifficultyBin(bin_id=0, label="x", min_score=0.0, max_score=1.1)


# ===========================================================================
# 3. ToolCalibration model
# ===========================================================================


class TestToolCalibration:
    def test_minimal_valid(self):
        tc = ToolCalibration(tool_name="my_tool", reference_embedding=[0.1, 0.2])
        assert tc.tool_name == "my_tool"
        assert tc.prior == 1.0
        assert tc.success_rates == {}

    def test_custom_prior(self):
        tc = ToolCalibration(tool_name="t", reference_embedding=[1.0], prior=0.3)
        assert tc.prior == pytest.approx(0.3)

    def test_prior_must_be_positive(self):
        with pytest.raises(ValueError):
            ToolCalibration(tool_name="t", reference_embedding=[1.0], prior=0.0)
        with pytest.raises(ValueError):
            ToolCalibration(tool_name="t", reference_embedding=[1.0], prior=-1.0)

    def test_reference_embedding_must_be_non_empty(self):
        with pytest.raises(ValueError):
            ToolCalibration(tool_name="t", reference_embedding=[])

    def test_success_rates_with_int_keys(self):
        tc = ToolCalibration(tool_name="t", reference_embedding=[0.5], success_rates={0: 0.9, 2: 0.3})
        assert tc.success_rates[0] == pytest.approx(0.9)
        assert tc.success_rates[2] == pytest.approx(0.3)

    def test_success_rates_coerced_from_string_keys(self):
        """JSON round-trip converts int keys to strings; validator must convert back."""
        tc = ToolCalibration(
            tool_name="t",
            reference_embedding=[0.5],
            success_rates={"0": "0.8", "1": "0.5"},  # type: ignore[arg-type]
        )
        assert 0 in tc.success_rates
        assert 1 in tc.success_rates
        assert tc.success_rates[0] == pytest.approx(0.8)

    def test_success_rate_out_of_range_raises(self):
        with pytest.raises(ValueError):
            ToolCalibration(tool_name="t", reference_embedding=[0.5], success_rates={0: 1.5})
        with pytest.raises(ValueError):
            ToolCalibration(tool_name="t", reference_embedding=[0.5], success_rates={0: -0.1})

    def test_valid_high_dim_embedding(self):
        emb = list(np.random.default_rng(42).random(1536))
        tc = ToolCalibration(tool_name="big", reference_embedding=emb)
        assert len(tc.reference_embedding) == 1536


# ===========================================================================
# 4. CalibrationArtifact model
# ===========================================================================


class TestCalibrationArtifact:
    def test_minimal_valid(self):
        art = CalibrationArtifact(primes=[7])
        assert art.version == "1.0"
        assert art.primes == [7]
        assert art.alpha == pytest.approx(0.6)
        assert art.beta == pytest.approx(0.4)
        assert art.tools == {}
        assert art.difficulty_bins == []

    def test_primes_must_be_non_empty(self):
        with pytest.raises(ValueError):
            CalibrationArtifact(primes=[])

    def test_non_prime_in_primes_raises(self):
        with pytest.raises(ValueError, match="not a prime"):
            CalibrationArtifact(primes=[7, 9, 11])

    def test_one_is_not_prime(self):
        with pytest.raises(ValueError):
            CalibrationArtifact(primes=[1])

    def test_zero_is_not_prime(self):
        with pytest.raises(ValueError):
            CalibrationArtifact(primes=[0, 7])

    def test_alpha_beta_out_of_range(self):
        with pytest.raises(ValueError):
            CalibrationArtifact(primes=[7], alpha=1.5)
        with pytest.raises(ValueError):
            CalibrationArtifact(primes=[7], alpha=-0.1)
        with pytest.raises(ValueError):
            CalibrationArtifact(primes=[7], beta=2.0)

    def test_quantization_scale_must_be_positive(self):
        with pytest.raises(ValueError):
            CalibrationArtifact(primes=[7], quantization_scale=0.0)
        with pytest.raises(ValueError):
            CalibrationArtifact(primes=[7], quantization_scale=-500.0)

    def test_full_construction(self, calibration_artifact):
        art = calibration_artifact
        assert len(art.tools) == 3
        assert len(art.difficulty_bins) == 3
        assert "tool_a" in art.tools

    def test_json_roundtrip(self, calibration_artifact):
        data = calibration_artifact.model_dump()
        restored = CalibrationArtifact.model_validate(data)
        assert restored.primes == calibration_artifact.primes
        assert set(restored.tools.keys()) == set(calibration_artifact.tools.keys())
        assert restored.alpha == pytest.approx(calibration_artifact.alpha)

    def test_success_rates_preserved_through_json_roundtrip(self, calibration_artifact):
        data = calibration_artifact.model_dump()
        restored = CalibrationArtifact.model_validate(data)
        for name, tc in restored.tools.items():
            original = calibration_artifact.tools[name]
            assert tc.success_rates == original.success_rates

    def test_tools_with_empty_success_rates(self):
        art = CalibrationArtifact(
            primes=[7, 11],
            tools={
                "t": ToolCalibration(tool_name="t", reference_embedding=[1.0, 0.0])
            },
        )
        assert art.tools["t"].success_rates == {}


# ===========================================================================
# 5. ToolRelevanceScore model
# ===========================================================================


class TestToolRelevanceScore:
    def _make(self, **overrides):
        defaults = dict(
            tool_name="weather",
            rank=1,
            relevance_score=0.85,
            cosine_similarity=0.9,
            crt_score=0.7,
            posterior_score=0.5,
            difficulty_bin=0,
            prior=0.5,
        )
        defaults.update(overrides)
        return ToolRelevanceScore(**defaults)

    def test_valid_creation(self):
        s = self._make()
        assert s.tool_name == "weather"
        assert s.rank == 1
        assert s.relevance_score == pytest.approx(0.85)

    def test_rank_must_be_at_least_one(self):
        with pytest.raises(ValueError):
            self._make(rank=0)

    def test_relevance_score_bounds(self):
        with pytest.raises(ValueError):
            self._make(relevance_score=-0.1)
        with pytest.raises(ValueError):
            self._make(relevance_score=1.1)

    def test_cosine_similarity_bounds(self):
        with pytest.raises(ValueError):
            self._make(cosine_similarity=-0.1)
        with pytest.raises(ValueError):
            self._make(cosine_similarity=1.1)

    def test_crt_score_bounds(self):
        with pytest.raises(ValueError):
            self._make(crt_score=-0.01)
        with pytest.raises(ValueError):
            self._make(crt_score=1.01)

    def test_posterior_score_non_negative(self):
        with pytest.raises(ValueError):
            self._make(posterior_score=-0.1)

    def test_prior_must_be_positive(self):
        with pytest.raises(ValueError):
            self._make(prior=0.0)

    def test_difficulty_bin_non_negative(self):
        with pytest.raises(ValueError):
            self._make(difficulty_bin=-1)

    def test_boundary_values_accepted(self):
        s = self._make(relevance_score=0.0, cosine_similarity=0.0, crt_score=0.0)
        assert s.relevance_score == 0.0
        s2 = self._make(relevance_score=1.0, cosine_similarity=1.0, crt_score=1.0)
        assert s2.relevance_score == 1.0


# ===========================================================================
# 6. CRTRouter initialisation
# ===========================================================================


class TestCRTRouterInit:
    def test_init_from_calibration_artifact(self, calibration_artifact):
        router = CRTRouter(calibration_artifact)
        assert router.calibration is calibration_artifact

    def test_precomputes_residues_for_all_tools(self, calibration_artifact):
        router = CRTRouter(calibration_artifact)
        # All tool names should have pre-computed residues.
        for name in calibration_artifact.tools:
            assert name in router._tool_residues
            assert len(router._tool_residues[name]) == len(calibration_artifact.primes)

    def test_tool_names_property(self, router, unit_embeddings):
        assert set(router.tool_names) == set(unit_embeddings.keys())

    def test_calibration_property_is_same_object(self, router, calibration_artifact):
        assert router.calibration is calibration_artifact

    def test_primes_stored_correctly(self, router, simple_primes):
        assert router._primes == simple_primes

    def test_alpha_beta_stored(self, router):
        assert router._alpha == pytest.approx(0.6)
        assert router._beta == pytest.approx(0.4)


# ===========================================================================
# 7. CRTRouter.from_json
# ===========================================================================


class TestCRTRouterFromJson:
    def test_loads_valid_json(self, calibration_artifact, tmp_path):
        p = tmp_path / "cal.json"
        p.write_text(
            json.dumps(calibration_artifact.model_dump()),
            encoding="utf-8",
        )
        router = CRTRouter.from_json(p)
        assert set(router.tool_names) == set(calibration_artifact.tools.keys())

    def test_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            CRTRouter.from_json(tmp_path / "nonexistent.json")

    def test_raises_on_invalid_json(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("not json {{{", encoding="utf-8")
        with pytest.raises(ValueError, match="Invalid JSON"):
            CRTRouter.from_json(p)

    def test_raises_on_invalid_schema(self, tmp_path):
        """JSON parses but fails Pydantic validation (non-prime in primes)."""
        p = tmp_path / "invalid_schema.json"
        p.write_text(json.dumps({"primes": [4, 9]}), encoding="utf-8")
        with pytest.raises(ValueError):
            CRTRouter.from_json(p)

    def test_accepts_string_path(self, calibration_artifact, tmp_path):
        p = tmp_path / "cal.json"
        p.write_text(json.dumps(calibration_artifact.model_dump()), encoding="utf-8")
        # Pass as str, not Path.
        router = CRTRouter.from_json(str(p))
        assert len(router.tool_names) == 3

    def test_restored_router_produces_same_scores(self, calibration_artifact, tmp_path):
        p = tmp_path / "cal.json"
        p.write_text(json.dumps(calibration_artifact.model_dump()), encoding="utf-8")
        router1 = CRTRouter(calibration_artifact)
        router2 = CRTRouter.from_json(p)
        emb = [1.0, 0.0, 0.0]
        s1 = router1.rank_tools(emb)
        s2 = router2.rank_tools(emb)
        assert len(s1) == len(s2)
        for a, b in zip(s1, s2):
            assert a.tool_name == b.tool_name
            assert a.relevance_score == pytest.approx(b.relevance_score)


# ===========================================================================
# 8. CRTRouter.from_tool_embeddings
# ===========================================================================


class TestCRTRouterFromToolEmbeddings:
    def test_creates_router_from_embeddings(self, unit_embeddings):
        router = CRTRouter.from_tool_embeddings(unit_embeddings)
        assert set(router.tool_names) == set(unit_embeddings.keys())

    def test_uses_uniform_priors(self, unit_embeddings):
        router = CRTRouter.from_tool_embeddings(unit_embeddings)
        n = len(unit_embeddings)
        for name in router.tool_names:
            assert router.calibration.tools[name].prior == pytest.approx(1.0 / n)

    def test_uses_default_primes_when_none_provided(self, unit_embeddings):
        router = CRTRouter.from_tool_embeddings(unit_embeddings)
        assert router._primes == DEFAULT_PRIMES

    def test_custom_primes_accepted(self, unit_embeddings):
        router = CRTRouter.from_tool_embeddings(unit_embeddings, primes=[3, 5, 7])
        assert router._primes == [3, 5, 7]

    def test_custom_alpha_beta(self, unit_embeddings):
        router = CRTRouter.from_tool_embeddings(unit_embeddings, alpha=0.8, beta=0.2)
        assert router._alpha == pytest.approx(0.8)
        assert router._beta == pytest.approx(0.2)

    def test_empty_dict_creates_empty_router(self):
        router = CRTRouter.from_tool_embeddings({})
        assert router.tool_names == []
        # rank_tools with no calibrated tools returns []
        result = router.rank_tools([0.5, 0.5])
        assert result == []

    def test_single_tool(self):
        router = CRTRouter.from_tool_embeddings({"only": [1.0, 0.0]})
        scores = router.rank_tools([1.0, 0.0])
        assert len(scores) == 1
        assert scores[0].tool_name == "only"
        assert scores[0].rank == 1


# ===========================================================================
# 9. CRTRouter.rank_tools — input validation
# ===========================================================================


class TestRankToolsValidation:
    def test_empty_embedding_raises(self, router):
        with pytest.raises(ValueError, match="non-empty"):
            router.rank_tools([])

    def test_k_less_than_one_raises(self, router):
        with pytest.raises(ValueError, match="at least 1"):
            router.rank_tools([1.0, 0.0, 0.0], k=0)

    def test_k_negative_raises(self, router):
        with pytest.raises(ValueError):
            router.rank_tools([1.0, 0.0, 0.0], k=-5)

    def test_threshold_above_one_raises(self, router):
        with pytest.raises(ValueError, match="threshold"):
            router.rank_tools([1.0, 0.0, 0.0], threshold=1.1)

    def test_threshold_below_zero_raises(self, router):
        with pytest.raises(ValueError, match="threshold"):
            router.rank_tools([1.0, 0.0, 0.0], threshold=-0.01)

    def test_threshold_zero_accepted(self, router):
        result = router.rank_tools([1.0, 0.0, 0.0], threshold=0.0)
        assert isinstance(result, list)

    def test_threshold_one_accepted(self, router):
        # May return empty if no score is exactly 1.0; must not raise.
        result = router.rank_tools([1.0, 0.0, 0.0], threshold=1.0)
        assert isinstance(result, list)

    def test_k_one_returns_at_most_one(self, router):
        result = router.rank_tools([1.0, 0.0, 0.0], k=1)
        assert len(result) <= 1


# ===========================================================================
# 10. CRTRouter.rank_tools — result properties
# ===========================================================================


class TestRankToolsResults:
    def test_returns_list_of_tool_relevance_scores(self, router):
        results = router.rank_tools([1.0, 0.0, 0.0])
        assert all(isinstance(r, ToolRelevanceScore) for r in results)

    def test_sorted_by_relevance_descending(self, router):
        results = router.rank_tools([1.0, 0.0, 0.0])
        scores = [r.relevance_score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_ranks_are_sequential_starting_at_one(self, router):
        results = router.rank_tools([1.0, 0.0, 0.0])
        assert [r.rank for r in results] == list(range(1, len(results) + 1))

    def test_relevance_scores_in_unit_interval(self, router):
        results = router.rank_tools([1.0, 0.0, 0.0])
        for r in results:
            assert 0.0 <= r.relevance_score <= 1.0

    def test_cosine_similarity_in_unit_interval(self, router):
        results = router.rank_tools([1.0, 0.0, 0.0])
        for r in results:
            assert 0.0 <= r.cosine_similarity <= 1.0

    def test_crt_score_in_unit_interval(self, router):
        results = router.rank_tools([1.0, 0.0, 0.0])
        for r in results:
            assert 0.0 <= r.crt_score <= 1.0

    def test_k_limits_output(self, router):
        results = router.rank_tools([1.0, 0.0, 0.0], k=2)
        assert len(results) <= 2

    def test_k_larger_than_tools_returns_all(self, router):
        results = router.rank_tools([1.0, 0.0, 0.0], k=100)
        assert len(results) == 3  # only 3 tools calibrated

    def test_threshold_filters_low_scores(self, router):
        results_all = router.rank_tools([1.0, 0.0, 0.0], threshold=0.0)
        results_filtered = router.rank_tools([1.0, 0.0, 0.0], threshold=0.5)
        assert len(results_filtered) <= len(results_all)
        for r in results_filtered:
            assert r.relevance_score >= 0.5

    def test_available_tools_filters_candidates(self, router):
        results = router.rank_tools([1.0, 0.0, 0.0], available_tools=["tool_a"])
        assert all(r.tool_name == "tool_a" for r in results)
        assert len(results) == 1

    def test_available_tools_none_includes_all(self, router):
        results = router.rank_tools([1.0, 0.0, 0.0], available_tools=None)
        assert len(results) == 3

    def test_uncalibrated_tools_silently_skipped(self, router):
        results = router.rank_tools([1.0, 0.0, 0.0], available_tools=["tool_a", "ghost_tool"])
        names = [r.tool_name for r in results]
        assert "ghost_tool" not in names
        assert "tool_a" in names

    def test_all_uncalibrated_tools_returns_empty(self, router):
        results = router.rank_tools([1.0, 0.0, 0.0], available_tools=["x", "y", "z"])
        assert results == []

    def test_empty_available_tools_returns_empty(self, router):
        results = router.rank_tools([1.0, 0.0, 0.0], available_tools=[])
        assert results == []

    def test_available_tools_deduplicates(self, router):
        results = router.rank_tools([1.0, 0.0, 0.0], available_tools=["tool_a", "tool_a", "tool_a"])
        names = [r.tool_name for r in results]
        assert names.count("tool_a") == 1

    def test_explainability_fields_populated(self, router):
        results = router.rank_tools([1.0, 0.0, 0.0])
        for r in results:
            assert r.tool_name != ""
            assert r.difficulty_bin >= 0
            assert r.prior > 0.0

    def test_top_result_is_most_similar_tool(self):
        """With alpha=1, beta=0 the top result should be the most cosine-similar tool."""
        embeddings = {
            "close": [0.99, 0.14, 0.0],
            "far":   [0.0, 0.0, 1.0],
        }
        router = CRTRouter.from_tool_embeddings(embeddings, alpha=1.0, beta=0.0)
        results = router.rank_tools([1.0, 0.0, 0.0])
        assert results[0].tool_name == "close"

    def test_difficulty_bin_recorded_in_results(self, router):
        results = router.rank_tools([1.0, 0.0, 0.0])
        # All results for the same query should share the same difficulty bin.
        bins = {r.difficulty_bin for r in results}
        assert len(bins) == 1


# ===========================================================================
# 11. Determinism
# ===========================================================================


class TestDeterminism:
    def test_same_input_same_output(self, router):
        emb = [0.5, 0.3, 0.8]
        r1 = router.rank_tools(emb)
        r2 = router.rank_tools(emb)
        for a, b in zip(r1, r2):
            assert a.tool_name == b.tool_name
            assert a.relevance_score == pytest.approx(b.relevance_score)

    def test_different_embeddings_may_differ(self, router):
        r1 = router.rank_tools([1.0, 0.0, 0.0])
        r2 = router.rank_tools([0.0, 1.0, 0.0])
        # tool_a should rank first for [1,0,0], tool_b for [0,1,0].
        assert r1[0].tool_name == "tool_a"
        assert r2[0].tool_name == "tool_b"

    def test_repeated_calls_identical(self, router):
        emb = list(np.random.default_rng(0).random(3))
        results = [router.rank_tools(emb) for _ in range(5)]
        for later in results[1:]:
            for a, b in zip(results[0], later):
                assert a.relevance_score == pytest.approx(b.relevance_score)


# ===========================================================================
# 12. CRTRouter._compute_residues
# ===========================================================================


class TestComputeResidues:
    def test_returns_one_residue_per_prime(self, router):
        residues = router._compute_residues([0.5, 0.3, 0.1])
        assert len(residues) == len(router._primes)

    def test_deterministic(self, router):
        emb = [0.1, 0.2, 0.3]
        r1 = router._compute_residues(emb)
        r2 = router._compute_residues(emb)
        assert r1 == r2

    def test_residues_in_valid_range(self, router):
        residues = router._compute_residues([1.5, -0.3, 0.0])
        for residue, prime in zip(residues, router._primes):
            assert 0 <= residue < prime

    def test_different_embeddings_differ(self, router):
        r1 = router._compute_residues([1.0, 0.0, 0.0])
        r2 = router._compute_residues([0.0, 1.0, 0.0])
        # At least one residue should differ (not a hard guarantee, but true
        # with high probability for these orthogonal inputs).
        assert r1 != r2

    def test_zero_embedding(self, router):
        residues = router._compute_residues([0.0, 0.0, 0.0])
        # Zero vector → all projections are 0.
        assert all(r == 0 for r in residues)

    def test_high_value_embedding_valid(self, router):
        residues = router._compute_residues([100.0, 200.0, 300.0])
        for residue, prime in zip(residues, router._primes):
            assert 0 <= residue < prime

    def test_negative_values_handled(self, router):
        residues = router._compute_residues([-0.5, -0.3, -0.1])
        for residue, prime in zip(residues, router._primes):
            assert 0 <= residue < prime


# ===========================================================================
# 13. CRTRouter._compute_crt_score
# ===========================================================================


class TestComputeCrtScore:
    def test_identical_residues_give_positive_score(self, router):
        residues = [3, 5, 7]
        score = router._compute_crt_score(residues, residues)
        assert score > 0.0

    def test_identical_residues_give_score_one(self, router):
        """When all residues match, the score should be 1.0."""
        residues = router._compute_residues([0.5, 0.5, 0.5])
        score = router._compute_crt_score(residues, residues)
        assert score == pytest.approx(1.0)

    def test_all_different_residues_give_zero(self, router):
        """Craft residues that never match any prime bucket."""
        primes = router._primes
        query = [0] * len(primes)
        tool = [(p - 1) for p in primes]  # guaranteed ≠ 0 for all primes ≥ 2
        score = router._compute_crt_score(query, tool)
        assert score == pytest.approx(0.0)

    def test_score_in_unit_interval(self, router):
        r1 = [1, 2, 3]
        r2 = [1, 9, 3]
        score = router._compute_crt_score(r1, r2)
        assert 0.0 <= score <= 1.0

    def test_empty_residues_return_zero(self, router):
        assert router._compute_crt_score([], []) == 0.0

    def test_larger_primes_contribute_more(self):
        """With primes [3, 97], matching only on 97 should give a higher score
        than matching only on 3."""
        artifact = CalibrationArtifact(
            primes=[3, 97],
            tools={"t": ToolCalibration(tool_name="t", reference_embedding=[1.0])},
        )
        router = CRTRouter(artifact)

        # Match on large prime only (index 1), miss on small prime (index 0).
        score_large = router._compute_crt_score([0, 5], [1, 5])   # match on 97
        score_small = router._compute_crt_score([0, 5], [0, 9])   # match on  3
        assert score_large > score_small

    def test_partial_match_intermediate_score(self, router):
        r_query = router._compute_residues([1.0, 0.0, 0.0])
        r_same = r_query[:]
        # Corrupt one residue.
        r_different = r_query[:]
        r_different[0] = (r_different[0] + 1) % router._primes[0]

        score_full = router._compute_crt_score(r_query, r_same)
        score_part = router._compute_crt_score(r_query, r_different)
        assert score_part < score_full


# ===========================================================================
# 14. CRTRouter._cosine_similarity
# ===========================================================================


class TestCosineSimilarity:
    def test_identical_vectors_give_one(self, router):
        assert router._cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)

    def test_opposite_vectors_clamped_to_zero(self, router):
        # Raw cosine = -1, clamped to 0.
        assert router._cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(0.0)

    def test_perpendicular_vectors_give_zero(self, router):
        assert router._cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_zero_vector_a_gives_zero(self, router):
        assert router._cosine_similarity([0.0, 0.0], [1.0, 0.0]) == pytest.approx(0.0)

    def test_zero_vector_b_gives_zero(self, router):
        assert router._cosine_similarity([1.0, 0.0], [0.0, 0.0]) == pytest.approx(0.0)

    def test_parallel_different_magnitudes(self, router):
        # [2, 0] and [5, 0] are parallel → cos = 1.
        assert router._cosine_similarity([2.0, 0.0], [5.0, 0.0]) == pytest.approx(1.0)

    def test_arbitrary_vectors(self, router):
        a = [0.6, 0.8]   # unit vector
        b = [0.6, 0.8]   # same
        assert router._cosine_similarity(a, b) == pytest.approx(1.0)

    def test_result_always_in_unit_interval(self, router):
        rng = np.random.default_rng(1)
        for _ in range(20):
            a = rng.standard_normal(10).tolist()
            b = rng.standard_normal(10).tolist()
            sim = router._cosine_similarity(a, b)
            assert 0.0 <= sim <= 1.0

    def test_static_method_accessible_without_instance(self):
        result = CRTRouter._cosine_similarity([1.0], [1.0])
        assert result == pytest.approx(1.0)


# ===========================================================================
# 15. CRTRouter._classify_difficulty
# ===========================================================================


class TestClassifyDifficulty:
    def test_no_bins_returns_zero(self):
        art = CalibrationArtifact(primes=[7], difficulty_bins=[])
        router = CRTRouter(art)
        assert router._classify_difficulty([1.0, 2.0]) == 0

    def test_low_norm_maps_to_easy_bin(self, router):
        # Very small embedding → norm ≈ 0 → tanh(0) = 0 → easy bin (0.0–0.33).
        bin_id = router._classify_difficulty([0.001, 0.001, 0.001])
        assert bin_id == 0

    def test_high_norm_maps_to_hard_bin(self, router):
        # Large embedding → norm >> 1 → tanh → ~1 → hard bin (0.67–1.0).
        bin_id = router._classify_difficulty([100.0, 100.0, 100.0])
        assert bin_id == 2

    def test_medium_norm_maps_to_medium_bin(self, router):
        # Craft embedding whose tanh(norm) ≈ 0.5 (medium 0.33–0.67).
        # norm = atanh(0.5) ≈ 0.549 → single component ≈ [0.549].
        target_norm = math.atanh(0.5)
        emb = [target_norm, 0.0, 0.0]
        bin_id = router._classify_difficulty(emb)
        assert bin_id == 1

    def test_beyond_all_bins_returns_last(self):
        """An embedding that falls outside every bin's range → last bin."""
        # Create bins that don't cover the full [0,1] range.
        bins = [
            DifficultyBin(bin_id=0, label="partial", min_score=0.0, max_score=0.3),
        ]
        art = CalibrationArtifact(primes=[7], difficulty_bins=bins)
        router = CRTRouter(art)
        # Large embedding → tanh ≈ 1.0, outside [0, 0.3].
        bin_id = router._classify_difficulty([1000.0])
        assert bin_id == 0  # only one bin, so falls back to it

    def test_boundary_value_included_in_bin(self, router):
        # tanh(0) == 0.0 which is the min of the "easy" bin.
        bin_id = router._classify_difficulty([0.0, 0.0, 0.0])
        assert bin_id == 0


# ===========================================================================
# 16. CRTRouter._fuse_posteriors
# ===========================================================================


class TestFusePosteriurs:
    def _make_tool_cal(self, prior=1.0, success_rates=None):
        return ToolCalibration(
            tool_name="t",
            reference_embedding=[1.0],
            prior=prior,
            success_rates=success_rates or {},
        )

    def test_higher_prior_yields_higher_posterior(self, router):
        tc_low = self._make_tool_cal(prior=0.1, success_rates={0: 0.8})
        tc_high = self._make_tool_cal(prior=0.9, success_rates={0: 0.8})
        p_low = router._fuse_posteriors(tc_low, cos_sim=0.7, crt_score=0.5, difficulty_bin=0)
        p_high = router._fuse_posteriors(tc_high, cos_sim=0.7, crt_score=0.5, difficulty_bin=0)
        assert p_high > p_low

    def test_higher_success_rate_yields_higher_posterior(self, router):
        tc = self._make_tool_cal(prior=1.0, success_rates={0: 0.9, 1: 0.2})
        p0 = router._fuse_posteriors(tc, cos_sim=0.7, crt_score=0.5, difficulty_bin=0)
        p1 = router._fuse_posteriors(tc, cos_sim=0.7, crt_score=0.5, difficulty_bin=1)
        assert p0 > p1

    def test_missing_bin_defaults_to_0_5(self, router):
        tc = self._make_tool_cal(prior=1.0, success_rates={})  # no rates calibrated
        posterior = router._fuse_posteriors(tc, cos_sim=0.8, crt_score=0.6, difficulty_bin=99)
        # success_rate defaults to 0.5; posterior = 1.0 * 0.5 * (0.6*0.8 + 0.4*0.6)
        expected = 1.0 * 0.5 * (0.6 * 0.8 + 0.4 * 0.6)
        assert posterior == pytest.approx(expected)

    def test_alpha_one_beta_zero_uses_only_cosine(self, calibration_artifact):
        art = CalibrationArtifact(
            primes=[7], alpha=1.0, beta=0.0,
            tools={"t": ToolCalibration(tool_name="t", reference_embedding=[1.0])},
        )
        router = CRTRouter(art)
        tc = art.tools["t"]
        p = router._fuse_posteriors(tc, cos_sim=0.8, crt_score=0.0, difficulty_bin=0)
        expected = tc.prior * 0.5 * 0.8  # 0.5 = default success_rate
        assert p == pytest.approx(expected)

    def test_alpha_zero_beta_one_uses_only_crt(self, calibration_artifact):
        art = CalibrationArtifact(
            primes=[7], alpha=0.0, beta=1.0,
            tools={"t": ToolCalibration(tool_name="t", reference_embedding=[1.0])},
        )
        router = CRTRouter(art)
        tc = art.tools["t"]
        p = router._fuse_posteriors(tc, cos_sim=0.0, crt_score=0.9, difficulty_bin=0)
        expected = tc.prior * 0.5 * 0.9
        assert p == pytest.approx(expected)

    def test_zero_cosine_and_crt_gives_zero_posterior(self, router):
        tc = self._make_tool_cal(prior=1.0, success_rates={})
        p = router._fuse_posteriors(tc, cos_sim=0.0, crt_score=0.0, difficulty_bin=0)
        assert p == pytest.approx(0.0)


# ===========================================================================
# 17. CRTRouter.save_json
# ===========================================================================


class TestSaveJson:
    def test_creates_file(self, router, tmp_path):
        p = tmp_path / "out.json"
        router.save_json(p)
        assert p.exists()

    def test_file_contains_valid_json(self, router, tmp_path):
        p = tmp_path / "out.json"
        router.save_json(p)
        with p.open() as f:
            data = json.load(f)
        assert "primes" in data
        assert "tools" in data

    def test_round_trip_via_save_and_load(self, router, tmp_path):
        p = tmp_path / "round.json"
        router.save_json(p)
        restored = CRTRouter.from_json(p)
        assert set(restored.tool_names) == set(router.tool_names)
        assert restored.calibration.primes == router.calibration.primes
        assert restored._alpha == pytest.approx(router._alpha)

    def test_creates_parent_directories(self, router, tmp_path):
        nested = tmp_path / "a" / "b" / "c" / "cal.json"
        router.save_json(nested)
        assert nested.exists()

    def test_accepts_string_path(self, router, tmp_path):
        p = tmp_path / "str_path.json"
        router.save_json(str(p))
        assert p.exists()


# ===========================================================================
# 18. Integration tests
# ===========================================================================


class TestIntegration:
    def _make_high_dim_router(self, n_tools=5, dim=64, seed=42):
        rng = np.random.default_rng(seed)
        embeddings = {
            f"tool_{i}": rng.random(dim).tolist()
            for i in range(n_tools)
        }
        return CRTRouter.from_tool_embeddings(embeddings, primes=[7, 11, 13, 17, 19])

    def test_top_tool_is_nearest_neighbour(self):
        """The tool whose embedding is closest (cosine) to the query ranks first."""
        embeddings = {
            "near": [1.0, 0.0, 0.0],
            "far":  [0.0, 0.0, 1.0],
        }
        router = CRTRouter.from_tool_embeddings(embeddings, alpha=1.0, beta=0.0)
        results = router.rank_tools([1.0, 0.0, 0.0])
        assert results[0].tool_name == "near"

    def test_all_tools_returned_when_k_is_large(self):
        router = self._make_high_dim_router(n_tools=5)
        results = router.rank_tools(
            [0.5] * 64,
            k=100,
        )
        assert len(results) == 5

    def test_threshold_removes_irrelevant_tools(self):
        router = self._make_high_dim_router(n_tools=10)
        results_full = router.rank_tools([0.5] * 64, threshold=0.0)
        results_thresh = router.rank_tools([0.5] * 64, threshold=0.8)
        assert len(results_thresh) <= len(results_full)

    def test_save_load_produces_equivalent_ranking(self, tmp_path):
        router = self._make_high_dim_router()
        router.save_json(tmp_path / "cal.json")
        restored = CRTRouter.from_json(tmp_path / "cal.json")

        query = [0.3] * 64
        r1 = router.rank_tools(query)
        r2 = restored.rank_tools(query)
        assert [r.tool_name for r in r1] == [r.tool_name for r in r2]

    def test_available_tools_subset_consistent_ranking(self):
        router = self._make_high_dim_router(n_tools=10)
        query = [0.1] * 64
        full = router.rank_tools(query)
        top3_names = [r.tool_name for r in full[:3]]
        subset = router.rank_tools(query, available_tools=top3_names)
        # The relative order within the subset should be preserved.
        assert [r.tool_name for r in subset] == top3_names

    def test_prior_influences_final_ranking(self):
        """A tool with a 10× higher prior should rank above an otherwise equal tool."""
        base_emb = [0.5, 0.5, 0.0]
        art = CalibrationArtifact(
            primes=[7, 11],
            alpha=0.5,
            beta=0.5,
            tools={
                "low_prior": ToolCalibration(
                    tool_name="low_prior", reference_embedding=base_emb, prior=0.1
                ),
                "high_prior": ToolCalibration(
                    tool_name="high_prior", reference_embedding=base_emb, prior=1.0
                ),
            },
        )
        router = CRTRouter(art)
        # Query is identical to base_emb → same cosine & CRT for both tools.
        results = router.rank_tools(base_emb)
        assert results[0].tool_name == "high_prior"

    def test_no_calibrated_tools_at_all(self):
        art = CalibrationArtifact(primes=[7], tools={})
        router = CRTRouter(art)
        assert router.rank_tools([1.0, 0.0]) == []

    def test_explainability_fields_make_sense(self):
        embeddings = {"a": [1.0, 0.0], "b": [0.0, 1.0]}
        router = CRTRouter.from_tool_embeddings(embeddings, alpha=1.0, beta=0.0)
        results = router.rank_tools([1.0, 0.0])
        top = results[0]
        assert top.tool_name == "a"
        assert top.cosine_similarity == pytest.approx(1.0)
        assert top.posterior_score > 0
        assert top.prior > 0

    def test_large_number_of_tools(self):
        rng = np.random.default_rng(7)
        embeddings = {f"t{i}": rng.random(32).tolist() for i in range(100)}
        router = CRTRouter.from_tool_embeddings(embeddings)
        query = rng.random(32).tolist()
        results = router.rank_tools(query, k=10)
        assert len(results) == 10
        assert all(r.rank == i + 1 for i, r in enumerate(results))
