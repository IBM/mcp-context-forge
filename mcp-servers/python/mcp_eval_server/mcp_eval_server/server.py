# -*- coding: utf-8 -*-
"""MCP Evaluation Server - Main entry point."""

# Standard
import asyncio
import json
import logging
import os
from typing import Any, Dict, List

# Load .env file if it exists
try:
    # Third-Party
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    # python-dotenv not available, skip
    pass

# Third-Party
from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

# Local
from .health import start_health_server, stop_health_server, mark_ready, mark_judge_tools_ready, mark_storage_ready
from .storage.cache import BenchmarkCache, EvaluationCache, JudgeResponseCache
from .storage.results_store import ResultsStore
from .tools.agent_tools import AgentTools
from .tools.calibration_tools import CalibrationTools
from .tools.judge_tools import JudgeTools
from .tools.prompt_tools import PromptTools
from .tools.quality_tools import QualityTools
from .tools.rag_tools import RAGTools
from .tools.workflow_tools import WorkflowTools

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
logger = logging.getLogger(__name__)

# Initialize server
server = Server("mcp-eval-server")

# Global variables for tools (initialized in main after .env loading)
JUDGE_TOOLS = None  # pylint: disable=invalid-name
PROMPT_TOOLS = None  # pylint: disable=invalid-name
AGENT_TOOLS = None  # pylint: disable=invalid-name
QUALITY_TOOLS = None  # pylint: disable=invalid-name
RAG_TOOLS = None  # pylint: disable=invalid-name
WORKFLOW_TOOLS = None  # pylint: disable=invalid-name
CALIBRATION_TOOLS = None  # pylint: disable=invalid-name
EVALUATION_CACHE = None  # pylint: disable=invalid-name
JUDGE_CACHE = None  # pylint: disable=invalid-name
BENCHMARK_CACHE = None  # pylint: disable=invalid-name
RESULTS_STORE = None  # pylint: disable=invalid-name


