# -*- coding: utf-8 -*-
"""OpenAI judge implementation for LLM-as-a-judge evaluation."""

# Standard
import asyncio
import json
import logging
import os
import secrets
from typing import Any, Dict, List, Optional

# Third-Party
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

# Local
from .base_judge import (
    BaseJudge,
    EvaluationCriteria,
    EvaluationResult,
    EvaluationRubric,
    PairwiseResult,
    RankingResult,
    ReferenceEvaluationResult,
)


class OpenAIJudge(BaseJudge):
    """Judge implementation using OpenAI API."""

    def __init__(self, config: Dict[str, Any]) -> None:
        """Initialize OpenAI judge.

        Args:
            config: Configuration dictionary with OpenAI settings

        Raises:
            ValueError: If API key not found in environment
        """
        super().__init__(config)
        self.logger = logging.getLogger(__name__)

        api_key = os.getenv(config["api_key_env"])
        if not api_key:
            raise ValueError(f"API key not found in environment variable: {config['api_key_env']}")

        # Support for organization (updated to match agent_runtimes)
        organization = None
        if config.get("organization_env"):
            organization = os.getenv(config["organization_env"])
        elif config.get("organization"):  # Fallback for old config
            organization = config["organization"]

        # Support for custom base URL
        base_url = None
        if config.get("base_url_env"):
            base_url = os.getenv(config["base_url_env"])

        self.client = AsyncOpenAI(api_key=api_key, organization=organization, base_url=base_url)
        self.model = config["model_name"]

        self.logger.debug(f"🔧 Initialized OpenAI judge: {self.model}")
        if base_url:
            self.logger.debug(f"   Using custom base URL: {base_url}")
        if organization:
            self.logger.debug(f"   Using organization: {organization}")

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    async def _make_api_call(self, messages: List[Dict[str, str]], temperature: Optional[float] = None, max_tokens: Optional[int] = None) -> str:
        """Make API call with retry logic.

        Args:
            messages: Chat messages for the API call
            temperature: Optional temperature override
            max_tokens: Optional max tokens override

        Returns:
            Response content from the API
        """
        self.logger.debug(f"🔗 Making OpenAI API call to {self.model}")
        self.logger.debug(f"   Messages: {len(messages)}, Temperature: {temperature or self.temperature}, Max tokens: {max_tokens or self.max_tokens}")

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature or self.temperature,
            max_tokens=max_tokens or self.max_tokens,
        )

        result = response.choices[0].message.content or ""
        self.logger.debug(f"✅ OpenAI API response received - Length: {len(result)} chars")

        return result

    async def evaluate_response(
        self,
        response: str,
        criteria: List[EvaluationCriteria],
        rubric: EvaluationRubric,
        context: Optional[str] = None,
        use_cot: bool = True,
    ) -> EvaluationResult:
        """Evaluate a single response using OpenAI.

        Args:
            response: Text response to evaluate
            criteria: List of evaluation criteria
            rubric: Detailed scoring rubric
            context: Optional context
            use_cot: Whether to use chain-of-thought reasoning

        Returns:
            Evaluation result with scores and reasoning
        """

        criteria_text = self._format_criteria(criteria)
        rubric_text = self._format_rubric(rubric)

        prompt = self._render_template("evaluation", context=context, response=response, criteria_text=criteria_text, rubric_text=rubric_text, use_cot=use_cot)

        messages = [{"role": "system", "content": "You are a professional evaluation expert. Provide thorough, unbiased assessments."}, {"role": "user", "content": prompt}]

        response_text = await self._make_api_call(messages)

        return self._parse_evaluation_response(response_text, criteria, model=self.model, temperature=self.temperature, use_cot=use_cot)

    async def pairwise_comparison(
        self,
        response_a: str,
        response_b: str,
        criteria: List[EvaluationCriteria],
        context: Optional[str] = None,
        position_bias_mitigation: bool = True,
    ) -> PairwiseResult:
        """Compare two responses using OpenAI.

        Args:
            response_a: First response
            response_b: Second response
            criteria: Comparison criteria
            context: Optional context
            position_bias_mitigation: Whether to mitigate position bias

        Returns:
            Pairwise comparison result
        """

        # Position bias mitigation: randomly swap A and B
        original_order = True
        if position_bias_mitigation and secrets.randbelow(2) == 0:
            response_a, response_b = response_b, response_a
            original_order = False

        criteria_text = self._format_criteria(criteria)

        prompt = self._render_template("pairwise", context=context, response_a=response_a, response_b=response_b, criteria_text=criteria_text)

        messages = [{"role": "system", "content": "You are a professional evaluation expert. Provide fair, detailed comparisons."}, {"role": "user", "content": prompt}]

        response_text = await self._make_api_call(messages)

        try:
            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1
            json_text = response_text[json_start:json_end]
            result_data = json.loads(json_text)

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

        except (json.JSONDecodeError, KeyError) as e:
            return PairwiseResult(winner="tie", confidence_score=0.3, reasoning=f"Error parsing judge response: {str(e)}", criterion_scores={}, margin=0.0)

    async def rank_responses(
        self,
        responses: List[str],
        criteria: List[EvaluationCriteria],
        context: Optional[str] = None,
        ranking_method: str = "tournament",
    ) -> RankingResult:
        """Rank multiple responses using OpenAI.

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

    async def _rank_by_scoring(self, responses: List[str], criteria: List[EvaluationCriteria], context: Optional[str] = None) -> RankingResult:
        """Rank by scoring each response individually.

        Args:
            responses: List of response strings to rank
            criteria: List of evaluation criteria for scoring
            context: Optional context for evaluation

        Returns:
            RankingResult with responses ranked by individual scores
        """

        # Create a simple rubric for ranking
        rubric = EvaluationRubric(criteria=criteria, scale_description={"1": "Poor", "2": "Below Average", "3": "Average", "4": "Good", "5": "Excellent"})

        # Evaluate each response
        evaluation_tasks = [self.evaluate_response(response, criteria, rubric, context) for response in responses]

        evaluations = await asyncio.gather(*evaluation_tasks)

        # Sort by overall score
        ranked_results = []
        for i, evaluation in enumerate(evaluations):
            ranked_results.append({"response_index": i, "response": responses[i], "score": evaluation.overall_score, "reasoning": evaluation.reasoning})

        ranked_results.sort(key=lambda x: x["score"], reverse=True)

        return RankingResult(rankings=ranked_results, consistency_score=1.0, reasoning="Ranked by individual scoring of each response")  # Single judge, perfectly consistent

    async def _rank_by_tournament(self, responses: List[str], criteria: List[EvaluationCriteria], context: Optional[str] = None) -> RankingResult:
        """Rank using tournament-style pairwise comparisons.

        Args:
            responses: List of response strings to rank
            criteria: List of evaluation criteria for comparison
            context: Optional context for evaluation

        Returns:
            RankingResult with responses ranked by tournament wins
        """

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
            ranked_results.append({"response_index": idx, "response": responses[idx], "score": wins[idx] / (n - 1), "wins": wins[idx], "rank": rank + 1})  # Normalize to 0-1

        # Calculate consistency (simplified)
        consistency = 1.0 - (sum(abs(wins[i] - wins[j]) for i in range(n) for j in range(i + 1, n)) / (n * (n - 1) / 2)) / n

        return RankingResult(rankings=ranked_results, consistency_score=max(0.0, consistency), reasoning="Ranked by tournament-style pairwise comparisons")

    async def _rank_by_round_robin(self, responses: List[str], criteria: List[EvaluationCriteria], context: Optional[str] = None) -> RankingResult:
        """Rank using round-robin pairwise comparisons.

        Args:
            responses: List of response strings to rank
            criteria: List of evaluation criteria for comparison
            context: Optional context for evaluation

        Returns:
            RankingResult with responses ranked by round-robin comparisons
        """

        # For now, implement same as tournament
        # In a full implementation, this could include multiple rounds
        return await self._rank_by_tournament(responses, criteria, context)

    async def evaluate_with_reference(
        self,
        response: str,
        reference: str,
        evaluation_type: str = "factuality",
        tolerance: str = "moderate",
    ) -> ReferenceEvaluationResult:
        """Evaluate response against reference using OpenAI.

        Args:
            response: Response text to evaluate
            reference: Reference text to compare against
            evaluation_type: Type of evaluation ("factuality", "completeness", "style_match")
            tolerance: Tolerance level for evaluation ("strict", "moderate", "lenient")

        Returns:
            ReferenceEvaluationResult containing score and analysis
        """

        prompt = self._render_template("reference", response=response, reference=reference, evaluation_type=evaluation_type, tolerance=tolerance)

        messages = [{"role": "system", "content": "You are a professional evaluation expert. Provide thorough, accurate assessments against reference standards."}, {"role": "user", "content": prompt}]

        response_text = await self._make_api_call(messages)

        return self._parse_reference_response(response_text)
