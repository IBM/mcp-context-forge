# -*- coding: utf-8 -*-
"""Location: ./plugins/tool_shadow_detector/tool_shadow_detector.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tool Shadow Detector Plugin.

Flags tool invocations whose name is suspiciously similar (small edit
distance) to ANOTHER already-registered tool backed by a DIFFERENT
gateway/server -- the "tool shadowing" pattern where an attacker
registers a malicious tool with a name that is a near-miss of a
legitimate one (e.g. ``get_user_role`` vs. ``get_user_roles``) to
trick a caller (human or LLM) into invoking the wrong one.

This plugin does not know which of the two similarly-named tools is
"the real one" -- it only detects the suspicious naming collision and
either warns (default) or blocks, leaving the actual trust decision to
an operator. It complements, but does not replace, an explicit
per-tool allow/deny policy (e.g. UnifiedPDPPlugin) once a shadow tool
has been identified.
"""

# Future
from __future__ import annotations

# Standard
from typing import Any, List, Optional

# Third-Party
from pydantic import BaseModel

# Third-Party
from cpex.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PluginViolation,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
)
from mcpgateway.services.logging_service import LoggingService

# Initialize logging service
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


def _levenshtein(a: str, b: str) -> int:
    """Compute the Levenshtein (edit) distance between two strings.

    Standard iterative dynamic-programming implementation, O(len(a) * len(b))
    time and O(min(len(a), len(b))) space. No external dependencies.

    Args:
        a: First string.
        b: Second string.

    Returns:
        The minimum number of single-character insertions, deletions, or
        substitutions required to turn ``a`` into ``b``.
    """
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    if not b:
        return len(a)

    previous_row = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        current_row = [i] + [0] * len(b)
        for j, char_b in enumerate(b, start=1):
            insert_cost = current_row[j - 1] + 1
            delete_cost = previous_row[j] + 1
            substitute_cost = previous_row[j - 1] + (0 if char_a == char_b else 1)
            current_row[j] = min(insert_cost, delete_cost, substitute_cost)
        previous_row = current_row
    return previous_row[-1]


class ToolShadowDetectorConfig(BaseModel):
    """Configuration for the tool shadow detector plugin.

    Attributes:
        max_edit_distance: Two tool names at or below this Levenshtein
            distance apart are considered a possible shadow pair.
        min_name_length: Names shorter than this are skipped entirely --
            very short names produce too many coincidental near-matches
            to be a useful signal (e.g. "ls" vs "cp" is meaningless).
        block_on_detection: If True, block the invocation when a shadow
            candidate is found. If False (default), allow the call through
            but attach the finding to the result's metadata so operators
            and downstream policy plugins (e.g. UnifiedPDPPlugin) can act
            on it -- flipping this to True without first reviewing false
            positives on your own tool catalog is not recommended.
        exempt_same_gateway: If True, two similarly-named tools registered
            under the SAME gateway/server are not flagged, on the theory
            that it's an ordinary naming choice by one server operator
            rather than cross-server impersonation. Defaults to False,
            because this assumption does not hold in practice: a single
            malicious server operator can register both a legitimate-
            looking tool and a shadow tool on the SAME server specifically
            to blend in (this is exactly the pattern used by the "tool
            shadowing" reference vulnerability this plugin targets — see
            PR description). Set True only if your deployment has verified,
            trusted multi-tool servers that intentionally use near-miss
            names and you want to suppress those specific false positives.
    """

    max_edit_distance: int = 2
    min_name_length: int = 6
    block_on_detection: bool = False
    exempt_same_gateway: bool = False


class ToolShadowDetectorPlugin(Plugin):
    """Detects tool names that are suspiciously similar to another
    already-registered tool backed by a different gateway.
    """

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the tool shadow detector plugin.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        self._cfg = ToolShadowDetectorConfig(**(config.config or {}))

    async def _find_shadow_candidates(self, tool_name: str, tool_gateway_id: Optional[str]) -> List[dict]:
        """Query the tool registry for other tools with a near-miss name.

        Args:
            tool_name: The slug/name of the tool being invoked.
            tool_gateway_id: The gateway/server ID that owns the invoked tool
                (None for a locally-defined, non-federated tool).

        Returns:
            A list of dicts describing each suspicious near-miss found,
            each with "name", "gateway_id", "distance" keys.
        """
        if len(tool_name) < self._cfg.min_name_length:
            return []

        # First-Party -- imported lazily so the plugin module can be loaded
        # (e.g. for unit tests) without a live database configured.
        from mcpgateway.db import Tool as DbTool  # pylint: disable=import-outside-toplevel
        from mcpgateway.db import get_db  # pylint: disable=import-outside-toplevel
        from sqlalchemy import select  # pylint: disable=import-outside-toplevel

        candidates: List[dict] = []
        gen = get_db()
        db = next(gen)
        try:
            # DbTool.name is the externally-visible, gateway-prefixed federated
            # name (e.g. "dvmcp-challenge5-get-user-roles") -- the same value
            # payload.name carries here. custom_name_slug is the tool's own
            # short local name WITHOUT the gateway prefix and is not
            # comparable to payload.name for federated tools.
            rows = db.execute(select(DbTool.name, DbTool.gateway_id).where(DbTool.enabled == True)).all()  # noqa: E712  pylint: disable=singleton-comparison
            for other_name, other_gateway_id in rows:
                if not other_name or other_name == tool_name:
                    continue
                if self._cfg.exempt_same_gateway and other_gateway_id == tool_gateway_id:
                    continue
                distance = _levenshtein(tool_name, other_name)
                if distance <= self._cfg.max_edit_distance:
                    candidates.append({"name": other_name, "gateway_id": other_gateway_id, "distance": distance})
        finally:
            db.close()

        return candidates

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
        """Check the invoked tool's name for suspicious near-miss collisions.

        Args:
            payload: Tool invocation payload.
            context: Plugin execution context.

        Returns:
            A ToolPreInvokeResult -- either pass-through (with a
            "tool_shadow_candidates" metadata entry when something was
            found) or blocked with a PluginViolation, depending on
            block_on_detection.
        """
        tool_gateway_id: Optional[str] = None
        server_id = getattr(context.global_context, "server_id", None)
        if server_id:
            tool_gateway_id = server_id

        try:
            candidates = await self._find_shadow_candidates(payload.name, tool_gateway_id)
        except Exception as exc:  # pylint: disable=broad-except
            # Never let a registry lookup failure break tool invocation --
            # this plugin is a detector, not a hard dependency.
            logger.warning("tool_shadow_detector: lookup failed for %s: %s", payload.name, exc)
            return ToolPreInvokeResult(continue_processing=True)

        if not candidates:
            return ToolPreInvokeResult(continue_processing=True)

        logger.warning("tool_shadow_detector: %s has %d near-miss name candidate(s): %s", payload.name, len(candidates), candidates)

        if self._cfg.block_on_detection:
            violation = PluginViolation(
                reason="Possible tool shadowing",
                description=(f"Tool '{payload.name}' has a name within edit distance {self._cfg.max_edit_distance} of {len(candidates)} other registered tool(s)."),
                code="TOOL_SHADOW_SUSPECTED",
                details={"tool": payload.name, "candidates": candidates},
            )
            return ToolPreInvokeResult(continue_processing=False, violation=violation)

        return ToolPreInvokeResult(continue_processing=True, metadata={"tool_shadow_candidates": candidates})
