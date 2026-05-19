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
from functools import lru_cache
import logging
from typing import Optional

# Third-Party
from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS as MCP_SUPPORTED_PROTOCOL_VERSIONS

logger = logging.getLogger(__name__)

SUPPORTED_PROTOCOL_VERSIONS = list(MCP_SUPPORTED_PROTOCOL_VERSIONS)

# Sessionless semantics start with the post-session SEP-aligned protocol.
SESSIONLESS_PROTOCOL_MIN_VERSION = "2025-11-25"

# Default to the latest sessionful version for backward compatibility.
# This prevents clients that don't send a protocol version from being
# silently pulled into sessionless mode when LATEST_PROTOCOL_VERSION
# advances to >= 2025-11-25. Clients must explicitly opt into sessionless
# semantics by sending protocolVersion >= "2025-11-25" in initialize.
DEFAULT_PROTOCOL_VERSION = "2024-11-05"  # Latest sessionful version


@lru_cache(maxsize=None)
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


@lru_cache(maxsize=128)
def _log_deprecation_warning_once(normalized_version: str) -> None:
    """Log deprecation warning once per unique version (thread-safe via lru_cache)."""
    logger.warning(
        "DEPRECATION: MCP protocol version %s uses legacy sessionful semantics. "
        "Sessionful protocols (< %s) are deprecated and will be removed in a future release. "
        "Please upgrade to protocol version %s or later for sessionless semantics. "
        "See https://github.com/modelcontextprotocol/specification/pull/2567 for details.",
        normalized_version,
        SESSIONLESS_PROTOCOL_MIN_VERSION,
        SESSIONLESS_PROTOCOL_MIN_VERSION,
    )


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
    normalized = normalize_mcp_protocol_version(protocol_version)
    # Lexical comparison is safe because MCP versions use ISO-8601 date format (YYYY-MM-DD).
    # This ensures correct ordering: "2024-11-05" < "2025-11-25" < "2026-01-01".
    # If MCP ever adopts non-date version labels, this comparison will need updating.
    is_sessionless = normalized >= SESSIONLESS_PROTOCOL_MIN_VERSION

    # Log deprecation warning for sessionful protocols (once per unique version, thread-safe)
    if not is_sessionless:
        _log_deprecation_warning_once(normalized)

    return is_sessionless
