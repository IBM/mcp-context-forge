#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/mcp_eval_server/mcp_eval_server/rest_server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

FastAPI REST server for MCP Evaluation Tools.

This module provides a REST API interface to all the evaluation tools
available in the MCP Evaluation Server. It groups tools logically by
category and provides comprehensive API documentation.
"""

# Standard
import argparse
import logging
import os
import sys
import time
from typing import Any, Dict, List, Optional

try:
    # Third-Party
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.openapi.utils import get_openapi
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel, Field
    import uvicorn
except ImportError:
    print("❌ FastAPI dependencies not installed!")
    print("💡 Install with: pip install fastapi uvicorn")
    sys.exit(1)

# Load .env file if it exists
try:
    # Third-Party
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# Local
from .storage.cache import BenchmarkCache, EvaluationCache, JudgeResponseCache
from .storage.results_store import ResultsStore
from .tools.agent_tools import AgentTools
from .tools.bias_tools import BiasTools
from .tools.calibration_tools import CalibrationTools

# Import all tool classes
from .tools.judge_tools import JudgeTools
from .tools.multilingual_tools import MultilingualTools
from .tools.performance_tools import PerformanceTools
from .tools.privacy_tools import PrivacyTools
from .tools.prompt_tools import PromptTools
from .tools.quality_tools import QualityTools
from .tools.rag_tools import RAGTools
from .tools.robustness_tools import RobustnessTools
from .tools.safety_tools import SafetyTools
from .tools.workflow_tools import WorkflowTools

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="MCP Evaluation Server REST API",
    description="Comprehensive AI evaluation platform with 60+ specialized tools across 14 categories",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# Global tools (initialized on startup)
tools = {}


# Pydantic models for API requests/responses
class ServerInfo(BaseModel):
    """Server information response."""

    name: str = Field(description="Server name")
    version: str = Field(description="Server version")
    description: str = Field(description="Server description")
    total_tools: int = Field(description="Total number of evaluation tools")
    categories: List[str] = Field(description="Available tool categories")
    status: str = Field(description="Server status")


class HealthCheck(BaseModel):
    """Health check response."""

    status: str = Field(description="Health status")
    timestamp: float = Field(description="Unix timestamp")
    service: str = Field(description="Service name")
    version: str = Field(description="Service version")
    checks: Dict[str, bool] = Field(description="Individual health check results")


# Judge evaluation models
class EvaluationCriterion(BaseModel):
    """Evaluation criterion."""

    name: str = Field(description="Criterion name")
    description: str = Field(description="Criterion description")
    scale: str = Field(description="Evaluation scale (e.g., '1-5')")
    weight: float = Field(description="Criterion weight")


class EvaluationRubric(BaseModel):
    """Evaluation rubric."""

    criteria: List[Dict[str, Any]] = Field(default=[], description="Additional rubric criteria")
    scale_description: Dict[str, str] = Field(description="Scale value descriptions")


class JudgeEvaluateRequest(BaseModel):
    """Request for judge evaluation."""

    response: str = Field(description="Text response to evaluate")
    criteria: List[EvaluationCriterion] = Field(description="Evaluation criteria")
    rubric: EvaluationRubric = Field(description="Scoring rubric")
    judge_model: str = Field(default="gpt-4o-mini", description="Judge model to use")
    context: Optional[str] = Field(None, description="Optional context")
    use_cot: bool = Field(True, description="Use chain-of-thought reasoning")


class JudgeCompareRequest(BaseModel):
    """Request for judge pairwise comparison."""

    response_a: str = Field(description="First response")
    response_b: str = Field(description="Second response")
    criteria: List[EvaluationCriterion] = Field(description="Comparison criteria")
    judge_model: str = Field(default="gpt-4o-mini", description="Judge model to use")
    context: Optional[str] = Field(None, description="Optional context")
    position_bias_mitigation: bool = Field(True, description="Enable position bias mitigation")


class JudgeRankRequest(BaseModel):
    """Request for judge ranking."""

    responses: List[str] = Field(description="List of responses to rank")
    criteria: List[EvaluationCriterion] = Field(description="Ranking criteria")
    judge_model: str = Field(default="gpt-4o-mini", description="Judge model to use")
    context: Optional[str] = Field(None, description="Optional context")
    ranking_method: str = Field(default="tournament", description="Ranking method")


class JudgeReferenceRequest(BaseModel):
    """Request for reference-based evaluation."""

    response: str = Field(description="Generated response")
    reference: str = Field(description="Gold standard reference")
    judge_model: str = Field(default="gpt-4o-mini", description="Judge model to use")
    evaluation_type: str = Field(default="factuality", description="Type of evaluation")
    tolerance: str = Field(default="moderate", description="Evaluation strictness")


# Quality evaluation models
class QualityFactualityRequest(BaseModel):
    """Request for factuality evaluation."""

    response: str = Field(description="Text to verify")
    knowledge_base: Optional[Dict[str, Any]] = Field(None, description="Reference sources")
    fact_checking_model: str = Field(default="gpt-4", description="Model for fact checking")
    confidence_threshold: float = Field(default=0.8, description="Minimum certainty")
    judge_model: str = Field(default="gpt-4o-mini", description="Judge model to use")


class QualityCoherenceRequest(BaseModel):
    """Request for coherence evaluation."""

    text: str = Field(description="Response to analyze")
    context: Optional[str] = Field(None, description="Conversation history")
    coherence_dimensions: List[str] = Field(default=["logical_flow", "consistency", "topic_transitions"], description="What to check")
    judge_model: str = Field(default="gpt-4o-mini", description="Judge model to use")


class QualityToxicityRequest(BaseModel):
    """Request for toxicity assessment."""

    content: str = Field(description="Text to analyze")
    toxicity_categories: List[str] = Field(default=["profanity", "hate_speech", "threats", "discrimination"], description="Types to check")
    sensitivity_level: str = Field(default="moderate", description="Detection threshold")
    judge_model: str = Field(default="gpt-4o-mini", description="Judge model to use")


# Prompt evaluation models
class PromptClarityRequest(BaseModel):
    """Request for prompt clarity evaluation."""

    prompt_text: str = Field(description="The prompt to evaluate")
    target_model: str = Field(default="general", description="Model the prompt is designed for")
    domain_context: Optional[str] = Field(None, description="Optional domain-specific requirements")
    judge_model: str = Field(default="gpt-4o-mini", description="Judge model to use")


class PromptConsistencyRequest(BaseModel):
    """Request for prompt consistency testing."""

    prompt: str = Field(description="Prompt template")
    test_inputs: List[str] = Field(description="List of input variations")
    num_runs: int = Field(default=3, description="Repetitions per input")
    temperature_range: List[float] = Field(default=[0.1, 0.5, 0.9], description="Test different temperatures")
    judge_model: str = Field(default="gpt-4o-mini", description="Judge model to use")


class PromptCompletenessRequest(BaseModel):
    """Request for prompt completeness measurement."""

    prompt: str = Field(description="The prompt text")
    expected_components: List[str] = Field(description="List of required elements")
    test_samples: Optional[List[str]] = Field(None, description="Sample outputs to analyze")
    judge_model: str = Field(default="gpt-4o-mini", description="Judge model to use")


class PromptRelevanceRequest(BaseModel):
    """Request for prompt relevance assessment."""

    prompt: str = Field(description="Input prompt")
    outputs: List[str] = Field(description="Generated responses")
    embedding_model: str = Field(default="all-MiniLM-L6-v2", description="Model for semantic similarity")
    relevance_threshold: float = Field(default=0.7, description="Minimum acceptable score")
    judge_model: str = Field(default="gpt-4o-mini", description="Judge model to use")


# Agent evaluation models
class AgentToolUseRequest(BaseModel):
    """Request for agent tool usage evaluation."""

    agent_trace: Dict[str, Any] = Field(description="Complete execution trace with tool calls")
    expected_tools: List[str] = Field(description="Tools that should be used")
    tool_sequence_matters: bool = Field(default=False, description="Whether order is important")
    allow_extra_tools: bool = Field(default=True, description="Permit additional tool calls")
    judge_model: str = Field(default="gpt-4o-mini", description="Judge model to use")


class AgentTaskCompletionRequest(BaseModel):
    """Request for agent task completion evaluation."""

    task_description: str = Field(description="What the agent should accomplish")
    success_criteria: List[Dict[str, Any]] = Field(description="Measurable outcomes")
    agent_trace: Dict[str, Any] = Field(description="Execution history")
    final_state: Optional[Dict[str, Any]] = Field(None, description="System state after execution")
    judge_model: str = Field(default="gpt-4o-mini", description="Judge model to use")


class AgentReasoningRequest(BaseModel):
    """Request for agent reasoning analysis."""

    reasoning_trace: List[Dict[str, Any]] = Field(description="Agent's thought process")
    decision_points: List[Dict[str, Any]] = Field(description="Key choices made")
    context: Dict[str, Any] = Field(description="Available information")
    optimal_path: Optional[List[str]] = Field(None, description="Best possible approach")
    judge_model: str = Field(default="gpt-4o-mini", description="Judge model to use")


class AgentBenchmarkRequest(BaseModel):
    """Request for agent benchmarking."""

    benchmark_suite: str = Field(description="Which tests to run")
    agent_config: Dict[str, Any] = Field(description="Agent setup")
    baseline_comparison: Optional[Dict[str, Any]] = Field(None, description="Compare to other agents")
    metrics_focus: List[str] = Field(default=["accuracy", "efficiency", "reliability"], description="Priority metrics")


# RAG evaluation models
class RAGRetrievalRelevanceRequest(BaseModel):
    """Request for RAG retrieval relevance evaluation."""

    query: str = Field(description="Original user query")
    retrieved_documents: List[Dict[str, Any]] = Field(description="List of retrieved docs with 'content' and optional 'score'")
    relevance_threshold: float = Field(default=0.7, description="Minimum relevance score")
    embedding_model: str = Field(default="text-embedding-ada-002", description="Model for semantic similarity")
    judge_model: str = Field(default="gpt-4o-mini", description="LLM judge for relevance assessment")
    use_llm_judge: bool = Field(default=True, description="Whether to use LLM judge in addition to embeddings")


class RAGContextUtilizationRequest(BaseModel):
    """Request for RAG context utilization evaluation."""

    query: str = Field(description="Original query")
    retrieved_context: str = Field(description="Full retrieved context")
    generated_answer: str = Field(description="Model's generated response")
    context_chunks: Optional[List[str]] = Field(None, description="Optional list of individual context chunks")
    judge_model: str = Field(default="gpt-4o-mini", description="Judge model for evaluation")


class RAGAnswerGroundednessRequest(BaseModel):
    """Request for RAG answer groundedness evaluation."""

    question: str = Field(description="Original question")
    answer: str = Field(description="Generated answer to verify")
    supporting_context: str = Field(description="Context that should support the answer")
    judge_model: str = Field(default="gpt-4o-mini", description="Judge model for evaluation")
    strictness: str = Field(default="moderate", description="Grounding strictness")


class RAGHallucinationDetectionRequest(BaseModel):
    """Request for RAG hallucination detection."""

    generated_text: str = Field(description="Text to analyze for hallucinations")
    source_context: str = Field(description="Source context to check against")
    judge_model: str = Field(default="gpt-4o-mini", description="Judge model for hallucination detection")
    detection_threshold: float = Field(default=0.8, description="Confidence threshold for hallucination detection")


# Initialize tools on startup
@app.on_event("startup")
async def startup_event():
    """Initialize all evaluation tools."""
    global tools  # pylint: disable=global-variable-not-assigned  # noqa: F824

    logger.info("🚀 Starting MCP Evaluation Server REST API...")
    logger.info("📡 Protocol: HTTP REST API")

    # Support custom configuration paths
    models_config_path = os.getenv("MCP_EVAL_MODELS_CONFIG")
    if models_config_path:
        logger.info(f"📄 Using custom models config: {models_config_path}")

    # Initialize all tool classes
    judge_tools = JudgeTools(config_path=models_config_path)

    tools.update(
        {
            "judge": judge_tools,
            "prompt": PromptTools(judge_tools),
            "agent": AgentTools(judge_tools),
            "quality": QualityTools(judge_tools),
            "rag": RAGTools(judge_tools),
            "bias": BiasTools(judge_tools),
            "robustness": RobustnessTools(judge_tools),
            "safety": SafetyTools(judge_tools),
            "multilingual": MultilingualTools(judge_tools),
            "performance": PerformanceTools(judge_tools),
            "privacy": PrivacyTools(judge_tools),
            "workflow": WorkflowTools(judge_tools, None, None, None),  # Initialize with minimal deps
            "calibration": CalibrationTools(judge_tools),
        }
    )

    # Initialize caching and storage
    tools["cache"] = {"evaluation": EvaluationCache(), "judge": JudgeResponseCache(), "benchmark": BenchmarkCache()}
    tools["storage"] = ResultsStore()

    # Log available judges
    available_judges = judge_tools.get_available_judges()
    logger.info(f"⚖️  Loaded {len(available_judges)} judge models: {available_judges}")

    logger.info("✅ REST API server startup complete!")


# Root endpoint
@app.get("/", response_model=ServerInfo, tags=["core"])
async def get_server_info():
    """Get server information and status.

    Returns:
        ServerInfo: Server information including name, version, and available categories.
    """
    categories = ["judge", "prompt", "agent", "quality", "rag", "bias", "robustness", "safety", "multilingual", "performance", "privacy", "workflow", "calibration"]

    return ServerInfo(
        name="MCP Evaluation Server REST API", version="0.1.0", description="Comprehensive AI evaluation platform with 60+ specialized tools", total_tools=63, categories=categories, status="healthy"
    )


# Health check endpoint
@app.get("/health", response_model=HealthCheck, tags=["core"])
async def health_check():
    """Health check endpoint for monitoring.

    Returns:
        HealthCheck: Health status with system checks and timestamps.
    """

    return HealthCheck(
        status="healthy",
        timestamp=time.time(),
        service="mcp-eval-server",
        version="0.1.0",
        checks={"server_running": True, "tools_loaded": len(tools) > 0, "judges_available": len(tools.get("judge", {}).get_available_judges() if tools.get("judge") else []) > 0},
    )


# Tool discovery endpoints
@app.get("/tools/categories", tags=["core"])
async def get_tool_categories():
    """Get list of available tool categories.

    Returns:
        Dict: Dictionary containing list of tool categories with descriptions and endpoints.
    """
    return {
        "categories": [
            {"name": "judge", "description": "LLM-as-a-judge evaluation tools", "tools": 4, "endpoints": ["/judge/evaluate", "/judge/compare", "/judge/rank", "/judge/reference"]},
            {"name": "prompt", "description": "Prompt quality evaluation tools", "tools": 4, "endpoints": ["/prompt/clarity", "/prompt/consistency", "/prompt/completeness", "/prompt/relevance"]},
            {"name": "agent", "description": "Agent performance evaluation tools", "tools": 4, "endpoints": ["/agent/tool-use", "/agent/task-completion", "/agent/reasoning", "/agent/benchmark"]},
            {"name": "quality", "description": "Content quality assessment tools", "tools": 3, "endpoints": ["/quality/factuality", "/quality/coherence", "/quality/toxicity"]},
            {
                "name": "rag",
                "description": "RAG system evaluation tools",
                "tools": 8,
                "endpoints": ["/rag/retrieval-relevance", "/rag/context-utilization", "/rag/answer-groundedness", "/rag/hallucination-detection"],
            },
            {"name": "bias", "description": "Bias and fairness assessment tools", "tools": 6, "endpoints": ["/bias/demographic", "/bias/representation-fairness", "/bias/cultural-sensitivity"]},
            {
                "name": "robustness",
                "description": "Robustness and security testing tools",
                "tools": 5,
                "endpoints": ["/robustness/adversarial", "/robustness/input-sensitivity", "/robustness/prompt-injection"],
            },
            {
                "name": "safety",
                "description": "Safety and alignment assessment tools",
                "tools": 4,
                "endpoints": ["/safety/harmful-content", "/safety/instruction-following", "/safety/value-alignment"],
            },
            {"name": "multilingual", "description": "Multilingual evaluation tools", "tools": 4, "endpoints": ["/multilingual/translation-quality", "/multilingual/cross-lingual-consistency"]},
            {
                "name": "performance",
                "description": "Performance monitoring tools",
                "tools": 4,
                "endpoints": ["/performance/latency", "/performance/computational-efficiency", "/performance/throughput-scaling"],
            },
            {"name": "privacy", "description": "Privacy and data protection tools", "tools": 8, "endpoints": ["/privacy/pii-detection", "/privacy/data-minimization", "/privacy/consent-compliance"]},
            {"name": "workflow", "description": "Workflow management tools", "tools": 3, "endpoints": ["/workflow/create-suite", "/workflow/run-evaluation", "/workflow/compare-evaluations"]},
            {"name": "calibration", "description": "Judge calibration tools", "tools": 2, "endpoints": ["/calibration/judge-agreement", "/calibration/optimize-rubrics"]},
        ]
    }


@app.get("/tools", tags=["core"])
async def get_all_tools():
    """Get detailed information about all available tools grouped by category.

    Returns:
        Dict: Dictionary with tools organized by category including names, descriptions, and endpoints.
    """
    return {
        "judge": {
            "evaluate": {
                "name": "judge.evaluate_response",
                "description": "Evaluate a single response using LLM-as-a-judge with customizable criteria and rubrics",
                "method": "POST",
                "endpoint": "/judge/evaluate",
            },
            "compare": {"name": "judge.pairwise_comparison", "description": "Compare two responses and determine which is better using LLM-as-a-judge", "method": "POST", "endpoint": "/judge/compare"},
            "rank": {"name": "judge.rank_responses", "description": "Rank multiple responses from best to worst using LLM-as-a-judge", "method": "POST", "endpoint": "/judge/rank"},
            "reference": {
                "name": "judge.evaluate_with_reference",
                "description": "Evaluate response against a gold standard reference using LLM-as-a-judge",
                "method": "POST",
                "endpoint": "/judge/reference",
            },
        },
        "quality": {
            "factuality": {"name": "quality.evaluate_factuality", "description": "Check factual accuracy of responses against knowledge bases", "method": "POST", "endpoint": "/quality/factuality"},
            "coherence": {"name": "quality.measure_coherence", "description": "Analyze logical flow and consistency of text", "method": "POST", "endpoint": "/quality/coherence"},
            "toxicity": {"name": "quality.assess_toxicity", "description": "Detect harmful or biased content", "method": "POST", "endpoint": "/quality/toxicity"},
        },
        "prompt": {
            "clarity": {"name": "prompt.evaluate_clarity", "description": "Assess prompt clarity using multiple rule-based and LLM-based metrics", "method": "POST", "endpoint": "/prompt/clarity"},
            "consistency": {
                "name": "prompt.test_consistency",
                "description": "Test prompt consistency across multiple runs and temperature settings",
                "method": "POST",
                "endpoint": "/prompt/consistency",
            },
            "completeness": {
                "name": "prompt.measure_completeness",
                "description": "Evaluate if prompt generates complete responses covering expected components",
                "method": "POST",
                "endpoint": "/prompt/completeness",
            },
            "relevance": {
                "name": "prompt.assess_relevance",
                "description": "Measure semantic alignment between prompt and outputs using embeddings",
                "method": "POST",
                "endpoint": "/prompt/relevance",
            },
        },
        # Additional categories would be added here...
    }


# Judge evaluation endpoints
@app.post("/judge/evaluate", tags=["judge"])
async def judge_evaluate(request: JudgeEvaluateRequest):
    """Evaluate a single response using LLM-as-a-judge.

    Args:
        request: JudgeEvaluateRequest with response, criteria, rubric, and judge model.

    Returns:
        Dict: Evaluation results with scores, reasoning, and metadata.

    Raises:
        HTTPException: If evaluation fails or invalid parameters provided.
    """
    try:
        # Convert Pydantic models to dict format expected by tools
        criteria = [criterion.dict() for criterion in request.criteria]
        rubric = request.rubric.dict()

        result = await tools["judge"].evaluate_response(response=request.response, criteria=criteria, rubric=rubric, judge_model=request.judge_model, context=request.context, use_cot=request.use_cot)
        return result
    except Exception as e:
        logger.error(f"Error in judge evaluation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/judge/compare", tags=["judge"])
async def judge_compare(request: JudgeCompareRequest):
    """Compare two responses using LLM-as-a-judge.

    Args:
        request: JudgeCompareRequest with two responses and comparison criteria.

    Returns:
        Dict: Comparison results with winner, scores, and reasoning.

    Raises:
        HTTPException: If comparison fails or invalid parameters provided.
    """
    try:
        criteria = [criterion.dict() for criterion in request.criteria]

        result = await tools["judge"].pairwise_comparison(
            response_a=request.response_a,
            response_b=request.response_b,
            criteria=criteria,
            judge_model=request.judge_model,
            context=request.context,
            position_bias_mitigation=request.position_bias_mitigation,
        )
        return result
    except Exception as e:
        logger.error(f"Error in judge comparison: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/judge/rank", tags=["judge"])
async def judge_rank(request: JudgeRankRequest):
    """Rank multiple responses using LLM-as-a-judge.

    Args:
        request: JudgeRankRequest with responses list and ranking criteria.

    Returns:
        Dict: Ranking results with ordered responses and scores.

    Raises:
        HTTPException: If ranking fails or invalid parameters provided.
    """
    try:
        criteria = [criterion.dict() for criterion in request.criteria]

        result = await tools["judge"].rank_responses(responses=request.responses, criteria=criteria, judge_model=request.judge_model, context=request.context, ranking_method=request.ranking_method)
        return result
    except Exception as e:
        logger.error(f"Error in judge ranking: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/judge/reference", tags=["judge"])
async def judge_reference(request: JudgeReferenceRequest):
    """Evaluate response against gold standard reference.

    Args:
        request: JudgeReferenceRequest with response, reference, and evaluation settings.

    Returns:
        Dict: Reference evaluation results with similarity scores and analysis.

    Raises:
        HTTPException: If evaluation fails or invalid parameters provided.
    """
    try:
        result = await tools["judge"].evaluate_with_reference(
            response=request.response, reference=request.reference, judge_model=request.judge_model, evaluation_type=request.evaluation_type, tolerance=request.tolerance
        )
        return result
    except Exception as e:
        logger.error(f"Error in reference evaluation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Quality assessment endpoints
@app.post("/quality/factuality", tags=["quality"])
async def quality_factuality(request: QualityFactualityRequest):
    """Check factual accuracy of responses.

    Args:
        request: QualityFactualityRequest with response and fact-checking parameters.

    Returns:
        Dict: Factuality assessment with accuracy scores and evidence analysis.

    Raises:
        HTTPException: If fact-checking fails or invalid parameters provided.
    """
    try:
        result = await tools["quality"].evaluate_factuality(
            response=request.response,
            knowledge_base=request.knowledge_base,
            fact_checking_model=request.fact_checking_model,
            confidence_threshold=request.confidence_threshold,
            judge_model=request.judge_model,
        )
        return result
    except Exception as e:
        logger.error(f"Error in factuality check: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/quality/coherence", tags=["quality"])
async def quality_coherence(request: QualityCoherenceRequest):
    """Analyze logical flow and consistency.

    Args:
        request: QualityCoherenceRequest with text and coherence analysis settings.

    Returns:
        Dict: Coherence analysis with flow scores and consistency metrics.

    Raises:
        HTTPException: If coherence analysis fails or invalid parameters provided.
    """
    try:
        result = await tools["quality"].measure_coherence(text=request.text, context=request.context, coherence_dimensions=request.coherence_dimensions, judge_model=request.judge_model)
        return result
    except Exception as e:
        logger.error(f"Error in coherence analysis: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/quality/toxicity", tags=["quality"])
async def quality_toxicity(request: QualityToxicityRequest):
    """Detect harmful or biased content.

    Args:
        request: QualityToxicityRequest with content and toxicity detection settings.

    Returns:
        Dict: Toxicity assessment with detection results and severity scores.

    Raises:
        HTTPException: If toxicity detection fails or invalid parameters provided.
    """
    try:
        result = await tools["quality"].assess_toxicity(
            content=request.content, toxicity_categories=request.toxicity_categories, sensitivity_level=request.sensitivity_level, judge_model=request.judge_model
        )
        return result
    except Exception as e:
        logger.error(f"Error in toxicity assessment: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Prompt evaluation endpoints
@app.post("/prompt/clarity", tags=["prompt"])
async def prompt_clarity(request: PromptClarityRequest):
    """Assess prompt clarity.

    Args:
        request: PromptClarityRequest with prompt text and evaluation settings.

    Returns:
        Dict: Clarity assessment with scores and improvement recommendations.

    Raises:
        HTTPException: If clarity evaluation fails or invalid parameters provided.
    """
    try:
        result = await tools["prompt"].evaluate_clarity(prompt_text=request.prompt_text, target_model=request.target_model, domain_context=request.domain_context, judge_model=request.judge_model)
        return result
    except Exception as e:
        logger.error(f"Error in prompt clarity evaluation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/prompt/consistency", tags=["prompt"])
async def prompt_consistency(request: PromptConsistencyRequest):
    """Test prompt consistency across runs.

    Args:
        request: PromptConsistencyRequest with prompt and testing parameters.

    Returns:
        Dict: Consistency analysis with variance metrics and stability scores.

    Raises:
        HTTPException: If consistency testing fails or invalid parameters provided.
    """
    try:
        result = await tools["prompt"].test_consistency(
            prompt=request.prompt, test_inputs=request.test_inputs, num_runs=request.num_runs, temperature_range=request.temperature_range, judge_model=request.judge_model
        )
        return result
    except Exception as e:
        logger.error(f"Error in prompt consistency testing: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/prompt/completeness", tags=["prompt"])
async def prompt_completeness(request: PromptCompletenessRequest):
    """Measure prompt completeness.

    Args:
        request: PromptCompletenessRequest with prompt and expected components.

    Returns:
        Dict: Completeness analysis with component coverage and scores.

    Raises:
        HTTPException: If completeness measurement fails or invalid parameters provided.
    """
    try:
        result = await tools["prompt"].measure_completeness(prompt=request.prompt, expected_components=request.expected_components, test_samples=request.test_samples, judge_model=request.judge_model)
        return result
    except Exception as e:
        logger.error(f"Error in prompt completeness measurement: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/prompt/relevance", tags=["prompt"])
async def prompt_relevance(request: PromptRelevanceRequest):
    """Assess prompt relevance.

    Args:
        request: PromptRelevanceRequest with prompt, outputs, and similarity settings.

    Returns:
        Dict: Relevance assessment with semantic alignment scores and analysis.

    Raises:
        HTTPException: If relevance assessment fails or invalid parameters provided.
    """
    try:
        result = await tools["prompt"].assess_relevance(
            prompt=request.prompt, outputs=request.outputs, embedding_model=request.embedding_model, relevance_threshold=request.relevance_threshold, judge_model=request.judge_model
        )
        return result
    except Exception as e:
        logger.error(f"Error in prompt relevance assessment: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Agent evaluation endpoints
@app.post("/agent/tool-use", tags=["agent"])
async def agent_tool_use(request: AgentToolUseRequest):
    """Evaluate agent tool usage.

    Args:
        request: AgentToolUseRequest with agent trace and expected tools.

    Returns:
        Dict: Tool usage evaluation with selection accuracy and efficiency scores.

    Raises:
        HTTPException: If tool usage evaluation fails or invalid parameters provided.
    """
    try:
        result = await tools["agent"].evaluate_tool_use(
            agent_trace=request.agent_trace,
            expected_tools=request.expected_tools,
            tool_sequence_matters=request.tool_sequence_matters,
            allow_extra_tools=request.allow_extra_tools,
            judge_model=request.judge_model,
        )
        return result
    except Exception as e:
        logger.error(f"Error in agent tool use evaluation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/agent/task-completion", tags=["agent"])
async def agent_task_completion(request: AgentTaskCompletionRequest):
    """Evaluate agent task completion.

    Args:
        request: AgentTaskCompletionRequest with task description and success criteria.

    Returns:
        Dict: Task completion analysis with success metrics and achievement scores.

    Raises:
        HTTPException: If task completion evaluation fails or invalid parameters provided.
    """
    try:
        result = await tools["agent"].measure_task_completion(
            task_description=request.task_description, success_criteria=request.success_criteria, agent_trace=request.agent_trace, final_state=request.final_state, judge_model=request.judge_model
        )
        return result
    except Exception as e:
        logger.error(f"Error in agent task completion evaluation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/agent/reasoning", tags=["agent"])
async def agent_reasoning(request: AgentReasoningRequest):
    """Analyze agent reasoning quality.

    Args:
        request: AgentReasoningRequest with reasoning trace and decision points.

    Returns:
        Dict: Reasoning analysis with logic quality and decision-making scores.

    Raises:
        HTTPException: If reasoning analysis fails or invalid parameters provided.
    """
    try:
        result = await tools["agent"].analyze_reasoning(
            reasoning_trace=request.reasoning_trace, decision_points=request.decision_points, context=request.context, optimal_path=request.optimal_path, judge_model=request.judge_model
        )
        return result
    except Exception as e:
        logger.error(f"Error in agent reasoning analysis: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/agent/benchmark", tags=["agent"])
async def agent_benchmark(request: AgentBenchmarkRequest):
    """Run agent performance benchmarks.

    Args:
        request: AgentBenchmarkRequest with benchmark suite and agent configuration.

    Returns:
        Dict: Benchmark results with performance metrics and comparative analysis.

    Raises:
        HTTPException: If benchmarking fails or invalid parameters provided.
    """
    try:
        result = await tools["agent"].benchmark_performance(
            benchmark_suite=request.benchmark_suite, agent_config=request.agent_config, baseline_comparison=request.baseline_comparison, metrics_focus=request.metrics_focus
        )
        return result
    except Exception as e:
        logger.error(f"Error in agent benchmarking: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# RAG evaluation endpoints
@app.post("/rag/retrieval-relevance", tags=["rag"])
async def rag_retrieval_relevance(request: RAGRetrievalRelevanceRequest):
    """Evaluate RAG retrieval relevance.

    Args:
        request: RAGRetrievalRelevanceRequest with query and retrieved documents.

    Returns:
        Dict: Retrieval relevance analysis with document scores and rankings.

    Raises:
        HTTPException: If retrieval evaluation fails or invalid parameters provided.
    """
    try:
        result = await tools["rag"].evaluate_retrieval_relevance(
            query=request.query,
            retrieved_documents=request.retrieved_documents,
            relevance_threshold=request.relevance_threshold,
            embedding_model=request.embedding_model,
            judge_model=request.judge_model,
            use_llm_judge=request.use_llm_judge,
        )
        return result
    except Exception as e:
        logger.error(f"Error in RAG retrieval relevance evaluation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/rag/context-utilization", tags=["rag"])
async def rag_context_utilization(request: RAGContextUtilizationRequest):
    """Evaluate RAG context utilization.

    Args:
        request: RAGContextUtilizationRequest with query, context, and generated answer.

    Returns:
        Dict: Context utilization analysis with usage metrics and integration scores.

    Raises:
        HTTPException: If context utilization evaluation fails or invalid parameters provided.
    """
    try:
        result = await tools["rag"].measure_context_utilization(
            query=request.query, retrieved_context=request.retrieved_context, generated_answer=request.generated_answer, context_chunks=request.context_chunks, judge_model=request.judge_model
        )
        return result
    except Exception as e:
        logger.error(f"Error in RAG context utilization evaluation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/rag/answer-groundedness", tags=["rag"])
async def rag_answer_groundedness(request: RAGAnswerGroundednessRequest):
    """Evaluate RAG answer groundedness.

    Args:
        request: RAGAnswerGroundednessRequest with question, answer, and supporting context.

    Returns:
        Dict: Groundedness evaluation with claim verification and support analysis.

    Raises:
        HTTPException: If groundedness evaluation fails or invalid parameters provided.
    """
    try:
        result = await tools["rag"].assess_answer_groundedness(
            question=request.question, answer=request.answer, supporting_context=request.supporting_context, judge_model=request.judge_model, strictness=request.strictness
        )
        return result
    except Exception as e:
        logger.error(f"Error in RAG answer groundedness evaluation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/rag/hallucination-detection", tags=["rag"])
async def rag_hallucination_detection(request: RAGHallucinationDetectionRequest):
    """Detect hallucinations in RAG responses.

    Args:
        request: RAGHallucinationDetectionRequest with generated text and source context.

    Returns:
        Dict: Hallucination detection results with contradiction analysis and confidence scores.

    Raises:
        HTTPException: If hallucination detection fails or invalid parameters provided.
    """
    try:
        result = await tools["rag"].detect_hallucination_vs_context(
            generated_text=request.generated_text, source_context=request.source_context, judge_model=request.judge_model, detection_threshold=request.detection_threshold
        )
        return result
    except Exception as e:
        logger.error(f"Error in RAG hallucination detection: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Custom OpenAPI schema generation
def custom_openapi():
    """Generate custom OpenAPI schema with enhanced documentation.

    Returns:
        Dict: OpenAPI schema with custom tags and enhanced documentation.
    """
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title="MCP Evaluation Server REST API",
        version="0.1.0",
        description="""
