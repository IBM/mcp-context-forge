# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/mcp_eval_server/mcp_eval_server/judges/bedrock_judge.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

AWS Bedrock judge implementation for LLM-as-a-judge evaluation.
"""

# Standard
import asyncio
import os
from typing import Any, Dict, List, Optional

import orjson
try:
    # Third-Party
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    boto3 = None
    ClientError = Exception

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


class BedrockJudge(BaseJudge):
    """Judge implementation using AWS Bedrock."""

    def __init__(self, config: Dict[str, Any]) -> None:
        """Initialize Bedrock judge.

        Args:
            config: Configuration dictionary with Bedrock settings

        Raises:
            ValueError: If required environment variables not found or boto3 not available
        """
        super().__init__(config)

        if boto3 is None:
            raise ValueError("boto3 library not installed. Please install with: pip install boto3")

        # Get AWS credentials
        aws_access_key = os.getenv(config["aws_access_key_env"])
        aws_secret_key = os.getenv(config["aws_secret_key_env"])
        aws_region = os.getenv(config["aws_region_env"], "us-east-1")

        if not aws_access_key or not aws_secret_key:
            raise ValueError(f"AWS credentials not found in environment variables: {config['aws_access_key_env']}, {config['aws_secret_key_env']}")

        self.client = boto3.client(
            "bedrock-runtime",
            aws_access_key_id=aws_access_key,
            aws_secret_access_key=aws_secret_key,
            region_name=aws_region,
        )

        self.model_id = config["model_id"]
        self.model = config["model_name"]

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
            Exception: If Bedrock API call fails
        """
        # Format for Anthropic models on Bedrock
        system_message = ""
        user_messages = []

        for msg in messages:
            if msg["role"] == "system":
                system_message = msg["content"]
            else:
                user_messages.append({"role": msg["role"], "content": msg["content"]})

        # Combine system message with first user message for Bedrock
        if system_message and user_messages:
            user_messages[0]["content"] = f"{system_message}\n\n{user_messages[0]['content']}"

        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens or self.max_tokens,
            "temperature": temperature or self.temperature,
            "messages": user_messages,
        }

        try:
            # Run in thread pool since boto3 is synchronous
            # Standard
            import concurrent.futures  # pylint: disable=import-outside-toplevel

            def make_request():
                return self.client.invoke_model(
                    modelId=self.model_id,
                    body=orjson.dumps(body),
                    contentType="application/json",
                    accept="application/json",
                )

            loop = asyncio.get_event_loop()
            with concurrent.futures.ThreadPoolExecutor() as executor:
                response = await loop.run_in_executor(executor, make_request)

            response_body = orjson.loads(response["body"].read())
            return response_body.get("content", [{}])[0].get("text", "")

        except ClientError as e:
            raise Exception(f"Bedrock API call failed: {e}")

    async def evaluate_response(
        self,
        response: str,
        criteria: List[EvaluationCriteria],
        rubric: EvaluationRubric,
        context: Optional[str] = None,
        use_cot: bool = True,
    ) -> EvaluationResult:
        """Evaluate a single response using Bedrock.

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
        """Compare two responses using Bedrock.

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
        """Rank multiple responses using Bedrock.

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
        """Evaluate response against reference using Bedrock.

        Args:
            response: Response text to evaluate
            reference: Reference text to compare against
            evaluation_type: Type of evaluation
            tolerance: Tolerance level for evaluation

        Returns:
            ReferenceEvaluationResult containing score and analysis
        """
        return await self._base_reference_evaluation(response, reference, evaluation_type, tolerance)
