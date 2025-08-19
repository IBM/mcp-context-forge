# -*- coding: utf-8 -*-
"""MCP tools for LLM-as-a-judge evaluation."""

# Standard
import asyncio
import os
import statistics
from typing import Any, Dict, List, Optional

# Third-Party
import yaml

# Local
from ..judges.azure_judge import AzureOpenAIJudge
from ..judges.base_judge import (
    EvaluationCriteria,
    EvaluationRubric,
)
from ..judges.openai_judge import OpenAIJudge
from ..judges.rule_judge import RuleBasedJudge


class JudgeTools:
    """Tools for LLM-as-a-judge evaluation."""

    def __init__(self, config_path: Optional[str] = None):
        """Initialize judge tools.

        Args:
            config_path: Path to models configuration file
        """
        self.judges = {}
        self.config_path = config_path or os.path.join(os.path.dirname(__file__), "..", "config", "models.yaml")
        self._load_judges()

    def _load_judges(self) -> None:
        """Load all configured judge models from configuration file or defaults.

        This method initializes OpenAI, Azure OpenAI, and rule-based judges
        based on the configuration file or default settings if file is missing.
        """
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
        except FileNotFoundError:
            # Default configuration if file not found
            config = self._get_default_config()

        # Load OpenAI models
        for model_name, model_config in config.get("models", {}).get("openai", {}).items():
            try:
                self.judges[model_name] = OpenAIJudge(model_config)
            except Exception as e:
                print(f"Warning: Could not load OpenAI judge {model_name}: {e}")

        # Load Azure OpenAI models
        for model_name, model_config in config.get("models", {}).get("azure", {}).items():
            try:
                self.judges[model_name] = AzureOpenAIJudge(model_config)
            except Exception as e:
                print(f"Warning: Could not load Azure judge {model_name}: {e}")

        # Always include rule-based judge
        self.judges["rule-based"] = RuleBasedJudge({"model_name": "rule-based"})

    def _get_default_config(self) -> Dict[str, Any]:
        """Get default configuration when config file is missing.

        Returns:
            Dict[str, Any]: Default configuration with OpenAI and Azure model settings.
        """
        return {
            "models": {
                "openai": {
                    "gpt-4": {
                        "provider": "openai",
                        "model_name": "gpt-4",
                        "api_key_env": "OPENAI_API_KEY",
                        "default_temperature": 0.3,
                        "max_tokens": 2000,
                    },
                    "gpt-3.5-turbo": {
                        "provider": "openai",
                        "model_name": "gpt-3.5-turbo",
                        "api_key_env": "OPENAI_API_KEY",
                        "default_temperature": 0.3,
                        "max_tokens": 2000,
                    },
                },
                "azure": {},
            }
        }

    def get_available_judges(self) -> List[str]:
        """Get list of available judge models.

        Returns:
            List[str]: List of available judge model names.
        """
        return list(self.judges.keys())

    async def evaluate_response(
        self,
        response: str,
        criteria: List[Dict[str, Any]],
        rubric: Dict[str, Any],
        judge_model: str = "gpt-4",
        context: Optional[str] = None,
        use_cot: bool = True,
    ) -> Dict[str, Any]:
        """Evaluate response with specified judge model.

        Args:
            response: Text response to evaluate
            criteria: List of evaluation criteria as dicts
            rubric: Scoring rubric as dict
            judge_model: Judge model to use
            context: Optional context (e.g., original question)
            use_cot: Whether to use chain-of-thought reasoning

        Returns:
            Evaluation result as dict
        """
        # Convert criteria and rubric to proper objects
        criteria_objs = [EvaluationCriteria(**c) for c in criteria]
        rubric_obj = EvaluationRubric(**rubric)

        # Get judge, with fallback options
        judge = self._get_judge_with_fallback(judge_model)

        # Perform evaluation
        result = await judge.evaluate_response(response=response, criteria=criteria_objs, rubric=rubric_obj, context=context, use_cot=use_cot)

        # Convert result to dict for MCP response
        return {"scores": result.scores, "reasoning": result.reasoning, "overall_score": result.overall_score, "confidence": result.confidence, "metadata": result.metadata, "judge_model": judge_model}

    async def pairwise_comparison(
        self,
        response_a: str,
        response_b: str,
        criteria: List[Dict[str, Any]],
        judge_model: str = "gpt-4",
        context: Optional[str] = None,
        position_bias_mitigation: bool = True,
    ) -> Dict[str, Any]:
        """Compare two responses and determine which is better.

        Args:
            response_a: First response
            response_b: Second response
            criteria: Comparison criteria as dicts
            judge_model: Judge model to use
            context: Optional context (e.g., original question)
            position_bias_mitigation: Whether to mitigate position bias

        Returns:
            Pairwise comparison result as dict
        """
        criteria_objs = [EvaluationCriteria(**c) for c in criteria]
        judge = self._get_judge_with_fallback(judge_model)

        result = await judge.pairwise_comparison(response_a=response_a, response_b=response_b, criteria=criteria_objs, context=context, position_bias_mitigation=position_bias_mitigation)

        return {
            "winner": result.winner,
            "confidence_score": result.confidence_score,
            "reasoning": result.reasoning,
            "criterion_scores": result.criterion_scores,
            "margin": result.margin,
            "judge_model": judge_model,
        }

    async def rank_responses(
        self,
        responses: List[str],
        criteria: List[Dict[str, Any]],
        judge_model: str = "gpt-4",
        context: Optional[str] = None,
        ranking_method: str = "tournament",
    ) -> Dict[str, Any]:
        """Rank multiple responses from best to worst.

        Args:
            responses: List of responses to rank
            criteria: Ranking criteria as dicts
            judge_model: Judge model to use
            context: Optional context
            ranking_method: Method to use ('tournament', 'round_robin', 'scoring')

        Returns:
            Ranking result as dict

        Raises:
            ValueError: If fewer than 2 responses provided for ranking.
        """
        if len(responses) < 2:
            raise ValueError("Need at least 2 responses to rank")

        criteria_objs = [EvaluationCriteria(**c) for c in criteria]
        judge = self._get_judge_with_fallback(judge_model)

        result = await judge.rank_responses(responses=responses, criteria=criteria_objs, context=context, ranking_method=ranking_method)

        return {
            "rankings": result.rankings,
            "pairwise_matrix": result.pairwise_matrix,
            "consistency_score": result.consistency_score,
            "reasoning": result.reasoning,
            "judge_model": judge_model,
            "ranking_method": ranking_method,
        }

    async def evaluate_with_reference(
        self,
        response: str,
        reference: str,
        judge_model: str = "gpt-4",
        evaluation_type: str = "factuality",
        tolerance: str = "moderate",
    ) -> Dict[str, Any]:
        """Evaluate response against a gold standard reference.

        Args:
            response: Generated response
            reference: Gold standard answer
            judge_model: Judge model to use
            evaluation_type: Type of evaluation ('factuality', 'completeness', 'style_match')
            tolerance: Flexibility in matching ('strict', 'moderate', 'loose')

        Returns:
            Reference evaluation result as dict
        """
        judge = self._get_judge_with_fallback(judge_model)

        result = await judge.evaluate_with_reference(response=response, reference=reference, evaluation_type=evaluation_type, tolerance=tolerance)

        return {
            "similarity_score": result.similarity_score,
            "missing_elements": result.missing_elements,
            "extra_elements": result.extra_elements,
            "factual_errors": result.factual_errors,
            "reasoning": result.reasoning,
            "judge_model": judge_model,
            "evaluation_type": evaluation_type,
            "tolerance": tolerance,
        }

    async def batch_evaluate(
        self,
        responses: List[str],
        criteria: List[Dict[str, Any]],
        rubric: Dict[str, Any],
        judge_model: str = "gpt-4",
        context: Optional[str] = None,
        use_cot: bool = True,
        max_concurrent: int = 5,
    ) -> List[Dict[str, Any]]:
        """Evaluate multiple responses in parallel.

        Args:
            responses: List of responses to evaluate
            criteria: Evaluation criteria
            rubric: Scoring rubric
            judge_model: Judge model to use
            context: Optional context
            use_cot: Whether to use chain-of-thought
            max_concurrent: Maximum concurrent evaluations

        Returns:
            List of evaluation results
        """
        semaphore = asyncio.Semaphore(max_concurrent)

        async def evaluate_single(response: str) -> Dict[str, Any]:
            async with semaphore:
                return await self.evaluate_response(response=response, criteria=criteria, rubric=rubric, judge_model=judge_model, context=context, use_cot=use_cot)

        tasks = [evaluate_single(response) for response in responses]
        results = await asyncio.gather(*tasks)

        return results

    async def multi_judge_evaluation(
        self,
        response: str,
        criteria: List[Dict[str, Any]],
        rubric: Dict[str, Any],
        judge_models: List[str],
        context: Optional[str] = None,
        use_cot: bool = True,
    ) -> Dict[str, Any]:
        """Evaluate response with multiple judges for consensus.

        Args:
            response: Response to evaluate
            criteria: Evaluation criteria
            rubric: Scoring rubric
            judge_models: List of judge models to use
            context: Optional context
            use_cot: Whether to use chain-of-thought

        Returns:
            Aggregated evaluation results from multiple judges

        Raises:
            Exception: If all judge evaluations fail.
        """
        tasks = []
        for judge_model in judge_models:
            tasks.append(self.evaluate_response(response=response, criteria=criteria, rubric=rubric, judge_model=judge_model, context=context, use_cot=use_cot))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Aggregate results
        valid_results = [r for r in results if not isinstance(r, Exception)]

        if not valid_results:
            raise Exception("All judge evaluations failed")

        # Calculate consensus scores
        consensus_scores = {}
        all_reasoning = {}

        criteria_names = [c["name"] for c in criteria]

        for criterion_name in criteria_names:
            scores = [r["scores"].get(criterion_name, 0) for r in valid_results]
            consensus_scores[criterion_name] = sum(scores) / len(scores)

            reasonings = [r["reasoning"].get(criterion_name, "") for r in valid_results]
            all_reasoning[criterion_name] = " | ".join(reasonings)

        overall_score = sum(consensus_scores.values()) / len(consensus_scores)

        # Calculate agreement (standard deviation)
        agreement_scores = {}
        for criterion_name in criteria_names:
            scores = [r["scores"].get(criterion_name, 0) for r in valid_results]
            if len(scores) > 1:
                agreement_scores[criterion_name] = 1.0 - min(1.0, statistics.stdev(scores) / 2.0)
            else:
                agreement_scores[criterion_name] = 1.0

        average_agreement = sum(agreement_scores.values()) / len(agreement_scores)

        return {
            "consensus_scores": consensus_scores,
            "consensus_reasoning": all_reasoning,
            "overall_score": overall_score,
            "individual_results": valid_results,
            "agreement_scores": agreement_scores,
            "average_agreement": average_agreement,
            "judges_used": judge_models,
            "successful_judges": len(valid_results),
            "failed_judges": len(results) - len(valid_results),
        }

    def _get_judge_with_fallback(self, judge_model: str):
        """Get judge with fallback to available alternatives.

        Args:
            judge_model: Name of the requested judge model.

        Returns:
            Judge instance, falling back to gpt-4, gpt-3.5-turbo, or rule-based if needed.

        Raises:
            ValueError: If no judges are available.
        """
        if judge_model in self.judges:
            return self.judges[judge_model]

        # Try common fallbacks
        fallbacks = ["gpt-4", "gpt-3.5-turbo", "rule-based"]
        for fallback in fallbacks:
            if fallback in self.judges:
                print(f"Warning: Judge {judge_model} not available, using {fallback}")
                return self.judges[fallback]

        # Last resort: rule-based judge
        if "rule-based" in self.judges:
            print(f"Warning: Judge {judge_model} not available, using rule-based judge")
            return self.judges["rule-based"]

        raise ValueError(f"No judges available. Requested: {judge_model}")

    def get_judge_info(self, judge_model: str) -> Dict[str, Any]:
        """Get information about a judge model.

        Args:
            judge_model: Name of the judge model to get information for.

        Returns:
            Dict[str, Any]: Information about the judge including model name,
                temperature, max tokens, provider, and availability.
        """
        if judge_model not in self.judges:
            return {"error": f"Judge model {judge_model} not found"}

        judge = self.judges[judge_model]

        return {"model_name": judge.model_name, "temperature": judge.temperature, "max_tokens": judge.max_tokens, "provider": judge.config.get("provider", "unknown"), "available": True}
