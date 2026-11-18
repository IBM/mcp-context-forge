# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/a2a_errors.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Base exception for A2A agent errors, kept apart so that modules below ``a2a_service`` can raise it.
"""


class A2AAgentError(Exception):
    """Base class for A2A agent-related errors.

    Examples:
        >>> try:
        ...     raise A2AAgentError("Agent operation failed")
        ... except A2AAgentError as e:
        ...     str(e)
        'Agent operation failed'
        >>> try:
        ...     raise A2AAgentError("Connection error")
        ... except Exception as e:
        ...     isinstance(e, A2AAgentError)
        True
    """
