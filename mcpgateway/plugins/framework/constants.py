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
CMD = "cmd"
ENV = "env"
CWD = "cwd"
UDS = "uds"

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
