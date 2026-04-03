# -*- coding: utf-8 -*-
"""Output Length Guard configuration and policy.

Location: ./plugins/output_length_guard/config.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti
"""

# Future
from __future__ import annotations

# Standard
from dataclasses import dataclass
from typing import ClassVar, Optional

# Third-Party
from pydantic import BaseModel, Field, field_validator, model_validator


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
    ellipsis: str = Field(default="\u2026", description="Suffix appended on truncation. Use empty string to disable.")
    word_boundary: bool = Field(default=False, description="When true, truncate at word boundaries to avoid mid-word cuts.")

    # Security limits
    max_text_length: int = Field(default=1_000_000, description="Maximum text size to process (1MB default). Prevents memory exhaustion.")
    max_structure_size: int = Field(default=10_000, description="Maximum items in list/dict (10K default). Prevents DoS attacks.")
    max_recursion_depth: int = Field(default=100, description="Maximum nesting depth (100 default). Prevents stack overflow.")

    @field_validator("limit_mode")
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
            raise ValueError(f"Invalid limit_mode '{v}'. Must be one of: {', '.join(sorted(cls.ALLOWED_LIMIT_MODES))}")
        return normalized

    @field_validator("strategy")
    @classmethod
    def validate_strategy(cls, v: str) -> str:
        """Validate strategy is one of the allowed values.

        Args:
            v: Strategy value to validate.

        Returns:
            Validated strategy value (lowercase).

        Raises:
            ValueError: If strategy is not in ALLOWED_STRATEGIES.
        """
        normalized = v.lower().strip()
        if normalized not in cls.ALLOWED_STRATEGIES:
            raise ValueError(f"Invalid strategy '{v}'. Must be one of: {', '.join(sorted(cls.ALLOWED_STRATEGIES))}")
        return normalized

    @field_validator("max_chars")
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

    @field_validator("max_tokens")
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

    @field_validator("chars_per_token")
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

    @field_validator("max_text_length")
    @classmethod
    def validate_max_text_length(cls, v: int) -> int:
        """Validate max_text_length is in reasonable range.

        Args:
            v: Maximum text length value.

        Returns:
            Validated max_text_length value.

        Raises:
            ValueError: If max_text_length is not in range 1 KB to 10 MB.
        """
        if v < 1000 or v > 10_000_000:
            raise ValueError("max_text_length must be between 1000 (1KB) and 10000000 (10MB)")
        return v

    @field_validator("max_structure_size")
    @classmethod
    def validate_max_structure_size(cls, v: int) -> int:
        """Validate max_structure_size is in reasonable range.

        Args:
            v: Maximum structure size value.

        Returns:
            Validated max_structure_size value.

        Raises:
            ValueError: If max_structure_size is not in range 10 to 100 K.
        """
        if v < 10 or v > 100_000:
            raise ValueError("max_structure_size must be between 10 and 100000")
        return v

    @field_validator("max_recursion_depth")
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

    @model_validator(mode="after")
    def validate_min_max_relationship(self) -> "OutputLengthGuardConfig":
        """Ensure min_chars <= max_chars and min_tokens <= max_tokens when both are set.

        Returns:
            Validated config instance.

        Raises:
            ValueError: If min_chars > max_chars or min_tokens > max_tokens.
        """
        if self.max_chars is not None and self.min_chars > self.max_chars:
            raise ValueError(f"min_chars ({self.min_chars}) cannot be greater than max_chars ({self.max_chars})")
        if self.max_tokens is not None and self.min_tokens > self.max_tokens:
            raise ValueError(f"min_tokens ({self.min_tokens}) cannot be greater than max_tokens ({self.max_tokens})")
        return self

    def is_blocking(self) -> bool:
        """Check if strategy is set to blocking mode.

        Returns:
            True if strategy is block.
        """
        return self.strategy == "block"  # Already normalized by validator

    def to_policy(self) -> LengthGuardPolicy:
        """Create an immutable policy object from this config.

        Returns:
            LengthGuardPolicy with all enforcement parameters.
        """
        return LengthGuardPolicy(
            min_chars=self.min_chars,
            max_chars=self.max_chars,
            min_tokens=self.min_tokens,
            max_tokens=self.max_tokens,
            chars_per_token=self.chars_per_token,
            limit_mode=self.limit_mode,
            strategy=self.strategy,
            ellipsis=self.ellipsis,
            word_boundary=self.word_boundary,
            max_text_length=self.max_text_length,
            max_structure_size=self.max_structure_size,
            max_recursion_depth=self.max_recursion_depth,
        )


@dataclass(frozen=True)
class LengthGuardPolicy:
    """Immutable policy object for limit enforcement parameters.

    Consolidates all enforcement settings into a single object
    to avoid long parameter lists in recursive functions.
    """

    min_chars: int = 0
    max_chars: Optional[int] = None
    min_tokens: int = 0
    max_tokens: Optional[int] = None
    chars_per_token: int = 4
    limit_mode: str = "character"
    strategy: str = "truncate"
    ellipsis: str = "\u2026"
    word_boundary: bool = False
    max_text_length: int = 1_000_000
    max_structure_size: int = 10_000
    max_recursion_depth: int = 100
