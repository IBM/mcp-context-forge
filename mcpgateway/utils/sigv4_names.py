# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/sigv4_names.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Dependency-free SigV4 secret names shared by every redaction list.

Must not import any third-party or mcpgateway module. ``config.py`` imports this
module, so a heavier import here would load it on every ``mcpgateway.config`` import.

Examples:
    >>> "session_token" in SIGV4_REDACT_NAMES and "x-amz-signature" in SIGV4_REDACT_NAMES
    True
    >>> set(SIGV4_REDACT_NAMES) == set(SIGV4_SENSITIVE_KEYS) | set(SIGV4_WIRE_NAMES)
    True
"""

# Standard
from typing import Tuple

SIGV4_SENSITIVE_KEYS = frozenset({"secret_access_key", "session_token"})
SIGV4_WIRE_NAMES: Tuple[str, ...] = ("x-amz-security-token", "x-amz-signature", "x-amz-credential")
SIGV4_REDACT_NAMES: Tuple[str, ...] = (*sorted(SIGV4_SENSITIVE_KEYS), *SIGV4_WIRE_NAMES)
