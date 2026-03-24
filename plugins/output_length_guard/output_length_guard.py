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

Other result types are ignored.
"""


# Future
from __future__ import annotations

# Standard
import json
from typing import Any, ClassVar, Dict, List, Optional, Tuple
from venv import logger

# Third-Party
from pydantic import BaseModel, Field, field_validator, model_validator

# First-Party
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PluginViolation,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
)
import logging
logging.basicConfig(level=logging.DEBUG)


class OutputLengthGuardConfig(BaseModel):
    """Configuration for the Output Length Guard plugin."""

    ALLOWED_STRATEGIES: ClassVar[set[str]] = {"truncate", "block"}
    ALLOWED_LIMIT_MODES: ClassVar[set[str]] = {"character", "token"}

    # Output limits
    min_chars: int = Field(default=0, ge=0, description="Minimum allowed characters. 0 disables minimum check.")
    max_chars: Optional[int] = Field(default=None, description="Maximum allowed characters. 0 or None disables maximum check.")
    min_tokens: int = Field(default=0, ge=0, description="Minimum allowed tokens. 0 disables minimum token check.")
    max_tokens: Optional[int] = Field(default=None, description="Maximum allowed tokens. 0 or None disables maximum token check.")
    chars_per_token: int = Field(default=4, ge=1, le=10, description="Characters per token ratio for estimation. Default: 4 (English/GPT models)")

    # Behavior
    limit_mode: str = Field(default="character", description='Limit enforcement mode: "character" (character-based limits only) or "token" (token-based limits only)')
    strategy: str = Field(default="truncate", description='Strategy when out of bounds: "truncate" or "block"')
    ellipsis: str = Field(default="…", description="Suffix appended on truncation. Use empty string to disable.")
    word_boundary: bool = Field(default=False, description="When true, truncate at word boundaries to avoid mid-word cuts.")

    # Security limits
    max_text_length: int = Field(default=1_000_000, description="Maximum text size to process (1MB default). Prevents memory exhaustion.")
    max_structure_size: int = Field(default=10_000, description="Maximum items in list/dict (10K default). Prevents DoS attacks.")
    max_recursion_depth: int = Field(default=100, description="Maximum nesting depth (100 default). Prevents stack overflow.")
    max_binary_search_iterations: int = Field(default=30, description="Binary search iteration limit (30 default). Prevents infinite loops.")

    @field_validator('limit_mode')
    @classmethod
    def validate_limit_mode(cls, v: str) -> str:
        """Validate limit_mode is one of the allowed values.

        Args:
            v: Limit mode value to validate.

        Returns:
            Validated limit_mode value (lowercase).

        Raises:
            ValueError: If limit_mode is not 'character' or 'token'.
        """
        normalized = v.lower().strip()
        if normalized not in cls.ALLOWED_LIMIT_MODES:
            raise ValueError(
                f"Invalid limit_mode '{v}'. Must be one of: {', '.join(sorted(cls.ALLOWED_LIMIT_MODES))}"
            )
        return normalized

    @field_validator('strategy')
    @classmethod
    def validate_strategy(cls, v: str) -> str:
        """Validate strategy is one of the allowed values.
        
        Args:
            v: Strategy value to validate.
            
        Returns:
            The validated strategy value.
            
        Raises:
            ValueError: If strategy is not in ALLOWED_STRATEGIES.
        """
        logging.debug(f"Validating strategy: {v}")

        Args:
            v: Strategy value to validate.

        Returns:
            Validated strategy value (lowercase).

        Raises:
            ValueError: If strategy is not 'truncate' or 'block'.
        """
        normalized = v.lower().strip()
        if normalized not in cls.ALLOWED_STRATEGIES:
            raise ValueError(
                f"Invalid strategy '{v}'. Must be one of: {', '.join(sorted(cls.ALLOWED_STRATEGIES))}"
            )
        return normalized

    @field_validator('max_chars')
    @classmethod
    def validate_max_chars(cls, v: Optional[int]) -> Optional[int]:
        """Validate max_chars is positive when set, or convert 0 to None.

        Args:
            v: Maximum characters value.

        Returns:
            Validated max_chars value (None if 0 or None).

        Raises:
            ValueError: If max_chars is negative.
        """
        if v is not None and v < 0:
            raise ValueError("max_chars must be >= 0 (0 disables), or None to disable")
        # Treat 0 as None (disabled)
        return None if v == 0 else v

    @field_validator('max_tokens')
    @classmethod
    def validate_max_tokens(cls, v: Optional[int]) -> Optional[int]:
        """Validate max_tokens is positive when set, or convert 0 to None.

        Args:
            v: Maximum tokens value.

        Returns:
            Validated max_tokens value (None if 0 or None).

        Raises:
            ValueError: If max_tokens is negative.
        """
        if v is not None and v < 0:
            raise ValueError("max_tokens must be >= 0 (0 disables), or None to disable")
        # Treat 0 as None (disabled)
        return None if v == 0 else v

    @field_validator('chars_per_token')
    @classmethod
    def validate_chars_per_token(cls, v: int) -> int:
        """Validate chars_per_token is in reasonable range.

        Args:
            v: Characters per token ratio.

        Returns:
            Validated chars_per_token value.

        Raises:
            ValueError: If chars_per_token is not in range 1-10.
        """
        if v < 1 or v > 10:
            raise ValueError("chars_per_token must be between 1 and 10")
        return v

    @field_validator('max_text_length')
    @classmethod
    def validate_max_text_length(cls, v: int) -> int:
        """Validate max_text_length is in reasonable range.

        Args:
            v: Maximum text length value.

        Returns:
            Validated max_text_length value.

        Raises:
            ValueError: If max_text_length is not in range 1KB to 10MB.
        """
        if v < 1000 or v > 10_000_000:
            raise ValueError("max_text_length must be between 1000 (1KB) and 10000000 (10MB)")
        return v

    @field_validator('max_structure_size')
    @classmethod
    def validate_max_structure_size(cls, v: int) -> int:
        """Validate max_structure_size is in reasonable range.

        Args:
            v: Maximum structure size value.

        Returns:
            Validated max_structure_size value.

        Raises:
            ValueError: If max_structure_size is not in range 10-100K.
        """
        if v < 10 or v > 100_000:
            raise ValueError("max_structure_size must be between 10 and 100000")
        return v

    @field_validator('max_recursion_depth')
    @classmethod
    def validate_max_recursion_depth(cls, v: int) -> int:
        """Validate max_recursion_depth is in reasonable range.

        Args:
            v: Maximum recursion depth value.

        Returns:
            Validated max_recursion_depth value.

        Raises:
            ValueError: If max_recursion_depth is not in range 10-1000.
        """
        if v < 10 or v > 1000:
            raise ValueError("max_recursion_depth must be between 10 and 1000")
        return v

    @field_validator('max_binary_search_iterations')
    @classmethod
    def validate_max_binary_search_iterations(cls, v: int) -> int:
        """Validate max_binary_search_iterations is in reasonable range.

        Args:
            v: Maximum binary search iterations value.

        Returns:
            Validated max_binary_search_iterations value.

        Raises:
            ValueError: If max_binary_search_iterations is not in range 10-100.
        """
        if v < 10 or v > 100:
            raise ValueError("max_binary_search_iterations must be between 10 and 100")
        return v

    @model_validator(mode='after')
    def validate_min_max_relationship(self) -> 'OutputLengthGuardConfig':
        """Ensure min_chars <= max_chars and min_tokens <= max_tokens when both are set.

        Returns:
            Validated config instance.

        Raises:
            ValueError: If min_chars > max_chars or min_tokens > max_tokens.
        """
        if self.max_chars is not None and self.min_chars > self.max_chars:
            raise ValueError(
                f"min_chars ({self.min_chars}) cannot be greater than max_chars ({self.max_chars})"
            )
        if self.max_tokens is not None and self.min_tokens > self.max_tokens:
            raise ValueError(
                f"min_tokens ({self.min_tokens}) cannot be greater than max_tokens ({self.max_tokens})"
            )
        return self

    def is_blocking(self) -> bool:
        """Check if strategy is set to blocking mode.

        Returns:
            True if strategy is block.
        """
        return self.strategy == "block"  # Already normalized by validator


