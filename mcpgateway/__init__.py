# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/__init__.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

MCP Gateway - A flexible feature-rich FastAPI-based gateway for the Model Context Protocol (MCP).
"""

__author__ = "Mihai Criveti"
__copyright__ = "Copyright 2025"
__license__ = "Apache 2.0"
__version__ = "0.7.0"
__description__ = "IBM Consulting Assistants - Extensions API Library"
__url__ = "https://ibm.github.io/mcp-context-forge/"
__download_url__ = "https://github.com/IBM/mcp-context-forge"
__packages__ = ["mcpgateway"]

# Export main components for easier imports
__all__ = [
    "__version__",
    "__author__",
    "__license__",
    "reverse_proxy",
    "wrapper",
    "translate",
]
