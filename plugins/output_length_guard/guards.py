# -*- coding: utf-8 -*-
"""Pure helper functions for output length guard enforcement.

Location: ./plugins/output_length_guard/guards.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti
"""

# Future
from __future__ import annotations

# Standard
import logging
import math
from typing import Optional

# Local
from .config import LengthGuardPolicy

logger = logging.getLogger(__name__)

# Maximum length for numeric string exemption
_MAX_NUMERIC_STRING_LENGTH = 50

# Performance optimization - Module-level constant
BOUNDARY_CHARS = frozenset({" ", "\t", "\n", "\r", ".", ",", ";", ":", "!", "?", "-", "\u2014", "\u2013", "/", "\\", "(", ")", "[", "]", "{", "}"})


def _evaluate_text_limits(length: int, token_count: int, policy: LengthGuardPolicy) -> tuple[bool, bool]:
    """Evaluate whether text violates limits based on policy.limit_mode.

    Centralized limit evaluation used by all code paths to ensure
    consistent enforcement of character vs token mode.

    Args:
        length: Character length of the text.
        token_count: Estimated token count of the text.
        policy: Enforcement policy.

    Returns:
        Tuple of (below_min, above_max) for the active limit mode.
    """
    if policy.limit_mode == "character":
        below_min = policy.min_chars > 0 and length < policy.min_chars
        above_max = policy.max_chars is not None and length > policy.max_chars
    else:  # token
        below_min = policy.min_tokens > 0 and token_count < policy.min_tokens
        above_max = policy.max_tokens is not None and token_count > policy.max_tokens
    return below_min, above_max


def _estimate_tokens(text: str, chars_per_token: int) -> int:
    """Estimate token count using configurable chars-per-token ratio.

    This is an approximate estimation based on the industry-standard heuristic
    that English text averages ~4 characters per token for GPT models.

    Args:
        text: String to estimate tokens for.
        chars_per_token: Characters per token ratio (default: 4).

    Returns:
        Estimated token count. Returns 0 if an error occurs.
    """
    if not isinstance(text, str):
        logger.error("Invalid text type in _estimate_tokens: %s, expected str", type(text).__name__)
        return 0

    if not isinstance(chars_per_token, int):
        logger.error("Invalid chars_per_token type: %s, expected int", type(chars_per_token).__name__)
        chars_per_token = 4

    if chars_per_token <= 0:
        logger.error("Invalid chars_per_token: %d, using default 4", chars_per_token)
        chars_per_token = 4

    token_count = len(text) // chars_per_token
    logger.debug("Token estimation: %d chars / %d = %d tokens", len(text), chars_per_token, token_count)
    return token_count


def _find_word_boundary(value: str, cut: int, max_chars: int) -> int:
    """Find word boundary position without creating substrings.

    Returns position instead of creating substrings in the loop,
    reducing from O(n) substring creations to O(1).

    Args:
        value: String to search.
        cut: Initial cut position.
        max_chars: Maximum characters (for calculating search range).

    Returns:
        Position of word boundary, or cut if none found.
    """
    try:
        if not isinstance(value, str):
            logger.error("Invalid value type in _find_word_boundary: %s", type(value).__name__)
            return cut

        if not value or cut <= 0:
            return cut

        # Ensure cut is within bounds
        cut = min(cut, len(value))

        min_search = max(0, cut - int(max_chars * 0.2))

        for i in range(cut - 1, min_search - 1, -1):
            if value[i] in BOUNDARY_CHARS:
                return i + 1

        return cut  # No boundary found

    except (IndexError, TypeError, ValueError) as e:
        logger.error(
            "Exception in _find_word_boundary: %s: %s",
            type(e).__name__,
            str(e),
            extra={"function": "_find_word_boundary", "error_type": type(e).__name__, "value_length": len(value) if isinstance(value, str) else "N/A", "cut": cut, "max_chars": max_chars},
            exc_info=True,
        )
        return cut


def _truncate(
    value: str,
    max_chars: Optional[int],
    ellipsis: str,
    word_boundary: bool = False,
    max_tokens: Optional[int] = None,
    chars_per_token: int = 4,
    max_text_length: int = 1_000_000,
    limit_mode: str = "character",
) -> str:
    """Truncate string to maximum length with ellipsis.

    Args:
        value: String to truncate.
        max_chars: Maximum number of characters. None means no limit.
        ellipsis: Ellipsis string to append.
        word_boundary: If True, truncate at word boundaries to avoid mid-word cuts.
        max_tokens: Maximum number of estimated tokens. None means no token limit.
        chars_per_token: Characters per token ratio for estimation.
        max_text_length: Maximum text size to process (security limit).
        limit_mode: "character" (character-based only) or "token" (token-based only).

    Returns:
        Truncated string, or original if within limits.
    """
    try:
        if not isinstance(value, str):
            logger.error("Invalid value type in _truncate: %s", type(value).__name__)
            return str(value) if value is not None else ""

        ell = ellipsis or ""

        # Token-based truncation (only if limit_mode is "token" and max_tokens specified)
        if limit_mode == "token" and max_tokens is not None and max_tokens > 0:
            estimated_tokens = len(value) // chars_per_token

            if estimated_tokens > max_tokens:
                # Direct arithmetic: max character position that fits token budget
                safe_chars_per_token = max(1, chars_per_token)
                capped_value = value[:max_text_length] if len(value) > max_text_length else value
                cut = min(len(capped_value), max_tokens * safe_chars_per_token)

                if word_boundary and cut > 0:
                    cut = _find_word_boundary(value, cut, cut)

                return value[:cut] + ell

        # Character-based truncation (only if limit_mode is "character")
        if limit_mode != "character":
            return value

        if max_chars is None or max_chars == 0:
            return value

        value_len = len(value)
        if value_len <= max_chars:
            return value

        # Truncation needed
        ell_len = len(ell)

        # If ellipsis doesn't fit, hard cut
        if ell_len >= max_chars:
            return value[:max_chars]

        cut = max_chars - ell_len

        if word_boundary and cut > 0:
            cut = _find_word_boundary(value, cut, max_chars)

        return value[:cut] + ell

    except (IndexError, ValueError, TypeError, MemoryError) as e:
        logger.error(
            "Exception in _truncate: %s: %s",
            type(e).__name__,
            str(e),
            extra={
                "function": "_truncate",
                "error_type": type(e).__name__,
                "value_length": len(value) if isinstance(value, str) else "N/A",
                "max_chars": max_chars,
                "max_tokens": max_tokens,
                "limit_mode": limit_mode,
            },
            exc_info=True,
        )
        return value if isinstance(value, str) else ""


def _is_numeric_string(text: str) -> bool:
    """Check if a string represents a finite numeric value.

    Handles integers, floats, and scientific notation.
    Rejects nan, inf, and strings longer than 50 characters
    to prevent guard bypass via numeric exemption.

    Examples: "123", "123.45", "1.23e-4", "5E+10"

    Args:
        text: String to check.

    Returns:
        True if string is a finite numeric value, False otherwise.
    """
    if len(text) > _MAX_NUMERIC_STRING_LENGTH:
        return False
    try:
        return math.isfinite(float(text))
    except (ValueError, OverflowError):
        return False
