# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/mcp_eval_server/mcp_eval_server/judges/__init__.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Judge implementations for LLM-as-a-judge evaluation.
"""

from .base_judge import BaseJudge, EvaluationCriteria, EvaluationResult, EvaluationRubric
from .openai_judge import OpenAIJudge
from .azure_judge import AzureOpenAIJudge
from .rule_judge import RuleBasedJudge

# Optional imports for additional providers
try:
    from .anthropic_judge import AnthropicJudge
except ImportError:
    AnthropicJudge = None

try:
    from .bedrock_judge import BedrockJudge
except ImportError:
    BedrockJudge = None

try:
    from .ollama_judge import OllamaJudge
except ImportError:
    OllamaJudge = None

try:
    from .gemini_judge import GeminiJudge
except ImportError:
    GeminiJudge = None

try:
    from .watsonx_judge import WatsonxJudge
except ImportError:
    WatsonxJudge = None

__all__ = [
    "BaseJudge",
    "EvaluationCriteria",
    "EvaluationResult",
    "EvaluationRubric",
    "OpenAIJudge",
    "AzureOpenAIJudge",
    "RuleBasedJudge",
    "AnthropicJudge",
    "BedrockJudge",
    "OllamaJudge",
    "GeminiJudge",
    "WatsonxJudge",
]
