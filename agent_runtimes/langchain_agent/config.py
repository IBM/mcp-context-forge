# -*- coding: utf-8 -*-
import os
from functools import lru_cache
from typing import Optional, List

# Load .env file if it exists
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # python-dotenv not available, skip
    pass

try:
    from .models import AgentConfig
except ImportError:
    from models import AgentConfig

def _parse_tools_list(tools_str: str) -> Optional[List[str]]:
    """Parse comma-separated tools string into list"""
    if not tools_str or not tools_str.strip():
        return None
    return [tool.strip() for tool in tools_str.split(",") if tool.strip()]

@lru_cache()
def get_settings() -> AgentConfig:
    """Get application settings from environment variables"""
    return AgentConfig(
        # MCP Gateway Configuration
        mcp_gateway_url=os.getenv("MCP_GATEWAY_URL", "http://localhost:4444"),
        gateway_bearer_token=os.getenv("MCPGATEWAY_BEARER_TOKEN"),
        tools_allowlist=_parse_tools_list(os.getenv("TOOLS", "")),

        # LLM Provider Configuration
        llm_provider=os.getenv("LLM_PROVIDER", "openai").lower(),
        default_model=os.getenv("DEFAULT_MODEL", "gpt-4o-mini"),

        # OpenAI Configuration
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        openai_base_url=os.getenv("OPENAI_BASE_URL"),
        openai_organization=os.getenv("OPENAI_ORGANIZATION"),

        # Azure OpenAI Configuration
        azure_openai_api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        azure_openai_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        azure_openai_api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"),
        azure_deployment_name=os.getenv("AZURE_DEPLOYMENT_NAME"),

        # AWS Bedrock Configuration
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        aws_region=os.getenv("AWS_REGION", "us-east-1"),
        bedrock_model_id=os.getenv("BEDROCK_MODEL_ID"),

        # OLLAMA Configuration
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        ollama_model=os.getenv("OLLAMA_MODEL"),

        # Anthropic Configuration
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),

        # Agent Configuration
        max_iterations=int(os.getenv("MAX_ITERATIONS", "10")),
        temperature=float(os.getenv("TEMPERATURE", "0.7")),
        streaming_enabled=os.getenv("STREAMING_ENABLED", "true").lower() == "true",
        debug_mode=os.getenv("DEBUG_MODE", "false").lower() == "true",

        # Performance Configuration
        request_timeout=int(os.getenv("REQUEST_TIMEOUT", "30")),
        max_tokens=int(os.getenv("MAX_TOKENS")) if os.getenv("MAX_TOKENS") else None,
        top_p=float(os.getenv("TOP_P")) if os.getenv("TOP_P") else None,
    )