def _length(value: str) -> int:
    """Get length of string value.

    Args:
        value: String to measure.

    Returns:
        Length of string.
    """
    return len(value)


# Performance optimization - Module-level constant (kept for performance)
BOUNDARY_CHARS = frozenset({
    ' ', '\t', '\n', '\r', '.', ',', ';', ':', '!', '?',
    '-', '—', '–', '/', '\\', '(', ')', '[', ']', '{', '}'
})


def _estimate_tokens(text: str, chars_per_token: int) -> int:
    """Estimate token count using configurable chars-per-token ratio.

    This is an approximate estimation based on the industry-standard heuristic
    that English text averages ~4 characters per token for GPT models.

    Args:
        text: String to estimate tokens for
        chars_per_token: Characters per token ratio (default: 4)

    Returns:
        Estimated token count. Returns 0 if an error occurs.

    Note:
        All exceptions are caught and handled internally. On error, returns 0
        and logs the exception. Handles: ZeroDivisionError, TypeError, ValueError.

    Examples:
        >>> _estimate_tokens("Hello world", 4)
        2  # 11 chars / 4 = 2 tokens

        >>> _estimate_tokens("Hello world", 3)
        3  # 11 chars / 3 = 3 tokens
    """
    try:
        # Validate inputs
        if not isinstance(text, str):
            logger.error(f"Invalid text type in _estimate_tokens: {type(text).__name__}, expected str")
            return 0

        if not isinstance(chars_per_token, int):
            logger.error(f"Invalid chars_per_token type: {type(chars_per_token).__name__}, expected int")
            chars_per_token = 4

        if chars_per_token <= 0:
            logger.error(f"Invalid chars_per_token: {chars_per_token}, using default 4")
            chars_per_token = 4

        token_count = len(text) // chars_per_token

        logger.debug(
            f"Token estimation: {len(text)} chars / {chars_per_token} = {token_count} tokens"
        )

        return token_count

    except (ZeroDivisionError, TypeError, ValueError) as e:
        logger.error(
            f"Exception in _estimate_tokens: {type(e).__name__}: {str(e)}",
            extra={
                "function": "_estimate_tokens",
                "error_type": type(e).__name__,
                "text_length": len(text) if isinstance(text, str) else "N/A",
                "chars_per_token": chars_per_token
            },
            exc_info=True
        )
        return 0
    except Exception as e:
        logger.error(
            f"Unexpected exception in _estimate_tokens: {type(e).__name__}: {str(e)}",
            extra={"function": "_estimate_tokens"},
            exc_info=True
        )
        return 0