@server.list_tools()
async def list_tools() -> List[Tool]:
    """List all available evaluation tools.

    Returns:
        List[Tool]: List of all available tools for evaluation including judge,
            prompt, agent, quality, workflow, and calibration tools.
    """
    return [
        # Judge tools
        Tool(
            name="judge.evaluate_response",
            description="Evaluate a single response using LLM-as-a-judge with customizable criteria and rubrics",
            inputSchema={
                "type": "object",
                "properties": {
                    "response": {"type": "string", "description": "Text response to evaluate"},
                    "criteria": {"type": "array", "items": {"type": "object"}, "description": "List of evaluation criteria"},
                    "rubric": {"type": "object", "description": "Scoring rubric"},
                    "judge_model": {"type": "string", "default": "gpt-4o-mini", "description": "Judge model to use"},
                    "context": {"type": "string", "description": "Optional context"},
                    "use_cot": {"type": "boolean", "default": True, "description": "Use chain-of-thought reasoning"},
                },
                "required": ["response", "criteria", "rubric"],
            },
        ),
        Tool(
            name="judge.pairwise_comparison",
            description="Compare two responses and determine which is better using LLM-as-a-judge",
            inputSchema={
                "type": "object",
                "properties": {
                    "response_a": {"type": "string", "description": "First response"},
                    "response_b": {"type": "string", "description": "Second response"},
                    "criteria": {"type": "array", "items": {"type": "object"}, "description": "Comparison criteria"},
                    "judge_model": {"type": "string", "default": "gpt-4o-mini"},
                    "context": {"type": "string", "description": "Optional context"},
                    "position_bias_mitigation": {"type": "boolean", "default": True},
                },
                "required": ["response_a", "response_b", "criteria"],
            },
        ),
        Tool(
            name="judge.rank_responses",
            description="Rank multiple responses from best to worst using LLM-as-a-judge",
            inputSchema={
                "type": "object",
                "properties": {
                    "responses": {"type": "array", "items": {"type": "string"}, "description": "List of responses to rank"},
                    "criteria": {"type": "array", "items": {"type": "object"}, "description": "Ranking criteria"},
                    "judge_model": {"type": "string", "default": "gpt-4o-mini"},
                    "context": {"type": "string", "description": "Optional context"},
                    "ranking_method": {"type": "string", "default": "tournament", "enum": ["tournament", "round_robin", "scoring"]},
                },
                "required": ["responses", "criteria"],
            },
        ),
        Tool(
            name="judge.evaluate_with_reference",
            description="Evaluate response against a gold standard reference using LLM-as-a-judge",
            inputSchema={
                "type": "object",
                "properties": {
                    "response": {"type": "string", "description": "Generated response"},
                    "reference": {"type": "string", "description": "Gold standard reference"},
                    "judge_model": {"type": "string", "default": "gpt-4o-mini"},
                    "evaluation_type": {"type": "string", "default": "factuality", "enum": ["factuality", "completeness", "style_match"]},
                    "tolerance": {"type": "string", "default": "moderate", "enum": ["strict", "moderate", "loose"]},
                },
                "required": ["response", "reference"],
            },
        ),
        # Prompt evaluation tools
        Tool(
            name="prompt.evaluate_clarity",
            description="Assess prompt clarity using multiple rule-based and LLM-based metrics",
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt_text": {"type": "string", "description": "The prompt to evaluate"},
                    "target_model": {"type": "string", "default": "general", "description": "Model the prompt is designed for"},
                    "domain_context": {"type": "string", "description": "Optional domain-specific requirements"},
                    "judge_model": {"type": "string", "default": "gpt-4o-mini"},
                },
                "required": ["prompt_text"],
            },
        ),
        Tool(
            name="prompt.test_consistency",
            description="Test prompt consistency across multiple runs and temperature settings",
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Prompt template"},
                    "test_inputs": {"type": "array", "items": {"type": "string"}, "description": "List of input variations"},
                    "num_runs": {"type": "integer", "default": 3, "description": "Repetitions per input"},
                    "temperature_range": {"type": "array", "items": {"type": "number"}, "default": [0.1, 0.5, 0.9], "description": "Test different temperatures"},
                    "judge_model": {"type": "string", "default": "gpt-4o-mini"},
                },
                "required": ["prompt", "test_inputs"],
            },
        ),
        Tool(
            name="prompt.measure_completeness",
            description="Evaluate if prompt generates complete responses covering expected components",
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "The prompt text"},
                    "expected_components": {"type": "array", "items": {"type": "string"}, "description": "List of required elements"},
                    "test_samples": {"type": "array", "items": {"type": "string"}, "description": "Sample outputs to analyze"},
                    "judge_model": {"type": "string", "default": "gpt-4o-mini"},
                },
                "required": ["prompt", "expected_components"],
            },
        ),
        Tool(
            name="prompt.assess_relevance",
            description="Measure semantic alignment between prompt and outputs using embeddings",
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Input prompt"},
                    "outputs": {"type": "array", "items": {"type": "string"}, "description": "Generated responses"},
                    "embedding_model": {"type": "string", "default": "all-MiniLM-L6-v2", "description": "Model for semantic similarity"},
                    "relevance_threshold": {"type": "number", "default": 0.7, "description": "Minimum acceptable score"},
                    "judge_model": {"type": "string", "default": "gpt-4o-mini"},
                },
                "required": ["prompt", "outputs"],
            },
        ),
        # Agent evaluation tools
        Tool(
            name="agent.evaluate_tool_use",
            description="Assess agent's tool selection and usage effectiveness",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_trace": {"type": "object", "description": "Complete execution trace with tool calls"},
                    "expected_tools": {"type": "array", "items": {"type": "string"}, "description": "Tools that should be used"},
                    "tool_sequence_matters": {"type": "boolean", "default": False, "description": "Whether order is important"},
                    "allow_extra_tools": {"type": "boolean", "default": True, "description": "Permit additional tool calls"},
                    "judge_model": {"type": "string", "default": "gpt-4o-mini"},
                },
                "required": ["agent_trace", "expected_tools"],
            },
        ),
        Tool(
            name="agent.measure_task_completion",
            description="Evaluate end-to-end task success against measurable criteria",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_description": {"type": "string", "description": "What the agent should accomplish"},
                    "success_criteria": {"type": "array", "items": {"type": "object"}, "description": "Measurable outcomes"},
                    "agent_trace": {"type": "object", "description": "Execution history"},
                    "final_state": {"type": "object", "description": "System state after execution"},
                    "judge_model": {"type": "string", "default": "gpt-4o-mini"},
                },
                "required": ["task_description", "success_criteria", "agent_trace"],
            },
        ),
        Tool(
            name="agent.analyze_reasoning",
            description="Evaluate agent's decision-making process and reasoning quality",
            inputSchema={
                "type": "object",
                "properties": {
                    "reasoning_trace": {"type": "array", "items": {"type": "object"}, "description": "Agent's thought process"},
                    "decision_points": {"type": "array", "items": {"type": "object"}, "description": "Key choices made"},
                    "context": {"type": "object", "description": "Available information"},
                    "optimal_path": {"type": "array", "items": {"type": "string"}, "description": "Best possible approach"},
                    "judge_model": {"type": "string", "default": "gpt-4o-mini"},
                },
                "required": ["reasoning_trace", "decision_points", "context"],
            },
        ),
        Tool(
            name="agent.benchmark_performance",
            description="Run comprehensive agent benchmarks comparing against baselines",
            inputSchema={
                "type": "object",
                "properties": {
                    "benchmark_suite": {"type": "string", "description": "Which tests to run"},
                    "agent_config": {"type": "object", "description": "Agent setup"},
                    "baseline_comparison": {"type": "object", "description": "Compare to other agents"},
                    "metrics_focus": {"type": "array", "items": {"type": "string"}, "default": ["accuracy", "efficiency", "reliability"], "description": "Priority metrics"},
                },
                "required": ["benchmark_suite", "agent_config"],
            },
        ),
        # Quality evaluation tools
        Tool(
            name="quality.evaluate_factuality",
            description="Check factual accuracy of responses against knowledge bases",
            inputSchema={
                "type": "object",
                "properties": {
                    "response": {"type": "string", "description": "Text to verify"},
                    "knowledge_base": {"type": "object", "description": "Reference sources"},
                    "fact_checking_model": {"type": "string", "default": "gpt-4", "description": "Model to use for fact checking"},
                    "confidence_threshold": {"type": "number", "default": 0.8, "description": "Minimum certainty"},
                    "judge_model": {"type": "string", "default": "gpt-4o-mini"},
                },
                "required": ["response"],
            },
        ),
        Tool(
            name="quality.measure_coherence",
            description="Analyze logical flow and consistency of text using rule-based and LLM metrics",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Response to analyze"},
                    "context": {"type": "string", "description": "Conversation history"},
                    "coherence_dimensions": {"type": "array", "items": {"type": "string"}, "default": ["logical_flow", "consistency", "topic_transitions"], "description": "What to check"},
                    "judge_model": {"type": "string", "default": "gpt-4o-mini"},
                },
                "required": ["text"],
            },
        ),
        Tool(
            name="quality.assess_toxicity",
            description="Detect harmful or biased content using pattern matching and LLM analysis",
            inputSchema={
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "Text to analyze"},
                    "toxicity_categories": {"type": "array", "items": {"type": "string"}, "default": ["profanity", "hate_speech", "threats", "discrimination"], "description": "Types to check"},
                    "sensitivity_level": {"type": "string", "default": "moderate", "enum": ["strict", "moderate", "loose"], "description": "Detection threshold"},
                    "judge_model": {"type": "string", "default": "gpt-4o-mini"},
                },
                "required": ["content"],
            },
        ),
        # RAG evaluation tools
        Tool(
            name="rag.evaluate_retrieval_relevance",
            description="Assess relevance of retrieved documents to the query using semantic similarity and LLM judges",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Original user query"},
                    "retrieved_documents": {"type": "array", "items": {"type": "object"}, "description": "List of retrieved docs with 'content' and optional 'score'"},
                    "relevance_threshold": {"type": "number", "default": 0.7, "description": "Minimum relevance score"},
                    "embedding_model": {"type": "string", "default": "text-embedding-ada-002", "description": "Model for semantic similarity"},
                    "judge_model": {"type": "string", "default": "gpt-4o-mini", "description": "LLM judge for relevance assessment"},
                    "use_llm_judge": {"type": "boolean", "default": True, "description": "Whether to use LLM judge in addition to embeddings"},
                },
                "required": ["query", "retrieved_documents"],
            },
        ),
        Tool(
            name="rag.measure_context_utilization",
            description="Check how well retrieved context is used in the generated answer",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Original query"},
                    "retrieved_context": {"type": "string", "description": "Full retrieved context"},
                    "generated_answer": {"type": "string", "description": "Model's generated response"},
                    "context_chunks": {"type": "array", "items": {"type": "string"}, "description": "Optional list of individual context chunks"},
                    "judge_model": {"type": "string", "default": "gpt-4o-mini", "description": "Judge model for evaluation"},
                },
                "required": ["query", "retrieved_context", "generated_answer"],
            },
        ),
        Tool(
            name="rag.assess_answer_groundedness",
            description="Verify answers are grounded in provided context by checking claim support",
            inputSchema={
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "Original question"},
                    "answer": {"type": "string", "description": "Generated answer to verify"},
                    "supporting_context": {"type": "string", "description": "Context that should support the answer"},
                    "judge_model": {"type": "string", "default": "gpt-4o-mini", "description": "Judge model for evaluation"},
                    "strictness": {"type": "string", "default": "moderate", "enum": ["strict", "moderate", "loose"], "description": "Grounding strictness"},
                },
                "required": ["question", "answer", "supporting_context"],
            },
        ),
        Tool(
            name="rag.detect_hallucination_vs_context",
            description="Identify when responses contradict provided context using statement verification",
            inputSchema={
                "type": "object",
                "properties": {
                    "generated_text": {"type": "string", "description": "Text to analyze for hallucinations"},
                    "source_context": {"type": "string", "description": "Source context to check against"},
                    "judge_model": {"type": "string", "default": "gpt-4o-mini", "description": "Judge model for hallucination detection"},
                    "detection_threshold": {"type": "number", "default": 0.8, "description": "Confidence threshold for hallucination detection"},
                },
                "required": ["generated_text", "source_context"],
            },
        ),
        Tool(
            name="rag.evaluate_retrieval_coverage",
            description="Measure if key information was retrieved by checking topic coverage",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Original search query"},
                    "expected_topics": {"type": "array", "items": {"type": "string"}, "description": "Topics that should be covered"},
                    "retrieved_documents": {"type": "array", "items": {"type": "object"}, "description": "Retrieved document set"},
                    "judge_model": {"type": "string", "default": "gpt-4o-mini", "description": "Judge model for coverage assessment"},
                },
                "required": ["query", "expected_topics", "retrieved_documents"],
            },
        ),
        Tool(
            name="rag.assess_citation_accuracy",
            description="Validate citation quality and accuracy against source documents",
            inputSchema={
                "type": "object",
                "properties": {
                    "generated_text": {"type": "string", "description": "Text with citations to verify"},
                    "source_documents": {"type": "array", "items": {"type": "object"}, "description": "Available source documents with 'content' and optional 'id'"},
                    "citation_format": {"type": "string", "default": "auto", "enum": ["auto", "numeric", "bracket", "parenthetical"], "description": "Expected citation format"},
                    "judge_model": {"type": "string", "default": "gpt-4o-mini", "description": "Judge model for citation assessment"},
                },
                "required": ["generated_text", "source_documents"],
            },
        ),
        Tool(
            name="rag.measure_chunk_relevance",
            description="Evaluate individual chunk relevance scores using semantic similarity and LLM assessment",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "context_chunks": {"type": "array", "items": {"type": "string"}, "description": "List of text chunks to evaluate"},
                    "embedding_model": {"type": "string", "default": "text-embedding-ada-002", "description": "Model for semantic similarity"},
                    "relevance_threshold": {"type": "number", "default": 0.6, "description": "Minimum relevance score"},
                    "judge_model": {"type": "string", "default": "gpt-4o-mini", "description": "Judge model for relevance assessment"},
                },
                "required": ["query", "context_chunks"],
            },
        ),
        Tool(
            name="rag.benchmark_retrieval_systems",
            description="Compare different retrieval approaches using standard IR metrics",
            inputSchema={
                "type": "object",
                "properties": {
                    "test_queries": {"type": "array", "items": {"type": "object"}, "description": "List of queries with expected results"},
                    "retrieval_systems": {"type": "array", "items": {"type": "object"}, "description": "List of retrieval system configurations"},
                    "evaluation_metrics": {"type": "array", "items": {"type": "string"}, "default": ["precision", "recall", "mrr", "ndcg"], "description": "Metrics to compute"},
                    "judge_model": {"type": "string", "default": "gpt-4o-mini", "description": "Judge model for evaluation"},
                },
                "required": ["test_queries", "retrieval_systems"],
            },
        ),
        # Workflow tools
        Tool(
            name="workflow.create_evaluation_suite",
            description="Define comprehensive evaluation pipeline with multiple tools and success criteria",
            inputSchema={
                "type": "object",
                "properties": {
                    "suite_name": {"type": "string", "description": "Identifier for the suite"},
                    "evaluation_steps": {"type": "array", "items": {"type": "object"}, "description": "List of evaluation tools to run"},
                    "success_thresholds": {"type": "object", "description": "Pass/fail criteria"},
                    "weights": {"type": "object", "description": "Importance of each metric"},
                    "description": {"type": "string", "description": "Optional description"},
                },
                "required": ["suite_name", "evaluation_steps", "success_thresholds"],
            },
        ),
        Tool(
            name="workflow.run_evaluation",
            description="Execute evaluation suite on test data with parallel or sequential execution",
            inputSchema={
                "type": "object",
                "properties": {
                    "suite_id": {"type": "string", "description": "Which suite to run"},
                    "test_data": {"type": "object", "description": "Inputs to evaluate"},
                    "parallel_execution": {"type": "boolean", "default": True, "description": "Run concurrently"},
                    "save_results": {"type": "boolean", "default": True, "description": "Persistence options"},
                    "max_concurrent": {"type": "integer", "default": 3, "description": "Maximum concurrent evaluations"},
                },
                "required": ["suite_id", "test_data"],
            },
        ),
        Tool(
            name="workflow.compare_evaluations",
            description="Compare results across multiple evaluation runs with statistical analysis",
            inputSchema={
                "type": "object",
                "properties": {
                    "evaluation_ids": {"type": "array", "items": {"type": "string"}, "description": "Results to compare"},
                    "comparison_type": {"type": "string", "default": "improvement", "enum": ["regression", "improvement", "a_b"], "description": "Type of comparison"},
                    "significance_test": {"type": "boolean", "default": True, "description": "Whether to run statistical validation"},
                },
                "required": ["evaluation_ids"],
            },
        ),
        # Calibration tools
        Tool(
            name="calibration.test_judge_agreement",
            description="Measure agreement between different judges and human evaluators",
            inputSchema={
                "type": "object",
                "properties": {
                    "test_cases": {"type": "array", "items": {"type": "object"}, "description": "Human-labeled examples"},
                    "judge_models": {"type": "array", "items": {"type": "string"}, "description": "LLMs to test"},
                    "correlation_metric": {"type": "string", "default": "pearson", "enum": ["pearson", "spearman", "cohen_kappa"], "description": "Correlation measure"},
                    "human_labels": {"type": "object", "description": "Ground truth human evaluations"},
                },
                "required": ["test_cases", "judge_models"],
            },
        ),
        Tool(
            name="calibration.optimize_rubrics",
            description="Tune evaluation rubrics for better alignment with human judgments",
            inputSchema={
                "type": "object",
                "properties": {
                    "current_rubric": {"type": "object", "description": "Existing criteria and rubric"},
                    "human_labels": {"type": "object", "description": "Ground truth labels"},
                    "optimization_target": {"type": "string", "default": "agreement", "enum": ["agreement", "consistency", "bias"], "description": "What to improve"},
                    "iterations": {"type": "integer", "default": 3, "description": "Number of optimization iterations"},
                },
                "required": ["current_rubric", "human_labels"],
            },
        ),
        # Utility tools
        Tool(name="server.get_available_judges", description="Get list of available judge models and their capabilities", inputSchema={"type": "object", "properties": {}}),
        Tool(name="server.get_evaluation_suites", description="List all created evaluation suites", inputSchema={"type": "object", "properties": {}}),
        Tool(
            name="server.get_evaluation_results",
            description="List evaluation results with optional filtering",
            inputSchema={
                "type": "object",
                "properties": {
                    "suite_id": {"type": "string", "description": "Filter by suite ID"},
                    "limit": {"type": "integer", "default": 20, "description": "Maximum results to return"},
                    "offset": {"type": "integer", "default": 0, "description": "Number of results to skip"},
                },
            },
        ),
        Tool(name="server.get_cache_stats", description="Get caching system statistics and performance metrics", inputSchema={"type": "object", "properties": {}}),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle tool calls.

    Args:
        name: Name of the tool to call.
        arguments: Arguments to pass to the tool.

    Returns:
        List[TextContent]: List containing the tool execution result as JSON text content.

    Raises:
        ValueError: If the tool name is not recognized.
    """
    try:
        logger.info(f"Calling tool: {name} with arguments: {arguments}")

        # Judge tools
        if name == "judge.evaluate_response":
            result = await JUDGE_TOOLS.evaluate_response(**arguments)
        elif name == "judge.pairwise_comparison":
            result = await JUDGE_TOOLS.pairwise_comparison(**arguments)
        elif name == "judge.rank_responses":
            result = await JUDGE_TOOLS.rank_responses(**arguments)
        elif name == "judge.evaluate_with_reference":
            result = await JUDGE_TOOLS.evaluate_with_reference(**arguments)

        # Prompt tools
        elif name == "prompt.evaluate_clarity":
            result = await PROMPT_TOOLS.evaluate_clarity(**arguments)
        elif name == "prompt.test_consistency":
            result = await PROMPT_TOOLS.test_consistency(**arguments)
        elif name == "prompt.measure_completeness":
            result = await PROMPT_TOOLS.measure_completeness(**arguments)
        elif name == "prompt.assess_relevance":
            result = await PROMPT_TOOLS.assess_relevance(**arguments)

        # Agent tools
        elif name == "agent.evaluate_tool_use":
            result = await AGENT_TOOLS.evaluate_tool_use(**arguments)
        elif name == "agent.measure_task_completion":
            result = await AGENT_TOOLS.measure_task_completion(**arguments)
        elif name == "agent.analyze_reasoning":
            result = await AGENT_TOOLS.analyze_reasoning(**arguments)
        elif name == "agent.benchmark_performance":
            result = await AGENT_TOOLS.benchmark_performance(**arguments)

        # Quality tools
        elif name == "quality.evaluate_factuality":
            result = await QUALITY_TOOLS.evaluate_factuality(**arguments)
        elif name == "quality.measure_coherence":
            result = await QUALITY_TOOLS.measure_coherence(**arguments)
        elif name == "quality.assess_toxicity":
            result = await QUALITY_TOOLS.assess_toxicity(**arguments)

        # RAG tools
        elif name == "rag.evaluate_retrieval_relevance":
            result = await RAG_TOOLS.evaluate_retrieval_relevance(**arguments)
        elif name == "rag.measure_context_utilization":
            result = await RAG_TOOLS.measure_context_utilization(**arguments)
        elif name == "rag.assess_answer_groundedness":
            result = await RAG_TOOLS.assess_answer_groundedness(**arguments)
        elif name == "rag.detect_hallucination_vs_context":
            result = await RAG_TOOLS.detect_hallucination_vs_context(**arguments)
        elif name == "rag.evaluate_retrieval_coverage":
            result = await RAG_TOOLS.evaluate_retrieval_coverage(**arguments)
        elif name == "rag.assess_citation_accuracy":
            result = await RAG_TOOLS.assess_citation_accuracy(**arguments)
        elif name == "rag.measure_chunk_relevance":
            result = await RAG_TOOLS.measure_chunk_relevance(**arguments)
        elif name == "rag.benchmark_retrieval_systems":
            result = await RAG_TOOLS.benchmark_retrieval_systems(**arguments)

        # Workflow tools
        elif name == "workflow.create_evaluation_suite":
            result = await WORKFLOW_TOOLS.create_evaluation_suite(**arguments)
        elif name == "workflow.run_evaluation":
            result = await WORKFLOW_TOOLS.run_evaluation(**arguments)
        elif name == "workflow.compare_evaluations":
            result = await WORKFLOW_TOOLS.compare_evaluations(**arguments)

        # Calibration tools
        elif name == "calibration.test_judge_agreement":
            result = await CALIBRATION_TOOLS.test_judge_agreement(**arguments)
        elif name == "calibration.optimize_rubrics":
            result = await CALIBRATION_TOOLS.optimize_rubrics(**arguments)

        # Server utility tools
        elif name == "server.get_available_judges":
            result = {"available_judges": JUDGE_TOOLS.get_available_judges()}
        elif name == "server.get_evaluation_suites":
            result = {"suites": WORKFLOW_TOOLS.list_evaluation_suites()}
        elif name == "server.get_evaluation_results":
            result = await RESULTS_STORE.list_evaluation_results(**arguments)
        elif name == "server.get_cache_stats":
            result = {"evaluation_cache": EVALUATION_CACHE.get_stats(), "judge_cache": JUDGE_CACHE.get_stats(), "benchmark_cache": BENCHMARK_CACHE.get_stats()}
        else:
            raise ValueError(f"Unknown tool: {name}")

        # Format result as JSON string
        result_text = json.dumps(result, indent=2, default=str)

        return [TextContent(type="text", text=result_text)]

    except Exception as e:
        logger.error(f"Error executing tool {name}: {str(e)}")
        error_result = {"error": str(e), "tool": name, "arguments": arguments}
        error_text = json.dumps(error_result, indent=2)
        return [TextContent(type="text", text=error_text)]


async def main():
    """Main server entry point."""
    global JUDGE_TOOLS, PROMPT_TOOLS, AGENT_TOOLS, QUALITY_TOOLS, RAG_TOOLS, WORKFLOW_TOOLS, CALIBRATION_TOOLS  # pylint: disable=global-statement
    global EVALUATION_CACHE, JUDGE_CACHE, BENCHMARK_CACHE, RESULTS_STORE  # pylint: disable=global-statement

    logger.info("🚀 Starting MCP Evaluation Server...")
    logger.info("📡 Protocol: Model Context Protocol (MCP) via stdio")
    logger.info("📋 Server: mcp-eval-server v0.1.0")

    # Initialize tools and storage after environment variables are loaded
    logger.info("🔧 Initializing tools and storage...")

    # Support custom configuration paths
    models_config_path = os.getenv("MCP_EVAL_MODELS_CONFIG")
    if models_config_path:
        logger.info(f"📄 Using custom models config: {models_config_path}")

    JUDGE_TOOLS = JudgeTools(config_path=models_config_path)
    PROMPT_TOOLS = PromptTools(JUDGE_TOOLS)
    AGENT_TOOLS = AgentTools(JUDGE_TOOLS)
    QUALITY_TOOLS = QualityTools(JUDGE_TOOLS)
    RAG_TOOLS = RAGTools(JUDGE_TOOLS)
    WORKFLOW_TOOLS = WorkflowTools(JUDGE_TOOLS, PROMPT_TOOLS, AGENT_TOOLS, QUALITY_TOOLS)
    CALIBRATION_TOOLS = CalibrationTools(JUDGE_TOOLS)

    # Initialize caching and storage
    EVALUATION_CACHE = EvaluationCache()
    JUDGE_CACHE = JudgeResponseCache()
    BENCHMARK_CACHE = BenchmarkCache()
    RESULTS_STORE = ResultsStore()
    
    # Mark storage as ready
    mark_storage_ready()

    # Log environment configuration
    logger.info("🔧 Environment Configuration:")
    env_vars = {
        "OPENAI_API_KEY": bool(os.getenv("OPENAI_API_KEY")),
        "AZURE_OPENAI_API_KEY": bool(os.getenv("AZURE_OPENAI_API_KEY")),
        "AZURE_OPENAI_ENDPOINT": os.getenv("AZURE_OPENAI_ENDPOINT", "not set"),
        "AZURE_DEPLOYMENT_NAME": os.getenv("AZURE_DEPLOYMENT_NAME", "not set"),
        "ANTHROPIC_API_KEY": bool(os.getenv("ANTHROPIC_API_KEY")),
        "AWS_ACCESS_KEY_ID": bool(os.getenv("AWS_ACCESS_KEY_ID")),
        "GOOGLE_API_KEY": bool(os.getenv("GOOGLE_API_KEY")),
        "WATSONX_API_KEY": bool(os.getenv("WATSONX_API_KEY")),
        "WATSONX_PROJECT_ID": os.getenv("WATSONX_PROJECT_ID", "not set"),
        "OLLAMA_BASE_URL": os.getenv("OLLAMA_BASE_URL", "not set"),
        "DEFAULT_JUDGE_MODEL": os.getenv("DEFAULT_JUDGE_MODEL", "not set"),
    }
    for var, value in env_vars.items():
        if var in ["AZURE_OPENAI_ENDPOINT", "AZURE_DEPLOYMENT_NAME", "WATSONX_PROJECT_ID", "OLLAMA_BASE_URL", "DEFAULT_JUDGE_MODEL"]:
            logger.info(f"   📊 {var}: {value}")
        else:
            status = "✅" if value else "❌"
            logger.info(f"   {status} {var}: {'configured' if value else 'not set'}")

    # Log judge initialization and test connectivity
    available_judges = JUDGE_TOOLS.get_available_judges()
    logger.info(f"⚖️  Loaded {len(available_judges)} judge models: {available_judges}")

    # Test judge connectivity and log detailed status with endpoints
    for judge_name in available_judges:
        info = JUDGE_TOOLS.get_judge_info(judge_name)
        provider = info.get("provider", "unknown")
        model_name = info.get("model_name", "N/A")

        # Get detailed configuration for each judge
        judge_instance = JUDGE_TOOLS.judges.get(judge_name)
        endpoint_info = ""

        if provider == "openai" and hasattr(judge_instance, "client"):
            base_url = str(judge_instance.client.base_url) if judge_instance.client.base_url else "https://api.openai.com/v1"
            endpoint_info = f" → {base_url}"
        elif provider == "azure":
            endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "not configured")
            deployment = os.getenv("AZURE_DEPLOYMENT_NAME", "not configured")
            endpoint_info = f" → {endpoint} (deployment: {deployment})"
        elif provider == "anthropic":
            endpoint_info = " → https://api.anthropic.com"
        elif provider == "ollama":
            base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
            # Test OLLAMA connectivity for status display
            try:
                # Third-Party
                import aiohttp  # pylint: disable=import-outside-toplevel

                async def test_ollama(test_url, aiohttp_module):  # pylint: disable=redefined-outer-name
                    try:
                        timeout = aiohttp_module.ClientTimeout(total=2)
                        async with aiohttp_module.ClientSession(timeout=timeout) as session:
                            async with session.get(f"{test_url}/api/tags") as response:
                                return response.status == 200
                    except Exception:
                        return False

                is_connected = await test_ollama(base_url, aiohttp)
                status = "🟢 connected" if is_connected else "🔴 not reachable"
                endpoint_info = f" → {base_url} ({status})"
            except Exception:
                endpoint_info = f" → {base_url} (🔴 not reachable)"
        elif provider == "bedrock":
            region = os.getenv("AWS_REGION", "us-east-1")
            endpoint_info = f" → AWS Bedrock ({region})"
        elif provider == "gemini":
            endpoint_info = " → Google AI Studio"
        elif provider == "watsonx":
            watsonx_url = os.getenv("WATSONX_URL", "https://us-south.ml.cloud.ibm.com")
            project_id = os.getenv("WATSONX_PROJECT_ID", "not configured")
            endpoint_info = f" → {watsonx_url} (project: {project_id})"

        logger.info(f"   📊 {judge_name} ({provider}): {model_name}{endpoint_info}")

    # Log tool categories
    logger.info("🛠️  Tool categories:")
    logger.info("   • 4 Judge tools (evaluate, compare, rank, reference)")
    logger.info("   • 4 Prompt tools (clarity, consistency, completeness, relevance)")
    logger.info("   • 4 Agent tools (tool usage, task completion, reasoning, benchmarks)")
    logger.info("   • 3 Quality tools (factuality, coherence, toxicity)")
    logger.info("   • 8 RAG tools (retrieval, context, grounding, hallucination, coverage, citations, chunks, benchmarks)")
    logger.info("   • 3 Workflow tools (suites, execution, comparison)")
    logger.info("   • 2 Calibration tools (agreement, optimization)")
    logger.info("   • 9 Server tools (management, statistics, health)")

    # Test primary judge with a simple evaluation if available
    primary_judge = os.getenv("DEFAULT_JUDGE_MODEL", "gpt-4o-mini")
    logger.info(f"🎯 Primary judge selection: {primary_judge}")

    if primary_judge in available_judges:
        try:
            logger.info(f"🧪 Testing primary judge: {primary_judge}")

            # Perform actual inference test
            criteria = [{"name": "helpfulness", "description": "Response helpfulness", "scale": "1-5", "weight": 1.0}]
            rubric = {"criteria": [], "scale_description": {"1": "Poor", "5": "Excellent"}}

            result = await JUDGE_TOOLS.evaluate_response(response="Hi, tell me about this model in one sentence.", criteria=criteria, rubric=rubric, judge_model=primary_judge)

            logger.info(f"✅ Primary judge {primary_judge} inference test successful - Score: {result['overall_score']:.2f}")

            # Log the model's actual response reasoning (truncated)
            if "reasoning" in result and result["reasoning"]:
                for criterion, reasoning in result["reasoning"].items():
                    truncated = reasoning[:150] + "..." if len(reasoning) > 150 else reasoning
                    logger.info(f"   💬 Model reasoning ({criterion}): {truncated}")
            
            # Mark judge tools as ready after successful primary judge test
            mark_judge_tools_ready()
        except Exception as e:
            logger.warning(f"⚠️  Primary judge {primary_judge} test failed: {e}")
            # Still mark as ready - server can function with fallback or rule-based judges
            mark_judge_tools_ready()
    elif available_judges:
        fallback = available_judges[0]
        logger.info(f"💡 Primary judge not available, using fallback: {fallback}")

        # Test fallback judge
        try:
            criteria = [{"name": "helpfulness", "description": "Response helpfulness", "scale": "1-5", "weight": 1.0}]
            rubric = {"criteria": [], "scale_description": {"1": "Poor", "5": "Excellent"}}

            result = await JUDGE_TOOLS.evaluate_response(response="Hi, tell me about this model in one sentence.", criteria=criteria, rubric=rubric, judge_model=fallback)

            logger.info(f"✅ Fallback judge {fallback} test successful - Score: {result['overall_score']:.2f}")

            # Log the model's actual response reasoning (truncated)
            if "reasoning" in result and result["reasoning"]:
                for criterion, reasoning in result["reasoning"].items():
                    truncated = reasoning[:150] + "..." if len(reasoning) > 150 else reasoning
                    logger.info(f"   💬 Model reasoning ({criterion}): {truncated}")
            
            # Mark judge tools as ready after successful fallback judge test
            mark_judge_tools_ready()
        except Exception as e:
            logger.warning(f"⚠️  Fallback judge {fallback} test failed: {e}")
            # Still mark as ready - server can function with rule-based judges
            mark_judge_tools_ready()
    else:
        logger.warning("⚠️  No judges available, but server can still function for non-LLM evaluations")
        # Mark judge tools as ready (even if no LLM judges available, rule-based judges can work)
        mark_judge_tools_ready()

    # Start health check server
    try:
        health_server = await start_health_server()
    except Exception as e:
        logger.warning(f"⚠️  Could not start health check server: {e}")
        health_server = None

    # Mark server as fully ready
    mark_ready()

    logger.info("🎯 Server ready for MCP client connections")
    logger.info("💡 Connect via: python -m mcp_eval_server.server")

    try:
        # Initialize server with stdio transport
        async with stdio_server() as streams:
            await server.run(streams[0], streams[1], InitializationOptions(server_name="mcp-eval-server", server_version="0.1.0", capabilities={}))
    finally:
        # Cleanup health server when main server stops
        if health_server:
            await stop_health_server()


if __name__ == "__main__":
    asyncio.run(main())