def validate_environment() -> dict:
    """Validate environment configuration and return status"""
    issues = []
    warnings = []

    # Check required environment variables
    if not os.getenv("MCPGATEWAY_BEARER_TOKEN"):
        warnings.append("MCPGATEWAY_BEARER_TOKEN not set - authentication may fail")

    # Validate LLM provider configuration
    llm_provider = os.getenv("LLM_PROVIDER", "openai").lower()

    if llm_provider == "openai":
        if not os.getenv("OPENAI_API_KEY"):
            issues.append("OPENAI_API_KEY not set - OpenAI LLM will fail")
    elif llm_provider == "azure":
        if not os.getenv("AZURE_OPENAI_API_KEY"):
            issues.append("AZURE_OPENAI_API_KEY not set - Azure OpenAI will fail")
        if not os.getenv("AZURE_OPENAI_ENDPOINT"):
            issues.append("AZURE_OPENAI_ENDPOINT not set - Azure OpenAI will fail")
        if not os.getenv("AZURE_DEPLOYMENT_NAME"):
            issues.append("AZURE_DEPLOYMENT_NAME not set - Azure OpenAI will fail")
    elif llm_provider == "bedrock":
        if not os.getenv("AWS_ACCESS_KEY_ID"):
            issues.append("AWS_ACCESS_KEY_ID not set - AWS Bedrock will fail")
        if not os.getenv("AWS_SECRET_ACCESS_KEY"):
            issues.append("AWS_SECRET_ACCESS_KEY not set - AWS Bedrock will fail")
        if not os.getenv("BEDROCK_MODEL_ID"):
            issues.append("BEDROCK_MODEL_ID not set - AWS Bedrock will fail")
    elif llm_provider == "ollama":
        if not os.getenv("OLLAMA_MODEL"):
            issues.append("OLLAMA_MODEL not set - OLLAMA will fail")
        ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        if "localhost" in ollama_url:
            warnings.append("OLLAMA appears to be running locally - ensure OLLAMA is accessible")
    elif llm_provider == "anthropic":
        if not os.getenv("ANTHROPIC_API_KEY"):
            issues.append("ANTHROPIC_API_KEY not set - Anthropic will fail")
    else:
        issues.append(f"Unknown LLM provider: {llm_provider}. Supported: openai, azure, bedrock, ollama, anthropic")

    # Validate numeric settings
    try:
        max_iter = int(os.getenv("MAX_ITERATIONS", "10"))
        if max_iter < 1:
            warnings.append("MAX_ITERATIONS should be >= 1")
    except ValueError:
        warnings.append("MAX_ITERATIONS is not a valid integer")

    try:
        temp = float(os.getenv("TEMPERATURE", "0.7"))
        if not 0.0 <= temp <= 2.0:
            warnings.append("TEMPERATURE should be between 0.0 and 2.0")
    except ValueError:
        warnings.append("TEMPERATURE is not a valid float")

    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "warnings": warnings
    }

def get_example_env() -> str:
    """Get example environment configuration"""
    return """# MCP LangChain Agent Configuration
# =================================

# Gateway Configuration
MCP_GATEWAY_URL=http://localhost:4444
MCPGATEWAY_BEARER_TOKEN=your-jwt-token-here

# LLM Provider (choose one: openai, azure, bedrock, ollama, anthropic)
LLM_PROVIDER=openai

# === OpenAI Configuration (LLM_PROVIDER=openai) ===
OPENAI_API_KEY=your-openai-api-key
DEFAULT_MODEL=gpt-4o-mini

# === Azure OpenAI Configuration (LLM_PROVIDER=azure) ===
# AZURE_OPENAI_API_KEY=your-azure-api-key
# AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
# AZURE_DEPLOYMENT_NAME=your-deployment-name
# DEFAULT_MODEL=gpt-4  # Use deployment name, not model name

# === AWS Bedrock Configuration (LLM_PROVIDER=bedrock) ===
# AWS_ACCESS_KEY_ID=your-access-key-id
# AWS_SECRET_ACCESS_KEY=your-secret-access-key
# AWS_REGION=us-east-1
# BEDROCK_MODEL_ID=anthropic.claude-3-sonnet-20240229-v1:0
# DEFAULT_MODEL=claude-3-sonnet

# === OLLAMA Configuration (LLM_PROVIDER=ollama) ===
# OLLAMA_BASE_URL=http://localhost:11434
# OLLAMA_MODEL=llama2:7b
# DEFAULT_MODEL=llama2:7b

# === Anthropic Configuration (LLM_PROVIDER=anthropic) ===
# ANTHROPIC_API_KEY=your-anthropic-api-key
# DEFAULT_MODEL=claude-3-sonnet-20240229

# Tool Configuration (optional - for production filtering)
TOOLS=list-users,books-search

# Agent Configuration
MAX_ITERATIONS=10
TEMPERATURE=0.7
STREAMING_ENABLED=true
DEBUG_MODE=false

# Performance Configuration
REQUEST_TIMEOUT=30
# MAX_TOKENS=1000
# TOP_P=0.9

# Generate MCPGATEWAY_BEARER_TOKEN with:
# export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token -u admin --secret my-test-key)
"""
