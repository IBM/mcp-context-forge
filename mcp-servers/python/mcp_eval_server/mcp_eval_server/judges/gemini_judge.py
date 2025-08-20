# -*- coding: utf-8 -*-
"""Google Gemini judge implementation for LLM-as-a-judge evaluation."""

# Standard
import asyncio
import json
import logging
import os
import secrets
from typing import Any, Dict, List, Optional

try:
    # Third-Party
    import google.generativeai as genai
    from google.generativeai.types import HarmBlockThreshold, HarmCategory
except ImportError:
    genai = None

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


class GeminiJudge(BaseJudge):
    """Judge implementation using Google Gemini API."""

    def __init__(self, config: Dict[str, Any]) -> None:
        """Initialize Gemini judge.

        Args:
            config: Configuration dictionary with Gemini settings

        Raises:
            ValueError: If API key not found or Gemini library not available
        """
        super().__init__(config)
        self.logger = logging.getLogger(__name__)

        if genai is None:
            raise ValueError("Google Generative AI library not installed. Please install with: pip install google-generativeai")

        api_key = os.getenv(config["api_key_env"])
        if not api_key:
            raise ValueError(f"API key not found in environment variable: {config['api_key_env']}")

        genai.configure(api_key=api_key)
        self.model_name = config["model_name"]

        # Initialize the model
        self.model = genai.GenerativeModel(
            model_name=self.model_name,
            safety_settings={
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            },
        )

        self.logger.debug(f"🔧 Initialized Gemini judge: {self.model_name}")

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
            Exception: If Gemini API call fails
        """
        self.logger.debug(f"🔗 Making Gemini API call to {self.model_name}")
        self.logger.debug(f"   Messages: {len(messages)}, Temperature: {temperature or self.temperature}, Max tokens: {max_tokens or self.max_tokens}")

        # Convert messages to Gemini format
        prompt_parts = []
        for msg in messages:
            if msg["role"] == "system":
                prompt_parts.append(f"System: {msg['content']}")
            elif msg["role"] == "user":
                prompt_parts.append(f"User: {msg['content']}")
            elif msg["role"] == "assistant":
                prompt_parts.append(f"Assistant: {msg['content']}")

        prompt = "\n\n".join(prompt_parts)

        # Generation config
        generation_config = genai.types.GenerationConfig(
            temperature=temperature or self.temperature,
            max_output_tokens=max_tokens or self.max_tokens,
        )

        try:
            # Run in thread pool since Google library is sync
            # Standard
            import concurrent.futures

            def make_request():
                response = self.model.generate_content(prompt, generation_config=generation_config)
                return response.text if response.text else ""

            loop = asyncio.get_event_loop()
            with concurrent.futures.ThreadPoolExecutor() as executor:
                result = await loop.run_in_executor(executor, make_request)

            self.logger.debug(f"✅ Gemini API response received - Length: {len(result)} chars")

            # Log the actual model response (truncated)
            truncated_response = result[:200] + "..." if len(result) > 200 else result
            self.logger.debug(f"   💬 Model response: {truncated_response}")

            return result

        except Exception as e:
            raise Exception(f"Gemini API call failed: {e}")

    async def evaluate_response(
        self,
        response: str,
        criteria: List[EvaluationCriteria],
        rubric: EvaluationRubric,
        context: Optional[str] = None,
        use_cot: bool = True,
    ) -> EvaluationResult:
        """Evaluate a single response using Gemini.

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

        return self._parse_evaluation_response(response_text, criteria, model=self.model_name, temperature=self.temperature, use_cot=use_cot)

    async def pairwise_comparison(
        self,
        response_a: str,
        response_b: str,
        criteria: List[EvaluationCriteria],
        context: Optional[str] = None,
        position_bias_mitigation: bool = True,
    ) -> PairwiseResult:
        """Compare two responses using Gemini.

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
        context_section = f"\n\nCONTEXT:\n{context}" if context else ""

        prompt = f"""You are an expert evaluator. Compare the following two responses and determine which is better.

