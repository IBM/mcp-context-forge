#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright (c) 2025 IBM
"""JSON compatibility module for Python 3.14 free-threaded support.

This module provides a compatibility layer for JSON serialization that works
with both orjson (when available) and the standard json library (fallback).

orjson doesn't support free-threaded Python (cp314t) yet, so we fall back
to the standard json library in that case.
"""

# Standard
from typing import Any

# Try to import orjson, fall back to standard json
try:
    # Third-Party
    import orjson

    ORJSON_AVAILABLE = True

    def dumps(obj: Any, **kwargs: Any) -> bytes:
        """Serialize object to JSON bytes using orjson."""
        return orjson.dumps(obj, **kwargs)

    def loads(data: bytes | str) -> Any:
        """Deserialize JSON data using orjson."""
        return orjson.loads(data)

    # Re-export orjson constants and exceptions
    OPT_INDENT_2 = orjson.OPT_INDENT_2
    OPT_SORT_KEYS = orjson.OPT_SORT_KEYS
    OPT_SERIALIZE_NUMPY = getattr(orjson, "OPT_SERIALIZE_NUMPY", 0)
    OPT_OMIT_MICROSECONDS = getattr(orjson, "OPT_OMIT_MICROSECONDS", 0)
    OPT_NON_STR_KEYS = getattr(orjson, "OPT_NON_STR_KEYS", 0)
    JSONDecodeError = orjson.JSONDecodeError

except ImportError:
    # Standard
    import json

    ORJSON_AVAILABLE = False

    # Define dummy option constants (ignored in fallback mode)
    OPT_INDENT_2 = 0
    OPT_SORT_KEYS = 0
    OPT_SERIALIZE_NUMPY = 0
    OPT_OMIT_MICROSECONDS = 0
    OPT_NON_STR_KEYS = 0
    JSONDecodeError = json.JSONDecodeError  # type: ignore[misc]

    def dumps(obj: Any, **kwargs: Any) -> bytes:
        """Serialize object to JSON bytes using standard json library.

        Note: orjson options are ignored in fallback mode.
        """
        # Extract orjson-specific options and map to json equivalents
        option = kwargs.pop("option", 0)
        default = kwargs.pop("default", None)

        # Map orjson options to json parameters
        indent = 2 if option & OPT_INDENT_2 else None
        sort_keys = bool(option & OPT_SORT_KEYS)

        return json.dumps(obj, indent=indent, sort_keys=sort_keys, default=default).encode("utf-8")

    def loads(data: bytes | str) -> Any:
        """Deserialize JSON data using standard json library."""
        if isinstance(data, bytes):
            data = data.decode("utf-8")
        return json.loads(data)


__all__ = [
    "ORJSON_AVAILABLE",
    "dumps",
    "loads",
    "OPT_INDENT_2",
    "OPT_SORT_KEYS",
    "OPT_SERIALIZE_NUMPY",
    "OPT_OMIT_MICROSECONDS",
    "OPT_NON_STR_KEYS",
    "JSONDecodeError",
]
