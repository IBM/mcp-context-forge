#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Model validation and connectivity testing script."""

# Standard
import asyncio
import logging
import os
import sys
from typing import Dict

# Add current directory to path for imports
sys.path.insert(0, ".")

# Third-Party
from mcp_eval_server.tools.judge_tools import JudgeTools  # noqa: E402

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)


def check_environment_variables() -> Dict[str, bool]:
    """Check for required environment variables.

    Returns:
        Dict[str, bool]: Dictionary mapping environment variable names to their presence status
    """
    env_checks = {}

    # OpenAI
    env_checks["OPENAI_API_KEY"] = bool(os.getenv("OPENAI_API_KEY"))
    env_checks["OPENAI_ORGANIZATION"] = bool(os.getenv("OPENAI_ORGANIZATION"))
    env_checks["OPENAI_BASE_URL"] = bool(os.getenv("OPENAI_BASE_URL"))

    # Azure OpenAI
    env_checks["AZURE_OPENAI_API_KEY"] = bool(os.getenv("AZURE_OPENAI_API_KEY"))
    env_checks["AZURE_OPENAI_ENDPOINT"] = bool(os.getenv("AZURE_OPENAI_ENDPOINT"))
    env_checks["AZURE_DEPLOYMENT_NAME"] = bool(os.getenv("AZURE_DEPLOYMENT_NAME"))

    # Anthropic
    env_checks["ANTHROPIC_API_KEY"] = bool(os.getenv("ANTHROPIC_API_KEY"))

    # AWS Bedrock
    env_checks["AWS_ACCESS_KEY_ID"] = bool(os.getenv("AWS_ACCESS_KEY_ID"))
    env_checks["AWS_SECRET_ACCESS_KEY"] = bool(os.getenv("AWS_SECRET_ACCESS_KEY"))
    env_checks["AWS_REGION"] = bool(os.getenv("AWS_REGION"))

    # Google Gemini
    env_checks["GOOGLE_API_KEY"] = bool(os.getenv("GOOGLE_API_KEY"))

    # IBM Watsonx.ai
    env_checks["WATSONX_API_KEY"] = bool(os.getenv("WATSONX_API_KEY"))
    env_checks["WATSONX_PROJECT_ID"] = bool(os.getenv("WATSONX_PROJECT_ID"))
    env_checks["WATSONX_URL"] = bool(os.getenv("WATSONX_URL"))

    # OLLAMA
    env_checks["OLLAMA_BASE_URL"] = bool(os.getenv("OLLAMA_BASE_URL"))

    return env_checks


async def test_judge_functionality(judge_tools: JudgeTools, judge_name: str) -> bool:
    """Test basic functionality of a judge.

    Args:
        judge_tools: Initialized JudgeTools instance
        judge_name: Name of the judge to test

    Returns:
        bool: True if judge test passes, False otherwise
    """
    try:
        # Simple test evaluation
        criteria = [{"name": "accuracy", "description": "Factual accuracy", "scale": "1-5", "weight": 1.0}]
        rubric = {"criteria": [], "scale_description": {"1": "Wrong", "5": "Correct"}}

        result = await judge_tools.evaluate_response(response="Paris is the capital of France.", criteria=criteria, rubric=rubric, judge_model=judge_name)

        # Check if we got a valid result
        return isinstance(result, dict) and "overall_score" in result and "scores" in result and result["overall_score"] > 0

    except Exception as e:
        logger.error(f"   ❌ Test failed for {judge_name}: {e}")
        return False


