# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/header_filtering.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Header filtering utilities for sensitive credential removal.

This module provides utilities to strip sensitive headers before passing
them to plugins or external services.

The filter also removes the AWS SigV4 headers ``X-Amz-Security-Token``, ``X-Amz-Signature`` and ``X-Amz-Credential``.
This applies to plugin input and to the downstream A2A agent call when ``ENABLE_SENSITIVE_HEADER_PASSTHROUGH`` is ``false``,
even when the operator lists these headers in a passthrough allowlist.
"""

# Standard
import re
from typing import Dict

_SENSITIVE_REQUEST_HEADER_PATTERNS = (
    re.compile(r"^authorization$", re.IGNORECASE),
    re.compile(r"^proxy-authorization$", re.IGNORECASE),
    re.compile(r"^x-api-key$", re.IGNORECASE),
    re.compile(r"^api-key$", re.IGNORECASE),
    re.compile(r"^apikey$", re.IGNORECASE),
    re.compile(r"^x-(?:auth|api|access|refresh|client|bearer|session|security)[-_]?(?:token|secret|key)$", re.IGNORECASE),
    re.compile(r"^x-amz-(?:security-token|signature|credential)$", re.IGNORECASE),
    re.compile(r"^cookie$", re.IGNORECASE),
    re.compile(r"^set-cookie$", re.IGNORECASE),
    re.compile(r"^host$", re.IGNORECASE),
)


def filter_sensitive_headers(headers: Dict[str, str]) -> Dict[str, str]:
    """Strip sensitive/credential headers from a dict before passing to plugins.

    Args:
        headers: Dictionary of HTTP headers.

    Returns:
        Filtered dictionary with sensitive headers removed.
    """
    return {k: v for k, v in headers.items() if not any(p.match(k) for p in _SENSITIVE_REQUEST_HEADER_PATTERNS)}


_TOOL_CREDENTIAL_HEADER_PATTERNS = (
    re.compile(r"^authorization$", re.IGNORECASE),
    re.compile(r"^proxy-authorization$", re.IGNORECASE),
    re.compile(r"^x-api-key$", re.IGNORECASE),
    re.compile(r"^api-key$", re.IGNORECASE),
    re.compile(r"^apikey$", re.IGNORECASE),
    # Keep broad-enough auth matching while avoiding operational noise from
    # non-secret tracing/idempotency headers (e.g. X-Correlation-Token).
    re.compile(r"^x-(?:auth|api|access|refresh|client|bearer|session|security)[-_]?(?:token|secret|key)$", re.IGNORECASE),
    re.compile(r"^(?:auth|api|access|refresh|client|bearer|session|security)[-_]?(?:token|secret|key)$", re.IGNORECASE),
    re.compile(r"^cookie$", re.IGNORECASE),
    re.compile(r"^set-cookie$", re.IGNORECASE),
)

_PROVIDER_CREDENTIAL_HEADERS = frozenset(
    {
        "ocp-apim-subscription-key",
        "private-token",
        "x-amz-credential",
        "x-amz-security-token",
        "x-amz-signature",
        "x-auth",
        "x-custom-auth",
        "x-github-token",
        "x-goog-api-key",
        "x-vault-token",
        "x-webhook-secret",
    }
)

_TOOL_RESTRICTED_MAPPING_HEADER_PATTERNS = (
    re.compile(r"^host$", re.IGNORECASE),
    re.compile(r"^transfer-encoding$", re.IGNORECASE),
    re.compile(r"^content-length$", re.IGNORECASE),
    re.compile(r"^connection$", re.IGNORECASE),
    re.compile(r"^upgrade$", re.IGNORECASE),
    # Prevent caller-controllable encoding dispatch via header_mapping (see #4139).
    re.compile(r"^content-type$", re.IGNORECASE),
)


def is_tool_credential_header_name(name: str) -> bool:
    """Return whether the header name identifies credential material.

    Args:
        name: Header name to evaluate.

    Returns:
        Whether the header carries credentials.
    """
    normalized_name = str(name).strip().lower()
    return normalized_name in _PROVIDER_CREDENTIAL_HEADERS or any(pattern.match(normalized_name) for pattern in _TOOL_CREDENTIAL_HEADER_PATTERNS)


def is_sensitive_tool_header_name(name: str) -> bool:
    """Return whether a tool header name should be treated as sensitive.

    Args:
        name: Header name to evaluate.

    Returns:
        ``True`` when header value should be protected.
    """
    normalized_name = str(name).strip().lower()
    return is_tool_credential_header_name(name) or any(pattern.match(normalized_name) for pattern in _TOOL_RESTRICTED_MAPPING_HEADER_PATTERNS)
