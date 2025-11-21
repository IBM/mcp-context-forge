# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/routing/field_selector.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Field Selection and Scoping.
Extracts specific fields from payloads for plugin processing using dot notation
and JSONPath-like syntax, then merges processed fields back into the original payload.

Supports:
- Dot notation: args.user_query, result.customer.ssn
- Array indexing: args.customers[0].email
- Wildcard arrays: args.customers[*].email (all email fields in array)
- Wildcard dicts: args.metadata.*.value (all values in dict)
"""

# Standard
import logging
import re
from typing import Any, Optional

# First-Party
from mcpgateway.plugins.framework.models import FieldSelection

logger = logging.getLogger(__name__)


class FieldSelector:
    """Extracts and merges specific fields from/to payloads.

    All methods are static - no need to instantiate this class.

    Examples:
        >>> # Simple field extraction
        >>> payload = {"args": {"query": "test", "limit": 10}}
        >>> extracted = FieldSelector.extract_fields(payload, ["args.query"])
        >>> extracted
        {'args': {'query': 'test'}}

        >>> # Nested field extraction
        >>> payload2 = {
        ...     "args": {
        ...         "filters": {
        ...             "email": "john@example.com",
        ...             "phone": "555-1234"
        ...         },
        ...         "limit": 10
        ...     }
        ... }
        >>> extracted2 = FieldSelector.extract_fields(
        ...     payload2,
        ...     ["args.filters.email", "args.filters.phone"]
        ... )
        >>> extracted2
        {'args': {'filters': {'email': 'john@example.com', 'phone': '555-1234'}}}

        >>> # Array wildcard extraction
        >>> payload3 = {
        ...     "args": {
        ...         "customers": [
        ...             {"name": "Alice", "email": "alice@example.com"},
        ...             {"name": "Bob", "email": "bob@example.com"}
        ...         ]
        ...     }
        ... }
        >>> extracted3 = FieldSelector.extract_fields(
        ...     payload3,
        ...     ["args.customers[*].email"]
        ... )
        >>> extracted3
        {'args': {'customers': [{'email': 'alice@example.com'}, {'email': 'bob@example.com'}]}}

        >>> # Merge processed fields back
        >>> original = {"args": {"query": "sensitive", "limit": 10}}
        >>> processed = {"args": {"query": "[REDACTED]"}}
        >>> merged = FieldSelector.merge_fields(original, processed, ["args.query"])
        >>> merged
        {'args': {'query': '[REDACTED]', 'limit': 10}}

        >>> # Multiple field extraction
        >>> payload4 = {
        ...     "name": "my_tool",
        ...     "args": {"user_query": "test", "email": "user@example.com", "limit": 5}
        ... }
        >>> extracted4 = FieldSelector.extract_fields(
        ...     payload4,
        ...     ["args.user_query", "args.email"]
        ... )
        >>> extracted4
        {'args': {'user_query': 'test', 'email': 'user@example.com'}}
    """

    @staticmethod
    def extract_fields(payload: dict[str, Any], field_paths: list[str]) -> dict[str, Any]:
        """Extract specific fields from payload.

        Args:
            payload: The full payload dict.
            field_paths: List of dot-notation field paths to extract.

        Returns:
            New dict containing only the specified fields.

        Examples:
            >>> payload = {"args": {"a": 1, "b": 2}, "name": "test"}
            >>> FieldSelector.extract_fields(payload, ["args.a"])
            {'args': {'a': 1}}
        """
        result: dict[str, Any] = {}

        for path in field_paths:
            FieldSelector._extract_path(payload, path, result)

        return result

    @staticmethod
    def merge_fields(
        original: dict[str, Any],
        processed: dict[str, Any],
        field_paths: list[str],
    ) -> dict[str, Any]:
        """Merge processed fields back into original payload.

        Args:
            original: Original payload dict.
            processed: Processed payload dict (only contains specified fields).
            field_paths: List of field paths that were processed.

        Returns:
            New dict with processed fields merged back into original.

        Examples:
            >>> original = {"args": {"query": "test", "limit": 10}}
            >>> processed = {"args": {"query": "REDACTED"}}
            >>> FieldSelector.merge_fields(original, processed, ["args.query"])
            {'args': {'query': 'REDACTED', 'limit': 10}}
        """
        # Start with a deep copy of original
        # Standard
        import copy

        result = copy.deepcopy(original)

        # Merge processed fields back
        for path in field_paths:
            FieldSelector._merge_path(result, processed, path)

        return result

    @staticmethod
    def apply_field_selection(
        payload: dict[str, Any],
        field_selection: Optional[FieldSelection],
        is_input: bool = True,
    ) -> tuple[dict[str, Any], Optional[list[str]]]:
        """Apply field selection to payload.

        Args:
            payload: The payload to filter.
            field_selection: Field selection configuration.
            is_input: True for input (pre-hook), False for output (post-hook).

        Returns:
            Tuple of (filtered_payload, field_paths_used).
            If no field selection, returns (original_payload, None).

        Examples:
            >>> from mcpgateway.plugins.framework.models import FieldSelection
            >>> fs = FieldSelection(input_fields=["args.query"])
            >>> payload = {"args": {"query": "test", "limit": 10}}
            >>> filtered, paths = FieldSelector.apply_field_selection(payload, fs, is_input=True)
            >>> filtered
            {'args': {'query': 'test'}}
            >>> paths
            ['args.query']
        """
        if field_selection is None:
            return payload, None

        # Determine which field list to use
        if is_input:
            # For input (pre-hook): use input_fields if specified, else fields
            field_paths = field_selection.input_fields or field_selection.fields
        else:
            # For output (post-hook): use output_fields if specified, else fields
            field_paths = field_selection.output_fields or field_selection.fields

        # If no fields specified, return original payload
        if not field_paths:
            return payload, None

        # Extract specified fields
        filtered = FieldSelector.extract_fields(payload, field_paths)
        return filtered, field_paths

    @staticmethod
    def _extract_path(source: dict[str, Any], path: str, result: dict[str, Any]):
        """Extract a single path from source into result.

        Handles dot notation, array indexing, and wildcards.
        """
        parts = FieldSelector._parse_path(path)
        FieldSelector._extract_parts(source, parts, result, parts)

    @staticmethod
    def _extract_parts(
        source: Any,
        parts: list[str],
        result: Any,
        full_parts: list[str],
        current_depth: int = 0,
    ):
        """Recursively extract parts from source into result."""
        if current_depth >= len(parts):
            return

        part = parts[current_depth]
        is_last = current_depth == len(parts) - 1

        # Handle array wildcard: [*]
        match = re.match(r"^(.+)\[\*\]$", part)
        if match:
            key = match.group(1)
            if isinstance(source, dict) and key in source:
                if isinstance(source[key], list):
                    # Create array in result if not exists
                    if not isinstance(result, dict):
                        return
                    if key not in result:
                        result[key] = []
                    # Process each array element
                    for item in source[key]:
                        if is_last:
                            # Last part: copy entire item
                            result[key].append(item if not isinstance(item, dict) else {})
                        else:
                            # More parts: recurse into each item
                            result_item = {}
                            result[key].append(result_item)
                            FieldSelector._extract_parts(item, parts, result_item, full_parts, current_depth + 1)
            return

        # Handle array index: [0], [1], etc.
        match2 = re.match(r"^(.+)\[(\d+)\]$", part)
        if match2:
            key = match2.group(1)
            index = int(match2.group(2))
            if isinstance(source, dict) and key in source:
                if isinstance(source[key], list) and len(source[key]) > index:
                    if not isinstance(result, dict):
                        return
                    if key not in result:
                        result[key] = []
                    # Pad array if needed
                    while len(result[key]) <= index:
                        result[key].append({})
                    if is_last:
                        result[key][index] = source[key][index]
                    else:
                        FieldSelector._extract_parts(
                            source[key][index],
                            parts,
                            result[key][index],
                            full_parts,
                            current_depth + 1,
                        )
            return

        # Handle simple key
        if isinstance(source, dict) and part in source:
            if not isinstance(result, dict):
                return
            if is_last:
                # Last part: copy value
                result[part] = source[part]
            else:
                # More parts: recurse
                if part not in result:
                    result[part] = {}
                FieldSelector._extract_parts(source[part], parts, result[part], full_parts, current_depth + 1)

    @staticmethod
    def _merge_path(target: dict[str, Any], source: dict[str, Any], path: str):
        """Merge a single path from source into target."""
        parts = FieldSelector._parse_path(path)
        FieldSelector._merge_parts(target, source, parts, 0)

    @staticmethod
    def _merge_parts(target: Any, source: Any, parts: list[str], current_depth: int):
        """Recursively merge parts from source into target."""
        if current_depth >= len(parts):
            return

        part = parts[current_depth]
        is_last = current_depth == len(parts) - 1

        # Handle array wildcard
        match = re.match(r"^(.+)\[\*\]$", part)
        if match:
            key = match.group(1)
            if isinstance(source, dict) and key in source and isinstance(target, dict) and key in target:
                if isinstance(source[key], list) and isinstance(target[key], list):
                    # Merge each array element
                    for i, item in enumerate(source[key]):
                        if i < len(target[key]):
                            if is_last:
                                target[key][i] = item
                            else:
                                FieldSelector._merge_parts(target[key][i], item, parts, current_depth + 1)
            return

        # Handle array index
        match2 = re.match(r"^(.+)\[(\d+)\]$", part)
        if match2:
            key = match2.group(1)
            index = int(match2.group(2))
            if isinstance(source, dict) and key in source and isinstance(target, dict) and key in target:
                if isinstance(source[key], list) and isinstance(target[key], list) and len(source[key]) > index and len(target[key]) > index:
                    if is_last:
                        target[key][index] = source[key][index]
                    else:
                        FieldSelector._merge_parts(target[key][index], source[key][index], parts, current_depth + 1)
            return

        # Handle simple key
        if isinstance(source, dict) and part in source and isinstance(target, dict):
            if is_last:
                target[part] = source[part]
            else:
                if part not in target:
                    target[part] = {}
                FieldSelector._merge_parts(target[part], source[part], parts, current_depth + 1)

    @staticmethod
    def _parse_path(path: str) -> list[str]:
        """Parse a dot-notation path into parts.

        Handles array notation like args.customers[0].email or args.items[*].name.

        Examples:
            >>> FieldSelector._parse_path("args.query")
            ['args', 'query']
            >>> FieldSelector._parse_path("args.customers[0].email")
            ['args', 'customers[0]', 'email']
            >>> FieldSelector._parse_path("args.items[*].name")
            ['args', 'items[*]', 'name']
        """
        # Split by dots, but keep array notation with the key
        # e.g., "args.customers[0].email" -> ["args", "customers[0]", "email"]
        parts = []
        current = ""
        in_bracket = False

        for char in path:
            if char == "[":
                in_bracket = True
                current += char
            elif char == "]":
                in_bracket = False
                current += char
            elif char == "." and not in_bracket:
                if current:
                    parts.append(current)
                current = ""
            else:
                current += char

        if current:
            parts.append(current)

        return parts
