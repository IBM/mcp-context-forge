# -*- coding: utf-8 -*-
"""Location: ./plugins/toon_encoder/toon.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

TOON (Token-Oriented Object Notation) Encoder/Decoder.

Pure Python implementation of TOON format specification v3.0.
https://github.com/toon-format/spec

TOON is a compact, human-readable encoding of the JSON data model designed
specifically for LLM prompts. It provides lossless serialization of JSON
objects, arrays, and primitives in a syntax that minimizes tokens.

Token Reduction Strategies:
1. Eliminates quotation marks around keys and simple string values
2. Uses compact array syntax: key[N]: val1,val2,val3
3. Uses columnar format for homogeneous object arrays
4. Removes colons/commas where context makes them unnecessary

Examples:
    >>> from plugins.toon_encoder.toon import encode, decode
    >>> data = {"name": "alice", "age": 30}
    >>> toon = encode(data)
    >>> toon
    'name: alice\\nage: 30'
    >>> decode(toon) == data
    True

    >>> arr = [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
    >>> print(encode(arr))
    [2]{id,name}:
      1,a
      2,b
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple


# =============================================================================
# Constants and Patterns
# =============================================================================

# Reserved words that must be quoted if used as string values
_RESERVED_WORDS = frozenset({"null", "true", "false"})

# Characters that require string quoting (excluding control chars handled separately)
_SPECIAL_CHARS_RE = re.compile(r'[\n\r\t,:\[\]{}"\\\-]')

# Pattern to detect if string looks like a number (full match for encoding)
_NUMBER_LIKE_RE = re.compile(r'^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?$')

# Pattern for leading zeros (must be quoted per spec)
_LEADING_ZEROS_RE = re.compile(r'^0\d+$')

# Pattern to match number at start of string (partial match for decoding)
_NUMBER_PREFIX_RE = re.compile(r'^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?')

# Pattern for parsing TOON array header: key[N] or [N] or [N]{key1,key2}
# Key can be: unquoted (word chars + dots), or quoted (with escaped quotes inside)
# Don't consume whitespace after colon - preserve indentation for list item parsing
_ARRAY_HEADER_RE = re.compile(r'^(?:([A-Za-z_][A-Za-z0-9_.]*|"(?:[^"\\]|\\.)*"))?\[(\d+)\](?:\{([^}]*)\})?:')

# Pattern for simple key: value lines
_KEY_VALUE_RE = re.compile(r'^([^:\s]+):\s*(.*)$')

# Pattern for valid unquoted keys per TOON spec: ^[A-Za-z_][A-Za-z0-9_.]*$
_VALID_KEY_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_.]*$')

# Default indent size (2 spaces per spec recommendation)
_INDENT_SIZE = 2


# =============================================================================
# Encoder
# =============================================================================


def encode(obj: Any, *, indent: int = 0, _as_root: bool = True) -> str:
    """Encode a Python object to TOON format.

    Args:
        obj: Python object to encode (dict, list, str, int, float, bool, None).
        indent: Current indentation level (internal use).
        _as_root: Whether this is the root object (internal use).

    Returns:
        TOON-formatted string representation.

    Raises:
        TypeError: If object type is not JSON-serializable.

    Examples:
        >>> encode(None)
        'null'
        >>> encode(True)
        'true'
        >>> encode(42)
        '42'
        >>> encode(3.14)
        '3.14'
        >>> encode("hello")
        'hello'
        >>> encode("hello world")
        'hello world'
        >>> encode("with,comma")
        '"with,comma"'
        >>> encode({"key": "value"})
        'key: value'
        >>> encode([1, 2, 3])
        '[3]: 1,2,3'
    """
    if obj is None:
        return "null"
    if isinstance(obj, bool):
        return "true" if obj else "false"
    if isinstance(obj, int):
        return str(obj)
    if isinstance(obj, float):
        return _encode_float(obj)
    if isinstance(obj, str):
        return _encode_string(obj)
    if isinstance(obj, (list, tuple)):
        return _encode_array(list(obj), indent=indent, _as_root=_as_root)
    if isinstance(obj, dict):
        return _encode_object(obj, indent=indent, _as_root=_as_root)

    # Fallback for other types - convert to string
    raise TypeError(f"Object of type {type(obj).__name__} is not TOON serializable")


def _encode_float(obj: float) -> str:
    """Encode a float value per TOON spec.

    Args:
        obj: Float to encode.

    Returns:
        TOON float representation.
    """
    # Handle special float values - per TOON spec, these must be null
    if obj != obj:  # NaN
        return "null"
    if obj == float("inf") or obj == float("-inf"):
        return "null"
    # Normalize -0 to 0 per spec
    if obj == 0.0:
        return "0"
    # Avoid trailing .0 for whole numbers
    if obj.is_integer():
        return str(int(obj))
    # Per spec: no exponent notation, emit full decimal
    formatted = f"{obj:.15g}"
    if "e" in formatted.lower():
        # Fall back to full decimal representation
        formatted = f"{obj:.15f}".rstrip("0").rstrip(".")
    return formatted


def _needs_quotes(s: str) -> bool:
    """Determine if a string value needs to be quoted in TOON.

    Per TOON spec, strings need quotes if they:
    - Are empty
    - Match reserved words (null, true, false)
    - Contain special characters (newlines, commas, colons, brackets, quotes, backslash)
    - Look like numbers
    - Have leading zeros (e.g., "05")
    - Start with hyphen (e.g., "-a" or "-")
    - Start/end with whitespace

    Args:
        s: String to check.

    Returns:
        True if string needs quoting.

    Examples:
        >>> _needs_quotes("")
        True
        >>> _needs_quotes("null")
        True
        >>> _needs_quotes("hello")
        False
        >>> _needs_quotes("hello world")
        False
        >>> _needs_quotes("has,comma")
        True
        >>> _needs_quotes("123")
        True
        >>> _needs_quotes("05")
        True
        >>> _needs_quotes("-a")
        True
        >>> _needs_quotes("-")
        True
        >>> _needs_quotes(" leading")
        True
    """
    if not s:
        return True
    if s in _RESERVED_WORDS:
        return True
    if _SPECIAL_CHARS_RE.search(s):
        return True
    if _NUMBER_LIKE_RE.match(s):
        return True
    # Per spec: leading zeros must be quoted
    if _LEADING_ZEROS_RE.match(s):
        return True
    # Per spec: strings starting with hyphen must be quoted
    if s[0] == "-":
        return True
    if s[0].isspace() or s[-1].isspace():
        return True
    # Check for control characters
    if any(ord(c) < 32 for c in s):
        return True
    return False


def _encode_string(s: str) -> str:
    """Encode a string value, quoting only when necessary.

    Args:
        s: String to encode.

    Returns:
        TOON string representation.

    Examples:
        >>> _encode_string("simple")
        'simple'
        >>> _encode_string("with space")
        'with space'
        >>> _encode_string("has\\nnewline")
        '"has\\\\nnewline"'
        >>> _encode_string("")
        '""'
    """
    if not _needs_quotes(s):
        return s
    return _quote_string(s)


def _quote_string(s: str) -> str:
    """Quote and escape a string unconditionally.

    Per TOON spec, only these escapes are valid: \\\\ \\\" \\n \\r \\t
    Control characters that can't be escaped must cause the string to be skipped.

    Args:
        s: String to quote.

    Returns:
        Quoted string with escapes applied.

    Raises:
        ValueError: If string contains unencodable control characters.
    """
    result = ['"']
    for char in s:
        if char == "\\":
            result.append("\\\\")
        elif char == '"':
            result.append('\\"')
        elif char == "\n":
            result.append("\\n")
        elif char == "\r":
            result.append("\\r")
        elif char == "\t":
            result.append("\\t")
        elif ord(char) < 32:
            # Per TOON spec, only the above escapes are valid
            # Control characters that can't be escaped should cause an error
            raise ValueError(f"Cannot encode control character U+{ord(char):04X} in TOON")
        else:
            result.append(char)
    result.append('"')
    return "".join(result)


def _encode_key(key: str) -> str:
    """Encode an object key.

    Per TOON spec, unquoted keys must match: ^[A-Za-z_][A-Za-z0-9_.]*$

    Args:
        key: Object key to encode.

    Returns:
        TOON key representation.

    Examples:
        >>> _encode_key("simple")
        'simple'
        >>> _encode_key("has space")
        '"has space"'
        >>> _encode_key("with:colon")
        '"with:colon"'
    """
    # Per TOON spec, unquoted keys must match ^[A-Za-z_][A-Za-z0-9_.]*$
    if key and _VALID_KEY_RE.match(key) and key not in _RESERVED_WORDS:
        return key
    # Key needs quoting
    return _quote_string(key)


def _encode_array(arr: List[Any], *, indent: int = 0, _as_root: bool = True, key_prefix: str = "") -> str:
    """Encode an array in TOON format.

    Per TOON spec:
    - Empty arrays: key[0]: or [0]: at root
    - Primitive arrays: key[N]: val1,val2,val3 or [N]: val1,val2,val3
    - Columnar arrays: key[N]{f1,f2}: followed by rows
    - Mixed/complex arrays: Use list item syntax with - prefix

    Args:
        arr: Array to encode.
        indent: Current indentation level.
        _as_root: Whether this is the root array (unused, for API consistency).
        key_prefix: Key name to prefix (for arrays in objects).

    Returns:
        TOON array representation.

    Examples:
        >>> _encode_array([])
        '[0]:'
        >>> _encode_array([1, 2, 3])
        '[3]: 1,2,3'
    """
    prefix = key_prefix if key_prefix else ""

    if not arr:
        return f"{prefix}[0]:"

    # Check if all elements are dicts with same keys (columnar opportunity)
    if len(arr) >= 1 and all(isinstance(item, dict) for item in arr):
        columnar = _try_columnar_encoding(arr, indent=indent, key_prefix=key_prefix)
        if columnar is not None:
            return columnar

    # Check if elements are simple (no nested structures)
    if all(_is_simple_value(item) for item in arr):
        encoded_items = [encode(item, indent=indent, _as_root=False) for item in arr]
        return f"{prefix}[{len(arr)}]: " + ",".join(encoded_items)

    # Complex array - use list item syntax with - prefix
    lines = [f"{prefix}[{len(arr)}]:"]
    child_ind = " " * (_INDENT_SIZE * (indent + 1))
    for item in arr:
        if _is_simple_value(item):
            lines.append(f"{child_ind}- {encode(item, indent=indent+1, _as_root=False)}")
        elif isinstance(item, dict):
            if not item:
                # Empty object as list item is just -
                lines.append(f"{child_ind}-")
            else:
                # Object as list item
                obj_lines = _encode_object_as_list_item(item, indent=indent + 1)
                lines.extend(obj_lines)
        elif isinstance(item, list):
            # Nested array as list item
            nested = _encode_array(item, indent=indent + 2, _as_root=False, key_prefix="")
            nested_lines = nested.split("\n")
            lines.append(f"{child_ind}- {nested_lines[0]}")
            for nl in nested_lines[1:]:
                lines.append(f"{child_ind}  {nl}")
        else:
            lines.append(f"{child_ind}- {encode(item, indent=indent+1, _as_root=False)}")
    return "\n".join(lines)


def _encode_object_as_list_item(obj: Dict[str, Any], indent: int) -> List[str]:
    """Encode an object as a list item with - prefix.

    Per TOON spec §10:
    - First field may appear on hyphen line
    - If first field is a columnar array, emit "- key[N]{fields}:" on hyphen line

    Args:
        obj: Dictionary to encode.
        indent: Current indentation level.

    Returns:
        List of lines.
    """
    lines = []
    ind = " " * (_INDENT_SIZE * indent)
    field_ind = " " * (_INDENT_SIZE * (indent + 1))

    items = list(obj.items())
    for i, (key, value) in enumerate(items):
        encoded_key = _encode_key(key)

        if isinstance(value, list) and value:
            # Check if this is a columnar array (first field on hyphen line per §10)
            if i == 0:
                columnar = _try_columnar_encoding(value, indent=0, key_prefix="")
                if columnar is not None:
                    # Emit columnar header on hyphen line: - key[N]{fields}:
                    # Extract header and rows from columnar encoding
                    columnar_lines = columnar.split("\n")
                    header = columnar_lines[0]  # [N]{fields}:
                    rows = columnar_lines[1:]
                    lines.append(f"{ind}- {encoded_key}{header}")
                    for row in rows:
                        lines.append(f"{field_ind}  {row.strip()}")
                    continue

            # Non-columnar array or not first field
            if i == 0:
                lines.append(f"{ind}- {encoded_key}:")
            else:
                lines.append(f"{field_ind}{encoded_key}:")
            encoded_value = encode(value, indent=indent + 2, _as_root=False)
            for vline in encoded_value.split("\n"):
                lines.append(f"{field_ind}  {vline}")

        elif isinstance(value, dict) and value:
            # Nested object - put on separate lines
            if i == 0:
                lines.append(f"{ind}- {encoded_key}:")
            else:
                lines.append(f"{field_ind}{encoded_key}:")

            encoded_value = encode(value, indent=indent + 2, _as_root=False)
            for vline in encoded_value.split("\n"):
                lines.append(f"{field_ind}  {vline}")
        else:
            encoded_value = encode(value, indent=indent + 1, _as_root=False)
            if i == 0:
                lines.append(f"{ind}- {encoded_key}: {encoded_value}")
            else:
                lines.append(f"{field_ind}{encoded_key}: {encoded_value}")

    return lines


def _is_simple_value(obj: Any) -> bool:
    """Check if value is simple (not nested dict/list).

    Args:
        obj: Value to check.

    Returns:
        True if value is a primitive type.
    """
    return obj is None or isinstance(obj, (bool, int, float, str))


def _try_columnar_encoding(arr: List[Dict[str, Any]], *, indent: int = 0, key_prefix: str = "") -> Optional[str]:
    """Try to encode array of objects in columnar format.

    Per TOON spec:
    - All objects must have identical key sets
    - All values must be primitives
    - Field order follows first object's key encounter order

    Args:
        arr: Array of dictionaries.
        indent: Current indentation level.
        key_prefix: Key name prefix for the array.

    Returns:
        Columnar TOON string, or None if not suitable.

    Examples:
        >>> result = _try_columnar_encoding([{"a": 1, "b": 2}, {"a": 3, "b": 4}])
        >>> print(result)
        [2]{a,b}:
          1,2
          3,4
    """
    if not arr:
        return None

    # Get keys from first object - preserve encounter order per spec
    first_keys = list(arr[0].keys())
    if not first_keys:
        return None

    first_keys_set = set(first_keys)

    # Check all objects have same keys
    for obj in arr[1:]:
        if set(obj.keys()) != first_keys_set:
            return None

    # Check all values are simple (columnar doesn't work well with nested)
    for obj in arr:
        if not all(_is_simple_value(v) for v in obj.values()):
            return None

    # Build columnar format with encounter order (not sorted)
    prefix = key_prefix if key_prefix else ""
    header = f"{prefix}[{len(arr)}]" + "{" + ",".join(first_keys) + "}:"

    # Rows indented one level below header (2 spaces)
    # Note: Don't include outer indentation here - caller handles that
    row_ind = " " * _INDENT_SIZE
    rows = []
    for obj in arr:
        row_values = [encode(obj[k], indent=0, _as_root=False) for k in first_keys]
        rows.append(f"{row_ind}{','.join(row_values)}")

    return header + "\n" + "\n".join(rows)


def _encode_object(obj: Dict[str, Any], *, indent: int = 0, _as_root: bool = True) -> str:
    """Encode an object (dict) in TOON format.

    Per TOON spec:
    - Empty object at root: empty document (no output)
    - Empty object as field: key: with no value
    - Arrays in objects use key[N]: format

    Args:
        obj: Dictionary to encode.
        indent: Current indentation level.
        _as_root: Whether this is the root object (unused, for API consistency).

    Returns:
        TOON object representation.

    Examples:
        >>> _encode_object({})
        ''
        >>> _encode_object({"a": 1})
        'a: 1'
        >>> print(_encode_object({"a": 1, "b": 2}))
        a: 1
        b: 2
    """
    # Per spec: empty object at root is empty document
    if not obj:
        return ""

    lines = []
    for key, value in obj.items():
        encoded_key = _encode_key(key)

        if isinstance(value, list):
            # Arrays use key[N]: format per spec
            arr_encoded = _encode_array(value, indent=indent, _as_root=False, key_prefix=encoded_key)
            lines.append(arr_encoded)
        elif isinstance(value, dict):
            if not value:
                # Empty nested object: key: with nothing after
                lines.append(f"{encoded_key}:")
            else:
                # Nested object
                lines.append(f"{encoded_key}:")
                encoded_value = _encode_object(value, indent=indent + 1, _as_root=False)
                for vline in encoded_value.split("\n"):
                    lines.append(f"{' ' * _INDENT_SIZE}{vline}")
        else:
            encoded_value = encode(value, indent=indent, _as_root=False)
            lines.append(f"{encoded_key}: {encoded_value}")

    return "\n".join(lines)


# =============================================================================
# Decoder
# =============================================================================


def decode(toon_str: str) -> Any:
    """Decode a TOON string back to Python objects.

    Args:
        toon_str: TOON-formatted string.

    Returns:
        Decoded Python object.

    Raises:
        ValueError: If TOON string is malformed.

    Examples:
        >>> decode("null")
        >>> decode("true")
        True
        >>> decode("false")
        False
        >>> decode("42")
        42
        >>> decode("3.14")
        3.14
        >>> decode("hello")
        'hello'
        >>> decode('"quoted"')
        'quoted'
        >>> decode("[3]: 1,2,3")
        [1, 2, 3]
        >>> decode("key: value")
        {'key': 'value'}
    """
    toon_str = toon_str.strip()

    # Per spec: empty document is empty object
    if not toon_str:
        return {}

    # Try primitives first
    primitive = _try_decode_primitive(toon_str)
    if primitive is not None:
        return primitive[0]

    # Check if this is an object with multiple fields at root level
    # (as opposed to a single array)
    if _looks_like_object(toon_str):
        return _decode_object(toon_str)

    # Try array (with or without key prefix)
    if toon_str.startswith("[") or _ARRAY_HEADER_RE.match(toon_str):
        return _decode_array(toon_str)

    # Try object (key: value format)
    if ":" in toon_str:
        return _decode_object(toon_str)

    # Unquoted string
    return toon_str


def _looks_like_object(s: str) -> bool:
    """Determine if string looks like a TOON object with multiple fields.

    This helps disambiguate between an array-as-object-field like:
        items[5]: 1,2,3
        name: test
    vs a standalone array like:
        [5]: 1,2,3,4,5

    Args:
        s: TOON string to check.

    Returns:
        True if string appears to be an object with multiple fields.
    """
    lines = s.split("\n")
    root_level_keys = 0

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Check if line starts at root level (no leading whitespace in original)
        if line and not line[0].isspace():
            # Check if it looks like a key: value or key[N]: line
            if ":" in stripped:
                root_level_keys += 1
                if root_level_keys > 1:
                    return True

    # Also consider it an object if it has key[N]: format with key name
    # at root level (vs just [N]:)
    first_line = lines[0].strip() if lines else ""
    arr_match = _ARRAY_HEADER_RE.match(first_line)
    if arr_match and arr_match.group(1) and root_level_keys >= 1:
        # Has a key prefix like "items[5]:" - this is an object field
        return True

    return False


def _try_decode_primitive(s: str) -> Optional[Tuple[Any, str]]:
    """Try to decode a primitive value from start of string.

    Args:
        s: String to parse.

    Returns:
        Tuple of (decoded_value, remaining_string) or None.

    Examples:
        >>> _try_decode_primitive("null")
        (None, '')
        >>> _try_decode_primitive("true")
        (True, '')
        >>> _try_decode_primitive("42")
        (42, '')
        >>> _try_decode_primitive("3.14")
        (3.14, '')
    """
    s = s.strip()

    # Null
    if s == "null" or s.startswith("null,") or s.startswith("null\n"):
        return (None, s[4:].lstrip(",\n "))

    # Boolean
    if s == "true" or s.startswith("true,") or s.startswith("true\n"):
        return (True, s[4:].lstrip(",\n "))
    if s == "false" or s.startswith("false,") or s.startswith("false\n"):
        return (False, s[5:].lstrip(",\n "))

    # Quoted string
    if s.startswith('"'):
        return _decode_quoted_string(s)

    # Number - use partial matching pattern to extract number from start
    match = _NUMBER_PREFIX_RE.match(s)
    if match:
        num_str = match.group()
        # Check that what follows is a delimiter or end of string
        rest = s[len(num_str):]
        if not rest or rest[0] in ",\n :]}":
            remaining = rest.lstrip(",\n ")
            if "." in num_str or "e" in num_str.lower():
                return (float(num_str), remaining)
            return (int(num_str), remaining)

    return None


def _decode_quoted_string(s: str) -> Tuple[str, str]:
    """Decode a quoted string from TOON.

    Per TOON spec, only these escapes are valid: \\\\ \\\" \\n \\r \\t
    Any other escape sequence must be rejected.

    Args:
        s: String starting with quote.

    Returns:
        Tuple of (decoded_string, remaining_string).

    Raises:
        ValueError: If string is malformed or contains invalid escapes.

    Examples:
        >>> _decode_quoted_string('"hello"')
        ('hello', '')
        >>> _decode_quoted_string('"with\\\\nescapes"')
        ('with\\nescapes', '')
    """
    if not s.startswith('"'):
        raise ValueError("Expected quoted string")

    result = []
    i = 1
    while i < len(s):
        char = s[i]
        if char == '"':
            return ("".join(result), s[i + 1:].lstrip(",\n "))
        if char == "\\":
            if i + 1 >= len(s):
                raise ValueError("Unterminated escape sequence")
            next_char = s[i + 1]
            if next_char == "n":
                result.append("\n")
            elif next_char == "r":
                result.append("\r")
            elif next_char == "t":
                result.append("\t")
            elif next_char == "\\":
                result.append("\\")
            elif next_char == '"':
                result.append('"')
            else:
                # Per spec: reject invalid escape sequences
                raise ValueError(f"Invalid escape sequence: \\{next_char}")
            i += 2
        else:
            result.append(char)
            i += 1

    raise ValueError("Unterminated string")


def _decode_array(s: str) -> List[Any]:
    """Decode a TOON array.

    Args:
        s: TOON array string starting with '[' or key[.

    Returns:
        Decoded Python list.

    Examples:
        >>> _decode_array("[0]:")
        []
        >>> _decode_array("[3]: 1,2,3")
        [1, 2, 3]
        >>> _decode_array("[2]{x,y}:\\n  1,2\\n  3,4")
        [{'x': 1, 'y': 2}, {'x': 3, 'y': 4}]
    """
    match = _ARRAY_HEADER_RE.match(s)
    if not match:
        raise ValueError(f"Invalid array format: {s[:50]}")

    # key_name = match.group(1)  # May be None for root arrays
    count = int(match.group(2))
    keys_str = match.group(3)
    # Get remaining content, preserving indentation
    remaining = s[match.end():]
    # Strip just the leading space/newline after colon (": " or ":\n")
    if remaining.startswith(" "):
        remaining = remaining[1:]
    elif remaining.startswith("\n"):
        remaining = remaining[1:]
    remaining_stripped = remaining.strip()

    if count == 0:
        return []

    # Columnar format with keys
    if keys_str:
        # Detect delimiter from header (comma, pipe, or tab per spec)
        delimiter = _detect_delimiter(keys_str)
        keys = [k.strip() for k in keys_str.split(delimiter)]
        return _decode_columnar_array(remaining_stripped, count, keys, delimiter)

    # Check for list item syntax (lines starting with -)
    if remaining_stripped.startswith("-") or "\n-" in remaining or "\n -" in remaining:
        return _decode_list_item_array(remaining, count)

    # Simple array format
    return _decode_simple_array(remaining_stripped, count)


def _decode_list_item_array(s: str, count: int) -> List[Any]:
    """Decode array using list item syntax (- prefix).

    Per TOON spec §9.4/§10, list items can be:
    - Simple values: - value
    - Empty objects: -
    - Object with first field: - key: value
    - Nested arrays: - [N]: values

    Args:
        s: Array content with list items.
        count: Expected number of elements.

    Returns:
        Decoded list.
    """
    result = []
    lines = s.split("\n")
    i = 0

    while i < len(lines) and len(result) < count:
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue

        # Find the base indentation of this list item
        item_indent = len(line) - len(line.lstrip())

        if stripped.startswith("- "):
            item_content = stripped[2:]

            # Check if this is a standalone array (no key prefix)
            if item_content.startswith("["):
                result.append(_decode_array(item_content))
                i += 1
            # Check if this is an object field (key: value or key[N]: per §10)
            elif ":" in item_content:
                # This is an object list item - gather all lines at item_indent + 2 or more
                obj_lines = [item_content]
                i += 1
                child_indent = item_indent + _INDENT_SIZE
                while i < len(lines):
                    next_line = lines[i]
                    if not next_line.strip():
                        i += 1
                        continue
                    next_indent = len(next_line) - len(next_line.lstrip())
                    # Stop if we hit another list item at same level or less indentation
                    if next_indent <= item_indent:
                        break
                    # Add the content with adjusted indentation
                    if next_indent >= child_indent:
                        obj_lines.append(next_line[child_indent:] if len(next_line) >= child_indent else next_line.strip())
                    i += 1
                # Decode the object
                obj_text = "\n".join(obj_lines)
                result.append(_decode_object(obj_text))
            else:
                # Simple value
                primitive = _try_decode_primitive(item_content)
                if primitive is not None:
                    result.append(primitive[0])
                else:
                    result.append(item_content)
                i += 1
        elif stripped == "-":
            # Empty object
            result.append({})
            i += 1
        else:
            # Unexpected line, skip
            i += 1

    return result


def _decode_simple_array(s: str, count: int) -> List[Any]:
    """Decode a simple (non-columnar) TOON array.

    Args:
        s: Array content after header.
        count: Expected number of elements.

    Returns:
        Decoded list.
    """
    if not s:
        return []

    result = []
    remaining = s

    for _ in range(count):
        if not remaining:
            break

        remaining = remaining.strip()

        # Try to parse a value
        primitive = _try_decode_primitive(remaining)
        if primitive is not None:
            result.append(primitive[0])
            remaining = primitive[1]
        elif remaining.startswith("["):
            # Nested array - find matching bracket
            nested, remaining = _extract_nested_structure(remaining, "[", "]")
            result.append(_decode_array(nested))
        elif remaining.startswith("{"):
            # Nested object
            nested, remaining = _extract_nested_structure(remaining, "{", "}")
            result.append(_decode_object(nested))
        else:
            # Unquoted string - read until comma or newline
            end = len(remaining)
            for i, c in enumerate(remaining):
                if c in ",\n":
                    end = i
                    break
            value = remaining[:end].strip()
            result.append(value if value else None)
            remaining = remaining[end:].lstrip(",\n ")

    return result


def _detect_delimiter(keys_str: str) -> str:
    """Detect the delimiter used in columnar array header.

    Per TOON spec v3.0, columnar headers can use comma, pipe, or tab as delimiter.

    Args:
        keys_str: The keys portion of the header (e.g., "a,b" or "a|b" or "a\\tb").

    Returns:
        The detected delimiter character.
    """
    # Check for pipe first (more specific)
    if "|" in keys_str:
        return "|"
    # Check for tab
    if "\t" in keys_str:
        return "\t"
    # Default to comma
    return ","


def _decode_columnar_array(s: str, count: int, keys: List[str], delimiter: str = ",") -> List[Dict[str, Any]]:
    """Decode a columnar TOON array.

    Args:
        s: Array content (rows).
        count: Expected number of rows.
        keys: Column keys.
        delimiter: The delimiter character used to separate values.

    Returns:
        List of dictionaries.
    """
    result = []
    lines = s.strip().split("\n")

    for line in lines[:count]:
        line = line.strip()
        if not line:
            continue

        values = _split_row_values(line, len(keys), delimiter)
        obj = {}
        for i, key in enumerate(keys):
            if i < len(values):
                # Decode each value
                val_str = values[i].strip()
                primitive = _try_decode_primitive(val_str)
                if primitive is not None:
                    obj[key] = primitive[0]
                else:
                    obj[key] = val_str
            else:
                obj[key] = None
        result.append(obj)

    return result


def _split_row_values(line: str, _expected_count: int, delimiter: str = ",") -> List[str]:
    """Split a columnar row into values, respecting quotes.

    Args:
        line: Row string.
        _expected_count: Expected number of values (unused, for potential validation).
        delimiter: The delimiter character to split on.

    Returns:
        List of value strings.
    """
    values = []
    current = []
    in_quotes = False
    escape = False

    for char in line:
        if escape:
            current.append(char)
            escape = False
        elif char == "\\":
            current.append(char)
            escape = True
        elif char == '"':
            current.append(char)
            in_quotes = not in_quotes
        elif char == delimiter and not in_quotes:
            values.append("".join(current))
            current = []
        else:
            current.append(char)

    if current:
        values.append("".join(current))

    return values


def _decode_object(s: str) -> Dict[str, Any]:
    """Decode a TOON object.

    Args:
        s: TOON object string.

    Returns:
        Decoded Python dictionary.

    Examples:
        >>> _decode_object("")
        {}
        >>> _decode_object("a: 1")
        {'a': 1}
        >>> _decode_object("a: 1\\nb: 2")
        {'a': 1, 'b': 2}
    """
    s = s.strip()
    if not s:
        return {}

    result = {}
    lines = s.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue

        # Check for array header format: key[N]: at base indent
        # Format: key[N]: or key[N]{fields}:
        arr_match = _ARRAY_HEADER_RE.match(stripped)
        if arr_match and arr_match.group(1):
            key = arr_match.group(1)
            # Unquote key if it's quoted
            if key.startswith('"') and key.endswith('"'):
                key = _decode_quoted_string(key)[0]
            # Collect all lines for this array
            arr_lines = [stripped]
            i += 1
            if i < len(lines) and lines[i].strip():
                base_indent = len(lines[i]) - len(lines[i].lstrip())
            else:
                base_indent = 0
            while i < len(lines):
                next_line = lines[i]
                if not next_line.strip():
                    i += 1
                    continue
                next_indent = len(next_line) - len(next_line.lstrip())
                # Stop if we reach a line at base level that's a new key
                if next_indent == 0 and (":" in next_line or _ARRAY_HEADER_RE.match(next_line.strip())):
                    break
                if next_indent < base_indent and next_line.strip():
                    break
                arr_lines.append(next_line)
                i += 1
            result[key] = _decode_array("\n".join(arr_lines))
            continue

        # Parse key: value (or key: for empty value / nested object)
        if ":" in stripped:
            # Find the colon - handle quoted keys
            if stripped.startswith('"'):
                # Quoted key - find end quote then colon
                try:
                    key, rest = _decode_quoted_string(stripped)
                    if rest.startswith(":"):
                        value_str = rest[1:].strip()
                    else:
                        i += 1
                        continue
                except ValueError:
                    i += 1
                    continue
            else:
                colon_idx = stripped.index(":")
                key = stripped[:colon_idx].strip()
                value_str = stripped[colon_idx + 1:].strip()

            # Check if value continues on next lines (indented)
            if not value_str and i + 1 < len(lines):
                # Find base indent from first non-empty line after this one
                base_indent = 0
                for j in range(i + 1, len(lines)):
                    if lines[j].strip():
                        base_indent = len(lines[j]) - len(lines[j].lstrip())
                        break

                # If next non-empty line is at root level, this is an empty value
                if base_indent == 0:
                    result[key] = {}
                    i += 1
                    continue

                # Multi-line value - gather indented lines
                nested_lines = []
                i += 1

                while i < len(lines):
                    next_line = lines[i]
                    if not next_line.strip():
                        nested_lines.append("")
                        i += 1
                        continue
                    next_indent = len(next_line) - len(next_line.lstrip())
                    if next_indent < base_indent:
                        break
                    # Remove the base indentation for nested content
                    if len(next_line) >= base_indent:
                        nested_lines.append(next_line[base_indent:])
                    else:
                        nested_lines.append(next_line.strip())
                    i += 1
                value_str = "\n".join(nested_lines)
                result[key] = decode(value_str)
            else:
                # Single line value
                primitive = _try_decode_primitive(value_str)
                if primitive is not None:
                    result[key] = primitive[0]
                elif value_str.startswith("["):
                    result[key] = _decode_array(value_str)
                else:
                    result[key] = value_str if value_str else {}
                i += 1
        else:
            i += 1

    return result


def _extract_nested_structure(s: str, open_char: str, close_char: str) -> Tuple[str, str]:
    """Extract a nested structure (array or object) from string.

    Args:
        s: String starting with open_char.
        open_char: Opening character ('[' or '{').
        close_char: Closing character (']' or '}').

    Returns:
        Tuple of (nested_content, remaining_string).
    """
    depth = 0
    in_quotes = False
    escape = False

    for i, char in enumerate(s):
        if escape:
            escape = False
            continue
        if char == "\\":
            escape = True
            continue
        if char == '"':
            in_quotes = not in_quotes
            continue
        if in_quotes:
            continue
        if char == open_char:
            depth += 1
        elif char == close_char:
            depth -= 1
            if depth == 0:
                return (s[: i + 1], s[i + 1:].lstrip(",\n "))

    return (s, "")


# =============================================================================
# Utility Functions
# =============================================================================


def estimate_token_savings(json_str: str) -> Tuple[int, int, float]:
    """Estimate token savings from JSON to TOON conversion.

    This is a rough estimate based on byte count, not actual tokenization.
    Actual savings depend on the specific tokenizer used.

    Args:
        json_str: Original JSON string.

    Returns:
        Tuple of (json_bytes, toon_bytes, savings_percent).

    Examples:
        >>> import json
        >>> data = {"users": [{"id": 1, "name": "alice"}, {"id": 2, "name": "bob"}]}
        >>> json_str = json.dumps(data)
        >>> json_len, toon_len, savings = estimate_token_savings(json_str)
        >>> savings > 0
        True
    """
    import json

    try:
        obj = json.loads(json_str)
        toon_str = encode(obj)
        # Use byte length for accurate measurement
        json_len = len(json_str.encode("utf-8"))
        toon_len = len(toon_str.encode("utf-8"))
        savings = ((json_len - toon_len) / json_len) * 100 if json_len > 0 else 0
        return (json_len, toon_len, savings)
    except Exception:
        return (len(json_str), len(json_str), 0.0)
