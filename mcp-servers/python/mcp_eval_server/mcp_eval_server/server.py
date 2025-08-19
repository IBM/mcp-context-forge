# -*- coding: utf-8 -*-
"""MCP Evaluation Server - Main entry point."""

# Standard
import asyncio
import json
import logging
from typing import Any, Dict, List

# Third-Party
from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

# Local
from .storage.cache import BenchmarkCache, EvaluationCache, JudgeResponseCache
from .storage.results_store import ResultsStore
from .tools.agent_tools import AgentTools
from .tools.calibration_tools import CalibrationTools
from .tools.judge_tools import JudgeTools
from .tools.prompt_tools import PromptTools
from .tools.quality_tools import QualityTools
from .tools.workflow_tools import WorkflowTools

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize server
server = Server("mcp-eval-server")

# Initialize tools and storage
judge_tools = JudgeTools()
prompt_tools = PromptTools(judge_tools)
agent_tools = AgentTools(judge_tools)
quality_tools = QualityTools(judge_tools)
workflow_tools = WorkflowTools(judge_tools, prompt_tools, agent_tools, quality_tools)
calibration_tools = CalibrationTools(judge_tools)

# Initialize caching and storage
evaluation_cache = EvaluationCache()
judge_cache = JudgeResponseCache()
benchmark_cache = BenchmarkCache()
results_store = ResultsStore()


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
                    "judge_model": {"type": "string", "default": "gpt-4", "description": "Judge model to use"},
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
                    "judge_model": {"type": "string", "default": "gpt-4"},
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
                    "judge_model": {"type": "string", "default": "gpt-4"},
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
                    "judge_model": {"type": "string", "default": "gpt-4"},
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
                    "judge_model": {"type": "string", "default": "gpt-4"},
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
                    "judge_model": {"type": "string", "default": "gpt-4"},
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
                    "judge_model": {"type": "string", "default": "gpt-4"},
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
                    "judge_model": {"type": "string", "default": "gpt-4"},
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
                    "judge_model": {"type": "string", "default": "gpt-4"},
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
                    "judge_model": {"type": "string", "default": "gpt-4"},
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
                    "judge_model": {"type": "string", "default": "gpt-4"},
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
                    "judge_model": {"type": "string", "default": "gpt-4"},
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
                    "judge_model": {"type": "string", "default": "gpt-4"},
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
                    "judge_model": {"type": "string", "default": "gpt-4"},
                },
                "required": ["content"],
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
            result = await judge_tools.evaluate_response(**arguments)
        elif name == "judge.pairwise_comparison":
            result = await judge_tools.pairwise_comparison(**arguments)
        elif name == "judge.rank_responses":
            result = await judge_tools.rank_responses(**arguments)
        elif name == "judge.evaluate_with_reference":
            result = await judge_tools.evaluate_with_reference(**arguments)

        # Prompt tools
        elif name == "prompt.evaluate_clarity":
            result = await prompt_tools.evaluate_clarity(**arguments)
        elif name == "prompt.test_consistency":
            result = await prompt_tools.test_consistency(**arguments)
        elif name == "prompt.measure_completeness":
            result = await prompt_tools.measure_completeness(**arguments)
        elif name == "prompt.assess_relevance":
            result = await prompt_tools.assess_relevance(**arguments)

        # Agent tools
        elif name == "agent.evaluate_tool_use":
            result = await agent_tools.evaluate_tool_use(**arguments)
        elif name == "agent.measure_task_completion":
            result = await agent_tools.measure_task_completion(**arguments)
        elif name == "agent.analyze_reasoning":
            result = await agent_tools.analyze_reasoning(**arguments)
        elif name == "agent.benchmark_performance":
            result = await agent_tools.benchmark_performance(**arguments)

        # Quality tools
        elif name == "quality.evaluate_factuality":
            result = await quality_tools.evaluate_factuality(**arguments)
        elif name == "quality.measure_coherence":
            result = await quality_tools.measure_coherence(**arguments)
        elif name == "quality.assess_toxicity":
            result = await quality_tools.assess_toxicity(**arguments)

        # Workflow tools
        elif name == "workflow.create_evaluation_suite":
            result = await workflow_tools.create_evaluation_suite(**arguments)
        elif name == "workflow.run_evaluation":
            result = await workflow_tools.run_evaluation(**arguments)
        elif name == "workflow.compare_evaluations":
            result = await workflow_tools.compare_evaluations(**arguments)

        # Calibration tools
        elif name == "calibration.test_judge_agreement":
            result = await calibration_tools.test_judge_agreement(**arguments)
        elif name == "calibration.optimize_rubrics":
            result = await calibration_tools.optimize_rubrics(**arguments)

        # Server utility tools
        elif name == "server.get_available_judges":
            result = {"available_judges": judge_tools.get_available_judges()}
        elif name == "server.get_evaluation_suites":
            result = {"suites": workflow_tools.list_evaluation_suites()}
        elif name == "server.get_evaluation_results":
            result = await results_store.list_evaluation_results(**arguments)
        elif name == "server.get_cache_stats":
            result = {"evaluation_cache": evaluation_cache.get_stats(), "judge_cache": judge_cache.get_stats(), "benchmark_cache": benchmark_cache.get_stats()}
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
    logger.info("Starting MCP Evaluation Server...")
    logger.info(f"Available judges: {judge_tools.get_available_judges()}")

    # Initialize server with stdio transport
    async with stdio_server() as streams:
        await server.run(streams[0], streams[1], InitializationOptions(server_name="mcp-eval-server", server_version="0.1.0", capabilities={}))


if __name__ == "__main__":
    asyncio.run(main())