def _find_token_cut_point(
    text: str,
    max_tokens: int,
    chars_per_token: int,
    max_text_length: int = 1_000_000,
    max_iterations: int = 30
) -> int:
    """Binary search to find character position that fits token budget.

    PERFORMANCE OPTIMIZATION: Calculates tokens from length without creating
    substrings, reducing complexity from O(n*log n) to O(log n).

    Security measures:
    - Limits text length to prevent memory exhaustion
    - Limits iterations to prevent infinite loops
    - Validates inputs

    Args:
        text: String to find cut point for
        max_tokens: Maximum token count
        chars_per_token: Characters per token ratio
        max_text_length: Maximum text size to process (security limit)
        max_iterations: Maximum binary search iterations (security limit)

    Returns:
        Character index for truncation. Returns 0 if an error occurs.

    Note:
        All exceptions are caught and handled internally. On error, returns 0
        and logs the exception. Handles: ValueError, TypeError, MemoryError.
    """
    try:
        # Validate inputs
        if not isinstance(text, str):
            logger.error(f"Invalid text type in _find_token_cut_point: {type(text).__name__}")
            return 0

        if not text or max_tokens <= 0:
            return 0

        # SECURITY: Limit text length
        if len(text) > max_text_length:
            logger.warning(
                f"Text length {len(text)} exceeds maximum {max_text_length}, "
                f"truncating to safe length"
            )
            text = text[:max_text_length]

        # SECURITY: Prevent division by zero
        if chars_per_token <= 0:
            logger.error(f"Invalid chars_per_token: {chars_per_token}, using default 4")
            chars_per_token = 4

        logger.debug(
            f"Starting binary search: text_length={len(text)}, max_tokens={max_tokens}, "
            f"chars_per_token={chars_per_token}"
        )

        left, right = 0, min(len(text), max_tokens * chars_per_token + 100)
        best_cut = 0
        iterations = 0

        while left <= right and iterations < max_iterations:
            iterations += 1
            mid = (left + right) // 2

            # PERFORMANCE CRITICAL: Calculate tokens from length, not substring
            # Before: estimated_tokens = len(text[:mid]) // chars_per_token  # O(n) per iteration!
            # After:  estimated_tokens = mid // chars_per_token              # O(1) per iteration!
            estimated_tokens = mid // chars_per_token

            logger.debug(
                f"Binary search iteration {iterations}: left={left}, right={right}, "
                f"mid={mid}, estimated_tokens={estimated_tokens}"
            )

            if estimated_tokens <= max_tokens:
                best_cut = mid
                left = mid + 1
            else:
                right = mid - 1

        if iterations >= max_iterations:
            logger.warning(
                f"Binary search hit iteration limit ({max_iterations}), "
                f"using best cut point found: {best_cut}"
            )

        return best_cut

    except (ValueError, TypeError, MemoryError) as e:
        logger.error(
            f"Exception in _find_token_cut_point: {type(e).__name__}: {str(e)}",
            extra={
                "function": "_find_token_cut_point",
                "error_type": type(e).__name__,
                "text_length": len(text) if isinstance(text, str) else "N/A",
                "max_tokens": max_tokens,
                "chars_per_token": chars_per_token
            },
            exc_info=True
        )
        return 0
    except Exception as e:
        logger.error(
            f"Unexpected exception in _find_token_cut_point: {type(e).__name__}: {str(e)}",
            extra={"function": "_find_token_cut_point"},
            exc_info=True
        )
        return 0


def _find_word_boundary(value: str, cut: int, max_chars: int) -> int:
    """Find word boundary position without creating substrings.

    PERFORMANCE OPTIMIZATION: Returns position instead of creating substrings
    in the loop, reducing from O(n) substring creations to O(1).

    Args:
        value: String to search
        cut: Initial cut position
        max_chars: Maximum characters (for calculating search range)

    Returns:
        Position of word boundary, or cut if none found. Returns original cut
        position if an error occurs.

    Note:
        All exceptions are caught and handled internally. On error, returns
        original cut position and logs the exception. Handles: IndexError,
        TypeError, ValueError.
    """
    try:
        # Validate inputs
        if not isinstance(value, str):
            logger.error(f"Invalid value type in _find_word_boundary: {type(value).__name__}")
            return cut

        if not value or cut <= 0:
            return cut

        # Ensure cut is within bounds
        cut = min(cut, len(value))

        min_search = max(0, cut - int(max_chars * 0.2))

        # PERFORMANCE: Use module-level constant instead of creating set
        for i in range(cut - 1, min_search - 1, -1):
            if value[i] in BOUNDARY_CHARS:
                # Return position after the boundary character (includes the space/boundary in result)
                return i + 1

        return cut  # No boundary found

    except (IndexError, TypeError, ValueError) as e:
        logger.error(
            f"Exception in _find_word_boundary: {type(e).__name__}: {str(e)}",
            extra={
                "function": "_find_word_boundary",
                "error_type": type(e).__name__,
                "value_length": len(value) if isinstance(value, str) else "N/A",
                "cut": cut,
                "max_chars": max_chars
            },
            exc_info=True
        )
        return cut
    except Exception as e:
        logger.error(
            f"Unexpected exception in _find_word_boundary: {type(e).__name__}: {str(e)}",
            extra={"function": "_find_word_boundary"},
            exc_info=True
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
    max_iterations: int = 30,
    limit_mode: str = "character"
) -> str:
    """Truncate string to maximum length with ellipsis.

    Args:
        value: String to truncate.
        max_chars: Maximum number of characters. None means no limit.
        ellipsis: Ellipsis string to append.
        word_boundary: If True, truncate at word boundaries to avoid mid-word cuts.
        max_tokens: Maximum number of tokens. None means no token limit.
        chars_per_token: Characters per token ratio for estimation.
        max_text_length: Maximum text size to process (security limit).
        max_iterations: Maximum binary search iterations (security limit).
        limit_mode: "character" (character-based only) or "token" (token-based only).

    Returns:
        Truncated string, or original if within limits. Returns original string
        or empty string if an error occurs.

    Note:
        All exceptions are caught and handled internally. On error, returns
        original value (if string) or empty string, and logs the exception.
        Handles: IndexError, ValueError, TypeError, MemoryError.
    """
    try:
        # Validate inputs
        if not isinstance(value, str):
            logger.error(f"Invalid value type in _truncate: {type(value).__name__}")
            return str(value) if value is not None else ""

        ell = ellipsis or ""

        # Token-based truncation (only if limit_mode is "token" and max_tokens specified)
        # Treat 0 as None (disabled) - consistent with validator behavior
        if limit_mode == "token" and max_tokens is not None and max_tokens > 0:
            estimated_tokens = len(value) // chars_per_token

            if estimated_tokens > max_tokens:
                # Use binary search to find cut point
                cut = _find_token_cut_point(value, max_tokens, chars_per_token, max_text_length, max_iterations)

                # Apply word boundary if enabled
                if word_boundary and cut > 0:
                    original_cut = cut
                    cut = _find_word_boundary(value, cut, cut)

                    if cut != original_cut:
                        logger.debug(
                            f"Word boundary adjustment: original_cut={original_cut}, "
                            f"adjusted_cut={cut}, adjustment={original_cut - cut}"
                        )

                result = value[:cut] + ell

                return result

        # Character-based truncation (only if limit_mode is "character")
        if limit_mode != "character":
            return value

        # Treat 0 as None (disabled) - consistent with validator behavior
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

        # Calculate cut point
        cut = max_chars - ell_len

        # Word boundary truncation
        if word_boundary and cut > 0:
            cut = _find_word_boundary(value, cut, max_chars)

            result = value[:cut] + ell

            return result

        # Hard cut (no word boundary mode or no boundary found)
        return value[:cut] + ell

    except (IndexError, ValueError, TypeError, MemoryError) as e:
        logger.error(
            f"Exception in _truncate: {type(e).__name__}: {str(e)}",
            extra={
                "function": "_truncate",
                "error_type": type(e).__name__,
                "value_length": len(value) if isinstance(value, str) else "N/A",
                "max_chars": max_chars,
                "max_tokens": max_tokens,
                "limit_mode": limit_mode
            },
            exc_info=True
        )
        return value if isinstance(value, str) else ""
    except Exception as e:
        logger.error(
            f"Unexpected exception in _truncate: {type(e).__name__}: {str(e)}",
            extra={"function": "_truncate"},
            exc_info=True
        )
        return value if isinstance(value, str) else ""


