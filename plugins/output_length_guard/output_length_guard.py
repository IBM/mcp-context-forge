# -*- coding: utf-8 -*-
"""Location: ./plugins/output_length_guard/output_length_guard.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Output Length Guard Plugin for ContextForge.
Enforces min/max output length bounds on tool results, with either
truncate or block strategies.

Behavior
- If strategy = "truncate":
  - When result is a string longer than max_chars, truncate and append ellipsis.
  - Under-length results are allowed but annotated in metadata.
- If strategy = "block":
  - Block when result length is outside [min_chars, max_chars] (when provided).

Supported result shapes
- str: operate directly
- dict with a top-level "text" (str): operate on that field
- list[str]: operate element-wise
- MCP content array: [{"type": "text", "text": "..."}]
- MCP CallToolResult dict with "content" key

Other result types are ignored.
"""

# Future
from __future__ import annotations

# Standard
import logging
from typing import Any, List, Optional

# First-Party
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PluginViolation,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
)

# Local
from .config import LengthGuardPolicy, OutputLengthGuardConfig
from .guards import _evaluate_text_limits, _is_numeric_string, _truncate
from .structured import _generate_text_representation, _process_structured_data

logger = logging.getLogger(__name__)


def _handle_text(text: str, cfg: OutputLengthGuardConfig, policy: LengthGuardPolicy) -> tuple[str, dict[str, Any], Optional[PluginViolation]]:
    """Handle length guard for a single text string.

    Args:
        text: Text to check and possibly modify.
        cfg: Plugin configuration.
        policy: Enforcement policy.

    Returns:
        Tuple of (modified_text, metadata, violation).
    """
    try:
        if not isinstance(text, str):
            logger.error("Invalid text type in _handle_text: %s", type(text).__name__)
            return str(text) if text is not None else "", {"error": "invalid_type"}, None

        if _is_numeric_string(text):
            logger.debug("Preserving numeric string: length=%d", len(text))
            meta: dict[str, Any] = {"original_length": len(text), "numeric": True, "within_bounds": True}
            return text, meta, None

        length = len(text)
        token_count = length // cfg.chars_per_token
        meta = {"original_length": length}

        below_min, above_max = _evaluate_text_limits(length, token_count, policy)

        if not (below_min or above_max):
            logger.debug("Text within bounds: length=%d, mode=%s", length, cfg.limit_mode)
            meta.update({"within_bounds": True})
            return text, meta, None

        # Out of bounds
        meta.update(
            {
                "within_bounds": False,
                "limit_mode": cfg.limit_mode,
                "strategy": cfg.strategy,
            }
        )

        if cfg.is_blocking():
            logger.info("BLOCKING output: length=%d, tokens=%d, mode=%s", length, token_count, cfg.limit_mode)
            if above_max and cfg.limit_mode == "token":
                violation = PluginViolation(
                    reason="Output estimated token count out of bounds",
                    description=f"Estimated token count {token_count} exceeds max_tokens {cfg.max_tokens}",
                    code="OUTPUT_TOKEN_VIOLATION",
                    details={"token_count": token_count, "max_tokens": cfg.max_tokens, "chars_per_token": cfg.chars_per_token, "strategy": cfg.strategy},
                    http_status_code=422,
                    mcp_error_code=-32000,
                )
            elif above_max:
                violation = PluginViolation(
                    reason="Output length out of bounds",
                    description=f"Result length {length} exceeds max_chars {cfg.max_chars}",
                    code="OUTPUT_LENGTH_VIOLATION",
                    details={"length": length, "max_chars": cfg.max_chars, "strategy": cfg.strategy},
                    http_status_code=422,
                    mcp_error_code=-32000,
                )
            else:
                violation = PluginViolation(
                    reason="Output length below minimum",
                    description=f"Result length {length} (tokens {token_count}) below minimum",
                    code="OUTPUT_LENGTH_VIOLATION",
                    details={"length": length, "min_chars": cfg.min_chars, "token_count": token_count, "min_tokens": cfg.min_tokens, "strategy": cfg.strategy},
                    http_status_code=422,
                    mcp_error_code=-32000,
                )
            return text, meta, violation

        # Truncate strategy only handles over-length
        if above_max:
            logger.info("TRUNCATING output: original_length=%d, mode=%s", length, cfg.limit_mode)
            new_text = _truncate(
                text,
                cfg.max_chars,
                cfg.ellipsis,
                cfg.word_boundary,
                max_tokens=cfg.max_tokens,
                chars_per_token=cfg.chars_per_token,
                max_text_length=cfg.max_text_length,
                limit_mode=cfg.limit_mode,
            )
            reduction_pct = round((1 - len(new_text) / length) * 100, 1) if length > 0 else 0
            logger.info("Truncation complete: new_length=%d, reduction=%s%%", len(new_text), reduction_pct)
            meta.update({"truncated": True, "new_length": len(new_text)})
            return new_text, meta, None

        # Under min with truncate: allow through, annotate only
        logger.debug("Text below minimum but allowing through (truncate mode): length=%d", length)
        meta.update({"truncated": False, "new_length": length})
        return text, meta, None

    except (TypeError, ValueError, AttributeError) as e:
        logger.error(
            "Exception in _handle_text: %s: %s",
            type(e).__name__,
            str(e),
            extra={"function": "_handle_text", "error_type": type(e).__name__, "text_length": len(text) if isinstance(text, str) else "N/A"},
            exc_info=True,
        )
        return text if isinstance(text, str) else "", {"error": str(e)}, None


