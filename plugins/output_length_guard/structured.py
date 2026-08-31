# -*- coding: utf-8 -*-
"""Structured data processing for output length guard.

Location: ./plugins/output_length_guard/structured.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti
"""

# Future
from __future__ import annotations

# Standard
import json
import logging
from typing import Any, Optional

# First-Party
from cpex.framework import (
    PluginContext,
    PluginViolation,
)

# Local
from .config import LengthGuardPolicy
from .guards import _evaluate_text_limits, _is_numeric_string, _truncate

logger = logging.getLogger(__name__)


def _process_structured_data(
    data: Any,
    policy: LengthGuardPolicy,
    context: PluginContext,
    path: str = "",
    depth: int = 0,
) -> tuple[Any, bool, Optional[PluginViolation]]:
    """Recursively process structured data, truncating or blocking based on strategy.

    Traverses nested data structures (lists, dicts) and either truncates
    or blocks when string values exceed limits. Numeric strings (integers, floats,
    and scientific notation) are not truncated or blocked.

    Args:
        data: The data to process (can be str, list, dict, or nested structures).
        policy: Enforcement policy with all limit parameters.
        context: Plugin context for logging.
        path: Current path in data structure (for error reporting).
        depth: Current recursion depth.

    Returns:
        Tuple of (modified_data, was_modified, violation).
        - In block mode: returns violation if any string exceeds limits
        - In truncate mode: returns modified data with truncated strings
    """
    try:
        logger.debug("Processing structured data: type=%s, path=%s, strategy=%s", type(data).__name__, path or "root", policy.strategy)

        # Security: Check recursion depth
        if depth > policy.max_recursion_depth:
            logger.error("Recursion depth %d exceeds maximum %d at path: %s", depth, policy.max_recursion_depth, path)
            if policy.strategy == "block":
                return (
                    data,
                    False,
                    PluginViolation(
                        reason="Recursion depth exceeds security limit",
                        description=f"Nesting depth {depth} exceeds limit of {policy.max_recursion_depth}",
                        code="STRUCTURE_DEPTH_VIOLATION",
                        details={"depth": depth, "max_depth": policy.max_recursion_depth, "location": path or "root"},
                        mcp_error_code=-32000,
                        http_status_code=422,
                    ),
                )
            return data, False, None

        # Base case: string
        if isinstance(data, str):
            if _is_numeric_string(data):
                logger.debug("Skipping numeric string at %s: length=%d", path or "root", len(data))
                return data, False, None

            length = len(data)
            token_count = length // policy.chars_per_token

            below_min, above_max = _evaluate_text_limits(length, token_count, policy)

            if below_min or above_max:
                logger.debug(
                    "String out of bounds at %s: length=%d, tokens=%d, mode=%s",
                    path or "root",
                    length,
                    token_count,
                    policy.limit_mode,
                )

                # BLOCK MODE: Return violation immediately
                if policy.strategy == "block":
                    location = f" at {path}" if path else ""

                    if above_max and policy.limit_mode == "token":
                        violation = PluginViolation(
                            reason=f"Estimated token count out of bounds{location}",
                            description=f"Estimated token count {token_count} exceeds max_tokens {policy.max_tokens}{location}",
                            code="OUTPUT_TOKEN_VIOLATION",
                            details={
                                "token_count": token_count,
                                "max_tokens": policy.max_tokens,
                                "chars_per_token": policy.chars_per_token,
                                "strategy": policy.strategy,
                                "location": path or "root",
                            },
                            mcp_error_code=-32000,
                            http_status_code=422,
                        )
                        logger.warning("Token limit violation, blocking: location=%s, tokens=%d, max=%s", path or "root", token_count, policy.max_tokens)
                    elif above_max:
                        violation = PluginViolation(
                            reason=f"String length out of bounds{location}",
                            description=f"String length {length} exceeds max_chars {policy.max_chars}{location}",
                            code="OUTPUT_LENGTH_VIOLATION",
                            details={"length": length, "max_chars": policy.max_chars, "strategy": policy.strategy, "location": path or "root"},
                            mcp_error_code=-32000,
                            http_status_code=422,
                        )
                        logger.debug("Blocking: string at %s exceeds char limits (length=%d)", path or "root", length)
                    else:
                        violation = PluginViolation(
                            reason=f"String length/tokens below minimum{location}",
                            description=f"String length {length} or tokens {token_count} below minimum{location}",
                            code="OUTPUT_LENGTH_VIOLATION",
                            details={"length": length, "min_chars": policy.min_chars, "token_count": token_count, "min_tokens": policy.min_tokens, "location": path or "root"},
                            mcp_error_code=-32000,
                            http_status_code=422,
                        )
                        logger.debug("Blocking: string at %s below minimum limits", path or "root")

                    return data, False, violation

                # TRUNCATE MODE: Only truncate if above max
                if above_max:
                    truncated = _truncate(
                        data,
                        policy.max_chars,
                        policy.ellipsis,
                        policy.word_boundary,
                        policy.max_tokens,
                        policy.chars_per_token,
                        policy.max_text_length,
                        policy.limit_mode,
                    )
                    was_modified = truncated != data
                    return truncated, was_modified, None

            return data, False, None

        # Recursive case: list
        if isinstance(data, list):
            if len(data) > policy.max_structure_size:
                logger.error("List size %d exceeds maximum %d at path: %s", len(data), policy.max_structure_size, path)
                if policy.strategy == "block":
                    return (
                        data,
                        False,
                        PluginViolation(
                            reason="Structure size exceeds security limit",
                            description=f"List has {len(data)} items, exceeding limit of {policy.max_structure_size}",
                            code="STRUCTURE_SIZE_VIOLATION",
                            details={"size": len(data), "max_size": policy.max_structure_size, "location": path or "root"},
                            mcp_error_code=-32000,
                            http_status_code=422,
                        ),
                    )
                return data, False, None

            modified = False
            result = []
            for idx, item in enumerate(data):
                item_path = f"{path}[{idx}]" if path else f"[{idx}]"
                processed_item, item_modified, violation = _process_structured_data(item, policy, context, item_path, depth + 1)

                if violation:
                    return data, False, violation

                result.append(processed_item)
                if item_modified:
                    modified = True
            return result, modified, None

        # Recursive case: dict
        if isinstance(data, dict):
            if len(data) > policy.max_structure_size:
                logger.error("Dict size %d exceeds maximum %d at path: %s", len(data), policy.max_structure_size, path)
                if policy.strategy == "block":
                    return (
                        data,
                        False,
                        PluginViolation(
                            reason="Structure size exceeds security limit",
                            description=f"Dict has {len(data)} items, exceeding limit of {policy.max_structure_size}",
                            code="STRUCTURE_SIZE_VIOLATION",
                            details={"size": len(data), "max_size": policy.max_structure_size, "location": path or "root"},
                            mcp_error_code=-32000,
                            http_status_code=422,
                        ),
                    )
                return data, False, None

            modified = False
            result = {}
            for key, value in data.items():
                value_path = f"{path}.{key}" if path else key
                processed_value, value_modified, violation = _process_structured_data(value, policy, context, value_path, depth + 1)

                if violation:
                    return data, False, violation

                result[key] = processed_value
                if value_modified:
                    modified = True
            return result, modified, None

        # Other types (int, bool, None, etc.) - pass through unchanged
        return data, False, None

    except (RecursionError, MemoryError, TypeError, KeyError, AttributeError) as e:
        logger.error(
            "Exception in _process_structured_data: %s: %s",
            type(e).__name__,
            str(e),
            extra={"function": "_process_structured_data", "error_type": type(e).__name__, "path": path, "data_type": type(data).__name__},
            exc_info=True,
        )
        return data, False, None