def _is_numeric_string(text: str) -> bool:
    """Check if a string represents a numeric value.

    Handles integers, floats, and scientific notation.
    Examples: "123", "123.45", "1.23e-4", "5E+10"

    Args:
        text: String to check

    Returns:
        True if string is numeric, False otherwise
    """
    try:
        float(text)  # float() handles int, float, and scientific notation
        return True
    except ValueError:
        return False


def _process_structured_data(
    data: Any,
    min_chars: int,
    max_chars: Optional[int],
    ellipsis: str,
    strategy: str,
    word_boundary: bool,
    context: PluginContext,
    path: str = "",
    min_tokens: int = 0,
    max_tokens: Optional[int] = None,
    chars_per_token: int = 4,
    max_text_length: int = 1_000_000,
    max_structure_size: int = 10_000,
    max_recursion_depth: int = 100,
    max_binary_search_iterations: int = 20,
    limit_mode: str = "character"
) -> Tuple[Any, bool, Optional[PluginViolation]]:
    """Recursively process structured data, truncating or blocking based on strategy.

    This function traverses nested data structures (lists, dicts) and either truncates
    or blocks when string values exceed limits. Numeric strings (integers, floats,
    and scientific notation) are not truncated or blocked.

    Args:
        data: The data to process (can be str, list, dict, or nested structures).
        min_chars: Minimum allowed characters. 0 disables minimum check.
        max_chars: Maximum characters for string truncation/blocking. None disables max check.
        ellipsis: Ellipsis string to append when truncating.
        strategy: "truncate" or "block" - determines behavior when limits exceeded.
        word_boundary: If True, truncate at word boundaries to avoid mid-word cuts.
        context: Plugin context for logging.
        path: Current path in data structure (for error reporting).
        min_tokens: Minimum allowed tokens. 0 disables minimum token check.
        max_tokens: Maximum allowed tokens. None disables maximum token check.
        chars_per_token: Characters per token ratio for estimation.
        max_text_length: Maximum text length for security (prevents DoS).
        max_structure_size: Maximum structure size for security (prevents DoS).
        max_recursion_depth: Maximum recursion depth for security (prevents stack overflow).
        max_binary_search_iterations: Maximum binary search iterations for security.

    Returns:
        Tuple of (modified_data, was_modified, violation).
        - In block mode: returns violation if any string exceeds limits
        - In truncate mode: returns modified data with truncated strings
        Returns (original_data, False, None) if an error occurs.

    Note:
        All exceptions are caught and handled internally. On error, returns
        original data unchanged and logs the exception. Handles: RecursionError,
        MemoryError, TypeError, KeyError, AttributeError.
    """
    try:
        logger.debug(
            f"Processing structured data: type={type(data).__name__}, path={path or 'root'}, "
            f"strategy={strategy}"
        )

        # Security: Check recursion depth
        depth = path.count('.') + path.count('[')
        if depth > max_recursion_depth:
            logger.error(
                f"Recursion depth {depth} exceeds maximum {max_recursion_depth} at path: {path}"
            )
            return data, False, None

        # Base case: string - check if it's numeric, then process based on strategy
        if isinstance(data, str):
            # Skip processing for numeric strings (int, float, scientific notation)
            if _is_numeric_string(data):
                logger.debug(f"Skipping numeric string at {path or 'root'}: length={len(data)}")
                return data, False, None

            # PERFORMANCE: Calculate once, reuse
            length = len(data)
            token_count = length // chars_per_token  # Inline for speed

            # Check if string is out of bounds (character limits)
            below_min_chars = min_chars > 0 and length < min_chars
            above_max_chars = max_chars is not None and length > max_chars

            # Check if string is out of bounds (token limits)
            below_min_tokens = min_tokens > 0 and token_count < min_tokens
            above_max_tokens = max_tokens is not None and token_count > max_tokens

            if below_min_chars or above_max_chars or below_min_tokens or above_max_tokens:
                logger.debug(
                    f"String out of bounds at {path or 'root'}: length={length}, tokens={token_count}, "
                    f"char_limits=[{min_chars}, {max_chars}], token_limits=[{min_tokens}, {max_tokens}]"
                )

                # BLOCK MODE: Return violation immediately
                if strategy == "block":
                    location = f" at {path}" if path else ""

                    # Determine violation type
                    if above_max_tokens:
                        violation = PluginViolation(
                            reason=f"Token count out of bounds{location}",
                            description=f"Token count {token_count} exceeds max_tokens {max_tokens}{location}",
                            code="OUTPUT_TOKEN_VIOLATION",
                            details={
                                "token_count": token_count,
                                "max_tokens": max_tokens,
                                "chars_per_token": chars_per_token,
                                "strategy": strategy,
                                "location": path or "root",
                                "value_preview": data[:50] + "..." if len(data) > 50 else data
                            },
                            http_status_code=422,
                            mcp_error_code=-32000,
                        )
                        logger.warning(
                            f"Token limit violation detected, blocking output: location={path or 'root'}, "
                            f"token_count={token_count}, max_tokens={max_tokens}"
                        )
                    elif above_max_chars:
                        violation = PluginViolation(
                            reason=f"String length out of bounds{location}",
                            description=f"String length {length} exceeds max_chars {max_chars}{location}",
                            code="OUTPUT_LENGTH_VIOLATION",
                            details={
                                "length": length,
                                "max_chars": max_chars,
                                "strategy": strategy,
                                "location": path or "root",
                                "value_preview": data[:50] + "..." if len(data) > 50 else data
                            },
                            http_status_code=422,
                            mcp_error_code=-32000,
                        )
                        logger.debug(f"🚫 BLOCKING: String at {path or 'root'} exceeds char limits (length={length})")
                    else:
                        # Min violations
                        violation = PluginViolation(
                            reason=f"String length/tokens below minimum{location}",
                            description=f"String length {length} or tokens {token_count} below minimum{location}",
                            code="OUTPUT_LENGTH_VIOLATION",
                            details={
                                "length": length,
                                "min_chars": min_chars,
                                "token_count": token_count,
                                "min_tokens": min_tokens,
                                "location": path or "root"
                            },
                            http_status_code=422,
                            mcp_error_code=-32000,
                        )
                        logger.debug(f"🚫 BLOCKING: String at {path or 'root'} below minimum limits")

                    return data, False, violation

                # TRUNCATE MODE: Only truncate if above max
                if above_max_chars or above_max_tokens:
                    truncated = _truncate(
                        data, max_chars, ellipsis, word_boundary, max_tokens, chars_per_token,
                        max_text_length, max_binary_search_iterations, limit_mode
                    )
                    was_modified = truncated != data
                    return truncated, was_modified, None

            # Within bounds - return unchanged
            return data, False, None

        # Recursive case: list - process each element
        if isinstance(data, list):
            # Security: Check structure size
            if len(data) > max_structure_size:
                logger.warning(
                    f"List size {len(data)} exceeds maximum {max_structure_size} at path: {path}"
                )
                return data, False, None

            modified = False
            result = []
            for idx, item in enumerate(data):
                item_path = f"{path}[{idx}]" if path else f"[{idx}]"
                processed_item, item_modified, violation = _process_structured_data(
                    item, min_chars, max_chars, ellipsis, strategy, word_boundary, context, item_path,
                    min_tokens, max_tokens, chars_per_token,
                    max_text_length, max_structure_size, max_recursion_depth, max_binary_search_iterations,
                    limit_mode
                )

                # In block mode, return violation immediately
                if violation:
                    return data, False, violation

                result.append(processed_item)
                if item_modified:
                    modified = True
            return result, modified, None

        # Recursive case: dict - process each value
        if isinstance(data, dict):
            # Security: Check structure size
            if len(data) > max_structure_size:
                logger.warning(
                    f"Dict size {len(data)} exceeds maximum {max_structure_size} at path: {path}"
                )
                return data, False, None

            modified = False
            result = {}
            for key, value in data.items():
                value_path = f"{path}.{key}" if path else key
                processed_value, value_modified, violation = _process_structured_data(
                    value, min_chars, max_chars, ellipsis, strategy, word_boundary, context, value_path,
                    min_tokens, max_tokens, chars_per_token,
                    max_text_length, max_structure_size, max_recursion_depth, max_binary_search_iterations,
                    limit_mode
                )

                # In block mode, return violation immediately
                if violation:
                    return data, False, violation

                result[key] = processed_value
                if value_modified:
                    modified = True
            return result, modified, None

        # Other types (int, bool, None, etc.) - pass through unchanged
        return data, False, None

    except RecursionError as e:
        logger.error(
            f"RecursionError in _process_structured_data: {str(e)}",
            extra={
                "function": "_process_structured_data",
                "error_type": "RecursionError",
                "path": path,
                "data_type": type(data).__name__
            },
            exc_info=True
        )
        return data, False, None
    except (MemoryError, TypeError, KeyError, AttributeError) as e:
        logger.error(
            f"Exception in _process_structured_data: {type(e).__name__}: {str(e)}",
            extra={
                "function": "_process_structured_data",
                "error_type": type(e).__name__,
                "path": path,
                "data_type": type(data).__name__
            },
            exc_info=True
        )
        return data, False, None
    except Exception as e:
        logger.error(
            f"Unexpected exception in _process_structured_data: {type(e).__name__}: {str(e)}",
            extra={
                "function": "_process_structured_data",
                "path": path
            },
            exc_info=True
        )
        return data, False, None


