# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/__init__.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

ContextForge - A flexible feature-rich FastAPI-based gateway for the Model Context Protocol (MCP).
"""

__author__ = "Mihai Criveti"
__copyright__ = "Copyright 2025"
__license__ = "Apache 2.0"
__version__ = "1.0.7"
__description__ = "IBM Consulting Assistants - Extensions API Library"
__url__ = "https://ibm.github.io/mcp-context-forge/"
__download_url__ = "https://github.com/IBM/mcp-context-forge"
__packages__ = ["mcpgateway"]


def _install_mcp_v2_cpex_compat() -> None:
    """Install temporary MCP v1 aliases expected by current CPEX releases."""
    try:
        # Third-Party
        import mcp
        import mcp.client.streamable_http as mcp_streamable_http
        import mcp.shared.exceptions as mcp_exceptions
    except ImportError:
        return

    if not hasattr(mcp, "McpError") and hasattr(mcp, "MCPError"):
        mcp.McpError = mcp.MCPError  # type: ignore[attr-defined]
    if not hasattr(mcp_exceptions, "McpError") and hasattr(mcp_exceptions, "MCPError"):
        mcp_exceptions.McpError = mcp_exceptions.MCPError  # type: ignore[attr-defined]
    if not hasattr(mcp_streamable_http, "streamablehttp_client") and hasattr(mcp_streamable_http, "streamable_http_client"):
        mcp_streamable_http.streamablehttp_client = mcp_streamable_http.streamable_http_client  # type: ignore[attr-defined]


_install_mcp_v2_cpex_compat()