def _generate_text_representation(data: Any, _depth: int = 0) -> str:
    """Generate a formatted text representation of structured data.

    For single-key dicts (like {"result": [...]}), extracts and formats just the value.
    For simple strings, returns them directly without JSON encoding.
    Uses json.dumps for clean formatting of lists and dicts.
    Falls back to repr() for other types.

    Args:
        data: The data to represent as text.
        _depth: Internal recursion depth counter.

    Returns:
        Formatted string representation.
    """
    try:
        if isinstance(data, str):
            return data

        # Single-key dict unwrapping with depth limit to prevent infinite recursion
        if isinstance(data, dict) and len(data) == 1 and _depth < 10:
            value = next(iter(data.values()))
            return _generate_text_representation(value, _depth + 1)

        if isinstance(data, (list, dict)):
            return json.dumps(data, ensure_ascii=False, separators=(",", ":"))

        return repr(data)
    except (TypeError, ValueError, AttributeError, KeyError) as e:
        logger.error(
            "Exception in _generate_text_representation: %s: %s",
            type(e).__name__,
            str(e),
            extra={"function": "_generate_text_representation", "error_type": type(e).__name__, "data_type": type(data).__name__},
            exc_info=True,
        )
        try:
            return repr(data)
        except Exception:
            return "<unrepresentable data>"
