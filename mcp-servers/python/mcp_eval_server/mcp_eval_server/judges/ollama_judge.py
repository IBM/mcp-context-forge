# -*- coding: utf-8 -*-
"""OLLAMA judge implementation for LLM-as-a-judge evaluation."""

# Standard
import asyncio
import os
from typing import Any, Dict, List, Optional

try:
    # Third-Party
    import aiohttp
except ImportError:
    aiohttp = None

# Third-Party
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


class OllamaJudge(BaseJudge):
    """Judge implementation using OLLAMA."""

    def __init__(self, config: Dict[str, Any]) -> None:
        """Initialize OLLAMA judge.

        Args:
            config: Configuration dictionary with OLLAMA settings

        Raises:
            ValueError: If aiohttp not available or base URL not configured
        """
        super().__init__(config)

        if aiohttp is None:
            raise ValueError("aiohttp library not installed. Please install with: pip install aiohttp")

        self.base_url = os.getenv(config["base_url_env"], "http://localhost:11434")
        self.model = config["model_name"]
        self.request_timeout = config.get("request_timeout", 60)  # OLLAMA can be slower

        # Create session for connection pooling
        self.session = None
        self._is_healthy = None

    async def _get_session(self):
        """Get or create HTTP session.

        Returns:
            aiohttp.ClientSession: HTTP session for making requests
        """
        if self.session is None:
            timeout = aiohttp.ClientTimeout(total=self.request_timeout)
            self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session

    async def _cleanup_session(self):
        """Cleanup HTTP session."""
        if self.session:
            await self.session.close()
            self.session = None

    def __del__(self):
        """Cleanup on deletion."""
        if self.session and not self.session.closed:
            try:
                asyncio.create_task(self._cleanup_session())
            except RuntimeError:
                # Event loop is not running, session will be cleaned up by garbage collector
                pass

    async def is_healthy(self) -> bool:
        """Check if OLLAMA server is healthy and model is available.

        Returns:
            bool: True if OLLAMA server is healthy and model is available, False otherwise
        """
        if self._is_healthy is not None:
            return self._is_healthy

        try:
            session = await self._get_session()

            # First check if server is responding
            async with session.get(f"{self.base_url}/api/tags") as response:
                if response.status != 200:
                    self._is_healthy = False
                    return False

                tags_data = await response.json()
                available_models = [model.get("name", "") for model in tags_data.get("models", [])]

                # Check if our specific model is available
                self._is_healthy = self.model in available_models
                return self._is_healthy

        except Exception:
            self._is_healthy = False
            return False

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    async def _make_api_call(self, messages: List[Dict[str, str]], temperature: Optional[float] = None, max_tokens: Optional[int] = None) -> str:
        """Make API call with retry logic.

        Args:
            messages: Chat messages for the API call
            temperature: Optional temperature override
            max_tokens: Optional max tokens override

        Returns:
            Response content from the API

        Raises:
            Exception: If OLLAMA API call fails
        """
        session = await self._get_session()

        # Format for OLLAMA chat API
        body = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature or self.temperature,
                "num_predict": max_tokens or self.max_tokens,
            },
        }

        try:
            async with session.post(f"{self.base_url}/api/chat", json=body) as response:
                if response.status == 200:
                    result = await response.json()
                    return result.get("message", {}).get("content", "")
                error_text = await response.text()
                raise Exception(f"OLLAMA API call failed with status {response.status}: {error_text}")

        except aiohttp.ClientError as e:
            raise Exception(f"OLLAMA API call failed: {e}")

    async def evaluate_response(
        self,
        response: str,
        criteria: List[EvaluationCriteria],
        rubric: EvaluationRubric,
        context: Optional[str] = None,
        use_cot: bool = True,
    ) -> EvaluationResult:
        """Evaluate a single response using OLLAMA.

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
        """Compare two responses using OLLAMA.

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
        """Rank multiple responses using OLLAMA.

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
        """Evaluate response against reference using OLLAMA.

        Args:
            response: Response text to evaluate
            reference: Reference text to compare against
            evaluation_type: Type of evaluation
            tolerance: Tolerance level for evaluation

        Returns:
            ReferenceEvaluationResult containing score and analysis
        """
        return await self._base_reference_evaluation(response, reference, evaluation_type, tolerance)
