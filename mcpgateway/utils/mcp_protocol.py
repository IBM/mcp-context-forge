# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/mcp_protocol.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Bogdan-Marius Catanus

Helpers for MCP protocol-version semantics.

Phase 1 for issue #4686 introduces a shared, explicit gate for sessionless MCP
behavior so legacy sessionful behavior can remain the default while newer
protocol versions opt into the new semantics.

Phase 5 adds deprecation warnings for sessionful protocol usage.
"""

# Standard
import logging
from typing import Optional

# Third-Party
from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS as MCP_SUPPORTED_PROTOCOL_VERSIONS
from mcp.types import LATEST_PROTOCOL_VERSION

logger = logging.getLogger(__name__)

SUPPORTED_PROTOCOL_VERSIONS = list(MCP_SUPPORTED_PROTOCOL_VERSIONS)
DEFAULT_PROTOCOL_VERSION = LATEST_PROTOCOL_VERSION

# Sessionless semantics start with the post-session SEP-aligned protocol.
SESSIONLESS_PROTOCOL_MIN_VERSION = "2025-11-25"

# Track if we've already logged the deprecation warning to avoid spam
_deprecation_warning_logged = False


def normalize_mcp_protocol_version(protocol_version: Optional[str]) -> str:
    """Return a validated MCP protocol version or the default.

    Args:
        protocol_version: Raw version value from request headers or payload.

    Returns:
        Canonical protocol version string. Missing/blank values fall back to the
        implementation default for backwards compatibility.
    """
    candidate = str(protocol_version or "").strip()
    return candidate or DEFAULT_PROTOCOL_VERSION


def is_supported_mcp_protocol_version(protocol_version: Optional[str]) -> bool:
    """Return whether the version is supported by this gateway build."""
    normalized = normalize_mcp_protocol_version(protocol_version)
    return normalized in SUPPORTED_PROTOCOL_VERSIONS


def uses_sessionless_mcp_semantics(protocol_version: Optional[str]) -> bool:
    """Return whether the protocol version should use sessionless MCP semantics.

    Phase 1 keeps this as a pure version gate so call sites can branch between
    legacy sessionful transport behavior and the new sessionless model without
    changing defaults for older clients.

    Phase 5 adds deprecation warnings for sessionful protocol usage.

    Args:
        protocol_version: MCP protocol version from headers or initialize params.

    Returns:
        ``True`` for protocol versions at or after the sessionless cutoff.
    """
    global _deprecation_warning_logged

    normalized = normalize_mcp_protocol_version(protocol_version)
    is_sessionless = normalized >= SESSIONLESS_PROTOCOL_MIN_VERSION

    # Log deprecation warning for sessionful protocols (once per process)
    if not is_sessionless and not _deprecation_warning_logged:
        logger.warning(
            "DEPRECATION: MCP protocol version %s uses legacy sessionful semantics. "
            "Sessionful protocols (< %s) are deprecated and will be removed in a future release. "
            "Please upgrade to protocol version %s or later for sessionless semantics. "
            "See https://github.com/modelcontextprotocol/specification/pull/2567 for details.",
            normalized,
            SESSIONLESS_PROTOCOL_MIN_VERSION,
            SESSIONLESS_PROTOCOL_MIN_VERSION,
        )
        _deprecation_warning_logged = True

    return is_sessionless
