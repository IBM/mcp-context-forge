# -*- coding: utf-8 -*-
"""Tests for MCP Eval Server main functionality."""

# Third-Party
from mcp_eval_server.server import (
    agent_tools,
    calibration_tools,
    judge_tools,
    prompt_tools,
    quality_tools,
    workflow_tools,
)
import pytest


class TestServerComponents:
    """Test core server components."""

    def test_judge_tools_initialization(self):
        """Test that judge tools initialize correctly."""
        assert judge_tools is not None
        available_judges = judge_tools.get_available_judges()
        assert isinstance(available_judges, list)
        assert "rule-based" in available_judges

    def test_prompt_tools_initialization(self):
        """Test that prompt tools initialize correctly."""
        assert prompt_tools is not None
        assert prompt_tools.judge_tools is not None

    def test_agent_tools_initialization(self):
        """Test that agent tools initialize correctly."""
        assert agent_tools is not None
        assert agent_tools.judge_tools is not None

    def test_quality_tools_initialization(self):
        """Test that quality tools initialize correctly."""
        assert quality_tools is not None
        assert quality_tools.judge_tools is not None

    def test_workflow_tools_initialization(self):
        """Test that workflow tools initialize correctly."""
        assert workflow_tools is not None
        assert workflow_tools.judge_tools is not None

    def test_calibration_tools_initialization(self):
        """Test that calibration tools initialize correctly."""
        assert calibration_tools is not None
        assert calibration_tools.judge_tools is not None


class TestRuleBasedEvaluation:
    """Test rule-based evaluation functionality."""

    @pytest.mark.asyncio
    async def test_basic_response_evaluation(self):
        """Test basic response evaluation with rule-based judge."""

        criteria = [{"name": "length", "description": "Appropriate response length", "scale": "1-5", "weight": 1.0}]

        rubric = {"criteria": criteria, "scale_description": {"1": "Very poor", "5": "Excellent"}}

        result = await judge_tools.evaluate_response(response="This is a test response with adequate length for evaluation.", criteria=criteria, rubric=rubric, judge_model="rule-based")

        assert "scores" in result
        assert "reasoning" in result
        assert "overall_score" in result
        assert "confidence" in result
        assert isinstance(result["scores"], dict)
        assert "length" in result["scores"]
        assert isinstance(result["overall_score"], (int, float))
        assert 0 <= result["overall_score"] <= 5

    @pytest.mark.asyncio
    async def test_pairwise_comparison(self):
        """Test pairwise comparison functionality."""

        criteria = [{"name": "quality", "description": "Overall response quality", "scale": "1-5", "weight": 1.0}]

        result = await judge_tools.pairwise_comparison(
            response_a="Short response.", response_b="This is a longer, more detailed response with better coverage.", criteria=criteria, judge_model="rule-based"
        )

        assert "winner" in result
        assert result["winner"] in ["A", "B", "tie"]
        assert "confidence_score" in result
        assert "reasoning" in result
        assert isinstance(result["confidence_score"], (int, float))
        assert 0 <= result["confidence_score"] <= 1


class TestPromptEvaluation:
    """Test prompt evaluation functionality."""

    @pytest.mark.asyncio
    async def test_evaluate_clarity(self):
        """Test prompt clarity evaluation."""

        result = await prompt_tools.evaluate_clarity(prompt_text="Write a summary of the main points in this article.", target_model="gpt-4", judge_model="rule-based")

        assert "clarity_score" in result
        assert "rule_based_metrics" in result
        assert "recommendations" in result
        assert isinstance(result["clarity_score"], (int, float))
        assert 0 <= result["clarity_score"] <= 5

    @pytest.mark.asyncio
    async def test_measure_completeness(self):
        """Test prompt completeness measurement."""

        result = await prompt_tools.measure_completeness(
            prompt="Analyze the climate data",
            expected_components=["temperature", "precipitation", "trends"],
            test_samples=["Temperature has increased over time", "Precipitation patterns show variation and temperature trends are rising", "Brief analysis"],
        )

        assert "completeness_score" in result
        assert "component_scores" in result
        assert "missing_components" in result
        assert isinstance(result["completeness_score"], (int, float))
        assert 0 <= result["completeness_score"] <= 1


class TestAgentEvaluation:
    """Test agent evaluation functionality."""

    @pytest.mark.asyncio
    async def test_evaluate_tool_use(self):
        """Test agent tool usage evaluation."""

        agent_trace = {"tool_calls": [{"tool_name": "search", "parameters": {"query": "test"}, "success": True}, {"tool_name": "analyzer", "parameters": {"data": "results"}, "success": True}]}

        result = await agent_tools.evaluate_tool_use(agent_trace=agent_trace, expected_tools=["search", "analyzer"], tool_sequence_matters=True)

        assert "tool_accuracy" in result
        assert "sequence_score" in result
        assert "efficiency_score" in result
        assert "overall_score" in result
        assert isinstance(result["tool_accuracy"], (int, float))
        assert 0 <= result["tool_accuracy"] <= 1


class TestQualityEvaluation:
    """Test quality evaluation functionality."""

    @pytest.mark.asyncio
    async def test_assess_toxicity(self):
        """Test toxicity assessment."""

        result = await quality_tools.assess_toxicity(content="This is a normal, safe piece of text for testing.", toxicity_categories=["profanity", "hate_speech"], judge_model="rule-based")

        assert "toxicity_scores" in result
        assert "safety_rating" in result
        assert "recommendations" in result
        assert isinstance(result["toxicity_scores"], dict)
        assert result["safety_rating"] in ["Safe", "Low Risk", "Medium Risk", "High Risk"]

    @pytest.mark.asyncio
    async def test_measure_coherence(self):
        """Test coherence measurement."""

        result = await quality_tools.measure_coherence(
            text="This is the first sentence. Furthermore, this connects to the previous idea. Therefore, the text flows logically.", judge_model="rule-based"
        )

        assert "coherence_score" in result
        assert "rule_based_analysis" in result
        assert "logical_flow" in result
        assert isinstance(result["coherence_score"], (int, float))
        assert 0 <= result["coherence_score"] <= 5


class TestWorkflowManagement:
    """Test workflow and suite management."""

    @pytest.mark.asyncio
    async def test_create_evaluation_suite(self):
        """Test evaluation suite creation."""

        result = await workflow_tools.create_evaluation_suite(
            suite_name="test_suite",
            evaluation_steps=[
                {
                    "tool": "judge.evaluate_response",
                    "weight": 1.0,
                    "parameters": {
                        "criteria": [{"name": "quality", "description": "Quality", "scale": "1-5", "weight": 1.0}],
                        "rubric": {"criteria": [], "scale_description": {"1": "Poor", "5": "Excellent"}},
                    },
                }
            ],
            success_thresholds={"overall": 0.7},
        )

        assert "suite_id" in result
        assert "configuration" in result
        assert "total_steps" in result
        assert isinstance(result["suite_id"], str)
        assert len(result["suite_id"]) > 0


class TestServerUtilities:
    """Test server utility functions."""

    def test_get_available_judges(self):
        """Test getting available judges."""
        judges = judge_tools.get_available_judges()
        assert isinstance(judges, list)
        assert len(judges) > 0
        assert "rule-based" in judges

    def test_list_evaluation_suites(self):
        """Test listing evaluation suites."""
        suites = workflow_tools.list_evaluation_suites()
        assert isinstance(suites, list)

    def test_list_evaluation_results(self):
        """Test listing evaluation results."""
        results = workflow_tools.list_evaluation_results()
        assert isinstance(results, list)


if __name__ == "__main__":
    pytest.main([__file__])
