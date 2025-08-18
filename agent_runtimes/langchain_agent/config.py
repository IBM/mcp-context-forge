import os
from functools import lru_cache
from typing import Optional, List

from .models import AgentConfig

def _parse_tools_list(tools_str: str) -> Optional[List[str]]:
    """Parse comma-separated tools string into list"""
    if not tools_str or not tools_str.strip():
        return None
    return [tool.strip() for tool in tools_str.split(",") if tool.strip()]

@lru_cache()
def get_settings() -> AgentConfig:
    """Get application settings from environment variables"""
    return AgentConfig(
        mcp_gateway_url=os.getenv(
            "MCP_GATEWAY_URL", 
            "http://localhost:4444"
        ),
        gateway_bearer_token=os.getenv("GATEWAY_BEARER_TOKEN"),
        tools_allowlist=_parse_tools_list(os.getenv("TOOLS", "")),
        default_model=os.getenv("DEFAULT_MODEL", "gpt-4o-mini"),
        max_iterations=int(os.getenv("MAX_ITERATIONS", "10")),
        temperature=float(os.getenv("TEMPERATURE", "0.7")),
        streaming_enabled=os.getenv("STREAMING_ENABLED", "true").lower() == "true",
        debug_mode=os.getenv("DEBUG_MODE", "false").lower() == "true"
    )

def validate_environment() -> dict:
    """Validate environment configuration and return status"""
    issues = []
    warnings = []
    
    # Check required environment variables
    if not os.getenv("GATEWAY_BEARER_TOKEN"):
        warnings.append("GATEWAY_BEARER_TOKEN not set - authentication may fail")
    
    # Check optional but recommended settings
    if not os.getenv("OPENAI_API_KEY"):
        issues.append("OPENAI_API_KEY not set - Langchain LLM will fail")
    
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
    return """# MCP Langchain Agent Configuration

# Gateway Configuration
MCP_GATEWAY_URL=http://localhost:4444
GATEWAY_BEARER_TOKEN=your-jwt-token-here

# OpenAI Configuration (required for Langchain)
OPENAI_API_KEY=your-openai-api-key

# Tool Configuration (optional - for production filtering)
TOOLS=list-users,books-search

# Agent Configuration
DEFAULT_MODEL=gpt-4o-mini
MAX_ITERATIONS=10
TEMPERATURE=0.7
STREAMING_ENABLED=true
DEBUG_MODE=false

# Generate GATEWAY_BEARER_TOKEN with:
# export GATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token -u admin --secret my-test-key)
"""