{context_section}

RESPONSE A:
{response_a}

RESPONSE B:
{response_b}

COMPARISON CRITERIA:
{criteria_text}

Please provide a detailed comparison and determine the winner. Consider each criterion carefully.

Provide your evaluation in the following JSON format:
{{
    "winner": "A" | "B" | "tie",
    "confidence_score": confidence_level_0_to_1,
    "reasoning": "detailed comparison reasoning",
    "criterion_scores": {{
        "criterion_name": "A" | "B" | "tie",
        ...
    }},
    "margin": strength_of_preference_0_to_1
}}"""

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
        """Rank multiple responses using Gemini.

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
            criteria: Evaluation criteria to use for scoring
            context: Optional context for evaluation

        Returns:
            RankingResult containing ranked responses with scores and reasoning
        """
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

    async def _rank_by_tournament(self, responses: List[str], criteria: List[EvaluationCriteria], context: Optional[str] = None) -> RankingResult:
        """Rank using tournament-style pairwise comparisons.

        Args:
            responses: List of response strings to rank
            criteria: Evaluation criteria to use for comparisons
            context: Optional context for evaluation

        Returns:
            RankingResult containing ranked responses based on tournament wins
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
            ranked_results.append({"response_index": idx, "response": responses[idx], "score": wins[idx] / (n - 1), "wins": wins[idx], "rank": rank + 1})

        # Calculate consistency (simplified)
        consistency = 1.0 - (sum(abs(wins[i] - wins[j]) for i in range(n) for j in range(i + 1, n)) / (n * (n - 1) / 2)) / n

        return RankingResult(rankings=ranked_results, consistency_score=max(0.0, consistency), reasoning="Ranked by tournament-style pairwise comparisons")

    async def _rank_by_round_robin(self, responses: List[str], criteria: List[EvaluationCriteria], context: Optional[str] = None) -> RankingResult:
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

    async def evaluate_with_reference(
        self,
        response: str,
        reference: str,
        evaluation_type: str = "factuality",
        tolerance: str = "moderate",
    ) -> ReferenceEvaluationResult:
        """Evaluate response against reference using Gemini.

        Args:
            response: Response text to evaluate
            reference: Reference text to compare against
            evaluation_type: Type of evaluation ("factuality", "completeness", "style_match")
            tolerance: Tolerance level for evaluation ("strict", "moderate", "lenient")

        Returns:
            ReferenceEvaluationResult containing score and analysis
        """

        type_descriptions = {
            "factuality": "Compare the factual accuracy and correctness of information",
            "completeness": "Assess how completely the response covers the reference content",
            "style_match": "Evaluate how well the writing style and tone match the reference",
        }

        tolerance_descriptions = {
            "strict": "Require exact matches and perfect alignment",
            "moderate": "Allow reasonable variations while maintaining core accuracy",
            "loose": "Accept substantial variations as long as general meaning is preserved",
        }

        prompt = f"""You are an expert evaluator. Compare the following response against the reference and evaluate based on {evaluation_type}.

REFERENCE (Gold Standard):
{reference}

RESPONSE TO EVALUATE:
{response}

EVALUATION TYPE: {type_descriptions.get(evaluation_type, evaluation_type)}
TOLERANCE LEVEL: {tolerance_descriptions.get(tolerance, tolerance)}

Please provide your evaluation in the following JSON format:
{{
    "similarity_score": overall_similarity_0_to_1,
    "missing_elements": ["element1", "element2", ...],
    "extra_elements": ["element1", "element2", ...],
    "factual_errors": ["error1", "error2", ...],
    "reasoning": "detailed comparison reasoning"
}}"""

        messages = [{"role": "system", "content": "You are a professional evaluation expert. Provide thorough, accurate assessments against reference standards."}, {"role": "user", "content": prompt}]

        response_text = await self._make_api_call(messages)

        return self._parse_reference_response(response_text)
