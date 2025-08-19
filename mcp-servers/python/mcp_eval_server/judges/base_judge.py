# -*- coding: utf-8 -*-
"""Base abstract interface for LLM judges."""

# Standard
import abc
from typing import Any, Dict, List, Optional, Protocol, Union

# Third-Party
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
