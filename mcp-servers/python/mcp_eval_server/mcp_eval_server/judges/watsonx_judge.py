# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/mcp_eval_server/mcp_eval_server/judges/watsonx_judge.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

IBM Watsonx.ai judge implementation for LLM-as-a-judge evaluation.
"""

# Standard
import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

try:
    # Third-Party
    from ibm_watsonx_ai import Credentials
    from ibm_watsonx_ai.foundation_models import Model
    from ibm_watsonx_ai.metanames import GenTextParamsMetaNames as GenParams
except ImportError:
    Model = None
    GenParams = None
    Credentials = None

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


class WatsonxJudge(BaseJudge):
    """Judge implementation using IBM Watsonx.ai."""

    def __init__(self, config: Dict[str, Any]) -> None:
        """Initialize Watsonx.ai judge.

        Args:
            config: Configuration dictionary with Watsonx.ai settings

        Raises:
            ValueError: If required environment variables not found or watsonx library not available
        """
        super().__init__(config)
        self.logger = logging.getLogger(__name__)

        if Model is None:
            raise ValueError("IBM Watsonx.ai library not installed. Please install with: pip install ibm-watsonx-ai")

        # Get Watsonx.ai credentials
        api_key = os.getenv(config["api_key_env"])
        project_id = os.getenv(config["project_id_env"])
        url = os.getenv(config.get("url_env", "WATSONX_URL"), "https://us-south.ml.cloud.ibm.com")

        if not api_key:
            raise ValueError(f"API key not found in environment variable: {config['api_key_env']}")
        if not project_id:
            raise ValueError(f"Project ID not found in environment variable: {config['project_id_env']}")

        self.credentials = Credentials(
            url=url,
            api_key=api_key,
        )

        self.project_id = project_id
        self.model_id = config["model_id"]
        self.model = config["model_name"]

        # Initialize the Watsonx model
        self.watsonx_model = Model(
            model_id=self.model_id,
            params={GenParams.DECODING_METHOD: "greedy", GenParams.MAX_NEW_TOKENS: self.max_tokens, GenParams.TEMPERATURE: self.temperature, GenParams.STOP_SEQUENCES: ["\n\n"]},
            credentials=self.credentials,
            project_id=self.project_id,
        )

        self.logger.debug(f"🔧 Initialized Watsonx.ai judge: {self.model}")
        self.logger.debug(f"   Model ID: {self.model_id}")
        self.logger.debug(f"   Project ID: {project_id}")
        self.logger.debug(f"   URL: {url}")

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
            Exception: If Watsonx.ai API call fails
        """
        self.logger.debug(f"🔗 Making Watsonx.ai API call to {self.model}")
        self.logger.debug(f"   Messages: {len(messages)}, Temperature: {temperature or self.temperature}, Max tokens: {max_tokens or self.max_tokens}")

        # Convert messages to single prompt for Watsonx.ai
        prompt_parts = []
        for msg in messages:
            if msg["role"] == "system":
                prompt_parts.append(f"System: {msg['content']}")
            elif msg["role"] == "user":
                prompt_parts.append(f"Human: {msg['content']}")
            elif msg["role"] == "assistant":
                prompt_parts.append(f"Assistant: {msg['content']}")

        prompt = "\n\n".join(prompt_parts) + "\n\nAssistant:"

        # Update parameters for this call
        params = {
            GenParams.DECODING_METHOD: "greedy",
            GenParams.MAX_NEW_TOKENS: max_tokens or self.max_tokens,
            GenParams.TEMPERATURE: temperature or self.temperature,
            GenParams.STOP_SEQUENCES: ["\n\n", "Human:", "System:"],
        }

        try:
            # Run in thread pool since Watsonx.ai library is sync
            # Standard
            import concurrent.futures  # pylint: disable=import-outside-toplevel

            def make_request():
                response = self.watsonx_model.generate_text(prompt=prompt, params=params)
                return response if response else ""

            loop = asyncio.get_event_loop()
            with concurrent.futures.ThreadPoolExecutor() as executor:
                result = await loop.run_in_executor(executor, make_request)

            self.logger.debug(f"✅ Watsonx.ai API response received - Length: {len(result)} chars")

            # Log the actual model response (truncated)
            truncated_response = result[:200] + "..." if len(result) > 200 else result
            self.logger.debug(f"   💬 Model response: {truncated_response}")

            return result

        except Exception as e:
            raise Exception(f"Watsonx.ai API call failed: {e}")

    async def evaluate_response(
        self,
        response: str,
        criteria: List[EvaluationCriteria],
        rubric: EvaluationRubric,
        context: Optional[str] = None,
        use_cot: bool = True,
    ) -> EvaluationResult:
        """Evaluate a single response using Watsonx.ai.

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

        return self._parse_evaluation_response(response_text, criteria, model=self.model, model_id=self.model_id, temperature=self.temperature, use_cot=use_cot)

    async def pairwise_comparison(
        self,
        response_a: str,
        response_b: str,
        criteria: List[EvaluationCriteria],
        context: Optional[str] = None,
        position_bias_mitigation: bool = True,
    ) -> PairwiseResult:
        """Compare two responses using Watsonx.ai.

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
        """Rank multiple responses using Watsonx.ai.

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
        """Evaluate response against reference using Watsonx.ai.

        Args:
            response: Response text to evaluate
            reference: Reference text to compare against
            evaluation_type: Type of evaluation
            tolerance: Tolerance level for evaluation

        Returns:
            ReferenceEvaluationResult containing score and analysis
        """
        return await self._base_reference_evaluation(response, reference, evaluation_type, tolerance)