def _generate_text_representation(data: Any) -> str:
    """Generate a formatted text representation of structured data.

    For single-key dicts (like {"result": [...]}), extracts and formats just the value.
    For simple strings, returns them directly without JSON encoding.
    Uses Python's json.dumps for clean, readable formatting of lists and dicts.
    Falls back to repr() for other types.

    Args:
        data: The data to represent as text.

    Returns:
        Formatted string representation. Returns error message string if
        representation fails.

    Note:
        All exceptions are caught and handled internally. On error, attempts
        fallback to repr(), then returns error message string. Handles:
        TypeError, ValueError, AttributeError, KeyError.
    """
    try:
        # Special case: simple string - return as-is without JSON encoding
        if isinstance(data, str):
            return data

        # Special case: single-key dict - extract the value for cleaner display
        if isinstance(data, dict) and len(data) == 1:
            # Get the single value (e.g., from {"result": [...]})
            value = next(iter(data.values()))
            # Recursively format the value
            return _generate_text_representation(value)

        # Use JSON for lists and dicts for clean formatting
        if isinstance(data, (list, dict)):
            return json.dumps(data, ensure_ascii=False, separators=(',', ':'))

        # For other types, use repr
        return repr(data)
    except (TypeError, ValueError, AttributeError, KeyError) as e:
        logger.error(
            f"Exception in _generate_text_representation: {type(e).__name__}: {str(e)}",
            extra={
                "function": "_generate_text_representation",
                "error_type": type(e).__name__,
                "data_type": type(data).__name__
            },
            exc_info=True
        )
        # Fallback to repr if JSON serialization fails
        try:
            return repr(data)
        except Exception:
            return "<unrepresentable data>"
    except Exception as e:
        logger.error(
            f"Unexpected exception in _generate_text_representation: {type(e).__name__}: {str(e)}",
            extra={"function": "_generate_text_representation"},
            exc_info=True
        )
        return "<error generating representation>"


