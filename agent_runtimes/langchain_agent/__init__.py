"""
MCP Langchain Agent Package

A configurable Langchain agent that supports MCP and integrates with the MCP Gateway
via streamable HTTP + Auth. Exposes an OpenAI compatible API.
"""
from .app import app
from .agent_langchain import LangchainMCPAgent
from .mcp_client import MCPClient
from .config import get_settings

__all__ = []