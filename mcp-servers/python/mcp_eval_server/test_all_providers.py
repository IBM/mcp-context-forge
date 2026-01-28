#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/mcp_eval_server/test_all_providers.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Test all provider implementations with mock credentials.
"""

# Standard
import asyncio
import logging
import os
import sys

# Add current directory to path for imports
sys.path.insert(0, ".")

# Third-Party
try:
    # Third-Party
    from dotenv import load_dotenv  # noqa: E402
except ImportError:
    load_dotenv = None

# Third-Party
from mcp_eval_server.tools.judge_tools import JudgeTools  # noqa: E402  # pylint: disable=wrong-import-position,no-name-in-module

# Load .env if available
if load_dotenv:
    load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)


def setup_test_environment():
    """Set up test environment variables for all providers.

    Returns:
        dict: Dictionary of environment variables that were set
    """
    test_env = {
        # OpenAI
        "OPENAI_API_KEY": "sk-test-key",
        "OPENAI_ORGANIZATION": "org-test",
        # Azure
        "AZURE_OPENAI_API_KEY": "test-azure-key",
        "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com/",
        "AZURE_DEPLOYMENT_NAME": "test-deployment",
        # Anthropic
        "ANTHROPIC_API_KEY": "sk-ant-test-key",
        # AWS Bedrock
        "AWS_ACCESS_KEY_ID": "AKIA-test-key",
        "AWS_SECRET_ACCESS_KEY": "test-secret-key",
        "AWS_REGION": "us-east-1",
        # Google Gemini
        "GOOGLE_API_KEY": "test-google-key",
        # IBM Watsonx.ai
        "WATSONX_API_KEY": "test-watsonx-key",
        "WATSONX_PROJECT_ID": "test-project-id",
        "WATSONX_URL": "https://us-south.ml.cloud.ibm.com",
        # OLLAMA
        "OLLAMA_BASE_URL": "http://localhost:11434",
        # Default judge
        "DEFAULT_JUDGE_MODEL": "claude-4-1-bedrock",
    }

    for key, value in test_env.items():
        os.environ[key] = value

    return test_env


async def test_all_providers():
    """Test all provider configurations.

    Returns:
        bool: True if at least one judge is available, False otherwise
    """
    logger.info("🧪 Testing All LLM Providers for MCP Eval Server")
    logger.info("=" * 60)

    # Setup test environment
    setup_test_environment()
    logger.info("🔧 Test Environment Setup:")

    providers = {
        "OpenAI": ["OPENAI_API_KEY"],
        "Azure OpenAI": ["AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT"],
        "Anthropic": ["ANTHROPIC_API_KEY"],
        "AWS Bedrock": ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"],
        "Google Gemini": ["GOOGLE_API_KEY"],
        "IBM Watsonx.ai": ["WATSONX_API_KEY", "WATSONX_PROJECT_ID"],
        "OLLAMA": ["OLLAMA_BASE_URL"],
    }

    for provider, variables in providers.items():
        status = "✅" if all(os.getenv(var) for var in variables) else "❌"
        logger.info(f"   {status} {provider}: {'configured' if status == '✅' else 'missing vars'}")

    logger.info("")

    # Initialize judge tools
    logger.info("⚖️  Loading Judge Models:")
    judge_tools = JudgeTools()
    available_judges = judge_tools.get_available_judges()
    logger.info(f"   Total judges loaded: {len(available_judges)}")

    # Group judges by provider
    judge_by_provider = {}
    for judge_name in available_judges:
        info = judge_tools.get_judge_info(judge_name)
        provider = info.get("provider", "unknown")
        if provider not in judge_by_provider:
            judge_by_provider[provider] = []
        judge_by_provider[provider].append({"name": judge_name, "model": info.get("model_name", "N/A")})

    logger.info("")
    logger.info("📊 Loaded Judges by Provider:")
    for provider, judges in judge_by_provider.items():
        logger.info(f"   {provider.title()}: {len(judges)} judges")
        for judge in judges:
            logger.info(f"      • {judge['name']} → {judge['model']}")

    logger.info("")

    # Test each provider's flagship model
    flagship_models = {
        "claude-4-1-bedrock": "AWS Bedrock Claude 4.1",
        "gemini-1-5-pro": "Google Gemini Pro 1.5",
        "llama-3-1-70b-watsonx": "IBM Watsonx.ai Llama 3.1 70B",
        "gpt-5-chat": "Azure OpenAI GPT-4o",
        "claude-3-sonnet": "Anthropic Claude 3 Sonnet",
        "gpt-4o-mini": "OpenAI GPT-4o Mini",
        "rule-based": "Rule-Based Judge",
    }

    logger.info("🧪 Testing Flagship Models:")
    test_results = {}

    for model_name, description in flagship_models.items():
        if model_name in available_judges:
            logger.info(f"   Testing {model_name} ({description})...")
            try:
                criteria = [{"name": "quality", "description": "Overall quality", "scale": "1-5", "weight": 1.0}]
                rubric = {"criteria": [], "scale_description": {"1": "Poor", "5": "Excellent"}}

                result = await judge_tools.evaluate_response(response="Hi, tell me about this model in one sentence.", criteria=criteria, rubric=rubric, judge_model=model_name)

                test_results[model_name] = True
                logger.info(f"      ✅ Success - Score: {result['overall_score']:.2f}")

                # Show model reasoning (truncated)
                if "reasoning" in result and result["reasoning"]:
                    for _, reasoning in result["reasoning"].items():
                        truncated = reasoning[:100] + "..." if len(reasoning) > 100 else reasoning
                        logger.info(f"      💬 Reasoning: {truncated}")

            except Exception as e:
                test_results[model_name] = False
                logger.info(f"      ❌ Failed: {str(e)[:100]}...")
        else:
            logger.info(f"   {model_name} ({description}): Not available (missing dependencies/credentials)")

    logger.info("")

    # Summary
    logger.info("📈 Provider Test Summary:")
    logger.info(f"   📊 Total providers supported: {len(providers)}")
    logger.info(f"   📊 Total judges configured: {len(available_judges)}")
    logger.info(f"   🧪 Models tested: {len(test_results)}")
    logger.info(f"   ✅ Tests passed: {sum(test_results.values())}")
    logger.info(f"   ❌ Tests failed: {len(test_results) - sum(test_results.values())}")

    logger.info("")
    logger.info("💡 Provider Status:")

    status_by_provider = {}
    for judge_name in available_judges:
        info = judge_tools.get_judge_info(judge_name)
        provider = info.get("provider", "unknown")
        if provider not in status_by_provider:
            status_by_provider[provider] = 0
        status_by_provider[provider] += 1

    for provider, count in status_by_provider.items():
        logger.info(f"   ✅ {provider.title()}: {count} judges available")

    # Installation recommendations
    logger.info("")
    logger.info("📦 Installation Commands for Missing Providers:")

    if not available_judges or "gemini-1-5-pro" not in available_judges:
        logger.info("   pip install google-generativeai  # For Google Gemini")

    if not available_judges or "llama-3-1-70b-watsonx" not in available_judges:
        logger.info("   pip install ibm-watsonx-ai       # For IBM Watsonx.ai")

    logger.info('   pip install -e ".[all]"           # For all providers')

    logger.info("")
    logger.info("🎯 Multi-provider testing completed!")

    return len(available_judges) > 0


if __name__ == "__main__":
    success = asyncio.run(test_all_providers())
    sys.exit(0 if success else 1)
