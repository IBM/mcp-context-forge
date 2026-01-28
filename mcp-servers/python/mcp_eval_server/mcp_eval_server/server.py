# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/mcp_eval_server/mcp_eval_server/server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

MCP Evaluation Server - Main entry point.
"""

# Standard
import asyncio
import logging
import os
from typing import Any, Dict, List

import orjson
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
from .health import mark_judge_tools_ready, mark_ready, mark_storage_ready, start_health_server, stop_health_server
from .storage.cache import BenchmarkCache, EvaluationCache, JudgeResponseCache
from .storage.results_store import ResultsStore
from .tools.agent_tools import AgentTools
from .tools.bias_tools import BiasTools
from .tools.calibration_tools import CalibrationTools
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
BIAS_TOOLS = None  # pylint: disable=invalid-name
ROBUSTNESS_TOOLS = None  # pylint: disable=invalid-name
SAFETY_TOOLS = None  # pylint: disable=invalid-name
MULTILINGUAL_TOOLS = None  # pylint: disable=invalid-name
PERFORMANCE_TOOLS = None  # pylint: disable=invalid-name
PRIVACY_TOOLS = None  # pylint: disable=invalid-name
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
        # Bias & Fairness tools
        Tool(
            name="bias.detect_demographic_bias",
            description="Identify bias against protected groups using pattern matching and LLM assessment",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to analyze for demographic bias"},
                    "protected_groups": {"type": "array", "items": {"type": "string"}, "description": "Specific groups to check (default: all)"},
                    "bias_types": {"type": "array", "items": {"type": "string"}, "default": ["stereotyping", "exclusionary", "diminishing"], "description": "Types of bias to detect"},
                    "judge_model": {"type": "string", "default": "gpt-4o-mini", "description": "Judge model for bias assessment"},
                    "sensitivity_threshold": {"type": "number", "default": 0.7, "description": "Threshold for bias detection sensitivity"},
                },
                "required": ["text"],
            },
        ),
        Tool(
            name="bias.measure_representation_fairness",
            description="Assess balanced representation across groups in different contexts",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to analyze for representation balance"},
                    "target_groups": {"type": "array", "items": {"type": "string"}, "description": "Groups to check for fair representation"},
                    "representation_contexts": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": ["leadership", "expertise", "success", "achievement", "competence"],
                        "description": "Contexts to analyze",
                    },
                    "judge_model": {"type": "string", "default": "gpt-4o-mini", "description": "Judge model for representation assessment"},
                },
                "required": ["text", "target_groups"],
            },
        ),
        Tool(
            name="bias.evaluate_outcome_equity",
            description="Check for disparate impacts across protected groups in outcomes",
            inputSchema={
                "type": "object",
                "properties": {
                    "scenarios": {"type": "array", "items": {"type": "object"}, "description": "List of scenarios with attributes and outcomes"},
                    "protected_attributes": {"type": "array", "items": {"type": "string"}, "description": "Attributes that should not influence outcomes"},
                    "outcome_measures": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": ["success_rate", "quality_score", "approval_rate"],
                        "description": "Specific outcomes to measure equity for",
                    },
                    "judge_model": {"type": "string", "default": "gpt-4o-mini", "description": "Judge model for equity assessment"},
                },
                "required": ["scenarios", "protected_attributes"],
            },
        ),
        Tool(
            name="bias.assess_cultural_sensitivity",
            description="Evaluate cross-cultural appropriateness and cultural awareness",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to assess for cultural sensitivity"},
                    "cultural_contexts": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": ["western", "eastern", "african", "latin", "middle_eastern", "indigenous"],
                        "description": "Cultural contexts to consider",
                    },
                    "sensitivity_dimensions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": ["respect", "awareness", "inclusivity", "accuracy", "appropriateness"],
                        "description": "Aspects of cultural sensitivity to evaluate",
                    },
                    "judge_model": {"type": "string", "default": "gpt-4o-mini", "description": "Judge model for cultural assessment"},
                },
                "required": ["text"],
            },
        ),
        Tool(
            name="bias.detect_linguistic_bias",
            description="Identify language-based discrimination and dialect bias",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to analyze for linguistic bias"},
                    "linguistic_dimensions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": ["formality", "complexity", "dialect", "accent", "grammar"],
                        "description": "Aspects of language to check for bias",
                    },
                    "dialect_variants": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": ["aave", "southern", "urban", "rural", "formal", "informal"],
                        "description": "Specific dialects or variants to consider",
                    },
                    "judge_model": {"type": "string", "default": "gpt-4o-mini", "description": "Judge model for linguistic assessment"},
                },
                "required": ["text"],
            },
        ),
        Tool(
            name="bias.measure_intersectional_fairness",
            description="Evaluate compound bias effects across multiple identity dimensions",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to analyze for intersectional bias"},
                    "intersectional_groups": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}, "description": "Lists of identity combinations to analyze"},
                    "fairness_metrics": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": ["representation", "sentiment", "agency", "competence"],
                        "description": "Specific fairness measures to evaluate",
                    },
                    "judge_model": {"type": "string", "default": "gpt-4o-mini", "description": "Judge model for intersectional assessment"},
                },
                "required": ["text", "intersectional_groups"],
            },
        ),
        # Robustness tools
        Tool(
            name="robustness.test_adversarial_inputs",
            description="Evaluate system response to malicious prompts and attack vectors",
            inputSchema={
                "type": "object",
                "properties": {
                    "base_prompt": {"type": "string", "description": "Original prompt to test variations against"},
                    "adversarial_inputs": {"type": "array", "items": {"type": "string"}, "description": "Custom adversarial inputs to test"},
                    "attack_types": {"type": "array", "items": {"type": "string"}, "default": ["prompt_injection", "manipulation", "social_engineering"], "description": "Types of attacks to test"},
                    "target_model": {"type": "string", "default": "test_model", "description": "Model being tested for robustness"},
                    "judge_model": {"type": "string", "default": "gpt-4o-mini", "description": "Judge model for evaluation"},
                },
                "required": ["base_prompt"],
            },
        ),
        Tool(
            name="robustness.measure_input_sensitivity",
            description="Test response stability to input variations and perturbations",
            inputSchema={
                "type": "object",
                "properties": {
                    "base_input": {"type": "string", "description": "Original input to create variations from"},
                    "perturbation_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": ["typos", "synonyms", "reordering", "paraphrasing", "capitalization"],
                        "description": "Types of perturbations to apply",
                    },
                    "num_perturbations": {"type": "integer", "default": 10, "description": "Number of perturbations per type"},
                    "sensitivity_threshold": {"type": "number", "default": 0.1, "description": "Threshold for considering response changed"},
                    "judge_model": {"type": "string", "default": "gpt-4o-mini", "description": "Judge model for evaluation"},
                },
                "required": ["base_input"],
            },
        ),
        Tool(
            name="robustness.evaluate_prompt_injection_resistance",
            description="Check prompt injection defenses and security measures",
            inputSchema={
                "type": "object",
                "properties": {
                    "system_prompt": {"type": "string", "description": "System prompt to test for injection resistance"},
                    "injection_attempts": {"type": "array", "items": {"type": "string"}, "description": "Specific injection attempts to test"},
                    "injection_strategies": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": ["direct_override", "role_assumption", "context_switching", "encoding_bypass"],
                        "description": "Types of injection strategies to use",
                    },
                    "judge_model": {"type": "string", "default": "gpt-4o-mini", "description": "Judge model for evaluation"},
                },
                "required": ["system_prompt"],
            },
        ),
        Tool(
            name="robustness.assess_distribution_shift",
            description="Test performance degradation on out-of-domain data",
            inputSchema={
                "type": "object",
                "properties": {
                    "in_domain_samples": {"type": "array", "items": {"type": "string"}, "description": "Samples from the training/expected domain"},
                    "out_of_domain_samples": {"type": "array", "items": {"type": "string"}, "description": "Samples from different domains"},
                    "performance_metrics": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": ["quality", "relevance", "coherence", "factuality"],
                        "description": "Metrics to evaluate performance degradation",
                    },
                    "judge_model": {"type": "string", "default": "gpt-4o-mini", "description": "Judge model for evaluation"},
                },
                "required": ["in_domain_samples", "out_of_domain_samples"],
            },
        ),
        Tool(
            name="robustness.measure_consistency_under_perturbation",
            description="Check output stability under various input perturbations",
            inputSchema={
                "type": "object",
                "properties": {
                    "base_inputs": {"type": "array", "items": {"type": "string"}, "description": "Original inputs to test consistency for"},
                    "perturbation_strength": {"type": "number", "default": 0.1, "description": "Strength of perturbations to apply"},
                    "consistency_metrics": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": ["semantic_similarity", "factual_consistency", "response_length", "sentiment"],
                        "description": "Metrics to measure consistency",
                    },
                    "num_trials": {"type": "integer", "default": 5, "description": "Number of trials per input"},
                    "judge_model": {"type": "string", "default": "gpt-4o-mini", "description": "Judge model for evaluation"},
                },
                "required": ["base_inputs"],
            },
        ),
        # Safety & Alignment tools
        Tool(
            name="safety.detect_harmful_content",
            description="Identify dangerous or harmful outputs across multiple risk categories",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to analyze for harmful content"},
                    "harm_categories": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": ["violence", "illegal_activities", "self_harm", "explicit_content", "hate_speech", "misinformation"],
                        "description": "Specific categories of harm to check",
                    },
                    "detection_threshold": {"type": "number", "default": 0.7, "description": "Threshold for harm detection"},
                    "judge_model": {"type": "string", "default": "gpt-4o-mini", "description": "Judge model for harm assessment"},
                    "include_context": {"type": "boolean", "default": True, "description": "Whether to include context in analysis"},
                },
                "required": ["text"],
            },
        ),
        Tool(
            name="safety.assess_instruction_following",
            description="Measure adherence to constraints and safety instructions",
            inputSchema={
                "type": "object",
                "properties": {
                    "instructions": {"type": "string", "description": "Original instructions or constraints"},
                    "response": {"type": "string", "description": "Model response to evaluate"},
                    "instruction_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": ["format", "content", "style", "constraints", "safety"],
                        "description": "Types of instructions to check adherence for",
                    },
                    "adherence_threshold": {"type": "number", "default": 0.8, "description": "Threshold for considering instruction followed"},
                    "judge_model": {"type": "string", "default": "gpt-4o-mini", "description": "Judge model for adherence assessment"},
                },
                "required": ["instructions", "response"],
            },
        ),
        Tool(
            name="safety.evaluate_refusal_appropriateness",
            description="Check when system appropriately refuses potentially harmful requests",
            inputSchema={
                "type": "object",
                "properties": {
                    "requests": {"type": "array", "items": {"type": "object"}, "description": "List of requests with expected refusal behavior"},
                    "refusal_criteria": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": ["harmful", "illegal", "unethical", "privacy_violating", "beyond_capability"],
                        "description": "Criteria for when refusal is appropriate",
                    },
                    "appropriateness_threshold": {"type": "number", "default": 0.8, "description": "Threshold for appropriate refusal"},
                    "judge_model": {"type": "string", "default": "gpt-4o-mini", "description": "Judge model for refusal assessment"},
                },
                "required": ["requests"],
            },
        ),
        Tool(
            name="safety.measure_value_alignment",
            description="Assess alignment with human values and ethical principles",
            inputSchema={
                "type": "object",
                "properties": {
                    "scenarios": {"type": "array", "items": {"type": "object"}, "description": "List of scenarios to evaluate value alignment"},
                    "alignment_principles": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": ["helpfulness", "harmlessness", "honesty", "fairness", "privacy", "autonomy", "transparency", "accountability"],
                        "description": "Specific principles to evaluate alignment against",
                    },
                    "weight_distribution": {"type": "object", "description": "Weights for different alignment principles"},
                    "judge_model": {"type": "string", "default": "gpt-4o-mini", "description": "Judge model for value alignment assessment"},
                },
                "required": ["scenarios"],
            },
        ),
        # Multilingual tools
        Tool(
            name="multilingual.evaluate_translation_quality",
            description="Assess translation accuracy and quality across languages",
            inputSchema={
                "type": "object",
                "properties": {
                    "source_text": {"type": "string", "description": "Original text in source language"},
                    "translated_text": {"type": "string", "description": "Translated text"},
                    "source_language": {"type": "string", "description": "Source language code/name"},
                    "target_language": {"type": "string", "description": "Target language code/name"},
                    "quality_dimensions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": ["accuracy", "fluency", "completeness", "cultural_adaptation", "terminology"],
                        "description": "Aspects of translation quality to evaluate",
                    },
                    "judge_model": {"type": "string", "default": "gpt-4o-mini", "description": "Judge model for translation assessment"},
                },
                "required": ["source_text", "translated_text", "source_language", "target_language"],
            },
        ),
        Tool(
            name="multilingual.measure_cross_lingual_consistency",
            description="Check consistency across multiple language versions",
            inputSchema={
                "type": "object",
                "properties": {
                    "base_text": {"type": "string", "description": "Original text in base language"},
                    "base_language": {"type": "string", "description": "Base language code/name"},
                    "translated_versions": {"type": "object", "description": "Dictionary of language -> translated text"},
                    "consistency_metrics": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": ["semantic_consistency", "factual_consistency", "tone_consistency", "style_consistency"],
                        "description": "Metrics to evaluate consistency",
                    },
                    "judge_model": {"type": "string", "default": "gpt-4o-mini", "description": "Judge model for consistency assessment"},
                },
                "required": ["base_text", "base_language", "translated_versions"],
            },
        ),
        Tool(
            name="multilingual.assess_cultural_adaptation",
            description="Evaluate cultural appropriateness and localization quality",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to assess for cultural adaptation"},
                    "target_culture": {"type": "string", "description": "Target culture/region for adaptation"},
                    "cultural_dimensions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": ["formality", "directness", "context_level", "hierarchy", "collectivism", "time_orientation"],
                        "description": "Aspects of cultural adaptation to evaluate",
                    },
                    "reference_text": {"type": "string", "description": "Optional reference text for comparison"},
                    "judge_model": {"type": "string", "default": "gpt-4o-mini", "description": "Judge model for cultural assessment"},
                },
                "required": ["text", "target_culture"],
            },
        ),
        Tool(
            name="multilingual.detect_language_mixing",
            description="Identify inappropriate code-switching or language mixing",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to analyze for language mixing"},
                    "expected_language": {"type": "string", "description": "Expected primary language"},
                    "mixing_tolerance": {"type": "number", "default": 0.05, "description": "Acceptable level of language mixing (0-1)"},
                    "detection_method": {"type": "string", "default": "pattern_based", "enum": ["pattern_based", "llm_based"], "description": "Method for detecting language mixing"},
                    "judge_model": {"type": "string", "default": "gpt-4o-mini", "description": "Judge model for language assessment"},
                },
                "required": ["text", "expected_language"],
            },
        ),
        # Performance tools
        Tool(
            name="performance.measure_response_latency",
            description="Track generation speed and response times with statistical analysis",
            inputSchema={
                "type": "object",
                "properties": {
                    "test_inputs": {"type": "array", "items": {"type": "string"}, "description": "List of inputs to test latency for"},
                    "warmup_runs": {"type": "integer", "default": 2, "description": "Number of warmup runs before measurement"},
                    "measurement_runs": {"type": "integer", "default": 10, "description": "Number of measured runs per input"},
                    "timeout_seconds": {"type": "number", "default": 30.0, "description": "Maximum time to wait for response"},
                },
                "required": ["test_inputs"],
            },
        ),
        Tool(
            name="performance.assess_computational_efficiency",
            description="Measure resource usage and computational efficiency metrics",
            inputSchema={
                "type": "object",
                "properties": {
                    "test_workloads": {"type": "array", "items": {"type": "object"}, "description": "List of workloads to test efficiency for"},
                    "resource_monitoring_interval": {"type": "number", "default": 0.1, "description": "How often to sample resource usage (seconds)"},
                    "efficiency_metrics": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": ["cpu_usage", "memory_usage", "cpu_per_token", "memory_per_token"],
                        "description": "Specific efficiency metrics to track",
                    },
                },
                "required": ["test_workloads"],
            },
        ),
        Tool(
            name="performance.evaluate_throughput_scaling",
            description="Test concurrent request handling and scaling behavior",
            inputSchema={
                "type": "object",
                "properties": {
                    "test_request": {"type": "string", "description": "Request to use for throughput testing"},
                    "concurrency_levels": {"type": "array", "items": {"type": "integer"}, "default": [1, 2, 5, 10, 20], "description": "List of concurrent request counts to test"},
                    "requests_per_level": {"type": "integer", "default": 20, "description": "Number of requests to send at each concurrency level"},
                },
                "required": ["test_request"],
            },
        ),
        Tool(
            name="performance.monitor_memory_usage",
            description="Track memory consumption patterns during execution",
            inputSchema={
                "type": "object",
                "properties": {
                    "monitoring_duration": {"type": "number", "default": 60.0, "description": "How long to monitor (seconds)"},
                    "sampling_interval": {"type": "number", "default": 1.0, "description": "How often to sample memory (seconds)"},
                    "memory_threshold_mb": {"type": "number", "default": 1000.0, "description": "Memory usage threshold for alerts"},
                },
            },
        ),
        # Privacy tools
        Tool(
            name="privacy.detect_pii_exposure",
            description="Detect personally identifiable information in text with configurable sensitivity",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to analyze for PII exposure"},
                    "pii_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": ["email", "phone", "ssn", "credit_card", "ip_address", "address", "name"],
                        "description": "Specific types of PII to detect",
                    },
                    "sensitivity_level": {"type": "string", "default": "high", "enum": ["low", "medium", "high"], "description": "Detection sensitivity"},
                    "include_context": {"type": "boolean", "default": True, "description": "Whether to include surrounding context"},
                    "judge_model": {"type": "string", "default": "gpt-4o-mini", "description": "Judge model for PII assessment"},
                },
                "required": ["text"],
            },
        ),
        Tool(
            name="privacy.assess_data_minimization",
            description="Evaluate if data collection follows minimization principles",
            inputSchema={
                "type": "object",
                "properties": {
                    "collected_data": {"type": "object", "description": "Data being collected or processed"},
                    "stated_purpose": {"type": "string", "description": "Stated purpose for data collection"},
                    "data_categories": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": ["personal_identifiers", "financial", "medical", "behavioral", "sensitive_attributes"],
                        "description": "Categories of data to evaluate",
                    },
                    "judge_model": {"type": "string", "default": "gpt-4o-mini", "description": "Judge model for minimization assessment"},
                },
                "required": ["collected_data", "stated_purpose"],
            },
        ),
        Tool(
            name="privacy.evaluate_consent_compliance",
            description="Assess consent mechanisms and compliance with privacy regulations",
            inputSchema={
                "type": "object",
                "properties": {
                    "consent_text": {"type": "string", "description": "Consent notice or privacy policy text"},
                    "data_practices": {"type": "object", "description": "Actual data collection and processing practices"},
                    "compliance_standards": {"type": "array", "items": {"type": "string"}, "default": ["gdpr", "ccpa", "coppa", "hipaa"], "description": "Standards to check compliance against"},
                    "judge_model": {"type": "string", "default": "gpt-4o-mini", "description": "Judge model for compliance assessment"},
                },
                "required": ["consent_text", "data_practices"],
            },
        ),
        Tool(
            name="privacy.measure_anonymization_effectiveness",
            description="Evaluate effectiveness of data anonymization techniques",
            inputSchema={
                "type": "object",
                "properties": {
                    "original_data": {"type": "string", "description": "Original data before anonymization"},
                    "anonymized_data": {"type": "string", "description": "Data after anonymization"},
                    "anonymization_method": {"type": "string", "default": "unknown", "description": "Method used for anonymization"},
                    "reidentification_risk_threshold": {"type": "number", "default": 0.1, "description": "Acceptable re-identification risk level"},
                    "judge_model": {"type": "string", "default": "gpt-4o-mini", "description": "Judge model for anonymization assessment"},
                },
                "required": ["original_data", "anonymized_data"],
            },
        ),
        Tool(
            name="privacy.detect_data_leakage",
            description="Identify unintended data exposure or leakage in outputs",
            inputSchema={
                "type": "object",
                "properties": {
                    "input_data": {"type": "string", "description": "Input data provided to system"},
                    "output_data": {"type": "string", "description": "Output data generated by system"},
                    "expected_data_flow": {"type": "object", "description": "Expected data transformation rules"},
                    "leakage_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": ["direct_exposure", "inference_leakage", "aggregation_leakage", "temporal_leakage"],
                        "description": "Types of data leakage to check for",
                    },
                    "judge_model": {"type": "string", "default": "gpt-4o-mini", "description": "Judge model for leakage assessment"},
                },
                "required": ["input_data", "output_data"],
            },
        ),
        Tool(
            name="privacy.assess_consent_clarity",
            description="Evaluate clarity and comprehensibility of consent notices",
            inputSchema={
                "type": "object",
                "properties": {
                    "consent_text": {"type": "string", "description": "Consent notice or privacy policy text"},
                    "target_audience": {"type": "string", "default": "general_public", "description": "Target audience for the consent notice"},
                    "clarity_dimensions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": ["readability", "completeness", "specificity", "accessibility", "actionability"],
                        "description": "Aspects of clarity to evaluate",
                    },
                    "judge_model": {"type": "string", "default": "gpt-4o-mini", "description": "Judge model for clarity assessment"},
                },
                "required": ["consent_text"],
            },
        ),
        Tool(
            name="privacy.evaluate_data_retention_compliance",
            description="Assess data retention policy compliance and effectiveness",
            inputSchema={
                "type": "object",
                "properties": {
                    "retention_policies": {"type": "object", "description": "Stated data retention policies"},
                    "actual_practices": {"type": "object", "description": "Actual data retention practices"},
                    "regulatory_requirements": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": ["gdpr_erasure", "ccpa_deletion", "coppa_retention", "sector_specific"],
                        "description": "Regulatory standards to check against",
                    },
                    "judge_model": {"type": "string", "default": "gpt-4o-mini", "description": "Judge model for compliance assessment"},
                },
                "required": ["retention_policies", "actual_practices"],
            },
        ),
        Tool(
            name="privacy.assess_privacy_by_design",
            description="Evaluate privacy-by-design implementation in systems",
            inputSchema={
                "type": "object",
                "properties": {
                    "system_description": {"type": "string", "description": "Description of the system or process"},
                    "privacy_controls": {"type": "array", "items": {"type": "object"}, "description": "List of implemented privacy controls"},
                    "design_principles": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": ["proactive", "privacy_default", "privacy_embedded", "full_functionality", "end_to_end_security", "visibility_transparency", "user_privacy"],
                        "description": "Privacy-by-design principles to evaluate",
                    },
                    "judge_model": {"type": "string", "default": "gpt-4o-mini", "description": "Judge model for privacy assessment"},
                },
                "required": ["system_description", "privacy_controls"],
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

        # Bias & Fairness tools
        elif name == "bias.detect_demographic_bias":
            result = await BIAS_TOOLS.detect_demographic_bias(**arguments)
        elif name == "bias.measure_representation_fairness":
            result = await BIAS_TOOLS.measure_representation_fairness(**arguments)
        elif name == "bias.evaluate_outcome_equity":
            result = await BIAS_TOOLS.evaluate_outcome_equity(**arguments)
        elif name == "bias.assess_cultural_sensitivity":
            result = await BIAS_TOOLS.assess_cultural_sensitivity(**arguments)
        elif name == "bias.detect_linguistic_bias":
            result = await BIAS_TOOLS.detect_linguistic_bias(**arguments)
        elif name == "bias.measure_intersectional_fairness":
            result = await BIAS_TOOLS.measure_intersectional_fairness(**arguments)

        # Robustness tools
        elif name == "robustness.test_adversarial_inputs":
            result = await ROBUSTNESS_TOOLS.test_adversarial_inputs(**arguments)
        elif name == "robustness.measure_input_sensitivity":
            result = await ROBUSTNESS_TOOLS.measure_input_sensitivity(**arguments)
        elif name == "robustness.evaluate_prompt_injection_resistance":
            result = await ROBUSTNESS_TOOLS.evaluate_prompt_injection_resistance(**arguments)
        elif name == "robustness.assess_distribution_shift":
            result = await ROBUSTNESS_TOOLS.assess_distribution_shift(**arguments)
        elif name == "robustness.measure_consistency_under_perturbation":
            result = await ROBUSTNESS_TOOLS.measure_consistency_under_perturbation(**arguments)

        # Safety & Alignment tools
        elif name == "safety.detect_harmful_content":
            result = await SAFETY_TOOLS.detect_harmful_content(**arguments)
        elif name == "safety.assess_instruction_following":
            result = await SAFETY_TOOLS.assess_instruction_following(**arguments)
        elif name == "safety.evaluate_refusal_appropriateness":
            result = await SAFETY_TOOLS.evaluate_refusal_appropriateness(**arguments)
        elif name == "safety.measure_value_alignment":
            result = await SAFETY_TOOLS.measure_value_alignment(**arguments)

        # Multilingual tools
        elif name == "multilingual.evaluate_translation_quality":
            result = await MULTILINGUAL_TOOLS.evaluate_translation_quality(**arguments)
        elif name == "multilingual.measure_cross_lingual_consistency":
            result = await MULTILINGUAL_TOOLS.measure_cross_lingual_consistency(**arguments)
        elif name == "multilingual.assess_cultural_adaptation":
            result = await MULTILINGUAL_TOOLS.assess_cultural_adaptation(**arguments)
        elif name == "multilingual.detect_language_mixing":
            result = await MULTILINGUAL_TOOLS.detect_language_mixing(**arguments)

        # Performance tools
        elif name == "performance.measure_response_latency":
            result = await PERFORMANCE_TOOLS.measure_response_latency(**arguments)
        elif name == "performance.assess_computational_efficiency":
            result = await PERFORMANCE_TOOLS.assess_computational_efficiency(**arguments)
        elif name == "performance.evaluate_throughput_scaling":
            result = await PERFORMANCE_TOOLS.evaluate_throughput_scaling(**arguments)
        elif name == "performance.monitor_memory_usage":
            result = await PERFORMANCE_TOOLS.monitor_memory_usage(**arguments)

        # Privacy tools
        elif name == "privacy.detect_pii_exposure":
            result = await PRIVACY_TOOLS.detect_pii_exposure(**arguments)
        elif name == "privacy.assess_data_minimization":
            result = await PRIVACY_TOOLS.assess_data_minimization(**arguments)
        elif name == "privacy.evaluate_consent_compliance":
            result = await PRIVACY_TOOLS.evaluate_consent_compliance(**arguments)
        elif name == "privacy.measure_anonymization_effectiveness":
            result = await PRIVACY_TOOLS.measure_anonymization_effectiveness(**arguments)
        elif name == "privacy.detect_data_leakage":
            result = await PRIVACY_TOOLS.detect_data_leakage(**arguments)
        elif name == "privacy.assess_consent_clarity":
            result = await PRIVACY_TOOLS.assess_consent_clarity(**arguments)
        elif name == "privacy.evaluate_data_retention_compliance":
            result = await PRIVACY_TOOLS.evaluate_data_retention_compliance(**arguments)
        elif name == "privacy.assess_privacy_by_design":
            result = await PRIVACY_TOOLS.assess_privacy_by_design(**arguments)

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
        result_text = orjson.dumps(result, default=str, option=orjson.OPT_INDENT_2).decode()

        return [TextContent(type="text", text=result_text)]

    except Exception as e:
        logger.error(f"Error executing tool {name}: {str(e)}")
        error_result = {"error": str(e), "tool": name, "arguments": arguments}
        error_text = orjson.dumps(error_result, option=orjson.OPT_INDENT_2).decode()
        return [TextContent(type="text", text=error_text)]


async def main():
    """Main server entry point."""
    global JUDGE_TOOLS, PROMPT_TOOLS, AGENT_TOOLS, QUALITY_TOOLS, RAG_TOOLS, BIAS_TOOLS, ROBUSTNESS_TOOLS, SAFETY_TOOLS, MULTILINGUAL_TOOLS, PERFORMANCE_TOOLS, PRIVACY_TOOLS, WORKFLOW_TOOLS, CALIBRATION_TOOLS  # pylint: disable=global-statement
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
    BIAS_TOOLS = BiasTools(JUDGE_TOOLS)
    ROBUSTNESS_TOOLS = RobustnessTools(JUDGE_TOOLS)
    SAFETY_TOOLS = SafetyTools(JUDGE_TOOLS)
    MULTILINGUAL_TOOLS = MultilingualTools(JUDGE_TOOLS)
    PERFORMANCE_TOOLS = PerformanceTools(JUDGE_TOOLS)
    PRIVACY_TOOLS = PrivacyTools(JUDGE_TOOLS)
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
    logger.info("   • 6 Bias & Fairness tools (demographic, representation, equity, cultural, linguistic, intersectional)")
    logger.info("   • 5 Robustness tools (adversarial, sensitivity, injection, distribution, consistency)")
    logger.info("   • 4 Safety & Alignment tools (harmful content, instruction following, refusal, value alignment)")
    logger.info("   • 4 Multilingual tools (translation quality, cross-lingual consistency, cultural adaptation, language mixing)")
    logger.info("   • 4 Performance tools (latency, efficiency, throughput, memory)")
    logger.info("   • 8 Privacy tools (PII detection, data minimization, consent compliance, anonymization, leakage detection)")
    logger.info("   • 3 Workflow tools (suites, execution, comparison)")
    logger.info("   • 2 Calibration tools (agreement, optimization)")
    logger.info("   • 4 Server tools (management, statistics, health)")

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
