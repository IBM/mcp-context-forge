# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/constants.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Plugins constants file.
This module stores a collection of plugin constants used throughout the framework.
"""

# Model constants.
# Specialized plugin types.
EXTERNAL_PLUGIN_TYPE = "external"

# MCP related constants.
PYTHON_SUFFIX = ".py"
URL = "url"
SCRIPT = "script"

NAME = "name"
PYTHON = "python"
PLUGIN_NAME = "plugin_name"
PAYLOAD = "payload"
CONTEXT = "context"
RESULT = "result"
ERROR = "error"
IGNORE_CONFIG_EXTERNAL = "ignore_config_external"

# Global Context Metadata fields

TOOL_METADATA = "tool"
GATEWAY_METADATA = "gateway"

# MCP Plugin Server Runtime constants
MCP_SERVER_NAME = "MCP Plugin Server"
MCP_SERVER_INSTRUCTIONS = "External plugin server for MCP Gateway"
GET_PLUGIN_CONFIGS = "get_plugin_configs"
GET_PLUGIN_CONFIG = "get_plugin_config"
HOOK_TYPE = "hook_type"
INVOKE_HOOK = "invoke_hook"

# Rule Specificity Scoring Constants
# Used by rule resolver and UI to calculate how specific a routing rule is
# Higher scores indicate more specific rules (evaluated first)
SPECIFICITY_SCORE_NAME_MATCH = 1000  # Exact entity name match (most specific)
SPECIFICITY_SCORE_TAG_MATCH = 100  # Tag-based matching
SPECIFICITY_SCORE_HOOK_FILTER = 50  # Hook type filter
SPECIFICITY_SCORE_WHEN_EXPRESSION = 10  # Conditional when clause
SPECIFICITY_SCORE_ENTITY_TYPE = 0  # Entity type only (least specific, global-like)
