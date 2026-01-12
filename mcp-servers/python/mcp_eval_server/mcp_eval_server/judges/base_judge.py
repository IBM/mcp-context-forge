# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/mcp_eval_server/mcp_eval_server/judges/base_judge.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Base abstract interface for LLM judges.
"""

# Standard
import abc
import os
from typing import Any, Dict, List, Optional, Protocol, Union

# Third-Party
from jinja2 import Environment, FileSystemLoader
import orjson
from pydantic import BaseModel, Field


class EvaluationCriteria(BaseModel):
    """Evaluation criteria specification."""

    name: str = Field(..., description="Name of the criterion")
    description: str = Field(..., description="Detailed description of what to evaluate")
    scale: str = Field(default="1-5", description="Scoring scale (e.g., '1-5', '0-10')")
    weight: float = Field(default=1.0, description="Weight for this criterion in overall score")


class EvaluationRubric(BaseModel):
    """Detailed scoring rubric for evaluation."""

    criteria: List[EvaluationCriteria] = Field(..., description="List of evaluation criteria")
    scale_description: Dict[str, str] = Field(default_factory=dict, description="Description of what each scale point means")
    examples: Optional[Dict[str, str]] = Field(default=None, description="Example responses for each scale point")


class EvaluationResult(BaseModel):
    """Result of an evaluation."""

    scores: Dict[str, float] = Field(..., description="Scores for each criterion")
    reasoning: Dict[str, str] = Field(..., description="Reasoning for each score")
    overall_score: float = Field(..., description="Weighted average overall score")
    confidence: float = Field(..., description="Judge's confidence in the evaluation (0-1)")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class PairwiseResult(BaseModel):
    """Result of pairwise comparison."""

    winner: str = Field(..., description="'A', 'B', or 'tie'")
    confidence_score: float = Field(..., description="Confidence in the decision (0-1)")
    reasoning: str = Field(..., description="Detailed comparison reasoning")
    criterion_scores: Dict[str, str] = Field(default_factory=dict, description="Winner for each individual criterion")
    margin: Optional[float] = Field(default=None, description="Strength of preference (0-1, higher = stronger preference)")


class RankingResult(BaseModel):
    """Result of ranking multiple responses."""

    rankings: List[Dict[str, Union[str, float]]] = Field(..., description="Ordered list of responses with scores")
    pairwise_matrix: Optional[List[List[str]]] = Field(default=None, description="Head-to-head comparison matrix")
    consistency_score: float = Field(..., description="Consistency of rankings across comparisons (0-1)")
    reasoning: str = Field(..., description="Overall ranking reasoning")


class ReferenceEvaluationResult(BaseModel):
    """Result of evaluation against reference."""

    similarity_score: float = Field(..., description="Overall similarity to reference (0-1)")
    missing_elements: List[str] = Field(default_factory=list, description="Key points from reference not covered")
    extra_elements: List[str] = Field(default_factory=list, description="Additional information not in reference")
    factual_errors: List[str] = Field(default_factory=list, description="Identified factual errors")
    reasoning: str = Field(..., description="Detailed comparison reasoning")


class BaseJudge(abc.ABC):
    """Abstract base class for all LLM judges."""

    def __init__(self, config: Dict[str, Any]) -> None:
        """Initialize judge with configuration.

        Args:
            config: Judge configuration dictionary
        """
        self.config = config
        self.model_name = config.get("model_name", "unknown")
        self.temperature = config.get("default_temperature", 0.3)
        self.max_tokens = config.get("max_tokens", 2000)

        # Set up Jinja2 template environment
        template_dir = os.path.join(os.path.dirname(__file__), "templates")
        self.jinja_env = Environment(loader=FileSystemLoader(template_dir), trim_blocks=True, lstrip_blocks=True)

    @abc.abstractmethod
    async def evaluate_response(
        self,
        response: str,
        criteria: List[EvaluationCriteria],
        rubric: EvaluationRubric,
        context: Optional[str] = None,
        use_cot: bool = True,
    ) -> EvaluationResult:
        """Evaluate a single response.

        Args:
            response: Text response to evaluate
            criteria: List of evaluation criteria
            rubric: Detailed scoring rubric
            context: Optional context (e.g., original question)
            use_cot: Whether to use chain-of-thought reasoning
        """

    @abc.abstractmethod
    async def pairwise_comparison(
        self,
        response_a: str,
        response_b: str,
        criteria: List[EvaluationCriteria],
        context: Optional[str] = None,
        position_bias_mitigation: bool = True,
    ) -> PairwiseResult:
        """Compare two responses.

        Args:
            response_a: First response
            response_b: Second response
            criteria: Comparison criteria
            context: Optional context (e.g., original question)
            position_bias_mitigation: Whether to mitigate position bias
        """

    @abc.abstractmethod
    async def rank_responses(
        self,
        responses: List[str],
        criteria: List[EvaluationCriteria],
        context: Optional[str] = None,
        ranking_method: str = "tournament",
    ) -> RankingResult:
        """Rank multiple responses.

        Args:
            responses: List of responses to rank
            criteria: Ranking criteria
            context: Optional context
            ranking_method: Method to use ('tournament', 'round_robin', 'scoring')
        """

    @abc.abstractmethod
    async def evaluate_with_reference(
        self,
        response: str,
        reference: str,
        evaluation_type: str = "factuality",
        tolerance: str = "moderate",
    ) -> ReferenceEvaluationResult:
        """Evaluate response against reference.

        Args:
            response: Generated response
            reference: Gold standard reference
            evaluation_type: Type of evaluation ('factuality', 'completeness', 'style_match')
            tolerance: Matching tolerance ('strict', 'moderate', 'loose')
        """

    def _format_criteria(self, criteria: List[EvaluationCriteria]) -> str:
        """Format criteria for prompt inclusion.

        Args:
            criteria: List of evaluation criteria to format

        Returns:
            Formatted criteria string
        """
        formatted = []
        for criterion in criteria:
            formatted.append(f"- {criterion.name}: {criterion.description} (Scale: {criterion.scale})")
        return "\n".join(formatted)

    def _format_rubric(self, rubric: EvaluationRubric) -> str:
        """Format rubric for prompt inclusion.

        Args:
            rubric: Evaluation rubric to format

        Returns:
            Formatted rubric string
        """
        parts = []

        # Add scale descriptions
        if rubric.scale_description:
            parts.append("Scale Descriptions:")
            for scale, desc in rubric.scale_description.items():
                parts.append(f"  {scale}: {desc}")
            parts.append("")

        # Add examples if available
        if rubric.examples:
            parts.append("Examples:")
            for scale, example in rubric.examples.items():
                parts.append(f"  {scale}: {example}")

        return "\n".join(parts)

    def _calculate_overall_score(self, scores: Dict[str, float], criteria: List[EvaluationCriteria]) -> float:
        """Calculate weighted overall score.

        Args:
            scores: Score dictionary by criterion name
            criteria: List of evaluation criteria with weights

        Returns:
            Weighted overall score
        """
        total_weight = sum(c.weight for c in criteria)
        if total_weight == 0:
            return 0.0

        weighted_sum = sum(scores.get(c.name, 0.0) * c.weight for c in criteria)
        return weighted_sum / total_weight

    def _render_template(self, template_name: str, **kwargs) -> str:
        """Render a Jinja2 template with the given variables.

        Args:
            template_name: Name of the template file (without .j2 extension)
            **kwargs: Template variables

        Returns:
            Rendered template string
        """
        template = self.jinja_env.get_template(f"{template_name}.j2")
        return template.render(**kwargs)

    def _create_error_evaluation_result(self, criteria: List[EvaluationCriteria], error: str, raw_response: str = "") -> "EvaluationResult":
        """Create fallback evaluation result when parsing fails.

        Args:
            criteria: List of evaluation criteria
            error: Error message
            raw_response: Raw response from the judge

        Returns:
            Fallback evaluation result
        """
        return EvaluationResult(
            scores={c.name: 3.0 for c in criteria},  # Default middle scores
            reasoning={c.name: "Error parsing judge response" for c in criteria},
            overall_score=3.0,
            confidence=0.3,
            metadata={"model": self.model_name, "error": error, "raw_response": raw_response},
        )

    def _create_error_reference_result(self, error: str) -> "ReferenceEvaluationResult":
        """Create fallback reference evaluation result when parsing fails.

        Args:
            error: Error message

        Returns:
            Fallback reference evaluation result
        """
        return ReferenceEvaluationResult(similarity_score=0.5, missing_elements=[], extra_elements=[], factual_errors=[], reasoning=f"Error parsing judge response: {error}")

    def _parse_evaluation_response(self, response_text: str, criteria: List[EvaluationCriteria], **metadata) -> "EvaluationResult":
        """Parse JSON response from judge for evaluation.

        Args:
            response_text: Raw response text from judge
            criteria: List of evaluation criteria
            **metadata: Additional metadata to include

        Returns:
            Parsed evaluation result
        """
        try:
            # Extract JSON from response
            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1
            json_text = response_text[json_start:json_end]
            result_data = orjson.loads(json_text)

            # Calculate overall score
            overall_score = self._calculate_overall_score(result_data["scores"], criteria)

            return EvaluationResult(
                scores=result_data["scores"],
                reasoning=result_data["reasoning"],
                overall_score=overall_score,
                confidence=result_data.get("confidence", 0.8),
                metadata={**metadata, "model": self.model_name},
            )

        except (orjson.JSONDecodeError, KeyError) as e:
            return self._create_error_evaluation_result(criteria, str(e), response_text)

    def _parse_reference_response(self, response_text: str) -> "ReferenceEvaluationResult":
        """Parse JSON response from judge for reference evaluation.

        Args:
            response_text: Raw response text from judge

        Returns:
            Parsed reference evaluation result
        """
        try:
            # Extract JSON from response
            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1
            json_text = response_text[json_start:json_end]
            result_data = orjson.loads(json_text)

            return ReferenceEvaluationResult(
                similarity_score=result_data.get("similarity_score", 0.5),
                missing_elements=result_data.get("missing_elements", []),
                extra_elements=result_data.get("extra_elements", []),
                factual_errors=result_data.get("factual_errors", []),
                reasoning=result_data.get("reasoning", ""),
            )

        except (orjson.JSONDecodeError, KeyError) as e:
            return self._create_error_reference_result(str(e))

    def _parse_pairwise_response(self, response_text: str, original_order: bool) -> "PairwiseResult":
        """Parse JSON response from judge for pairwise comparison.

        Args:
            response_text: Raw response text from judge
            original_order: Whether responses were in original order (A, B) or swapped

        Returns:
            Parsed pairwise comparison result
        """
        try:
            # Extract JSON from response
            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1
            json_text = response_text[json_start:json_end]
            result_data = orjson.loads(json_text)

            # Adjust winner if we swapped positions
            winner = result_data["winner"]
            if not original_order and winner in ["A", "B"]:
                winner = "B" if winner == "A" else "A"

            # Adjust criterion scores
            criterion_scores = result_data.get("criterion_scores", {})
            if not original_order:
                for k, v in criterion_scores.items():
                    if v == "A":
                        criterion_scores[k] = "B"
                    elif v == "B":
                        criterion_scores[k] = "A"

            return PairwiseResult(
                winner=winner,
                confidence_score=result_data.get("confidence_score", 0.8),
                reasoning=result_data.get("reasoning", ""),
                criterion_scores=criterion_scores,
                margin=result_data.get("margin", 0.5),
            )

        except (orjson.JSONDecodeError, KeyError) as e:
            return PairwiseResult(winner="tie", confidence_score=0.3, reasoning=f"Error parsing judge response: {str(e)}", criterion_scores={}, margin=0.0)

    async def _base_pairwise_comparison(
        self,
        response_a: str,
        response_b: str,
        criteria: List[EvaluationCriteria],
        context: Optional[str] = None,
        position_bias_mitigation: bool = True,
    ) -> "PairwiseResult":
        """Base implementation for pairwise comparison.

        Args:
            response_a: First response
            response_b: Second response
            criteria: Comparison criteria
            context: Optional context
            position_bias_mitigation: Whether to mitigate position bias

        Returns:
            Pairwise comparison result
        """
        # Standard import for randomization
        # Standard
        import secrets  # pylint: disable=import-outside-toplevel

        # Position bias mitigation: randomly swap A and B
        original_order = True
        if position_bias_mitigation and secrets.randbelow(2) == 0:
            response_a, response_b = response_b, response_a
            original_order = False

        criteria_text = self._format_criteria(criteria)

        prompt = self._render_template("pairwise", context=context, response_a=response_a, response_b=response_b, criteria_text=criteria_text)

        messages = [{"role": "system", "content": "You are a professional evaluation expert. Provide fair, detailed comparisons."}, {"role": "user", "content": prompt}]

        response_text = await self._make_api_call(messages)  # pylint: disable=no-member
        return self._parse_pairwise_response(response_text, original_order)

    async def _base_reference_evaluation(
        self,
        response: str,
        reference: str,
        evaluation_type: str = "factuality",
        tolerance: str = "moderate",
    ) -> "ReferenceEvaluationResult":
        """Base implementation for reference evaluation.

        Args:
            response: Response text to evaluate
            reference: Reference text to compare against
            evaluation_type: Type of evaluation
            tolerance: Tolerance level for evaluation

        Returns:
            Reference evaluation result
        """
        prompt = self._render_template("reference", response=response, reference=reference, evaluation_type=evaluation_type, tolerance=tolerance)

        messages = [{"role": "system", "content": "You are a professional evaluation expert. Provide thorough, accurate assessments against reference standards."}, {"role": "user", "content": prompt}]

        response_text = await self._make_api_call(messages)  # pylint: disable=no-member
        return self._parse_reference_response(response_text)

    async def _rank_by_scoring(self, responses: List[str], criteria: List[EvaluationCriteria], context: Optional[str] = None) -> "RankingResult":
        """Rank by scoring each response individually.

        Args:
            responses: List of response strings to rank
            criteria: Evaluation criteria to use for scoring
            context: Optional context for evaluation

        Returns:
            RankingResult containing ranked responses with scores and reasoning
        """
        # Standard
        import asyncio  # pylint: disable=import-outside-toplevel

        rubric = EvaluationRubric(criteria=criteria, scale_description={"1": "Poor", "2": "Below Average", "3": "Average", "4": "Good", "5": "Excellent"})

        # Evaluate each response
        evaluation_tasks = [self.evaluate_response(response, criteria, rubric, context) for response in responses]
        evaluations = await asyncio.gather(*evaluation_tasks)

        # Sort by overall score
        ranked_results = []
        for i, evaluation in enumerate(evaluations):
            ranked_results.append({"response_index": i, "response": responses[i], "score": evaluation.overall_score, "reasoning": evaluation.reasoning})

        ranked_results.sort(key=lambda x: x["score"], reverse=True)

        return RankingResult(rankings=ranked_results, consistency_score=1.0, reasoning="Ranked by individual scoring of each response")

    async def _rank_by_tournament(self, responses: List[str], criteria: List[EvaluationCriteria], context: Optional[str] = None) -> "RankingResult":
        """Rank using tournament-style pairwise comparisons.

        Args:
            responses: List of response strings to rank
            criteria: Evaluation criteria to use for comparisons
            context: Optional context for evaluation

        Returns:
            RankingResult containing ranked responses based on tournament wins
        """
        # Standard
        import asyncio  # pylint: disable=import-outside-toplevel

        n = len(responses)
        wins = [0] * n

        # Perform all pairwise comparisons
        comparison_tasks = []
        pairs = []

        for i in range(n):
            for j in range(i + 1, n):
                pairs.append((i, j))
                comparison_tasks.append(self.pairwise_comparison(responses[i], responses[j], criteria, context))

        comparisons = await asyncio.gather(*comparison_tasks)

        # Count wins
        for (i, j), comparison in zip(pairs, comparisons):
            if comparison.winner == "A":
                wins[i] += 1
            elif comparison.winner == "B":
                wins[j] += 1
            else:  # tie
                wins[i] += 0.5
                wins[j] += 0.5

        # Sort by wins
        ranked_indices = sorted(range(n), key=lambda i: wins[i], reverse=True)

        ranked_results = []
        for rank, idx in enumerate(ranked_indices):
            ranked_results.append({"response_index": idx, "response": responses[idx], "score": wins[idx] / (n - 1), "wins": wins[idx], "rank": rank + 1})

        # Calculate consistency (simplified)
        total_comparisons = n * (n - 1) / 2
        win_variance = sum(abs(wins[i] - wins[j]) for i in range(n) for j in range(i + 1, n)) / total_comparisons
        consistency = max(0.0, 1.0 - (win_variance / n))

        return RankingResult(rankings=ranked_results, consistency_score=consistency, reasoning="Ranked by tournament-style pairwise comparisons")

    async def _rank_by_round_robin(self, responses: List[str], criteria: List[EvaluationCriteria], context: Optional[str] = None) -> "RankingResult":
        """Rank using round-robin pairwise comparisons.

        Args:
            responses: List of response strings to rank
            criteria: Evaluation criteria to use for comparisons
            context: Optional context for evaluation

        Returns:
            RankingResult containing ranked responses based on round-robin wins
        """
        # For now, implement same as tournament
        return await self._rank_by_tournament(responses, criteria, context)

    async def _base_rank_responses(
        self,
        responses: List[str],
        criteria: List[EvaluationCriteria],
        context: Optional[str] = None,
        ranking_method: str = "tournament",
    ) -> "RankingResult":
        """Base implementation for ranking multiple responses.

        Args:
            responses: List of response strings to rank
            criteria: List of evaluation criteria for ranking
            context: Optional context for evaluation
            ranking_method: Method to use for ranking ("tournament", "scoring", "round_robin")

        Returns:
            RankingResult containing ranked responses and consistency score

        Raises:
            ValueError: If less than 2 responses provided or unknown ranking method
        """
        if len(responses) < 2:
            raise ValueError("Need at least 2 responses to rank")

        if ranking_method == "scoring":
            return await self._rank_by_scoring(responses, criteria, context)
        if ranking_method == "tournament":
            return await self._rank_by_tournament(responses, criteria, context)
        if ranking_method == "round_robin":
            return await self._rank_by_round_robin(responses, criteria, context)

        raise ValueError(f"Unknown ranking method: {ranking_method}")


class JudgeCapabilities(BaseModel):
    """Capabilities of a judge model."""

    supports_cot: bool = Field(default=True, description="Supports chain-of-thought reasoning")
    supports_pairwise: bool = Field(default=True, description="Supports pairwise comparison")
    supports_ranking: bool = Field(default=True, description="Supports multi-response ranking")
    supports_reference: bool = Field(default=True, description="Supports reference-based evaluation")
    max_context_length: int = Field(default=4000, description="Maximum context length in tokens")
    optimal_temperature: float = Field(default=0.3, description="Optimal temperature for evaluation")
    consistency_level: str = Field(default="high", description="Expected consistency level")


class JudgeConfig(BaseModel):
    """Configuration for a judge."""

    model_name: str = Field(..., description="Model identifier")
    provider: str = Field(..., description="Provider (openai, azure, anthropic, etc.)")
    api_key_env: str = Field(..., description="Environment variable for API key")
    capabilities: JudgeCapabilities = Field(default_factory=JudgeCapabilities)
    default_temperature: float = Field(default=0.3, description="Default temperature")
    max_tokens: int = Field(default=2000, description="Maximum tokens per response")

    # Provider-specific configs
    api_base_env: Optional[str] = Field(default=None, description="API base URL env var (for Azure)")
    api_version: Optional[str] = Field(default=None, description="API version (for Azure)")
    deployment_name: Optional[str] = Field(default=None, description="Deployment name (for Azure)")
    organization: Optional[str] = Field(default=None, description="Organization (for OpenAI)")


class JudgeProtocol(Protocol):
    """Protocol for judge implementations."""

    async def evaluate_response(
        self,
        response: str,
        criteria: List[EvaluationCriteria],
        rubric: EvaluationRubric,
        context: Optional[str] = None,
        use_cot: bool = True,
    ) -> EvaluationResult:
        """Evaluate a single response.

        Args:
            response: Text response to evaluate
            criteria: List of evaluation criteria
            rubric: Detailed scoring rubric
            context: Optional context
            use_cot: Whether to use chain-of-thought reasoning

        Raises:
            NotImplementedError: This is an abstract method that must be implemented by subclasses.
        """
        raise NotImplementedError

    async def pairwise_comparison(
        self,
        response_a: str,
        response_b: str,
        criteria: List[EvaluationCriteria],
        context: Optional[str] = None,
        position_bias_mitigation: bool = True,
    ) -> PairwiseResult:
        """Compare two responses.

        Args:
            response_a: First response
            response_b: Second response
            criteria: Comparison criteria
            context: Optional context
            position_bias_mitigation: Whether to mitigate position bias

        Raises:
            NotImplementedError: This is an abstract method that must be implemented by subclasses.
        """
        raise NotImplementedError