# MCP Evaluation Server REST API

## Overview
Comprehensive AI evaluation platform providing 60+ specialized evaluation tools across 14 categories.

## Features
- **LLM-as-a-Judge**: Advanced evaluation using GPT-4, Azure OpenAI, and other models
- **Multi-Category Assessment**: Judge, quality, prompt, agent, RAG, bias, safety, and more
- **Production Ready**: Health checks, monitoring, comprehensive error handling
- **Extensible**: Support for custom models, rubrics, and evaluation criteria

## Quick Start
1. **Health Check**: `GET /health` - Verify server status
2. **Discover Tools**: `GET /tools/categories` - See available evaluation categories
3. **Evaluate Content**: `POST /judge/evaluate` - Evaluate any AI response
4. **Interactive Docs**: Visit `/docs` for full API documentation

## Tool Categories
- **Judge (4 tools)**: Response evaluation, comparison, ranking, reference-based
- **Quality (3 tools)**: Factuality, coherence, toxicity detection
- **Prompt (4 tools)**: Clarity, consistency, completeness, relevance
- **Agent (4 tools)**: Tool usage, task completion, reasoning, benchmarking
- **RAG (8 tools)**: Retrieval relevance, context utilization, grounding verification
- **Bias (6 tools)**: Demographic bias, representation fairness, cultural sensitivity
- **Robustness (5 tools)**: Adversarial testing, input sensitivity, prompt injection
- **Safety (4 tools)**: Harmful content detection, instruction following, value alignment
- **Multilingual (4 tools)**: Translation quality, cross-lingual consistency, cultural adaptation
- **Performance (4 tools)**: Latency measurement, computational efficiency, throughput scaling
- **Privacy (8 tools)**: PII detection, data minimization, consent compliance, anonymization
- **Workflow (3 tools)**: Evaluation suites, parallel execution, results comparison
- **Calibration (2 tools)**: Judge agreement testing, rubric optimization
        """,
        routes=app.routes,
    )

    # Add custom tags for better organization
    openapi_schema["tags"] = [
        {"name": "core", "description": "Core server functionality"},
        {"name": "judge", "description": "LLM-as-a-judge evaluation tools"},
        {"name": "quality", "description": "Content quality assessment tools"},
        {"name": "prompt", "description": "Prompt evaluation and optimization tools"},
        {"name": "agent", "description": "AI agent performance evaluation tools"},
        {"name": "rag", "description": "RAG system evaluation tools"},
        {"name": "bias", "description": "Bias and fairness assessment tools"},
        {"name": "robustness", "description": "Robustness and security testing tools"},
        {"name": "safety", "description": "Safety and alignment assessment tools"},
        {"name": "multilingual", "description": "Multilingual evaluation tools"},
        {"name": "performance", "description": "Performance monitoring tools"},
        {"name": "privacy", "description": "Privacy and data protection tools"},
        {"name": "workflow", "description": "Workflow management tools"},
        {"name": "calibration", "description": "Judge calibration and optimization tools"},
    ]

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler for better error responses.

    Args:
        request: FastAPI request object.
        exc: Exception that was raised.

    Returns:
        JSONResponse: Formatted error response with details.
    """
    logger.error(f"Global exception on {request.url}: {exc}")
    return JSONResponse(status_code=500, content={"error": "Internal server error", "detail": str(exc), "type": type(exc).__name__})


def main():
    """Main function to run the REST API server."""
    parser = argparse.ArgumentParser(description="MCP Evaluation Server REST API")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8080, help="Port to bind to")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    parser.add_argument("--log-level", default="info", help="Log level")

    args = parser.parse_args()

    print("🚀 Starting MCP Evaluation Server REST API...")
    print(f"📍 Server URL: http://{args.host}:{args.port}")
    print(f"📚 API Documentation: http://{args.host}:{args.port}/docs")
    print(f"🔍 Health Check: http://{args.host}:{args.port}/health")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    uvicorn.run("mcp_eval_server.rest_server:app", host=args.host, port=args.port, reload=args.reload, log_level=args.log_level)


if __name__ == "__main__":
    main()
