# -*- coding: utf-8 -*-
"""OpenAI judge implementation for LLM-as-a-judge evaluation."""

# Standard
import logging
import os
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
        return await self._base_pairwise_comparison(response_a, response_b, criteria, context, position_bias_mitigation)

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
            ranking_method: Method to use for ranking

        Returns:
            RankingResult containing ranked responses and consistency score

        Raises:
            ValueError: If less than 2 responses provided or unknown ranking method
        """
        return await self._base_rank_responses(responses, criteria, context, ranking_method)

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
            evaluation_type: Type of evaluation
            tolerance: Tolerance level for evaluation

        Returns:
            ReferenceEvaluationResult containing score and analysis
        """
        return await self._base_reference_evaluation(response, reference, evaluation_type, tolerance)
