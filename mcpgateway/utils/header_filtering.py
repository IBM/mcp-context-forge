# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/header_filtering.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Header filtering utilities for sensitive credential removal.

This module provides utilities to strip sensitive headers before passing
them to plugins or external services.
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
