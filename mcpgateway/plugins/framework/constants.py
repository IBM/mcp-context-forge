# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/constants.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Plugins constants file.
This module stores a collection of plugin constants used throughout the framework.
"""

# Standard

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

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


@dataclass(frozen=True)
class PluginViolationCode:
    """
    Plugin violation codes as an immutable dataclass object.

    Provide Maping for violation codes to their corresponding HTTP status codes for proper error responses.
    """

    code: int
    name: str
    message: str


PLUGIN_VIOLATION_CODE_MAPPING: Mapping[str, PluginViolationCode] = MappingProxyType(
    {
        # Rate Limiting
        "RATE_LIMIT": PluginViolationCode(429, "RATE_LIMIT", "Used when rate limit is exceeded (rate_limiter plugin)"),
        # Resource & URI Validation
        "INVALID_URI": PluginViolationCode(400, "INVALID_URI", "Used when URI cannot be parsed or has invalid format (resource_filter, cedar, opa)"),
        "PROTOCOL_BLOCKED": PluginViolationCode(403, "PROTOCOL_BLOCKED", "Used when protocol/scheme is not allowed (resource_filter)"),
        "DOMAIN_BLOCKED": PluginViolationCode(403, "DOMAIN_BLOCKED", "Used when domain is in blocklist (resource_filter)"),
        "CONTENT_TOO_LARGE": PluginViolationCode(413, "CONTENT_TOO_LARGE", "Used when resource content exceeds size limit (resource_filter)"),
        # Content Moderation & Safety
        "CONTENT_MODERATION": PluginViolationCode(422, "CONTENT_MODERATION", "Used when harmful content is detected (content_moderation plugin)"),
        "MODERATION_ERROR": PluginViolationCode(503, "MODERATION_ERROR", "Used when moderation service fails (content_moderation plugin)"),
        "PII_DETECTED": PluginViolationCode(422, "PII_DETECTED", "Used when PII is detected in content (pii_filter plugin)"),
        "SENSITIVE_CONTENT": PluginViolationCode(422, "SENSITIVE_CONTENT", "Used when sensitive information is detected"),
        # Authentication & Authorization
        "INVALID_TOKEN": PluginViolationCode(401, "INVALID_TOKEN", "Used for invalid/expired tokens (simple_token_auth example)"),  # nosec B105 - Not a password; INVALID_TOKEN is a HTTP Status Code
        "API_KEY_REVOKED": PluginViolationCode(401, "API_KEY_REVOKED", "Used when API key has been revoked (custom_auth_example)"),
        "AUTH_REQUIRED": PluginViolationCode(401, "AUTH_REQUIRED", "Used when authentication is missing"),
        # Generic Violation Codes
        "PROHIBITED_CONTENT": PluginViolationCode(422, "PROHIBITED_CONTENT", "Used when content violates policy rules"),
        "BLOCKED_CONTENT": PluginViolationCode(403, "BLOCKED_CONTENT", "Used when content is explicitly blocked by policy"),
        "BLOCKED": PluginViolationCode(403, "BLOCKED", "Generic blocking violation"),
        "EXECUTION_ERROR": PluginViolationCode(500, "EXECUTION_ERROR", "Used when plugin execution fails"),
        "PROCESSING_ERROR": PluginViolationCode(500, "PROCESSING_ERROR", "Used when processing encounters an error"),
    }
)
