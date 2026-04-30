# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/constants.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Plugins constants file.
This module stores a collection of plugin constants used throughout the framework.
"""

# Standard

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

    Provide Mapping for violation codes to their corresponding HTTP status codes for proper error responses.
    """

    code: int
    name: str
    message: str


PLUGIN_VIOLATION_CODE_MAPPING: Mapping[str, PluginViolationCode] = MappingProxyType(
    # MappingProxyType will make sure the resulting object is immutable and hence this will act as a constant.
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

VALID_HTTP_STATUS_CODES: dict[int, str] = {  # RFC 9110
    # 4xx — Client Error
    400: "Bad Request",
    401: "Unauthorized",
    402: "Payment Required",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    406: "Not Acceptable",
    407: "Proxy Authentication Required",
    408: "Request Timeout",
    409: "Conflict",
    410: "Gone",
    411: "Length Required",
    412: "Precondition Failed",
    413: "Content Too Large",  # (was "Payload Too Large" before RFC 9110)
    414: "URI Too Long",
    415: "Unsupported Media Type",
    416: "Range Not Satisfiable",
    417: "Expectation Failed",
    418: "(Unused)",
    421: "Misdirected Request",
    422: "Unprocessable Content",  # (was "Unprocessable Entity")
    423: "Locked",
    424: "Failed Dependency",
    425: "Too Early",
    426: "Upgrade Required",
    428: "Precondition Required",
    429: "Too Many Requests",
    431: "Request Header Fields Too Large",
    451: "Unavailable For Legal Reasons",
    # 5xx — Server Error
    500: "Internal Server Error",
    501: "Not Implemented",
    502: "Bad Gateway",
    503: "Service Unavailable",
    504: "Gateway Timeout",
    505: "HTTP Version Not Supported",
    506: "Variant Also Negotiates",
    507: "Insufficient Storage",
    508: "Loop Detected",
    510: "Not Extended",
    511: "Network Authentication Required",
}
