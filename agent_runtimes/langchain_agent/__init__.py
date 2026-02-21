# -*- coding: utf-8 -*-
"""MCP LangChain Agent Package.

A production-ready LangChain agent that integrates with ContextForge,
providing both OpenAI-compatible chat completions and A2A JSON-RPC endpoints.

Features:
- Dynamic tool discovery from ContextForge
- OpenAI-compatible API (/v1/chat/completions)
- A2A JSON-RPC communication endpoint
- Configurable tool allowlists for security
- Comprehensive health and readiness checks
- Streaming response support
- Full observability and metrics

Examples:
    Basic usage:

    >>> from agent_runtimes.langchain_agent import get_settings, LangchainMCPAgent
    >>> settings = get_settings()
    >>> agent = LangchainMCPAgent.from_config(settings)

    Starting the server:

    $ cd agent_runtimes/langchain_agent
    $ make dev
"""

__version__ = "1.0.0"
__author__ = "ContextForge Contributors"
__email__ = "noreply@example.com"

# Core exports
from .agent_langchain import LangchainMCPAgent
from .app import app
from .config import get_settings, validate_environment
from .mcp_client import MCPClient
from .models import AgentConfig, ChatCompletionRequest, ChatCompletionResponse

__all__ = [
    "app",
    "LangchainMCPAgent",
    "MCPClient",
    "get_settings",
    "validate_environment",
    "AgentConfig",
    "ChatCompletionRequest",
    "ChatCompletionResponse",
    "__version__",
]