class OutputLengthGuardPlugin(Plugin):
    """Guard tool outputs by length with block or truncate strategies."""

    def __init__(self, config: PluginConfig):
        """Initialize the output length guard plugin.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        self._cfg = OutputLengthGuardConfig(**(config.config or {}))
        self._policy = self._cfg.to_policy()

        logger.info(
            "OutputLengthGuard initialized: mode=%s, strategy=%s, char_limits=[%s, %s], token_limits=[%s, %s], word_boundary=%s",
            self._cfg.limit_mode,
            self._cfg.strategy,
            self._cfg.min_chars,
            self._cfg.max_chars,
            self._cfg.min_tokens,
            self._cfg.max_tokens,
            self._cfg.word_boundary,
        )

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        """Guard tool output by length with block or truncate strategies.

        Args:
            payload: Tool invocation result payload.
            context: Plugin execution context.

        Returns:
            Result with length enforcement applied.
        """
        try:
            result_type = type(payload.result).__name__
            logger.info("OutputLengthGuard processing tool '%s' with result type: %s", payload.name, result_type)

            result = payload.result

            # Case 0: MCP CallToolResult as dict (from model_dump with 'content' key)
            if isinstance(result, dict) and "content" in result and isinstance(result.get("content"), list):
                return self._handle_mcp_content_dict(payload, result, context)

            # Case 1: String result
            if isinstance(result, str):
                return self._handle_plain_string(payload, result)

            # Case 2: Dict with text field
            if isinstance(result, dict):
                return self._handle_text_dict(payload, result)

            # Case 3: MCP content array format: [{"type": "text", "text": "..."}]
            if isinstance(result, list) and len(result) > 0 and isinstance(result[0], dict) and "type" in result[0]:
                return self._handle_mcp_list(payload, result)

            # Case 4: List of strings
            if isinstance(result, list) and all(isinstance(x, str) for x in result):
                return self._handle_string_list(payload, result)

            # Unsupported result type
            logger.debug("OutputLengthGuard: unsupported result type '%s' from tool '%s', passing through", type(result).__name__, payload.name)
            return ToolPostInvokeResult(continue_processing=True, metadata={"skipped": True, "reason": f"unsupported_type_{type(result).__name__}"})

        except (TypeError, ValueError, AttributeError, KeyError) as e:
            logger.error(
                "Exception in tool_post_invoke: %s: %s",
                type(e).__name__,
                str(e),
                extra={"function": "tool_post_invoke", "error_type": type(e).__name__, "tool_name": payload.name, "result_type": type(payload.result).__name__},
                exc_info=True,
            )
            return ToolPostInvokeResult(continue_processing=True, metadata={"error": str(e), "error_type": type(e).__name__})

    def _handle_mcp_content_dict(self, payload: ToolPostInvokePayload, result: dict, context: PluginContext) -> ToolPostInvokeResult:
        """Handle MCP CallToolResult dict with 'content' key.

        Args:
            payload: Tool invocation result payload.
            result: Dict with 'content' list.
            context: Plugin execution context.

        Returns:
            Result with length enforcement applied.
        """
        cfg = self._cfg
        policy = self._policy

        # PRIORITY CHECK: Process structuredContent first if present (and not None/null)
        struct_key = None
        if "structuredContent" in result and result["structuredContent"] is not None:
            struct_key = "structuredContent"
        elif "structured_content" in result and result["structured_content"] is not None:
            struct_key = "structured_content"

        if struct_key:
            truncated_struct, struct_modified, violation = _process_structured_data(result[struct_key], policy, context, "")

            if violation:
                logger.debug("Blocking due to violation in %s", struct_key)
                return ToolPostInvokeResult(
                    continue_processing=False,
                    violation=violation,
                    metadata={"structured_content_blocked": True, "location": struct_key, "min_tokens": cfg.min_tokens, "max_tokens": cfg.max_tokens, "chars_per_token": cfg.chars_per_token},
                )

            if struct_modified:
                new_result = dict(result)
                new_result[struct_key] = truncated_struct
                new_text = _generate_text_representation(truncated_struct)
                new_result["content"] = [{"type": "text", "text": new_text}]

                return ToolPostInvokeResult(
                    modified_payload=ToolPostInvokePayload(name=payload.name, result=new_result),
                    metadata={
                        "mcp_result_processed": True,
                        "items_modified": True,
                        "structured_content_processed": True,
                        "min_tokens": cfg.min_tokens,
                        "max_tokens": cfg.max_tokens,
                        "chars_per_token": cfg.chars_per_token,
                    },
                )
            return ToolPostInvokeResult(metadata={"mcp_result_processed": True, "items_modified": False, "structured_content_processed": False})

        # NO structuredContent: Process content array normally
        modified = False
        content_out: List[Any] = []

        for item in result["content"]:
            if isinstance(item, dict) and item.get("type") == "text" and "text" in item:
                current_text = item["text"]
                new_text, meta, violation = _handle_text(current_text, cfg, policy)

                if violation:
                    return ToolPostInvokeResult(continue_processing=False, violation=violation, metadata=meta)

                if new_text != current_text:
                    modified = True
                    new_item = dict(item)
                    new_item["text"] = new_text
                    content_out.append(new_item)
                else:
                    content_out.append(item)
            else:
                content_out.append(item)

        if modified:
            new_result = dict(result)
            new_result["content"] = content_out

            return ToolPostInvokeResult(
                modified_payload=ToolPostInvokePayload(name=payload.name, result=new_result),
                metadata={"mcp_result_processed": True, "items_modified": True, "structured_content_processed": False},
            )
        return ToolPostInvokeResult(metadata={"mcp_result_processed": True, "items_modified": False})

    def _handle_plain_string(self, payload: ToolPostInvokePayload, result: str) -> ToolPostInvokeResult:
        """Handle plain string result.

        Args:
            payload: Tool invocation result payload.
            result: String result.

        Returns:
            Result with length enforcement applied.
        """
        new_text, meta, violation = _handle_text(result, self._cfg, self._policy)
        if violation:
            return ToolPostInvokeResult(continue_processing=False, violation=violation, metadata=meta)
        if new_text != result:
            return ToolPostInvokeResult(modified_payload=ToolPostInvokePayload(name=payload.name, result=new_text), metadata=meta)
        return ToolPostInvokeResult(metadata=meta)

    def _handle_text_dict(self, payload: ToolPostInvokePayload, result: dict) -> ToolPostInvokeResult:
        """Handle dict result with optional 'text' field.

        Args:
            payload: Tool invocation result payload.
            result: Dict result.

        Returns:
            Result with length enforcement applied.
        """
        if isinstance(result.get("text"), str):
            current = result["text"]
            new_text, meta, violation = _handle_text(current, self._cfg, self._policy)
            if violation:
                return ToolPostInvokeResult(continue_processing=False, violation=violation, metadata=meta)
            if new_text != current:
                new_res = dict(result)
                new_res["text"] = new_text
                return ToolPostInvokeResult(modified_payload=ToolPostInvokePayload(name=payload.name, result=new_res), metadata=meta)
            return ToolPostInvokeResult(metadata=meta)
        logger.debug("OutputLengthGuard: Dict result from tool '%s' has no 'text' field, passing through unchanged", payload.name)
        return ToolPostInvokeResult(continue_processing=True)

    def _handle_mcp_list(self, payload: ToolPostInvokePayload, result: list) -> ToolPostInvokeResult:
        """Handle MCP content array format: [{"type": "text", "text": "..."}].

        Args:
            payload: Tool invocation result payload.
            result: List of MCP content items.

        Returns:
            Result with length enforcement applied.
        """
        modified = False
        mcp_out: List[Any] = []

        for item in result:
            if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                current_text = item["text"]
                new_text, meta, violation = _handle_text(current_text, self._cfg, self._policy)

                if violation:
                    return ToolPostInvokeResult(continue_processing=False, violation=violation, metadata=meta)

                if new_text != current_text:
                    modified = True
                    new_item = dict(item)
                    new_item["text"] = new_text
                    mcp_out.append(new_item)
                else:
                    mcp_out.append(item)
            else:
                mcp_out.append(item)

        if modified:
            return ToolPostInvokeResult(modified_payload=ToolPostInvokePayload(name=payload.name, result=mcp_out), metadata={"mcp_content_processed": True})
        return ToolPostInvokeResult(metadata={"mcp_content_processed": True})

    def _handle_string_list(self, payload: ToolPostInvokePayload, result: list) -> ToolPostInvokeResult:
        """Handle list of strings result.

        Args:
            payload: Tool invocation result payload.
            result: List of strings.

        Returns:
            Result with length enforcement applied.
        """
        texts: List[str] = result
        modified = False
        meta_list: List[dict[str, Any]] = []
        str_list_out: List[str] = []

        for idx, t in enumerate(texts):
            new_t, m, violation = _handle_text(t, self._cfg, self._policy)
            meta_list.append(m)

            if violation:
                return ToolPostInvokeResult(continue_processing=False, violation=violation, metadata={"items": meta_list, "violation_index": idx, "total_items": len(texts)})

            if new_t != t:
                modified = True

            str_list_out.append(new_t)

        if modified:
            return ToolPostInvokeResult(modified_payload=ToolPostInvokePayload(name=payload.name, result=str_list_out), metadata={"items": meta_list})
        return ToolPostInvokeResult(metadata={"items": meta_list})