async def main():
    """Main validation function.

    Returns:
        bool: True if at least one judge is available and working, False otherwise
    """
    logger.info("🔍 MCP Eval Server - Model Validation & Connectivity Test")
    logger.info("=" * 60)

    # Check environment variables
    logger.info("📋 Environment Variables Check:")
    env_vars = check_environment_variables()

    providers = {
        "OpenAI": ["OPENAI_API_KEY"],
        "Azure OpenAI": ["AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT"],
        "Anthropic": ["ANTHROPIC_API_KEY"],
        "AWS Bedrock": ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"],
        "Google Gemini": ["GOOGLE_API_KEY"],
        "IBM Watsonx.ai": ["WATSONX_API_KEY", "WATSONX_PROJECT_ID"],
        "OLLAMA": ["OLLAMA_BASE_URL"],
    }

    for provider, required_vars in providers.items():
        has_required = all(env_vars.get(var, False) for var in required_vars)

        if provider == "OpenAI":
            pass
        elif provider == "Azure OpenAI":
            pass
        elif provider == "AWS Bedrock":
            pass

        status = "✅" if has_required else "⚠️ "
        logger.info(f"   {status} {provider}: {has_required}")

        if not has_required:
            missing = [var for var in required_vars if not env_vars.get(var, False)]
            logger.info(f"      Missing: {', '.join(missing)}")

    logger.info("")

    # Initialize judge tools
    logger.info("⚖️  Initializing Judge Tools:")
    judge_tools = JudgeTools()
    available_judges = judge_tools.get_available_judges()
    logger.info(f"   Loaded {len(available_judges)} judges")

    # Group judges by provider
    judge_by_provider = {}
    for judge_name in available_judges:
        info = judge_tools.get_judge_info(judge_name)
        provider = info.get("provider", "unknown")
        if provider not in judge_by_provider:
            judge_by_provider[provider] = []
        judge_by_provider[provider].append(judge_name)

    logger.info("")
    logger.info("📊 Judge Models by Provider:")
    for provider, judges in judge_by_provider.items():
        logger.info(f"   {provider.title()}: {len(judges)} judges")
        for judge_name in judges:
            info = judge_tools.get_judge_info(judge_name)
            model_name = info.get("model_name", "N/A")
            logger.info(f"      • {judge_name} → {model_name}")

    logger.info("")

    # Test basic functionality
    logger.info("🧪 Testing Basic Functionality:")
    logger.info("   Testing with simple evaluation: 'Paris is the capital of France.'")

    test_results = {}
    # Always test rule-based judge first (no API key needed)
    test_judges = []
    if "rule-based" in available_judges:
        test_judges.append("rule-based")
    # Add first 2 other judges
    other_judges = [j for j in available_judges if j != "rule-based"][:2]
    test_judges.extend(other_judges)

    for judge_name in test_judges:
        logger.info(f"   Testing {judge_name}...")
        success = await test_judge_functionality(judge_tools, judge_name)
        test_results[judge_name] = success
        status = "✅" if success else "❌"
        logger.info(f"      {status} {'Passed' if success else 'Failed'}")

    logger.info("")

    # Summary
    logger.info("📈 Validation Summary:")
    logger.info(f"   📊 Total judges available: {len(available_judges)}")
    logger.info(f"   🧪 Judges tested: {len(test_results)}")
    logger.info(f"   ✅ Tests passed: {sum(test_results.values())}")
    logger.info(f"   ❌ Tests failed: {len(test_results) - sum(test_results.values())}")

    # Recommendations
    logger.info("")
    logger.info("💡 Recommendations:")

    # Check if we have at least one working judge
    working_judges = [name for name, success in test_results.items() if success]
    if working_judges:
        logger.info(f"   ✅ Primary judge available: {working_judges[0]}")
    else:
        logger.info("   ⚠️  No working judges found - check API keys and connectivity")

    # Provider-specific recommendations
    if not env_vars.get("OPENAI_API_KEY"):
        logger.info("   💡 For OpenAI models: export OPENAI_API_KEY='sk-...'")

    if not env_vars.get("ANTHROPIC_API_KEY"):
        logger.info("   💡 For Anthropic models: export ANTHROPIC_API_KEY='sk-ant-...'")

    if not env_vars.get("AZURE_OPENAI_API_KEY"):
        logger.info("   💡 For Azure OpenAI: export AZURE_OPENAI_API_KEY='...' and AZURE_OPENAI_ENDPOINT='...'")

    # Rule-based judge always works
    if "rule-based" in available_judges:
        logger.info("   ✅ Rule-based judge available (no API key required)")

    logger.info("")
    logger.info("🎯 Model validation completed!")

    return len(available_judges) > 0 and any(test_results.values())


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