class OutputLengthGuardPlugin(Plugin):
    """Guard tool outputs by length with block or truncate strategies."""

    def __init__(self, config: PluginConfig):
        """Initialize the output length guard plugin.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        self._cfg = OutputLengthGuardConfig(**(config.config or {}))

        # Log plugin initialization with configuration summary
        logger.info(
            f"OutputLengthGuard initialized: mode={self._cfg.limit_mode}, "
            f"strategy={self._cfg.strategy}, "
            f"char_limits=[{self._cfg.min_chars}, {self._cfg.max_chars}], "
            f"token_limits=[{self._cfg.min_tokens}, {self._cfg.max_tokens}], "
            f"word_boundary={self._cfg.word_boundary}"
        )

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:  # noqa: PLR0911
        """Guard tool output by length with block or truncate strategies.

        Args:
            payload: Tool invocation result payload.
            context: Plugin execution context.

        Returns:
            Result with length enforcement applied. On error, returns result
            that passes through original data with error metadata.

        Note:
            All exceptions are caught and handled internally. On error, passes
            through original result unchanged with error metadata, and logs the
            exception. Handles: TypeError, ValueError, AttributeError, KeyError.
        """
        try:
            cfg = self._cfg

            # Log hook invocation
            result_type = type(payload.result).__name__
            logger.info(f"OutputLengthGuard processing tool '{payload.name}' with result type: {result_type}")
            logger.debug(f"Tool '{payload.name}' config: mode={cfg.limit_mode}, strategy={cfg.strategy}, char_limits=[{cfg.min_chars}, {cfg.max_chars}]")

            # Helper to evaluate and possibly modify a single string
            def handle_text(text: str) -> tuple[str, dict[str, Any], Optional[PluginViolation]]:
                """Handle length guard for a single text string.

                Args:
                    text: Text to check and possibly modify.

                Returns:
                    Tuple of (modified_text, metadata, violation).
                """
                try:
                    # Validate input
                    if not isinstance(text, str):
                        logger.error(f"Invalid text type in handle_text: {type(text).__name__}")
                        return str(text) if text is not None else "", {"error": "invalid_type"}, None

                    # Check if text is numeric (int, float, scientific notation) - if so, don't truncate
                    if _is_numeric_string(text):
                        logger.debug(f"Preserving numeric string: length={len(text)}, value_preview={text[:50]}...")
                        meta = {"original_length": len(text), "numeric": True, "within_bounds": True}
                        return text, meta, None

                    length = _length(text)
                    meta: Dict[str, Any] = {"original_length": length}

                    # Use explicit comparison instead of falsy check
                    # When min_chars=0, we want to skip the minimum check (not treat 0 as False)
                    below_min = cfg.min_chars > 0 and length < cfg.min_chars
                    above_max = cfg.max_chars is not None and length > cfg.max_chars

                    if not (below_min or above_max):
                        logger.debug(f"Text within bounds: length={length}, limits=[{cfg.min_chars}, {cfg.max_chars}]")
                        meta.update({"within_bounds": True})
                        return text, meta, None

                    # Out of bounds
                    meta.update(
                        {
                            "within_bounds": False,
                            "min_chars": cfg.min_chars if cfg.min_chars > 0 else None,
                            "max_chars": cfg.max_chars,
                            "strategy": cfg.strategy,
                        }
                    )

                    if cfg.is_blocking():
                        logger.info(f"BLOCKING output: length={length}, limits=[{cfg.min_chars}, {cfg.max_chars}], below_min={below_min}, above_max={above_max}")
                        violation = PluginViolation(
                            reason="Output length out of bounds",
                            description=f"Result length {length} not in [{cfg.min_chars}, {cfg.max_chars}]",
                            code="OUTPUT_LENGTH_VIOLATION",
                            details={"length": length, "min": cfg.min_chars, "max": cfg.max_chars, "strategy": cfg.strategy},
                            http_status_code=422,  # Unprocessable Entity - content validation failed
                            mcp_error_code=-32000,  # Server error
                        )
                        return text, meta, violation

                    # Truncate strategy only handles over-length
                    if above_max and cfg.max_chars is not None:
                        logger.info(f"TRUNCATING output: original_length={length}, max_chars={cfg.max_chars}, mode={cfg.limit_mode}")
                        new_text = _truncate(
                            text, cfg.max_chars, cfg.ellipsis, cfg.word_boundary,
                            max_tokens=None, chars_per_token=cfg.chars_per_token,
                            max_text_length=cfg.max_text_length,
                            max_iterations=cfg.max_binary_search_iterations,
                            limit_mode=cfg.limit_mode
                        )
                        reduction_pct = round((1 - len(new_text) / length) * 100, 1) if length > 0 else 0
                        logger.info(f"Truncation complete: new_length={len(new_text)}, reduction={reduction_pct}%")
                        meta.update({"truncated": True, "new_length": len(new_text)})
                        return new_text, meta, None

                    # Under min with truncate: allow through, annotate only
                    logger.debug(f"Text below minimum but allowing through (truncate mode): length={length}, min={cfg.min_chars}")
                    meta.update({"truncated": False, "new_length": length})
                    return text, meta, None

                except (TypeError, ValueError, AttributeError) as e:
                    logger.error(
                        f"Exception in handle_text: {type(e).__name__}: {str(e)}",
                        extra={
                            "function": "handle_text",
                            "error_type": type(e).__name__,
                            "text_length": len(text) if isinstance(text, str) else "N/A"
                        },
                        exc_info=True
                    )
                    # Return original text with error metadata
                    return text if isinstance(text, str) else "", {"error": str(e)}, None
                except Exception as e:
                    logger.error(
                        f"Unexpected exception in handle_text: {type(e).__name__}: {str(e)}",
                        extra={"function": "handle_text"},
                        exc_info=True
                    )
                    return text if isinstance(text, str) else "", {"error": "unexpected_exception"}, None

            result = payload.result

            result = payload.result

            # Case 0: MCP CallToolResult as dict (from model_dump with 'content' key)
            # This is the most common case when tools return MCP-formatted results
            if isinstance(result, dict) and 'content' in result and isinstance(result.get('content'), list):
                # PRIORITY CHECK: Process structuredContent first if present
                struct_key = None
                struct_modified = False
                truncated_struct = None

                if 'structuredContent' in result:
                    struct_key = 'structuredContent'
                elif 'structured_content' in result:
                    struct_key = 'structured_content'

                if struct_key:

                    # Recursively process all strings in structured data (truncate or block)
                    truncated_struct, struct_modified, violation = _process_structured_data(
                        result[struct_key],
                        cfg.min_chars,
                        cfg.max_chars,
                        cfg.ellipsis,
                        cfg.strategy,
                        cfg.word_boundary,
                        context,
                        "",  # path
                        cfg.min_tokens,
                        cfg.max_tokens,
                        cfg.chars_per_token,
                        cfg.max_text_length,
                        cfg.max_structure_size,
                        cfg.max_recursion_depth,
                        cfg.max_binary_search_iterations,
                        cfg.limit_mode
                    )

                    # If blocking mode triggered a violation, return it immediately
                    if violation:
                        logger.debug(f"🚫 Blocking due to violation in {struct_key}")
                        return ToolPostInvokeResult(
                            continue_processing=False,
                            violation=violation,
                            metadata={
                                "structured_content_blocked": True,
                                "location": struct_key,
                                "min_tokens": cfg.min_tokens,
                                "max_tokens": cfg.max_tokens,
                                "chars_per_token": cfg.chars_per_token
                            }
                        )

                    if struct_modified:
                        # Create new result dict
                        new_result = dict(result)
                        new_result[struct_key] = truncated_struct

                        # Regenerate content[0].text from truncated structured data
                        # This content should NOT be truncated - it already contains
                        # the properly truncated strings from structuredContent processing
                        new_text = _generate_text_representation(truncated_struct)
                        new_result['content'] = [{"type": "text", "text": new_text}]

                        return ToolPostInvokeResult(
                            modified_payload=ToolPostInvokePayload(name=payload.name, result=new_result),
                            metadata={
                                "mcp_result_processed": True,
                                "items_modified": True,
                                "structured_content_processed": True,
                                "min_tokens": cfg.min_tokens,
                                "max_tokens": cfg.max_tokens,
                                "chars_per_token": cfg.chars_per_token
                            }
                        )
                    else:
                        return ToolPostInvokeResult(metadata={"mcp_result_processed": True, "items_modified": False, "structured_content_processed": False})

                # NO structuredContent: Process content array normally
                modified = False
                content_out: List[Any] = []

                for item in result['content']:
                    # Check if it's a text content dict (has type='text' and 'text' key)
                    if isinstance(item, dict) and item.get('type') == 'text' and 'text' in item:
                        current_text = item['text']
                        new_text, meta, violation = handle_text(current_text)

                        if violation:
                            return ToolPostInvokeResult(continue_processing=False, violation=violation, metadata=meta)

                        if new_text != current_text:
                            modified = True
                            # Create new dict with modified text, preserving other fields
                            new_item = dict(item)
                            new_item['text'] = new_text
                            content_out.append(new_item)

                            if hasattr(context, 'logger'):
                                context.logger.debug(
                                    f"OutputLengthGuard: Truncated text content from {len(current_text)} to {len(new_text)} chars"
                                )
                        else:
                            content_out.append(item)
                    else:
                        # Non-text content item (image, audio, etc.), pass through
                        content_out.append(item)

                if modified:
                    # Create new result dict with modified content
                    new_result = dict(result)
                    new_result['content'] = content_out

                    return ToolPostInvokeResult(
                        modified_payload=ToolPostInvokePayload(name=payload.name, result=new_result),
                        metadata={"mcp_result_processed": True, "items_modified": True, "structured_content_processed": False}
                    )
                return ToolPostInvokeResult(metadata={"mcp_result_processed": True, "items_modified": False})

            # Case 1: String result
            if isinstance(result, str):
                new_text, meta, violation = handle_text(result)
                if violation:
                    return ToolPostInvokeResult(continue_processing=False, violation=violation, metadata=meta)
                if new_text != result:
                    return ToolPostInvokeResult(modified_payload=ToolPostInvokePayload(name=payload.name, result=new_text), metadata=meta)
                return ToolPostInvokeResult(metadata=meta)

            # Case 2: Dict with text field
            if isinstance(result, dict):
                if isinstance(result.get("text"), str):
                    current = result["text"]
                    new_text, meta, violation = handle_text(current)
                    if violation:
                        return ToolPostInvokeResult(continue_processing=False, violation=violation, metadata=meta)
                    if new_text != current:
                        new_res = dict(result)
                        new_res["text"] = new_text
                        return ToolPostInvokeResult(modified_payload=ToolPostInvokePayload(name=payload.name, result=new_res), metadata=meta)
                    return ToolPostInvokeResult(metadata=meta)
                else:
                    # Dict without "text" field - pass through unchanged
                    if hasattr(context, 'logger'):
                        context.logger.debug(
                            f"OutputLengthGuard: Dict result from tool '{payload.name}' has no 'text' field, passing through unchanged"
                        )
                    return ToolPostInvokeResult(continue_processing=True)

            # Case 3: MCP content array format: [{"type": "text", "text": "..."}]
            if isinstance(result, list) and len(result) > 0 and isinstance(result[0], dict) and "type" in result[0]:
                # MCP format - process text content items
                modified = False
                mcp_out: List[Any] = []

                for item in result:
                    if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                        current_text = item["text"]
                        new_text, meta, violation = handle_text(current_text)

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
                        # Non-text content item, pass through
                        mcp_out.append(item)

                if modified:
                    return ToolPostInvokeResult(
                        modified_payload=ToolPostInvokePayload(name=payload.name, result=mcp_out),
                        metadata={"mcp_content_processed": True}
                    )
                return ToolPostInvokeResult(metadata={"mcp_content_processed": True})

            # Case 4: List of strings
            if isinstance(result, list) and all(isinstance(x, str) for x in result):
                texts: List[str] = result
                modified = False
                meta_list: List[dict[str, Any]] = []
                str_list_out: List[str] = []

                # Cache blocking mode for early exit optimization
                is_blocking = cfg.is_blocking()

                # Add logging to track list processing
                if hasattr(context, 'logger'):
                    context.logger.debug(
                        f"OutputLengthGuard: Processing list of {len(texts)} strings from tool '{payload.name}'"
                    )

                for idx, t in enumerate(texts):
                    new_t, m, violation = handle_text(t)
                    meta_list.append(m)

                    if violation:
                        # Early exit in block mode for performance
                        if is_blocking and hasattr(context, 'logger'):
                            context.logger.debug(
                                f"OutputLengthGuard: Blocking at list index {idx}/{len(texts)}"
                            )
                        return ToolPostInvokeResult(
                            continue_processing=False,
                            violation=violation,
                            metadata={"items": meta_list, "violation_index": idx, "total_items": len(texts)}
                        )

                    if new_t != t:
                        modified = True
                        # Log individual truncations
                        if hasattr(context, 'logger'):
                            context.logger.debug(
                                f"OutputLengthGuard: Truncated list item {idx} from {len(t)} to {len(new_t)} chars"
                            )

                    str_list_out.append(new_t)

                if modified:
                    return ToolPostInvokeResult(
                        modified_payload=ToolPostInvokePayload(name=payload.name, result=str_list_out),
                        metadata={"items": meta_list}
                    )
                return ToolPostInvokeResult(metadata={"items": meta_list})

            # Log unsupported result types for observability
            result_type = type(result).__name__
            if hasattr(context, 'logger'):
                context.logger.debug(
                    f"OutputLengthGuard: Unsupported result type '{result_type}' from tool '{payload.name}', passing through unchanged"
                )
            return ToolPostInvokeResult(
                continue_processing=True,
                metadata={"skipped": True, "reason": f"unsupported_type_{result_type}"}
            )

        except (TypeError, ValueError, AttributeError, KeyError) as e:
            logger.error(
                f"Exception in tool_post_invoke: {type(e).__name__}: {str(e)}",
                extra={
                    "function": "tool_post_invoke",
                    "error_type": type(e).__name__,
                    "tool_name": payload.name,
                    "result_type": type(payload.result).__name__
                },
                exc_info=True
            )
            # Pass through original result on error
            return ToolPostInvokeResult(
                continue_processing=True,
                metadata={"error": str(e), "error_type": type(e).__name__}
            )
        except Exception as e:
            logger.error(
                f"Unexpected exception in tool_post_invoke: {type(e).__name__}: {str(e)}",
                extra={
                    "function": "tool_post_invoke",
                    "tool_name": payload.name
                },
                exc_info=True
            )
            # Pass through original result on unexpected error
            return ToolPostInvokeResult(
                continue_processing=True,
                metadata={"error": "unexpected_exception", "error_type": type(e).__name__}
            )
