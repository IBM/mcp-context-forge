# -*- coding: utf-8 -*-
"""Location: ./plugins/invinoveritas_review/invinoveritas_review.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: babyblueviper1

invinoveritas /review gate for tool_pre_invoke.

Grew out of issue #5437 (Human in the loop Approval for tool execution): gates every
tool invocation on an independent, signed pre-action verdict from invinoveritas
(api.babyblueviper.com/review) BEFORE the tool runs, rather than a rule-based auto_approve
boolean. A reject verdict blocks the call by default; approve/approve_with_concerns always
lets it proceed unmodified.

Design mirrors the same discipline used in the invinoveritas AutoGen GovernedWorkbench
integration (integrations/autogen/governed_workbench.py):
  - FAIL-OPEN on any /review-side problem (network error, timeout, malformed response,
    missing key) -- the tool call proceeds as if ungated, never silently hangs or blocks
    the gateway because our service had a bad moment. `review_unavailable` is set on the
    result metadata so it's visible, not silent.
  - GATES on a real reject verdict by default (block_on_reject=true in plugin config).
    Set block_on_reject=false for an advisory/observe-only rollout that never blocks,
    only annotates every ToolPreInvokeResult with the verdict.
  - Optional sign=true attaches a portable, independently-verifiable signed proof
    (verify at https://api.babyblueviper.com/verify-proof, free, no auth) to every
    verdict, win or block.

Configuration (inside plugins/config.yaml ``config:`` block), see PLUGIN_CONFIG below
for every field and its default:

    config:
      api_key: null              # falls back to IVV_API_KEY env var
      base_url: "https://api.babyblueviper.com"
      block_on_reject: true
      sign: false
      artifact_type: "general"
      timeout_s: 15.0
"""

# Standard
import json
import logging
import os
from typing import Any, Optional

# Third-Party
import httpx

# First-Party
from cpex.framework import Plugin, PluginContext, PluginResult, PluginViolation
from cpex.framework.hooks.tools import ToolPreInvokePayload, ToolPreInvokeResult

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.babyblueviper.com"
DEFAULT_TIMEOUT_S = 15.0
_VALID_VERDICTS = ("approve", "approve_with_concerns", "reject")


class InvinoveritasReviewPlugin(Plugin):
    """Gates tool_pre_invoke on an invinoveritas /review verdict.

    See module docstring for the full design discipline (fail-open, block_on_reject,
    sign). Register free, instant, no payment: POST https://api.babyblueviper.com/register
    """

    async def initialize(self) -> None:
        """Parse the plugin config block into local settings, once at startup."""
        cfg = self._config.config or {}
        self._api_key: Optional[str] = cfg.get("api_key") or os.environ.get("IVV_API_KEY")
        self._base_url: str = cfg.get("base_url", DEFAULT_BASE_URL)
        self._block_on_reject: bool = cfg.get("block_on_reject", True)
        self._sign: bool = cfg.get("sign", False)
        self._artifact_type: str = cfg.get("artifact_type", "general")
        self._timeout_s: float = cfg.get("timeout_s", DEFAULT_TIMEOUT_S)
        if not self._api_key:
            logger.warning(
                "InvinoveritasReviewPlugin: no IVV_API_KEY set (config.api_key or env var) -- "
                "every tool call will proceed UNGATED (review_unavailable). Register free at "
                "%s/register", self._base_url,
            )

    async def tool_pre_invoke(
        self,
        payload: ToolPreInvokePayload,
        context: PluginContext,
    ) -> ToolPreInvokeResult:
        """Called before every tool invocation.

        Args:
            payload: contains the tool name and invocation arguments.
            context: gateway-provided request context (unused directly here -- the
                verdict is scoped to the tool call itself, not the caller identity;
                a future revision could bind context.global_context.user into the
                /review `context` field for a richer audit trail).

        Returns:
            A ToolPreInvokeResult -- pass-through (with the verdict attached as
            metadata) or blocked with a PluginViolation on a reject verdict.
        """
        verdict = await self._review(payload, context)

        if verdict is None:
            # fail-open: either not configured, or the /review call itself failed
            return PluginResult(continue_processing=True, metadata={"invinoveritas_review": "unavailable"})

        if verdict.get("verdict") == "reject" and self._block_on_reject:
            violation = PluginViolation(
                reason="Independent invinoveritas /review verdict: reject",
                description=verdict.get("summary", "Blocked by an independent pre-action verdict."),
                code="IVV_REVIEW_REJECT",
                details={
                    "verdict": verdict.get("verdict"),
                    "confidence": verdict.get("confidence"),
                    "issues": verdict.get("issues"),
                    "verify_url": f"{self._base_url}/verify-proof",
                },
            )
            logger.warning(
                "InvinoveritasReviewPlugin BLOCK tool_pre_invoke | tool=%s | confidence=%s",
                payload.name, verdict.get("confidence"),
            )
            return PluginResult(continue_processing=False, violation=violation)

        return PluginResult(continue_processing=True, metadata={"invinoveritas_review": verdict})

    # ---- internals ----

    async def _review(
        self, payload: ToolPreInvokePayload, context: PluginContext
    ) -> Optional[dict[str, Any]]:
        """Returns the /review response dict, or None on any failure/misconfiguration
        (fail-open -- the caller treats None exactly like an approve, just without a
        verdict to attach)."""
        if not self._api_key:
            return None

        artifact = json.dumps({"tool_name": payload.name, "arguments": dict(payload.args or {})}, default=str)
        request_id = context.global_context.request_id if context.global_context else None
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                resp = await client.post(
                    f"{self._base_url}/review",
                    headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                    json={
                        "artifact": artifact,
                        "artifact_type": self._artifact_type,
                        "context": f"mcp-context-forge tool_pre_invoke, request_id={request_id}"
                        if request_id else "mcp-context-forge tool_pre_invoke",
                        "sign": self._sign,
                    },
                )
            resp.raise_for_status()
            data = resp.json()
            if data.get("verdict") not in _VALID_VERDICTS:
                logger.warning(
                    "InvinoveritasReviewPlugin: malformed /review response for %r, failing open: %r",
                    payload.name, data,
                )
                return None
            logger.info(
                "InvinoveritasReviewPlugin: %r -> %s (confidence=%s)",
                payload.name, data.get("verdict"), data.get("confidence"),
            )
            return data
        except Exception as e:  # noqa: BLE001 -- fail-open on ANY error, by design
            logger.warning(
                "InvinoveritasReviewPlugin: /review call failed for %r (%s), failing open (review_unavailable)",
                payload.name, e,
            )
            return None
