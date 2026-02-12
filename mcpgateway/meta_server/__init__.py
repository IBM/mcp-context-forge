# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/meta_server/__init__.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Meta-Server package for MCP Gateway.

This package implements the Virtual Meta-Server feature, which exposes a fixed set
of meta-tools (search_tools, list_tools, describe_tool, execute_tool,
get_tool_categories, get_similar_tools) instead of the underlying real tools.

The meta-server provides:
- Unified tool discovery across federated servers
- Scope-based filtering configuration
- Configurable meta-tool behavior via MetaConfig
"""
