# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/constants.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Plugins constants file.
This module stores a collection of plugin constants used throughout the framework.
"""

# Standard

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
MCP_SERVER_INSTRUCTIONS = "External plugin server for ContextForge"
GET_PLUGIN_CONFIGS = "get_plugin_configs"
GET_PLUGIN_CONFIG = "get_plugin_config"
HOOK_TYPE = "hook_type"
INVOKE_HOOK = "invoke_hook"

# Plugin Violation Code to HTTP Status Code Mapping
# Maps violation codes to their corresponding HTTP status codes for proper error responses
PLUGIN_VIOLATION_CODE_MAPPING = {
    # Rate Limiting
    "RATE_LIMIT": 429,  # Used when rate limit is exceeded (rate_limiter plugin)
    # Resource & URI Validation
    "INVALID_URI": 400,  # Used when URI cannot be parsed or has invalid format (resource_filter, cedar, opa)
    "PROTOCOL_BLOCKED": 403,  # Used when protocol/scheme is not allowed (resource_filter)
    "DOMAIN_BLOCKED": 403,  # Used when domain is in blocklist (resource_filter)
    "CONTENT_TOO_LARGE": 413,  # Used when resource content exceeds size limit (resource_filter)
    # Content Moderation & Safety
    "CONTENT_MODERATION": 422,  # Used when harmful content is detected (content_moderation plugin)
    "MODERATION_ERROR": 503,  # Used when moderation service fails (content_moderation plugin)
    "PII_DETECTED": 422,  # Used when PII is detected in content (pii_filter plugin)
    "SENSITIVE_CONTENT": 422,  # Used when sensitive information is detected
    # Authentication & Authorization
    "INVALID_TOKEN": 401,  # nosec B105 - Not a password; INVALID_TOKEN is a HTTP Status Code
    # Used for invalid/expired tokens (simple_token_auth example)
    "API_KEY_REVOKED": 401,  # Used when API key has been revoked (custom_auth_example)
    "AUTH_REQUIRED": 401,  # Used when authentication is missing
    # Generic Violation Codes
    "PROHIBITED_CONTENT": 422,  # Used when content violates policy rules
    "BLOCKED_CONTENT": 403,  # Used when content is explicitly blocked by policy
    "BLOCKED": 403,  # Generic blocking violation
    "EXECUTION_ERROR": 500,  # Used when plugin execution fails
    "PROCESSING_ERROR": 500,  # Used when processing encounters an error
}
