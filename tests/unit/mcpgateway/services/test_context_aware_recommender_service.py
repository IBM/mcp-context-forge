# -*- coding: utf-8 -*-
"""Tests for the context-aware recommender service.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

# Standard
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.schemas import (
    RecommendationResponse,
    TimeRecommendation,
    ToolRecommendation,
    ToolSearchResult,
    WorkflowRecommendation,
)
from mcpgateway.services.context_aware_recommender_service import (
    ContextAwareRecommenderService,
    get_context_aware_recommender_service,
)


@pytest.fixture
def svc():
    return ContextAwareRecommenderService()


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.execute.return_value.all.return_value = []
    return db


def _make_search_result(name, score=0.8):
    return ToolSearchResult(tool_name=name, description="d", similarity_score=score)


def _make_workflow_rec(name, score=0.9, explanation="Often used with other_tool"):
    return WorkflowRecommendation(tool_name=name, description="d", score=score, explanation=explanation)


def _make_time_rec(name, score=0.6, explanation="Frequently used on Monday mornings"):
    return TimeRecommendation(tool_name=name, description="d", score=score, explanation=explanation)


# ---------------------------------------------------------------------------
# Singleton helper
# ---------------------------------------------------------------------------


class TestGetContextAwareRecommenderService:
    def test_returns_singleton(self):
        a = get_context_aware_recommender_service()
        b = get_context_aware_recommender_service()
        assert a is b
        assert isinstance(a, ContextAwareRecommenderService)


# ---------------------------------------------------------------------------
# All signals return results
# ---------------------------------------------------------------------------


class TestAllSignals:
    @pytest.mark.asyncio
    async def test_aggregates_all_three_signals(self, svc, mock_db):
        conv_results = [_make_search_result("tool_conv", score=1.0)]
        workflow_results = [_make_workflow_rec("tool_workflow", score=1.0)]
        time_results = [_make_time_rec("tool_time", score=1.0)]

        with patch("mcpgateway.services.conversation_context_service.get_conversation_context_service") as mock_conv:
            mock_conv.return_value.extract_context = AsyncMock(return_value=conv_results)
            with patch("mcpgateway.services.workflow_pattern_service.get_workflow_pattern_service") as mock_wf:
                mock_wf.return_value.get_workflow_recommendations = AsyncMock(return_value=workflow_results)
                with patch("mcpgateway.services.time_pattern_service.get_time_pattern_service") as mock_tp:
                    mock_tp.return_value.get_time_recommendations = AsyncMock(return_value=time_results)
                    response = await svc.recommend("user1", [], mock_db, limit=10)

        names = {r.tool_name for r in response.recommendations}
        assert "tool_conv" in names
        assert "tool_workflow" in names
        assert "tool_time" in names
        assert isinstance(response, RecommendationResponse)
        assert response.user_id == "user1"

    @pytest.mark.asyncio
    async def test_score_is_max_weighted_contribution(self, svc, mock_db):
        """The recommendation score should equal the maximum weighted signal contribution."""
        conv_results = [_make_search_result("shared_tool", score=1.0)]
        workflow_results = [_make_workflow_rec("shared_tool", score=1.0)]

        with patch("mcpgateway.services.conversation_context_service.get_conversation_context_service") as mock_conv:
            mock_conv.return_value.extract_context = AsyncMock(return_value=conv_results)
            with patch("mcpgateway.services.workflow_pattern_service.get_workflow_pattern_service") as mock_wf:
                mock_wf.return_value.get_workflow_recommendations = AsyncMock(return_value=workflow_results)
                with patch("mcpgateway.services.time_pattern_service.get_time_pattern_service") as mock_tp:
                    mock_tp.return_value.get_time_recommendations = AsyncMock(return_value=[])
                    with patch("mcpgateway.config.settings") as mock_settings:
                        mock_settings.recommendation_conversation_weight = 0.10
                        mock_settings.recommendation_workflow_weight = 0.20
                        mock_settings.recommendation_time_weight = 0.05
                        response = await svc.recommend("user1", [], mock_db, limit=10)

        rec = next(r for r in response.recommendations if r.tool_name == "shared_tool")
        # Max of (1.0 * 0.10, 1.0 * 0.20) = 0.20
        assert rec.score == pytest.approx(0.20)


# ---------------------------------------------------------------------------
# Graceful degradation — individual signal failures
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    @pytest.mark.asyncio
    async def test_conversation_signal_failure_still_returns_other_signals(self, svc, mock_db):
        workflow_results = [_make_workflow_rec("tool_wf")]
        time_results = [_make_time_rec("tool_tp")]

        with patch("mcpgateway.services.conversation_context_service.get_conversation_context_service") as mock_conv:
            mock_conv.return_value.extract_context = AsyncMock(side_effect=RuntimeError("embed down"))
            with patch("mcpgateway.services.workflow_pattern_service.get_workflow_pattern_service") as mock_wf:
                mock_wf.return_value.get_workflow_recommendations = AsyncMock(return_value=workflow_results)
                with patch("mcpgateway.services.time_pattern_service.get_time_pattern_service") as mock_tp:
                    mock_tp.return_value.get_time_recommendations = AsyncMock(return_value=time_results)
                    response = await svc.recommend("user1", [], mock_db, limit=10)

        names = {r.tool_name for r in response.recommendations}
        assert "tool_wf" in names
        assert "tool_tp" in names

    @pytest.mark.asyncio
    async def test_workflow_signal_failure_still_returns_other_signals(self, svc, mock_db):
        conv_results = [_make_search_result("tool_conv")]
        time_results = [_make_time_rec("tool_tp")]

        with patch("mcpgateway.services.conversation_context_service.get_conversation_context_service") as mock_conv:
            mock_conv.return_value.extract_context = AsyncMock(return_value=conv_results)
            with patch("mcpgateway.services.workflow_pattern_service.get_workflow_pattern_service") as mock_wf:
                mock_wf.return_value.get_workflow_recommendations = AsyncMock(side_effect=RuntimeError("matrix down"))
                with patch("mcpgateway.services.time_pattern_service.get_time_pattern_service") as mock_tp:
                    mock_tp.return_value.get_time_recommendations = AsyncMock(return_value=time_results)
                    response = await svc.recommend("user1", [], mock_db, limit=10)

        names = {r.tool_name for r in response.recommendations}
        assert "tool_conv" in names
        assert "tool_tp" in names

    @pytest.mark.asyncio
    async def test_time_signal_failure_still_returns_other_signals(self, svc, mock_db):
        conv_results = [_make_search_result("tool_conv")]
        workflow_results = [_make_workflow_rec("tool_wf")]

        with patch("mcpgateway.services.conversation_context_service.get_conversation_context_service") as mock_conv:
            mock_conv.return_value.extract_context = AsyncMock(return_value=conv_results)
            with patch("mcpgateway.services.workflow_pattern_service.get_workflow_pattern_service") as mock_wf:
                mock_wf.return_value.get_workflow_recommendations = AsyncMock(return_value=workflow_results)
                with patch("mcpgateway.services.time_pattern_service.get_time_pattern_service") as mock_tp:
                    mock_tp.return_value.get_time_recommendations = AsyncMock(side_effect=RuntimeError("time down"))
                    response = await svc.recommend("user1", [], mock_db, limit=10)

        names = {r.tool_name for r in response.recommendations}
        assert "tool_conv" in names
        assert "tool_wf" in names

    @pytest.mark.asyncio
    async def test_all_signals_fail_returns_empty_response(self, svc, mock_db):
        with patch("mcpgateway.services.conversation_context_service.get_conversation_context_service") as mock_conv:
            mock_conv.return_value.extract_context = AsyncMock(side_effect=RuntimeError("fail"))
            with patch("mcpgateway.services.workflow_pattern_service.get_workflow_pattern_service") as mock_wf:
                mock_wf.return_value.get_workflow_recommendations = AsyncMock(side_effect=RuntimeError("fail"))
                with patch("mcpgateway.services.time_pattern_service.get_time_pattern_service") as mock_tp:
                    mock_tp.return_value.get_time_recommendations = AsyncMock(side_effect=RuntimeError("fail"))
                    response = await svc.recommend("user1", [], mock_db, limit=10)

        assert response.recommendations == []
        assert response.total_results == 0


# ---------------------------------------------------------------------------
# Recent tools filtering
# ---------------------------------------------------------------------------


class TestRecentToolsFiltered:
    @pytest.mark.asyncio
    async def test_recent_tools_excluded_from_results(self, svc, mock_db):
        """Tools in recent_tool_names must not appear in recommendations."""
        conv_results = [
            _make_search_result("recent_tool", score=1.0),
            _make_search_result("new_tool", score=0.8),
        ]

        with patch("mcpgateway.services.conversation_context_service.get_conversation_context_service") as mock_conv:
            mock_conv.return_value.extract_context = AsyncMock(return_value=conv_results)
            with patch("mcpgateway.services.workflow_pattern_service.get_workflow_pattern_service") as mock_wf:
                mock_wf.return_value.get_workflow_recommendations = AsyncMock(return_value=[])
                with patch("mcpgateway.services.time_pattern_service.get_time_pattern_service") as mock_tp:
                    mock_tp.return_value.get_time_recommendations = AsyncMock(return_value=[])
                    response = await svc.recommend("user1", ["recent_tool"], mock_db, limit=10)

        names = {r.tool_name for r in response.recommendations}
        assert "recent_tool" not in names
        assert "new_tool" in names

    @pytest.mark.asyncio
    async def test_all_results_filtered_returns_empty(self, svc, mock_db):
        """If all recommended tools are in recent_tool_names, return empty."""
        conv_results = [_make_search_result("used_tool")]

        with patch("mcpgateway.services.conversation_context_service.get_conversation_context_service") as mock_conv:
            mock_conv.return_value.extract_context = AsyncMock(return_value=conv_results)
            with patch("mcpgateway.services.workflow_pattern_service.get_workflow_pattern_service") as mock_wf:
                mock_wf.return_value.get_workflow_recommendations = AsyncMock(return_value=[])
                with patch("mcpgateway.services.time_pattern_service.get_time_pattern_service") as mock_tp:
                    mock_tp.return_value.get_time_recommendations = AsyncMock(return_value=[])
                    response = await svc.recommend("user1", ["used_tool"], mock_db, limit=10)

        assert response.recommendations == []


# ---------------------------------------------------------------------------
# Limit / ranking
# ---------------------------------------------------------------------------


class TestRankingAndLimit:
    @pytest.mark.asyncio
    async def test_results_sorted_by_score_descending(self, svc, mock_db):
        conv_results = [
            _make_search_result("low_score_tool", score=0.2),
            _make_search_result("high_score_tool", score=1.0),
            _make_search_result("mid_score_tool", score=0.6),
        ]

        with patch("mcpgateway.services.conversation_context_service.get_conversation_context_service") as mock_conv:
            mock_conv.return_value.extract_context = AsyncMock(return_value=conv_results)
            with patch("mcpgateway.services.workflow_pattern_service.get_workflow_pattern_service") as mock_wf:
                mock_wf.return_value.get_workflow_recommendations = AsyncMock(return_value=[])
                with patch("mcpgateway.services.time_pattern_service.get_time_pattern_service") as mock_tp:
                    mock_tp.return_value.get_time_recommendations = AsyncMock(return_value=[])
                    response = await svc.recommend("user1", [], mock_db, limit=10)

        scores = [r.score for r in response.recommendations]
        assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_limit_caps_number_of_results(self, svc, mock_db):
        conv_results = [_make_search_result(f"tool_{i}", score=float(i) / 10) for i in range(1, 11)]

        with patch("mcpgateway.services.conversation_context_service.get_conversation_context_service") as mock_conv:
            mock_conv.return_value.extract_context = AsyncMock(return_value=conv_results)
            with patch("mcpgateway.services.workflow_pattern_service.get_workflow_pattern_service") as mock_wf:
                mock_wf.return_value.get_workflow_recommendations = AsyncMock(return_value=[])
                with patch("mcpgateway.services.time_pattern_service.get_time_pattern_service") as mock_tp:
                    mock_tp.return_value.get_time_recommendations = AsyncMock(return_value=[])
                    response = await svc.recommend("user1", [], mock_db, limit=3)

        assert len(response.recommendations) == 3
        assert response.total_results == 3

    @pytest.mark.asyncio
    async def test_workflow_reasons_included_in_recommendation(self, svc, mock_db):
        """Workflow explanations should be surfaced in the reasons list."""
        workflow_results = [_make_workflow_rec("wf_tool", explanation="Often used with base_tool")]

        with patch("mcpgateway.services.conversation_context_service.get_conversation_context_service") as mock_conv:
            mock_conv.return_value.extract_context = AsyncMock(return_value=[])
            with patch("mcpgateway.services.workflow_pattern_service.get_workflow_pattern_service") as mock_wf:
                mock_wf.return_value.get_workflow_recommendations = AsyncMock(return_value=workflow_results)
                with patch("mcpgateway.services.time_pattern_service.get_time_pattern_service") as mock_tp:
                    mock_tp.return_value.get_time_recommendations = AsyncMock(return_value=[])
                    response = await svc.recommend("user1", [], mock_db, limit=10)

        rec = next(r for r in response.recommendations if r.tool_name == "wf_tool")
        assert "Often used with base_tool" in rec.reasons
