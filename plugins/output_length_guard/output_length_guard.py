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
from typing import Any, ClassVar, List, Optional, Tuple
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

    min_chars: int = Field(default=0, ge=0, description="Minimum allowed characters. 0 disables minimum check.")
    max_chars: Optional[int] = Field(default=None, description="Maximum allowed characters. None disables maximum check.")
    strategy: str = Field(default="truncate", description='Strategy when out of bounds: "truncate" or "block"')
    ellipsis: str = Field(default="…", description="Suffix appended on truncation. Use empty string to disable.")

    @field_validator('strategy')
    @classmethod
    def validate_strategy(cls, v: str) -> str:
        
        logging.debug(f"Validating strategy: {v}")
        """Validate strategy is one of the allowed values.

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
        """Validate max_chars is positive when set.

        Args:
            v: Maximum characters value.

        Returns:
            Validated max_chars value.

        Raises:
            ValueError: If max_chars is set but not positive.
        """
        if v is not None and v < 1:
            raise ValueError("max_chars must be >= 1 when set, or None to disable")
        return v

    @model_validator(mode='after')
    def validate_min_max_relationship(self) -> 'OutputLengthGuardConfig':
        """Ensure min_chars <= max_chars when both are set.

        Returns:
            Validated config instance.

        Raises:
            ValueError: If min_chars > max_chars.
        """
        if self.max_chars is not None and self.min_chars > self.max_chars:
            raise ValueError(
                f"min_chars ({self.min_chars}) cannot be greater than max_chars ({self.max_chars})"
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


def _truncate(value: str, max_chars: Optional[int], ellipsis: str) -> str:
    """Truncate string to maximum length with ellipsis.

    BUG FIX #5: Handle max_chars=None correctly to disable truncation.
    BUG FIX #7: Optimize for large strings by caching length and using early returns.

    Args:
        value: String to truncate.
        max_chars: Maximum number of characters. None means no limit.
        ellipsis: Ellipsis string to append.

    Returns:
        Truncated string, or original if max_chars is None or within limits.
    """
    # BUG FIX #5: Early return if no max limit (None disables truncation)
    if max_chars is None:
        return value

    if max_chars <= 0:
        return ""

    # BUG FIX #7: Cache length for performance with large strings
    value_len = len(value)
    if value_len <= max_chars:
        return value

    # Truncation needed
    ell = ellipsis or ""
    ell_len = len(ell)

    # If ellipsis doesn't fit, hard cut
    if ell_len >= max_chars:
        return value[:max_chars]

    # Calculate cut point and slice once (optimization)
    cut = max_chars - ell_len
    return value[:cut] + ell


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
    context: PluginContext,
    path: str = ""
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
        context: Plugin context for logging.
        path: Current path in data structure (for error reporting).
    
    Returns:
        Tuple of (modified_data, was_modified, violation).
        - In block mode: returns violation if any string exceeds limits
        - In truncate mode: returns modified data with truncated strings
    """
    # Base case: string - check if it's numeric, then process based on strategy
    if isinstance(data, str):
        # Skip processing for numeric strings (int, float, scientific notation)
        if _is_numeric_string(data):
            logger.info(f"🔄 Skipping numeric string: '{data}'")
            return data, False, None
        
        length = len(data)
        
        # Check if string is out of bounds
        below_min = min_chars > 0 and length < min_chars
        above_max = max_chars is not None and length > max_chars
        
        if below_min or above_max:
            # BLOCK MODE: Return violation immediately
            if strategy == "block":
                location = f" at {path}" if path else ""
                violation = PluginViolation(
                    reason=f"String length out of bounds{location}",
                    description=f"String length {length} not in [{min_chars}, {max_chars}]{location}",
                    code="OUTPUT_LENGTH_VIOLATION",
                    details={
                        "length": length,
                        "min": min_chars,
                        "max": max_chars,
                        "strategy": strategy,
                        "location": path or "root",
                        "value_preview": data[:50] + "..." if len(data) > 50 else data
                    },
                    http_status_code=422,
                    mcp_error_code=-32000,
                )
                logger.info(f"🚫 BLOCKING: String at {path or 'root'} exceeds limits (length={length})")
                return data, False, violation
            
            # TRUNCATE MODE: Only truncate if above max
            if above_max and max_chars is not None:
                truncated = _truncate(data, max_chars, ellipsis)
                was_modified = truncated != data
                if was_modified:
                    logger.info(f"🔄 Truncated string at {path or 'root'}: '{data[:30]}...' -> '{truncated}'")
                return truncated, was_modified, None
        
        # Within bounds - return unchanged
        return data, False, None
    
    # Recursive case: list - process each element
    if isinstance(data, list):
        modified = False
        result = []
        for idx, item in enumerate(data):
            item_path = f"{path}[{idx}]" if path else f"[{idx}]"
            processed_item, item_modified, violation = _process_structured_data(
                item, min_chars, max_chars, ellipsis, strategy, context, item_path
            )
            
            # In block mode, return violation immediately
            if violation:
                return data, False, violation
            
            result.append(processed_item)
            if item_modified:
                modified = True
                logger.info(f"🔄 Modified list item at index {idx}")
        return result, modified, None
    
    # Recursive case: dict - process each value
    if isinstance(data, dict):
        modified = False
        result = {}
        for key, value in data.items():
            value_path = f"{path}.{key}" if path else key
            processed_value, value_modified, violation = _process_structured_data(
                value, min_chars, max_chars, ellipsis, strategy, context, value_path
            )
            
            # In block mode, return violation immediately
            if violation:
                return data, False, violation
            
            result[key] = processed_value
            if value_modified:
                modified = True
                logger.info(f"🔄 Modified dict value for key '{key}'")
        return result, modified, None
    
    # Other types (int, bool, None, etc.) - pass through unchanged
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
        Formatted string representation.
    """
    try:
        # Special case: simple string - return as-is without JSON encoding
        if isinstance(data, str):
            return data
        
        # Special case: single-key dict - extract the value for cleaner display
        if isinstance(data, dict) and len(data) == 1:
            # Get the single value (e.g., from {"result": [...]})
            value = next(iter(data.values()))
            logger.info(f"🔄 Extracting single dict value for content display")
            # Recursively format the value
            return _generate_text_representation(value)
        
        # Use JSON for lists and dicts for clean formatting
        if isinstance(data, (list, dict)):
            return json.dumps(data, ensure_ascii=False, separators=(',', ':'))
        
        # For other types, use repr
        return repr(data)
    except (TypeError, ValueError):
        # Fallback to repr if JSON serialization fails
        return repr(data)


class OutputLengthGuardPlugin(Plugin):
    """Guard tool outputs by length with block or truncate strategies."""

    def __init__(self, config: PluginConfig):
        """Initialize the output length guard plugin.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        self._cfg = OutputLengthGuardConfig(**(config.config or {}))

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        """Guard tool output by length with block or truncate strategies.

        Args:
            payload: Tool invocation result payload.
            context: Plugin execution context.

        Returns:
            Result with length enforcement applied.
        """
        # CRITICAL DEBUG LOG - This should appear if method is called
        logger.info(f"🎯 OutputLengthGuard.tool_post_invoke CALLED for tool '{payload.name}'")
        logger.info(f"🎯 Plugin config: max_chars={self._cfg.max_chars}, min_chars={self._cfg.min_chars}, strategy={self._cfg.strategy}")
        
        cfg = self._cfg

        # Helper to evaluate and possibly modify a single string
        def handle_text(text: str) -> tuple[str, dict[str, Any], Optional[PluginViolation]]:
            """Handle length guard for a single text string.

            Args:
                text: Text to check and possibly modify.

            Returns:
                Tuple of (modified_text, metadata, violation).
            """
            # Check if text is numeric (int, float, scientific notation) - if so, don't truncate
            if _is_numeric_string(text):
                logger.info(f"🎯 handle_text: Skipping numeric string: '{text}'")
                meta = {"original_length": len(text), "numeric": True, "within_bounds": True}
                return text, meta, None
            
            length = _length(text)
            meta = {"original_length": length}

            # BUG FIX #1: Use explicit comparison instead of falsy check
            # When min_chars=0, we want to skip the minimum check (not treat 0 as False)
            below_min = cfg.min_chars > 0 and length < cfg.min_chars
            above_max = cfg.max_chars is not None and length > cfg.max_chars
            
            logger.info(f"🎯 handle_text: text='{text[:50]}...', length={length}, min_chars={cfg.min_chars}, max_chars={cfg.max_chars}")
            logger.info(f"🎯 handle_text: below_min={below_min}, above_max={above_max}")
            
            if not (below_min or above_max):
                logger.info(f"🎯 handle_text: Within bounds, returning unchanged")
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
            logger.info(f"🎯 handle_text: Checking truncation condition - above_max={above_max}, cfg.max_chars={cfg.max_chars}")
            if above_max and cfg.max_chars is not None:
                logger.info(f"🎯 handle_text: TRUNCATING text from {length} to {cfg.max_chars} chars")
                new_text = _truncate(text, cfg.max_chars, cfg.ellipsis)
                logger.info(f"🎯 handle_text: Truncated result: '{new_text}' (length={len(new_text)})")
                meta.update({"truncated": True, "new_length": len(new_text)})
                return new_text, meta, None

            # Under min with truncate: allow through, annotate only
            logger.info(f"🎯 handle_text: NOT truncating, returning original text")
            meta.update({"truncated": False, "new_length": length})
            return text, meta, None

        result = payload.result
        
        # Debug: Log what we received
        logger.info(
            f"🎯 OutputLengthGuard: Received result type: {type(result).__name__}, "
            f"is_dict: {isinstance(result, dict)}, "
            f"has_content: {'content' in result if isinstance(result, dict) else 'N/A'}"
        )
        if isinstance(result, dict):
            logger.info(f"🎯 OutputLengthGuard: Result keys: {list(result.keys())}")
            if 'content' in result:
                logger.info(f"🎯 OutputLengthGuard: Content type: {type(result['content'])}, length: {len(result['content']) if isinstance(result['content'], list) else 'N/A'}")
                if isinstance(result['content'], list) and len(result['content']) > 0:
                    logger.info(f"🎯 OutputLengthGuard: First content item: {result['content'][0]}")

        # Case 0: MCP CallToolResult as dict (from model_dump with 'content' key)
        # This is the most common case when tools return MCP-formatted results
        if isinstance(result, dict) and 'content' in result and isinstance(result.get('content'), list):
            logger.info(
                f"🎯 OutputLengthGuard: ✓ MATCHED Case 0 - Processing MCP result dict with {len(result['content'])} content items from tool '{payload.name}'"
            )
            
            # PRIORITY CHECK: Process structuredContent first if present
            struct_key = None
            struct_modified = False
            truncated_struct = None
            
            if 'structuredContent' in result:
                struct_key = 'structuredContent'
            elif 'structured_content' in result:
                struct_key = 'structured_content'
            
            if struct_key:
                logger.info(f"🎯 Processing {struct_key} field FIRST (will skip content processing)")
                
                # Recursively process all strings in structured data (truncate or block)
                truncated_struct, struct_modified, violation = _process_structured_data(
                    result[struct_key],
                    cfg.min_chars,
                    cfg.max_chars,
                    cfg.ellipsis,
                    cfg.strategy,
                    context
                )
                
                # If blocking mode triggered a violation, return it immediately
                if violation:
                    logger.info(f"🚫 Blocking due to violation in {struct_key}")
                    return ToolPostInvokeResult(
                        continue_processing=False,
                        violation=violation,
                        metadata={"structured_content_blocked": True, "location": struct_key}
                    )
                
                if struct_modified:
                    logger.info(f"🎯 {struct_key} was modified, regenerating content text")
                    # Create new result dict
                    new_result = dict(result)
                    new_result[struct_key] = truncated_struct
                    
                    # Regenerate content[0].text from truncated structured data
                    # This content should NOT be truncated - it already contains
                    # the properly truncated strings from structuredContent processing
                    new_text = _generate_text_representation(truncated_struct)
                    new_result['content'] = [{"type": "text", "text": new_text}]
                    
                    logger.info(f"🎯 Updated content text from structuredContent: '{new_text[:100]}...'")
                    
                    return ToolPostInvokeResult(
                        modified_payload=ToolPostInvokePayload(name=payload.name, result=new_result),
                        metadata={"mcp_result_processed": True, "items_modified": True, "structured_content_processed": True}
                    )
                else:
                    logger.info(f"🎯 {struct_key} was not modified, no changes needed")
                    return ToolPostInvokeResult(metadata={"mcp_result_processed": True, "items_modified": False, "structured_content_processed": False})
            
            # NO structuredContent: Process content array normally
            logger.info("🎯 No structuredContent found, processing content array")
            modified = False
            out = []
            
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
                        out.append(new_item)
                        
                        if hasattr(context, 'logger'):
                            context.logger.debug(
                                f"OutputLengthGuard: Truncated text content from {len(current_text)} to {len(new_text)} chars"
                            )
                    else:
                        out.append(item)
                else:
                    # Non-text content item (image, audio, etc.), pass through
                    out.append(item)
            
            if modified:
                # Create new result dict with modified content
                new_result = dict(result)
                new_result['content'] = out
                
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
                # BUG FIX #2: Dict without "text" field - pass through unchanged
                if hasattr(context, 'logger'):
                    context.logger.debug(
                        f"OutputLengthGuard: Dict result from tool '{payload.name}' has no 'text' field, passing through unchanged"
                    )
                return ToolPostInvokeResult(continue_processing=True)

        # Case 3: MCP content array format: [{"type": "text", "text": "..."}]
        if isinstance(result, list) and len(result) > 0 and isinstance(result[0], dict) and "type" in result[0]:
            # MCP format - process text content items
            modified = False
            out = []
            
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
                        out.append(new_item)
                    else:
                        out.append(item)
                else:
                    # Non-text content item, pass through
                    out.append(item)
            
            if modified:
                return ToolPostInvokeResult(
                    modified_payload=ToolPostInvokePayload(name=payload.name, result=out),
                    metadata={"mcp_content_processed": True}
                )
            return ToolPostInvokeResult(metadata={"mcp_content_processed": True})
        
        # Case 4: List of strings
        if isinstance(result, list) and all(isinstance(x, str) for x in result):
            texts: List[str] = result
            modified = False
            meta_list: List[dict[str, Any]] = []
            out: List[str] = []

            # BUG FIX #8: Cache blocking mode for early exit optimization
            is_blocking = cfg.is_blocking()

            # BUG FIX #3: Add logging to track list processing
            if hasattr(context, 'logger'):
                context.logger.debug(
                    f"OutputLengthGuard: Processing list of {len(texts)} strings from tool '{payload.name}'"
                )

            for idx, t in enumerate(texts):
                new_t, m, violation = handle_text(t)
                meta_list.append(m)

                if violation:
                    # BUG FIX #8: Early exit in block mode for performance
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
                    # BUG FIX #3: Log individual truncations
                    if hasattr(context, 'logger'):
                        context.logger.debug(
                            f"OutputLengthGuard: Truncated list item {idx} from {len(t)} to {len(new_t)} chars"
                        )

                out.append(new_t)

            if modified:
                return ToolPostInvokeResult(
                    modified_payload=ToolPostInvokePayload(name=payload.name, result=out),
                    metadata={"items": meta_list}
                )
            return ToolPostInvokeResult(metadata={"items": meta_list})

        # BUG FIX #6: Log unsupported result types for observability
        result_type = type(result).__name__
        if hasattr(context, 'logger'):
            context.logger.debug(
                f"OutputLengthGuard: Unsupported result type '{result_type}' from tool '{payload.name}', passing through unchanged"
            )
        return ToolPostInvokeResult(
            continue_processing=True,
            metadata={"skipped": True, "reason": f"unsupported_type_{result_type}"}
        )
